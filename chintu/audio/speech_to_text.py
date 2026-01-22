"""Speech-to-Text using Whisper."""

import numpy as np
import threading
import time
from typing import Optional, Callable, Tuple
from collections import deque
import logging
import re

logger = logging.getLogger(__name__)

# Try to import faster-whisper
try:
    from faster_whisper import WhisperModel
    HAS_FASTER_WHISPER = True
except ImportError:
    HAS_FASTER_WHISPER = False
    logger.warning("faster-whisper not installed")

# Try regular whisper as fallback
try:
    import whisper
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False


class SpeechToText:
    """
    Speech-to-Text using OpenAI Whisper (via faster-whisper).
    Converts spoken audio to text transcription.
    """
    
    def __init__(
        self,
        model_name: str = "base",
        device: str = "cpu",
        language: str = "en",
        sample_rate: int = 16000,
        silence_threshold: float = 0.01,
        silence_duration: float = 1.5,
        vad_filter: bool = False,
        partial_interval: float = 0.7,
        partial_window_seconds: float = 2.8,
        initial_prompt: Optional[str] = None,
        timeout_seconds: float = 5.0,
        min_listen_seconds: float = 0.0,
        min_confidence: float = 0.0,
        speech_frames_required: int = 3,
        compute_type: Optional[str] = None,
        cpu_threads: int = 0,
        num_workers: int = 1,
        beam_size: int = 1,
        best_of: int = 1,
        partial_beam_size: int = 1,
    ):
        self.model_name = model_name
        self.device = device
        self.language = language
        self.sample_rate = sample_rate
        self._initial_prompt = initial_prompt
        self._compute_type = compute_type
        self._cpu_threads = max(0, int(cpu_threads))
        self._num_workers = max(1, int(num_workers))
        self._beam_size = max(1, int(beam_size))
        self._best_of = max(1, int(best_of))
        self._partial_beam_size = max(1, int(partial_beam_size))
        
        self._model = None
        self._on_transcript: Optional[Callable[[str, bool], None]] = None
        self._on_partial: Optional[Callable[[str], None]] = None
        self._audio_buffer = deque()
        self._is_listening = False
        self._buffered_samples = 0
        self._silence_start: Optional[float] = None
        self._silence_threshold = silence_threshold
        self._silence_duration = silence_duration  # seconds of silence to end
        self._vad_filter = vad_filter
        self._partial_interval = partial_interval
        self._partial_window_samples = int(sample_rate * partial_window_seconds)
        self._partial_last_time = 0.0
        self._partial_in_flight = False
        self._last_partial_text = ""
        self._transcribe_in_flight = False
        self._timeout_seconds = max(0.0, float(timeout_seconds))
        self._min_listen_seconds = max(0.0, float(min_listen_seconds))
        self._min_confidence = max(0.0, float(min_confidence))
        self._last_confidence = 0.0
        self._listening_start: Optional[float] = None
        self._speech_detected = False
        self._speech_frames_required = max(1, int(speech_frames_required))
        self._speech_frames = 0
        
        self._load_model()
    
    def _load_model(self):
        """Load the Whisper model."""
        if HAS_FASTER_WHISPER:
            try:
                compute_type = self._compute_type
                if not compute_type:
                    compute_type = "int8" if self.device == "cpu" else "float16"
                self._model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=compute_type,
                    cpu_threads=self._cpu_threads,
                    num_workers=self._num_workers,
                )
                self._backend = "faster-whisper"
                logger.info(
                    "Loaded faster-whisper model: %s (compute_type=%s, cpu_threads=%s)",
                    self.model_name,
                    compute_type,
                    self._cpu_threads or "default",
                )
                return
            except Exception as e:
                logger.warning(f"Failed to load faster-whisper: {e}")
        
        if HAS_WHISPER:
            try:
                self._model = whisper.load_model(self.model_name, device=self.device)
                self._backend = "whisper"
                logger.info(f"Loaded whisper model: {self.model_name}")
                return
            except Exception as e:
                logger.warning(f"Failed to load whisper: {e}")
        
        logger.warning("No STT model available - using simulation mode")
        self._backend = "simulation"
    
    def set_transcript_callback(self, callback: Callable[[str, bool], None]):
        """Set callback for transcription results. Args: (text, is_final)"""
        self._on_transcript = callback

    def set_partial_callback(self, callback: Callable[[str], None]):
        """Set callback for partial transcription results."""
        self._on_partial = callback
    
    def set_timeout(self, timeout_seconds: float):
        """Dynamically change the listening timeout (e.g., for conversation mode)."""
        self._timeout_seconds = timeout_seconds
    
    def start_listening(self):
        """Start collecting audio for transcription."""
        self._is_listening = True
        self._audio_buffer.clear()
        self._buffered_samples = 0
        self._silence_start = None
        self._partial_last_time = 0.0
        self._last_partial_text = ""
        self._listening_start = time.time()
        self._speech_detected = False
        self._speech_frames = 0
        logger.info("Started listening for speech")
    
    def stop_listening(self):
        """Stop listening and transcribe asynchronously."""
        self._is_listening = False
        self._listening_start = None
        
        if not self._audio_buffer:
            return
        
        # Convert buffer to numpy array
        audio = np.concatenate(list(self._audio_buffer))
        self._audio_buffer.clear()
        self._buffered_samples = 0
        
        # Transcribe asynchronously
        self._start_final_transcription(audio)
    
    def process_audio(self, audio_chunk: np.ndarray):
        """Process audio chunk during listening."""
        if not self._is_listening:
            return

        # Note: Timeout is now silence-based (in voice activity detection section below)
        
        self._audio_buffer.append(audio_chunk)
        self._buffered_samples += len(audio_chunk)

        if (
            self._on_partial
            and self._partial_interval > 0
            and self._buffered_samples >= self._partial_window_samples
        ):
            now = time.time()
            if now - self._partial_last_time >= self._partial_interval:
                self._partial_last_time = now
                self._start_partial_transcription()
        
        # Check for silence (voice activity detection)
        rms = np.sqrt(np.mean(audio_chunk ** 2))
        elapsed = 0.0
        if self._listening_start is not None:
            elapsed = time.time() - self._listening_start
        if self._min_listen_seconds > 0 and elapsed < self._min_listen_seconds:
            self._silence_start = None
            return

        if rms < self._silence_threshold:
            if not self._speech_detected:
                self._speech_frames = 0
            if self._silence_start is None:
                self._silence_start = time.time()
            else:
                silence_duration = time.time() - self._silence_start
                if not self._speech_detected:
                    if self._timeout_seconds > 0 and silence_duration >= self._timeout_seconds:
                        logger.info(f"Silence timeout ({self._timeout_seconds}s) - no speech detected")
                        self.stop_listening()
                        return
                else:
                    # Smart pause detection: adjust silence threshold based on sentence completeness
                    effective_silence_duration = self._get_smart_silence_duration(silence_duration)
                    
                    # Check for normal silence duration (end of utterance)
                    if silence_duration > effective_silence_duration:
                        logger.debug("Silence detected, ending utterance")
                        self.stop_listening()
                        return
                    # Optional long-silence timeout (conversation mode)
                    if self._timeout_seconds > 0 and silence_duration >= self._timeout_seconds:
                        logger.info(f"Silence timeout ({self._timeout_seconds}s) - ending utterance")
                        self.stop_listening()
                        return
        else:
            # Speech detected - reset silence timer
            self._speech_frames += 1
            if self._speech_frames >= self._speech_frames_required:
                self._speech_detected = True
            self._silence_start = None
    
    def _get_smart_silence_duration(self, current_silence: float) -> float:
        """
        Smart pause detection: analyze partial transcription to determine
        if the user is finished speaking or just pausing to think.
        
        Returns the effective silence duration threshold to use.
        """
        # Base silence duration from config
        base_duration = self._silence_duration
        
        # Get the last partial transcription
        text = self._last_partial_text.strip().lower() if self._last_partial_text else ""
        
        if not text or len(text) < 3:
            return base_duration
        
        # Sentence seems COMPLETE - respond faster
        # Ends with punctuation or question/command patterns
        complete_indicators = [
            text.endswith('.'),
            text.endswith('?'),
            text.endswith('!'),
            text.endswith('please'),
            text.endswith('thanks'),
            text.endswith('thank you'),
            text.endswith('now'),
            text.endswith('it'),
            text.endswith('that'),
            # Question patterns
            any(text.startswith(w) for w in ['what', 'who', 'where', 'when', 'why', 'how', 'can', 'could', 'would', 'should', 'is', 'are', 'do', 'does']),
        ]
        
        # Sentence seems INCOMPLETE - wait longer for continuation
        incomplete_indicators = [
            text.endswith(' and'),
            text.endswith(' or'),
            text.endswith(' but'),
            text.endswith(' so'),
            text.endswith(' because'),
            text.endswith(' like'),
            text.endswith(' the'),
            text.endswith(' a'),
            text.endswith(' an'),
            text.endswith(' to'),
            text.endswith(' for'),
            text.endswith(' with'),
            text.endswith(' in'),
            text.endswith(' on'),
            text.endswith(' at'),
            text.endswith(' of'),
            text.endswith(' that'),
            text.endswith(' which'),
            text.endswith(' who'),
            text.endswith(' if'),
            text.endswith(' when'),
            text.endswith(' then'),
            text.endswith(' also'),
            text.endswith(' just'),
            text.endswith(' um'),
            text.endswith(' uh'),
            text.endswith('...'),
            text.endswith(','),
        ]
        
        if any(incomplete_indicators):
            # User is probably still thinking - wait longer
            logger.debug("Smart pause: incomplete sentence detected, waiting longer")
            return base_duration * 2.0  # Double the wait time
        
        if any(complete_indicators):
            # Sentence seems complete - respond faster
            logger.debug("Smart pause: complete sentence detected, responding faster")
            return base_duration * 0.6  # 40% faster response
        
        # Default behavior
        return base_duration
    
    def _start_partial_transcription(self):
        if self._partial_in_flight or self._transcribe_in_flight or not self._on_partial:
            return
        self._partial_in_flight = True
        audio = np.concatenate(list(self._audio_buffer))
        if len(audio) > self._partial_window_samples:
            audio = audio[-self._partial_window_samples:]
        thread = threading.Thread(
            target=self._run_partial_transcription,
            args=(audio,),
            daemon=True,
        )
        thread.start()

    def _run_partial_transcription(self, audio: np.ndarray):
        try:
            text = self._transcribe(audio, is_partial=True)
            if not text:
                return
            if text == self._last_partial_text:
                return
            self._last_partial_text = text
            if self._on_partial:
                self._on_partial(text)
        finally:
            self._partial_in_flight = False

    def _start_final_transcription(self, audio: np.ndarray):
        if self._transcribe_in_flight:
            return
        self._transcribe_in_flight = True
        thread = threading.Thread(
            target=self._run_final_transcription,
            args=(audio,),
            daemon=True,
        )
        thread.start()

    def _run_final_transcription(self, audio: np.ndarray):
        try:
            transcript = self._transcribe(audio, is_partial=False)
            if transcript and self._min_confidence > 0 and self._last_confidence < self._min_confidence:
                word_count = len(transcript.split())
                if word_count < 3:
                     if self._on_transcript:
                         self._on_transcript(transcript, True)
                     return
                logger.info(
                    "Transcript confidence %.2f below threshold %.2f, triggering repair loop",
                    self._last_confidence,
                    self._min_confidence,
                )
                # Instead of dropping, tag it for repair
                transcript = f"__LOW_CONFIDENCE__ {transcript}"
            if self._on_transcript:
                self._on_transcript(transcript or "", True)
        finally:
            self._transcribe_in_flight = False

    def _normalize_text(self, text: str) -> str:
        if not text:
            return text
        
        # Check for garbage/noise transcription first
        if self._is_garbage_transcription(text):
            logger.info("Rejected garbage transcription: '%s...'", text[:50])
            return ""
        
        normalized = text
        name_patterns = [
            r"chintu",
            r"chintoo",
            r"chinto",
            r"chin tu",
            r"chai+ntu",
            r"shintu",
            r"shintoo",
        ]
        for pattern in name_patterns:
            normalized = re.sub(rf"\b{pattern}\b", "Chintu", normalized, flags=re.IGNORECASE)

        wake_variants = {
            r"^(fetch into)\b": "hey Chintu",
            r"^(hinching to)\b": "hey Chintu",
            r"^(h2)\b": "hey Chintu",
        }
        for pattern, replacement in wake_variants.items():
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        
        # User name normalization - fix common Whisper mishearings of "Sasidhar"
        user_name_patterns = [
            r"\bcesar\b",
            r"\bcaesar\b", 
            r"\bsasid?har\b",
            r"\bsashidhar\b",
            r"\bsasi\b",
            r"\bsesidhar\b",
            r"\bsesid?ar\b",
        ]
        for pattern in user_name_patterns:
            normalized = re.sub(pattern, "Sasidhar", normalized, flags=re.IGNORECASE)
        
        return normalized

    def _is_garbage_transcription(self, text: str) -> bool:
        """
        Detect and reject garbage/noise transcriptions from Whisper hallucinations.
        Common patterns: repetitive short tokens, very low unique word ratio.
        """
        if not text:
            return False
        
        words = text.lower().split()
        if len(words) < 3:
            return False  # Too short to analyze
        
        # Check for highly repetitive patterns (e.g., "h n 2 h n 2 h n 2...")
        unique_words = set(words)
        unique_ratio = len(unique_words) / len(words)
        
        # If less than 10% unique words in a long transcript, it's garbage
        if len(words) > 10 and unique_ratio < 0.15:
            logger.debug("Garbage: low unique ratio %.2f", unique_ratio)
            return True
        
        # Check for repeated short sequences (common Whisper hallucination)
        # e.g., "h n 2" repeated many times
        if len(words) > 20:
            # Count most common word
            word_counts = {}
            for w in words:
                word_counts[w] = word_counts.get(w, 0) + 1
            max_count = max(word_counts.values())
            if max_count > len(words) * 0.4:  # Same word appears 40%+ of the time
                logger.debug("Garbage: word repeated %d/%d times", max_count, len(words))
                return True
        
        # Check for very short tokens only (noise)
        avg_word_len = sum(len(w) for w in words) / len(words)
        if len(words) > 15 and avg_word_len < 2.0:
            logger.debug("Garbage: avg word length %.1f", avg_word_len)
            return True
        
        return False

    def _confidence_from_logprob(self, avg_logprob: Optional[float]) -> float:
        """Convert avg_logprob to a 0-1 confidence estimate."""
        if avg_logprob is None:
            return 0.0
        # Typical avg_logprob range is around [-2.0, 0.0]
        confidence = (avg_logprob + 2.0) / 2.0
        return max(0.0, min(1.0, confidence))

    def _estimate_confidence(self, segments, info=None) -> float:
        """Estimate confidence from transcription segments."""
        if not segments:
            return 0.0

        avg_logprob_values = []
        no_speech_values = []
        for seg in segments:
            avg_logprob = getattr(seg, "avg_logprob", None)
            if avg_logprob is None and isinstance(seg, dict):
                avg_logprob = seg.get("avg_logprob")
            if avg_logprob is not None:
                avg_logprob_values.append(avg_logprob)
            no_speech_prob = getattr(seg, "no_speech_prob", None)
            if no_speech_prob is None and isinstance(seg, dict):
                no_speech_prob = seg.get("no_speech_prob")
            if no_speech_prob is not None:
                no_speech_values.append(no_speech_prob)

        avg_logprob = None
        if avg_logprob_values:
            avg_logprob = sum(avg_logprob_values) / len(avg_logprob_values)

        confidence = self._confidence_from_logprob(avg_logprob)

        if no_speech_values:
            no_speech_prob = sum(no_speech_values) / len(no_speech_values)
            confidence = min(confidence, max(0.0, 1.0 - no_speech_prob))

        return confidence

    @property
    def last_confidence(self) -> float:
        """Return the last transcription confidence estimate."""
        return self._last_confidence

    @property
    def speech_detected(self) -> bool:
        """Whether speech was detected during the current listen session."""
        return self._speech_detected

    def _transcribe(self, audio: np.ndarray, is_partial: bool = False) -> str:
        """Transcribe audio to text."""
        if self._backend == "simulation":
            return "[Simulated transcription - install whisper]"
        
        try:
            if self._backend == "faster-whisper":
                segments, info = self._model.transcribe(
                    audio,
                    language=self.language,
                    beam_size=self._partial_beam_size if is_partial else self._beam_size,
                    best_of=1 if is_partial else self._best_of,
                    vad_filter=False if is_partial else self._vad_filter,
                    initial_prompt=self._initial_prompt,
                    temperature=0.0 if is_partial else 0.2,
                    condition_on_previous_text=False,
                )
                segments = list(segments)
                text = " ".join([s.text for s in segments]).strip()
                self._last_confidence = self._estimate_confidence(segments, info)
            else:  # regular whisper
                result = self._model.transcribe(
                    audio,
                    language=self.language,
                    fp16=self.device != "cpu",
                    initial_prompt=self._initial_prompt,
                )
                text = result["text"].strip()
                segments = result.get("segments", [])
                self._last_confidence = self._estimate_confidence(segments, None)
            
            text = self._normalize_text(text)
            if is_partial:
                logger.debug(f"Partial transcript: '{text}'")
            else:
                logger.info(f"Transcribed: '{text}'")
            return text
            
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            self._last_confidence = 0.0
            return ""
    
    @property
    def is_listening(self) -> bool:
        """Check if currently listening."""
        return self._is_listening
