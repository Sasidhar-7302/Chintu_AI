"""Windows application discovery module.

Discovers installed applications from Start Menu and Program Files.
Provides fuzzy matching for app names.
"""

import os
import logging
import subprocess
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredApp:
    """Represents a discovered application."""
    name: str
    path: str
    source: str  # "start_menu", "program_files", "system"
    
    
class AppDiscovery:
    """Discovers and caches installed Windows applications."""
    
    def __init__(self):
        self._apps: Dict[str, DiscoveredApp] = {}
        self._initialized = False
        
        # Pre-defined system apps (always available on Windows)
        self._system_apps = {
            "notepad": DiscoveredApp("Notepad", "notepad", "system"),
            "calculator": DiscoveredApp("Calculator", "calc", "system"),
            "calc": DiscoveredApp("Calculator", "calc", "system"),
            "explorer": DiscoveredApp("File Explorer", "explorer", "system"),
            "file explorer": DiscoveredApp("File Explorer", "explorer", "system"),
            "cmd": DiscoveredApp("Command Prompt", "cmd", "system"),
            "command prompt": DiscoveredApp("Command Prompt", "cmd", "system"),
            "powershell": DiscoveredApp("PowerShell", "powershell", "system"),
            "terminal": DiscoveredApp("Windows Terminal", "wt", "system"),
            "settings": DiscoveredApp("Settings", "ms-settings:", "system"),
            "control panel": DiscoveredApp("Control Panel", "control", "system"),
            "task manager": DiscoveredApp("Task Manager", "taskmgr", "system"),
            "paint": DiscoveredApp("Paint", "mspaint", "system"),
            "wordpad": DiscoveredApp("WordPad", "wordpad", "system"),
            "snipping tool": DiscoveredApp("Snipping Tool", "snippingtool", "system"),
        }
        
        # Common app executable mappings
        self._common_apps = {
            "chrome": ("Google Chrome", "chrome"),
            "google chrome": ("Google Chrome", "chrome"),
            "firefox": ("Firefox", "firefox"),
            "edge": ("Microsoft Edge", "msedge"),
            "microsoft edge": ("Microsoft Edge", "msedge"),
            "vscode": ("Visual Studio Code", "code"),
            "vs code": ("Visual Studio Code", "code"),
            "visual studio code": ("Visual Studio Code", "code"),
            "spotify": ("Spotify", "spotify"),
            "discord": ("Discord", "discord"),
            "slack": ("Slack", "slack"),
            "teams": ("Microsoft Teams", "teams"),
            "zoom": ("Zoom", "zoom"),
            "outlook": ("Outlook", "outlook"),
            "word": ("Microsoft Word", "winword"),
            "excel": ("Microsoft Excel", "excel"),
            "powerpoint": ("PowerPoint", "powerpnt"),
            "onenote": ("OneNote", "onenote"),
            "vlc": ("VLC Media Player", "vlc"),
            "obs": ("OBS Studio", "obs64"),
            "steam": ("Steam", "steam"),
            "epic games": ("Epic Games", "EpicGamesLauncher"),
            "whatsapp": ("WhatsApp", "WhatsApp"),
            "telegram": ("Telegram", "Telegram"),
        }
        
    def initialize(self):
        """Initialize app discovery by scanning system."""
        if self._initialized:
            return
            
        logger.info("Initializing app discovery...")
        
        # Add system apps
        self._apps.update(self._system_apps)
        
        # Add common apps
        for name, (display_name, exe) in self._common_apps.items():
            self._apps[name.lower()] = DiscoveredApp(display_name, exe, "common")
        
        # Scan Start Menu
        self._scan_start_menu()
        
        self._initialized = True
        logger.info(f"App discovery initialized: {len(self._apps)} apps found")
        
    def _scan_start_menu(self):
        """Scan Start Menu for installed applications."""
        start_menu_paths = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
            Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        ]
        
        for start_path in start_menu_paths:
            if not start_path.exists():
                continue
                
            try:
                for item in start_path.rglob("*.lnk"):
                    try:
                        name = item.stem.lower()
                        # Skip uninstall shortcuts
                        if "uninstall" in name:
                            continue
                        # Use the shortcut path
                        self._apps[name] = DiscoveredApp(
                            item.stem, 
                            str(item), 
                            "start_menu"
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Error scanning {start_path}: {e}")
                
    def find_app(self, query: str) -> Optional[DiscoveredApp]:
        """Find an app by name with fuzzy matching.
        
        Args:
            query: App name to search for
            
        Returns:
            DiscoveredApp if found, None otherwise
        """
        if not self._initialized:
            self.initialize()
            
        query_lower = query.lower().strip()
        
        # Exact match
        if query_lower in self._apps:
            return self._apps[query_lower]
            
        # Partial match - check if query is contained in app name
        for name, app in self._apps.items():
            if query_lower in name or name in query_lower:
                return app
                
        # Fuzzy match - check for similar names
        for name, app in self._apps.items():
            # Remove common words and compare
            clean_query = re.sub(r'\s+', '', query_lower)
            clean_name = re.sub(r'\s+', '', name)
            if clean_query in clean_name or clean_name in clean_query:
                return app
                
        return None
        
    def open_app(self, app: DiscoveredApp) -> bool:
        """Open the given application.
        
        Args:
            app: DiscoveredApp to open
            
        Returns:
            True if successful, False otherwise
        """
        try:
            path = app.path
            
            if path.startswith("ms-"):
                # Windows Settings URI
                os.startfile(path)
            elif path.endswith(".lnk"):
                # Start Menu shortcut
                os.startfile(path)
            else:
                # Direct executable or command
                if os.name == 'nt' and not os.path.isabs(path) and "/" not in path and "\\" not in path:
                    # For bare commands like 'chrome', use cmd /c start to ensure PATH/Registry lookup
                    subprocess.Popen(
                        ["cmd", "/c", "start", "", path],
                        shell=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    subprocess.Popen(
                        [path],
                        shell=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                               
            logger.info(f"Opened app: {app.name} ({app.path})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to open {app.name}: {e}")
            return False
            
    def get_all_apps(self) -> List[str]:
        """Get list of all discovered app names."""
        if not self._initialized:
            self.initialize()
        return sorted(set(self._apps.keys()))


# Global instance
_app_discovery: Optional[AppDiscovery] = None


def get_app_discovery() -> AppDiscovery:
    """Get the global AppDiscovery instance."""
    global _app_discovery
    if _app_discovery is None:
        _app_discovery = AppDiscovery()
    return _app_discovery
