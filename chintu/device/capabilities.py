"""
Device Capability Registry for Chintu AI Assistant.
Negotiates capabilities between devices for optimal task distribution.
"""

from typing import Dict, List, Optional, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ComputeCapability(Enum):
    """Compute capabilities."""
    CPU_ONLY = "cpu_only"
    GPU_AVAILABLE = "gpu_available"
    HIGH_RAM = "high_ram"
    DISTRIBUTED = "distributed"


class DeviceCapabilityRegistry:
    """
    Registry for device capabilities.
    Used to route tasks to optimal devices based on capabilities.
    """
    
    def __init__(self):
        self._capabilities: Dict[str, Dict[str, Any]] = {}
    
    def register_capabilities(self, device_id: str, capabilities: Dict[str, Any]) -> None:
        """Register capabilities for a device."""
        self._capabilities[device_id] = capabilities
        logger.info(f"Registered capabilities for device: {device_id}")
    
    def get_optimal_device(self, required_capabilities: List[str]) -> Optional[str]:
        """
        Find optimal device for given requirements.
        
        Args:
            required_capabilities: List of required capabilities
            
        Returns:
            Device ID of optimal device, or None if no match
        """
        best_device = None
        best_score = 0
        
        for device_id, caps in self._capabilities.items():
            score = 0
            for req in required_capabilities:
                if req in caps and caps[req]:
                    score += 1
            
            if score > best_score:
                best_score = score
                best_device = device_id
        
        if best_score == len(required_capabilities):
            return best_device
        
        return None
    
    def has_capability(self, device_id: str, capability: str) -> bool:
        """Check if device has a specific capability."""
        caps = self._capabilities.get(device_id, {})
        return caps.get(capability, False)

