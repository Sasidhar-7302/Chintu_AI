"""Wake word detection using openWakeWord with STT fallback."""

import numpy as np
import threading
import queue
import time
import os
import re
import pickle
from difflib import SequenceMatcher
from typing import Optional, Callable
from collections import deque
import logging

logger = logging.getLogger(__name__)

# Try to import openwakeword
try:
    import openwakeword
    from openwakeword import Model as OWWModel
    HAS_OPENWAKEWORD = True
except ImportError:
    HAS_OPENWAKEWORD = False
    logger.warning("openwakeword not installed. Wake word detection will be simulated.")

# Try STT backends for fallback
try:
    from faster_whisper import WhisperModel as FasterWhisperModel
    HAS_FASTER_WHISPER = True
except ImportError:
    HAS_FASTER_WHISPER = False

try:
    import whisper as WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False


class WakeWordDetector:
    """
    Detects the wake word "Hey Chintu" in audio stream.
    Uses openWakeWord for detection.
    """
    
    def __init__(
        self,
        wake_word: str = "hey chintu",
        sensitivity: float = 0.5,
        model_path: Optional[str] = None,
        sample_rate: int = 16000,
        base_model: Optional[str] = None,
        verifier_path: Optional[str] = None,
        verifier_threshold: float = 0.2,
        match_threshold: float = 0.88,
        require_prefix: bool = True,
        stt_model_name: str = "tiny.en",
        stt_language: str = "en",
        stt_energy_threshold: float = 0.01,
        stt_window_seconds: float = 1.0,
        stt_overlap_seconds: float = 0.25,
        cooldown_seconds: float = 2.0,
        activation_frames: int = 3,
        confirm_with_stt: bool = False,
        confirm_window_seconds: float = 1.2,
        backend: str = "auto",
        # === NEW: Confidence Gating ===
        stt_confidence_threshold: float = 0.6,  # Minimum confidence for STT
        noise_mode: bool = False,  # Stricter mode for noisy environments
        min_word_count: int = 2,  # Minimum words for valid wake phrase
    ):
        self.wake_word = wake_word.lower()
        self._wake_phrase_norm = self._normalize_phrase(self.wake_word)
        self._wake_tokens = self._wake_phrase_norm.split()
        self.sensitivity = sensitivity
        self.sample_rate = sample_rate
        self._backend = (backend or "auto").lower()
        self._cooldown_seconds = cooldown_seconds
        self._last_wake_time = 0.0
        self._last_candidate_time = 0.0
        self._activation_frames = max(1, activation_frames)
        self._activation_counts = {}
        self._model_path = model_path
        self._base_model = base_model
        self._verifier_path = verifier_path
        self._verifier_threshold = verifier_threshold
        self._match_threshold = max(0.0, min(1.0, float(match_threshold)))
        self._require_prefix = bool(require_prefix)
        self._confirm_with_stt = confirm_with_stt
        self._confirm_window_samples = int(sample_rate * confirm_window_seconds)
        self._confirm_in_flight = False
        
        self._on_wake: Optional[Callable[[], None]] = None
        self._running = False
        self._audio_buffer = deque(maxlen=sample_rate * 3)  # 3 seconds buffer
        
        # Initialize the model
        self._model = None
        self._use_simulation = True
        self._use_openwakeword = False
        self._use_stt_fallback = False
        self._force_stt_fallback = False
        self._model_names = []
        self._model_key = None
        self._stt_backend = None
        self._stt_model = None
        self._stt_queue: Optional[queue.Queue] = None
        self._stt_thread: Optional[threading.Thread] = None
        self._stt_buffer = deque()
        self._stt_language = stt_language
        self._stt_energy_threshold = stt_energy_threshold
        self._stt_window_samples = int(sample_rate * stt_window_seconds)
        self._stt_overlap_samples = max(1, int(sample_rate * stt_overlap_seconds))
        self._stt_model_name = stt_model_name
        
        # === Confidence Gating ===
        self._stt_confidence_threshold = stt_confidence_threshold
        self._noise_mode = noise_mode
        self._min_word_count = min_word_count
        self._rejected_low_confidence = 0  # Counter for debugging

        # Custom classifier for wake word verification
        self._custom_classifier = None
        self._custom_classifier_sr = sample_rate
        self._init_custom_classifier()

        self._allow_openwakeword = self._backend in ("auto", "openwakeword")
        if HAS_OPENWAKEWORD:
            wake_key = self.wake_word.replace(" ", "_")
            base_key = self._base_model if self._base_model in openwakeword.MODELS else None
            wake_supported = bool(self._model_path) or wake_key in openwakeword.MODELS
            if not wake_supported:
                self._force_stt_fallback = True
                if self._backend == "auto":
                    self._allow_openwakeword = False
                    logger.info(
                        "Wake word '%s' not supported by openWakeWord; using STT fallback.",
                        self.wake_word,
                    )
                else:
                    if base_key:
                        logger.info(
                            "Wake word '%s' not supported by openWakeWord; using base model '%s' with STT fallback.",
                            self.wake_word,
                            base_key,
                        )
                    else:
                        logger.warning(
                            "Wake word '%s' not supported by openWakeWord; using STT fallback.",
                            self.wake_word,
                        )
                        self._allow_openwakeword = False

        if self._allow_openwakeword:
            self._init_openwakeword()

        if not self._use_openwakeword:
            self._init_stt_fallback()
        elif self._confirm_with_stt and self._stt_model is None:
            self._init_stt_fallback(enable_detection=False)
        elif self._force_stt_fallback and self._use_openwakeword:
            if self._stt_model is None:
                self._init_stt_fallback(enable_detection=True)
            else:
                self._use_stt_fallback = True
                self._use_simulation = False
                logger.info("STT fallback detection enabled alongside openWakeWord.")

        if self._use_simulation:
            logger.info("Using simulated wake word detection - no wake word backend available")
    
    def _init_stt_fallback(self, enable_detection: bool = True):
        """Initialize STT-based wake word fallback."""
        if HAS_FASTER_WHISPER:
            try:
                self._stt_model = FasterWhisperModel(
                    self._stt_model_name,
                    device="cpu",
                    compute_type="int8",
                )
                self._stt_backend = "faster-whisper"
                if enable_detection:
                    self._use_stt_fallback = True
                self._use_simulation = False
                mode = "fallback" if enable_detection else "confirm"
                logger.info(f"STT {mode} enabled with faster-whisper ({self._stt_model_name})")
                return
            except Exception as e:
                logger.warning(f"Failed to init faster-whisper fallback: {e}")

        if HAS_WHISPER:
            try:
                self._stt_model = WhisperModel.load_model(self._stt_model_name, device="cpu")
                self._stt_backend = "whisper"
                if enable_detection:
                    self._use_stt_fallback = True
                self._use_simulation = False
                mode = "fallback" if enable_detection else "confirm"
                logger.info(f"STT {mode} enabled with whisper ({self._stt_model_name})")
                return
            except Exception as e:
                logger.warning(f"Failed to init whisper fallback: {e}")

    def _init_custom_classifier(self):
        """Initialize custom classifier for wake word verification."""
        if not self._verifier_path:
            return
        
        verifier_path = str(self._verifier_path)
        if not verifier_path.endswith('.pkl') or not os.path.exists(verifier_path):
            return
        
        try:
            with open(verifier_path, 'rb') as f:
                data = pickle.load(f)

            if isinstance(data, dict):
                classifier = data.get('classifier')
                sample_rate = data.get('sample_rate', self.sample_rate)
            else:
                if hasattr(data, "predict"):
                    logger.info(
                        "Wake word verifier loaded for openWakeWord; skipping MFCC verifier."
                    )
                else:
                    logger.warning(
                        "Unsupported wake word verifier format: %s",
                        type(data),
                    )
                return

            if classifier is not None:
                self._custom_classifier = classifier
                self._custom_classifier_sr = sample_rate
                logger.info(f"Custom wake word classifier loaded from {verifier_path}")
                # If we have a custom classifier, we can use it standalone
                self._use_simulation = False
        except Exception as e:
            logger.warning(f"Failed to load custom classifier: {e}")
    
    def _verify_with_classifier(self, audio: np.ndarray) -> bool:
        """Verify audio using custom classifier."""
        if self._custom_classifier is None:
            return True  # No classifier = no verification needed
        
        try:
            # Import librosa for feature extraction
            try:
                import librosa
            except ImportError:
                return True  # Can't verify without librosa
            
            # Resample if needed
            if len(audio) < self._custom_classifier_sr:
                # Pad short audio
                audio = np.pad(audio, (0, self._custom_classifier_sr - len(audio)))
            
            # Extract MFCC features (same as training)
            target_length = int(1.5 * self._custom_classifier_sr)
            if len(audio) < target_length:
                audio = np.pad(audio, (0, target_length - len(audio)))
            else:
                audio = audio[:target_length]
            
            mfccs = librosa.feature.mfcc(
                y=audio,
                sr=self._custom_classifier_sr,
                n_mfcc=40,
                n_fft=512,
                hop_length=160,
            )
            
            features = mfccs.flatten()
            features = (features - features.mean()) / (features.std() + 1e-8)
            
            # Predict
            prediction = self._custom_classifier.predict([features])[0]
            probability = None
            if hasattr(self._custom_classifier, 'predict_proba'):
                proba = self._custom_classifier.predict_proba([features])[0]
                probability = proba[1] if len(proba) > 1 else proba[0]
            
            is_wake_word = prediction == 1
            logger.debug(f"Classifier prediction: {is_wake_word} (prob: {probability})")
            
            return is_wake_word
        except Exception as e:
            logger.warning(f"Classifier verification failed: {e}")
            return True  # On error, allow through

    def _ensure_openwakeword_models(self, model_name: Optional[str]) -> None:
        """Download openWakeWord models when package resources are missing."""
        try:
            from openwakeword.utils import download_models
        except Exception as exc:
            logger.debug(f"openWakeWord download helpers unavailable: {exc}")
            return

        try:
            target_name = model_name if model_name in openwakeword.MODELS else None

            missing_feature = any(
                not os.path.exists(meta["model_path"])
                for meta in list(openwakeword.FEATURE_MODELS.values())
                + list(openwakeword.VAD_MODELS.values())
            )
            missing_base = False
            if target_name:
                model_path = openwakeword.MODELS[target_name]["model_path"]
                missing_base = (
                    not os.path.exists(model_path)
                    or not os.path.exists(model_path.replace(".tflite", ".onnx"))
                )

            if missing_feature or missing_base:
                download_target = target_name or "hey_jarvis"
                logger.info(f"Downloading openWakeWord assets for '{download_target}'...")
                download_models([download_target])
        except Exception as exc:
            logger.warning(f"Failed to download openWakeWord models: {exc}")

    def _init_openwakeword(self):
        """Initialize openWakeWord with optional custom verifier."""
        if not HAS_OPENWAKEWORD:
            return
        try:
            target_name = None
            if self._model_path:
                if os.path.exists(self._model_path):
                    wakeword_models = [self._model_path]
                    # Custom model found - no need for STT confirmation
                    self._using_custom_model = True
                else:
                    logger.warning(f"Wake word model path not found: {self._model_path}")
                    self._using_custom_model = False
            else:
                candidate = self._base_model or self.wake_word.replace(" ", "_")
                if candidate in openwakeword.MODELS:
                    wakeword_models = [candidate]
                elif "hey_jarvis" in openwakeword.MODELS:
                    wakeword_models = ["hey_jarvis"]
                # Using base model - MUST verify with STT to ensure it's "Hey Chintu" not "Hey Jarvis"
                self._using_custom_model = False
                if not self._confirm_with_stt:
                    logger.info("Using base wake word model - enabling STT confirmation for phrase verification")
                    self._confirm_with_stt = True

            if not wakeword_models:
                return

            target_name = None
            if wakeword_models and not os.path.exists(wakeword_models[0]):
                target_name = wakeword_models[0]
            self._ensure_openwakeword_models(target_name)

            self._model_key = self._resolve_model_key(wakeword_models[0])
            custom_verifiers = {}
            if self._verifier_path and os.path.exists(self._verifier_path):
                custom_verifiers[self._model_key] = self._verifier_path

            self._model = OWWModel(
                wakeword_models=wakeword_models,
                inference_framework="onnx",
                custom_verifier_models=custom_verifiers,
                custom_verifier_threshold=self._verifier_threshold,
            )
            if self._model is not None:
                self._model_names = list(self._model.models.keys())
                logger.info(f"OpenWakeWord models loaded: {self._model_names}")
                self._use_openwakeword = True
                self._use_simulation = False
        except Exception as e:
            logger.warning(f"Failed to load openWakeWord model: {e}")

    @staticmethod
    def _resolve_model_key(model_name: str) -> str:
        if os.path.exists(model_name):
            return os.path.splitext(os.path.basename(model_name))[0]
        return model_name

    def _normalize_phrase(self, text: str) -> str:
        """Normalize text for wake word matching."""
        cleaned = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        return " ".join(cleaned.split())

    def _normalize_wake_transcript(self, text: str) -> str:
        if not text:
            return ""
        cleaned = text.lower()
        replacements = {
            "fetch into": "hey chintu",
            "hinching to": "hey chintu",
            "h2": "hey chintu",
            "chintoo": "chintu",
            "chin tu": "chintu",
            "chin to": "chintu",
            "chaiintu": "chintu",
            "hey chin to": "hey chintu",
            "hey chinto": "hey chintu",
            "a chintu": "hey chintu",
            "hey ginto": "hey chintu",
            "hey chintoo": "hey chintu",
            "hey chin too": "hey chintu",
            "hey chin two": "hey chintu",
            "hi chintu": "hey chintu",
            "hello chintu": "hey chintu",
            "hey chintu": "hey chintu",
            "he chintu": "hey chintu",
            "hay chintu": "hey chintu",
            "hey chinthu": "hey chintu",
            "hei chintu": "hey chintu",
            "hey jim": "hey chintu",
            "jim": "chintu",
            "h into": "hey chintu",
            "into": "chintu",
            "hintu": "chintu",
            "chin 2": "chintu",
            "chin to": "chintu",
            "chin two": "chintu",
            "chint u": "chintu",
        }
        for src, dest in replacements.items():
            cleaned = cleaned.replace(src, dest)
        return cleaned

    def _phrase_similarity(self, left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        return SequenceMatcher(None, left, right).ratio()

    def _has_wake_token(self, text: str) -> bool:
        """Require a token similar to the wake target to avoid false positives."""
        tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
        if not tokens:
            return False
        for token in tokens:
            if token in ["chintu", "jim", "hintu", "into", "chin"]:
                return True
            if self._phrase_similarity(token, "chintu") >= 0.6: # Relaxed from 0.7
                return True
        return False

    def _matches_wake_phrase(self, text: str) -> bool:
        if not text:
            return False
        if not self._has_wake_token(text):
            return False
        normalized = self._normalize_phrase(self._normalize_wake_transcript(text))
        if not normalized or not self._wake_phrase_norm:
            return False

        if self._require_prefix:
            if normalized.startswith(self._wake_phrase_norm):
                return True
        elif self._wake_phrase_norm in normalized:
            return True

        tokens = normalized.split()
        if not tokens or not self._wake_tokens:
            return False

        if len(tokens) < len(self._wake_tokens):
            candidate = " ".join(tokens)
            return self._phrase_similarity(candidate, self._wake_phrase_norm) >= self._match_threshold

        if self._require_prefix:
            candidate = " ".join(tokens[:len(self._wake_tokens)])
            return self._phrase_similarity(candidate, self._wake_phrase_norm) >= self._match_threshold

        best = 0.0
        for i in range(0, len(tokens) - len(self._wake_tokens) + 1):
            window = " ".join(tokens[i:i + len(self._wake_tokens)])
            best = max(best, self._phrase_similarity(window, self._wake_phrase_norm))
            if best >= self._match_threshold:
                return True
        return False

    def _confidence_from_logprob(self, avg_logprob: Optional[float]) -> float:
        if avg_logprob is None:
            return 0.0
        confidence = (avg_logprob + 2.0) / 2.0
        return max(0.0, min(1.0, confidence))

    def _estimate_confidence(self, segments) -> float:
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

    def _is_valid_wake_transcript(self, text: str, confidence: float) -> bool:
        if not text:
            return False
        if confidence < self._stt_confidence_threshold:
            self._rejected_low_confidence += 1
            return False
        if self._noise_mode:
            if len(text.split()) < self._min_word_count:
                return False
        return True

    def set_wake_callback(self, callback: Callable[[], None]):
        """Set callback to be called when wake word is detected."""
        self._on_wake = callback
    
    def start(self):
        """Start wake word detection."""
        self._running = True
        logger.info(f"Wake word detector started (listening for '{self.wake_word}')")
        if self._use_stt_fallback:
            self._stt_queue = queue.Queue(maxsize=50)
            self._stt_thread = threading.Thread(target=self._stt_loop, daemon=True)
            self._stt_thread.start()
    
    def stop(self):
        """Stop wake word detection."""
        self._running = False
        if self._stt_thread:
            self._stt_thread.join(timeout=2.0)
        logger.info("Wake word detector stopped")

    def reload(self, verifier_path: Optional[str] = None, base_model: Optional[str] = None):
        """Reload openWakeWord with updated verifier settings."""
        if verifier_path is not None:
            self._verifier_path = verifier_path
        if base_model is not None:
            self._base_model = base_model
        self._use_openwakeword = False
        self._model = None
        self._model_names = []
        self._model_key = None
        self._use_simulation = True
        self._activation_counts = {}
        if self._allow_openwakeword and self._backend != "stt":
            self._init_openwakeword()
        if not self._use_openwakeword and not self._use_stt_fallback:
            self._init_stt_fallback()
        elif self._confirm_with_stt and self._stt_model is None:
            self._init_stt_fallback(enable_detection=False)
    
    def process_audio(self, audio_chunk: np.ndarray):
        """
        Process an audio chunk for wake word detection.
        
        Args:
            audio_chunk: Audio data as numpy array (float32, 16kHz)
        """
        if not self._running:
            return

        if self._confirm_with_stt and self._use_openwakeword:
            self._audio_buffer.extend(audio_chunk.astype(np.float32).tolist())
        
        if time.monotonic() - self._last_wake_time < self._cooldown_seconds:
            return

        if self._use_stt_fallback and self._stt_queue:
            try:
                self._stt_queue.put_nowait(audio_chunk.copy())
            except queue.Full:
                pass
            if not self._use_openwakeword:
                return

        if self._use_simulation:
            return
        
        # Add to buffer (convert to int16 for openWakeWord)
        if audio_chunk.dtype != np.int16:
            audio_chunk = np.clip(audio_chunk, -1.0, 1.0)
            audio_chunk = (audio_chunk * 32767).astype(np.int16)
        
        try:
            # Run prediction on the latest chunk (openWakeWord handles buffering internally)
            predictions = self._model.predict(audio_chunk)
            
            # Check for wake word activation
            for model_name, scores in predictions.items():
                if isinstance(scores, (list, tuple, np.ndarray)):
                    score_value = max((float(score) for score in scores), default=0.0)
                else:
                    score_value = float(scores)

                if score_value > self.sensitivity:
                    count = self._activation_counts.get(model_name, 0) + 1
                else:
                    count = 0
                self._activation_counts[model_name] = count

                detected = count >= self._activation_frames

                if detected:
                    self._activation_counts[model_name] = 0
                    if self._confirm_with_stt and self._stt_model is not None:
                        now = time.monotonic()
                        if now - self._last_candidate_time < self._cooldown_seconds:
                            break
                        self._last_candidate_time = now
                        if self._confirm_in_flight:
                            break
                        self._confirm_in_flight = True
                        audio = np.array(self._audio_buffer, dtype=np.float32)
                        if len(audio) > self._confirm_window_samples:
                            audio = audio[-self._confirm_window_samples:]
                        threading.Thread(
                            target=self._confirm_wake_word,
                            args=(audio, model_name),
                            daemon=True,
                        ).start()
                        logger.debug(
                            "Wake word candidate detected; confirming via STT"
                        )
                    else:
                        self._trigger_wake(model_name, confirmed=False)
                    break
                    
        except Exception as e:
            logger.error(f"Error in wake word detection: {e}")

    def _trigger_wake(self, model_name: str, confirmed: bool = False, audio: np.ndarray = None):
        # Verify with custom classifier if available and audio is provided
        if audio is not None and self._custom_classifier is not None:
            if not self._verify_with_classifier(audio):
                logger.info("Wake word rejected by custom classifier")
                return
        
        status = "confirmed" if confirmed else "detected"
        logger.info(f"Wake word {status}! (model: {model_name})")
        if self._on_wake:
            self._on_wake()
        self._last_wake_time = time.monotonic()

    def _confirm_wake_word(self, audio: np.ndarray, model_name: str):
        try:
            text, confidence = self._transcribe_fallback(audio)
            if not self._is_valid_wake_transcript(text, confidence):
                logger.debug("Wake word STT confirm rejected (confidence/length)")
                return
            
            # Check if transcript matches wake phrase
            if self._matches_wake_phrase(text):
                self._trigger_wake(model_name, confirmed=True)
                return
            
            # Check if transcript contains wake-like tokens (partial match)
            # This handles cases like "hey chintu what can you do" where STT might 
            # only capture the command part but wake word was still said
            if self._has_wake_token(text):
                logger.debug("Wake word confirmed via wake token in: '%s'", text)
                self._trigger_wake(model_name, confirmed=True)
                return

            logger.debug(
                "Wake word candidate rejected - no wake token in: '%s'",
                text,
            )
            logger.debug(
                "Wake word candidate rejected by STT confirm: '%s'",
                text,
            )
        except Exception as exc:
            logger.warning(f"Wake word STT confirm error: {exc}")
        finally:
            self._confirm_in_flight = False

    def _stt_loop(self):
        """Background STT loop for wake word detection."""
        loop_count = 0
        while self._running and self._use_stt_fallback and self._stt_queue:
            loop_count += 1
            if loop_count % 100 == 0:
                logger.debug(f"[STT Fallback] Loop running (iterations: {loop_count}, buffer: {len(self._stt_buffer)})")
            try:
                chunk = self._stt_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if chunk is None:
                continue

            self._stt_buffer.extend(chunk.tolist())
            if len(self._stt_buffer) < self._stt_window_samples:
                continue

            audio = np.array(list(self._stt_buffer), dtype=np.float32)
            rms = np.sqrt(np.mean(audio ** 2))
            if rms < self._stt_energy_threshold:
                self._stt_buffer = deque(audio[-self._stt_overlap_samples:].tolist())
                continue

            if time.monotonic() - self._last_wake_time < self._cooldown_seconds:
                self._stt_buffer = deque(audio[-self._stt_overlap_samples:].tolist())
                continue

            text, confidence = self._transcribe_fallback(audio)
            logger.debug(f"[STT Fallback] Transcribed: '{text}' (conf={confidence:.2f})")
            if not self._is_valid_wake_transcript(text, confidence):
                self._stt_buffer = deque(audio[-self._stt_overlap_samples:].tolist())
                continue
            if self._matches_wake_phrase(text):
                logger.info(f"Wake phrase match: '{text}'")
                # Verify with custom classifier if available
                if self._custom_classifier is not None:
                    if not self._verify_with_classifier(audio):
                        logger.info("Wake word rejected by custom classifier (STT fallback)")
                        self._stt_buffer = deque(audio[-self._stt_overlap_samples:].tolist())
                        continue
                
                logger.info("Wake word detected via STT fallback")
                self._last_wake_time = time.monotonic()
                if self._on_wake:
                    self._on_wake()
                self._stt_buffer.clear()
            else:
                self._stt_buffer = deque(audio[-self._stt_overlap_samples:].tolist())

    def _transcribe_fallback(self, audio: np.ndarray) -> tuple[str, float]:
        """Transcribe audio for wake word detection (text, confidence)."""
        if self._stt_backend is None or self._stt_model is None:
            return "", 0.0

        try:
            if self._stt_backend == "faster-whisper":
                segments, _ = self._stt_model.transcribe(
                    audio,
                    language=self._stt_language,
                    beam_size=1,
                    vad_filter=False,
                )
                segments = list(segments)
                text = " ".join([s.text for s in segments]).strip()
                confidence = self._estimate_confidence(segments)
            else:
                result = self._stt_model.transcribe(
                    audio,
                    language=self._stt_language,
                    fp16=False,
                )
                text = result.get("text", "").strip()
                segments = result.get("segments", [])
                confidence = self._estimate_confidence(segments)
            return text.lower(), confidence
        except Exception as e:
            logger.warning(f"STT fallback error: {e}")
            return "", 0.0
    
    def simulate_wake_word(self):
        """Manually trigger wake word detection (for testing)."""
        logger.info("Wake word simulated!")
        if self._on_wake:
            self._on_wake()
    
    @property
    def is_running(self) -> bool:
        """Check if detector is running."""
        return self._running
    
    # === Noise Mode & Debug Methods ===
    
    def set_noise_mode(self, enabled: bool):
        """
        Enable/disable noise mode.
        
        When enabled:
        - Higher confidence threshold required
        - More words required in wake phrase
        """
        self._noise_mode = enabled
        if enabled:
            self._stt_confidence_threshold = max(0.7, self._stt_confidence_threshold)
            self._min_word_count = max(2, self._min_word_count)
        logger.info(f"Noise mode {'enabled' if enabled else 'disabled'}")
    
    def set_confirm_with_stt(self, enabled: bool):
        """Dynamically enable/disable STT confirmation."""
        if self._confirm_with_stt == enabled:
            return
            
        self._confirm_with_stt = enabled
        logger.info(f"Wake word STT confirmation {'enabled' if enabled else 'disabled'}")
        
        # If enabling and STT fallback not initialized, init it
        if enabled and self._stt_model is None:
            self._init_stt_fallback(enable_detection=False)

    def get_noise_mode(self) -> bool:
        """Check if noise mode is enabled."""
        return self._noise_mode
    
    def get_status(self) -> dict:
        """Get detector status for debug UI."""
        return {
            "running": self._running,
            "wake_word": self.wake_word,
            "backend": self._stt_backend or "simulation",
            "noise_mode": self._noise_mode,
            "confidence_threshold": self._stt_confidence_threshold,
            "min_word_count": self._min_word_count,
            "rejected_low_confidence": self._rejected_low_confidence,
            "using_openwakeword": self._use_openwakeword,
            "using_stt_fallback": self._use_stt_fallback,
            "cooldown_remaining": max(0, self._cooldown_seconds - (time.monotonic() - self._last_wake_time)),
        }
