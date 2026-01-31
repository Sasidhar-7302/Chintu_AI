"""
Standard entry point for running Chintu via `python -m chintu`.
"""

import sys
import os
import asyncio
import logging
from pathlib import Path

# Add project root to path if necessary
sys.path.append(str(Path(__file__).parent.parent))

from chintu_backend.core.app import main

if __name__ == "__main__":
    asyncio.run(main())
