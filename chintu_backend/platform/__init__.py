"""Compatibility platform namespace for tests and legacy imports."""

from .app_discovery import AppDiscovery, DiscoveredApp, get_app_discovery
from .window_manager import WindowManager, get_window_manager

__all__ = [
    "AppDiscovery",
    "DiscoveredApp",
    "get_app_discovery",
    "WindowManager",
    "get_window_manager",
]
