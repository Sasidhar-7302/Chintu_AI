"""Configuration management for Chintu assistant."""

import os
from pathlib import Path
from typing import Optional, List
from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict


class Config(BaseSettings):
    """Application configuration with environment variable support."""
    
    model_config = ConfigDict(
        env_prefix="CHINTU_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignore extra environment variables not defined in the model
    )

    # General
    app_name: str = "Chintu"
    debug: bool = False
    log_level: str = "INFO"
    structured_logging: bool = True
    structured_log_file: Optional[Path] = Field(default_factory=lambda: Path.cwd() / "logs" / "latest.log")

    # User Customization (loaded from .env without prefix)
    user_name: str = "User"
    assistant_name: str = "Chintu"
    
    # Wake Word Settings
    wake_word: str = "hey chintu"
    wake_word_sensitivity: float = Field(0.65, ge=0.0, le=1.0)  # Balanced for reliability + reduce TV false positives
    wake_word_model_path: Optional[str] = None  # Will be set in __init__ to custom ONNX
    wake_word_base_model: str = "hey_jarvis"
    wake_word_backend: str = "openwakeword"  # Force openWakeWord with custom model
    wake_word_verifier_threshold: float = Field(0.0, ge=0.0, le=1.0)
    wake_word_activation_frames: int = Field(3, ge=1, le=10)  # 3 frames for consistent detection, reduces false positives
    wake_word_cooldown_seconds: float = Field(0.3, ge=0.0, le=10.0)  # Fast re-trigger after valid wake word
    wake_word_confirm_with_stt: bool = False  # Disabled by default for faster wake detection
    wake_word_confirm_window_seconds: float = Field(1.5, ge=0.4, le=3.0)  # Slightly longer window
    wake_word_match_threshold: float = Field(0.65, ge=0.0, le=1.0)  # Lower for better detection
    wake_word_require_prefix: bool = False  # Don't require prefix - more flexible
    wake_word_stt_model: str = "tiny.en"  # tiny.en = ~6x faster than base.en for wake word
    wake_word_stt_confidence_threshold: float = Field(0.3, ge=0.0, le=1.0)  # Much lower - was 0.6
    wake_word_noise_mode: bool = True  # Enabled for TV/background noise rejection
    wake_word_min_word_count: int = Field(1, ge=1, le=6)  # Reduced from 2
    wake_word_sample_count: int = 5
    wake_word_sample_duration: float = 1.6
    wake_word_samples_dir: Optional[Path] = None
    wake_word_verifier_path: Optional[Path] = None
    wake_word_use_process: bool = False  # Disabled - API compatibility issue with OpenWakeWord
    
    # Speech-to-Text Settings
    whisper_model: str = "small.en"  # Upgraded to small.en for better accuracy
    whisper_device: str = "auto"  # Smart auto-selection based on VRAM
    whisper_language: str = "en"
    stt_timeout_seconds: float = 15.0  # Reduced from 20
    stt_vad_filter: bool = False  # DISABLED - was removing valid speech
    stt_silence_threshold: float = Field(0.025, ge=0.0, le=1.0)  # Increased significantly to ignore fan noise
    stt_silence_duration: float = Field(0.35, ge=0.2, le=5.0)  # Ultra-fast response when user stops speaking
    stt_partial_interval: float = Field(0.5, ge=0.2, le=3.0)  # Faster partial updates
    stt_partial_window_seconds: float = Field(2.0, ge=0.8, le=6.0)  # Smaller window = faster response
    stt_initial_prompt: str = ""  # Removed - was causing phantom transcriptions
    stt_min_listen_seconds: float = Field(0.2, ge=0.0, le=3.0)  # Reduced from 0.6
    stt_min_confidence: float = Field(0.4, ge=0.0, le=1.0)  # Lowered to 0.4 for faster command acceptance
    stt_compute_type: str = "int8_float16"  # Optimized for GPU VRAM usage
    stt_cpu_threads: int = 0
    stt_num_workers: int = 1
    stt_beam_size: int = Field(1, ge=1, le=8)
    stt_best_of: int = Field(1, ge=1, le=8)
    stt_partial_beam_size: int = Field(1, ge=1, le=8)
    stt_speech_frames_required: int = Field(2, ge=1, le=10)  # Reduced from 3 for faster detection
    stt_auto_calibrate: bool = True  # Auto-calibrate silence threshold on startup
    stt_noise_calibration_seconds: float = Field(0.8, ge=0.2, le=5.0)
    stt_noise_multiplier: float = Field(3.0, ge=1.5, le=8.0)
    enable_barge_in: bool = True  # Enable Full Duplex Barge-In
    
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
    
    # Network
    network_check_host: str = "8.8.8.8"
    network_check_port: int = 53
    network_check_timeout_seconds: float = 2.0
    
    # Gesture Settings
    gesture_enabled: bool = False
    gesture_confidence_threshold: float = 0.5
    gesture_max_hands: int = 1
    
    # LLM Settings (Ollama)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"  # Optimized for 4GB VRAM (Sweet Spot)
    groq_model: str = "llama-3.1-8b-instant"
    gemini_model: str = "gemini-2.0-flash"
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.7
    llm_num_gpu: int = 50  # Offload layers to GPU
    llm_num_threads: Optional[int] = 4  # Cap CPU threads to avoid throttling
    llm_num_ctx: Optional[int] = None
    llm_prefer_local: bool = True  # Added to ensure GPU usage over cloud when possible
    groq_model: str = "llama-3.1-8b-instant"
    gemini_model: str = "gemini-2.0-flash"
    deepseek_model: str = "deepseek-chat"

    # Swarm Settings (v5.1)
    swarm_enabled: bool = False
    swarm_db_path: Optional[Path] = None
    swarm_router_model: str = "qwen2.5:1.5b"
    swarm_planner_model: str = "llama3.1:8b"
    swarm_coder_model: str = "qwen2.5-coder:7b"
    swarm_researcher_model: str = "phi3.5:mini"
    swarm_orchestrator_model: str = "qwen2.5:1.5b"
    swarm_parallel_enabled: bool = True

    # Docker Sandbox (MCP)
    docker_sandbox_image: str = "python:3.11-slim"
    docker_sandbox_network_mode: str = "none"
    docker_sandbox_workdir: str = "/app"
    docker_sandbox_workspace: Optional[Path] = None
    mcp_docker_enabled: bool = False
    mcp_docker_command: str = "python"
    mcp_docker_args: List[str] = Field(default_factory=lambda: ["-m", "chintu_backend.interfaces.mcp.docker_server"])
    mcp_enabled: bool = False
    # MCP servers can be provided as JSON via CHINTU_MCP_SERVERS, e.g.:
    # ["npx -y @modelcontextprotocol/server-github"]
    mcp_servers: List[str] = Field(default_factory=list)
    mcp_tool_cache_ttl_seconds: float = 300.0

    # Browser-as-Model fallback
    browser_fallback_enabled: bool = False
    docker_healthcheck_enabled: bool = False
    browser_fallback_threshold: float = Field(0.8, ge=0.0, le=1.0)
    browser_cdp_url: str = "http://localhost:9222"
    browser_fallback_url: str = "https://chatgpt.com"
    browser_fallback_timeout_seconds: float = 90.0

    # Autonomous Tools (code-first replacements for manual GUI steps)
    thumbnail_enabled: bool = True
    thumbnail_output_dir: Optional[Path] = None
    thumbnail_width: int = Field(1280, ge=640, le=4096)
    thumbnail_height: int = Field(720, ge=360, le=4096)

    email_reader_enabled: bool = False
    email_imap_host: Optional[str] = None
    email_imap_port: int = Field(993, ge=1, le=65535)
    email_imap_user: Optional[str] = None
    email_imap_password: Optional[str] = None
    email_imap_folder: str = "INBOX"
    email_reader_lookback_minutes: int = Field(30, ge=1, le=24 * 60)
    email_reader_max_messages: int = Field(10, ge=1, le=200)
    email_reader_allowed_senders: List[str] = Field(default_factory=list)
    email_reader_subject_keywords: List[str] = Field(
        default_factory=lambda: ["code", "verify", "verification", "security", "login"]
    )

    # Identity Vault (keyring-backed secrets with local encryption)
    identity_vault_enabled: bool = True
    identity_vault_key_path: Optional[Path] = None
    identity_vault_meta_path: Optional[Path] = None
    identity_vault_keyring_service_name: str = "chintu_ai_identity"

    # Telegram Gateway (headless control + push alerts)
    telegram_enabled: bool = False
    telegram_bot_token: Optional[str] = Field(default=None, validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_user_id: int = Field(default=0, validation_alias="TELEGRAM_ALLOWED_USER_ID")
    telegram_allow_orchestrator_approvals: bool = True
    telegram_allow_code_approvals: bool = False
    telegram_max_message_length: int = Field(3000, ge=200, le=4096)

    # WhatsApp (Twilio)
    whatsapp_enabled: bool = False
    whatsapp_account_sid: Optional[str] = Field(default=None, validation_alias="TWILIO_ACCOUNT_SID")
    whatsapp_auth_token: Optional[str] = Field(default=None, validation_alias="TWILIO_AUTH_TOKEN")
    whatsapp_from_number: Optional[str] = Field(default=None, validation_alias="TWILIO_WHATSAPP_FROM")
    whatsapp_allowed_numbers: str = ""

    # Project Watchdogs
    watchdog_enabled: bool = True
    watchdog_db_path: Optional[Path] = None
    watchdog_interval_seconds: float = 15.0
    watchdog_failure_threshold: int = 3

    # Project Orchestrator (long-running task execution)
    orchestrator_enabled: bool = True
    orchestrator_db_path: Optional[Path] = None
    orchestrator_interval_seconds: float = 60.0
    orchestrator_run_window_start_hour: int = Field(9, ge=0, le=23)
    orchestrator_run_window_end_hour: int = Field(21, ge=1, le=24)
    orchestrator_daily_budget_minutes: int = Field(120, ge=15, le=24 * 60)
    orchestrator_retry_backoff_minutes: int = Field(15, ge=1, le=24 * 60)
    orchestrator_max_step_attempts: int = Field(2, ge=1, le=10)
    
    # API Keys (loaded from .env - NO prefix for compatibility)
    google_ai_key: Optional[str] = Field(default=None, validation_alias="GOOGLE_AI_KEY")  # Gemini API key
    groq_api_key: Optional[str] = Field(default=None, validation_alias="GROQ_API_KEY")    # Groq API key
    deepseek_api_key: Optional[str] = Field(default=None, validation_alias="DEEPSEEK_API_KEY")  # DeepSeek API key

    # Memory + Training Data
    memory_enabled: bool = True
    memory_backend: str = "hybrid"  # hybrid | chroma
    memory_top_k: int = 4  # Number of similar memories to retrieve (used by MemoryManager)
    # Future expansion options (not yet wired):
    # memory_embedding_dim: int = 256  # ChromaDB uses default 384-dim from all-MiniLM-L6-v2
    # memory_min_similarity: float = 0.25  # ChromaDB returns by similarity automatically
    # memory_max_items: int = 2000  # ChromaDB handles storage limits
    memory_store_path: Optional[Path] = None
    memory_sqlite_path: Optional[Path] = None
    memory_markdown_sync_enabled: bool = False
    memory_markdown_dir: Optional[Path] = None
    memory_markdown_sync_interval_seconds: float = Field(60.0, ge=5.0, le=3600.0)
    memory_markdown_chunk_lines: int = Field(28, ge=4, le=200)
    memory_markdown_max_chunk_chars: int = Field(2400, ge=400, le=20000)
    memory_lifecycle_enabled: bool = True
    memory_lifecycle_interval_hours: float = Field(6.0, ge=0.5, le=168.0)
    memory_migrate_chroma: bool = False
    memory_decay_days: int = Field(90, ge=7, le=3650)
    training_log_enabled: bool = True  # Enable JSONL training data logging
    training_auto_approve: bool = False  # DISABLED: Manual review required for safety
    training_log_path: Optional[Path] = None
    training_exports_dir: Optional[Path] = None

    # Learning + Evolution
    learning_enabled: bool = True
    learning_auto_save: bool = True
    learning_train_enabled: bool = True
    learning_export_format: str = "chat"  # chat | instruction
    learning_weekly_enabled: bool = True
    learning_weekly_day: int = Field(6, ge=0, le=6)  # 0=Mon ... 6=Sun
    learning_weekly_hour: int = Field(2, ge=0, le=23)
    learning_weekly_min_events: int = Field(10, ge=1, le=10000)
    learning_train_command: Optional[str] = None
    learning_train_timeout_seconds: int = Field(3600, ge=60, le=86400)
    learning_base_model_id: str = "Qwen/Qwen2.5-1.5B-Instruct"
    learning_adapter_dir: Optional[Path] = None
    learning_use_finetuned_model: bool = True
    learning_train_max_steps: int = Field(80, ge=10, le=10000)
    learning_train_max_seq_len: int = Field(1024, ge=256, le=4096)
    learning_train_grad_accum: int = Field(8, ge=1, le=128)
    
    @property
    def training_logging_enabled(self) -> bool:
        """Alias for training_log_enabled for backwards compatibility."""
        return self.training_log_enabled
    
    # WebSocket Server
    websocket_host: str = "127.0.0.1"
    websocket_port: int = 8765

    # Gateway (Phase 1)
    gateway_enabled: bool = False
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 18789
    gateway_auth_token: Optional[str] = None

    # Skills (Phase 3)
    skills_enabled: bool = False
    skills_allow_shell: bool = False
    skills_use_docker: bool = False
    skills_docker_image: str = "python:3.11-slim"
    skills_docker_network_mode: str = "none"
    skills_docker_workdir: str = "/app"
    skills_dir: Optional[Path] = None  # Workspace skills (project root)
    skills_user_dir: Optional[Path] = None  # User-level skills (~/.chintu/skills)
    skills_bundled_dir: Optional[Path] = None  # Bundled skills shipped with app
    skills_learned_dir: Optional[Path] = None  # Learned skills (active learning)

    # Channel policies (Phase 4)
    channel_pairing_enabled: bool = False
    channel_allowlist_path: Optional[Path] = None
    telegram_dm_policy: str = "pairing"  # pairing | open
    
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
        if self.learning_adapter_dir is None:
            self.learning_adapter_dir = self.models_dir / "adapters"
        self.learning_adapter_dir.mkdir(parents=True, exist_ok=True)
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
            else:
                repo_onnx = Path.cwd() / "_Hey_Chintu_.onnx"
                if repo_onnx.exists():
                    self.wake_word_model_path = str(repo_onnx)
                else:
                    project_root = Path(__file__).resolve().parents[2]
                    root_onnx = project_root / "_Hey_Chintu_.onnx"
                    if root_onnx.exists():
                        self.wake_word_model_path = str(root_onnx)

        if self.memory_store_path is None:
            # ChromaDB requires a directory, not a file
            self.memory_store_path = self.data_dir / "memory_db"
        self.memory_store_path.mkdir(parents=True, exist_ok=True)

        if self.memory_sqlite_path is None:
            self.memory_sqlite_path = self.data_dir / "memory_hybrid.db"

        if self.memory_markdown_dir is None:
            self.memory_markdown_dir = self.data_dir / "brain_md"
        self.memory_markdown_dir.mkdir(parents=True, exist_ok=True)

        if self.training_log_path is None:
            self.training_log_path = self.data_dir / "training" / "interactions.jsonl"
        self.training_log_path.parent.mkdir(parents=True, exist_ok=True)

        if self.training_exports_dir is None:
            self.training_exports_dir = self.data_dir / "training" / "exports"
        self.training_exports_dir.mkdir(parents=True, exist_ok=True)

        if self.swarm_db_path is None:
            self.swarm_db_path = self.data_dir / "swarm.db"

        if self.docker_sandbox_workspace is None:
            self.docker_sandbox_workspace = Path.cwd()

        if self.watchdog_db_path is None:
            self.watchdog_db_path = self.data_dir / "watchdogs.db"

        if self.skills_dir is None:
            self.skills_dir = Path.cwd() / "skills"
        if self.skills_user_dir is None:
            self.skills_user_dir = self.data_dir / "skills"
        if self.skills_bundled_dir is None:
            self.skills_bundled_dir = (
                Path(__file__).resolve().parent.parent / "automation" / "skills" / "bundled"
            )
        if self.skills_learned_dir is None:
            project_learned = Path.cwd() / "brain_md" / "skills"
            self.skills_learned_dir = project_learned if project_learned.exists() else (self.data_dir / "skills_learned")
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.skills_user_dir.mkdir(parents=True, exist_ok=True)
        self.skills_bundled_dir.mkdir(parents=True, exist_ok=True)
        self.skills_learned_dir.mkdir(parents=True, exist_ok=True)

        if self.channel_allowlist_path is None:
            self.channel_allowlist_path = self.data_dir / "channel_allowlist.json"

        if self.orchestrator_db_path is None:
            self.orchestrator_db_path = self.data_dir / "orchestrator.db"

        if self.thumbnail_output_dir is None:
            self.thumbnail_output_dir = self.data_dir / "thumbnails"
        self.thumbnail_output_dir.mkdir(parents=True, exist_ok=True)

        if self.identity_vault_key_path is None:
            self.identity_vault_key_path = self.data_dir / "identity.key"
        self.identity_vault_key_path.parent.mkdir(parents=True, exist_ok=True)

        if self.identity_vault_meta_path is None:
            self.identity_vault_meta_path = self.data_dir / "identity_meta.json"
        self.identity_vault_meta_path.parent.mkdir(parents=True, exist_ok=True)


# Global config instance
_config: Optional[Config] = None
_config_loading = False  # Prevent recursive loading


def get_config() -> Config:
    """Get or create the global configuration instance."""
    global _config, _config_loading
    if _config is None and not _config_loading:
        _config_loading = True
        try:
            _config = Config()
        finally:
            _config_loading = False
    return _config


def get_config_lazy(key: str, default=None):
    """
    Get a single config value without loading the full config.

    Useful for fast startup when only a few values are needed.
    Falls back to environment variables directly.

    Args:
        key: Config key (e.g., 'wake_word', 'debug')
        default: Default value if not found

    Returns:
        The config value or default
    """
    import os

    # Map of commonly needed keys to their env var names and defaults
    _env_map = {
        'debug': ('CHINTU_DEBUG', False),
        'log_level': ('CHINTU_LOG_LEVEL', 'INFO'),
        'wake_word': ('CHINTU_WAKE_WORD', 'hey chintu'),
        'app_name': ('CHINTU_APP_NAME', 'Chintu'),
        'user_name': ('CHINTU_USER_NAME', 'User'),
        'assistant_name': ('CHINTU_ASSISTANT_NAME', 'Chintu'),
        'tts_auto_speak': ('CHINTU_TTS_AUTO_SPEAK', True),
        'memory_enabled': ('CHINTU_MEMORY_ENABLED', True),
        'groq_api_key': ('GROQ_API_KEY', None),
        'google_ai_key': ('GOOGLE_AI_KEY', None),
        'deepseek_api_key': ('DEEPSEEK_API_KEY', None),
    }

    if key in _env_map:
        env_var, fallback = _env_map[key]
        value = os.environ.get(env_var)
        if value is not None:
            # Convert string to appropriate type
            if isinstance(fallback, bool):
                return value.lower() in ('true', '1', 'yes')
            elif isinstance(fallback, int):
                return int(value)
            elif isinstance(fallback, float):
                return float(value)
            return value
        return fallback if default is None else default

    # Fall back to full config for unknown keys
    return getattr(get_config(), key, default)
