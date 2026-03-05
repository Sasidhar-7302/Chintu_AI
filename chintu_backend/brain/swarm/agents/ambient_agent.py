"""Ambient Agent: The proactive brain of Chintu."""

import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

from chintu_backend.brain.swarm.base_agent import BaseAgent
from chintu_backend.proactivity.signal_bus import get_signal_bus, Signal, SignalType

logger = logging.getLogger(__name__)

class AmbientAgent(BaseAgent):
    """
    Background worker that listens to the SignalBus and decides
    when to proactively assist the user.
    """
    def __init__(self, llm_client=None):
        super().__init__(
            name="AmbientAgent",
            description="Proactive background agent that monitors system state and suggests actions."
        )
        self.llm_client = llm_client
        self.bus = get_signal_bus()
        self._last_notification_time = {}
        self._notification_callback = None

    def set_notification_callback(self, callback):
        """Set callback for proactive notifications."""
        self._notification_callback = callback

    def start(self):
        """Subscribe to signals and start listening."""
        for sig_type in SignalType:
            self.bus.subscribe(sig_type, self.handle_signal)
        logger.info("AmbientAgent subcribed to all signal types.")

    async def handle_signal(self, signal: Signal):
        """Analyze incoming signals and decide on action."""
        logger.info(f"AmbientAgent analyzing signal: {signal.signal_type.value}")
        
        # Throttling: Don't spam the same signal type too often
        now = datetime.now()
        last_time = self._last_notification_time.get(signal.signal_type)
        if last_time and (now - last_time).total_seconds() < 3600: # 1 hour cooldown for proactivity
             return

        # Simple logic for now - can be expanded with LLM reasoning later
        if signal.signal_type == SignalType.SYSTEM:
            event = signal.data.get("event")
            if event == "low_battery":
                await self._notify_user(
                    f"Warning: Your battery is at {signal.data['percent']}%. You might want to plug in!"
                )
                self._last_notification_time[signal.signal_type] = now
            elif event == "connectivity_change" and not signal.data['is_online']:
                 await self._notify_user("Heads up: You just went offline.")
                 self._last_notification_time[signal.signal_type] = now
        
        elif signal.signal_type == SignalType.PROJECT:
             count = signal.data.get("file_count", 0)
             if count > 3:
                 await self._notify_user(f"I noticed you're making several changes to the project ({count} files). Need any help with a code audit or testing?")
                 self._last_notification_time[signal.signal_type] = now

    async def _notify_user(self, message: str):
        """Send a proactive message to the UI."""
        logger.info(f"PROACTIVE NOTIFICATION: {message}")
        if self._notification_callback:
            if asyncio.iscoroutinefunction(self._notification_callback):
                await self._notification_callback(message)
            else:
                self._notification_callback(message)

    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Manual execution for specific proactivity checks."""
        self.update_state("executing")
        return {"status": "running", "active_signals": len(self.bus._history)}

    def stop(self):
        """Stop agent execution."""
        self.update_state("idle")
