"""
ResourceManager: Aggregates system resources (CPU, RAM, VRAM) for adaptive swarm intelligence.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict

from ..swarm.vram_monitor import get_vram_monitor, VRAMStatus, VRAMPressure

logger = logging.getLogger(__name__)

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logger.warning("psutil not installed. CPU/RAM monitoring disabled.")

@dataclass
class SystemStatus:
    """Snapshot of current system resources."""
    vram: VRAMStatus
    cpu_percent: float
    ram_percent: float
    ram_available_mb: int
    gpu_pressure: bool  # Heuristic: High GPU usage from external processes
    recommendation: str

class ResourceManager:
    """
    Monitors system state to guide model selection.
    """
    
    def __init__(self):
        self.vram_monitor = get_vram_monitor()
        self._last_check = 0
        self._cache_status: Optional[SystemStatus] = None
        
    def get_status(self, force_refresh: bool = False) -> SystemStatus:
        """Get current system status (cached for 2s)."""
        now = time.time()
        if not force_refresh and self._cache_status and (now - self._last_check < 2.0):
            return self._cache_status
            
        # 1. Get VRAM Status
        vram = self.vram_monitor.get_status()
        
        # 2. Get CPU/RAM Status
        cpu_p = 0.0
        ram_p = 0.0
        ram_free = 0
        
        if HAS_PSUTIL:
            try:
                cpu_p = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory()
                ram_p = mem.percent
                ram_free = mem.available // (1024 * 1024)
            except Exception as e:
                logger.warning(f"psutil check failed: {e}")
        
        # 3. Detect "High GPU Load"
        # If VRAM pressure is High/Critical and we (Chintu) aren't running a heavy model yet,
        # it's likely an external app (Video Render, 3D app, or Game).
        # Improving this heuristic requires knowing OWN process GPU usage vs TOTAL.
        # For now, we trust VRAM pressure.
        
        gpu_pressure = vram.pressure in (VRAMPressure.HIGH, VRAMPressure.CRITICAL)
        
        # 4. Formulate Recommendation
        rec = "Standard"
        if gpu_pressure:
            rec = "High GPU Load detected. Preferring Cloud/CPU."
        elif ram_free < 4096 and vram.free_mb < 2000:
            rec = "System constrained. Use Small Models."
        elif vram.free_mb > 8000:
            rec = "High Performance. Load Large Models."
            
        status = SystemStatus(
            vram=vram,
            cpu_percent=cpu_p,
            ram_percent=ram_p,
            ram_available_mb=ram_free,
            gpu_pressure=gpu_pressure,
            recommendation=rec
        )
        
        self._last_check = now
        self._cache_status = status
        return status
        
    def should_unload_models(self) -> bool:
        """Check if we should aggressively unload models (e.g. user started Cyberpunk 2077)."""
        s = self.get_status()
        # If VRAM is critical (>90%), strictly unload.
        if s.vram.pressure == VRAMPressure.CRITICAL:
            return True
        return False

# Global
_manager = None

def get_resource_manager() -> ResourceManager:
    global _manager
    if not _manager:
        _manager = ResourceManager()
    return _manager
