"""Multi-monitor support for Chintu automation.

Handles multiple displays, monitor detection, and cross-monitor operations.
Uses free libraries: screeninfo, pyautogui.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from screeninfo import get_monitors, Monitor
    HAS_SCREENINFO = True
except ImportError:
    HAS_SCREENINFO = False
    logger.warning("screeninfo not installed. Install with: pip install screeninfo")

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False


@dataclass
class MonitorInfo:
    """Information about a display monitor."""
    id: int
    name: str
    x: int           # Left edge position
    y: int           # Top edge position  
    width: int
    height: int
    is_primary: bool
    
    @property
    def center(self) -> Tuple[int, int]:
        """Get center coordinates of monitor."""
        return (self.x + self.width // 2, self.y + self.height // 2)
    
    @property
    def bounds(self) -> Tuple[int, int, int, int]:
        """Get (x, y, width, height) bounds."""
        return (self.x, self.y, self.width, self.height)
    
    def contains_point(self, x: int, y: int) -> bool:
        """Check if point is within this monitor."""
        return (self.x <= x < self.x + self.width and 
                self.y <= y < self.y + self.height)


class MultiMonitorController:
    """Controls and coordinates across multiple monitors.
    
    Features:
    - Detect all connected monitors
    - Get monitor under mouse cursor
    - Move cursor between monitors
    - Take screenshots of specific monitors
    - Convert coordinates between monitors
    """

    def __init__(self):
        self._monitors: List[MonitorInfo] = []
        self._refresh_monitors()

    def _refresh_monitors(self) -> None:
        """Refresh the list of connected monitors."""
        self._monitors = []
        
        if HAS_SCREENINFO:
            try:
                for i, m in enumerate(get_monitors()):
                    info = MonitorInfo(
                        id=i,
                        name=m.name or f"Monitor {i+1}",
                        x=m.x,
                        y=m.y,
                        width=m.width,
                        height=m.height,
                        is_primary=m.is_primary,
                    )
                    self._monitors.append(info)
                logger.info("Detected %d monitors", len(self._monitors))
            except Exception as exc:
                logger.warning("Failed to detect monitors: %s", exc)
        
        # Fallback: use pyautogui for single monitor info
        if not self._monitors and HAS_PYAUTOGUI:
            size = pyautogui.size()
            self._monitors.append(MonitorInfo(
                id=0,
                name="Primary",
                x=0,
                y=0,
                width=size.width,
                height=size.height,
                is_primary=True,
            ))

    @property
    def monitors(self) -> List[MonitorInfo]:
        """Get list of all monitors."""
        return self._monitors.copy()

    @property
    def primary_monitor(self) -> Optional[MonitorInfo]:
        """Get the primary monitor."""
        for m in self._monitors:
            if m.is_primary:
                return m
        return self._monitors[0] if self._monitors else None

    @property
    def monitor_count(self) -> int:
        """Get number of connected monitors."""
        return len(self._monitors)

    def get_monitor(self, monitor_id: int) -> Optional[MonitorInfo]:
        """Get monitor by ID."""
        for m in self._monitors:
            if m.id == monitor_id:
                return m
        return None

    def get_monitor_at(self, x: int, y: int) -> Optional[MonitorInfo]:
        """Get the monitor containing the given coordinates."""
        for m in self._monitors:
            if m.contains_point(x, y):
                return m
        return None

    def get_monitor_under_mouse(self) -> Optional[MonitorInfo]:
        """Get the monitor where the mouse cursor is."""
        if not HAS_PYAUTOGUI:
            return self.primary_monitor
        
        try:
            pos = pyautogui.position()
            return self.get_monitor_at(pos.x, pos.y)
        except Exception:
            return self.primary_monitor

    def move_to_monitor(self, monitor_id: int) -> bool:
        """Move mouse cursor to center of specified monitor.
        
        Args:
            monitor_id: ID of target monitor
            
        Returns:
            True if successful
        """
        monitor = self.get_monitor(monitor_id)
        if not monitor or not HAS_PYAUTOGUI:
            return False
        
        try:
            center = monitor.center
            pyautogui.moveTo(center[0], center[1])
            logger.info("Moved to monitor %d at (%d, %d)", monitor_id, *center)
            return True
        except Exception as exc:
            logger.warning("Failed to move to monitor: %s", exc)
            return False

    def click_on_monitor(
        self, 
        monitor_id: int, 
        relative_x: float = 0.5, 
        relative_y: float = 0.5,
        clicks: int = 1
    ) -> bool:
        """Click at relative position on a specific monitor.
        
        Args:
            monitor_id: Target monitor ID
            relative_x: X position as fraction (0.0 = left, 1.0 = right)
            relative_y: Y position as fraction (0.0 = top, 1.0 = bottom)
            clicks: Number of clicks
            
        Returns:
            True if successful
        """
        monitor = self.get_monitor(monitor_id)
        if not monitor or not HAS_PYAUTOGUI:
            return False
        
        try:
            x = monitor.x + int(monitor.width * relative_x)
            y = monitor.y + int(monitor.height * relative_y)
            pyautogui.click(x, y, clicks=clicks)
            logger.info("Clicked on monitor %d at (%d, %d)", monitor_id, x, y)
            return True
        except Exception as exc:
            logger.warning("Click on monitor failed: %s", exc)
            return False

    def screenshot_monitor(
        self, 
        monitor_id: int,
        save_path: Optional[str] = None
    ):
        """Take screenshot of a specific monitor.
        
        Args:
            monitor_id: Target monitor ID
            save_path: Optional path to save screenshot
            
        Returns:
            PIL Image or None
        """
        monitor = self.get_monitor(monitor_id)
        if not monitor or not HAS_PYAUTOGUI:
            return None
        
        try:
            screenshot = pyautogui.screenshot(region=monitor.bounds)
            if save_path:
                screenshot.save(save_path)
                logger.info("Screenshot saved to %s", save_path)
            return screenshot
        except Exception as exc:
            logger.warning("Screenshot failed: %s", exc)
            return None

    def get_virtual_screen_size(self) -> Tuple[int, int, int, int]:
        """Get the bounding box of all monitors combined.
        
        Returns:
            (min_x, min_y, max_x, max_y) covering all monitors
        """
        if not self._monitors:
            return (0, 0, 1920, 1080)
        
        min_x = min(m.x for m in self._monitors)
        min_y = min(m.y for m in self._monitors)
        max_x = max(m.x + m.width for m in self._monitors)
        max_y = max(m.y + m.height for m in self._monitors)
        
        return (min_x, min_y, max_x, max_y)

    def get_status(self) -> str:
        """Get human-readable status of all monitors."""
        if not self._monitors:
            return "No monitors detected"
        
        lines = [f"🖥️ {len(self._monitors)} monitor(s) detected:"]
        for m in self._monitors:
            primary = " (Primary)" if m.is_primary else ""
            lines.append(f"  • {m.name}{primary}: {m.width}x{m.height} at ({m.x}, {m.y})")
        
        return "\n".join(lines)


# Singleton
_controller: Optional[MultiMonitorController] = None


def get_multi_monitor_controller() -> MultiMonitorController:
    """Get or create the global Multi-Monitor Controller."""
    global _controller
    if _controller is None:
        _controller = MultiMonitorController()
    return _controller
