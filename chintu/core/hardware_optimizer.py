"""
Hardware Optimization Module for Chintu
Auto-detects hardware and optimizes settings for performance.
"""

import os
import platform
import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class HardwareOptimizer:
    """Automatically detects hardware and optimizes configuration."""
    
    def __init__(self):
        self.cpu_count = self._detect_cpu_count()
        self.ram_gb = self._detect_ram()
        self.has_gpu = self._detect_gpu()
        self.hardware_profile = self._determine_profile()
        
        logger.info(
            f"Hardware detected: {self.cpu_count} CPU threads, "
            f"{self.ram_gb:.1f}GB RAM, GPU: {self.has_gpu}, "
            f"Profile: {self.hardware_profile}"
        )
    
    def _detect_cpu_count(self) -> int:
        """Detect number of CPU threads."""
        try:
            return os.cpu_count() or 4
        except Exception:
            return 4
    
    def _detect_ram(self) -> float:
        """Detect available RAM in GB."""
        try:
            if platform.system() == "Windows":
                try:
                    import psutil
                    return psutil.virtual_memory().total / (1024 ** 3)
                except ImportError:
                    # Fallback: use WMI on Windows
                    try:
                        import subprocess
                        result = subprocess.run(
                            ['wmic', 'computersystem', 'get', 'TotalPhysicalMemory'],
                            capture_output=True,
                            text=True
                        )
                        if result.returncode == 0:
                            for line in result.stdout.split('\n'):
                                line = line.strip()
                                if line.isdigit():
                                    return float(line) / (1024 ** 3)
                    except Exception:
                        pass
            elif platform.system() == "Linux":
                with open('/proc/meminfo', 'r') as f:
                    for line in f:
                        if 'MemTotal' in line:
                            return float(line.split()[1]) / (1024 ** 2)
            elif platform.system() == "Darwin":  # macOS
                try:
                    import psutil
                    return psutil.virtual_memory().total / (1024 ** 3)
                except ImportError:
                    pass
        except Exception:
            pass
        return 24.0  # Default assumption for i5 8th gen systems
    
    def _detect_gpu(self) -> bool:
        """Detect if a dedicated GPU is available."""
        try:
            # Check for CUDA
            import torch
            if torch.cuda.is_available():
                return True
        except Exception:
            pass
        
        # Check for Windows GPU via DirectX
        if platform.system() == "Windows":
            try:
                import subprocess
                result = subprocess.run(
                    ['wmic', 'path', 'win32_VideoController', 'get', 'name'],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0 and 'NVIDIA' in result.stdout:
                    return True
            except Exception:
                pass
        
        return False
    
    def _determine_profile(self) -> str:
        """Determine hardware profile for optimization."""
        if self.ram_gb >= 32 and self.has_gpu:
            return "high_end"
        elif self.ram_gb >= 16:
            return "mid_range"
        else:
            return "low_end"
    
    def optimize_config(self, config: Any) -> Dict[str, Any]:
        """
        Optimize configuration based on detected hardware.
        Returns dict of optimized settings.
        """
        optimizations = {}
        
        # Profile-specific optimizations
        if self.hardware_profile == "low_end":
            # Low-end hardware (8-16GB RAM, no GPU)
            optimizations.update({
                "ollama_model": "tinyllama",  # Smallest, fastest model
                "whisper_model": "tiny.en",   # Fastest STT
                "llm_max_tokens": 512,        # Shorter responses
                "llm_num_threads": min(self.cpu_count, 2),  # Limit threads
                "stt_cpu_threads": min(self.cpu_count, 2),
                "memory_enabled": True,       # Keep memory but optimize
                "memory_top_k": 2,            # Fewer memory retrievals
            })
        elif self.hardware_profile == "mid_range":
            # Mid-range (16-32GB RAM, possibly GPU)
            # i5 8th gen with 24GB fits here
            optimizations.update({
                "ollama_model": "tinyllama",  # or "phi-2" for better quality
                "whisper_model": "tiny.en",   # or "base.en" for better accuracy
                "llm_max_tokens": 1024,
                "llm_num_threads": min(self.cpu_count, 4),  # i5 8th gen = 4-8 threads
                "stt_cpu_threads": min(self.cpu_count, 4),
                "memory_enabled": True,
                "memory_top_k": 3,
            })
        else:  # high_end
            # High-end (32GB+ RAM, GPU available)
            optimizations.update({
                "ollama_model": "phi-2",      # Better quality
                "whisper_model": "base.en",   # Better accuracy
                "llm_max_tokens": 2048,
                "llm_num_threads": min(self.cpu_count, 8),
                "stt_cpu_threads": min(self.cpu_count, 8),
                "memory_enabled": True,
                "memory_top_k": 4,
            })
        
        # Apply optimizations
        for key, value in optimizations.items():
            if hasattr(config, key):
                setattr(config, key, value)
                logger.info(f"Optimized {key} = {value} for {self.hardware_profile} hardware")
        
        return optimizations
    
    def get_recommended_model(self) -> str:
        """Get recommended Ollama model for this hardware."""
        if self.hardware_profile == "low_end":
            return "tinyllama"
        elif self.hardware_profile == "mid_range":
            return "tinyllama"  # or "phi-2" if you want better quality
        else:
            return "phi-2"
    
    def get_recommended_whisper_model(self) -> str:
        """Get recommended Whisper model for this hardware."""
        if self.hardware_profile == "low_end":
            return "tiny.en"
        elif self.hardware_profile == "mid_range":
            return "tiny.en"  # or "base.en" for better accuracy
        else:
            return "base.en"


# Global optimizer instance
_optimizer: Optional[HardwareOptimizer] = None


def get_hardware_optimizer() -> HardwareOptimizer:
    """Get or create the global hardware optimizer instance."""
    global _optimizer
    if _optimizer is None:
        _optimizer = HardwareOptimizer()
    return _optimizer

