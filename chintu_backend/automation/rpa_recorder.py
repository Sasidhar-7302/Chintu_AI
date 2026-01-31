"""RPA Recording - Record and replay user actions.

Uses free libraries: pynput for recording, pyautogui for replay.
Records mouse clicks, keyboard input, and timing with natural variations.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import random
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from pynput import mouse, keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False
    logger.warning("pynput not installed. Install with: pip install pynput")

try:
    import pyautogui
    HAS_PYAUTOGUI = True
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.1
except ImportError:
    HAS_PYAUTOGUI = False


@dataclass
class RecordedAction:
    """A single recorded action."""
    type: str           # "click", "type", "key", "scroll", "move"
    timestamp: float    # Seconds since recording start
    x: int = 0
    y: int = 0
    button: str = ""    # "left", "right", "middle"
    key: str = ""       # Key name
    text: str = ""      # Typed text
    scroll_amount: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecordedAction":
        return cls(**data)


@dataclass
class Recording:
    """A complete recording of user actions."""
    name: str
    created_at: str
    duration: float
    actions: List[RecordedAction]
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "duration": self.duration,
            "actions": [a.to_dict() for a in self.actions],
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Recording":
        return cls(
            name=data["name"],
            created_at=data["created_at"],
            duration=data["duration"],
            actions=[RecordedAction.from_dict(a) for a in data["actions"]],
            metadata=data.get("metadata", {}),
        )
    
    def save(self, path: Path) -> None:
        """Save recording to file."""
        path.write_text(json.dumps(self.to_dict(), indent=2))
        logger.info("Recording saved to %s", path)
    
    @classmethod
    def load(cls, path: Path) -> "Recording":
        """Load recording from file."""
        data = json.loads(path.read_text())
        return cls.from_dict(data)


class RPARecorder:
    """Records user mouse and keyboard actions.
    
    Features:
    - Record mouse clicks with position
    - Record keyboard input (keys and text)
    - Record scroll actions
    - Save/load recordings as JSON
    - Natural timing preservation
    """

    def __init__(self):
        self._recording = False
        self._actions: List[RecordedAction] = []
        self._start_time: float = 0
        self._mouse_listener = None
        self._keyboard_listener = None
        self._typed_buffer: List[str] = []
        self._last_key_time: float = 0

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start_recording(self) -> bool:
        """Start recording user actions.
        
        Returns:
            True if recording started successfully
        """
        if not HAS_PYNPUT:
            logger.error("pynput required for recording")
            return False
        
        if self._recording:
            return False
        
        self._actions = []
        self._typed_buffer = []
        self._start_time = time.time()
        self._recording = True
        
        # Mouse listener
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._mouse_listener.start()
        
        # Keyboard listener
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
        )
        self._keyboard_listener.start()
        
        logger.info("RPA Recording started. Press ESC to stop.")
        return True

    def stop_recording(self, name: str = "recording") -> Optional[Recording]:
        """Stop recording and return the recording.
        
        Args:
            name: Name for this recording
            
        Returns:
            Recording object or None
        """
        if not self._recording:
            return None
        
        self._recording = False
        
        # Stop listeners
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._keyboard_listener:
            self._keyboard_listener.stop()
        
        # Flush any buffered typing
        self._flush_typed_buffer()
        
        duration = time.time() - self._start_time
        
        recording = Recording(
            name=name,
            created_at=datetime.now().isoformat(),
            duration=duration,
            actions=self._actions.copy(),
            metadata={
                "action_count": len(self._actions),
            }
        )
        
        logger.info("Recording stopped: %d actions in %.1fs", len(self._actions), duration)
        return recording

    def _get_timestamp(self) -> float:
        """Get current timestamp relative to recording start."""
        return time.time() - self._start_time

    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        """Handle mouse click event."""
        if not self._recording or not pressed:
            return
        
        # Flush any pending typed text first
        self._flush_typed_buffer()
        
        button_name = str(button).split(".")[-1]  # "Button.left" -> "left"
        
        action = RecordedAction(
            type="click",
            timestamp=self._get_timestamp(),
            x=x,
            y=y,
            button=button_name,
        )
        self._actions.append(action)
        logger.debug("Recorded click at (%d, %d)", x, y)

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        """Handle scroll event."""
        if not self._recording:
            return
        
        action = RecordedAction(
            type="scroll",
            timestamp=self._get_timestamp(),
            x=x,
            y=y,
            scroll_amount=dy,
        )
        self._actions.append(action)

    def _on_key_press(self, key) -> bool:
        """Handle key press event."""
        if not self._recording:
            return True
        
        # Check for ESC to stop recording
        try:
            if key == keyboard.Key.esc:
                threading.Thread(target=lambda: self.stop_recording()).start()
                return False
        except:
            pass
        
        current_time = self._get_timestamp()
        
        try:
            # Regular character
            char = key.char
            if char:
                # If too much time has passed, flush buffer
                if current_time - self._last_key_time > 2.0 and self._typed_buffer:
                    self._flush_typed_buffer()
                
                self._typed_buffer.append(char)
                self._last_key_time = current_time
        except AttributeError:
            # Special key
            self._flush_typed_buffer()
            
            key_name = str(key).split(".")[-1]  # "Key.enter" -> "enter"
            action = RecordedAction(
                type="key",
                timestamp=current_time,
                key=key_name,
            )
            self._actions.append(action)
        
        return True

    def _flush_typed_buffer(self) -> None:
        """Flush accumulated typed characters as a single type action."""
        if not self._typed_buffer:
            return
        
        text = "".join(self._typed_buffer)
        action = RecordedAction(
            type="type",
            timestamp=self._last_key_time,
            text=text,
        )
        self._actions.append(action)
        self._typed_buffer = []


class RPAPlayer:
    """Replays recorded user actions.
    
    Features:
    - Play recordings at original or adjusted speed
    - Add natural timing variations
    - Skip failed actions
    - Progress callbacks
    """

    def __init__(self):
        self._playing = False
        self._stop_requested = False

    @property
    def is_playing(self) -> bool:
        return self._playing

    def stop(self) -> None:
        """Request playback to stop."""
        self._stop_requested = True

    def play(
        self,
        recording: Recording,
        speed: float = 1.0,
        natural_variation: bool = True,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """Play back a recording.
        
        Args:
            recording: The recording to play
            speed: Playback speed multiplier (2.0 = 2x faster)
            natural_variation: Add small random delays for natural feel
            on_progress: Callback(current_index, total_count) for progress
            
        Returns:
            True if playback completed, False if stopped or errored
        """
        if not HAS_PYAUTOGUI:
            logger.error("pyautogui required for playback")
            return False
        
        if self._playing:
            return False
        
        self._playing = True
        self._stop_requested = False
        
        actions = recording.actions
        total = len(actions)
        last_timestamp = 0.0
        
        logger.info("Playing %d actions at %.1fx speed", total, speed)
        
        try:
            for i, action in enumerate(actions):
                if self._stop_requested:
                    logger.info("Playback stopped by user")
                    break
                
                # Wait for proper timing
                delay = (action.timestamp - last_timestamp) / speed
                if delay > 0:
                    if natural_variation:
                        delay *= random.uniform(0.9, 1.1)  # ±10% variation
                    time.sleep(min(delay, 10))  # Cap at 10 seconds
                
                last_timestamp = action.timestamp
                
                # Execute action
                success = self._execute_action(action)
                if not success:
                    logger.warning("Action %d failed: %s", i, action.type)
                
                # Progress callback
                if on_progress:
                    on_progress(i + 1, total)
            
            logger.info("Playback complete")
            return not self._stop_requested
            
        except pyautogui.FailSafeException:
            logger.warning("Playback aborted by failsafe (moved mouse to corner)")
            return False
        except Exception as exc:
            logger.error("Playback error: %s", exc)
            return False
        finally:
            self._playing = False

    def _execute_action(self, action: RecordedAction) -> bool:
        """Execute a single recorded action."""
        try:
            if action.type == "click":
                button = action.button or "left"
                pyautogui.click(action.x, action.y, button=button)
                
            elif action.type == "type":
                pyautogui.write(action.text, interval=0.02)
                
            elif action.type == "key":
                pyautogui.press(action.key)
                
            elif action.type == "scroll":
                pyautogui.scroll(action.scroll_amount, action.x, action.y)
                
            elif action.type == "move":
                pyautogui.moveTo(action.x, action.y)
                
            else:
                logger.warning("Unknown action type: %s", action.type)
                return False
            
            return True
            
        except Exception as exc:
            logger.debug("Action failed: %s", exc)
            return False


class RPAManager:
    """High-level RPA manager for recording and playback."""

    def __init__(self):
        from chintu_backend.core.config import get_config
        self.config = get_config()
        self.recordings_dir = self.config.data_dir / "rpa_recordings"
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        
        self.recorder = RPARecorder()
        self.player = RPAPlayer()

    def start_recording(self) -> bool:
        """Start recording user actions."""
        return self.recorder.start_recording()

    def stop_recording(self, name: str) -> Optional[str]:
        """Stop recording and save to file.
        
        Returns:
            Path to saved recording file, or None
        """
        recording = self.recorder.stop_recording(name)
        if not recording:
            return None
        
        # Save to file
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_name}_{timestamp}.json"
        path = self.recordings_dir / filename
        
        recording.save(path)
        return str(path)

    def list_recordings(self) -> List[Dict[str, Any]]:
        """List all saved recordings."""
        recordings = []
        for path in self.recordings_dir.glob("*.json"):
            try:
                rec = Recording.load(path)
                recordings.append({
                    "name": rec.name,
                    "file": path.name,
                    "path": str(path),
                    "created_at": rec.created_at,
                    "duration": rec.duration,
                    "action_count": len(rec.actions),
                })
            except Exception:
                pass
        return sorted(recordings, key=lambda x: x["created_at"], reverse=True)

    def play_recording(
        self, 
        name_or_path: str, 
        speed: float = 1.0
    ) -> bool:
        """Play a saved recording.
        
        Args:
            name_or_path: Recording name or full path
            speed: Playback speed multiplier
            
        Returns:
            True if playback completed successfully
        """
        path = Path(name_or_path)
        if not path.exists():
            # Try finding by name
            for p in self.recordings_dir.glob("*.json"):
                if name_or_path in p.name:
                    path = p
                    break
        
        if not path.exists():
            logger.error("Recording not found: %s", name_or_path)
            return False
        
        recording = Recording.load(path)
        return self.player.play(recording, speed=speed)

    def delete_recording(self, name_or_path: str) -> bool:
        """Delete a saved recording."""
        path = Path(name_or_path)
        if not path.exists():
            for p in self.recordings_dir.glob("*.json"):
                if name_or_path in p.name:
                    path = p
                    break
        
        if path.exists():
            path.unlink()
            logger.info("Deleted recording: %s", path)
            return True
        return False


# Singleton
_rpa_manager: Optional[RPAManager] = None


def get_rpa_manager() -> RPAManager:
    """Get or create the global RPA Manager."""
    global _rpa_manager
    if _rpa_manager is None:
        _rpa_manager = RPAManager()
    return _rpa_manager
