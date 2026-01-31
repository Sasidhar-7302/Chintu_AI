"""Screen Control Module for Chintu.
Provides capabilities to control mouse and keyboard.
"""

import logging
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import pyautogui
    HAS_PYAUTOGUI = True
    # FAILSAFE: Move mouse to corner to abort
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.5  # Add pause between actions
except ImportError:
    HAS_PYAUTOGUI = False
    logger.warning("pyautogui not installed - screen control disabled")


class ScreenController:
    """Controls mouse and keyboard."""

    def __init__(self):
        self.enabled = HAS_PYAUTOGUI

    def click_at(self, x: int, y: int, clicks: int = 1, button: str = 'left'):
        """Click at specific coordinates."""
        if not self.enabled:
            return False
        try:
            pyautogui.click(x=x, y=y, clicks=clicks, button=button)
            return True
        except pyautogui.FailSafeException:
            logger.warning("Screen control aborted by failsafe")
            return False
        except Exception as e:
            logger.error(f"Click failed: {e}")
            return False

    def type_text(self, text: str, interval: float = 0.05):
        """Type text."""
        if not self.enabled:
            return False
        try:
            pyautogui.write(text, interval=interval)
            return True
        except Exception as e:
            logger.error(f"Typing failed: {e}")
            return False

    def press_key(self, key: str):
        """Press a specific key."""
        if not self.enabled:
            return False
        try:
            pyautogui.press(key)
            return True
        except Exception as e:
            logger.error(f"Key press failed: {e}")
            return False
            
    def scroll(self, amount: int):
        """Scroll usage: positive=up, negative=down."""
        if not self.enabled:
            return False
        try:
            pyautogui.scroll(amount)
            return True
        except Exception as e:
            logger.error(f"Scroll failed: {e}")
            return False
            
    def get_mouse_position(self) -> Tuple[int, int]:
        """Get current mouse (x, y)."""
        if not self.enabled:
            return (0, 0)
        return pyautogui.position()

    def screen_size(self) -> Tuple[int, int]:
        """Get screen resolution."""
        if not self.enabled:
            return (0, 0)
        return pyautogui.size()


_controller = None

def get_screen_controller() -> ScreenController:
    global _controller
    if _controller is None:
        _controller = ScreenController()
    return _controller
