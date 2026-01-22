"""Screen capture and analysis module.

Provides capabilities for:
- Taking screenshots
- Analyzing screen content
- OCR text extraction
- Window detection
"""

import logging
import io
import tempfile
from typing import Optional, Dict, Any, Tuple
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Try to import screen capture libraries
try:
    from PIL import ImageGrab, Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("PIL not available. Screen capture will be limited.")

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False


@dataclass
class ScreenCapture:
    """Represents a captured screenshot."""
    image: Any  # PIL Image
    timestamp: str
    path: Optional[Path] = None
    width: int = 0
    height: int = 0
    

class ScreenCaptureManager:
    """Manages screen capture and analysis."""
    
    def __init__(self):
        self._last_capture: Optional[ScreenCapture] = None
        self._captures_dir = Path.home() / ".chintu" / "screenshots"
        self._captures_dir.mkdir(parents=True, exist_ok=True)
        
    def capture_screen(self, save: bool = False, 
                       region: Optional[Tuple[int, int, int, int]] = None) -> Optional[ScreenCapture]:
        """Capture the current screen or a region.
        
        Args:
            save: Whether to save the screenshot to disk
            region: Optional (left, top, right, bottom) region to capture
            
        Returns:
            ScreenCapture if successful, None otherwise
        """
        if not PIL_AVAILABLE:
            logger.error("PIL not available for screen capture")
            return None
            
        try:
            # Capture screen
            if region:
                image = ImageGrab.grab(bbox=region)
            else:
                image = ImageGrab.grab()
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            capture = ScreenCapture(
                image=image,
                timestamp=timestamp,
                width=image.width,
                height=image.height
            )
            
            if save:
                filename = f"screenshot_{timestamp}.png"
                filepath = self._captures_dir / filename
                image.save(filepath)
                capture.path = filepath
                logger.info(f"Screenshot saved to {filepath}")
            
            self._last_capture = capture
            return capture
            
        except Exception as e:
            logger.error(f"Screen capture failed: {e}")
            return None
    
    def capture_active_window(self, save: bool = False) -> Optional[ScreenCapture]:
        """Capture only the active window.
        
        Args:
            save: Whether to save the screenshot to disk
            
        Returns:
            ScreenCapture if successful, None otherwise
        """
        if not PYAUTOGUI_AVAILABLE:
            logger.warning("pyautogui not available, capturing full screen instead")
            return self.capture_screen(save=save)
        
        try:
            # Get active window
            import pygetwindow as gw
            active_window = gw.getActiveWindow()
            
            if active_window:
                left, top, width, height = (
                    active_window.left,
                    active_window.top,
                    active_window.width,
                    active_window.height
                )
                region = (left, top, left + width, top + height)
                return self.capture_screen(save=save, region=region)
            else:
                return self.capture_screen(save=save)
                
        except Exception as e:
            logger.error(f"Active window capture failed: {e}")
            return self.capture_screen(save=save)
    
    def get_last_capture(self) -> Optional[ScreenCapture]:
        """Get the most recent screen capture."""
        return self._last_capture
    
    def extract_text_from_screen(self) -> Optional[str]:
        """Extract text from a screen capture using OCR.
        
        Returns:
            Extracted text or None if OCR not available
        """
        try:
            import pytesseract
            
            if self._last_capture is None:
                self.capture_screen()
            
            if self._last_capture and self._last_capture.image:
                text = pytesseract.image_to_string(self._last_capture.image)
                return text.strip() if text else None
                
        except ImportError:
            logger.warning("pytesseract not available for OCR")
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            
        return None
    
    def get_screen_info(self) -> Dict[str, Any]:
        """Get information about the screen(s).
        
        Returns:
            Dictionary with screen information
        """
        info = {
            "primary_width": 1920,
            "primary_height": 1080,
            "monitors": 1
        }
        
        try:
            if PIL_AVAILABLE:
                # Get screen size from a capture
                screenshot = ImageGrab.grab()
                info["primary_width"] = screenshot.width
                info["primary_height"] = screenshot.height
                
        except Exception as e:
            logger.debug(f"Could not get screen info: {e}")
            
        return info


# Global instance
_screen_manager: Optional[ScreenCaptureManager] = None


def get_screen_manager() -> ScreenCaptureManager:
    """Get the global ScreenCaptureManager instance."""
    global _screen_manager
    if _screen_manager is None:
        _screen_manager = ScreenCaptureManager()
    return _screen_manager
