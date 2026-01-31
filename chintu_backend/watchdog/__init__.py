"""Project watchdog package."""

from .manager import ProjectWatchdogManager, WatchdogEntry, get_watchdog_manager
from .watchdog_capabilities import register_watchdog_capabilities

__all__ = [
    "ProjectWatchdogManager",
    "WatchdogEntry",
    "get_watchdog_manager",
    "register_watchdog_capabilities",
]

