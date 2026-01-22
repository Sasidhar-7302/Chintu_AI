"""
Windows Notifications for Chintu AI Assistant.

Provides native Windows toast notifications:
- Non-intrusive alerts
- Action buttons
- Notification history
"""

import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# Windows toast notifications
try:
    from win10toast_click import ToastNotifier
    HAS_TOAST = True
except ImportError:
    try:
        from win10toast import ToastNotifier
        HAS_TOAST = True
    except ImportError:
        HAS_TOAST = False
        logger.warning("win10toast not installed - notifications disabled")


class WindowsNotifications:
    """
    Windows toast notification system.
    
    Uses win10toast for native Windows notifications.
    """
    
    def __init__(self, app_name: str = "Chintu"):
        """
        Initialize notification system.
        
        Args:
            app_name: Application name shown in notifications
        """
        self.app_name = app_name
        self._notifier = ToastNotifier() if HAS_TOAST else None
        
    @property
    def is_available(self) -> bool:
        """Check if notifications are available."""
        return HAS_TOAST and self._notifier is not None
    
    def notify(
        self,
        title: str,
        message: str,
        duration: int = 5,
        icon_path: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> bool:
        """
        Show a toast notification.
        
        Args:
            title: Notification title
            message: Notification body
            duration: Duration in seconds
            icon_path: Optional icon path
            callback: Optional callback when clicked
            
        Returns:
            True if notification was shown
        """
        if not self.is_available:
            logger.warning("Notifications not available")
            return False
        
        try:
            if callback and hasattr(self._notifier, 'show_toast'):
                # win10toast_click supports callbacks
                self._notifier.show_toast(
                    title,
                    message,
                    duration=duration,
                    icon_path=icon_path,
                    callback_on_click=callback,
                    threaded=True,
                )
            else:
                self._notifier.show_toast(
                    title,
                    message,
                    duration=duration,
                    icon_path=icon_path,
                    threaded=True,
                )
            
            logger.debug(f"Notification shown: {title}")
            return True
            
        except Exception as e:
            logger.error(f"Notification failed: {e}")
            return False
    
    def notify_success(self, message: str) -> bool:
        """Show a success notification."""
        return self.notify("✓ Chintu", message, duration=3)
    
    def notify_error(self, message: str) -> bool:
        """Show an error notification."""
        return self.notify("⚠ Chintu", message, duration=5)
    
    def notify_reminder(self, message: str) -> bool:
        """Show a reminder notification."""
        return self.notify("🔔 Reminder", message, duration=10)


# Global instance
_notifications: Optional[WindowsNotifications] = None


def get_notifications() -> WindowsNotifications:
    """Get or create the global notifications instance."""
    global _notifications
    if _notifications is None:
        _notifications = WindowsNotifications()
    return _notifications


def notify(title: str, message: str, duration: int = 5) -> bool:
    """Convenience function to show a notification."""
    return get_notifications().notify(title, message, duration)
