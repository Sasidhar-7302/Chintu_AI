"""Robustness Middleware - Integrates all reliability components.

Provides a clean facade that wraps command handling with:
- Context awareness (pending requests)
- Error recovery with retries
- Input validation
- Prerequisite checking
- Graceful failure handling
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from chintu_backend.core.context_manager import (
    get_context_manager, 
    ConversationContextManager, 
    PendingType
)
from chintu_backend.core.error_recovery import (
    get_error_recovery, 
    ErrorRecoverySystem,
    RecoverableError,
    with_recovery
)
from chintu_backend.core.validators import (
    get_input_validator, 
    get_prerequisite_checker,
    InputValidator,
    PrerequisiteChecker,
    PrereqStatus
)
from chintu_backend.core.command_parser import (
    get_command_parser,
    SmartCommandParser,
    CommandIntent,
    ParsedCommand
)

logger = logging.getLogger(__name__)


@dataclass
class RobustResponse:
    """Response from the robustness middleware."""
    success: bool
    message: str
    original_input: str
    intent: Optional[CommandIntent] = None
    needs_followup: bool = False
    followup_prompt: Optional[str] = None
    data: Dict[str, Any] = None
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}


class RobustnessMiddleware:
    """Central middleware for making Chintu robust and reliable.
    
    Wraps command handling with:
    1. Context awareness (pending requests, confirmations)
    2. Input validation and clarification
    3. Prerequisite checking
    4. Error recovery with retries
    5. Graceful failure handling
    
    Usage:
        middleware = get_robustness_middleware()
        
        # Before handling a command
        result = middleware.pre_process("open chrome")
        if result.needs_followup:
            return result.followup_prompt  # Ask for clarification
        
        # Handle the command normally
        ...
        
        # After handling, wrap any errors
        result = middleware.wrap_error(exception, "opening chrome")
    """

    def __init__(self):
        self.context_manager = get_context_manager()
        self.error_recovery = get_error_recovery()
        self.validator = get_input_validator()
        self.prereq_checker = get_prerequisite_checker()
        self.command_parser = get_command_parser()
        
        # Register common fallbacks
        self._register_fallbacks()
        
        logger.info("RobustnessMiddleware initialized")

    def _register_fallbacks(self) -> None:
        """Register fallback methods for common operations."""
        # If Docker sandbox fails, use local Python
        self.error_recovery.register_fallback(
            "sandbox_run",
            self._fallback_local_python
        )
        
        # If Ollama fails, use Groq
        self.error_recovery.register_fallback(
            "ollama_query",
            self._fallback_groq
        )
        
        # If browser fails, try system browser
        self.error_recovery.register_fallback(
            "browser_open",
            self._fallback_system_browser
        )

    def pre_process(self, user_input: str) -> RobustResponse:
        """Pre-process user input before command handling.
        
        Handles:
        - Empty/garbage input
        - Pending request resolution
        - Confirmation detection
        - Missing info detection
        - Clarification requests
        
        Args:
            user_input: Raw user input
            
        Returns:
            RobustResponse with processing result
        """
        # Handle empty input
        if not user_input or not user_input.strip():
            return RobustResponse(
                success=False,
                message="I didn't catch that. How can I help you?",
                original_input=user_input or "",
                needs_followup=True,
                followup_prompt="What would you like me to do?",
            )
        
        user_input = user_input.strip()
        
        # Check for pending requests first
        if self.context_manager.has_pending_requests():
            handled, message, result = self.context_manager.process_user_input(user_input)
            
            if handled:
                return RobustResponse(
                    success=True,
                    message=message,
                    original_input=user_input,
                    intent=CommandIntent.CONFIRM if result else CommandIntent.CANCEL,
                    data=result or {},
                )
        
        # Parse the command
        parsed = self.command_parser.parse(user_input)
        
        # Check if clarification needed
        if parsed.clarification_needed:
            return RobustResponse(
                success=True,
                message="",
                original_input=user_input,
                intent=parsed.intent,
                needs_followup=True,
                followup_prompt=parsed.clarification_question,
                data={"parsed": parsed},
            )
        
        # Check if low confidence
        if parsed.confidence < 0.3:
            suggestions = parsed.suggestions[:3] if parsed.suggestions else []
            if suggestions:
                suggestion_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(suggestions))
                prompt = f"I'm not sure what you mean. Did you want to:\n{suggestion_text}"
            else:
                prompt = "I didn't understand that. Could you rephrase?"
            
            return RobustResponse(
                success=False,
                message=prompt,
                original_input=user_input,
                intent=CommandIntent.UNKNOWN,
                needs_followup=True,
                followup_prompt=prompt,
            )
        
        # All good, proceed with processing
        return RobustResponse(
            success=True,
            message="",
            original_input=user_input,
            intent=parsed.intent,
            data={"parsed": parsed, "target": parsed.target, "params": parsed.parameters},
        )

    def check_prerequisites(self, action: str) -> RobustResponse:
        """Check if prerequisites are met for an action.
        
        Args:
            action: Action type (browser, sandbox, voice, llm, vision, file)
            
        Returns:
            RobustResponse indicating if action can proceed
        """
        ok, issues = self.prereq_checker.check_for_action(action)
        
        if ok:
            return RobustResponse(
                success=True,
                message="",
                original_input=action,
            )
        
        # Build helpful error message
        issue_msgs = []
        for issue in issues:
            msg = f"• {issue.name}: {issue.message}"
            if issue.fix_instructions:
                msg += f"\n  Fix: {issue.fix_instructions}"
            issue_msgs.append(msg)
        
        error_message = "Some requirements are missing:\n" + "\n".join(issue_msgs)
        
        # Check if any are auto-fixable
        auto_fixable = [i for i in issues if i.auto_fixable]
        if auto_fixable:
            fix_cmds = [i.fix_command for i in auto_fixable if i.fix_command]
            if fix_cmds:
                # Create pending request for confirmation
                self.context_manager.create_pending_request(
                    request_type=PendingType.CONFIRMATION,
                    prompt=f"I need to fix some issues first. Should I run: {'; '.join(fix_cmds)}?",
                    original_command=action,
                    context={"fix_commands": fix_cmds},
                )
                return RobustResponse(
                    success=False,
                    message=error_message,
                    original_input=action,
                    needs_followup=True,
                    followup_prompt=f"Should I try to fix this automatically?",
                )
        
        return RobustResponse(
            success=False,
            message=error_message,
            original_input=action,
            error="prerequisites_not_met",
        )

    def request_info(
        self, 
        what_is_needed: str, 
        original_command: str,
        required_fields: Optional[List[str]] = None,
    ) -> str:
        """Request missing information from user.
        
        Args:
            what_is_needed: Description of what's needed
            original_command: The original user command
            required_fields: List of field names to collect
            
        Returns:
            The prompt to show the user
        """
        return self.context_manager.request_missing_info(
            what_is_needed,
            original_command,
            required_fields,
        )

    def request_confirmation(
        self,
        action: str,
        original_command: str,
        details: Optional[str] = None,
    ) -> str:
        """Request user confirmation before an action.
        
        Args:
            action: Description of action to confirm
            original_command: Original command
            details: Additional details
            
        Returns:
            The confirmation prompt
        """
        return self.context_manager.request_confirmation(
            action,
            original_command,
            details,
        )

    def request_credential(
        self,
        service: str,
        username: str,
        original_command: str,
    ) -> str:
        """Request a credential from the user.
        
        Args:
            service: Service name (e.g., "GitHub", "OpenAI")
            username: Username or key type
            original_command: Original command
            
        Returns:
            The credential request prompt
        """
        return self.context_manager.request_credential(
            service,
            username,
            original_command,
        )

    def wrap_error(self, exception: Exception, operation: str) -> RobustResponse:
        """Wrap an exception in a user-friendly response.
        
        Args:
            exception: The exception that occurred
            operation: What operation was being performed
            
        Returns:
            RobustResponse with friendly error message
        """
        friendly_message = self.error_recovery.get_friendly_message(exception)
        action, suggestion = self.error_recovery.suggest_recovery(exception, operation)
        
        full_message = f"{friendly_message}\n{suggestion}"
        
        return RobustResponse(
            success=False,
            message=full_message,
            original_input=operation,
            error=str(exception),
        )

    def get_status(self) -> Dict[str, Any]:
        """Get current status of all robustness components."""
        return {
            "context": self.context_manager.get_status(),
            "prerequisites": self.prereq_checker.get_summary(),
            "errors": self.error_recovery.get_error_summary(5),
        }

    # =========================================================================
    # FALLBACK METHODS
    # =========================================================================

    def _fallback_local_python(self, command: str, **kwargs) -> str:
        """Fallback: Run Python locally instead of Docker."""
        import subprocess
        try:
            result = subprocess.run(
                ["python", "-c", command],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout or result.stderr
        except Exception as exc:
            return f"Local execution also failed: {exc}"

    def _fallback_groq(self, prompt: str, **kwargs) -> str:
        """Fallback: Use Groq API instead of Ollama."""
        import os
        import httpx
        
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RecoverableError("Groq API key not configured")
        
        response = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30.0,
        )
        
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        raise RecoverableError(f"Groq API error: {response.status_code}")

    def _fallback_system_browser(self, url: str, **kwargs) -> str:
        """Fallback: Use system browser instead of Playwright."""
        import webbrowser
        webbrowser.open(url)
        return f"Opened {url} in system browser"


# Singleton
_middleware: Optional[RobustnessMiddleware] = None


def get_robustness_middleware() -> RobustnessMiddleware:
    """Get or create the global Robustness Middleware."""
    global _middleware
    if _middleware is None:
        _middleware = RobustnessMiddleware()
    return _middleware


# Convenience functions for common use cases

def check_and_ask(user_input: str) -> Tuple[bool, str, Optional[Dict]]:
    """Quick check if user input needs clarification.
    
    Returns:
        Tuple of (can_proceed, response_message, data)
    """
    middleware = get_robustness_middleware()
    result = middleware.pre_process(user_input)
    
    if result.needs_followup:
        return False, result.followup_prompt or result.message, None
    
    return result.success, result.message, result.data


def safe_execute(operation: str, func: Callable, *args, **kwargs) -> Tuple[bool, Any]:
    """Execute a function with automatic error recovery.
    
    Returns:
        Tuple of (success, result_or_error_message)
    """
    import asyncio
    
    recovery = get_error_recovery()
    
    async def run():
        return await recovery.execute_with_recovery(operation, func, *args, **kwargs)
    
    return asyncio.run(run())


def ensure_prerequisites(action: str) -> Tuple[bool, Optional[str]]:
    """Ensure prerequisites are met for an action.
    
    Returns:
        Tuple of (ok, error_message_if_not_ok)
    """
    middleware = get_robustness_middleware()
    result = middleware.check_prerequisites(action)
    
    if result.success:
        return True, None
    
    return False, result.message
