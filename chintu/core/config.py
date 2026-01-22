"""Configuration management for Chintu assistant."""

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict


class Config(BaseSettings):
    """Application configuration with environment variable support."""
    
    model_config = ConfigDict(
        env_prefix="CHINTU_",
        env_file=".env",
        env_file_encoding="utf-8",
    )
    
    # General
    app_name: str = "Chintu"
    debug: bool = False
    log_level: str = "INFO"
    structured_logging: bool = False
    structured_log_file: Optional[Path] = None
    
    # Wake Word Settings
    wake_word: str = "hey chintu"
    wake_word_sensitivity: float = Field(0.6, ge=0.0, le=1.0)  # Lowered to 0.6 to reduce TV false positives
    wake_word_model_path: Optional[str] = None  # Will be set in __init__ to custom ONNX
    wake_word_base_model: str = "hey_jarvis"
    wake_word_backend: str = "openwakeword"  # Force openWakeWord with custom model
    wake_word_verifier_threshold: float = Field(0.0, ge=0.0, le=1.0)
    wake_word_activation_frames: int = Field(2, ge=1, le=10)  # Reduced to 2 for faster response
    wake_word_cooldown_seconds: float = Field(0.5, ge=0.0, le=10.0)  # Reduced to 0.5 for instant re-trigger
    wake_word_confirm_with_stt: bool = False  # Disabled for instant activation (User request)
    wake_word_confirm_window_seconds: float = Field(1.5, ge=0.4, le=3.0)  # Slightly longer window
    wake_word_match_threshold: float = Field(0.65, ge=0.0, le=1.0)  # Lower for better detection
    wake_word_require_prefix: bool = False  # Don't require prefix - more flexible
    wake_word_stt_model: str = "base.en"
    wake_word_stt_confidence_threshold: float = Field(0.3, ge=0.0, le=1.0)  # Much lower - was 0.6
    wake_word_noise_mode: bool = True  # Enabled for TV/background noise rejection
    wake_word_min_word_count: int = Field(1, ge=1, le=6)  # Reduced from 2
    wake_word_sample_count: int = 5
    wake_word_sample_duration: float = 1.6
    wake_word_samples_dir: Optional[Path] = None
    wake_word_verifier_path: Optional[Path] = None
    wake_word_use_process: bool = False  # Disabled - API compatibility issue with OpenWakeWord
    
    # Speech-to-Text Settings
    whisper_model: str = "base.en"  # tiny.en, base.en, small.en for CPU
    whisper_device: str = "cpu"  # cpu or cuda
    whisper_language: str = "en"
    stt_timeout_seconds: float = 15.0  # Reduced from 20
    stt_vad_filter: bool = True  # Enable VAD for better end-of-speech detection
    stt_silence_threshold: float = Field(0.025, ge=0.0, le=1.0)  # Increased significantly to ignore fan noise
    stt_silence_duration: float = Field(0.4, ge=0.2, le=5.0)  # Reduced to 0.4 - respond faster when you stop
    stt_partial_interval: float = Field(0.5, ge=0.2, le=3.0)  # Faster partial updates
    stt_partial_window_seconds: float = Field(2.0, ge=0.8, le=6.0)  # Smaller window = faster response
    stt_initial_prompt: str = ""  # Removed - was causing phantom transcriptions
    stt_min_listen_seconds: float = Field(0.2, ge=0.0, le=3.0)  # Reduced from 0.6
    stt_min_confidence: float = Field(0.4, ge=0.0, le=1.0)  # Lowered to 0.4 for faster command acceptance
    stt_compute_type: str = "int8"
    stt_cpu_threads: int = 0
    stt_num_workers: int = 1
    stt_beam_size: int = Field(1, ge=1, le=8)
    stt_best_of: int = Field(1, ge=1, le=8)
    stt_partial_beam_size: int = Field(1, ge=1, le=8)
    stt_speech_frames_required: int = Field(2, ge=1, le=10)  # Reduced from 3 for faster detection
    
    # Conversation Mode Settings (Google Assistant-style)
    conversation_mode: bool = True  # Stay awake after response for follow-ups
    conversation_timeout_seconds: float = 15.0  # Go to sleep after this much silence
    auto_listen_on_connect: bool = True  # Start listening when UI connects

    # Text-to-Speech Settings
    tts_auto_speak: bool = True  # Speak responses automatically
    tts_streaming: bool = False  # Avoid line-by-line streaming TTS
    tts_prompt_after_response: bool = False  # Don't prompt to read aloud
    tts_allow_barge_in: bool = True  # Allow user to interrupt TTS
    tts_greeting_enabled: bool = True  # Greet user on startup
    
    # Audio Settings
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    audio_chunk_size: int = 1024
    
    # Gesture Settings
    gesture_enabled: bool = False
    gesture_confidence_threshold: float = 0.5
    gesture_max_hands: int = 1
    
    # LLM Settings (Ollama)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:1.5b"  # Fast model for CPU inference
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.7
    
    # API Keys (loaded from .env)
    google_ai_key: Optional[str] = None   # Gemini API key
    groq_api_key: Optional[str] = None    # Groq API key

    # Memory + Training Data
    memory_enabled: bool = True
    memory_top_k: int = 4  # Number of similar memories to retrieve (used by MemoryManager)
    # Future expansion options (not yet wired):
    # memory_embedding_dim: int = 256  # ChromaDB uses default 384-dim from all-MiniLM-L6-v2
    # memory_min_similarity: float = 0.25  # ChromaDB returns by similarity automatically
    # memory_max_items: int = 2000  # ChromaDB handles storage limits
    memory_store_path: Optional[Path] = None
    training_log_enabled: bool = True  # Enable JSONL training data logging
    training_auto_approve: bool = False  # DISABLED: Manual review required for safety
    training_log_path: Optional[Path] = None
    training_exports_dir: Optional[Path] = None
    
    @property
    def training_logging_enabled(self) -> bool:
        """Alias for training_log_enabled for backwards compatibility."""
        return self.training_log_enabled
    
    # WebSocket Server
    websocket_host: str = "127.0.0.1"
    websocket_port: int = 8765
    
    # Paths
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".chintu")
    models_dir: Optional[Path] = None
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.models_dir is None:
            self.models_dir = self.data_dir / "models"
            self.models_dir.mkdir(parents=True, exist_ok=True)
        if self.wake_word_samples_dir is None:
            self.wake_word_samples_dir = self.data_dir / "wakeword"
        self.wake_word_samples_dir.mkdir(parents=True, exist_ok=True)
        (self.wake_word_samples_dir / "positive").mkdir(parents=True, exist_ok=True)
        (self.wake_word_samples_dir / "negative").mkdir(parents=True, exist_ok=True)
        if self.wake_word_verifier_path is None:
            self.wake_word_verifier_path = self.wake_word_samples_dir / "verifier.pkl"
        
        # Auto-detect custom ONNX wake word model
        if self.wake_word_model_path is None:
            custom_onnx = self.wake_word_samples_dir / "hey_chintu.onnx"
            if custom_onnx.exists():
                self.wake_word_model_path = str(custom_onnx)

        if self.memory_store_path is None:
            # ChromaDB requires a directory, not a file
            self.memory_store_path = self.data_dir / "memory_db"
        self.memory_store_path.mkdir(parents=True, exist_ok=True)

        if self.training_log_path is None:
            self.training_log_path = self.data_dir / "training" / "interactions.jsonl"
        self.training_log_path.parent.mkdir(parents=True, exist_ok=True)

        if self.training_exports_dir is None:
            self.training_exports_dir = self.data_dir / "training" / "exports"
        self.training_exports_dir.mkdir(parents=True, exist_ok=True)


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
