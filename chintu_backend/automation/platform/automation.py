"""
Platform-specific automation implementations.
Provides cross-platform app launching and automation.
"""

import logging
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class PlatformAutomation(ABC):
    """Base class for platform-specific automation."""
    
    def __init__(self, platform_type: str):
        self.platform_type = platform_type
        self._available = False
        self._errors: list[str] = []
    
    @abstractmethod
    def launch_app(self, app_name: str) -> bool:
        """Launch an application."""
        pass
    
    @abstractmethod
    def open_url(self, url: str) -> bool:
        """Open a URL in browser."""
        pass
    
    def is_available(self) -> bool:
        """Check if automation is available."""
        return self._available
    
    def get_errors(self) -> list[str]:
        """Get list of errors."""
        return self._errors.copy()


class WindowsAutomation(PlatformAutomation):
    """Windows-specific automation."""
    
    def __init__(self):
        super().__init__("windows")
        self._init_windows()
    
    def _init_windows(self):
        """Initialize Windows automation."""
        try:
            import pywinauto
            self._available = True
            logger.info("Windows automation initialized")
        except ImportError:
            self._errors.append("pywinauto not installed")
            logger.warning("Windows automation unavailable - pywinauto not installed")
        except Exception as e:
            self._errors.append(f"Windows automation init failed: {e}")
            logger.error(f"Windows automation initialization failed: {e}")
    
    def launch_app(self, app_name: str) -> bool:
        """Launch Windows app."""
        if not self._available:
            logger.warning("Windows automation not available")
            return False
        
        try:
            import subprocess
            import pywinauto
            import os
            
            # Try common Windows apps
            apps = {
                "chrome": "chrome.exe",
                "firefox": "firefox.exe",
                "edge": "msedge.exe",
                "notepad": "notepad.exe",
                "calculator": "calc.exe",
            }
            
            app_exe = apps.get(app_name.lower(), app_name)
            
            # Launch app
            subprocess.Popen(app_exe, shell=True)
            return True
        
        except Exception as e:
            error_msg = f"Failed to launch app '{app_name}': {e}"
            self._errors.append(error_msg)
            logger.error(error_msg)
            return False
    
    def open_url(self, url: str) -> bool:
        """Open URL in Windows browser."""
        if not self._available:
            logger.warning("Windows automation not available")
            return False
        
        try:
            import webbrowser
            webbrowser.open(url)
            return True
        except Exception as e:
            error_msg = f"Failed to open URL '{url}': {e}"
            self._errors.append(error_msg)
            logger.error(error_msg)
            return False


class MacOSAutomation(PlatformAutomation):
    """macOS-specific automation."""
    
    def __init__(self):
        super().__init__("macos")
        self._init_macos()
    
    def _init_macos(self):
        """Initialize macOS automation."""
        try:
            import subprocess
            # Check if 'open' command is available
            result = subprocess.run(['which', 'open'], capture_output=True)
            if result.returncode == 0:
                self._available = True
                logger.info("macOS automation initialized")
            else:
                self._errors.append("'open' command not available")
        except Exception as e:
            self._errors.append(f"macOS automation init failed: {e}")
            logger.error(f"macOS automation initialization failed: {e}")
    
    def launch_app(self, app_name: str) -> bool:
        """Launch macOS app."""
        if not self._available:
            logger.warning("macOS automation not available")
            return False
        
        try:
            import subprocess
            
            # Try common macOS apps
            apps = {
                "chrome": "Google Chrome",
                "firefox": "Firefox",
                "safari": "Safari",
                "calculator": "Calculator",
            }
            
            app_name_mac = apps.get(app_name.lower(), app_name)
            
            # Launch using 'open' command
            subprocess.Popen(['open', '-a', app_name_mac])
            return True
        
        except Exception as e:
            error_msg = f"Failed to launch app '{app_name}': {e}"
            self._errors.append(error_msg)
            logger.error(error_msg)
            return False
    
    def open_url(self, url: str) -> bool:
        """Open URL in macOS browser."""
        if not self._available:
            logger.warning("macOS automation not available")
            return False
        
        try:
            import subprocess
            subprocess.Popen(['open', url])
            return True
        except Exception as e:
            error_msg = f"Failed to open URL '{url}': {e}"
            self._errors.append(error_msg)
            logger.error(error_msg)
            return False


class LinuxAutomation(PlatformAutomation):
    """Linux-specific automation."""
    
    def __init__(self):
        super().__init__("linux")
        self._available = True  # Linux usually supports basic commands
        logger.info("Linux automation initialized")
    
    def launch_app(self, app_name: str) -> bool:
        """Launch Linux app."""
        try:
            import subprocess
            
            # Try common Linux apps
            apps = {
                "chrome": "google-chrome",
                "firefox": "firefox",
                "calculator": "gnome-calculator",
            }
            
            app_cmd = apps.get(app_name.lower(), app_name)
            subprocess.Popen([app_cmd], shell=True)
            return True
        
        except Exception as e:
            error_msg = f"Failed to launch app '{app_name}': {e}"
            self._errors.append(error_msg)
            logger.error(error_msg)
            return False
    
    def open_url(self, url: str) -> bool:
        """Open URL in Linux browser."""
        try:
            import subprocess
            subprocess.Popen(['xdg-open', url])
            return True
        except Exception as e:
            error_msg = f"Failed to open URL '{url}': {e}"
            self._errors.append(error_msg)
            logger.error(error_msg)
            return False


def create_automation(platform_type: Optional[str] = None) -> PlatformAutomation:
    """
    Create platform-appropriate automation handler.
    
    Args:
        platform_type: Platform type (auto-detected if None)
        
    Returns:
        PlatformAutomation instance
    """
    if platform_type is None:
        from .detector import get_platform
        detector = get_platform()
        platform_type = detector.platform.value
    
    if platform_type == "windows":
        return WindowsAutomation()
    elif platform_type == "macos":
        return MacOSAutomation()
    elif platform_type == "linux":
        return LinuxAutomation()
    else:
        # Fallback to basic implementation
        logger.warning(f"Unknown platform {platform_type}, using basic automation")
        return LinuxAutomation()  # Most compatible

