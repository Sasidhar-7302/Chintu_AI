"""
Failure Handling System for Chintu Assistant.
Provides graceful error handling with explanations for users.
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class FailureType(Enum):
    """Types of failures that can occur."""
    NETWORK = "network"          # Internet/API connectivity issues
    LLM_UNAVAILABLE = "llm"      # LLM service unavailable
    APP_NOT_FOUND = "app"        # Application not installed
    PERMISSION = "permission"    # Permission denied
    TIMEOUT = "timeout"          # Operation timed out
    UNKNOWN = "unknown"          # Unknown error


@dataclass
class FailureInfo:
    """Information about a failure."""
    failure_type: FailureType
    message: str
    user_message: str
    recoverable: bool = True
    suggestion: Optional[str] = None
    
    def get_explanation(self) -> str:
        """Get user-friendly explanation."""
        parts = [self.user_message]
        if self.suggestion:
            parts.append(self.suggestion)
        return " ".join(parts)


class FailureHandler:
    """
    Handles failures gracefully with user-friendly explanations.
    """
    
    @staticmethod
    def handle_llm_failure(error: Exception, attempted_model: str) -> FailureInfo:
        """Handle LLM service failure."""
        error_str = str(error).lower()
        
        if "connection" in error_str or "network" in error_str:
            return FailureInfo(
                failure_type=FailureType.NETWORK,
                message=str(error),
                user_message=f"I couldn't reach the {attempted_model} service.",
                suggestion="Let me try with a different model.",
                recoverable=True
            )
        
        if "timeout" in error_str:
            return FailureInfo(
                failure_type=FailureType.TIMEOUT,
                message=str(error),
                user_message="The request took too long to process.",
                suggestion="Please try a simpler question.",
                recoverable=True
            )
        
        return FailureInfo(
            failure_type=FailureType.LLM_UNAVAILABLE,
            message=str(error),
            user_message=f"I'm having trouble processing your request.",
            suggestion="Let me try another approach.",
            recoverable=True
        )
    
    @staticmethod
    def handle_app_failure(app_name: str, error: Exception) -> FailureInfo:
        """Handle application launch failure."""
        error_str = str(error).lower()
        
        if "not found" in error_str or "cannot find" in error_str:
            return FailureInfo(
                failure_type=FailureType.APP_NOT_FOUND,
                message=str(error),
                user_message=f"I couldn't find {app_name} on your system.",
                suggestion="Please make sure it's installed.",
                recoverable=False
            )
        
        if "permission" in error_str or "access denied" in error_str:
            return FailureInfo(
                failure_type=FailureType.PERMISSION,
                message=str(error),
                user_message=f"I don't have permission to open {app_name}.",
                suggestion="You may need to run as administrator.",
                recoverable=False
            )
        
        return FailureInfo(
            failure_type=FailureType.UNKNOWN,
            message=str(error),
            user_message=f"I couldn't open {app_name}.",
            recoverable=False
        )
    
    @staticmethod
    def handle_network_failure(service: str, error: Exception) -> FailureInfo:
        """Handle network/connectivity failure."""
        return FailureInfo(
            failure_type=FailureType.NETWORK,
            message=str(error),
            user_message=f"I couldn't connect to {service}.",
            suggestion="Please check your internet connection.",
            recoverable=True
        )
    
    @staticmethod
    def handle_generic_failure(action: str, error: Exception) -> FailureInfo:
        """Handle any other type of failure."""
        return FailureInfo(
            failure_type=FailureType.UNKNOWN,
            message=str(error),
            user_message=f"I encountered an issue while trying to {action}.",
            suggestion="Please try again.",
            recoverable=True
        )
    
    @staticmethod
    def format_response(failure: FailureInfo) -> str:
        """Format a failure as a user-friendly response."""
        return failure.get_explanation()


class RetryManager:
    """
    Manages retry logic for recoverable failures.
    """
    
    def __init__(self, max_retries: int = 2):
        self.max_retries = max_retries
        self._retry_counts: Dict[str, int] = {}
    
    def should_retry(self, operation_id: str) -> bool:
        """Check if we should retry an operation."""
        count = self._retry_counts.get(operation_id, 0)
        return count < self.max_retries
    
    def record_attempt(self, operation_id: str) -> int:
        """Record an attempt and return the attempt number."""
        count = self._retry_counts.get(operation_id, 0) + 1
        self._retry_counts[operation_id] = count
        return count
    
    def reset(self, operation_id: str) -> None:
        """Reset retry count for an operation."""
        if operation_id in self._retry_counts:
            del self._retry_counts[operation_id]
    
    def clear_all(self) -> None:
        """Clear all retry counts."""
        self._retry_counts.clear()


# Global instances
_failure_handler = FailureHandler()
_retry_manager = RetryManager()


def get_failure_handler() -> FailureHandler:
    return _failure_handler


def get_retry_manager() -> RetryManager:
    return _retry_manager
