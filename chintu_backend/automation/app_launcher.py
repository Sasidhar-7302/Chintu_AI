"""Application and URL launcher for OS automation."""

import subprocess
import webbrowser
import os
import platform
from typing import Optional, Dict
import logging
import shlex

logger = logging.getLogger(__name__)


class AppLauncher:
    """
    Launches applications and opens URLs on Windows.
    Provides safe, sandboxed automation for common tasks.
    """
    
    # Common Windows application paths/commands
    KNOWN_APPS: Dict[str, str] = {
        "notepad": "notepad",
        "calculator": "calc",
        "paint": "mspaint",
        "wordpad": "wordpad",
        "file explorer": "explorer",
        "explorer": "explorer",
        "cmd": "cmd",
        "command prompt": "cmd",
        "powershell": "powershell",
        "terminal": "wt",  # Windows Terminal
        "settings": "ms-settings:",
        "control panel": "control",
        "task manager": "taskmgr",
        "snipping tool": "snippingtool",
        "chrome": "chrome",
        "firefox": "firefox",
        "edge": "msedge",
        "vs code": "code",
        "visual studio code": "code",
        "word": "winword",
        "excel": "excel",
        "powerpoint": "powerpnt",
        "outlook": "outlook",
        "teams": "ms-teams:",
        "spotify": "spotify",
        "discord": "discord",
        "slack": "slack",
    }
    
    # Common URLs
    KNOWN_URLS: Dict[str, str] = {
        "linkedin": "https://www.linkedin.com",
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "github": "https://github.com",
        "twitter": "https://twitter.com",
        "x": "https://x.com",
        "facebook": "https://www.facebook.com",
        "instagram": "https://www.instagram.com",
        "reddit": "https://www.reddit.com",
        "stack overflow": "https://stackoverflow.com",
        "amazon": "https://www.amazon.com",
        "netflix": "https://www.netflix.com",
        "chatgpt": "https://chat.openai.com",
    }
    
    def __init__(self):
        self._is_windows = platform.system() == "Windows"
    
    def open_url(self, url: str) -> bool:
        """
        Open a URL in the default browser.
        
        Args:
            url: The URL to open
            
        Returns:
            True if successful
        """
        try:
            # Check if it's a known shortcut
            url_lower = url.lower()
            if url_lower in self.KNOWN_URLS:
                url = self.KNOWN_URLS[url_lower]
            
            # Ensure URL has protocol
            if not url.startswith(("http://", "https://", "file://")):
                url = "https://" + url
            
            webbrowser.open(url)
            logger.info(f"Opened URL: {url}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to open URL {url}: {e}")
            return False
    
    def launch_app(self, app_name: str) -> bool:
        """
        Launch an application by name.
        
        Args:
            app_name: Name or command of the application
            
        Returns:
            True if successful
        """
        try:
            app_lower = app_name.lower()
            
            # Check known apps
            if app_lower in self.KNOWN_APPS:
                command = self.KNOWN_APPS[app_lower]
            else:
                command = app_name
            
            # Handle special URL schemes (ms-settings:, ms-teams:, etc.)
            if ":" in command and not command.endswith(":"):
                os.startfile(command)
            elif command.endswith(":"):
                os.startfile(command)
            else:
                # Try to start the application
                # Try to start the application
                if self._is_windows:
                    # Audit Fix: Avoid shell=True for security
                    # Use shlex to parse command string safely into args list
                    try:
                        args = shlex.split(command, posix=False)
                    except Exception:
                        # Fallback for simple commands
                        args = [command]
                        
                    subprocess.Popen(
                        args,
                        shell=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    try:
                        args = shlex.split(command)
                    except Exception:
                        args = [command]
                        
                    subprocess.Popen(
                        args,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            
            logger.info(f"Launched application: {app_name} ({command})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to launch {app_name}: {e}")
            return False
    
    def open(self, target: str) -> bool:
        """
        Smart open - determines if target is URL or app.
        
        Args:
            target: URL or application name
            
        Returns:
            True if successful
        """
        target_lower = target.lower()
        
        # Check if it's a known URL
        if target_lower in self.KNOWN_URLS:
            return self.open_url(target_lower)
        
        # Check if it looks like a URL
        if any(target.startswith(p) for p in ["http://", "https://", "www."]):
            return self.open_url(target)
        
        # Check if it's a known app
        if target_lower in self.KNOWN_APPS:
            return self.launch_app(target_lower)
        
        # Try as app first, then URL
        if self.launch_app(target):
            return True
        
        return self.open_url(target)
    
    def get_available_apps(self) -> list:
        """Get list of known applications."""
        return list(self.KNOWN_APPS.keys())
    
    def get_available_urls(self) -> list:
        """Get list of known URLs/websites."""
        return list(self.KNOWN_URLS.keys())

