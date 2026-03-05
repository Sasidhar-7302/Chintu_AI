"""
Hardware Optimization Module for Chintu
Auto-detects hardware and optimizes settings for performance.
"""

import os
import platform
import logging
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class HardwareOptimizer:
    """Automatically detects hardware and optimizes configuration."""
    
    def __init__(self):
        self.cpu_count = 0
        self.ram_gb = 0.0
        self.gpus = []
        self.has_gpu = False
        self.vram_total_mb = 0
        self.primary_gpu = None
        self.secondary_gpu = None
        self.hardware_profile = "low_end"
        self.hardware_signature: Dict[str, Any] = {}
        self.refresh_hardware()
        
        logger.info(
            f"Hardware detected: {self.cpu_count} CPU threads, "
            f"{self.ram_gb:.1f}GB RAM, GPU: {self.has_gpu}, "
            f"VRAM: {self.vram_total_mb or 'unknown'}MB, "
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
    
    def _detect_multiple_gpus(self) -> list:
        """Detect multiple GPUs and return their basic info."""
        gpus = []
        try:
            # Try PyTorch if available
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    props = torch.cuda.get_device_properties(i)
                    gpus.append({
                        "id": i,
                        "name": props.name,
                        "vram_mb": props.total_memory / (1024 * 1024)
                    })
                return gpus
        except Exception:
            pass

        # Fallback for Windows WMI
        if platform.system() == "Windows":
            try:
                import subprocess
                result = subprocess.run(
                    ['wmic', 'path', 'win32_VideoController', 'get', 'name,AdapterRAM'],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    lines = [line.strip() for line in result.stdout.split('\n') if line.strip() and 'Name' not in line]
                    for i, line in enumerate(lines):
                        parts = line.rsplit(' ', 1)
                        if len(parts) == 2 and parts[1].isdigit():
                            gpus.append({
                                "id": i,
                                "name": parts[0].strip(),
                                "vram_mb": int(parts[1]) / (1024 * 1024)
                            })
            except Exception:
                pass
        return gpus

    def _detect_vram_fallback(self) -> int:
        """Fallback to detect VRAM if GPU list is empty but we know it exists."""
        try:
            from chintu_backend.swarm.vram_monitor import get_vram_monitor
            status = get_vram_monitor().get_status()
            if status and status.total_mb:
                return int(status.total_mb)
        except Exception:
            pass
        return 0

    def _assign_gpu_roles(self):
        """Assign primary (Executive LLM) and secondary (Background) GPUs."""
        self.primary_gpu = None
        self.secondary_gpu = None
        if not self.gpus:
            return

        # Sort GPUs by VRAM descending
        sorted_gpus = sorted(self.gpus, key=lambda x: x.get('vram_mb', 0), reverse=True)
        self.primary_gpu = sorted_gpus[0]
        
        if len(sorted_gpus) > 1:
            self.secondary_gpu = sorted_gpus[1]
            logger.info(f"Assigned Primary GPU (LLM): {self.primary_gpu['name']} ({self.primary_gpu['vram_mb']:.0f}MB)")
            logger.info(f"Assigned Secondary GPU (Background): {self.secondary_gpu['name']} ({self.secondary_gpu['vram_mb']:.0f}MB)")
        else:
            logger.info(f"Assigned Single GPU: {self.primary_gpu['name']}")

    def _gpu_device_id(self, gpu: Optional[Dict[str, Any]]) -> int:
        if not gpu:
            return -1
        try:
            return int(gpu.get("id", -1))
        except Exception:
            return -1

    def _build_signature(self) -> Dict[str, Any]:
        gpu_signature: Tuple[Tuple[str, int], ...] = tuple(
            sorted(
                (
                    str(gpu.get("name", "")).strip(),
                    int(float(gpu.get("vram_mb", 0) or 0)),
                )
                for gpu in (self.gpus or [])
            )
        )
        return {
            "cpu_count": int(self.cpu_count or 0),
            "ram_gb": round(float(self.ram_gb or 0.0), 2),
            "gpu_count": len(self.gpus or []),
            "gpu_signature": gpu_signature,
            "hardware_profile": str(self.hardware_profile or ""),
        }

    def get_signature(self) -> Dict[str, Any]:
        return dict(self.hardware_signature or self._build_signature())

    def refresh_hardware(self) -> Dict[str, Any]:
        previous = self.get_signature()

        self.cpu_count = self._detect_cpu_count()
        self.ram_gb = self._detect_ram()
        self.gpus = self._detect_multiple_gpus()
        self.has_gpu = len(self.gpus) > 0
        self.vram_total_mb = (
            sum(gpu.get("vram_mb", 0) for gpu in self.gpus)
            if self.has_gpu
            else self._detect_vram_fallback()
        )
        self._assign_gpu_roles()
        self.hardware_profile = self._determine_profile()
        self.hardware_signature = self._build_signature()

        changed = previous != self.hardware_signature
        if changed:
            logger.info(
                "Hardware signature changed: %s -> %s",
                previous,
                self.hardware_signature,
            )
        return {
            "changed": bool(changed),
            "previous": previous,
            "current": self.get_signature(),
            "hardware_profile": self.hardware_profile,
            "gpu_count": len(self.gpus or []),
        }
    
    def _determine_profile(self) -> str:
        """Determine hardware profile for optimization."""
        if self.vram_total_mb >= 11000:
            return "high_end_gpu"
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
                "whisper_model": "tiny.en",   # Fastest STT
                "llm_max_tokens": 512,        # Shorter responses
                "llm_num_threads": min(self.cpu_count, 2),  # Limit threads
                "stt_cpu_threads": min(self.cpu_count, 2),
                "llm_num_gpu": 0,
                "memory_enabled": True,       # Keep memory but optimize
                "memory_top_k": 2,            # Fewer memory retrievals
            })
        elif self.hardware_profile == "mid_range":
            # Mid-range (16-32GB RAM, possibly GPU)
            # i5 8th gen with 24GB fits here
            optimizations.update({
                "whisper_model": "tiny.en",   # or "base.en" for better accuracy
                "llm_max_tokens": 1024,
                "llm_num_threads": min(self.cpu_count, 4),  # i5 8th gen = 4-8 threads
                "stt_cpu_threads": min(self.cpu_count, 4),
                "llm_num_gpu": 20 if self.has_gpu else 0,
                "memory_enabled": True,
                "memory_top_k": 3,
            })
        elif self.hardware_profile == "high_end":
            # High-end (32GB+ RAM, GPU available)
            optimizations.update({
                "whisper_model": "base.en",   # Better accuracy
                "llm_max_tokens": 2048,
                "llm_num_threads": min(self.cpu_count, 8),
                "stt_cpu_threads": min(self.cpu_count, 8),
                "llm_num_gpu": 35 if self.has_gpu else 0,
                "memory_enabled": True,
                "memory_top_k": 4,
            })
        else:
            # GPU-rich system (>= 10-12GB VRAM)
            optimizations.update({
                "whisper_model": "base.en",      # Faster fallback if CUDA fails
                "llm_max_tokens": 2048,
                "llm_num_threads": min(self.cpu_count, 8),
                "stt_cpu_threads": min(self.cpu_count, 8),
                "llm_num_gpu": 60,
                "llm_prefer_local": True,
                "memory_enabled": True,
                "memory_top_k": 4,
            })

        # Local model selection: keep configured if available, else auto-select
        # the best installed model for this machine (llmfit-style "what fits?").
        try:
            from ..brain.llm.model_selector import choose_local_brain_model, list_local_ollama_models

            host = str(getattr(config, "ollama_host", "http://localhost:11434") or "http://localhost:11434")
            preferred = str(getattr(config, "ollama_model", "") or "").strip()
            selected = choose_local_brain_model(
                preferred_model=preferred,
                host=host,
                auto_select=bool(getattr(config, "llm_auto_select_model", True)),
            )
            if selected:
                optimizations["ollama_model"] = selected

            # Keep the strong model pinned to something installed so router upgrades
            # don't repeatedly bounce on "model not found".
            strong = str(getattr(config, "ollama_model_strong", "") or "").strip()
            if strong:
                installed = {str(m.name) for m in list_local_ollama_models(host)}
                if installed and (strong not in installed) and selected in installed:
                    optimizations["ollama_model_strong"] = selected
        except Exception:
            pass

        # Keep GPU selector config aligned with current topology so runtime can
        # adapt automatically if hardware changes (add/remove/upgrade GPU).
        primary_id = self._gpu_device_id(self.primary_gpu)
        secondary_id = self._gpu_device_id(self.secondary_gpu)
        optimizations.update({
            "gpu_primary_device_id": primary_id,
            "gpu_secondary_device_id": secondary_id,
            "gpu_default_allow_cpu_fallback": True,
            "gpu_resource_manager_enabled": True,
        })
        if not self.has_gpu:
            optimizations["gpu_primary_reserved_vram_mb"] = 0
            optimizations["gpu_secondary_reserved_vram_mb"] = 0
        else:
            primary_vram_mb = int(float((self.primary_gpu or {}).get("vram_mb", 0) or 0))
            secondary_vram_mb = int(float((self.secondary_gpu or {}).get("vram_mb", 0) or 0))
            optimizations["gpu_primary_reserved_vram_mb"] = max(1024, min(4096, primary_vram_mb // 4 or 2048))
            if secondary_vram_mb > 0:
                optimizations["gpu_secondary_reserved_vram_mb"] = max(
                    512,
                    min(2048, secondary_vram_mb // 4 or 1024),
                )
            else:
                optimizations["gpu_secondary_reserved_vram_mb"] = 0
        
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
        elif self.hardware_profile == "high_end":
            return "phi-2"
        return "qwen2.5:7b"
    
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


def reset_hardware_optimizer() -> None:
    global _optimizer
    _optimizer = None

