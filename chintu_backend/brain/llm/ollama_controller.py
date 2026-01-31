"""
OllamaController: Manages local model loading/unloading via API.
Enables 'Swarm' behavior by dynamically swapping models.
"""

import logging
import requests
import json
from typing import List, Optional
from ...core.config import get_config

logger = logging.getLogger(__name__)

class OllamaController:
    """Controls the local Ollama instance."""
    
    def __init__(self):
        self.config = get_config()
        self.host = getattr(self.config, 'ollama_host', 'http://localhost:11434')
        
    def unload_all(self) -> bool:
        """Force unload all models to free VRAM."""
        try:
            # To unload, we send a request with keep_alive=0 to a dummy model match
            # Actually, standard way is to generic request with keep_alive=0
            # or use the /api/generate endpoint with an empty prompt and keep_alive=0
            
            # We'll try unloading the currently loaded model name if known,
            # otherwise just try standard unload trick.
            
            # Since we might not know what's running, let's list them first?
            # Or just hit the Generate endpoint for the configured default model with keep_alive=0
            model = getattr(self.config, 'ollama_model', 'llama3')
            
            url = f"{self.host}/api/generate"
            payload = {
                "model": model,
                "prompt": "",
                "keep_alive": 0  # Immediate unload
            }
            requests.post(url, json=payload, timeout=2)
            logger.info("Ollama: Requested model unload (keep_alive=0)")
            return True
        except Exception as e:
            logger.warning(f"Failed to unload models: {e}")
            return False

    def preload_model(self, model_name: str) -> bool:
        """Preload a model into memory."""
        try:
            url = f"{self.host}/api/generate"
            payload = {
                "model": model_name,
                "prompt": "", 
                "keep_alive": "5m" # Keep alive for 5 mins
            }
            # Send async? Or wait? Loading takes time.
            # Using very short timeout just to trigger load
            try:
                requests.post(url, json=payload, timeout=0.1)
            except requests.Timeout:
                pass # Expected, it started loading
            
            logger.info(f"Ollama: Preloading {model_name}...")
            return True
        except Exception as e:
            logger.warning(f"Failed to preload {model_name}: {e}")
            return False

# Global
_controller = None

def get_ollama_controller() -> OllamaController:
    global _controller
    if not _controller:
        _controller = OllamaController()
    return _controller
