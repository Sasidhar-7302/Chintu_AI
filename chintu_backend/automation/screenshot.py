"""
Screenshot Utility for Chintu AI Assistant.

Provides screenshot capabilities:
- Full screen capture
- Window capture
- Region capture
- Save to file
"""

import os
import logging
from datetime import datetime
from typing import Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class ScreenshotManager:
    """
    Manages screenshot capture.
    
    Features:
    - Full screen capture
    - Active window capture
    - Region selection
    - Auto-save with timestamp
    """
    
    def __init__(self, save_dir: Optional[str] = None):
        """
        Initialize screenshot manager.
        
        Args:
            save_dir: Directory to save screenshots
        """
        self.save_dir = save_dir or str(
            Path.home() / 'Pictures' / 'Chintu Screenshots'
        )
        
        # Ensure directory exists
        os.makedirs(self.save_dir, exist_ok=True)
        
    @property
    def is_available(self) -> bool:
        """Check if screenshots are available."""
        return HAS_PYAUTOGUI
    
    def capture_screen(self, save: bool = True) -> Optional[str]:
        """
        Capture the entire screen.
        
        Args:
            save: Whether to save to file
            
        Returns:
            File path if saved, None otherwise
        """
        if not HAS_PYAUTOGUI:
            logger.error("pyautogui not available")
            return None
        
        try:
            screenshot = pyautogui.screenshot()
            
            if save:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}.png"
                filepath = os.path.join(self.save_dir, filename)
                screenshot.save(filepath)
                logger.info(f"Screenshot saved: {filepath}")
                return filepath
            
            return None
            
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return None
    
    def capture_region(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        save: bool = True
    ) -> Optional[str]:
        """
        Capture a specific region.
        
        Args:
            x, y: Top-left corner
            width, height: Region size
            save: Whether to save to file
            
        Returns:
            File path if saved
        """
        if not HAS_PYAUTOGUI:
            return None
        
        try:
            screenshot = pyautogui.screenshot(region=(x, y, width, height))
            
            if save:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"region_{timestamp}.png"
                filepath = os.path.join(self.save_dir, filename)
                screenshot.save(filepath)
                return filepath
            
            return None
            
        except Exception as e:
            logger.error(f"Region capture failed: {e}")
            return None
    
    def capture_active_window(self, save: bool = True) -> Optional[str]:
        """
        Capture the currently active window.
        
        Returns:
            File path if saved
        """
        try:
            import pygetwindow as gw
            
            active = gw.getActiveWindow()
            if not active:
                logger.warning("No active window found")
                return self.capture_screen(save)
            
            # Get window bounds
            x, y = active.left, active.top
            width, height = active.width, active.height
            
            # Ensure valid bounds
            if width <= 0 or height <= 0:
                return self.capture_screen(save)
            
            return self.capture_region(x, y, width, height, save)
            
        except ImportError:
            logger.warning("pygetwindow not available, capturing full screen")
            return self.capture_screen(save)
        except Exception as e:
            logger.error(f"Window capture failed: {e}")
            return self.capture_screen(save)
    
    def get_latest_screenshot(self) -> Optional[str]:
        """Get path to the most recent screenshot."""
        try:
            files = list(Path(self.save_dir).glob("*.png"))
            if not files:
                return None
            
            latest = max(files, key=lambda f: f.stat().st_mtime)
            return str(latest)
            
        except Exception as e:
            logger.error(f"Error finding latest screenshot: {e}")
            return None
    
    def list_screenshots(self, count: int = 10) -> list:
        """List recent screenshots."""
        try:
            files = list(Path(self.save_dir).glob("*.png"))
            files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            return [str(f) for f in files[:count]]
        except Exception:
            return []


# Global instance
_screenshot: Optional[ScreenshotManager] = None


def get_screenshot_manager() -> ScreenshotManager:
    """Get or create the global screenshot manager."""
    global _screenshot
    if _screenshot is None:
        _screenshot = ScreenshotManager()
    return _screenshot


def take_screenshot() -> Optional[str]:
    """Convenience function to take a screenshot."""
    return get_screenshot_manager().capture_screen()
