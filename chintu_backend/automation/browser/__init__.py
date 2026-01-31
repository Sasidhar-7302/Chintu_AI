"""
Browser module for Chintu AI Assistant.
Provides browser automation capabilities using Playwright.
"""

from .browser_controller import BrowserController, get_browser_controller
from .browser_capabilities import register_browser_capabilities
from .browser_fallback import BrowserFallbackAgent, BrowserFallbackResult

__all__ = [
    "BrowserController",
    "BrowserFallbackAgent",
    "BrowserFallbackResult",
    "get_browser_controller",
    "register_browser_capabilities",
]
