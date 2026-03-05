"""Verification script for Phase 6: Ambient Hive."""

import asyncio
import logging
import sys
from pathlib import Path

# Ensure package is in path
sys.path.append(str(Path(__file__).parent.parent))

from chintu_backend.proactivity.signal_bus import get_signal_bus, Signal, SignalType
from chintu_backend.brain.swarm.agents.ambient_agent import AmbientAgent
from chintu_backend.brain.swarm.agents.librarian import LibrarianAgent
from chintu_backend.brain.llm.ollama_client import OllamaClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_v6")

async def test_proactivity():
    logger.info("--- Testing Proactivity Signal Bus ---")
    bus = get_signal_bus()
    agent = AmbientAgent()
    
    # Track notifications
    received = []
    agent.set_notification_callback(lambda msg: received.append(msg))
    agent.start()
    
    # Emit a low battery signal
    logger.info("Emitting low battery signal...")
    await bus.emit(Signal(SignalType.SYSTEM, "test", {"event": "low_battery", "percent": 15}))
    
    await asyncio.sleep(1)
    if received:
        logger.info(f"SUCCESS: Agent notified: {received[0]}")
    else:
        logger.error("FAILED: Agent did not respond to signal.")

async def test_librarian():
    logger.info("\n--- Testing Librarian (Skill Update) ---")
    # We need a real LLM for this or a mock
    llm = OllamaClient(model="qwen2.5:1.5b")
    if not llm.is_available:
        logger.warning("Ollama not available, skipping Librarian test.")
        return

    lib = LibrarianAgent(llm_client=llm)
    res = lib.run("Search for a tool to manage local docker containers and create a skill for it.")
    
    if "proposed_skill" in res:
        logger.info(f"SUCCESS: Librarian proposed a skill: {res['skill_name']}")
        logger.info("Preview:")
        print(res["proposed_skill"][:200] + "...")
    else:
        logger.error("FAILED: Librarian did not propose a skill.")

async def main():
    await test_proactivity()
    await test_librarian()

if __name__ == "__main__":
    asyncio.run(main())
