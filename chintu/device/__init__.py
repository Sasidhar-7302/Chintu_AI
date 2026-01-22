"""
Device Abstraction Layer for Chintu AI Assistant.
Enables multi-device support, distributed computing, and cross-platform capabilities.
"""

from .device_manager import DeviceManager, DeviceType, DeviceCapabilities, get_device_manager
from .device_interface import Device, AudioDevice, CameraDevice, DisplayDevice
from .capabilities import DeviceCapabilityRegistry
from .mobile_connector import MobileConnector, MobileDevice, get_mobile_connector
from .mobile_capabilities import register_mobile_capabilities
from .phone_capabilities import register_phone_capabilities

__all__ = [
    "DeviceManager",
    "DeviceType",
    "DeviceCapabilities",
    "get_device_manager",
    "Device",
    "AudioDevice",
    "CameraDevice",
    "DisplayDevice",
    "DeviceCapabilityRegistry",
    "MobileConnector",
    "MobileDevice",
    "get_mobile_connector",
    "register_mobile_capabilities",
    "register_phone_capabilities",
]
