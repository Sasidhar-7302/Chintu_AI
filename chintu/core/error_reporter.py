"""
Comprehensive Error Reporting System for Chintu AI Assistant.
Reports errors via UI, voice, and logs with graceful degradation.
"""

import logging
import traceback
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ErrorReport:
    """Error report structure."""
    error_id: str
    severity: ErrorSeverity
    message: str
    category: str
    component: str
    timestamp: str
    traceback: Optional[str] = None
    context: Dict[str, Any] = None
    user_message: Optional[str] = None  # User-friendly message
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "error_id": self.error_id,
            "severity": self.severity.value,
            "message": self.message,
            "category": self.category,
            "component": self.component,
            "timestamp": self.timestamp,
            "traceback": self.traceback,
            "context": self.context or {},
            "user_message": self.user_message,
        }


class ErrorReporter:
    """
    Comprehensive error reporting system.
    Reports errors via multiple channels: logs, UI, voice.
    """
    
    def __init__(self):
        self._errors: List[ErrorReport] = []
        self._ui_callbacks: List[Callable[[ErrorReport], None]] = []
        self._voice_callbacks: List[Callable[[ErrorReport], None]] = []
        self._max_errors = 100  # Keep last 100 errors
        
        logger.info("Error reporter initialized")
    
    def report_error(
        self,
        error: Exception,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        component: str = "unknown",
        context: Optional[Dict[str, Any]] = None,
        user_message: Optional[str] = None,
        log_to_file: bool = True,
        notify_ui: bool = True,
        notify_voice: bool = False,  # Don't annoy user with voice for every error
    ) -> ErrorReport:
        """
        Report an error with graceful degradation.
        
        Args:
            error: Exception object or error message string
            severity: Error severity level
            component: Component that generated the error
            context: Additional context dictionary
            user_message: User-friendly message (auto-generated if None)
            log_to_file: Whether to log to file (always True, cannot fail)
            notify_ui: Whether to notify UI (graceful degradation)
            notify_voice: Whether to notify via voice (only for critical errors)
            
        Returns:
            ErrorReport instance
        """
        import uuid
        
        # Generate error ID
        error_id = str(uuid.uuid4())[:8]
        
        # Extract error message
        if isinstance(error, Exception):
            message = str(error)
            tb = traceback.format_exc()
        else:
            message = str(error)
            tb = None
        
        # Generate user-friendly message if not provided
        if user_message is None:
            user_message = self._generate_user_message(error, severity, component)
        
        # Create error report
        report = ErrorReport(
            error_id=error_id,
            severity=severity,
            message=message,
            category=self._categorize_error(error),
            component=component,
            timestamp=datetime.now().isoformat(),
            traceback=tb,
            context=context or {},
            user_message=user_message,
        )
        
        # Always log to file (this should never fail)
        try:
            self._log_error(report, log_to_file)
        except Exception as e:
            # Even logging can fail - but we still try
            print(f"ERROR: Failed to log error: {e}")  # Fallback to stdout
        
        # Store error
        self._errors.append(report)
        if len(self._errors) > self._max_errors:
            self._errors.pop(0)  # Remove oldest
        
        # Notify UI (graceful degradation)
        if notify_ui:
            try:
                self._notify_ui(report)
            except Exception as e:
                logger.warning(f"Failed to notify UI: {e}")  # Degrade gracefully
        
        # Notify voice (only for critical errors)
        if notify_voice and severity == ErrorSeverity.CRITICAL:
            try:
                self._notify_voice(report)
            except Exception as e:
                logger.warning(f"Failed to notify voice: {e}")  # Degrade gracefully
        
        return report
    
    def _log_error(self, report: ErrorReport, log_to_file: bool):
        """Log error to file."""
        log_msg = f"[{report.error_id}] {report.severity.value.upper()}: {report.message} (component: {report.component})"
        
        if report.severity == ErrorSeverity.CRITICAL:
            logger.critical(log_msg, exc_info=report.traceback)
        elif report.severity == ErrorSeverity.ERROR:
            logger.error(log_msg, exc_info=report.traceback)
        elif report.severity == ErrorSeverity.WARNING:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)
        
        # Also log context if available
        if report.context:
            logger.debug(f"Error context: {report.context}")
    
    def _notify_ui(self, report: ErrorReport):
        """Notify UI about error."""
        for callback in self._ui_callbacks:
            try:
                callback(report)
            except Exception as e:
                logger.warning(f"Error in UI callback: {e}")
    
    def _notify_voice(self, report: ErrorReport):
        """Notify via voice (for critical errors only)."""
        # Only notify voice for critical errors
        if report.severity != ErrorSeverity.CRITICAL:
            return
        
        for callback in self._voice_callbacks:
            try:
                callback(report)
            except Exception as e:
                logger.warning(f"Error in voice callback: {e}")
    
    def _categorize_error(self, error: Exception) -> str:
        """Categorize error type."""
        if isinstance(error, ConnectionError):
            return "network"
        elif isinstance(error, FileNotFoundError):
            return "file_system"
        elif isinstance(error, PermissionError):
            return "permission"
        elif isinstance(error, ImportError):
            return "dependency"
        elif isinstance(error, ValueError):
            return "validation"
        elif isinstance(error, TimeoutError):
            return "timeout"
        elif isinstance(error, RuntimeError):
            return "runtime"
        else:
            return "unknown"
    
    def _generate_user_message(
        self,
        error: Exception,
        severity: ErrorSeverity,
        component: str
    ) -> str:
        """Generate user-friendly error message."""
        if severity == ErrorSeverity.CRITICAL:
            return f"Critical error in {component}. Please check logs for details."
        elif severity == ErrorSeverity.ERROR:
            return f"Error in {component}. Some features may be unavailable."
        elif severity == ErrorSeverity.WARNING:
            return f"Warning in {component}. System is running with limited functionality."
        else:
            return f"Info from {component}."
    
    def register_ui_callback(self, callback: Callable[[ErrorReport], None]):
        """Register UI callback for error notifications."""
        self._ui_callbacks.append(callback)
        logger.debug("Registered UI error callback")
    
    def register_voice_callback(self, callback: Callable[[ErrorReport], None]):
        """Register voice callback for error notifications."""
        self._voice_callbacks.append(callback)
        logger.debug("Registered voice error callback")
    
    def get_errors(self, severity: Optional[ErrorSeverity] = None) -> List[ErrorReport]:
        """Get error reports, optionally filtered by severity."""
        if severity:
            return [e for e in self._errors if e.severity == severity]
        return self._errors.copy()
    
    def get_recent_errors(self, count: int = 10) -> List[ErrorReport]:
        """Get recent error reports."""
        return self._errors[-count:]
    
    def get_error_summary(self) -> Dict[str, Any]:
        """Get error summary statistics."""
        summary = {
            "total_errors": len(self._errors),
            "by_severity": {
                "critical": len([e for e in self._errors if e.severity == ErrorSeverity.CRITICAL]),
                "error": len([e for e in self._errors if e.severity == ErrorSeverity.ERROR]),
                "warning": len([e for e in self._errors if e.severity == ErrorSeverity.WARNING]),
                "info": len([e for e in self._errors if e.severity == ErrorSeverity.INFO]),
            },
            "by_category": {},
            "recent_errors": [e.to_dict() for e in self.get_recent_errors(5)],
        }
        
        # Count by category
        for error in self._errors:
            category = error.category
            summary["by_category"][category] = summary["by_category"].get(category, 0) + 1
        
        return summary
    
    def clear_errors(self):
        """Clear all error reports."""
        self._errors.clear()
        logger.info("Cleared all error reports")


# Global error reporter instance
_error_reporter: Optional[ErrorReporter] = None


def get_error_reporter() -> ErrorReporter:
    """Get or create the global error reporter."""
    global _error_reporter
    if _error_reporter is None:
        _error_reporter = ErrorReporter()
    return _error_reporter


def report_error(
    error: Exception,
    severity: ErrorSeverity = ErrorSeverity.ERROR,
    component: str = "unknown",
    context: Optional[Dict[str, Any]] = None,
    user_message: Optional[str] = None,
    notify_voice: bool = False,
) -> ErrorReport:
    """
    Convenience function to report an error.
    
    Usage:
        try:
            # Some code
        except Exception as e:
            report_error(e, component="my_component", notify_voice=True)
    """
    reporter = get_error_reporter()
    return reporter.report_error(
        error=error,
        severity=severity,
        component=component,
        context=context,
        user_message=user_message,
        notify_voice=notify_voice,
    )

