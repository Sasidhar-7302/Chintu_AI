"""
Easy Device Registration System for Chintu AI Assistant.
Simplifies device registration and discovery with graceful degradation.
"""

import logging
import json
import socket
import uuid
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class DeviceRegistration:
    """Device registration information."""
    device_id: str
    name: str
    platform: str
    ip_address: str
    port: int = 8765
    capabilities: Dict[str, Any] = None
    registered_at: str = ""
    last_seen: str = ""
    is_online: bool = True
    errors: List[str] = None
    
    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = {}
        if self.errors is None:
            self.errors = []
        if not self.registered_at:
            self.registered_at = datetime.now().isoformat()
        if not self.last_seen:
            self.last_seen = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeviceRegistration':
        """Create from dictionary."""
        return cls(**data)


class DeviceRegistry:
    """
    Easy device registration system.
    Supports automatic discovery and manual registration.
    """
    
    def __init__(self, registry_file: Optional[Path] = None):
        if registry_file is None:
            # Default to config directory
            config_dir = Path.home() / ".chintu"
            config_dir.mkdir(exist_ok=True)
            registry_file = config_dir / "devices.json"
        
        self.registry_file = registry_file
        self._devices: Dict[str, DeviceRegistration] = {}
        self._errors: List[str] = []
        
        # Load existing registry
        self._load_registry()
    
    def _load_registry(self):
        """Load device registry from file."""
        try:
            if self.registry_file.exists():
                with open(self.registry_file, 'r') as f:
                    data = json.load(f)
                    for device_data in data.get("devices", []):
                        device = DeviceRegistration.from_dict(device_data)
                        self._devices[device.device_id] = device
                logger.info(f"Loaded {len(self._devices)} devices from registry")
        except Exception as e:
            error_msg = f"Failed to load device registry: {e}"
            self._errors.append(error_msg)
            logger.error(error_msg, exc_info=True)
    
    def _save_registry(self):
        """Save device registry to file."""
        try:
            self.registry_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.registry_file, 'w') as f:
                data = {
                    "devices": [device.to_dict() for device in self._devices.values()],
                    "updated_at": datetime.now().isoformat(),
                }
                json.dump(data, f, indent=2)
            logger.debug(f"Saved {len(self._devices)} devices to registry")
        except Exception as e:
            error_msg = f"Failed to save device registry: {e}"
            self._errors.append(error_msg)
            logger.error(error_msg, exc_info=True)
    
    def get_local_ip(self) -> str:
        """Get local IP address."""
        try:
            # Connect to external server to determine local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            # Fallback to localhost
            return "127.0.0.1"
    
    def auto_register_current_device(
        self,
        name: Optional[str] = None,
        port: int = 8765,
        capabilities: Optional[Dict[str, Any]] = None
    ) -> DeviceRegistration:
        """
        Automatically register the current device.
        This is the EASY way - no manual configuration needed!
        
        Args:
            name: Device name (auto-generated if None)
            port: Device port
            capabilities: Device capabilities (auto-detected if None)
            
        Returns:
            DeviceRegistration instance
        """
        try:
            # Generate device ID
            device_id = str(uuid.uuid4())
            
            # Auto-detect platform
            import platform
            system = platform.system().lower()
            
            # Auto-generate name if not provided
            if name is None:
                hostname = socket.gethostname()
                name = f"{hostname}-{system.title()}"
            
            # Auto-detect capabilities if not provided
            if capabilities is None:
                capabilities = self._detect_capabilities()
            
            # Get local IP
            ip_address = self.get_local_ip()
            
            # Create registration
            device = DeviceRegistration(
                device_id=device_id,
                name=name,
                platform=system,
                ip_address=ip_address,
                port=port,
                capabilities=capabilities,
            )
            
            # Register
            self._devices[device.device_id] = device
            self._save_registry()
            
            logger.info(f"Auto-registered device: {device.name} ({device.device_id[:8]}...)")
            return device
        
        except Exception as e:
            error_msg = f"Auto-registration failed: {e}"
            self._errors.append(error_msg)
            logger.error(error_msg, exc_info=True)
            raise
    
    def _detect_capabilities(self) -> Dict[str, Any]:
        """Auto-detect device capabilities."""
        capabilities = {
            "has_audio": False,
            "has_camera": False,
            "has_gpu": False,
            "supports_llm": False,
            "supports_stt": False,
            "supports_tts": False,
            "errors": [],
        }
        
        try:
            # Detect audio
            try:
                import sounddevice as sd
                devices = sd.query_devices()
                capabilities["has_audio"] = len(devices) > 0
            except ImportError:
                capabilities["errors"].append("Audio detection: sounddevice not installed")
            except Exception as e:
                capabilities["errors"].append(f"Audio detection: {e}")
            
            # Detect camera
            try:
                import platform as _platform
                if _platform.system().lower() == "windows":
                    try:
                        import subprocess
                        result = subprocess.run(
                            ["wmic", "path", "Win32_PnPEntity", "get", "name"],
                            capture_output=True,
                            text=True,
                            timeout=2,
                        )
                        device_list = result.stdout.lower()
                        capabilities["has_camera"] = ("camera" in device_list or "imaging" in device_list)
                    except Exception:
                        capabilities["has_camera"] = False
                else:
                    import cv2
                    cap = cv2.VideoCapture(0)
                    capabilities["has_camera"] = cap.isOpened()
                    cap.release()
            except ImportError:
                capabilities["errors"].append("Camera detection: opencv-python not installed")
            except Exception:
                pass  # Camera not critical
            
            # Detect GPU
            try:
                import torch
                capabilities["has_gpu"] = torch.cuda.is_available()
            except ImportError:
                pass  # GPU not critical
            
            # Assume LLM/STT/TTS support (will degrade gracefully if not available)
            capabilities["supports_llm"] = True
            capabilities["supports_stt"] = True
            capabilities["supports_tts"] = True
        
        except Exception as e:
            capabilities["errors"].append(f"Capability detection failed: {e}")
        
        return capabilities
    
    def register_device(
        self,
        device_id: str,
        name: str,
        platform: str,
        ip_address: str,
        port: int = 8765,
        capabilities: Optional[Dict[str, Any]] = None
    ) -> DeviceRegistration:
        """
        Manually register a device (advanced option).
        
        Args:
            device_id: Unique device ID
            name: Device name
            platform: Platform type (windows/macos/linux)
            ip_address: Device IP address
            port: Device port
            capabilities: Device capabilities
            
        Returns:
            DeviceRegistration instance
        """
        device = DeviceRegistration(
            device_id=device_id,
            name=name,
            platform=platform,
            ip_address=ip_address,
            port=port,
            capabilities=capabilities or {},
        )
        
        self._devices[device.device_id] = device
        self._save_registry()
        
        logger.info(f"Registered device: {device.name} ({device.device_id[:8]}...)")
        return device
    
    def unregister_device(self, device_id: str) -> bool:
        """Unregister a device."""
        if device_id in self._devices:
            del self._devices[device_id]
            self._save_registry()
            logger.info(f"Unregistered device: {device_id[:8]}...")
            return True
        return False
    
    def get_device(self, device_id: str) -> Optional[DeviceRegistration]:
        """Get device by ID."""
        return self._devices.get(device_id)
    
    def get_all_devices(self) -> List[DeviceRegistration]:
        """Get all registered devices."""
        return list(self._devices.values())
    
    def discover_devices(self, timeout: float = 2.0) -> List[DeviceRegistration]:
        """
        Discover devices on local network (simple implementation).
        
        This uses a simple broadcast/multicast approach.
        For more advanced discovery, use mDNS/Bonjour (future enhancement).
        
        Args:
            timeout: Discovery timeout in seconds
            
        Returns:
            List of discovered devices
        """
        discovered = []
        
        try:
            # Simple discovery: ping known registered devices
            for device in self._devices.values():
                if self._ping_device(device.ip_address, device.port, timeout):
                    device.is_online = True
                    device.last_seen = datetime.now().isoformat()
                    discovered.append(device)
                else:
                    device.is_online = False
            
            self._save_registry()
            logger.info(f"Discovered {len(discovered)} online devices")
        
        except Exception as e:
            error_msg = f"Device discovery failed: {e}"
            self._errors.append(error_msg)
            logger.error(error_msg, exc_info=True)
        
        return discovered
    
    def _ping_device(self, ip: str, port: int, timeout: float) -> bool:
        """Ping a device to check if it's online."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    def get_errors(self) -> List[str]:
        """Get list of errors."""
        return self._errors.copy()
    
    def get_status_message(self) -> str:
        """Get human-readable status message."""
        messages = []
        messages.append(f"Device Registry Status:")
        messages.append(f"  Registered Devices: {len(self._devices)}")
        
        online = sum(1 for d in self._devices.values() if d.is_online)
        messages.append(f"  Online Devices: {online}")
        
        if self._errors:
            messages.append(f"  Errors: {len(self._errors)}")
            for error in self._errors[:3]:  # Show first 3 errors
                messages.append(f"    - {error}")
        
        return "\n".join(messages)


# Global registry instance
_registry: Optional[DeviceRegistry] = None


def get_device_registry() -> DeviceRegistry:
    """Get or create the global device registry."""
    global _registry
    if _registry is None:
        _registry = DeviceRegistry()
    return _registry

