"""Audio module - Wake word detection, speech-to-text, and text-to-speech."""

import os
import sys

_FAST_IMPORT = bool(
    os.environ.get("PYTEST_CURRENT_TEST")
    or "pytest" in sys.modules
    or any(key.startswith("PYTEST") for key in os.environ)
)

if _FAST_IMPORT:
    # Keep imports minimal for test speed.
    from .text_to_speech import TextToSpeech, get_tts

    __all__ = [
        "TextToSpeech",
        "get_tts",
    ]
else:
    from .audio_capture import AudioCapture
    from .wake_word import WakeWordDetector
    from .speech_to_text import SpeechToText
    from .wake_word_training import WakeWordTrainer, WakeWordStatus
    from .text_to_speech import TextToSpeech, get_tts

    __all__ = [
        "AudioCapture",
        "WakeWordDetector",
        "SpeechToText",
        "WakeWordTrainer",
        "WakeWordStatus",
        "TextToSpeech",
        "get_tts",
    ]
