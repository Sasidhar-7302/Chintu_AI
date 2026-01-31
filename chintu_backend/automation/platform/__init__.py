"""
Platform Abstraction Layer for Chintu AI Assistant.
Provides cross-platform support for Windows, macOS, iOS, and Android.
"""

from .detector import PlatformDetector, get_platform, PlatformType
from .audio import PlatformAudioDevice, create_audio_device
from .automation import PlatformAutomation, create_automation

__all__ = [
    "PlatformDetector",
    "get_platform",
    "PlatformType",
    "PlatformAudioDevice",
    "create_audio_device",
    "PlatformAutomation",
    "create_automation",
]

