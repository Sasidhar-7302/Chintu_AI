"""
Figma automation helpers for Chintu.
Opens files and exports basic screenshots via browser automation.
"""

import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from chintu_backend.automation.browser.browser_controller import get_browser_controller

logger = logging.getLogger(__name__)


class FigmaAutomation:
    def __init__(self):
        self.browser = get_browser_controller(headless=False, profile_name="figma")

    def open(self, url: str) -> bool:
        try:
            self.browser.open_url(url, wait_for="domcontentloaded")
            return True
        except Exception as exc:
            logger.warning("Failed to open Figma url: %s", exc)
            return False

    def export_snapshot(self, filename: Optional[str] = None) -> Optional[str]:
        try:
            stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            name = filename or f"figma_{stamp}.png"
            return self.browser.take_screenshot(name)
        except Exception as exc:
            logger.warning("Figma snapshot failed: %s", exc)
            return None
