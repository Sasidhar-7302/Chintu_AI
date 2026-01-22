"""Audio capture from microphone."""

import numpy as np
import threading
import queue
from typing import Optional, Callable
import logging

logger = logging.getLogger(__name__)

# Try to import audio libraries
try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False
    logger.warning("sounddevice not available, trying pyaudio")

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False


class AudioCapture:
    """Captures audio from the microphone continuously."""
    
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024,
        device: Optional[int] = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.device = device
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._audio_queue: queue.Queue = queue.Queue()
        self._callbacks: list[Callable[[np.ndarray], None]] = []
        self._level_callback: Optional[Callable[[float], None]] = None
        self._record_lock = threading.Lock()
        self._record_session = None
        
        # Select backend
        if HAS_SOUNDDEVICE:
            self._backend = "sounddevice"
        elif HAS_PYAUDIO:
            self._backend = "pyaudio"
            self._pa = pyaudio.PyAudio()
        else:
            raise RuntimeError("No audio backend available. Install sounddevice or pyaudio.")
        
        logger.info(f"AudioCapture using {self._backend} backend")
    
    def add_callback(self, callback: Callable[[np.ndarray], None]):
        """Add a callback to receive audio chunks."""
        self._callbacks.append(callback)
    
    def set_level_callback(self, callback: Callable[[float], None]):
        """Set callback for audio level updates (for waveform)."""
        self._level_callback = callback
    
    def start(self):
        """Start capturing audio."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("Audio capture started")
    
    def stop(self):
        """Stop capturing audio."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("Audio capture stopped")
    
    def _capture_loop(self):
        """Main capture loop running in background thread."""
        if self._backend == "sounddevice":
            self._capture_sounddevice()
        else:
            self._capture_pyaudio()
    
    def _capture_sounddevice(self):
        """Capture using sounddevice."""
        chunk_count = [0]  # Mutable counter in closure
        def callback(indata, frames, time_info, status):
            chunk_count[0] += 1
            if status:
                if "input overflow" in str(status):
                    # Ignore occasional overflows, just warn
                    logger.debug(f"Audio status: {status}")
                else:
                    logger.warning(f"Audio status: {status}")
            
            # Debug: Log every 500 chunks (~30 seconds at 16kHz/1024)
            if chunk_count[0] % 500 == 0:
                logger.debug(f"AudioCapture: {chunk_count[0]} chunks processed")

            if self._callbacks:
                data = indata.copy().flatten()
                
                # Update level (RMS)
                if self._level_callback and len(data) > 0:
                    rms = np.sqrt(np.mean(data**2))
                    try:
                        self._level_callback(float(rms))
                    except Exception:
                        pass

                for cb in self._callbacks:
                    try:
                        cb(data)
                    except Exception as e:
                        logger.error(f"Error in audio callback: {e}")

        try:
            # Increase blocksize to reduce overflow risk (was likely default ~1024 or variable)
            # 4096 frames @ 16kHz = ~250ms chunks.
            # 'high' latency also helps stability.
            params = {
                "samplerate": self.sample_rate,
                "channels": self.channels,
                "callback": callback,
                "blocksize": 4096, # Increased from default
                "latency": "high"  # Relaxed latency constraints
            }
            if self.device is not None:
                params["device"] = self.device
            
            with sd.InputStream(**params):
                logger.info(f"Sounddevice InputStream opened successfully (blocksize=4096)")
                while self._running:
                    sd.sleep(100)
        except Exception as e:
            logger.error(f"Sounddevice error: {e}")
            self._running = False
    
    def _capture_pyaudio(self):
        """Capture using pyaudio."""
        try:
            stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                input_device_index=self.device,
            )
            
            while self._running:
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.float32)
                self._process_audio(audio_data)
            
            stream.stop_stream()
            stream.close()
        except Exception as e:
            logger.error(f"Error in pyaudio capture: {e}")
    
    def _process_audio(self, audio_data: np.ndarray):
        """Process captured audio data."""
        # Calculate audio level (RMS)
        rms = np.sqrt(np.mean(audio_data ** 2))
        level = min(1.0, rms * 10)  # Scale for visibility
        
        if self._level_callback:
            self._level_callback(level)

        session = None
        with self._record_lock:
            session = self._record_session
        if session is not None:
            session["buffer"].append(audio_data.copy())
            session["samples"] += len(audio_data)
            if session["samples"] >= session["target"]:
                session["event"].set()
        
        # Call registered callbacks
        for callback in self._callbacks:
            try:
                callback(audio_data)
            except Exception as e:
                logger.error(f"Error in audio callback: {e}")
    
    def get_audio_chunk(self, timeout: float = 0.1) -> Optional[np.ndarray]:
        """Get an audio chunk from the queue."""
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def record_samples(self, duration_seconds: float, timeout: Optional[float] = None) -> np.ndarray:
        """Record a fixed duration from the live audio stream."""
        if not self._running:
            raise RuntimeError("Audio capture is not running")
        if duration_seconds <= 0:
            raise ValueError("Duration must be positive")

        target_samples = int(duration_seconds * self.sample_rate)
        if target_samples <= 0:
            raise ValueError("Duration too short")

        event = threading.Event()
        session = {
            "target": target_samples,
            "buffer": [],
            "samples": 0,
            "event": event,
        }

        with self._record_lock:
            if self._record_session is not None:
                raise RuntimeError("A recording is already in progress")
            self._record_session = session

        wait_timeout = timeout if timeout is not None else duration_seconds + 2.0
        finished = event.wait(wait_timeout)

        with self._record_lock:
            self._record_session = None

        if not finished or not session["buffer"]:
            raise RuntimeError("Timed out while recording audio")

        audio = np.concatenate(session["buffer"])
        if len(audio) > target_samples:
            audio = audio[:target_samples]
        return audio

    @property
    def is_running(self) -> bool:
        """Check if audio capture is running."""
        return self._running
    
    def __del__(self):
        """Cleanup resources."""
        self.stop()
        if hasattr(self, "_pa"):
            self._pa.terminate()
