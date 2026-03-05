
import logging
from typing import Set, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class ActionRecord:
    action_type: str  # "open_app", "create_file", etc.
    target: str       # "notepad", "c:/foo.txt"
    timestamp: datetime = field(default_factory=datetime.now)
    details: Dict[str, Any] = field(default_factory=dict) # e.g. {"pid": 1234}

class ActionHistory:
    """
    Tracks actions performed by Chintu during the current session.
    Used for policy decisions (e.g. "allow closing apps I opened").
    """
    
    def __init__(self):
        self._actions: list[ActionRecord] = []
        self._opened_apps: Set[str] = set() # Track app names/exes
        self._created_files: Set[str] = set() # Track file paths

    def log_action(self, action_type: str, target: str, details: Dict[str, Any] = None):
        """Log an action."""
        record = ActionRecord(action_type, target, details=details or {})
        self._actions.append(record)
        
        if action_type == "open_app":
            self._opened_apps.add(target.lower())
        elif action_type == "create_file":
            self._created_files.add(target.lower())
            
        logger.debug(f"Action Logged: {action_type} -> {target}")

    def did_i_open_app(self, app_name: str) -> bool:
        """Check if we opened this app."""
        return app_name.lower() in self._opened_apps

    def did_i_create_file(self, file_path: str) -> bool:
        """Check if we created this file."""
        return file_path.lower() in self._created_files

    def mark_file_created(self, file_path: str):
        """Manually mark a file as created by Chintu."""
        self._created_files.add(file_path.lower())

    def get_recent_actions(self, limit: int = 10) -> list[ActionRecord]:
        return self._actions[-limit:]

# Global instance
_action_history: Optional[ActionHistory] = None

def get_action_history() -> ActionHistory:
    global _action_history
    if _action_history is None:
        _action_history = ActionHistory()
    return _action_history
