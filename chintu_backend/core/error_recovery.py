"""Error Recovery and Graceful Failure System.

Provides robust error handling, retries, and fallback mechanisms
to ensure Chintu never crashes or leaves users hanging.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import traceback
from contextlib import contextmanager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar, Union

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ErrorSeverity(str, Enum):
    """Severity levels for errors."""
    LOW = "low"           # Minor issue, can continue
    MEDIUM = "medium"     # Notable issue, may need attention
    HIGH = "high"         # Serious issue, requires action
    CRITICAL = "critical" # System failure, needs immediate attention


class RecoveryAction(str, Enum):
    """Actions to take on error."""
    IGNORE = "ignore"           # Log and continue
    RETRY = "retry"             # Retry the operation
    FALLBACK = "fallback"       # Use a fallback method
    ASK_USER = "ask_user"       # Ask user for help
    ABORT = "abort"             # Stop the operation
    RESTART = "restart"         # Restart the component


@dataclass
class ErrorContext:
    """Context about an error for recovery decisions."""
    error: Exception
    operation: str
    retry_count: int = 0
    max_retries: int = 3
    timestamp: str = ""
    traceback_str: str = ""
    additional_info: Dict[str, Any] = None
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        if not self.traceback_str:
            self.traceback_str = traceback.format_exc()
        if self.additional_info is None:
            self.additional_info = {}


class ErrorRecoverySystem:
    """Centralized error recovery for all Chintu components.
    
    Features:
    - Automatic retry with exponential backoff
    - Fallback methods registration
    - User notification for critical errors
    - Error pattern detection
    - Recovery suggestions
    """
    
    # Error message -> User-friendly message
    ERROR_MESSAGES = {
        "connection refused": "I couldn't connect to the service. Is it running?",
        "timeout": "The operation took too long. Let me try again.",
        "permission denied": "I don't have permission to do that. Check file permissions.",
        "file not found": "I couldn't find that file. Could you check the path?",
        "not found": "I couldn't find what you're looking for.",
        "authentication failed": "I need valid credentials for this.",
        "no such": "That doesn't seem to exist.",
        "rate limit": "Too many requests. I'll wait and try again.",
        "network": "There seems to be a network issue.",
        "memory": "Running low on memory. I'll try a lighter approach.",
        "docker": "Docker isn't available. I'll use local execution instead.",
        "ollama": "Ollama isn't running. Start it with 'ollama serve'.",
        "module not found": "A required dependency is missing.",
        "import error": "A required package needs to be installed.",
    }
    
    # Error patterns that are recoverable
    RECOVERABLE_PATTERNS = {
        "timeout": RecoveryAction.RETRY,
        "connection": RecoveryAction.RETRY,
        "temporary": RecoveryAction.RETRY,
        "busy": RecoveryAction.RETRY,
        "rate limit": RecoveryAction.RETRY,
        "docker not running": RecoveryAction.FALLBACK,
        "ollama": RecoveryAction.FALLBACK,
        "credential": RecoveryAction.ASK_USER,
        "permission": RecoveryAction.ASK_USER,
        "not configured": RecoveryAction.ASK_USER,
    }
    
    def __init__(self):
        self.fallbacks: Dict[str, Callable] = {}
        self.error_history: List[ErrorContext] = []
        self.max_history = 100
        
    def register_fallback(self, operation: str, fallback_fn: Callable) -> None:
        """Register a fallback function for an operation."""
        self.fallbacks[operation] = fallback_fn
        logger.debug("Registered fallback for: %s", operation)
    
    def get_friendly_message(self, error: Exception) -> str:
        """Convert technical error to user-friendly message."""
        error_str = str(error).lower()
        
        for pattern, message in self.ERROR_MESSAGES.items():
            if pattern in error_str:
                return message
        
        # Generic message for unknown errors
        return f"Something went wrong: {str(error)[:100]}"
    
    def suggest_recovery(self, error: Exception, operation: str) -> Tuple[RecoveryAction, str]:
        """Suggest a recovery action for an error."""
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()
        
        # Check patterns
        for pattern, action in self.RECOVERABLE_PATTERNS.items():
            if pattern in error_str or pattern in error_type:
                suggestion = self._get_recovery_suggestion(action, pattern)
                return action, suggestion
        
        # Check if fallback available
        if operation in self.fallbacks:
            return RecoveryAction.FALLBACK, f"I'll try an alternative approach for {operation}."
        
        # Default to asking user for serious errors
        return RecoveryAction.ASK_USER, "I need help with this issue."
    
    def _get_recovery_suggestion(self, action: RecoveryAction, pattern: str) -> str:
        """Get a suggestion message for recovery action."""
        suggestions = {
            RecoveryAction.RETRY: "Let me try again in a moment.",
            RecoveryAction.FALLBACK: "I'll use an alternative method.",
            RecoveryAction.ASK_USER: "I need some information from you.",
            RecoveryAction.ABORT: "I'll stop this operation.",
            RecoveryAction.RESTART: "I'll restart the component.",
        }
        return suggestions.get(action, "I'll handle this.")
    
    async def execute_with_recovery(
        self,
        operation: str,
        func: Callable[..., T],
        *args,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        on_error: Optional[Callable[[ErrorContext], None]] = None,
        **kwargs
    ) -> Tuple[bool, Union[T, str]]:
        """Execute a function with automatic error recovery.
        
        Args:
            operation: Name of the operation for logging
            func: Function to execute
            *args: Arguments for the function
            max_retries: Maximum retry attempts
            retry_delay: Initial delay between retries (exponential backoff)
            on_error: Optional callback on error
            **kwargs: Keyword arguments for the function
            
        Returns:
            Tuple of (success, result_or_error_message)
        """
        retry_count = 0
        last_error = None
        
        while retry_count <= max_retries:
            try:
                # Execute the function
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                return True, result
                
            except Exception as exc:
                last_error = exc
                error_ctx = ErrorContext(
                    error=exc,
                    operation=operation,
                    retry_count=retry_count,
                    max_retries=max_retries,
                )
                
                self._record_error(error_ctx)
                
                if on_error:
                    on_error(error_ctx)
                
                # Get recovery suggestion
                action, suggestion = self.suggest_recovery(exc, operation)
                
                if action == RecoveryAction.RETRY and retry_count < max_retries:
                    retry_count += 1
                    delay = retry_delay * (2 ** (retry_count - 1))  # Exponential backoff
                    logger.warning(
                        "%s failed (attempt %d/%d): %s. Retrying in %.1fs...",
                        operation, retry_count, max_retries, exc, delay
                    )
                    await asyncio.sleep(delay)
                    continue
                
                elif action == RecoveryAction.FALLBACK and operation in self.fallbacks:
                    logger.info("Using fallback for %s", operation)
                    try:
                        fallback_fn = self.fallbacks[operation]
                        if asyncio.iscoroutinefunction(fallback_fn):
                            result = await fallback_fn(*args, **kwargs)
                        else:
                            result = fallback_fn(*args, **kwargs)
                        return True, result
                    except Exception as fb_exc:
                        logger.warning("Fallback also failed: %s", fb_exc)
                        return False, self.get_friendly_message(fb_exc)
                
                else:
                    # Can't recover automatically
                    friendly_msg = self.get_friendly_message(exc)
                    logger.error("%s failed: %s", operation, exc)
                    return False, friendly_msg
        
        # Exhausted retries
        return False, self.get_friendly_message(last_error)
    
    def _record_error(self, error_ctx: ErrorContext) -> None:
        """Record error for history and pattern detection."""
        self.error_history.append(error_ctx)
        if len(self.error_history) > self.max_history:
            self.error_history = self.error_history[-self.max_history:]
    
    def get_error_summary(self, last_n: int = 10) -> str:
        """Get a summary of recent errors."""
        if not self.error_history:
            return "No recent errors."
        
        lines = ["Recent errors:"]
        for ctx in self.error_history[-last_n:]:
            lines.append(f"- [{ctx.timestamp}] {ctx.operation}: {ctx.error}")
        return "\n".join(lines)


# Decorator for easy error recovery
def with_recovery(
    operation: Optional[str] = None,
    max_retries: int = 3,
    fallback: Optional[Callable] = None,
):
    """Decorator to add error recovery to a function.
    
    Usage:
        @with_recovery(operation="fetch_data", max_retries=3)
        async def fetch_data(url):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        op_name = operation or func.__name__
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            recovery = get_error_recovery()
            
            if fallback:
                recovery.register_fallback(op_name, fallback)
            
            success, result = await recovery.execute_with_recovery(
                op_name, func, *args, max_retries=max_retries, **kwargs
            )
            
            if not success:
                raise RecoverableError(result)
            return result
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                recovery = get_error_recovery()
                friendly_msg = recovery.get_friendly_message(exc)
                raise RecoverableError(friendly_msg) from exc
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


class RecoverableError(Exception):
    """An error that has been converted to a user-friendly message."""
    pass


@contextmanager
def safe_operation(operation: str, default: Any = None):
    """Context manager for safe operations with logging.
    
    Usage:
        with safe_operation("reading file", default=""):
            content = file.read()
    """
    try:
        yield
    except Exception as exc:
        recovery = get_error_recovery()
        logger.warning("%s failed: %s", operation, exc)
        recovery._record_error(ErrorContext(error=exc, operation=operation))


@asynccontextmanager
async def async_safe_operation(operation: str, default: Any = None):
    """Async context manager for safe operations."""
    try:
        yield
    except Exception as exc:
        recovery = get_error_recovery()
        logger.warning("%s failed: %s", operation, exc)
        recovery._record_error(ErrorContext(error=exc, operation=operation))


# Singleton
_error_recovery: Optional[ErrorRecoverySystem] = None


def get_error_recovery() -> ErrorRecoverySystem:
    """Get or create the global Error Recovery System."""
    global _error_recovery
    if _error_recovery is None:
        _error_recovery = ErrorRecoverySystem()
    return _error_recovery
