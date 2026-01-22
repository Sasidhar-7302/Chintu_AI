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
        
        self._temp_dir = Path(tempfile.gettempdir()) / "chintu_tts"
        self._temp_dir.mkdir(exist_ok=True)
        
        self._init_engine()
    
    def _init_engine(self):
        """Initialize the best available TTS engine."""
        # Prefer edge-tts for natural voices
        if HAS_EDGE_TTS and HAS_PYGAME:
            try:
                # Test connectivity/initialization if possible, or just assume it works.
                # Use a flag to indicate preference, but don't strictly bind yet.
                self._use_edge_tts = True
                self._available = True
                logger.info(f"TTS initialized with edge-tts (voice: {self.VOICE})")
                return
            except Exception as e:
                logger.warning(f"edge-tts init failed: {e}")
                self._use_edge_tts = False
        
        # Fallback to pyttsx3
        if HAS_PYTTSX3:
            try:
                self._pyttsx_engine = pyttsx3.init()
                voices = self._pyttsx_engine.getProperty('voices')
                # Try to find a male voice
                for voice in voices or []:
                    if 'david' in voice.name.lower():
                        self._pyttsx_engine.setProperty('voice', voice.id)
                        break
                self._pyttsx_engine.setProperty('rate', 180)
                self._available = True
                logger.info("TTS initialized with pyttsx3 (fallback)")
            except Exception as e:
                logger.warning(f"pyttsx3 init failed: {e}")
    
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
    ):
        self._on_start = on_start
        self._on_done = on_done
    
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
        """Speak text synchronously."""
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
            
            print(f"[Chintu]: {text}")
            
            if self._use_edge_tts:
                # Use edge-tts for natural voice - unique filename with timestamp
                import time
                unique_id = f"{int(time.time() * 1000)}_{hash(text) % 10000}"
                audio_file = self._temp_dir / f"tts_{unique_id}.mp3"
                asyncio.run(self._speak_edge_tts(text, audio_file))
                
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
                            pygame.time.wait(50)
                    finally:
                        # Unload music before deleting to release file lock
                        try:
                            pygame.mixer.music.unload()
                        except:
                            pass
                        try:
                            audio_file.unlink()
                        except:
                            pass  # File may still be locked, ignore
            else:
                # Fallback to pyttsx3
                if self._pyttsx_engine:
                    if not self._stop_signal.is_set():
                        self._pyttsx_engine.say(text)
                        self._pyttsx_engine.runAndWait()
            
        except Exception as e:
            logger.warning(f"TTS error: {e}")
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
