"""
Context Awareness for Chintu AI Assistant.

Provides awareness of current user context:
- Active application
- Active window title
- Recent activity
- System state

Enables context-aware responses and actions.
"""

import os
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    import pygetwindow as gw
    HAS_GETWINDOW = True
except ImportError:
    HAS_GETWINDOW = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


@dataclass
class AppContext:
    """Context about the currently active application."""
    app_name: str
    window_title: str
    process_name: str
    category: str  # browser, editor, media, etc.
    timestamp: str


class ContextAwareness:
    """
    Tracks and provides current user context.
    
    Features:
    - Active application detection
    - Window title tracking
    - App categorization
    - Context history
    """
    
    # App categorization
    APP_CATEGORIES = {
        # Browsers
        "chrome": "browser", "firefox": "browser", "edge": "browser", 
        "brave": "browser", "opera": "browser", "safari": "browser",
        
        # Editors/IDEs
        "code": "editor", "vscode": "editor", "notepad": "editor",
        "sublime": "editor", "atom": "editor", "pycharm": "editor",
        "visual studio": "editor", "intellij": "editor", "vim": "editor",
        
        # Media
        "spotify": "media", "vlc": "media", "netflix": "media",
        "youtube": "media", "prime video": "media", "music": "media",
        
        # Communication
        "slack": "communication", "discord": "communication", 
        "teams": "communication", "zoom": "communication",
        "outlook": "communication", "gmail": "communication",
        
        # Productivity
        "word": "document", "excel": "spreadsheet", "powerpoint": "presentation",
        "docs": "document", "sheets": "spreadsheet", "slides": "presentation",
        
        # Terminal
        "terminal": "terminal", "cmd": "terminal", "powershell": "terminal",
        "wt": "terminal", "iterm": "terminal", "bash": "terminal",
        
        # File management
        "explorer": "files", "finder": "files",
    }
    
    def __init__(self, max_history: int = 20):
        """
        Initialize context awareness.
        
        Args:
            max_history: Maximum context history entries
        """
        self.max_history = max_history
        self._history: List[AppContext] = []
        self._current: Optional[AppContext] = None
        
    def get_active_context(self) -> Optional[AppContext]:
        """
        Get the current active application context.
        
        Returns:
            AppContext or None
        """
        if not HAS_GETWINDOW:
            return None
        
        try:
            active = gw.getActiveWindow()
            if not active:
                return None
            
            title = active.title or "Unknown"
            
            # Extract app name from title
            app_name = self._extract_app_name(title)
            
            # Get process name if possible
            process_name = ""
            if HAS_PSUTIL:
                try:
                    # This is platform-specific
                    import win32gui
                    import win32process
                    hwnd = win32gui.GetForegroundWindow()
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    process = psutil.Process(pid)
                    process_name = process.name()
                except:
                    pass
            
            # Categorize
            category = self._categorize_app(app_name, process_name, title)
            
            context = AppContext(
                app_name=app_name,
                window_title=title,
                process_name=process_name,
                category=category,
                timestamp=datetime.now().isoformat(),
            )
            
            # Update current and history
            self._current = context
            self._add_to_history(context)
            
            return context
            
        except Exception as e:
            logger.debug(f"Failed to get active context: {e}")
            return None
    
    def _extract_app_name(self, title: str) -> str:
        """Extract application name from window title."""
        # Common patterns: "Document - App Name" or "App Name - Document"
        if " - " in title:
            parts = title.split(" - ")
            # Usually app name is at the end
            return parts[-1].strip()
        
        if " | " in title:
            parts = title.split(" | ")
            return parts[-1].strip()
        
        return title.split()[0] if title else "Unknown"
    
    def _categorize_app(self, app_name: str, process_name: str, title: str) -> str:
        """Categorize the application."""
        # Check app name
        app_lower = app_name.lower()
        for keyword, category in self.APP_CATEGORIES.items():
            if keyword in app_lower:
                return category
        
        # Check process name
        if process_name:
            proc_lower = process_name.lower()
            for keyword, category in self.APP_CATEGORIES.items():
                if keyword in proc_lower:
                    return category
        
        # Check title
        title_lower = title.lower()
        for keyword, category in self.APP_CATEGORIES.items():
            if keyword in title_lower:
                return category
        
        return "other"
    
    def _add_to_history(self, context: AppContext):
        """Add context to history, avoiding duplicates."""
        # Don't add if same as last entry
        if self._history:
            last = self._history[-1]
            if (last.app_name == context.app_name and 
                last.window_title == context.window_title):
                return
        
        self._history.append(context)
        
        # Trim history
        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history:]
    
    def get_context_summary(self) -> str:
        """Get a summary of current context for LLM."""
        context = self.get_active_context()
        
        if not context:
            return "No active window detected."
        
        summary = f"User is in {context.app_name}"
        
        if context.category == "browser":
            summary += f" viewing: {context.window_title}"
        elif context.category == "editor":
            summary += f" editing: {context.window_title}"
        elif context.category == "document":
            summary += f" working on: {context.window_title}"
        else:
            summary += f" ({context.window_title})"
        
        return summary
    
    def get_context_hints(self) -> Dict[str, Any]:
        """
        Get context hints for capability routing.
        
        Returns:
            Dict with hints like preferred_actions, related_capabilities, etc.
        """
        context = self.get_active_context()
        
        if not context:
            return {}
        
        hints = {
            "app_name": context.app_name,
            "category": context.category,
            "preferred_actions": [],
        }
        
        # Add category-specific hints
        if context.category == "browser":
            hints["preferred_actions"] = ["read_page", "search", "navigate"]
        elif context.category == "editor":
            hints["preferred_actions"] = ["code_help", "search_docs", "run_command"]
        elif context.category == "document":
            hints["preferred_actions"] = ["summarize", "format", "export"]
        elif context.category == "communication":
            hints["preferred_actions"] = ["draft_reply", "summarize_thread"]
        
        return hints
    
    def get_recent_apps(self, count: int = 5) -> List[str]:
        """Get list of recently used applications."""
        seen = set()
        recent = []
        
        for context in reversed(self._history):
            if context.app_name not in seen:
                seen.add(context.app_name)
                recent.append(context.app_name)
                if len(recent) >= count:
                    break
        
        return recent


# Global instance
_context: Optional[ContextAwareness] = None


def get_context_awareness() -> ContextAwareness:
    """Get or create the global context awareness."""
    global _context
    if _context is None:
        _context = ContextAwareness()
    return _context


def get_active_app() -> str:
    """Get the currently active application name."""
    ctx = get_context_awareness().get_active_context()
    return ctx.app_name if ctx else "Unknown"
