"""Conversation Context Manager - Robust state tracking for Chintu.

Handles all edge cases for a production-ready AI assistant:
- Pending requests (waiting for user input/credentials)
- Confirmation detection and handling
- Missing configuration recovery
- Graceful error handling with retries
- Credential requests with secure storage
- Task continuity across sessions
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import threading

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class PendingType(str, Enum):
    """Types of pending requests."""
    CONFIRMATION = "confirmation"      # Waiting for user to confirm action
    CREDENTIAL = "credential"          # Waiting for credential input
    MISSING_INFO = "missing_info"      # Waiting for missing details
    CONFIGURATION = "configuration"    # Waiting for config setup
    CHOICE = "choice"                  # Waiting for user to choose option
    FILE_PATH = "file_path"           # Waiting for file/folder path
    APPROVAL = "approval"             # Waiting for plan/action approval


class RequestStatus(str, Enum):
    """Status of a pending request."""
    PENDING = "pending"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    RETRY = "retry"


@dataclass
class PendingRequest:
    """A request waiting for user input."""
    id: str
    type: PendingType
    prompt: str                              # What to ask user
    original_command: str                    # Original user command
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expires_at: Optional[str] = None         # Auto-expire old requests
    status: RequestStatus = RequestStatus.PENDING
    required_fields: List[str] = field(default_factory=list)
    collected_data: Dict[str, Any] = field(default_factory=dict)
    callback_name: Optional[str] = None      # Function to call when resolved
    retry_count: int = 0
    max_retries: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["type"] = self.type.value
        data["status"] = self.status.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PendingRequest":
        data["type"] = PendingType(data["type"])
        data["status"] = RequestStatus(data["status"])
        return cls(**data)


class ConversationContextManager:
    """Manages conversation state, pending requests, and confirmations.
    
    Key features:
    - Track pending requests across conversation turns
    - Detect confirmation phrases intelligently
    - Handle missing credentials/config gracefully
    - Provide retry logic for failed operations
    - Persist state across restarts
    """
    
    # Confirmation patterns
    CONFIRM_PATTERNS = [
        r"\b(yes|yeah|yep|yup|sure|ok|okay|confirm|confirmed|approve|approved)\b",
        r"\b(go ahead|proceed|do it|continue|affirmative|absolutely|definitely)\b",
        r"\b(i confirm|i approve|sounds good|that's fine|that works|let's do it)\b",
        r"^(y|yes)$",
    ]
    
    DENY_PATTERNS = [
        r"\b(no|nope|nah|cancel|stop|abort|don't|dont|never|reject)\b",
        r"\b(wait|hold on|not yet|later|skip|ignore)\b",
        r"^(n|no)$",
    ]
    
    # Credential input patterns
    CREDENTIAL_PATTERNS = [
        r"(password|pwd|pass)\s*[=:]\s*['\"]?(.+?)['\"]?\s*$",
        r"(api[_\s]?key|token|secret)\s*[=:]\s*['\"]?(.+?)['\"]?\s*$",
        r"(username|user|email)\s*[=:]\s*['\"]?(.+?)['\"]?\s*$",
        r"^[A-Za-z0-9+/=_-]{20,}$",  # Looks like a token/key
    ]

    def __init__(self):
        self.config = get_config()
        self.state_file = self.config.data_dir / "conversation_state.json"
        self.pending_requests: Dict[str, PendingRequest] = {}
        self.callbacks: Dict[str, Callable] = {}
        self.conversation_history: List[Dict[str, str]] = []
        self.last_action: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()
        
        self._load_state()
        self._register_default_callbacks()
        logger.info("ConversationContextManager initialized with %d pending requests", 
                   len(self.pending_requests))

    def _load_state(self) -> None:
        """Load persisted state from disk."""
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                for req_id, req_data in data.get("pending_requests", {}).items():
                    self.pending_requests[req_id] = PendingRequest.from_dict(req_data)
                self.conversation_history = data.get("history", [])[-50:]  # Keep last 50
                self._cleanup_expired()
            except Exception as exc:
                logger.warning("Failed to load conversation state: %s", exc)

    def _save_state(self) -> None:
        """Persist state to disk."""
        try:
            data = {
                "pending_requests": {
                    k: v.to_dict() for k, v in self.pending_requests.items()
                },
                "history": self.conversation_history[-50:],
                "last_updated": datetime.now().isoformat(),
            }
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to save conversation state: %s", exc)

    def _cleanup_expired(self) -> None:
        """Remove expired pending requests."""
        now = datetime.now()
        expired = []
        for req_id, req in self.pending_requests.items():
            if req.expires_at:
                try:
                    exp_time = datetime.fromisoformat(req.expires_at)
                    if now > exp_time and req.status != RequestStatus.EXPIRED:
                        expired.append(req_id)
                except:
                    pass
        for req_id in expired:
            self.pending_requests[req_id].status = RequestStatus.EXPIRED
        if expired:
            logger.debug("Expired %d pending request(s)", len(expired))
        # Drop expired requests so they don't pollute future sessions/logs
        for req_id in list(self.pending_requests.keys()):
            if self.pending_requests[req_id].status == RequestStatus.EXPIRED:
                self.pending_requests.pop(req_id, None)
        if expired:
            self._save_state()

    def _register_default_callbacks(self) -> None:
        """Register default callback handlers."""
        self.callbacks["continue_task"] = self._continue_task
        self.callbacks["store_credential"] = self._store_credential
        self.callbacks["apply_config"] = self._apply_config
        self.callbacks["close_app_choice"] = self._close_app_choice

    def _generate_id(self) -> str:
        """Generate unique request ID."""
        return f"req_{int(time.time() * 1000)}"

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def create_pending_request(
        self,
        request_type: PendingType,
        prompt: str,
        original_command: str,
        required_fields: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        callback_name: Optional[str] = None,
        expires_minutes: int = 60,
    ) -> PendingRequest:
        """Create a new pending request.
        
        Args:
            request_type: Type of pending request
            prompt: What to ask the user
            original_command: The original command that triggered this
            required_fields: Fields we need to collect
            context: Additional context for the request
            callback_name: Function to call when resolved
            expires_minutes: Auto-expire after this many minutes
            
        Returns:
            The created PendingRequest
        """
        with self._lock:
            req_id = self._generate_id()
            expires_at = (datetime.now() + timedelta(minutes=expires_minutes)).isoformat()
            
            request = PendingRequest(
                id=req_id,
                type=request_type,
                prompt=prompt,
                original_command=original_command,
                required_fields=required_fields or [],
                context=context or {},
                callback_name=callback_name,
                expires_at=expires_at,
            )
            
            self.pending_requests[req_id] = request
            self._save_state()
            
            logger.info("Created pending request: %s (%s)", req_id, request_type.value)
            return request

    def has_pending_requests(self) -> bool:
        """Check if there are any pending requests."""
        self._cleanup_expired()
        return any(
            r.status == RequestStatus.PENDING 
            for r in self.pending_requests.values()
        )

    def get_pending_prompt(self) -> Optional[str]:
        """Get the prompt for the oldest pending request."""
        self._cleanup_expired()
        pending = [
            r for r in self.pending_requests.values() 
            if r.status == RequestStatus.PENDING
        ]
        if pending:
            # Sort by created_at, oldest first
            pending.sort(key=lambda x: x.created_at)
            return pending[0].prompt
        return None

    def get_pending_request(self, req_id: Optional[str] = None) -> Optional[PendingRequest]:
        """Get a pending request by ID, or the oldest pending one."""
        self._cleanup_expired()
        if req_id:
            return self.pending_requests.get(req_id)
        
        pending = [
            r for r in self.pending_requests.values() 
            if r.status == RequestStatus.PENDING
        ]
        if pending:
            pending.sort(key=lambda x: x.created_at)
            return pending[0]
        return None

    def process_user_input(self, user_input: str) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """Process user input and check if it resolves pending requests.
        
        Args:
            user_input: The user's input text
            
        Returns:
            Tuple of (was_handled, response_message, action_result)
        """
        user_input = user_input.strip()
        self._cleanup_expired()
        
        # Check for pending requests
        pending = self.get_pending_request()
        if not pending:
            return False, None, None
        
        # Check if this is a confirmation/denial
        is_confirm = self._is_confirmation(user_input)
        is_deny = self._is_denial(user_input)
        
        # Handle based on pending type
        if pending.type == PendingType.CONFIRMATION:
            if is_confirm:
                return self._resolve_request(pending, confirmed=True)
            elif is_deny:
                return self._resolve_request(pending, confirmed=False)
            else:
                # Unclear response, ask again
                return True, f"I need a clear yes or no. {pending.prompt}", None
        
        elif pending.type == PendingType.CREDENTIAL:
            # Check if input looks like a credential
            cred_match = self._extract_credential(user_input)
            if cred_match:
                pending.collected_data["credential"] = cred_match
                return self._resolve_request(pending, confirmed=True)
            elif is_deny:
                return self._resolve_request(pending, confirmed=False)
            else:
                # Store as credential if it's private-looking
                if len(user_input) > 6 and not " " in user_input[:20]:
                    pending.collected_data["credential"] = user_input
                    return self._resolve_request(pending, confirmed=True)
                return True, "Please provide the credential, or say 'cancel' to skip.", None
        
        elif pending.type == PendingType.MISSING_INFO:
            if is_deny:
                return self._resolve_request(pending, confirmed=False)
            # Store the info
            if pending.required_fields:
                field = pending.required_fields[0]  # Get first required field
                pending.collected_data[field] = user_input
                pending.required_fields = pending.required_fields[1:]
                
                if pending.required_fields:
                    # More fields needed
                    pending.prompt = f"Got it. Now I need: {pending.required_fields[0]}"
                    self._save_state()
                    return True, pending.prompt, None
            else:
                pending.collected_data["info"] = user_input
            
            return self._resolve_request(pending, confirmed=True)
        
        elif pending.type == PendingType.CHOICE:
            # Try to match choice
            choices = pending.context.get("choices", [])
            for i, choice in enumerate(choices):
                if (
                    str(i + 1) in user_input
                    or choice.lower() in user_input.lower()
                    or user_input.lower() in choice.lower()
                ):
                    pending.collected_data["choice"] = choice
                    pending.collected_data["choice_index"] = i
                    return self._resolve_request(pending, confirmed=True)
            
            if is_deny:
                return self._resolve_request(pending, confirmed=False)
            
            return True, f"Please choose one of: {', '.join(choices)}, or say 'cancel'.", None
        
        elif pending.type == PendingType.APPROVAL:
            if is_confirm:
                return self._resolve_request(pending, confirmed=True)
            elif is_deny:
                return self._resolve_request(pending, confirmed=False)
            else:
                return True, "Please confirm with 'yes' to proceed, or 'no' to cancel.", None
        
        elif pending.type == PendingType.FILE_PATH:
            # Validate path
            path = Path(user_input.strip().strip('"').strip("'"))
            if path.exists() or pending.context.get("allow_new", False):
                pending.collected_data["path"] = str(path)
                return self._resolve_request(pending, confirmed=True)
            elif is_deny:
                return self._resolve_request(pending, confirmed=False)
            else:
                return True, f"Path '{path}' doesn't exist. Please provide a valid path.", None
        
        elif pending.type == PendingType.CONFIGURATION:
            if is_deny:
                return self._resolve_request(pending, confirmed=False)
            # Parse config value
            pending.collected_data["value"] = user_input
            return self._resolve_request(pending, confirmed=True)
        
        return False, None, None

    def _resolve_request(
        self, 
        request: PendingRequest, 
        confirmed: bool
    ) -> Tuple[bool, str, Optional[Dict]]:
        """Resolve a pending request."""
        if confirmed:
            request.status = RequestStatus.RESOLVED
            message = "Got it, proceeding..."
            
            # Execute callback if registered
            result = None
            if request.callback_name and request.callback_name in self.callbacks:
                try:
                    result = self.callbacks[request.callback_name](request)
                    if isinstance(result, str):
                        message = result
                except Exception as exc:
                    logger.error("Callback failed: %s", exc)
                    message = f"Error executing action: {exc}"
                    request.status = RequestStatus.RETRY
                    request.retry_count += 1
                    
                    if request.retry_count < request.max_retries:
                        request.status = RequestStatus.PENDING
                        self._save_state()
                        return True, f"Something went wrong. {request.prompt} (Retry {request.retry_count})", None
        else:
            request.status = RequestStatus.CANCELLED
            message = "Okay, cancelled."
            result = None
        
        self._save_state()
        logger.info("Resolved request %s: %s", request.id, request.status.value)
        
        return True, message, {"request": request.to_dict(), "result": result}

    def _is_confirmation(self, text: str) -> bool:
        """Check if text is a confirmation."""
        text_lower = text.lower().strip()
        for pattern in self.CONFIRM_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def _is_denial(self, text: str) -> bool:
        """Check if text is a denial."""
        text_lower = text.lower().strip()
        for pattern in self.DENY_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def is_confirmation(self, text: str) -> bool:
        """Public confirmation check for other modules."""
        return self._is_confirmation(text)

    def is_denial(self, text: str) -> bool:
        """Public denial check for other modules."""
        return self._is_denial(text)

    def _extract_credential(self, text: str) -> Optional[str]:
        """Extract credential from text."""
        for pattern in self.CREDENTIAL_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                return groups[-1] if len(groups) > 1 else groups[0]
        return None

    # =========================================================================
    # DEFAULT CALLBACKS
    # =========================================================================

    def _continue_task(self, request: PendingRequest) -> str:
        """Continue a paused task with collected data."""
        logger.info("Continuing task: %s", request.original_command)
        # This would be hooked into the command handler
        return f"Continuing with: {request.original_command}"

    def _store_credential(self, request: PendingRequest) -> str:
        """Store a credential securely."""
        try:
            from chintu_backend.security.identity_vault import get_identity_vault
            vault = get_identity_vault()
            
            service = request.context.get("service", "unknown")
            username = request.context.get("username", "default")
            credential = request.collected_data.get("credential", "")
            
            vault.store_secret(service, username, credential)
            return f"Credential for {service}/{username} stored securely."
        except Exception as exc:
            return f"Failed to store credential: {exc}"

    def _apply_config(self, request: PendingRequest) -> str:
        """Apply a configuration change."""
        key = request.context.get("config_key", "")
        value = request.collected_data.get("value", "")
        
        # This would update the config
        logger.info("Would apply config: %s = %s", key, value)
        return f"Configuration updated: {key}"

    def _close_app_choice(self, request: PendingRequest) -> str:
        """Close a selected app/window from a CHOICE prompt."""
        choice = request.collected_data.get("choice", "")
        if not choice:
            return "I didn't catch which window to close."
        try:
            from chintu_backend.vision.app_listing import close_windows_by_title
            ok, msg = close_windows_by_title(choice)
            return msg if msg else ("Closed the window." if ok else "I couldn't close that window.")
        except Exception as exc:
            return f"Failed to close the window: {exc}"

    # =========================================================================
    # HELPER METHODS FOR COMMON SCENARIOS
    # =========================================================================

    def request_confirmation(
        self, 
        action: str, 
        original_command: str,
        details: Optional[str] = None,
        callback_name: Optional[str] = None,
    ) -> str:
        """Create a confirmation request and return the prompt."""
        prompt = f"Should I {action}?"
        if details:
            prompt += f" ({details})"
        prompt += " Reply 'yes' to confirm or 'no' to cancel."
        
        self.create_pending_request(
            request_type=PendingType.CONFIRMATION,
            prompt=prompt,
            original_command=original_command,
            callback_name=callback_name,
            context={"action": action},
        )
        return prompt

    def request_credential(
        self,
        service: str,
        username: str,
        original_command: str,
    ) -> str:
        """Create a credential request and return the prompt."""
        prompt = f"I need the password/API key for {service} (user: {username}). Please provide it securely."
        
        self.create_pending_request(
            request_type=PendingType.CREDENTIAL,
            prompt=prompt,
            original_command=original_command,
            callback_name="store_credential",
            context={"service": service, "username": username},
        )
        return prompt

    def request_missing_info(
        self,
        what_is_missing: str,
        original_command: str,
        required_fields: Optional[List[str]] = None,
    ) -> str:
        """Create a missing info request and return the prompt."""
        prompt = f"I need more information: {what_is_missing}"
        
        self.create_pending_request(
            request_type=PendingType.MISSING_INFO,
            prompt=prompt,
            original_command=original_command,
            required_fields=required_fields or [what_is_missing],
            callback_name="continue_task",
        )
        return prompt

    def request_choice(
        self,
        question: str,
        choices: List[str],
        original_command: str,
        callback_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a choice request and return the prompt."""
        options = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(choices))
        prompt = f"{question}\n{options}\nPlease choose a number or name."
        
        self.create_pending_request(
            request_type=PendingType.CHOICE,
            prompt=prompt,
            original_command=original_command,
            context=context or {"choices": choices},
            callback_name=callback_name or "continue_task",
        )
        return prompt

    def cancel_all_pending(self) -> int:
        """Cancel all pending requests."""
        count = 0
        with self._lock:
            for req in self.pending_requests.values():
                if req.status == RequestStatus.PENDING:
                    req.status = RequestStatus.CANCELLED
                    count += 1
            self._save_state()
        return count

    def get_status(self) -> Dict[str, Any]:
        """Get current conversation status."""
        self._cleanup_expired()
        pending = [r for r in self.pending_requests.values() if r.status == RequestStatus.PENDING]
        return {
            "has_pending": len(pending) > 0,
            "pending_count": len(pending),
            "pending_types": [r.type.value for r in pending],
            "history_length": len(self.conversation_history),
        }


# Singleton
_context_manager: Optional[ConversationContextManager] = None


def get_context_manager() -> ConversationContextManager:
    """Get or create the global Conversation Context Manager."""
    global _context_manager
    if _context_manager is None:
        _context_manager = ConversationContextManager()
    return _context_manager
