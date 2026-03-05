"""
Process-based Wake Word Detector for hard priority scheduling.

This module runs wake word detection in a separate process to ensure
it always has CPU priority, even when TTS or LLM is running.

Based on ChatGPT recommendation:
- Wake word must run in a SEPARATE PROCESS (not thread)
- Pinned to 1 CPU core
- Does NOT share audio buffer with TTS playback
- Immediately emits INTERRUPT_EVENT on detection
"""

import multiprocessing as mp
import queue
import time
import logging
import os
import numpy as np
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class WakeWordProcessWorker:
    """
    Runs wake word detection in a separate high-priority process.
    
    This ensures wake word detection is never blocked by:
    - TTS audio playback
    - LLM inference
    - STT processing
    - Python GIL contention
    """
    
    def __init__(
        self,
        wake_word: str = "hey chintu",
        sensitivity: float = 0.6,
        sample_rate: int = 16000,
        model_path: Optional[str] = None,
        base_model: str = "hey_jarvis",
    ):
        self.wake_word = wake_word
        self.sensitivity = sensitivity
        self.sample_rate = sample_rate
        self.model_path = model_path
        self.base_model = base_model
        
        # Inter-process communication
        self._audio_queue: Optional[mp.Queue] = None
        self._event_queue: Optional[mp.Queue] = None
        self._process: Optional[mp.Process] = None
        self._running = mp.Event()
        self._callback: Optional[Callable[[], None]] = None
        
        # Listener thread for event queue
        self._listener_thread = None
        
    def set_wake_callback(self, callback: Callable[[], None]):
        """Set callback to be called when wake word is detected."""
        self._callback = callback
        
    def start(self):
        """Start the wake word detection process."""
        if self._process and self._process.is_alive():
            logger.warning("Wake word process already running")
            return
            
        # Create queues
        self._audio_queue = mp.Queue(maxsize=100)  # Audio chunks from main process
        self._event_queue = mp.Queue(maxsize=10)    # Events back to main process
        self._running.set()
        
        # Start worker process
        self._process = mp.Process(
            target=_wake_word_worker,
            args=(
                self._audio_queue,
                self._event_queue,
                self._running,
                self.wake_word,
                self.sensitivity,
                self.sample_rate,
                self.model_path,
                self.base_model,
            ),
            daemon=True,
            name="WakeWordProcess"
        )
        self._process.start()
        
        # Set process priority to high (Windows)
        try:
            import psutil
            p = psutil.Process(self._process.pid)
            p.nice(psutil.HIGH_PRIORITY_CLASS)  # Windows high priority
            # Pin to first CPU core
            p.cpu_affinity([0])
            logger.info(f"Wake word process started (PID: {self._process.pid}, priority: HIGH, core: 0)")
        except Exception as e:
            logger.warning(f"Could not set process priority: {e}")
            logger.info(f"Wake word process started (PID: {self._process.pid})")
        
        # Start event listener thread
        import threading
        self._listener_thread = threading.Thread(target=self._event_listener, daemon=True)
        self._listener_thread.start()
        
    def stop(self):
        """Stop the wake word detection process."""
        self._running.clear()
        
        if self._process:
            self._process.join(timeout=2.0)
            if self._process.is_alive():
                self._process.terminate()
            self._process = None
            
        logger.info("Wake word process stopped")
        
    def process_audio(self, audio_chunk: np.ndarray):
        """Send audio chunk to the wake word process."""
        if not self._running.is_set() or not self._audio_queue:
            return
            
        try:
            # Non-blocking put - drop audio if queue is full
            self._audio_queue.put_nowait(audio_chunk.tobytes())
        except queue.Full:
            pass  # Drop frame rather than block
            
    def _event_listener(self):
        """Listen for events from the wake word process."""
        while self._running.is_set():
            try:
                event = self._event_queue.get(timeout=0.1)
                if event == "WAKE_DETECTED":
                    logger.info("Wake word detected by process worker")
                    if self._callback:
                        self._callback()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Event listener error: {e}")
                break
                
    @property
    def is_running(self) -> bool:
        """Check if the process is running."""
        return self._process is not None and self._process.is_alive()


def _wake_word_worker(
    audio_queue: mp.Queue,
    event_queue: mp.Queue,
    running: mp.Event,
    wake_word: str,
    sensitivity: float,
    sample_rate: int,
    model_path: Optional[str],
    base_model: str,
):
    """
    Worker function that runs in a separate process.
    This is the entry point for the wake word detection process.
    """
    import numpy as np
    import time
    import logging

    worker_logger = logging.getLogger("chintu_backend.audio.wake_word_process.worker")
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    # Import openWakeWord in the subprocess
    try:
        from openwakeword.model import Model as OWWModel
        HAS_OWW = True
    except ImportError:
        HAS_OWW = False
        
    # Initialize openWakeWord model
    oww_model = None
    model_key = None
    
    if HAS_OWW:
        try:
            # Standard model paths
            if model_path and os.path.exists(model_path):
                oww_model = OWWModel(wakeword_models=[model_path])
                model_key = os.path.basename(model_path).replace(".onnx", "")
            else:
                # Use base model
                oww_model = OWWModel(wakeword_models=[base_model])
                model_key = base_model
                
            worker_logger.info("Wake-word worker initialized with model: %s", model_key)
        except Exception as e:
            worker_logger.warning("Wake-word worker failed to initialize openWakeWord: %s", e)
            HAS_OWW = False
    
    if not HAS_OWW:
        worker_logger.info("openWakeWord unavailable; using energy-based fallback detection")
    
    # Detection state
    consecutive_frames = 0
    activation_frames = 3
    cooldown_until = 0.0
    cooldown_seconds = 1.5
    
    while running.is_set():
        try:
            # Get audio from queue with timeout
            audio_bytes = audio_queue.get(timeout=0.1)
            audio = np.frombuffer(audio_bytes, dtype=np.float32)
            
            now = time.time()
            
            # Cooldown check
            if now < cooldown_until:
                continue
                
            detected = False
            
            if HAS_OWW and oww_model:
                # Run openWakeWord inference
                oww_model.predict(audio)
                scores = oww_model.get_positive_scores()
                
                for name, score in scores.items():
                    if score >= sensitivity:
                        consecutive_frames += 1
                        if consecutive_frames >= activation_frames:
                            detected = True
                            consecutive_frames = 0
                        break
                else:
                    # Decay on no detection
                    if consecutive_frames > 0:
                        consecutive_frames -= 1
            else:
                # Simple energy-based detection fallback
                energy = np.sqrt(np.mean(audio ** 2))
                if energy > 0.1:  # High energy might be speech
                    consecutive_frames += 1
                    if consecutive_frames >= 10:  # More frames needed for energy
                        detected = True
                        consecutive_frames = 0
                else:
                    consecutive_frames = max(0, consecutive_frames - 1)
                    
            if detected:
                # Send detection event
                try:
                    event_queue.put_nowait("WAKE_DETECTED")
                    cooldown_until = now + cooldown_seconds
                    worker_logger.info("Wake-word detected")
                except queue.Full:
                    pass
                    
        except queue.Empty:
            continue
        except Exception as e:
            worker_logger.warning("Wake-word worker loop error: %s", e)
            import threading
            threading.Event().wait(0.1)  # Interruptible error recovery wait
            
    worker_logger.info("Wake-word worker shutting down")
