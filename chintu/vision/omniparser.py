"""OmniParser v2 - Vision-based Screen Understanding.

Supports:
1. Google Gemini 2.0 Flash (Cloud - Fastest/Best)
2. Ollama + Moondream (Local - Private/Free)

Enables commands like "what's on my screen" and "click the submit button".
"""

import os
import logging
import base64
import json
import io
from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Try to import Google GenAI (New SDK)
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("google-genai not installed for vision")

# Try to import Ollama
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    logger.warning("ollama library not installed")


@dataclass
class UIElement:
    """Represents a detected UI element."""
    element_type: str  # button, text, input, image, link
    text: str
    location: str  # description like "top-left", "center"
    confidence: float
    bounds: Optional[Tuple[int, int, int, int]] = None  # x, y, width, height


class OmniParser:
    """Vision-based screen understanding using Gemini Vision API or Local Ollama."""
    
    def __init__(self, api_key: str = None):
        # 1. Try Configured API Keys
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_AI_KEY")
        
        # Also try chintu config
        if not self.api_key:
            try:
                from ..core.config import get_config
                self.api_key = get_config().google_ai_key
            except ImportError:
                pass
        
        self.client = None
        self._initialized = False
        self.use_ollama = False
        
        # Determine Backend
        if self.api_key and GEMINI_AVAILABLE:
            self.backend = "gemini"
        elif OLLAMA_AVAILABLE:
            self.backend = "ollama"
            self.use_ollama = True
            logger.info("OmniParser using LOCAL backend (Ollama/Moondream)")
        else:
            self.backend = "none"
            logger.warning("No vision backend available (Missing API Key & Ollama)")

    def _ensure_initialized(self):
        """Initialize Gemini client if needed."""
        if self._initialized:
            return
            
        if self.backend == "gemini":
            try:
                self.client = genai.Client(api_key=self.api_key)
                self._initialized = True
                logger.info("OmniParser initialized with Gemini Vision")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini Client: {e}")
                # Fallback to Ollama if initialization fails
                if OLLAMA_AVAILABLE:
                    self.backend = "ollama"
                    self.use_ollama = True
                    logger.info("Falling back to Ollama")
        
        elif self.backend == "ollama":
            self._initialized = True

    def _generate(self, prompt: str, image_bytes: bytes) -> Optional[str]:
        """Generate content using the active backend."""
        self._ensure_initialized()
        
        if self.backend == "gemini" and self.client:
            try:
                response = self.client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=image_bytes, mime_type="image/png")
                    ]
                )
                return response.text
            except Exception as e:
                logger.error(f"Gemini API error: {e}")
                # If rate limited, fallback to Ollama?
                if "429" in str(e) and OLLAMA_AVAILABLE:
                     logger.warning("Gemini Rate Limit hit. Switching to Local Ollama.")
                     self.backend = "ollama"
                     self.use_ollama = True
                     return self._generate(prompt, image_bytes) # Retry with ollama
                return None

        elif self.backend == "ollama":
            try:
                # Moondream is small and fast. Llava is bigger.
                model = "moondream" 
                
                response = ollama.chat(
                    model=model,
                    messages=[{
                        'role': 'user',
                        'content': prompt,
                        'images': [image_bytes]
                    }]
                )
                return response['message']['content']
            except Exception as e:
                logger.error(f"Ollama Vision error: {e}")
                return None
                
        return None

    def analyze_screen(self, image_path: str = None, 
                       image_bytes: bytes = None) -> Dict[str, Any]:
        """Analyze a screenshot and return structured description."""
        
        # Load image
        if image_path:
            try:
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
            except Exception as e:
                return {"error": f"Failed to read image: {e}"}
        
        if not image_bytes:
            return {"error": "No image provided"}
            
        # Prompt for structured analysis
        prompt = """Analyze this screenshot and provide:

1. **Description**: What application/website is shown? What's the main content?
2. **Key Elements**: List important UI elements (buttons, text fields, links)
3. **Text Content**: Any readable text on screen
4. **Actions Available**: What can the user do here?

Be concise but thorough. Format as JSON if possible, otherwise just text."""

        response_text = self._generate(prompt, image_bytes)
        if not response_text:
             return {
                "error": "Vision model failed",
                "description": "I cannot analyze the screen right now."
            }

        result = self._parse_response(response_text)
        result["raw_response"] = response_text
        return result
            
    def describe_screen(self, image_path: str = None,
                        image_bytes: bytes = None) -> str:
        """Get a natural language description suitable for voice."""
        
        if image_path:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        
        if not image_bytes:
            return "No screenshot available."
            
        prompt = """Look at this screenshot and give me a brief, natural description.
Speak as if you're telling someone what's on their screen.
Keep it to 2-3 sentences. Be specific about the app/website and main content."""

        text = self._generate(prompt, image_bytes)
        if not text:
            return "I cannot see your screen right now. Vision is not available."
        return text.strip()
    
    def find_element(self, image_path: str, element_description: str) -> Dict[str, Any]:
        """Find a UI element matching the description."""
        
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        except:
             return {"found": False, "error": "Image load failed"}

        prompt = f"""Look at this screenshot and find the visible UI element described as: "{element_description}"

Return a JSON object with this EXACT structure:

{{
  "found": true/false,
  "description": "brief description of what was found and its location",
  "coordinates": [x_percent, y_percent]  // Center point as percentage (0-100). Top-left is [0,0].
}}

If not found, set "found": false and "coordinates": null.
DO NOT output conversational text, ONLY the JSON."""

        text = self._generate(prompt, image_bytes)
        if not text:
            return {"found": False, "error": "API failed"}
            
        return self._parse_json_response(text)

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Parse strict JSON response."""
        try:
            clean = text.strip()
            # Try to find JSON block
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()
            
            # Find start and end braces if mixed with text
            start = clean.find("{")
            end = clean.rfind("}") + 1
            if start != -1 and end != -1:
                clean = clean[start:end]
                
            return json.loads(clean)
        except Exception:
            # Fallback logic for models that chatter
            lower = text.lower()
            return {
                "found": "found" in lower and "not found" not in lower,
                "description": text[:200],
                "coordinates": None # Cannot reliably guess without JSON
            }
    
    def _parse_response(self, text: str) -> Dict[str, Any]:
        """Parse response into structured format."""
        try:
            # Look for JSON block
            if "```json" in text:
                json_start = text.find("```json") + 7
                json_end = text.find("```", json_start)
                json_str = text[json_start:json_end]
                return json.loads(json_str)
            elif "{" in text and "}" in text:
                # Try to find JSON object
                start = text.find("{")
                end = text.rfind("}") + 1
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
        
        return {
            "description": text,
            "elements": [],
            "text_content": "",
            "actions": []
        }

# Global instance
_parser: Optional[OmniParser] = None

def get_omniparser() -> OmniParser:
    """Get the global OmniParser instance."""
    global _parser
    if _parser is None:
        _parser = OmniParser()
    return _parser
