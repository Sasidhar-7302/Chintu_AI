"""
VRAM Monitor for Chintu v5.1

Monitors GPU VRAM usage and provides:
- Real-time VRAM usage tracking
- OOM (Out of Memory) prediction
- Graceful model eviction recommendations
- VRAM pressure alerts

Designed for GTX 1650 (4GB VRAM) constraint.
"""

import logging
import subprocess
import re
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class VRAMPressure(Enum):
    """VRAM pressure levels."""
    LOW = "low"          # < 50% usage
    MODERATE = "moderate" # 50-75% usage
    HIGH = "high"        # 75-90% usage
    CRITICAL = "critical" # > 90% usage


@dataclass
class VRAMStatus:
    """Current VRAM status."""
    total_mb: int
    used_mb: int
    free_mb: int
    pressure: VRAMPressure
    utilization_percent: float
    can_load_model: bool  # Can we safely load another model?
    recommended_action: str


class VRAMMonitor:
    """
    Monitors NVIDIA GPU VRAM usage.
    
    Uses nvidia-smi for VRAM queries. Falls back to estimates if unavailable.
    """
    
    def __init__(self, vram_limit_mb: int = 4096, safety_margin_mb: int = 512):
        """
        Initialize VRAM monitor.
        
        Args:
            vram_limit_mb: Total VRAM in MB (default: 4GB for GTX 1650)
            safety_margin_mb: Safety buffer to keep free (default: 512MB)
        """
        self.vram_limit_mb = vram_limit_mb
        self.safety_margin_mb = safety_margin_mb
        self._nvidia_smi_available = self._check_nvidia_smi()
        
        # Model size estimates (Q4_K_M quantization)
        self.model_sizes = {
            "qwen2.5:1.5b": 1200,      # ~1.2GB
            "qwen2.5:3b": 2400,        # ~2.4GB
            "qwen2.5-coder:7b": 4500,  # ~4.5GB
            "llama3.1:8b": 4800,       # ~4.8GB
            "phi3.5:mini": 2400,       # ~2.4GB
            "gemma2:2b": 1600,         # ~1.6GB
        }
        
        logger.info(f"VRAMMonitor initialized: {vram_limit_mb}MB limit, nvidia-smi={'yes' if self._nvidia_smi_available else 'no'}")
    
    def _check_nvidia_smi(self) -> bool:
        """Check if nvidia-smi is available."""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def get_status(self) -> VRAMStatus:
        """Get current VRAM status."""
        if self._nvidia_smi_available:
            return self._get_nvidia_status()
        return self._get_estimated_status()
    
    def _get_nvidia_status(self) -> VRAMStatus:
        """Get VRAM status from nvidia-smi."""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free", 
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            
            if result.returncode == 0:
                parts = result.stdout.strip().split(",")
                total = int(parts[0].strip())
                used = int(parts[1].strip())
                free = int(parts[2].strip())
                
                return self._build_status(total, used, free)
        except Exception as e:
            logger.warning(f"nvidia-smi query failed: {e}")
        
        return self._get_estimated_status()
    
    def _get_estimated_status(self) -> VRAMStatus:
        """Estimate VRAM status when nvidia-smi unavailable."""
        # Conservative estimate: assume 50% usage
        total = self.vram_limit_mb
        used = total // 2
        free = total - used
        return self._build_status(total, used, free)
    
    def _build_status(self, total: int, used: int, free: int) -> VRAMStatus:
        """Build VRAMStatus from raw values."""
        utilization = (used / total) * 100 if total > 0 else 0
        
        if utilization < 50:
            pressure = VRAMPressure.LOW
            action = "VRAM healthy, models can be loaded"
        elif utilization < 75:
            pressure = VRAMPressure.MODERATE
            action = "VRAM moderate, prefer smaller models"
        elif utilization < 90:
            pressure = VRAMPressure.HIGH
            action = "VRAM high, consider evicting unused models"
        else:
            pressure = VRAMPressure.CRITICAL
            action = "VRAM critical, evict models immediately"
        
        can_load = free > self.safety_margin_mb
        
        return VRAMStatus(
            total_mb=total,
            used_mb=used,
            free_mb=free,
            pressure=pressure,
            utilization_percent=utilization,
            can_load_model=can_load,
            recommended_action=action
        )
    
    def can_fit_model(self, model_name: str) -> Tuple[bool, str]:
        """Check if a model can fit in available VRAM."""
        status = self.get_status()
        model_size = self.model_sizes.get(model_name, 2000)  # Default 2GB estimate
        
        available = status.free_mb - self.safety_margin_mb
        
        if model_size <= available:
            return True, f"Model {model_name} ({model_size}MB) fits in {available}MB available"
        else:
            deficit = model_size - available
            return False, f"Model {model_name} needs {model_size}MB but only {available}MB available (need {deficit}MB more)"
    
    def get_eviction_candidates(self) -> List[str]:
        """Get list of models that could be evicted to free VRAM."""
        # This would integrate with ModelManager to get loaded models
        # For now, return models sorted by size (evict largest first)
        return sorted(self.model_sizes.keys(), key=lambda m: self.model_sizes[m], reverse=True)


# Global instance
_vram_monitor: Optional[VRAMMonitor] = None


def get_vram_monitor() -> VRAMMonitor:
    """Get or create the global VRAM monitor."""
    global _vram_monitor
    if _vram_monitor is None:
        _vram_monitor = VRAMMonitor()
    return _vram_monitor

