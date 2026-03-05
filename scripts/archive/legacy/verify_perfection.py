"""Verification script for Final Perfection Phase."""

import asyncio
import logging
import sys
import os
from pathlib import Path

# Ensure package is in path
sys.path.append(str(Path(__file__).parent.parent))

from chintu_backend.proactivity.signal_bus import get_signal_bus, Signal, SignalType
from chintu_backend.brain.swarm.agents.ambient_agent import AmbientAgent
from chintu_backend.proactivity.project_observer import ProjectObserver

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_perfection")

async def test_dependencies():
    logger.info("--- Testing Critical Dependencies ---")
    try:
        import telegram
        logger.info(f"SUCCESS: telegram version {telegram.__version__}")
    except ImportError:
        logger.error("FAILED: telegram (python-telegram-bot) not installed")

    try:
        from googleapiclient.discovery import build
        logger.info("SUCCESS: google-api-python-client available")
    except ImportError:
        logger.error("FAILED: google-api-python-client not installed")

async def test_project_observer():
    logger.info("\n--- Testing Project Observer Signal ---")
    bus = get_signal_bus()
    agent = AmbientAgent()
    
    received = []
    agent.set_notification_callback(lambda msg: received.append(msg))
    agent.start()
    
    # Emit a project signal
    logger.info("Emitting PROJECT signal (simulating file burst)...")
    await bus.emit(Signal(SignalType.PROJECT, "test", {"file_count": 5}))
    
    await asyncio.sleep(1)
    if received:
        logger.info(f"SUCCESS: Agent proactive help triggered: {received[0]}")
    else:
        logger.error("FAILED: Agent did not respond to project signal.")

async def main():
    await test_dependencies()
    await test_project_observer()

if __name__ == "__main__":
    asyncio.run(main())
