"""
Signal Manager: Collects real-time system and environmental signals.
Run in a background thread to update state without blocking.

Design goals:
- Never block Chintu startup if optional dependencies like ``psutil`` are missing.
- Degrade gracefully and simply omit system metrics when unavailable.
"""

import logging
import threading
import time
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except Exception:  # ImportError or runtime issues
    psutil = None  # type: ignore
    _HAS_PSUTIL = False
    logger.warning("psutil not available; SignalManager will run without detailed system metrics.")

class SignalManager:
    """
    Monitors system state (battery, CPU, time, etc.) at a fixed interval.
    Stores current signals for the RuleEngine to evaluate.
    """
    
    def __init__(self, interval: float = 2.0):
        self.interval = interval
        self._signals: Dict[str, Any] = {}
        self._running = False
        self._stop_event = threading.Event()  # For interruptible sleep
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
    def start(self):
        """Start the signal monitoring thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="SignalManager")
        self._thread.start()
        logger.info("SignalManager started")
        
    def stop(self):
        """Stop the signal monitoring thread."""
        self._running = False
        self._stop_event.set()  # Signal thread to wake up
        if self._thread:
            self._thread.join(timeout=1.0)
        logger.info("SignalManager stopped")
        
    def get_signals(self) -> Dict[str, Any]:
        """Get a copy of the current signals (thread-safe)."""
        with self._lock:
            return self._signals.copy()
            
    def _monitor_loop(self):
        """Main loop for updating signals."""
        while self._running:
            try:
                self._update_signals()
            except Exception as e:
                logger.error(f"Error in SignalManager loop: {e}")
            
            self._stop_event.wait(self.interval)  # Interruptible sleep
            
    def _update_signals(self):
        """Collect all signals."""
        new_signals = {}
        
        # 1. System Signals (psutil) - optional
        if _HAS_PSUTIL and psutil is not None:
            try:
                battery = psutil.sensors_battery()
                new_signals["battery_percent"] = battery.percent if battery else 100
                new_signals["is_plugged_in"] = battery.power_plugged if battery else True
                new_signals["cpu_percent"] = psutil.cpu_percent(interval=None)
            except Exception as e:
                logger.debug(f"SignalManager psutil metrics failed: {e}")
            
        # 2. Time Signals
        now = time.localtime()
        new_signals["hour"] = now.tm_hour
        new_signals["minute"] = now.tm_min
        new_signals["is_weekday"] = now.tm_wday < 5
        
        # 3. Network Check
        try:
            import socket
            with socket.create_connection(("8.8.8.8", 53), timeout=1):
                new_signals["is_online"] = True
        except (socket.timeout, OSError):
            new_signals["is_online"] = False
        
        # Update thread-safe storage
        with self._lock:
            self._signals = new_signals
            
# Singleton Support
_signal_manager = None

def get_signal_manager():
    global _signal_manager
    if _signal_manager is None:
        _signal_manager = SignalManager()
    return _signal_manager
