"""Base class for proactive Observers."""

import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Optional

from .signal_bus import get_signal_bus, Signal, SignalType

logger = logging.getLogger(__name__)

class BaseObserver(ABC):
    """
    Base class for background sensors that monitor system state.
    """
    def __init__(self, name: str, interval: int = 60):
        self.name = name
        self.interval = interval
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self.bus = get_signal_bus()

    async def start(self):
        """Start the background monitoring loop."""
        if self.is_running:
            return
        
        self.is_running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Observer started: {self.name}")

    async def stop(self):
        """Stop the monitoring loop."""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"Observer stopped: {self.name}")

    async def _run_loop(self):
        """Internal loop for periodic polling."""
        while self.is_running:
            try:
                await self.poll()
            except Exception as e:
                logger.error(f"Observer {self.name} error: {e}")
            
            await asyncio.sleep(self.interval)

    @abstractmethod
    async def poll(self):
        """Poll the monitored resource and emit signals if needed."""
        pass

    async def emit_signal(self, signal_type: SignalType, data: dict, priority: int = 1):
        """Convenience method to emit a signal."""
        signal = Signal(signal_type, self.name, data, priority)
        await self.bus.emit(signal)
