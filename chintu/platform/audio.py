"""
Platform-specific audio implementations.
Provides cross-platform audio device abstraction.
"""

import logging
from typing import Optional, Callable
import numpy as np

from ..device.device_interface import AudioDevice, AudioCapabilities, DeviceInfo, DeviceType

logger = logging.getLogger(__name__)


class PlatformAudioDevice(AudioDevice):
    """Platform-specific audio device implementation."""
    
    def __init__(self, platform_type: str = "windows"):
        self._platform_type = platform_type
        self._device_id = self._generate_device_id()
        self._initialized = False
        self._available = False
        self._errors: list[str] = []
        
        # Platform-specific implementation
        self._audio_impl = None
        
        # Initialize based on platform
        self._init_platform_audio()
    
    def _generate_device_id(self) -> str:
        """Generate unique device ID."""
        import socket
        import uuid
        hostname = socket.gethostname()
        return f"{hostname}-audio-{uuid.uuid4().hex[:8]}"
    
    def _init_platform_audio(self):
        """Initialize platform-specific audio."""
        try:
            if self._platform_type == "windows":
                self._init_windows_audio()
            elif self._platform_type == "macos":
                self._init_macos_audio()
            elif self._platform_type == "linux":
                self._init_linux_audio()
            else:
                self._errors.append(f"Unsupported platform: {self._platform_type}")
                logger.warning(f"Audio not available for platform: {self._platform_type}")
        
        except Exception as e:
            error_msg = f"Audio initialization failed: {e}"
            self._errors.append(error_msg)
            logger.error(error_msg, exc_info=True)
            self._available = False
    
    def _init_windows_audio(self):
        """Initialize Windows audio (sounddevice)."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            
            if not devices:
                raise RuntimeError("No audio devices found")
            
            # Find default input device
            default_input = sd.default.device[0] if sd.default.device else None
            if default_input is None:
                # Find first input device
                for i, dev in enumerate(devices):
                    if dev['max_input_channels'] > 0:
                        default_input = i
                        break
            
            if default_input is None:
                raise RuntimeError("No microphone found")
            
            self._audio_impl = {
                "type": "sounddevice",
                "input_device": default_input,
                "sample_rate": 16000,
                "channels": 1,
            }
            self._available = True
            self._initialized = True
            logger.info(f"Windows audio initialized (device: {default_input})")
        
        except ImportError:
            self._errors.append("sounddevice not installed")
            logger.error("sounddevice not installed - audio unavailable")
        except Exception as e:
            self._errors.append(f"Windows audio init failed: {e}")
            logger.error(f"Windows audio initialization failed: {e}")
    
    def _init_macos_audio(self):
        """Initialize macOS audio."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            
            if not devices:
                raise RuntimeError("No audio devices found")
            
            default_input = sd.default.device[0] if sd.default.device else None
            if default_input is None:
                for i, dev in enumerate(devices):
                    if dev['max_input_channels'] > 0:
                        default_input = i
                        break
            
            if default_input is None:
                raise RuntimeError("No microphone found")
            
            self._audio_impl = {
                "type": "sounddevice",
                "input_device": default_input,
                "sample_rate": 16000,
                "channels": 1,
            }
            self._available = True
            self._initialized = True
            logger.info(f"macOS audio initialized (device: {default_input})")
        
        except ImportError:
            self._errors.append("sounddevice not installed")
            logger.error("sounddevice not installed - audio unavailable")
        except Exception as e:
            self._errors.append(f"macOS audio init failed: {e}")
            logger.error(f"macOS audio initialization failed: {e}")
    
    def _init_linux_audio(self):
        """Initialize Linux audio."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            
            if not devices:
                raise RuntimeError("No audio devices found")
            
            default_input = sd.default.device[0] if sd.default.device else None
            if default_input is None:
                for i, dev in enumerate(devices):
                    if dev['max_input_channels'] > 0:
                        default_input = i
                        break
            
            if default_input is None:
                raise RuntimeError("No microphone found")
            
            self._audio_impl = {
                "type": "sounddevice",
                "input_device": default_input,
                "sample_rate": 16000,
                "channels": 1,
            }
            self._available = True
            self._initialized = True
            logger.info(f"Linux audio initialized (device: {default_input})")
        
        except ImportError:
            self._errors.append("sounddevice not installed")
            logger.error("sounddevice not installed - audio unavailable")
        except Exception as e:
            self._errors.append(f"Linux audio init failed: {e}")
            logger.error(f"Linux audio initialization failed: {e}")
    
    @property
    def device_id(self) -> str:
        """Get unique device ID."""
        return self._device_id
    
    @property
    def device_info(self) -> DeviceInfo:
        """Get device information."""
        from ..device.device_interface import DeviceInfo, DeviceType
        
        import platform
        system = platform.system().lower()
        
        if system == "windows":
            device_type = DeviceType.DESKTOP
        elif system == "darwin":
            device_type = DeviceType.DESKTOP
        elif system == "linux":
            device_type = DeviceType.DESKTOP
        else:
            device_type = DeviceType.DESKTOP
        
        return DeviceInfo(
            device_id=self._device_id,
            name=f"{system.title()} Audio Device",
            device_type=device_type,
            platform=system,
            capabilities={
                "audio": True,
                "errors": self._errors,
            },
            is_primary=True,
            is_online=self._available,
        )
    
    @property
    def audio_capabilities(self) -> AudioCapabilities:
        """Get audio capabilities."""
        has_mic = self._available and len(self._errors) == 0
        
        return AudioCapabilities(
            has_microphone=has_mic,
            has_speaker=True,  # Assume speaker available
            has_headphones=False,  # Can't detect
            sample_rate=16000,
            channels=1,
            supports_multichannel=False,
            supports_beamforming=False,
            device_list=[self._device_id] if has_mic else [],
        )
    
    def is_available(self) -> bool:
        """Check if device is available."""
        return self._available and self._initialized
    
    def connect(self) -> bool:
        """Connect to audio device."""
        if not self._available:
            return False
        
        try:
            # Test audio device
            if self._audio_impl and self._audio_impl["type"] == "sounddevice":
                import sounddevice as sd
                # Try to query device
                sd.query_devices(self._audio_impl["input_device"])
                return True
        except Exception as e:
            logger.error(f"Failed to connect to audio device: {e}")
            self._errors.append(f"Connection failed: {e}")
            return False
        
        return False
    
    def disconnect(self) -> None:
        """Disconnect from audio device."""
        # Sounddevice doesn't require explicit disconnect
        pass
    
    def capture_audio(self, duration: Optional[float] = None) -> np.ndarray:
        """Capture audio from microphone."""
        if not self.is_available():
            raise RuntimeError(f"Audio device not available. Errors: {self._errors}")
        
        if self._audio_impl and self._audio_impl["type"] == "sounddevice":
            import sounddevice as sd
            
            if duration:
                samples = int(duration * self._audio_impl["sample_rate"])
            else:
                # One chunk (100ms)
                samples = self._audio_impl["sample_rate"] // 10
            
            try:
                audio = sd.rec(
                    samples,
                    samplerate=self._audio_impl["sample_rate"],
                    channels=self._audio_impl["channels"],
                    device=self._audio_impl["input_device"],
                    dtype=np.float32,
                )
                sd.wait()
                return audio.flatten()
            except Exception as e:
                error_msg = f"Audio capture failed: {e}"
                self._errors.append(error_msg)
                logger.error(error_msg)
                raise RuntimeError(error_msg) from e
        
        raise RuntimeError("Audio implementation not initialized")
    
    def play_audio(self, audio: np.ndarray) -> None:
        """Play audio through speaker."""
        if not self.is_available():
            logger.warning("Audio device not available for playback")
            return
        
        try:
            if self._audio_impl and self._audio_impl["type"] == "sounddevice":
                import sounddevice as sd
                
                sd.play(
                    audio,
                    samplerate=self._audio_impl["sample_rate"],
                    device=sd.default.device[1] if sd.default.device else None,
                )
                sd.wait()
        except Exception as e:
            logger.warning(f"Audio playback failed: {e}")
    
    def get_audio_level(self) -> float:
        """Get current audio input level."""
        if not self.is_available():
            return 0.0
        
        try:
            # Capture a small chunk and compute RMS
            chunk = self.capture_audio(duration=0.1)
            rms = np.sqrt(np.mean(chunk ** 2))
            return float(rms)
        except Exception:
            return 0.0
    
    def get_errors(self) -> list[str]:
        """Get list of errors for this device."""
        return self._errors.copy()


def create_audio_device(platform_type: Optional[str] = None) -> PlatformAudioDevice:
    """
    Create a platform-appropriate audio device.
    
    Args:
        platform_type: Platform type (auto-detected if None)
        
    Returns:
        PlatformAudioDevice instance
    """
    if platform_type is None:
        from .detector import get_platform
        detector = get_platform()
        platform_type = detector.platform.value
    
    return PlatformAudioDevice(platform_type=platform_type)

