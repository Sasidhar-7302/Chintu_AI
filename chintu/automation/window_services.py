"""
Window Management Services.
Lists and manages open application windows.
"""

import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

try:
    import pygetwindow as gw
    HAS_GW = True
except ImportError:
    HAS_GW = False
    logger.warning("pygetwindow not installed")

# System windows to filter out (invisible/background windows)
SYSTEM_WINDOWS_TO_HIDE = {
    "default ime",
    "msctfime ui",
    "nvidia geforce overlay",
    "program manager",
    "windows input experience",
    "windows shell experience host",
    "microsoft text input application",
    "systray",
    "start",
    "",  # Empty titles
}

def get_open_windows() -> List[str]:
    """Get a list of titles of visible open windows (filtered for real apps)."""
    if not HAS_GW:
        return ["(Window listing unavailable - pygetwindow missing)"]
        
    try:
        all_windows = gw.getAllWindows()
        visible_windows = []
        
        for win in all_windows:
            title = win.title.strip()
            title_lower = title.lower()
            
            # Skip empty titles
            if not title:
                continue
            
            # Skip known system windows
            if title_lower in SYSTEM_WINDOWS_TO_HIDE:
                continue
            
            # Skip windows with very short generic titles
            if len(title) < 3 and not title.isupper():
                continue
            
            # Try to check if window is visible and has size
            try:
                # Window must have some dimensions to be visible
                if win.width > 0 and win.height > 0:
                    visible_windows.append(title)
            except:
                # If we can't check size, include it anyway
                visible_windows.append(title)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_windows = []
        for w in visible_windows:
            if w.lower() not in seen:
                seen.add(w.lower())
                unique_windows.append(w)
        
        return unique_windows if unique_windows else ["No visible application windows found."]
        
    except Exception as e:
        logger.error(f"Failed to list windows: {e}")
        return [f"(Error listing windows: {e})"]

def list_windows_formatted() -> str:
    """Get a formatted string of open windows for LLM/User."""
    windows = get_open_windows()
    if not windows or (len(windows) == 1 and windows[0].startswith("(")):
        return windows[0] if windows else "No visible windows found."
    
    # Extract app names from window titles and count them
    app_counts = {}
    for title in windows:
        app_name = _extract_app_name(title)
        if app_name:
            app_counts[app_name] = app_counts.get(app_name, 0) + 1
    
    if not app_counts:
        return "No applications found."
    
    # Format as concise list
    parts = []
    for app, count in sorted(app_counts.items()):
        if count > 1:
            parts.append(f"{count} {app} windows")
        else:
            parts.append(app)
    
    return f"You have open: {', '.join(parts)}."


def _extract_app_name(title: str) -> str:
    """Extract the app name from a window title."""
    title_lower = title.lower()
    
    # Known app patterns (window title -> app name)
    APP_PATTERNS = {
        "visual studio code": "VS Code",
        "vscode": "VS Code",
        "- code": "VS Code",
        "google chrome": "Chrome",
        "- chrome": "Chrome",
        "mozilla firefox": "Firefox",
        "- firefox": "Firefox",
        "microsoft edge": "Edge",
        "- edge": "Edge",
        "file explorer": "File Explorer",
        "explorer.exe": "File Explorer",
        "microsoft word": "Word",
        "- word": "Word",
        ".docx": "Word",
        "microsoft excel": "Excel",
        "- excel": "Excel", 
        ".xlsx": "Excel",
        "microsoft powerpoint": "PowerPoint",
        "- powerpoint": "PowerPoint",
        ".pptx": "PowerPoint",
        "notepad": "Notepad",
        "windows terminal": "Terminal",
        "powershell": "PowerShell",
        "command prompt": "Command Prompt",
        "cmd.exe": "Command Prompt",
        "discord": "Discord",
        "spotify": "Spotify",
        "slack": "Slack",
        "teams": "Teams",
        "zoom": "Zoom",
        "outlook": "Outlook",
        "task manager": "Task Manager",
        "settings": "Settings",
        "calculator": "Calculator",
        "paint": "Paint",
        "photos": "Photos",
        "movies & tv": "Movies",
        "vlc": "VLC",
        "youtube": "YouTube (browser)",
        "gmail": "Gmail (browser)",
        "chintu": "Chintu",
        "antigravity": "Antigravity",
        "gemini": "Gemini",
    }
    
    # Check known patterns
    for pattern, app_name in APP_PATTERNS.items():
        if pattern in title_lower:
            return app_name
    
    # If no pattern matches, try to extract app name from title
    # Common formats: "Document - App Name" or "App Name - Document"
    if " - " in title:
        parts = title.split(" - ")
        # Usually the app name is more generic (shorter or known pattern)
        # Try the last part first (most common format: "Doc - App")
        candidate = parts[-1].strip()
        if len(candidate) < 30 and not any(c in candidate for c in ['\\', '/', ':']):
            return candidate
        # Try first part
        candidate = parts[0].strip()
        if len(candidate) < 30 and not any(c in candidate for c in ['\\', '/', ':']):
            return candidate
    
    # Fallback: use the title itself if it's short enough
    if len(title) < 25:
        return title
    
    return title[:25] + "..."


