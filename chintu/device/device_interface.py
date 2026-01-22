"""
Device Interface Definitions for Chintu AI Assistant.
Abstract base classes for audio, camera, and display devices.
Enables multi-device support and distributed computing.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
import numpy as np


class DeviceType(Enum):
    """Types of devices."""
    DESKTOP = "desktop"       # Windows, macOS, Linux desktop
    LAPTOP = "laptop"         # Windows, macOS laptop
    MOBILE = "mobile"         # iOS, Android phone
    TABLET = "tablet"         # iOS, Android tablet
    SERVER = "server"         # Cloud/server compute node
    IOT = "iot"              # IoT device


@dataclass
class DeviceInfo:
    """Device information."""
    device_id: str
    name: str
    device_type: DeviceType
    platform: str              # "windows", "macos", "ios", "android"
    capabilities: Dict[str, Any]
    location: Optional[str] = None  # Room/home identifier
    is_primary: bool = False
    is_online: bool = True


@dataclass
class AudioCapabilities:
    """Audio device capabilities."""
    has_microphone: bool = True
    has_speaker: bool = True
    has_headphones: bool = False
    sample_rate: int = 16000
    channels: int = 1
    supports_multichannel: bool = False
    supports_beamforming: bool = False
    device_list: List[str] = None  # Available audio devices


@dataclass
class CameraCapabilities:
    """Camera device capabilities."""
    has_camera: bool = True
    resolution: tuple = (1920, 1080)
    supports_night_mode: bool = False
    supports_tracking: bool = False
    fps: int = 30


@dataclass
class DisplayCapabilities:
    """Display device capabilities."""
    has_display: bool = True
    resolution: tuple = (1920, 1080)
    supports_touch: bool = False
    is_primary: bool = False


class Device(ABC):
    """Base device interface."""
    
    @property
    @abstractmethod
    def device_id(self) -> str:
        """Unique device identifier."""
        pass
    
    @property
    @abstractmethod
    def device_info(self) -> DeviceInfo:
        """Device information."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if device is available."""
        pass
    
    @abstractmethod
    def connect(self) -> bool:
        """Connect to device."""
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from device."""
        pass


class AudioDevice(Device):
    """Audio device interface (microphone/speaker)."""
    
    @property
    @abstractmethod
    def audio_capabilities(self) -> AudioCapabilities:
        """Audio device capabilities."""
        pass
    
    @abstractmethod
    def capture_audio(self, duration: float = None) -> np.ndarray:
        """
        Capture audio from microphone.
        
        Args:
            duration: Capture duration in seconds (None = one chunk)
            
        Returns:
            Audio data as numpy array (float32, mono, 16kHz)
        """
        pass
    
    @abstractmethod
    def play_audio(self, audio: np.ndarray) -> None:
        """
        Play audio through speaker.
        
        Args:
            audio: Audio data as numpy array (float32, mono, 16kHz)
        """
        pass
    
    @abstractmethod
    def get_audio_level(self) -> float:
        """Get current audio input level (0.0 to 1.0)."""
        pass


class CameraDevice(Device):
    """Camera device interface."""
    
    @property
    @abstractmethod
    def camera_capabilities(self) -> CameraCapabilities:
        """Camera device capabilities."""
        pass
    
    @abstractmethod
    def capture_frame(self) -> Optional[np.ndarray]:
        """
        Capture a frame from camera.
        
        Returns:
            Image frame as numpy array (BGR format) or None if unavailable
        """
        pass
    
    @abstractmethod
    def start_stream(self, callback) -> None:
        """Start camera stream with callback."""
        pass
    
    @abstractmethod
    def stop_stream(self) -> None:
        """Stop camera stream."""
        pass


class DisplayDevice(Device):
    """Display device interface."""
    
    @property
    @abstractmethod
    def display_capabilities(self) -> DisplayCapabilities:
        """Display device capabilities."""
        pass
    
    @abstractmethod
    def show_message(self, message: str, duration: float = 3.0) -> None:
        """Display a message on screen."""
        pass
    
    @abstractmethod
    def show_image(self, image: np.ndarray) -> None:
        """Display an image on screen."""
        pass

