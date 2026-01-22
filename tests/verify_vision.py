
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from chintu.vision.omniparser import OmniParser, GEMINI_AVAILABLE
print(f"GEMINI_AVAILABLE: {GEMINI_AVAILABLE}")

if GEMINI_AVAILABLE:
    op = OmniParser(api_key="TEST_KEY")
    op._ensure_initialized()
    print(f"Client Initialized: {op.client is not None}")
    if op.client:
        print("Success: google-genai SDK loaded.")
else:
    print("Failure: google-genai not found.")
