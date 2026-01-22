"""
User Preferences System for Chintu Assistant.
Provides structured preference storage that persists across sessions.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, Any, Dict, List
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class UserPreferences:
    """
    Structured user preferences that persist across sessions.
    LLM reads these preferences, does not infer them every time.
    """
    # Response preferences
    response_style: str = "balanced"  # "concise", "balanced", "detailed"
    response_language: str = "english"
    use_humor: bool = True
    
    # App preferences
    default_browser: str = "chrome"
    default_editor: str = "vscode"
    preferred_apps: Dict[str, str] = field(default_factory=dict)  # category -> app
    
    # Behavior preferences
    confirmation_required: bool = False  # Ask before destructive actions
    auto_listen_after_response: bool = True  # Conversation mode
    wake_word_enabled: bool = True
    
    # Voice preferences
    tts_voice: str = "en-US-AriaNeural"
    tts_speed: float = 1.0
    
    # Memory preferences
    save_conversations: bool = True
    conversation_memory_days: int = 30  # How long to keep conversation history
    
    # User info (explicitly set by user)
    user_name: Optional[str] = None
    location: Optional[str] = None
    timezone: Optional[str] = None
    
    # Learned preferences (updated based on usage)
    frequently_used_apps: List[str] = field(default_factory=list)
    frequently_visited_sites: List[str] = field(default_factory=list)
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def update(self, **kwargs) -> None:
        """Update preferences with validation."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
                logger.debug(f"Updated preference: {key} = {value}")
            else:
                logger.warning(f"Unknown preference: {key}")
        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserPreferences":
        """Create from dictionary."""
        # Filter only known fields
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)
    
    def get_context_string(self) -> str:
        """Get preferences as a context string for LLM."""
        parts = []
        
        if self.user_name:
            parts.append(f"User's name is {self.user_name}.")
        
        if self.location:
            parts.append(f"User is located in {self.location}.")
        
        parts.append(f"Response style preference: {self.response_style}.")
        
        if self.frequently_used_apps:
            apps = ", ".join(self.frequently_used_apps[:5])
            parts.append(f"Frequently used apps: {apps}.")
        
        return " ".join(parts)


class PreferenceManager:
    """
    Manages user preferences with persistence.
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or Path.home() / ".chintu" / "preferences.json"
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._preferences: Optional[UserPreferences] = None
        self._load()
        logger.info(f"PreferenceManager initialized: {self.storage_path}")
    
    def _load(self) -> None:
        """Load preferences from disk."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._preferences = UserPreferences.from_dict(data)
                
                # Enforce Sasidhar's Identity if missing
                if not self._preferences.user_name or self._preferences.user_name == "User":
                    self._preferences.user_name = "S"
                    self._save()
                    
                logger.info("Loaded user preferences from disk")
            except Exception as e:
                logger.error(f"Failed to load preferences: {e}")
                self._preferences = UserPreferences(user_name="S")
                self._save()
        else:
            self._preferences = UserPreferences(user_name="S")
            self._save()  # Create default file
    
    def _save(self) -> None:
        """Save preferences to disk."""
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self._preferences.to_dict(), f, indent=2)
            logger.debug("Saved user preferences to disk")
        except Exception as e:
            logger.error(f"Failed to save preferences: {e}")
    
    @property
    def preferences(self) -> UserPreferences:
        """Get current preferences."""
        return self._preferences
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a specific preference value."""
        return getattr(self._preferences, key, default)
    
    def set(self, key: str, value: Any) -> bool:
        """Set a preference and save."""
        if not hasattr(self._preferences, key):
            logger.warning(f"Unknown preference: {key}")
            return False
        
        setattr(self._preferences, key, value)
        self._preferences.updated_at = datetime.now().isoformat()
        self._save()
        logger.info(f"Set preference: {key} = {value}")
        return True
    
    def update(self, **kwargs) -> None:
        """Update multiple preferences at once."""
        self._preferences.update(**kwargs)
        self._save()
    
    def track_app_usage(self, app_name: str) -> None:
        """Track frequently used apps."""
        apps = self._preferences.frequently_used_apps
        if app_name in apps:
            apps.remove(app_name)
        apps.insert(0, app_name)
        self._preferences.frequently_used_apps = apps[:10]  # Keep top 10
        self._save()
    
    def track_site_usage(self, site: str) -> None:
        """Track frequently visited sites."""
        sites = self._preferences.frequently_visited_sites
        if site in sites:
            sites.remove(site)
        sites.insert(0, site)
        self._preferences.frequently_visited_sites = sites[:10]
        self._save()
    
    def reset(self) -> None:
        """Reset to default preferences."""
        self._preferences = UserPreferences()
        self._save()
        logger.info("Reset preferences to defaults")
    
    def export(self) -> Dict[str, Any]:
        """Export preferences for backup."""
        return self._preferences.to_dict()
    
    def import_preferences(self, data: Dict[str, Any]) -> None:
        """Import preferences from backup."""
        self._preferences = UserPreferences.from_dict(data)
        self._save()
        logger.info("Imported preferences")


# Global instance
_preference_manager: Optional[PreferenceManager] = None


def get_preference_manager() -> PreferenceManager:
    """Get or create the global preference manager."""
    global _preference_manager
    if _preference_manager is None:
        _preference_manager = PreferenceManager()
    return _preference_manager
