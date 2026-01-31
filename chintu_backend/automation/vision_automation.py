"""Vision-based automation using local Ollama vision models.

Uses LLaVA or other vision models running locally via Ollama to understand
screenshots and find UI elements visually - completely free, no API costs.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import image libraries
try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logger.warning("Pillow not installed - vision automation limited")

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False


class VisionAutomation:
    """Vision-based UI automation using local LLM vision models.
    
    Uses Ollama with LLaVA or similar vision models to:
    - Understand what's on screen
    - Find UI elements by description
    - Click on elements visually
    
    100% free - runs locally on your GPU/CPU.
    """
    
    # Vision models that work with Ollama (ordered by quality/speed)
    VISION_MODELS = [
        "llava:7b",           # Best balance
        "llava:13b",          # More accurate but slower
        "bakllava",           # Alternative
        "llava-llama3",       # Latest
    ]

    def __init__(self, model: str = "llava:7b"):
        self.model = model
        self._ollama_available = None
        self._check_ollama()

    def _check_ollama(self) -> bool:
        """Check if Ollama is available with vision model."""
        if self._ollama_available is not None:
            return self._ollama_available
            
        try:
            import requests
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                # Check if any vision model is available
                for vm in self.VISION_MODELS:
                    if any(vm in name for name in model_names):
                        self.model = vm
                        self._ollama_available = True
                        logger.info("Vision automation using model: %s", self.model)
                        return True
                logger.warning("No vision model found. Install with: ollama pull llava:7b")
            self._ollama_available = False
        except Exception:
            self._ollama_available = False
        return False

    def _capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Optional[Image.Image]:
        """Capture screenshot of screen or region."""
        if not HAS_PYAUTOGUI or not HAS_PIL:
            return None
        try:
            screenshot = pyautogui.screenshot(region=region)
            return screenshot
        except Exception as exc:
            logger.warning("Screenshot failed: %s", exc)
            return None

    def _image_to_base64(self, image: Image.Image, max_size: int = 1024) -> str:
        """Convert PIL Image to base64, resizing if needed."""
        # Resize to reduce token usage while maintaining quality
        if max(image.size) > max_size:
            ratio = max_size / max(image.size)
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.LANCZOS)
        
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    async def _query_vision(self, prompt: str, image: Image.Image) -> str:
        """Query Ollama vision model with image."""
        import aiohttp
        
        image_b64 = self._image_to_base64(image)
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "http://localhost:11434/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("response", "")
        except Exception as exc:
            logger.warning("Vision query failed: %s", exc)
        return ""

    async def describe_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> str:
        """Describe what's currently on screen.
        
        Args:
            region: Optional (x, y, width, height) to capture specific area
            
        Returns:
            Text description of the screen
        """
        if not self._check_ollama():
            return "Vision model not available. Install with: ollama pull llava:7b"
        
        image = self._capture_screen(region)
        if not image:
            return "Failed to capture screen"
        
        prompt = """Describe what you see on this computer screen. 
Include:
- What application/window is open
- Key UI elements visible (buttons, text fields, menus)
- Any important text or information displayed
Be concise but comprehensive."""

        return await self._query_vision(prompt, image)

    async def find_element(
        self, 
        description: str,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Tuple[int, int]]:
        """Find a UI element by visual description.
        
        Args:
            description: What to look for (e.g., "the blue Submit button", "search box")
            region: Optional region to search in
            
        Returns:
            (x, y) coordinates of the element center, or None if not found
        """
        if not self._check_ollama():
            return None
        
        image = self._capture_screen(region)
        if not image:
            return None
        
        # Get screen offset if using region
        offset_x = region[0] if region else 0
        offset_y = region[1] if region else 0
        
        prompt = f"""Find the UI element matching this description: "{description}"

Return ONLY a JSON object with the approximate center coordinates as percentages of the image size:
{{"found": true, "x_percent": 50, "y_percent": 30, "element_name": "Submit Button"}}

If not found:
{{"found": false, "reason": "could not find element"}}

Respond with ONLY the JSON, no other text."""

        response = await self._query_vision(prompt, image)
        
        # Parse the response
        try:
            # Extract JSON from response
            json_match = re.search(r'\{[^}]+\}', response)
            if json_match:
                data = json.loads(json_match.group())
                if data.get("found"):
                    # Convert percentages to actual coordinates
                    x = int(image.width * data["x_percent"] / 100) + offset_x
                    y = int(image.height * data["y_percent"] / 100) + offset_y
                    logger.info("Found element '%s' at (%d, %d)", description, x, y)
                    return (x, y)
        except Exception as exc:
            logger.warning("Failed to parse vision response: %s", exc)
        
        return None

    async def click_element(
        self, 
        description: str,
        region: Optional[Tuple[int, int, int, int]] = None,
        double_click: bool = False
    ) -> bool:
        """Find and click a UI element by visual description.
        
        Args:
            description: What to click (e.g., "the red Close button")
            region: Optional region to search in
            double_click: Whether to double-click
            
        Returns:
            True if element was found and clicked
        """
        coords = await self.find_element(description, region)
        if not coords or not HAS_PYAUTOGUI:
            return False
        
        try:
            x, y = coords
            if double_click:
                pyautogui.doubleClick(x, y)
            else:
                pyautogui.click(x, y)
            logger.info("Clicked at (%d, %d)", x, y)
            return True
        except Exception as exc:
            logger.warning("Click failed: %s", exc)
            return False

    async def read_text_at(
        self, 
        description: str,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> str:
        """Read text from a specific area described visually.
        
        Args:
            description: Where to read (e.g., "the price shown in the cart")
            
        Returns:
            The text found, or empty string
        """
        if not self._check_ollama():
            return ""
        
        image = self._capture_screen(region)
        if not image:
            return ""
        
        prompt = f"""Look at this screenshot and read the text that matches this description:
"{description}"

Return ONLY the exact text you see, nothing else. If you can't find it, return "NOT_FOUND"."""

        response = await self._query_vision(prompt, image)
        return response.strip() if response.strip() != "NOT_FOUND" else ""

    async def get_all_clickable_elements(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> List[Dict[str, Any]]:
        """Get all visible clickable elements on screen.
        
        Returns:
            List of elements with name and approximate position
        """
        if not self._check_ollama():
            return []
        
        image = self._capture_screen(region)
        if not image:
            return []
        
        prompt = """List ALL clickable elements visible on this screen (buttons, links, icons, checkboxes, etc).

Return a JSON array with each element:
[
  {"name": "Search button", "type": "button", "x_percent": 80, "y_percent": 10},
  {"name": "Settings icon", "type": "icon", "x_percent": 95, "y_percent": 5}
]

Only return the JSON array, nothing else."""

        response = await self._query_vision(prompt, image)
        
        try:
            # Extract JSON array
            json_match = re.search(r'\[[\s\S]*\]', response)
            if json_match:
                elements = json.loads(json_match.group())
                # Convert percentages to coordinates
                offset_x = region[0] if region else 0
                offset_y = region[1] if region else 0
                
                for elem in elements:
                    elem["x"] = int(image.width * elem.get("x_percent", 0) / 100) + offset_x
                    elem["y"] = int(image.height * elem.get("y_percent", 0) / 100) + offset_y
                
                return elements
        except Exception as exc:
            logger.warning("Failed to parse elements: %s", exc)
        
        return []


# Singleton
_vision_automation: Optional[VisionAutomation] = None


def get_vision_automation(model: str = "llava:7b") -> VisionAutomation:
    """Get or create the global Vision Automation instance."""
    global _vision_automation
    if _vision_automation is None:
        _vision_automation = VisionAutomation(model=model)
    return _vision_automation
