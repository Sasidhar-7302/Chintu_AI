import os
import sys
import logging
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# FORCE LOCAL Testing: Unset keys to test Ollama fallback
if "GEMINI_API_KEY" in os.environ:
    del os.environ["GEMINI_API_KEY"]
if "GOOGLE_AI_KEY" in os.environ:
    del os.environ["GOOGLE_AI_KEY"]

# Setup paths
sys.path.append(os.getcwd())

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from chintu_backend.vision.omniparser import get_omniparser
from chintu_backend.vision.screen_capture import get_screen_manager

def test_vision():
    logger.info("Testing Visual Automation (Gemini 2.0 Flash)...")
    
    # 1. Capture Screen
    manager = get_screen_manager()
    capture = manager.capture_screen(save=True)
    if not capture:
        logger.error("Failed to capture screen")
        return

    logger.info(f"Screen captured: {capture.width}x{capture.height}")
    
    # 2. Initialize OmniParser
    # Ensure API key is set
    if not os.environ.get("GEMINI_API_KEY"):
        logger.error("GEMINI_API_KEY not found in environment")
        # Try to load from .env if needed, or assume system env
    
    parser = get_omniparser()
    
    # 3. Find Element
    target = "Start button"
    logger.info(f"Asking Gemini to find: '{target}'...")
    
    # Read bytes from the saved file
    with open(capture.path, "rb") as f:
        image_bytes = f.read()
        
    result = parser.find_element(image_path=str(capture.path), element_description=target)
    
    logger.info("--- Result ---")
    logger.info(result)
    
    if result.get("found"):
        coords = result.get("coordinates") # [x%, y%]
        if coords:
            # Convert to pixels
            px_x = int((coords[0] / 100) * capture.width)
            px_y = int((coords[1] / 100) * capture.height)
            logger.info(f"Target Coordinates: {px_x}, {px_y}")
            logger.info("TEST PASSED: Vision is working.")
        else:
            logger.warn("Found but no coordinates returned.")
    else:
        logger.error("TEST FAILED: Target not found.")

if __name__ == "__main__":
    test_vision()
