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


class AudioLevelDetector:
    """Detects high volume levels for barge-in (interruption)."""
    
    def __init__(self, threshold: float = 0.3, min_duration: float = 0.2):
        self.threshold = threshold
        self.min_duration = min_duration
        self._consecutive_loud_chunks = 0
        self._on_speech_detected: Optional[Callable[[], None]] = None
        
    def set_callback(self, callback: Callable[[], None]):
        self._on_speech_detected = callback
        
    def process(self, level: float):
        """Process an audio level sample (0.0 to 1.0)."""
        if level > self.threshold:
            self._consecutive_loud_chunks += 1
            # Assuming ~20ms chunks, 10 chunks = 200ms
            if self._consecutive_loud_chunks >= (self.min_duration * 50): 
                if self._on_speech_detected:
                    self._on_speech_detected()
                    # Reset to avoid continuous firing
                    self._consecutive_loud_chunks = 0
        else:
            self._consecutive_loud_chunks = 0


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
        self._processor_thread: Optional[threading.Thread] = None
        self._audio_queue: queue.Queue = queue.Queue()
        self._processing_queue: queue.Queue = queue.Queue(maxsize=8)
        self._queue_drop_count = 0
        self._callbacks: list[Callable[[np.ndarray], None]] = []
        self._level_callback: Optional[Callable[[float], None]] = None
        self._record_lock = threading.Lock()
        self._record_session = None
        self._backend: Optional[str] = None
        
        # Barge-in detector
        self.barge_in_detector = AudioLevelDetector(threshold=0.4)  # 40% volume threshold
        
        # Select backend with graceful degradation
        if HAS_SOUNDDEVICE:
            self._backend = "sounddevice"
        elif HAS_PYAUDIO:
            self._backend = "pyaudio"
            self._pa = pyaudio.PyAudio()
        else:
            # Do NOT raise here – run headless without audio so UI can still launch.
            self._backend = None
            logger.info("No audio backend available. Install 'sounddevice' or 'pyaudio'. Running without microphone support.")
            try:
                from chintu_backend.core.state import get_state_manager
                sm = get_state_manager()
                sm.update_feature(
                    "audio",
                    enabled=False,
                    status="inactive",
                    error="No audio backend available (install sounddevice or pyaudio)",
                )
                sm.update_feature(
                    "microphone",
                    enabled=False,
                    status="inactive",
                    error="No audio backend available (install sounddevice or pyaudio)",
                )
            except Exception:
                # State manager might not be ready yet during early startup.
                pass
            try:
                from chintu_backend.core.error_reporter import report_error, ErrorSeverity
                report_error(
                    Exception("No audio backend available"),
                    severity=ErrorSeverity.WARNING,
                    component="audio",
                    user_message="Audio libraries are missing. Voice input is disabled, but the assistant UI is running.",
                )
            except Exception:
                # Error reporter is optional; fail silently if unavailable.
                pass
        
        if self._backend:
            logger.info(f"AudioCapture using {self._backend} backend")
    
    def add_callback(self, callback: Callable[[np.ndarray], None]):
        """Add a callback to receive audio chunks."""
        self._callbacks.append(callback)
    
    def set_level_callback(self, callback: Callable[[float], None]):
        """Set callback for audio level updates (for waveform)."""
        self._level_callback = callback
    
    def check_hardware_available(self) -> bool:
        """Check if any microphone hardware is actually available."""
        if not self._backend:
            return False
        
        try:
            if self._backend == "sounddevice":
                devices = sd.query_devices()
                has_input = any(d.get("max_input_channels", 0) > 0 for d in devices)
                return has_input
            elif self._backend == "pyaudio" and hasattr(self, "_pa"):
                count = self._pa.get_device_count()
                for i in range(count):
                    info = self._pa.get_device_info_by_index(i)
                    if info.get("maxInputChannels", 0) > 0:
                        return True
                return False
        except Exception as e:
            logger.debug(f"Audio hardware check failed: {e}")
            return False
        return False

    def start(self):
        """Start capturing audio."""
        if self._running:
            return
        
        if self._backend is None:
            # No audio backend – keep running without microphone, but do not start capture thread.
            logger.info("AudioCapture.start() called with no available backend; skipping microphone capture.")
            return
        
        # Verify hardware before starting
        if not self.check_hardware_available():
            logger.info("No microphone detected. Audio capture will not start.")
            try:
                from chintu_backend.core.state import get_state_manager
                sm = get_state_manager()
                sm.update_feature("microphone", enabled=False, status="inactive", error="No microphone detected")
            except Exception:
                pass
            return
        
        self._running = True
        self._processor_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._processor_thread.start()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("Audio capture started")
    
    def stop(self):
        """Stop capturing audio."""
        self._running = False
        try:
            self._processing_queue.put_nowait(None)
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._processor_thread:
            self._processor_thread.join(timeout=2.0)
        logger.info("Audio capture stopped")

    def _process_loop(self):
        """Process audio chunks in a separate thread."""
        while self._running or not self._processing_queue.empty():
            try:
                item = self._processing_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                self._process_audio(item)
            except Exception as exc:
                logger.error(f"Error processing audio: {exc}")
    
    def _capture_loop(self):
        """Main capture loop running in background thread."""
        if self._backend == "sounddevice":
            self._capture_sounddevice()
        else:
            self._capture_pyaudio()
    
    def _capture_sounddevice(self):
        """Capture using sounddevice."""
        # Validate input device availability
        selected_input = None
        try:
            devices = sd.query_devices()
            has_input = any(d.get("max_input_channels", 0) > 0 for d in devices)
            if not has_input:
                device_list_str = "\n".join([f"{i}: {d['name']} (In: {d.get('max_input_channels', 0)})" for i, d in enumerate(devices)])
                logger.info(f"No microphone detected. Found devices:\n{device_list_str}")
                self._running = False
                try:
                    from chintu_backend.core.state import get_state_manager
                    sm = get_state_manager()
                    sm.update_feature("audio", enabled=False, status="inactive", error="No microphone detected")
                    sm.update_feature("microphone", enabled=False, status="inactive", error="No microphone detected")
                except Exception:
                    pass
                try:
                    from chintu_backend.core.error_reporter import report_error, ErrorSeverity
                    report_error(
                        Exception("No microphone detected"),
                        severity=ErrorSeverity.WARNING,
                        component="microphone",
                        user_message="Microphone not detected. Checked all devices but none reported input channels.",
                    )
                except Exception:
                    pass
                return
            for idx, d in enumerate(devices):
                if d.get("max_input_channels", 0) > 0:
                    selected_input = idx
                    break
        except Exception as e:
            logger.warning(f"Audio device query failed: {e}")
            devices = []

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

            data = indata.copy().flatten()
            # Fan out to queues quickly to avoid blocking the capture thread
            try:
                self._audio_queue.put_nowait(data)
            except queue.Full:
                pass
            try:
                self._processing_queue.put_nowait(data)
            except queue.Full:
                self._queue_drop_count += 1
                if self._queue_drop_count % 100 == 0:
                    logger.debug("Audio processing queue full; dropped %d chunks", self._queue_drop_count)

        try:
            # Prefer an explicit input device if none is provided.
            if self.device is None:
                try:
                    default_input = sd.default.device[0]
                    # If default is invalid, use our fallback selected_input
                    if default_input is None or default_input < 0:
                        logger.debug(f"Default input device is undefined (-1); using fallback: {selected_input}")
                        default_input = selected_input
                    
                    # Double-check compatibility
                    if default_input is not None and default_input >= 0:
                        try:
                            info = sd.query_devices(default_input)
                            if info.get("max_input_channels", 0) <= 0:
                                logger.debug(f"Device {default_input} has no inputs; using fallback: {selected_input}")
                                default_input = selected_input
                        except Exception:
                            default_input = selected_input
                        
                        self.device = default_input
                        try:
                            # Update portaudio default to avoid future "Invalid device" errors
                            sd.default.device = (default_input, sd.default.device[1])
                        except Exception:
                            pass
                except Exception as e:
                    logger.debug(f"Failed to select default input device: {e}")

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
            
            # --- Windows Intelligence: Fallback Sample Rates ---
            # If 16000 fails (common on some Windows drivers/exclusive modes), try standard rates.
            fallback_rates = [16000, 44100, 48000, 22050]
            if self.sample_rate not in fallback_rates:
                fallback_rates.insert(0, self.sample_rate)
            
            input_device_indices = []
            for idx, d in enumerate(devices):
                if d.get("max_input_channels", 0) > 0:
                    input_device_indices.append(idx)

            def try_open(params_to_use):
                with sd.InputStream(**params_to_use):
                    logger.info(f"Sounddevice InputStream opened successfully (blocksize=4096)")
                    while self._running:
                        sd.sleep(100)

            candidates = []
            if self.device is not None:
                candidates.append(self.device)
            if selected_input is not None and selected_input not in candidates:
                candidates.append(selected_input)
            for idx in input_device_indices:
                if idx not in candidates:
                    candidates.append(idx)

            # Filter candidates by compatibility before trying to open
            valid_candidates = []
            for candidate in candidates:
                try:
                    sd.check_input_settings(
                        device=candidate,
                        samplerate=self.sample_rate,
                        channels=self.channels,
                    )
                    valid_candidates.append(candidate)
                except Exception:
                    continue

            last_error = None
            for candidate in valid_candidates:
                for rate in fallback_rates:
                    try:
                        params["device"] = candidate
                        params["samplerate"] = rate
                        try_open(params)
                        # If successful, update internal state
                        self.sample_rate = rate
                        return
                    except Exception as e:
                        last_error = e
                        if "Invalid device" in str(e) or "-9996" in str(e) or "Invalid sample rate" in str(e):
                            logger.debug(f"Sounddevice try failed (dev={candidate}, rate={rate}): {e}")
                            continue
                        else:
                            logger.warning(f"Sounddevice unexpected error: {e}")
                            break

            if not valid_candidates:
                logger.info("No compatible microphone device found; audio capture disabled")
                self._running = False
                try:
                    from chintu_backend.core.state import get_state_manager
                    sm = get_state_manager()
                    sm.update_feature("audio", enabled=False, status="inactive", error="No compatible microphone device")
                    sm.update_feature("microphone", enabled=False, status="inactive", error="No compatible microphone device")
                except Exception:
                    pass
                return

            # Final retry without explicit device
            try:
                params.pop("device", None)
                try_open(params)
                return
            except Exception as e:
                last_error = e
                raise last_error
        except Exception as e:
            logger.warning(f"Sounddevice error: {e}")
            self._running = False
            try:
                from chintu_backend.core.state import get_state_manager
                sm = get_state_manager()
                sm.update_feature("audio", enabled=False, status="inactive", error=str(e))
                sm.update_feature("microphone", enabled=False, status="inactive", error=str(e))
            except Exception:
                pass
            try:
                from chintu_backend.core.error_reporter import report_error, ErrorSeverity
                report_error(
                    Exception(str(e)),
                    severity=ErrorSeverity.WARNING,
                    component="audio",
                    user_message="Microphone is not available. Voice input is disabled.",
                )
            except Exception:
                pass
            if HAS_PYAUDIO:
                try:
                    logger.warning("Sounddevice failed; falling back to pyaudio")
                    self._backend = "pyaudio"
                    if not hasattr(self, "_pa"):
                        self._pa = pyaudio.PyAudio()
                    self._running = True
                    self._capture_pyaudio()
                except Exception as pyaudio_err:
                    logger.warning(f"Pyaudio fallback failed: {pyaudio_err}")
    
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
                try:
                    self._audio_queue.put_nowait(audio_data)
                except queue.Full:
                    pass
                try:
                    self._processing_queue.put_nowait(audio_data)
                except queue.Full:
                    self._queue_drop_count += 1
                    if self._queue_drop_count % 100 == 0:
                        logger.debug("Audio processing queue full; dropped %d chunks", self._queue_drop_count)
            
            stream.stop_stream()
            stream.close()
        except Exception as e:
            logger.warning(f"Error in pyaudio capture: {e}")
            self._running = False
            # Update feature status to reflect audio capture failure
            try:
                from chintu_backend.core.state import get_state_manager
                sm = get_state_manager()
                sm.update_feature("audio", enabled=False, status="inactive", error=str(e))
                sm.update_feature("microphone", enabled=False, status="inactive", error=str(e))
            except Exception:
                pass
            try:
                from chintu_backend.core.error_reporter import report_error, ErrorSeverity
                report_error(
                    Exception(str(e)),
                    severity=ErrorSeverity.WARNING,
                    component="audio",
                    user_message="Microphone is not available. Voice input is disabled.",
                )
            except Exception:
                pass
    
    def _process_audio(self, audio_data: np.ndarray):
        """Process captured audio data."""
        # Calculate audio level (RMS)
        rms = np.sqrt(np.mean(audio_data ** 2))
        level = min(1.0, rms * 10)  # Scale for visibility
        
        if self._level_callback:
            self._level_callback(level)

        # Update barge-in detector
        if self.barge_in_detector:
            self.barge_in_detector.process(level)

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
