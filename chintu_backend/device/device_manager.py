"""
Device Manager for Chintu AI Assistant.
Manages multiple devices, device discovery, and capability negotiation.
Enables distributed computing and multi-device support.
"""

import logging
import platform
from typing import Optional, Dict, List, Set, Any
from dataclasses import dataclass
from enum import Enum

from .device_interface import (
    Device, AudioDevice, CameraDevice, DisplayDevice,
    DeviceType, DeviceInfo, AudioCapabilities, CameraCapabilities, DisplayCapabilities
)

logger = logging.getLogger(__name__)


@dataclass
class DeviceCapabilities:
    """Complete device capabilities."""
    audio: AudioCapabilities
    camera: Optional[CameraCapabilities] = None
    display: Optional[DisplayCapabilities] = None
    compute: Dict[str, Any] = None  # CPU, RAM, GPU info
    network: Dict[str, Any] = None   # Network capabilities


class DeviceManager:
    """
    Manages multiple devices for distributed computing.
    Handles device discovery, registration, and capability negotiation.
    """
    
    def __init__(self):
        self._devices: Dict[str, Device] = {}
        self._primary_device: Optional[str] = None
        self._active_audio_device: Optional[str] = None
        self._active_camera_device: Optional[str] = None
        self._discovered_devices: Set[str] = set()
        self._gpu_info: Optional[Dict[str, Any]] = None
        
        # Auto-detect local device
        self._detect_local_device()
        self._detect_gpu()
    
    def _detect_local_device(self) -> None:
        """Auto-detect and register local device."""
        system = platform.system().lower()
        
        if system == "windows":
            device_type = DeviceType.DESKTOP if platform.machine() != "ARM64" else DeviceType.LAPTOP
        elif system == "darwin":  # macOS
            device_type = DeviceType.DESKTOP  # Could detect laptop vs desktop
        elif system == "linux":
            device_type = DeviceType.DESKTOP
        else:
            device_type = DeviceType.DESKTOP
        
        device_id = self._generate_device_id()
        logger.info(f"Detected local device: {device_id} ({system}, {device_type.value})")
    
    def _generate_device_id(self) -> str:
        """Generate unique device ID."""
        import uuid
        import socket
        hostname = socket.gethostname()
        machine_id = platform.machine()
        return f"{hostname}-{machine_id}-{uuid.uuid4().hex[:8]}"
    
    def register_device(self, device: Device) -> bool:
        """
        Register a device (local or remote).
        
        Args:
            device: Device to register
            
        Returns:
            True if registered successfully
        """
        device_id = device.device_id
        
        if device_id in self._devices:
            logger.warning(f"Device already registered: {device_id}")
            return False
        
        if not device.is_available():
            logger.warning(f"Device not available: {device_id}")
            return False
        
        if not device.connect():
            logger.error(f"Failed to connect to device: {device_id}")
            return False
        
        self._devices[device_id] = device
        self._discovered_devices.add(device_id)
        
        # Set as primary if first device or explicitly marked
        if not self._primary_device or device.device_info.is_primary:
            self._primary_device = device_id
        
        logger.info(f"Registered device: {device_id} ({device.device_info.name})")
        return True
    
    def unregister_device(self, device_id: str) -> None:
        """Unregister a device."""
        if device_id in self._devices:
            device = self._devices[device_id]
            device.disconnect()
            del self._devices[device_id]
            
            if self._primary_device == device_id:
                self._primary_device = None
            if self._active_audio_device == device_id:
                self._active_audio_device = None
            if self._active_camera_device == device_id:
                self._active_camera_device = None
            
            logger.info(f"Unregistered device: {device_id}")
    
    def get_device(self, device_id: str) -> Optional[Device]:
        """Get device by ID."""
        return self._devices.get(device_id)
    
    def get_primary_device(self) -> Optional[Device]:
        """Get primary device."""
        if self._primary_device:
            return self._devices.get(self._primary_device)
        return None
    
    def list_devices(self, device_type: Optional[DeviceType] = None) -> List[DeviceInfo]:
        """List all registered devices."""
        devices = []
        for device in self._devices.values():
            info = device.device_info
            if device_type is None or info.device_type == device_type:
                devices.append(info)
        return devices
    
    def get_audio_devices(self) -> List[AudioDevice]:
        """Get all audio-capable devices."""
        audio_devices = []
        for device in self._devices.values():
            if isinstance(device, AudioDevice):
                audio_devices.append(device)
        return audio_devices
    
    def get_camera_devices(self) -> List[CameraDevice]:
        """Get all camera-capable devices."""
        camera_devices = []
        for device in self._devices.values():
            if isinstance(device, CameraDevice):
                camera_devices.append(device)
        return camera_devices
    
    def set_active_audio_device(self, device_id: str) -> bool:
        """Set active audio device for input/output."""
        device = self._devices.get(device_id)
        if not device or not isinstance(device, AudioDevice):
            logger.error(f"Device not found or not audio-capable: {device_id}")
            return False
        
        self._active_audio_device = device_id
        logger.info(f"Set active audio device: {device_id}")
        return True
    
    def set_active_camera_device(self, device_id: str) -> bool:
        """Set active camera device."""
        device = self._devices.get(device_id)
        if not device or not isinstance(device, CameraDevice):
            logger.error(f"Device not found or not camera-capable: {device_id}")
            return False
        
        self._active_camera_device = device_id
        logger.info(f"Set active camera device: {device_id}")
        return True
    
    def get_active_audio_device(self) -> Optional[AudioDevice]:
        """Get currently active audio device."""
        if self._active_audio_device:
            device = self._devices.get(self._active_audio_device)
            if isinstance(device, AudioDevice):
                return device
        
        # Fallback to primary device
        primary = self.get_primary_device()
        if isinstance(primary, AudioDevice):
            return primary
        
        # Fallback to first available audio device
        audio_devices = self.get_audio_devices()
        if audio_devices:
            return audio_devices[0]
        
        return None
    
    def get_active_camera_device(self) -> Optional[CameraDevice]:
        """Get currently active camera device."""
        if self._active_camera_device:
            device = self._devices.get(self._active_camera_device)
            if isinstance(device, CameraDevice):
                return device
        
        # Fallback to primary device
        primary = self.get_primary_device()
        if isinstance(primary, CameraDevice):
            return primary
        
        # Fallback to first available camera device
        camera_devices = self.get_camera_devices()
        if camera_devices:
            return camera_devices[0]
        
        return None
    
    def discover_devices(self) -> List[DeviceInfo]:
        """
        Discover available devices on network using mDNS/Zeroconf.
        Also includes local device.
        """
        discovered = []
        
        # Include local device
        if self._primary_device:
            device = self._devices.get(self._primary_device)
            if device:
                discovered.append(device.device_info)
        
        # Try mDNS/Zeroconf discovery
        discovered.extend(self._discover_network_devices())
        
        return discovered
    
    def _discover_network_devices(self) -> List[DeviceInfo]:
        """Discover devices on local network using mDNS/Zeroconf."""
        discovered = []
        
        try:
            from zeroconf import ServiceBrowser, Zeroconf, ServiceStateChange
            import time
            
            class ChintuListener:
                def __init__(self):
                    self.devices = []
                
                def add_service(self, zc, type_, name):
                    info = zc.get_service_info(type_, name)
                    if info:
                        self.devices.append({
                            "name": name,
                            "address": info.parsed_addresses()[0] if info.parsed_addresses() else None,
                            "port": info.port
                        })
                
                def remove_service(self, zc, type_, name):
                    pass
                
                def update_service(self, zc, type_, name):
                    pass
            
            zc = Zeroconf()
            listener = ChintuListener()
            browser = ServiceBrowser(zc, "_chintu._tcp.local.", listener)
            
            # Wait briefly for responses
            time.sleep(1)
            
            for dev in listener.devices:
                discovered.append(DeviceInfo(
                    device_id=f"remote-{dev['name']}",
                    name=dev['name'],
                    device_type=DeviceType.DESKTOP,
                    manufacturer="Chintu Node",
                    model="Remote",
                    is_connected=False,
                    is_primary=False
                ))
            
            zc.close()
            
        except ImportError:
            logger.debug("zeroconf not installed, network discovery disabled")
        except Exception as e:
            logger.debug(f"Network discovery error: {e}")
        
        return discovered
    
    def _detect_gpu(self) -> None:
        """Detect GPU capabilities (NVIDIA, AMD, etc.)."""
        self._gpu_info = {
            "available": False,
            "name": None,
            "vram_mb": 0,
            "cuda_available": False,
            "cuda_version": None
        }
        
        # Try nvidia-smi first
        try:
            from chintu_backend.core.safe_exec import safe_run
            
            result = safe_run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                timeout=10
            )
            
            if result.success and result.stdout.strip():
                lines = result.stdout.strip().split('\n')
                first_gpu = lines[0].split(',')
                self._gpu_info["available"] = True
                self._gpu_info["name"] = first_gpu[0].strip()
                self._gpu_info["vram_mb"] = int(float(first_gpu[1].strip())) if len(first_gpu) > 1 else 0
                logger.info(f"Detected GPU: {self._gpu_info['name']} ({self._gpu_info['vram_mb']}MB)")
        except Exception as e:
            logger.debug(f"nvidia-smi not available: {e}")
        
        # Check CUDA availability via torch
        try:
            import torch
            self._gpu_info["cuda_available"] = torch.cuda.is_available()
            if self._gpu_info["cuda_available"]:
                self._gpu_info["cuda_version"] = torch.version.cuda
                if not self._gpu_info["name"]:
                    self._gpu_info["name"] = torch.cuda.get_device_name(0)
                    self._gpu_info["available"] = True
                    self._gpu_info["vram_mb"] = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
                logger.info(f"CUDA available: {self._gpu_info['cuda_version']}")
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"CUDA detection error: {e}")
    
    def get_gpu_info(self) -> Dict[str, Any]:
        """Get GPU information."""
        return self._gpu_info or {"available": False}
    
    def get_device_capabilities(self, device_id: str) -> Optional[DeviceCapabilities]:
        """Get complete capabilities for a device."""
        device = self._devices.get(device_id)
        if not device:
            return None
        
        info = device.device_info
        
        # Extract capabilities based on device type
        audio = None
        camera = None
        display = None
        
        if isinstance(device, AudioDevice):
            audio = device.audio_capabilities
        
        if isinstance(device, CameraDevice):
            camera = device.camera_capabilities
        
        if isinstance(device, DisplayDevice):
            display = device.display_capabilities
        
        # Get compute capabilities including GPU
        try:
            import psutil
            gpu_info = self.get_gpu_info()
            compute = {
                "cpu_count": psutil.cpu_count(),
                "ram_gb": psutil.virtual_memory().total / (1024 ** 3),
                "gpu_available": gpu_info.get("available", False),
                "gpu_name": gpu_info.get("name"),
                "gpu_vram_mb": gpu_info.get("vram_mb", 0),
                "cuda_available": gpu_info.get("cuda_available", False),
                "cuda_version": gpu_info.get("cuda_version")
            }
        except Exception:
            compute = {"gpu_available": False}
        
        # Get network capabilities
        network = {
            "local": True,
            "remote": device_id.startswith("remote-"),
        }
        
        return DeviceCapabilities(
            audio=audio or AudioCapabilities(has_microphone=False, has_speaker=False),
            camera=camera,
            display=display,
            compute=compute,
            network=network,
        )


# Global device manager instance
_device_manager: Optional[DeviceManager] = None


def get_device_manager() -> DeviceManager:
    """Get or create the global device manager."""
    global _device_manager
    if _device_manager is None:
        _device_manager = DeviceManager()
    return _device_manager

