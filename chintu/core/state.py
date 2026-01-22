"""State management for the assistant."""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
import time
import logging

logger = logging.getLogger(__name__)


class AssistantState(Enum):
    """States of the Chintu assistant."""
    IDLE = "idle"                    # Waiting for wake word
    LISTENING = "listening"          # Wake word detected, listening for command
    PROCESSING = "processing"        # Processing command/transcription
    THINKING = "thinking"            # Waiting for LLM response
    SPEAKING = "speaking"            # Playing TTS response
    EXECUTING = "executing"          # Executing an action
    ERROR = "error"                  # Error state


@dataclass
class FeatureStatus:
    """Status of a feature in the capability panel."""
    name: str
    enabled: bool = True
    status: str = "inactive"  # inactive, testing, active
    last_used: Optional[datetime] = None
    error_message: Optional[str] = None


@dataclass
class SystemState:
    """Complete system state."""
    assistant_state: AssistantState = AssistantState.IDLE
    current_transcript: str = ""
    last_command: str = ""
    last_response: str = ""
    last_response_raw: str = ""
    last_capability: str = ""
    last_model: str = ""
    trace_id: str = ""
    audio_level: float = 0.0
    
    # Feature statuses
    features: Dict[str, FeatureStatus] = field(default_factory=lambda: {
        "wake_word": FeatureStatus("Wake Word"),
        "voice_commands": FeatureStatus("Voice Commands"),
        "hand_gestures": FeatureStatus("Hand Gestures"),
        "app_control": FeatureStatus("App Control"),
        "job_search": FeatureStatus("Job Search"),
        "llm_integration": FeatureStatus("LLM Integration"),
    })
    
    # Detected entities
    detected_hand: bool = False
    current_gesture: Optional[str] = None
    
    # Session tracking
    last_opened_app: Optional[str] = None
    
    # Session context (captured at wake word for consistent window state)
    session_foreground_window: Optional[str] = None
    session_visible_windows: List[str] = field(default_factory=list)
    session_snapshot_time: Optional[datetime] = None


class StateManager:
    """Manages the system state and notifies listeners of changes."""
    
    def __init__(self):
        self._state = SystemState()
        self._listeners: List[Callable[[SystemState], None]] = []
        self._last_audio_notify = 0.0
        self._audio_notify_interval = 0.05  # seconds
        self._audio_level_epsilon = 0.01
    
    @property
    def state(self) -> SystemState:
        """Get the current state."""
        return self._state
    
    @property
    def assistant_state(self) -> AssistantState:
        """Get the current assistant state."""
        return self._state.assistant_state
    
    def set_last_opened_app(self, app_name: str):
        """Update the last opened application."""
        self._state.last_opened_app = app_name
        self._notify_listeners()
    
    def capture_window_snapshot(self):
        """
        Capture current window state for consistent context during command handling.
        Called at wake word detection so window state is frozen for the session.
        """
        from datetime import datetime
        try:
            from chintu.automation.window_services import get_open_windows
            
            # Get visible windows
            windows = get_open_windows()
            self._state.session_visible_windows = windows if windows else []
            
            # Get foreground window (first or most relevant)
            if windows:
                self._state.session_foreground_window = windows[0] if windows else None
            else:
                self._state.session_foreground_window = None
            
            self._state.session_snapshot_time = datetime.now()
            logger.info(f"Window snapshot captured: {len(self._state.session_visible_windows)} windows")
            
        except Exception as e:
            logger.warning(f"Failed to capture window snapshot: {e}")
            self._state.session_visible_windows = []
            self._state.session_foreground_window = None
            self._state.session_snapshot_time = datetime.now()
    
    def get_session_windows(self) -> List[str]:
        """Get the captured session windows (from snapshot, not live)."""
        return self._state.session_visible_windows
    
    def get_foreground_window(self) -> Optional[str]:
        """Get the captured foreground window (from snapshot)."""
        return self._state.session_foreground_window
    
    def set_assistant_state(self, new_state: AssistantState):
        """Update the assistant state."""
        if self._state.assistant_state != new_state:
            logger.info(f"State change: {self._state.assistant_state.value} -> {new_state.value}")
            self._state.assistant_state = new_state
            self._notify_listeners()
    
    def update_audio_level(self, level: float):
        """Update the audio level (0.0 to 1.0)."""
        level = float(max(0.0, min(1.0, level)))
        prev_level = self._state.audio_level
        self._state.audio_level = level

        now = time.monotonic()
        if (abs(level - prev_level) >= self._audio_level_epsilon or
                (now - self._last_audio_notify) >= self._audio_notify_interval):
            self._last_audio_notify = now
            self._notify_listeners()
    
    def set_transcript(self, transcript: str, is_final: bool = False):
        """Update the current transcript."""
        self._state.current_transcript = transcript
        if is_final:
            self._state.last_command = transcript
        self._notify_listeners()
    
    def set_response(self, response: str, raw: Optional[str] = None):
        """Set the last response (display + raw)."""
        self._state.last_response = response
        self._state.last_response_raw = response if raw is None else raw
        self._notify_listeners()

    def set_debug_info(self, last_capability: Optional[str] = None,
                       last_model: Optional[str] = None,
                       trace_id: Optional[str] = None):
        """Update debug metadata for UI/telemetry."""
        if last_capability is not None:
            self._state.last_capability = last_capability
        if last_model is not None:
            self._state.last_model = last_model
        if trace_id is not None:
            self._state.trace_id = trace_id
        self._notify_listeners()
    
    def update_feature(self, feature_name: str, enabled: bool = None, 
                       status: str = None, error: str = None):
        """Update a feature's status."""
        if feature_name in self._state.features:
            feature = self._state.features[feature_name]
            if enabled is not None:
                feature.enabled = enabled
            if status is not None:
                feature.status = status
            if error is not None:
                feature.error_message = error
            feature.last_used = datetime.now()
            self._notify_listeners()
    
    def set_hand_detected(self, detected: bool, gesture: Optional[str] = None):
        """Update hand detection state."""
        self._state.detected_hand = detected
        self._state.current_gesture = gesture
        self._notify_listeners()
    
    def add_listener(self, callback: Callable[[SystemState], None]):
        """Add a state change listener."""
        self._listeners.append(callback)
    
    def remove_listener(self, callback: Callable[[SystemState], None]):
        """Remove a state change listener."""
        self._listeners = [l for l in self._listeners if l != callback]
    
    def _notify_listeners(self):
        """Notify all listeners of state change."""
        for listener in self._listeners:
            try:
                listener(self._state)
            except Exception as e:
                logger.error(f"Error in state listener: {e}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for JSON serialization."""
        return {
            "assistant_state": self._state.assistant_state.value,
            "transcript": self._state.current_transcript,
            "last_command": self._state.last_command,
            "last_response": self._state.last_response,
            "last_response_raw": self._state.last_response_raw,
            "last_capability": self._state.last_capability,
            "last_model": self._state.last_model,
            "trace_id": self._state.trace_id,
            "audio_level": float(self._state.audio_level),
            "detected_hand": self._state.detected_hand,
            "current_gesture": self._state.current_gesture,
            "features": {
                name: {
                    "name": f.name,
                    "enabled": f.enabled,
                    "status": f.status,
                    "error": f.error_message,
                }
                for name, f in self._state.features.items()
            }
        }


# Global state manager
_state_manager: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """Get or create the global state manager."""
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager
