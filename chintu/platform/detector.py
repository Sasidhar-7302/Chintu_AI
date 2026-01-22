"""
Platform Detection for Chintu AI Assistant.
Auto-detects OS and platform capabilities.
"""

import platform
import sys
import logging
from enum import Enum
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class PlatformType(Enum):
    """Supported platform types."""
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    IOS = "ios"          # Future: iOS
    ANDROID = "android"  # Future: Android
    UNKNOWN = "unknown"


class PlatformCapabilities:
    """Platform capabilities."""
    
    def __init__(self):
        self.has_audio = False
        self.has_camera = False
        self.has_gpu = False
        self.has_microphone = False
        self.has_speaker = False
        self.supports_app_launching = False
        self.supports_browser_control = False
        self.supports_file_access = True  # Most platforms support file access
        self.supports_wake_word = True    # Can run wake word detection
        self.supports_stt = True          # Can run speech-to-text
        self.supports_tts = True          # Can run text-to-speech
        self.errors: Dict[str, str] = {}  # Errors for missing features
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "has_audio": self.has_audio,
            "has_camera": self.has_camera,
            "has_gpu": self.has_gpu,
            "has_microphone": self.has_microphone,
            "has_speaker": self.has_speaker,
            "supports_app_launching": self.supports_app_launching,
            "supports_browser_control": self.supports_browser_control,
            "supports_file_access": self.supports_file_access,
            "supports_wake_word": self.supports_wake_word,
            "supports_stt": self.supports_stt,
            "supports_tts": self.supports_tts,
            "errors": self.errors,
        }


class PlatformDetector:
    """Detects platform and capabilities."""
    
    def __init__(self):
        self.platform_type = self._detect_platform()
        self.capabilities = self._detect_capabilities()
        
        logger.info(
            f"Platform detected: {self.platform_type.value} "
            f"(Audio: {self.capabilities.has_audio}, "
            f"Camera: {self.capabilities.has_camera}, "
            f"GPU: {self.capabilities.has_gpu})"
        )
        
        # Log any errors
        if self.capabilities.errors:
            for feature, error in self.capabilities.errors.items():
                logger.warning(f"Feature '{feature}' unavailable: {error}")
    
    def _detect_platform(self) -> PlatformType:
        """Detect the current platform."""
        system = platform.system().lower()
        
        if system == "windows":
            return PlatformType.WINDOWS
        elif system == "darwin":
            return PlatformType.MACOS
        elif system == "linux":
            # Check if Android (via Termux or other indicators)
            if "android" in platform.platform().lower():
                return PlatformType.ANDROID
            return PlatformType.LINUX
        else:
            return PlatformType.UNKNOWN
    
    def _detect_capabilities(self) -> PlatformCapabilities:
        """Detect platform capabilities."""
        caps = PlatformCapabilities()
        
        try:
            # Detect audio (microphone/speaker)
            try:
                import sounddevice as sd
                devices = sd.query_devices()
                caps.has_audio = True
                caps.has_microphone = any(d['max_input_channels'] > 0 for d in devices)
                caps.has_speaker = any(d['max_output_channels'] > 0 for d in devices)
            except ImportError:
                caps.errors["audio"] = "sounddevice not installed"
            except Exception as e:
                caps.errors["audio"] = f"Audio detection failed: {e}"
                logger.warning(f"Audio detection failed: {e}")
            
            # Detect camera
            try:
                import cv2
                cap = cv2.VideoCapture(0)
                if cap.isOpened():
                    caps.has_camera = True
                    cap.release()
            except ImportError:
                caps.errors["camera"] = "opencv-python not installed"
            except Exception as e:
                caps.errors["camera"] = f"Camera detection failed: {e}"
                logger.debug(f"Camera detection failed: {e}")
            
            # Detect GPU
            try:
                if self.platform_type == PlatformType.WINDOWS:
                    # Check for NVIDIA GPU on Windows
                    import subprocess
                    result = subprocess.run(
                        ['wmic', 'path', 'win32_VideoController', 'get', 'name'],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if 'NVIDIA' in result.stdout or 'AMD' in result.stdout or 'Intel' in result.stdout:
                        caps.has_gpu = True
                elif self.platform_type in (PlatformType.MACOS, PlatformType.LINUX):
                    # Check for GPU on macOS/Linux
                    try:
                        import torch
                        caps.has_gpu = torch.cuda.is_available()
                    except ImportError:
                        pass
            except Exception as e:
                logger.debug(f"GPU detection failed: {e}")
            
            # Platform-specific capabilities
            if self.platform_type == PlatformType.WINDOWS:
                try:
                    import pywinauto
                    caps.supports_app_launching = True
                    caps.supports_browser_control = True
                except ImportError:
                    caps.errors["automation"] = "pywinauto not installed"
            
            elif self.platform_type == PlatformType.MACOS:
                try:
                    import subprocess
                    # Check if we can launch apps (use 'open' command)
                    result = subprocess.run(['which', 'open'], capture_output=True)
                    caps.supports_app_launching = result.returncode == 0
                    caps.supports_browser_control = True  # macOS supports browser automation
                except Exception as e:
                    caps.errors["automation"] = f"macOS automation check failed: {e}"
            
            elif self.platform_type == PlatformType.LINUX:
                # Linux supports basic automation
                caps.supports_app_launching = True
                caps.supports_browser_control = True
            
            # iOS/Android - future support
            if self.platform_type in (PlatformType.IOS, PlatformType.ANDROID):
                caps.supports_app_launching = False  # Limited on mobile
                caps.supports_browser_control = False  # Limited on mobile
                caps.supports_file_access = False  # Limited on mobile
        
        except Exception as e:
            logger.error(f"Error detecting capabilities: {e}")
            caps.errors["detection"] = f"Capability detection failed: {e}"
        
        return caps
    
    @property
    def platform(self) -> PlatformType:
        """Get detected platform type."""
        return self.platform_type
    
    @property
    def is_windows(self) -> bool:
        """Check if Windows."""
        return self.platform_type == PlatformType.WINDOWS
    
    @property
    def is_macos(self) -> bool:
        """Check if macOS."""
        return self.platform_type == PlatformType.MACOS
    
    @property
    def is_linux(self) -> bool:
        """Check if Linux."""
        return self.platform_type == PlatformType.LINUX
    
    @property
    def is_mobile(self) -> bool:
        """Check if mobile platform."""
        return self.platform_type in (PlatformType.IOS, PlatformType.ANDROID)
    
    def get_status_message(self) -> str:
        """Get human-readable status message for user."""
        messages = []
        messages.append(f"Platform: {self.platform_type.value.title()}")
        
        if self.capabilities.has_audio:
            messages.append("✅ Audio: Available")
        else:
            messages.append("❌ Audio: Unavailable")
            if "audio" in self.capabilities.errors:
                messages.append(f"   Reason: {self.capabilities.errors['audio']}")
        
        if self.capabilities.has_camera:
            messages.append("✅ Camera: Available")
        else:
            messages.append("⚠️ Camera: Unavailable")
            if "camera" in self.capabilities.errors:
                messages.append(f"   Reason: {self.capabilities.errors['camera']}")
        
        if self.capabilities.has_gpu:
            messages.append("✅ GPU: Available")
        else:
            messages.append("ℹ️ GPU: Not detected (using CPU)")
        
        if self.capabilities.errors:
            messages.append(f"\n⚠️ Some features unavailable. Check logs for details.")
        
        return "\n".join(messages)


# Global detector instance
_detector: Optional[PlatformDetector] = None


def get_platform() -> PlatformDetector:
    """Get or create the global platform detector."""
    global _detector
    if _detector is None:
        _detector = PlatformDetector()
    return _detector

