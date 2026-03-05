"""Observer for hardware and system state."""

import psutil
import socket
import logging
from .base_observer import BaseObserver, SignalType

logger = logging.getLogger(__name__)

class SystemObserver(BaseObserver):
    """
    Monitors hardware (battery) and connectivity.
    Emits signals when thresholds are crossed.
    """
    def __init__(self, interval: int = 300):  # Poll every 5 mins
        super().__init__("system_sensor", interval)
        self._last_battery = None
        self._last_online = None

    async def poll(self):
        # 1. Check Internet
        is_online = self._check_internet()
        if self._last_online is not None and is_online != self._last_online:
            await self.emit_signal(
                SignalType.SYSTEM, 
                {"event": "connectivity_change", "is_online": is_online},
                priority=2 if not is_online else 1
            )
        self._last_online = is_online

        # 2. Check Battery
        battery = psutil.sensors_battery()
        if battery:
            percent = battery.percent
            is_plugged = battery.power_plugged
            
            # Emit signal if battery low and not plugged
            if percent < 20 and not is_plugged:
                await self.emit_signal(
                    SignalType.SYSTEM,
                    {"event": "low_battery", "percent": percent},
                    priority=2
                )
            
            self._last_battery = percent

    def _check_internet(self):
        try:
            # Check if we can reach Google's DNS
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except OSError:
            return False
