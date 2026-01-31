"""Window Manager for accurate app detection.
Uses ctypes and WinAPI (EnumWindows) for reliable window enumeration.
"""

import logging
import collections
import ctypes
from typing import List, Dict, Counter

logger = logging.getLogger(__name__)

# Ctypes definitions
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
GetWindowText = ctypes.windll.user32.GetWindowTextW
GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
IsWindowVisible = ctypes.windll.user32.IsWindowVisible

class WindowManager:
    """Manages window detection using native WinAPI."""
    
    def get_open_windows(self) -> List[str]:
        """Get list of titles of all open, visible windows."""
        titles = []

        def foreach_window(hwnd, lParam):
            if IsWindowVisible(hwnd):
                length = GetWindowTextLength(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    GetWindowText(hwnd, buff, length + 1)
                    title = buff.value
                    # Filter out system/hidden/manager windows
                    if title and title not in ["Program Manager", "Settings", "Microsoft Text Input Application"]:
                        titles.append(title)
            return True

        ctypes.windll.user32.EnumWindows(EnumWindowsProc(foreach_window), 0)
        return titles

    def get_window_summary(self) -> str:
        """Get a human-readable summary of open apps."""
        titles = self.get_open_windows()
        if not titles:
            return "No active windows detected."
            
        app_counts = collections.Counter()
        
        for title in titles:
            lower = title.lower()
            # Heuristics
            if " - google chrome" in lower:
                app_counts["Google Chrome"] += 1
            elif " - visual studio code" in lower:
                app_counts["VS Code"] += 1
            elif " - word" in lower:
                app_counts["Microsoft Word"] += 1
            elif " - excel" in lower:
                app_counts["Microsoft Excel"] += 1
            elif " - powerpoint" in lower:
                app_counts["PowerPoint"] += 1
            elif " - notepad" in lower:
                app_counts["Notepad"] += 1
            elif "spotify" in lower: # Spotify sometimes just "Spotify" or "Song - Spotify"
                 if lower == "spotify" or " - spotify" in lower:
                    app_counts["Spotify"] += 1
            elif "command prompt" in lower or "cmd.exe" in lower:
                app_counts["Command Prompt"] += 1
            elif "windows powershell" in lower:
                app_counts["PowerShell"] += 1
            else:
                # Try to extract app name from "Doc - App" format
                if " - " in title:
                    # Assume last part is app name
                    possible_app = title.split(" - ")[-1]
                    # Filter out noise (e.g. browser tabs sometimes put site name at end? No usually Site - Browser)
                    app_counts[possible_app] += 1
                else:
                    # Just count unique title if it looks real?
                    # Avoid noise.
                    pass

        # Build summary
        parts = []
        for app, count in app_counts.items():
            parts.append(f"{count} {app}" + ("s" if count > 1 else ""))
        
        if not parts:
            # Fallback
            return "Windows: " + ", ".join(titles[:5])
            
        return ", ".join(parts)

    def switch_to_window(self, keyword: str) -> bool:
        """Switch focus to a window matching the keyword."""
        keyword = keyword.lower()
        found_hwnd = 0
        
        def foreach_window(hwnd, lParam):
            if IsWindowVisible(hwnd):
                length = GetWindowTextLength(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    GetWindowText(hwnd, buff, length + 1)
                    title = buff.value.lower()
                    if keyword in title:
                        nonlocal found_hwnd
                        found_hwnd = hwnd
                        return False # Stop
            return True

        ctypes.windll.user32.EnumWindows(EnumWindowsProc(foreach_window), 0)
        
        if found_hwnd:
            # SW_RESTORE = 9
            ctypes.windll.user32.ShowWindow(found_hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(found_hwnd)
            return True
            
        return False

_window_manager = None

def get_window_manager() -> WindowManager:
    global _window_manager
    if _window_manager is None:
        _window_manager = WindowManager()
    return _window_manager
