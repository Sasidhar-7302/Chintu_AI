"""
Text-to-Speech module for Chintu AI Assistant.
Uses edge-tts for natural-sounding Microsoft Azure voices.
Personality: Professional-friendly buddy for Sasi.
"""

import threading
import queue
import logging
import asyncio
import atexit
import tempfile
import os
import random
import time
import sys
import re
from typing import Optional, Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# Fast init path for tests to avoid slow COM initialization.
def _fast_tts_init_enabled() -> bool:
    return bool(
        os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("CHINTU_TTS_FAST_INIT")
        or "pytest" in sys.modules
        or any("pytest" in arg for arg in sys.argv)
        or os.environ.get("CHINTU_TTS_AUTO_SPEAK", "").strip().lower() in ("false", "0", "no")
        or any(key.startswith("PYTEST") for key in os.environ)
    )

# Optional deps are loaded lazily inside _init_engine.
edge_tts = None
pyttsx3 = None
pygame = None
HAS_EDGE_TTS = False
HAS_PYTTSX3 = False
HAS_PYGAME = False
_INTERPRETER_SHUTTING_DOWN = False


def _mark_interpreter_shutdown() -> None:
    global _INTERPRETER_SHUTTING_DOWN
    _INTERPRETER_SHUTTING_DOWN = True


atexit.register(_mark_interpreter_shutdown)


# Professional-friendly phrases (warm but not slang)
GREETINGS = [
    "Hey Sasi, what can I help you with?",
    "Hi Sasi! Ready when you are.",
    "Hello Sasi, how can I assist you today?",
]

LISTENING_PHRASES = [
    "I'm listening.",
    "Go ahead.",
    "Yes, I'm here.",
]

PROCESSING_PHRASES = [
    "Let me check that for you.",
    "One moment please.",
    "Working on it.",
]

DONE_PHRASES = [
    "Done.",
    "All set.",
    "There you go.",
]

ERROR_PHRASES = [
    "Sorry, that didn't work.",
    "I ran into an issue.",
    "Something went wrong, let me try again.",
]

_SPEECH_URL_RE = re.compile(r"https?://\S+|www\.\S+", flags=re.IGNORECASE)
_SPEECH_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)", flags=re.IGNORECASE)
_SPEECH_CITATION_RE = re.compile(r"\[(?:\s*source\s*)?\d+\]", flags=re.IGNORECASE)
_SPEECH_SOURCE_LABEL_RE = re.compile(r"\b(?:sources?|citations?)\s*:\s*", flags=re.IGNORECASE)
_SPEECH_DECOR_RE = re.compile(r"(?:={3,}|_{3,}|~{3,})")
_SPEECH_ESCAPED_RE = re.compile(r"(?:\\[nrt])+")


def _fallback_sanitize_for_speech(text: str, preserve_links: bool = False) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    raw = _SPEECH_MD_LINK_RE.sub(r"\1", raw)
    raw = _SPEECH_ESCAPED_RE.sub(" ", raw)
    raw = _SPEECH_DECOR_RE.sub(" ", raw)
    if not preserve_links:
        raw = _SPEECH_SOURCE_LABEL_RE.sub("", raw)
        raw = _SPEECH_CITATION_RE.sub("", raw)
        raw = _SPEECH_URL_RE.sub("", raw)
        raw = re.sub(r"\bsource\b", "", raw, flags=re.IGNORECASE)
    raw = raw.replace("`", " ")
    raw = raw.replace("\\", " ")
    raw = raw.replace("*", " ")
    raw = re.sub(r"\s+", " ", raw).strip(" -|")
    return raw


def _sanitize_for_speech(text: str, preserve_links: bool = False) -> str:
    try:
        from ..core.command_handler import sanitize_for_tts

        cleaned = sanitize_for_tts(text, preserve_links=preserve_links)
        if cleaned:
            return cleaned
    except Exception:
        pass
    return _fallback_sanitize_for_speech(text, preserve_links=preserve_links)


def _is_runtime_shutdown_error(exc: Exception | str) -> bool:
    msg = str(exc or "").lower()
    shutdown_tokens = (
        "cannot schedule new futures after interpreter shutdown",
        "cannot create new thread at interpreter shutdown",
        "interpreter shutdown",
        "event loop is closed",
        "cannot be called from a running event loop",
    )
    return any(token in msg for token in shutdown_tokens)


class TextToSpeech:
    """
    Text-to-Speech with natural Azure voices via edge-tts.
    Falls back to pyttsx3 if edge-tts unavailable.
    """
    
    # Natural male voice - Christopher is clear and natural
    VOICE = "en-US-ChristopherNeural"  # Natural, clear male voice
    
    def __init__(
        self,
        rate: str = "+10%",       # Slightly faster for natural flow
        volume: str = "+0%",
        user_name: str = "Sasi",
    ):
        self._rate = rate
        self._volume = volume
        self._user_name = user_name
        
        self._available = False
        self._speaking = False
        self._speech_queue: queue.Queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._use_edge_tts = False
        self._pyttsx_engine = None
        self._stop_signal = threading.Event()
        self._local_fallback_unavailable_logged = False
        self._edge_unavailable_logged = False
        
        self._on_start: Optional[Callable[[], None]] = None
        self._on_done: Optional[Callable[[], None]] = None
        # NEW: Callback for live caption display (Google Assistant style)
        self._on_speaking_text: Optional[Callable[[str, bool], None]] = None
        
        self._temp_dir = Path(tempfile.gettempdir()) / "chintu_tts"
        self._temp_dir.mkdir(exist_ok=True)
        
        self._init_engine()
    
    def _init_engine(self):
        """Initialize the best available TTS engine.
        
        Engine order depends on `tts_engine_mode`:
        - quality: edge-tts first (natural), then pyttsx3 fallback
        - balanced: edge-tts first, then pyttsx3 fallback
        - speed: pyttsx3 first, then edge-tts fallback
        """
        if _fast_tts_init_enabled():
            # Lightweight test mode: mark available without heavy COM init.
            self._use_edge_tts = False
            self._available = True
            logger.info("TTS fast-init enabled (tests)")
            return

        global pyttsx3, edge_tts, pygame, HAS_PYTTSX3, HAS_EDGE_TTS, HAS_PYGAME
        mode = "quality"
        try:
            from ..core.config import get_config

            configured_mode = str(getattr(get_config(), "tts_engine_mode", "quality") or "quality").strip().lower()
            if configured_mode in {"quality", "balanced", "speed"}:
                mode = configured_mode
        except Exception:
            mode = "quality"

        def _try_pyttsx() -> bool:
            global pyttsx3, HAS_PYTTSX3
            if not HAS_PYTTSX3:
                try:
                    import pyttsx3 as _pyttsx3

                    pyttsx3 = _pyttsx3
                    HAS_PYTTSX3 = True
                except ImportError:
                    HAS_PYTTSX3 = False
            if not HAS_PYTTSX3:
                return False
            try:
                self._pyttsx_engine = pyttsx3.init()
                voices = self._pyttsx_engine.getProperty("voices")
                # Try to find a clearer male voice on Windows.
                for voice in voices or []:
                    if "david" in voice.name.lower():
                        self._pyttsx_engine.setProperty("voice", voice.id)
                        break
                self._pyttsx_engine.setProperty("rate", 176)
                self._use_edge_tts = False
                self._available = True
                logger.info("TTS initialized with pyttsx3 (local).")
                return True
            except Exception as exc:
                logger.warning(f"pyttsx3 init failed: {exc}")
                return False

        def _try_edge() -> bool:
            global edge_tts, pygame, HAS_EDGE_TTS, HAS_PYGAME
            if not HAS_EDGE_TTS:
                try:
                    import edge_tts as _edge_tts

                    edge_tts = _edge_tts
                    HAS_EDGE_TTS = True
                except ImportError:
                    HAS_EDGE_TTS = False
            if not HAS_PYGAME:
                try:
                    import pygame as _pygame

                    _pygame.mixer.init()
                    pygame = _pygame
                    HAS_PYGAME = True
                except Exception as exc:
                    HAS_PYGAME = False
                    logger.debug(f"pygame mixer init failed: {exc}")
            if not (HAS_EDGE_TTS and HAS_PYGAME):
                return False
            try:
                self._use_edge_tts = True
                self._available = True
                logger.info(f"TTS initialized with edge-tts (natural voice: {self.VOICE}).")
                return True
            except Exception as exc:
                logger.warning(f"edge-tts init failed: {exc}")
                self._use_edge_tts = False
                return False

        # Engine selection policy.
        if mode == "speed":
            if _try_pyttsx():
                return
            if _try_edge():
                return
        else:
            if _try_edge():
                return
            if _try_pyttsx():
                return
        
        # Final check: if neither engine worked or no output hardware
        if not self.check_output_available():
            logger.warning("No audio output hardware detected. TTS will be disabled.")
            self._available = False

    def _ensure_local_fallback_engine(self) -> bool:
        """Best-effort lazy init of local fallback engine."""
        if self._pyttsx_engine:
            return True

        global pyttsx3, HAS_PYTTSX3
        if not HAS_PYTTSX3:
            try:
                import pyttsx3 as _pyttsx3

                pyttsx3 = _pyttsx3
                HAS_PYTTSX3 = True
            except Exception:
                HAS_PYTTSX3 = False
                return False
        try:
            self._pyttsx_engine = pyttsx3.init()
            voices = self._pyttsx_engine.getProperty("voices")
            for voice in voices or []:
                if "david" in str(getattr(voice, "name", "")).lower():
                    self._pyttsx_engine.setProperty("voice", voice.id)
                    break
            self._pyttsx_engine.setProperty("rate", 176)
            return True
        except Exception:
            return False
    
    def check_output_available(self) -> bool:
        """Check if any speaker hardware is actually available."""
        # Try sounddevice if available (most reliable for query)
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            has_output = any(d.get("max_output_channels", 0) > 0 for d in devices)
            return has_output
        except Exception:
            pass
            
        # Fallback to checking pyttsx/pygame status
        if self._pyttsx_engine:
            return True
        if HAS_PYGAME and pygame.mixer.get_init():
            return True
            
        return False
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    @property
    def is_speaking(self) -> bool:
        return self._speaking
    
    def set_callbacks(
        self,
        on_start: Optional[Callable[[], None]] = None,
        on_done: Optional[Callable[[], None]] = None,
        on_speaking_text: Optional[Callable[[str, bool], None]] = None,
    ):
        """Set TTS callbacks.
        
        Args:
            on_start: Called when speech starts
            on_done: Called when speech completes
            on_speaking_text: Called with (text, is_complete) during speech
                              for Google-Assistant-style live captions
        """
        self._on_start = on_start
        self._on_done = on_done
        self._on_speaking_text = on_speaking_text
    
    def start(self):
        if not self._available:
            return
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        logger.info("TTS worker started")
    
    def stop(self):
        self._running = False
        self._speech_queue.put(None)
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)
        logger.info("TTS stopped")

    def wait_until_done(self, timeout: Optional[float] = None) -> bool:
        """
        Block until the current speech queue is finished.
        Returns True if completed before timeout, False otherwise.
        """
        if not self._available:
            return True

        deadline = None
        if timeout is not None:
            try:
                deadline = time.monotonic() + float(timeout)
            except Exception:
                deadline = None

        while True:
            if not self._speaking and self._speech_queue.empty():
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def stop_speaking(self):
        """Stop current speech and clear queued messages."""
        if not self._available:
            return
        
        # CRITICAL FIX: Reset speaking flag immediately
        was_speaking = self._speaking
        self._speaking = False
        
        # Set stop signal to interrupt current playback
        self._stop_signal.set()
        
        # Clear queued messages
        while not self._speech_queue.empty():
            try:
                self._speech_queue.get_nowait()
            except queue.Empty:
                break
        
        # Stop audio playback
        if HAS_PYGAME:
            try:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()  # Release file lock
            except Exception:
                pass
        
        if self._pyttsx_engine:
            try:
                self._pyttsx_engine.stop()
            except Exception:
                pass
        
        # Call on_done callback if was speaking
        if was_speaking and self._on_done:
            try:
                self._on_done()
            except Exception as e:
                logger.warning(f"Error in on_done callback: {e}")
        
        if was_speaking:
            logger.info("TTS stopped (barge-in)")
    
    def speak(
        self,
        text: str,
        priority: bool = False,
        sanitize: bool = True,
        preserve_links: bool = False,
    ):
        """Queue text to be spoken."""
        if not self._available or not text:
            return

        queued_text = str(text or "")
        if sanitize:
            queued_text = _sanitize_for_speech(queued_text, preserve_links=preserve_links)
        queued_text = str(queued_text or "").strip()
        if not queued_text:
            return
        
        # CRITICAL FIX: Clear stop signal before queuing new speech
        # This ensures previous barge-in doesn't block new speech
        self._stop_signal.clear()
        
        if priority:
            while not self._speech_queue.empty():
                try:
                    self._speech_queue.get_nowait()
                except queue.Empty:
                    break
        
        self._speech_queue.put(queued_text)
        logger.debug(f"Queued speech: {queued_text[:50]}...")
    
    async def _speak_edge_tts(self, text: str, output_path: Path):
        """Generate audio using edge-tts."""
        communicate = edge_tts.Communicate(
            text,
            voice=self.VOICE,
            rate=self._rate,
            volume=self._volume,
        )
        await communicate.save(str(output_path))

    def synthesize_to_file(self, text: str, output_path: Path) -> bool:
        """Generate an audio file without playing it."""
        if not self._available or not text:
            return False
        try:
            if self._use_edge_tts and HAS_EDGE_TTS:
                asyncio.run(self._speak_edge_tts(text, output_path))
                return output_path.exists()
        except Exception:
            return False
        return False
    
    def speak_sync(self, text: str):
        """Speak text synchronously with progressive display.
        
        Text is split into sentences and each sentence is displayed
        AS it's being spoken for a synchronized reading experience.
        """
        if not self._available or not text:
            return
        
        try:
            # CRITICAL FIX: Check stop signal before starting
            if self._stop_signal.is_set():
                logger.debug("TTS skipped - stop signal already set")
                return
            if _INTERPRETER_SHUTTING_DOWN:
                logger.debug("TTS skipped - interpreter shutdown in progress")
                return
            
            self._stop_signal.clear()
            self._speaking = True
            if self._on_start:
                self._on_start()
            
            # Print header
            print("[Chintu]: ", end="", flush=True)

            if not self._use_edge_tts and HAS_PYTTSX3 and self._pyttsx_engine:
                # Local TTS: speak full text in one call for reliability.
                if not self._stop_signal.is_set():
                    print(text.strip(), end="", flush=True)
                    # NEW: Broadcast live caption for UI
                    if self._on_speaking_text:
                        try:
                            self._on_speaking_text(text.strip(), True)  # full text, complete
                        except Exception as cb_err:
                            logger.warning(f"on_speaking_text callback error: {cb_err}")
                    logger.info(f"Speaking (Local): '{text.strip()[:120]}'")
                    self._pyttsx_engine.say(text.strip())
                    self._pyttsx_engine.runAndWait()
                print(flush=True)
                return

            # Edge-TTS path: split text into sentences for progressive display
            import re
            sentences = re.split(r'(?<=[.!?])\s+', text.strip())
            sentences = [s.strip() for s in sentences if s.strip()]

            for i, sentence in enumerate(sentences):
                # Check for stop signal before each sentence
                if self._stop_signal.is_set():
                    print()  # Newline after partial output
                    logger.debug("TTS interrupted between sentences")
                    break

                # Print sentence AS we speak it (progressive display)
                if i > 0:
                    print(" ", end="", flush=True)  # Space between sentences
                print(sentence, end="", flush=True)

                # NEW: Broadcast live caption for UI (progressive)
                is_last_sentence = (i == len(sentences) - 1)
                if self._on_speaking_text:
                    try:
                        # Build cumulative text for smooth display
                        spoken_so_far = " ".join(sentences[:i+1])
                        self._on_speaking_text(spoken_so_far, is_last_sentence)
                    except Exception as cb_err:
                        logger.warning(f"on_speaking_text callback error: {cb_err}")

                # Speak this sentence
                if self._use_edge_tts:
                    try:
                        if _INTERPRETER_SHUTTING_DOWN:
                            logger.debug("Skipping Edge-TTS sentence - interpreter shutdown in progress")
                            break
                        import time
                        unique_id = f"{int(time.time() * 1000)}_{hash(sentence) % 10000}"
                        audio_file = self._temp_dir / f"tts_{unique_id}.mp3"
                        # Log what we are about to say through Edge-TTS
                        logger.info(f"Speaking (Cloud): '{sentence}'")
                        asyncio.run(self._speak_edge_tts(sentence, audio_file))

                        if audio_file.exists() and HAS_PYGAME:
                            try:
                                pygame.mixer.music.load(str(audio_file))
                                pygame.mixer.music.play()
                                while pygame.mixer.music.get_busy():
                                    if self._stop_signal.is_set():
                                        pygame.mixer.music.stop()
                                        pygame.mixer.music.unload()
                                        logger.debug("TTS playback interrupted by stop signal")
                                        break
                                    pygame.time.wait(20)
                            finally:
                                try:
                                    pygame.mixer.music.unload()
                                except:
                                    pass
                                try:
                                    audio_file.unlink()
                                except:
                                    pass
                    except Exception as edge_err:
                        if _is_runtime_shutdown_error(edge_err):
                            if not self._edge_unavailable_logged:
                                logger.warning(
                                    "Edge-TTS skipped during shutdown (%s).",
                                    edge_err,
                                )
                                self._edge_unavailable_logged = True
                            break
                        logger.warning(f"Edge-TTS failed ({edge_err}). Falling back to local TTS.")
                        # Fallback to pyttsx3 for this sentence
                        if self._ensure_local_fallback_engine():
                            logger.info(f"Speaking (Local Fallback): '{sentence}'")
                            self._pyttsx_engine.say(sentence)
                            self._pyttsx_engine.runAndWait()
                        else:
                            if not self._local_fallback_unavailable_logged:
                                logger.warning("Local TTS fallback is unavailable; skipping spoken audio for this segment.")
                                self._local_fallback_unavailable_logged = True

            # Print final newline
            print(flush=True)
            
        except Exception as e:
            logger.warning(f"TTS error: {e}")
            print()  # Ensure newline on error
        finally:
            # CRITICAL FIX: Only reset if we were actually speaking
            was_speaking = self._speaking
            self._speaking = False
            if was_speaking and self._on_done:
                self._on_done()
    
    def _worker_loop(self):
        while self._running:
            try:
                text = self._speech_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if text is None:
                break
            self.speak_sync(text)
    
    def say_greeting(self):
        """Speak a professional-friendly greeting."""
        self.speak(random.choice(GREETINGS))
    
    def say_listening(self):
        """Announce listening state."""
        self.speak(random.choice(LISTENING_PHRASES), priority=True)
    
    def say_processing(self):
        """Announce processing state."""
        self.speak(random.choice(PROCESSING_PHRASES), priority=True)
    
    def say_done(self):
        """Announce task completion."""
        self.speak(random.choice(DONE_PHRASES))
    
    def say_error(self, error: str = ""):
        """Announce an error."""
        phrase = random.choice(ERROR_PHRASES)
        if error:
            phrase += f" {error}"
        self.speak(phrase)


# Global TTS instance
_tts: Optional[TextToSpeech] = None


def get_tts() -> TextToSpeech:
    """Get or create the global TTS instance."""
    global _tts
    if _tts is None:
        _tts = TextToSpeech()
    return _tts
