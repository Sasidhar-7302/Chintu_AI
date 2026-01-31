"""
Chintu Personal AI Assistant - Wrapper Entry Point
"""

import asyncio
import sys
import os
from pathlib import Path

# Ensure the package is in sys.path
sys.path.append(str(Path(__file__).parent))

from chintu_backend.core.app import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"FATAL: {e}")
        sys.exit(1)
