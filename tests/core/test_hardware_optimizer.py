"""Tests for the Hardware Optimizer module."""

from unittest.mock import patch
from types import SimpleNamespace
from chintu_backend.core.hardware_optimizer import HardwareOptimizer

def test_hardware_optimizer_dual_gpu_mock():
    """Mock dual GPU detection to simulate RTX 3060 and GTX 1650."""
    with patch.object(HardwareOptimizer, '_detect_multiple_gpus') as mock_gpus:
        # Simulate local machine setup
        mock_gpus.return_value = [
            {"id": 0, "name": "NVIDIA GeForce GTX 1650", "vram_mb": 4096},
            {"id": 1, "name": "NVIDIA GeForce RTX 3060", "vram_mb": 12288}
        ]
        
        optimizer = HardwareOptimizer()
        
        assert optimizer.has_gpu is True
        assert len(optimizer.gpus) == 2
        assert optimizer.vram_total_mb == 16384  # 12288 + 4096
        
        # Verify correct role assignment (highest VRAM = primary)
        assert optimizer.primary_gpu["name"] == "NVIDIA GeForce RTX 3060"
        assert optimizer.secondary_gpu["name"] == "NVIDIA GeForce GTX 1650"
        
def test_hardware_optimizer_single_gpu_mock():
    """Mock single GPU detection."""
    with patch.object(HardwareOptimizer, '_detect_multiple_gpus') as mock_gpus:
        mock_gpus.return_value = [
            {"id": 0, "name": "NVIDIA GeForce RTX 3060", "vram_mb": 12288}
        ]
        
        optimizer = HardwareOptimizer()
        
        assert len(optimizer.gpus) == 1
        assert optimizer.primary_gpu["name"] == "NVIDIA GeForce RTX 3060"
        assert optimizer.secondary_gpu is None

def test_hardware_optimizer_profiles():
    """Verify profile determination."""
    with patch.object(HardwareOptimizer, '_detect_multiple_gpus') as mock_gpus:
        # High end GPU
        mock_gpus.return_value = [{"id": 0, "name": "RTX 3060", "vram_mb": 12288}]
        optimizer = HardwareOptimizer()
        assert optimizer.hardware_profile == "high_end_gpu"


def test_hardware_optimizer_refresh_handles_gpu_removal():
    with patch.object(HardwareOptimizer, "_detect_cpu_count", return_value=8), patch.object(
        HardwareOptimizer, "_detect_ram", return_value=24.0
    ), patch.object(
        HardwareOptimizer,
        "_detect_multiple_gpus",
        side_effect=[
            [{"id": 0, "name": "NVIDIA GeForce RTX 3060", "vram_mb": 12288}],
            [],
        ],
    ), patch.object(HardwareOptimizer, "_detect_vram_fallback", return_value=0):
        optimizer = HardwareOptimizer()
        assert optimizer.primary_gpu is not None
        result = optimizer.refresh_hardware()
        assert result["changed"] is True
        assert optimizer.has_gpu is False
        assert optimizer.primary_gpu is None
        assert optimizer.secondary_gpu is None


def test_hardware_optimizer_optimize_config_realigns_gpu_settings_after_topology_change():
    config = SimpleNamespace(
        ollama_model="qwen2.5-coder:7b",
        whisper_model="small.en",
        llm_max_tokens=1024,
        llm_num_threads=4,
        stt_cpu_threads=4,
        llm_num_gpu=50,
        llm_prefer_local=True,
        memory_enabled=True,
        memory_top_k=4,
        gpu_primary_device_id=-1,
        gpu_secondary_device_id=-1,
        gpu_primary_reserved_vram_mb=2048,
        gpu_secondary_reserved_vram_mb=1024,
        gpu_default_allow_cpu_fallback=True,
        gpu_resource_manager_enabled=True,
    )
    with patch.object(HardwareOptimizer, "_detect_cpu_count", return_value=8), patch.object(
        HardwareOptimizer, "_detect_ram", return_value=24.0
    ), patch.object(
        HardwareOptimizer,
        "_detect_multiple_gpus",
        side_effect=[
            [
                {"id": 0, "name": "NVIDIA GeForce GTX 1650", "vram_mb": 4096},
                {"id": 1, "name": "NVIDIA GeForce RTX 3060", "vram_mb": 12288},
            ],
            [],
        ],
    ), patch.object(HardwareOptimizer, "_detect_vram_fallback", return_value=0):
        optimizer = HardwareOptimizer()

        first = optimizer.optimize_config(config)
        assert first["llm_num_gpu"] >= 20
        assert first["gpu_primary_device_id"] == 1
        assert first["gpu_secondary_device_id"] == 0

        optimizer.refresh_hardware()
        second = optimizer.optimize_config(config)
        assert second["llm_num_gpu"] == 0
        assert second["gpu_primary_device_id"] == -1
        assert second["gpu_secondary_device_id"] == -1
