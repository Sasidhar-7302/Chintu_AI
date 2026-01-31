"""
Text-to-Speech module for Chintu AI Assistant.
Uses edge-tts for natural-sounding Microsoft Azure voices.
Personality: Professional-friendly buddy for Sasi.
"""

import threading
import queue
import logging
import asyncio
import tempfile
import os
import random
import time
from typing import Optional, Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# Try edge-tts (natural voices)
try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False
    logger.warning("edge-tts not installed.")

# Try pyttsx3 as fallback
try:
    import pyttsx3
    HAS_PYTTSX3 = True
except ImportError:
    HAS_PYTTSX3 = False

# Try pygame for audio playback
try:
    import pygame
    pygame.mixer.init()
    HAS_PYGAME = True
except:
    HAS_PYGAME = False


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
        
        self._on_start: Optional[Callable[[], None]] = None
        self._on_done: Optional[Callable[[], None]] = None
        # NEW: Callback for live caption display (Google Assistant style)
        self._on_speaking_text: Optional[Callable[[str, bool], None]] = None
        
        self._temp_dir = Path(tempfile.gettempdir()) / "chintu_tts"
        self._temp_dir.mkdir(exist_ok=True)
        
        self._init_engine()
    
    def _init_engine(self):
        """Initialize the best available TTS engine.
        
        Priority: pyttsx3 (local, instant) > edge-tts (cloud, slow but natural)
        Local TTS is preferred for speed - edge-tts takes 10-60 seconds for network.
        """
        # PREFER pyttsx3 for instant local speech (no network latency)
        if HAS_PYTTSX3:
            try:
                self._pyttsx_engine = pyttsx3.init()
                voices = self._pyttsx_engine.getProperty('voices')
                # Try to find a male voice (David on Windows)
                for voice in voices or []:
                    if 'david' in voice.name.lower():
                        self._pyttsx_engine.setProperty('voice', voice.id)
                        break
                self._pyttsx_engine.setProperty('rate', 180)  # Slightly faster
                self._use_edge_tts = False
                self._available = True
                logger.info("TTS initialized with pyttsx3 (local, instant)")
                return
            except Exception as e:
                logger.warning(f"pyttsx3 init failed: {e}")
        
        # Fallback to edge-tts (cloud-based, higher quality but slow)
        if HAS_EDGE_TTS and HAS_PYGAME:
            try:
                self._use_edge_tts = True
                self._available = True
                logger.info(f"TTS initialized with edge-tts (cloud, high-quality voice: {self.VOICE})")
                return
            except Exception as e:
                logger.warning(f"edge-tts init failed: {e}")
                self._use_edge_tts = False
    
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
    
    def speak(self, text: str, priority: bool = False):
        """Queue text to be spoken."""
        if not self._available or not text:
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
        
        self._speech_queue.put(text)
        logger.debug(f"Queued speech: {text[:50]}...")
    
    async def _speak_edge_tts(self, text: str, output_path: Path):
        """Generate audio using edge-tts."""
        communicate = edge_tts.Communicate(
            text,
            voice=self.VOICE,
            rate=self._rate,
            volume=self._volume,
        )
        await communicate.save(str(output_path))
    
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
                        logger.warning(f"Edge-TTS failed ({edge_err}). Falling back to local TTS.")
                        # Fallback to pyttsx3 for this sentence
                        if HAS_PYTTSX3 and self._pyttsx_engine:
                            logger.info(f"Speaking (Local Fallback): '{sentence}'")
                            self._pyttsx_engine.say(sentence)
                            self._pyttsx_engine.runAndWait()
                        else:
                            logger.error("Local TTS (pyttsx3) not available for fallback.")

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
