"""Configuration management for Chintu assistant."""

import os
import sys
from pathlib import Path
from typing import Optional, List, Dict
from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict

from chintu_backend.core.config_runtime import apply_fast_defaults, initialize_runtime_paths


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
    hardware_auto_tune: bool = True
    hardware_adapt_runtime_enabled: bool = True
    hardware_adapt_check_interval_seconds: float = Field(120.0, ge=5.0, le=3600.0)

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
    stt_noise_calibration_min_samples: int = Field(20, ge=5, le=500)
    stt_reject_low_confidence_noise: bool = True
    stt_low_confidence_noise_word_limit: int = Field(6, ge=2, le=30)
    enable_barge_in: bool = False  # Disabled by default to prevent self-interruption (Echo)
    
    # Conversation Mode Settings (Google Assistant-style)
    conversation_mode: bool = True  # Stay awake after response for follow-ups
    conversation_timeout_seconds: float = 15.0  # Go to sleep after this much silence
    auto_listen_on_connect: bool = True  # Start listening when UI connects

    # Behavior policy (human-like responses)
    behavior_enabled: bool = True
    behavior_use_emotion_signals: bool = True
    behavior_include_mental_model: bool = True

    # Cloud response verification (local model as verifier)
    verify_cloud_responses: bool = True
    verify_cloud_max_chars: int = Field(2000, ge=200, le=10000)
    verify_cloud_min_words: int = Field(40, ge=10, le=500)
    training_mask_pii: bool = True

    # Text-to-Speech Settings
    tts_auto_speak: bool = True  # Speak responses automatically
    tts_streaming: bool = False  # Avoid line-by-line streaming TTS
    tts_prompt_after_response: bool = False  # Don't prompt to read aloud
    tts_allow_barge_in: bool = True  # Allow user to interrupt TTS
    tts_greeting_enabled: bool = True  # Greet user on startup
    tts_engine_mode: str = "quality"  # quality | balanced | speed
    tts_word_threshold: int = Field(25, ge=8, le=200)
    tts_summary_max_sentences: int = Field(3, ge=1, le=8)
    tts_summary_max_words: int = Field(70, ge=20, le=300)
    
    # Audio Settings
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    audio_chunk_size: int = 1024
    
    # Network
    network_check_host: str = "8.8.8.8"
    network_check_port: int = 53
    network_check_timeout_seconds: float = 3.0
    network_check_interval_seconds: float = Field(15.0, ge=2.0, le=300.0)
    network_check_failures_before_offline: int = Field(2, ge=1, le=10)
    network_check_successes_before_online: int = Field(1, ge=1, le=10)
    
    # Gesture Settings
    gesture_enabled: bool = False
    gesture_confidence_threshold: float = 0.5
    gesture_max_hands: int = 1

    # Terminal Execution (for code editing / self-improvements)
    terminal_enabled: bool = True
    terminal_require_confirmation: bool = True
    exec_approval_enabled: bool = True
    exec_approval_ttl_minutes: int = 10
    exec_approval_path: Optional[Path] = None
    # Phase 8: security/control policy resolver + sensitive action approval ledger
    security_unified_policy_enabled: bool = True
    security_runtime_profile: str = "balanced"  # balanced | safe_mode | high_trust
    security_payment_hard_block: bool = True
    security_publish_confirmation_required: bool = True
    security_destructive_confirmation_required: bool = True
    action_approval_enabled: bool = True
    action_approval_reuse_enabled: bool = True
    action_approval_ttl_minutes: int = Field(20, ge=1, le=180)
    action_approval_path: Optional[Path] = None
    # Tool loop guard (per-session repeated-call detection)
    tool_loop_detection_enabled: bool = True
    tool_loop_history_size: int = Field(24, ge=8, le=200)
    tool_loop_warning_threshold: int = Field(4, ge=2, le=50)
    tool_loop_critical_threshold: int = Field(6, ge=3, le=100)
    tool_loop_warning_cooldown_seconds: float = Field(12.0, ge=1.0, le=300.0)
    terminal_timeout_seconds: int = 60
    terminal_workspace_root: Path = Field(default_factory=lambda: Path.cwd())
    terminal_extra_roots: List[Path] = Field(default_factory=list)
    terminal_allowlist: List[str] = Field(default_factory=lambda: [
        "git", "rg", "python", "pip", "pytest",
        "node", "npm", "npx", "pnpm", "yarn",
        "deno", "go", "cargo", "dotnet", "cmake", "make", "msbuild",
        "code", "notepad", "type", "dir", "where"
    ])
    terminal_blocklist: List[str] = Field(default_factory=lambda: [
        "powershell", "pwsh", "cmd", "bash", "sh", "wsl"
    ])

    # Phase 4: Dependency bootstrap / environment recovery
    dependency_bootstrap_enabled: bool = True
    dependency_bootstrap_auto_resume: bool = True
    dependency_bootstrap_prefer_user_installs: bool = True
    dependency_bootstrap_force_user_scope: bool = True
    dependency_bootstrap_prefer_uv: bool = True
    dependency_bootstrap_prefer_npm_user_scope: bool = True
    dependency_bootstrap_allow_global_installs: bool = False
    dependency_bootstrap_max_attempts: int = Field(1, ge=1, le=3)
    dependency_bootstrap_receipts_dir: Optional[Path] = None
    # Phase 7: reliability + self-healing
    phase7_self_healing_enabled: bool = True
    phase7_max_recovery_attempts: int = Field(2, ge=1, le=5)
    phase7_cloud_fallback_enabled: bool = True
    phase7_watchdog_repeat_threshold: int = Field(3, ge=2, le=10)
    phase7_watchdog_window_seconds: float = Field(180.0, ge=30.0, le=3600.0)
    # Phase 9: governance + benchmarking
    phase9_governance_enabled: bool = True
    phase9_fail_on_critical_alerts: bool = True
    phase9_min_9_task_pass_rate: float = Field(0.85, ge=0.0, le=1.0)
    phase9_min_extended_pass_rate: float = Field(0.70, ge=0.0, le=1.0)
    phase9_weekly_target_pass_rate: float = Field(0.80, ge=0.0, le=1.0)
    phase9_drop_alert_threshold: float = Field(0.08, ge=0.01, le=0.5)
    phase9_reports_dir: Optional[Path] = None
    phase9_history_path: Optional[Path] = None
    phase9_alerts_path: Optional[Path] = None
    phase9_monthly_review_dir: Optional[Path] = None
    # Phase 15: safe self-improvement
    phase15_enabled: bool = True
    phase15_auto_propose_skill_on_missing_capability: bool = True
    phase15_routing_learning_enabled: bool = True
    phase15_routing_min_events: int = Field(40, ge=5, le=5000)
    phase15_routing_min_provider_attempts: int = Field(4, ge=1, le=1000)
    phase15_apply_routing_changes_automatically: bool = False
    phase15_dir: Optional[Path] = None
    phase15_gap_plans_dir: Optional[Path] = None
    phase15_change_reports_dir: Optional[Path] = None
    phase15_routing_reports_dir: Optional[Path] = None
    
    # Safe Execution (Docker Sandbox)
    safe_exec_sandbox_enabled: bool = False
    safe_exec_docker_image: str = "python:3.10-slim"
    safe_exec_mount_cwd: bool = True

    # Browser profiles
    browser_profiles_dir: Optional[Path] = None
    
    # LLM Settings (Ollama)
    ollama_host: str = "http://localhost:11434"
    ollama_keep_alive_seconds: int = 600  # Keep the local model loaded to reduce cold-start latency
    ollama_think: bool = False  # Disable verbose "thinking" output by default for lower latency
    ollama_think_for_complex_reasoning: bool = True  # Enable thinking for System-2 (complex_reasoning) tasks
    ollama_model: str = "qwen3.5:4b"  # Executive Brain (local-first default)
    ollama_model_strong: str = "qwen3.5:9b"  # Optional local upgrade for harder tasks
    airllm_enabled: bool = False
    airllm_model_id: str = ""
    airllm_cache_dir: Optional[Path] = None
    airllm_max_tokens: int = Field(2048, ge=128, le=8192)
    airllm_compression: str = "auto"  # auto|4bit|8bit|none
    airllm_device: str = "auto"  # auto|cuda:0|cpu
    airllm_allow_download: bool = False
    airllm_download_timeout_seconds: int = Field(3600, ge=60, le=86400)
    airllm_runtime_mode: str = "auto"  # auto|inprocess|subprocess
    airllm_request_timeout_seconds: int = Field(900, ge=30, le=7200)
    airllm_startup_timeout_seconds: int = Field(1800, ge=60, le=14400)
    llm_auto_select_model: bool = True
    llm_local_strong_model_enabled: bool = True
    llm_prewarm_enabled: bool = False
    llm_prewarm_include_strong: bool = True
    vision_prewarm_enabled: bool = False
    groq_model: str = "llama-3.1-8b-instant"
    gemini_model: str = "gemini-2.0-flash"
    deepseek_model: str = "deepseek-chat"
    nvidia_model: str = "moonshotai/kimi-k2.5"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    routing_prefer_free: bool = True
    routing_cloud_priority: List[str] = Field(default_factory=lambda: ["nvidia", "groq", "gemini", "deepseek"])
    provider_credits: Dict[str, float] = Field(default_factory=dict, validation_alias="CHINTU_PROVIDER_CREDITS")
    provider_circuit_breaker_enabled: bool = True
    provider_circuit_failure_threshold: int = Field(3, ge=1, le=20)
    provider_circuit_recovery_seconds: float = Field(45.0, ge=1.0, le=3600.0)
    provider_circuit_half_open_successes: int = Field(1, ge=1, le=10)
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.7
    llm_num_gpu: int = -1  # Ollama auto mode (prevents over-allocation on smaller VRAM cards)
    llm_num_threads: Optional[int] = 4  # Cap CPU threads to avoid throttling
    llm_num_ctx: Optional[int] = None
    llm_context_budget_chars: int = Field(3200, ge=800, le=20000)
    llm_context_max_conversation_turns: int = Field(8, ge=2, le=30)
    llm_context_include_preferences: bool = True
    phase16_clarifier_enabled: bool = True
    phase16_clarifier_min_words: int = Field(3, ge=1, le=20)
    phase16_clarifier_context_turns: int = Field(2, ge=1, le=10)
    phase16_clarifier_markers: List[str] = Field(
        default_factory=lambda: [
            "continue",
            "go on",
            "again",
            "do it",
            "do that",
            "same",
            "what about this",
            "what about that",
            "tell me more",
            "more details",
            "next",
            "next one",
        ]
    )
    llm_prefer_local: bool = True  # Added to ensure GPU usage over cloud when possible
    llm_tool_routing_enabled: bool = True
    llm_tool_routing_mode: str = "auto"  # auto | always | fallback
    llm_tool_routing_match_threshold: float = Field(0.18, ge=0.0, le=1.0)
    # Dispatcher fast-path tuning: lower defaults keep obvious system commands
    # off the slow LLM route ("set volume", "take screenshot", etc.).
    dispatcher_fast_path_threshold: float = Field(0.35, ge=0.0, le=1.0)
    dispatcher_direct_capability_threshold: float = Field(0.45, ge=0.0, le=1.0)
    gpu_resource_manager_enabled: bool = True
    gpu_step_telemetry_enabled: bool = True
    gpu_primary_device_id: int = Field(-1, ge=-1, le=16)
    gpu_secondary_device_id: int = Field(-1, ge=-1, le=16)
    gpu_primary_reserved_vram_mb: int = Field(2048, ge=0, le=65536)
    gpu_secondary_reserved_vram_mb: int = Field(1024, ge=0, le=65536)
    gpu_default_allow_cpu_fallback: bool = True
    gpu_local_brain_num_gpu: int = Field(-1, ge=-1, le=120)
    gpu_local_background_num_gpu: int = Field(20, ge=0, le=120)
    gpu_local_sanitizer_num_gpu: int = Field(16, ge=0, le=120)
    gpu_local_force_cpu_when_insufficient: bool = True
    llm_tool_routing_confidence_threshold: float = Field(0.55, ge=0.0, le=1.0)
    llm_tool_routing_max_candidates: int = Field(12, ge=4, le=30)
    llm_tool_routing_max_schema_fields: int = Field(6, ge=2, le=20)
    llm_tool_routing_local_only: bool = True
    llm_local_fallback_models: List[str] = Field(
        default_factory=lambda: [
            "qwen3.5:4b",
            "qwen3.5:9b",
            "qwen2.5-coder:7b",
            "llama3.1:8b",
            "qwen2.5:3b",
            "qwen2.5:1.5b",
        ]
    )
    llm_arbiter_enabled: bool = True
    llm_arbiter_confidence_threshold: float = Field(0.55, ge=0.0, le=1.0)
    llm_arbiter_sensitive_local_only: bool = True
    arbiter_telemetry_enabled: bool = True
    arbiter_telemetry_retention_events: int = Field(2000, ge=100, le=100000)
    arbiter_telemetry_path: Optional[Path] = None
    router_local_model_check_interval_seconds: float = Field(300.0, ge=5.0, le=3600.0)
    catalog_model_path: Optional[Path] = None
    catalog_model_feed_urls: List[str] = Field(default_factory=lambda: [
        "https://openai.com/news/rss.xml",
        "https://www.anthropic.com/news/rss.xml",
        "https://huggingface.co/blog/feed.xml",
        "https://ollama.com/blog/rss.xml",
    ])
    catalog_model_max_releases: int = Field(20, ge=5, le=200)
    catalog_model_save_memory: bool = True
    knowledge_updater_enabled: bool = True
    knowledge_store_dir: Optional[Path] = None
    knowledge_vector_backend: str = "chroma"  # chroma | sqlite
    knowledge_chroma_collection: str = "knowledge_updates"
    knowledge_daily_fetch_per_category: int = Field(8, ge=2, le=40)
    knowledge_digest_max_age_hours: int = Field(72, ge=12, le=720)
    knowledge_news_max_age_hours: int = Field(48, ge=6, le=240)
    knowledge_news_min_reliability: float = Field(0.58, ge=0.0, le=1.0)
    knowledge_news_fallback_min_reliability: float = Field(0.35, ge=0.0, le=1.0)
    knowledge_news_extra_trusted_domains: List[str] = Field(default_factory=list)
    knowledge_include_model_releases: bool = True
    knowledge_archive_enabled: bool = True
    knowledge_archive_on_like: bool = True
    knowledge_archive_include_html: bool = False
    knowledge_archive_max_text_chars: int = Field(120000, ge=2000, le=1000000)
    knowledge_archive_max_html_chars: int = Field(120000, ge=2000, le=1000000)
    semantic_routing_enabled: bool = False
    # Repository indexing (incremental codebase search via ChromaDB)
    repo_index_collection_name: str = "repo_index_v1"
    repo_index_dir: Optional[Path] = None
    repo_index_include_untracked: bool = True
    repo_index_max_file_bytes: int = Field(2 * 1024 * 1024, ge=32 * 1024, le=200 * 1024 * 1024)
    repo_index_chunk_chars: int = Field(2400, ge=400, le=20000)
    repo_index_chunk_overlap_chars: int = Field(200, ge=0, le=2000)
    repo_index_allowed_extensions: List[str] = Field(
        default_factory=lambda: [
            ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
            ".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".sass", ".html", ".xml",
            ".sql", ".sh", ".ps1", ".bat", ".cmd",
            ".go", ".rs", ".java", ".kt", ".swift", ".c", ".h", ".cpp", ".hpp", ".cs",
            ".csv", ".tsv", ".rst",
        ]
    )
    repo_index_secret_patterns: List[str] = Field(
        default_factory=lambda: [
            ".env",
            ".pem",
            ".p12",
            ".pfx",
            ".key",
            "token",
            "secret",
            "private",
        ]
    )

    # Swarm Settings (v5.1)
    swarm_enabled: bool = False
    swarm_db_path: Optional[Path] = None
    watchdog_db_path: Optional[Path] = None
    watchdog_enabled: bool = True
    watchdog_interval_seconds: float = Field(60.0, ge=5.0, le=3600.0)
    # Run-level timeout watchdog (built on top of the same interval).
    run_timeout_enabled: bool = True
    run_timeout_seconds: float = Field(900.0, ge=30.0, le=86400.0)
    swarm_router_model: str = "qwen2.5:1.5b"
    swarm_planner_model: str = "llama3.1:8b"
    swarm_coder_model: str = "qwen2.5-coder:7b"
    swarm_researcher_model: str = "llama3.1:8b"
    swarm_orchestrator_model: str = "llama3.1:8b"
    swarm_parallel_enabled: bool = True
    swarm_max_agents: int = Field(3, ge=1, le=6)
    swarm_agent_timeout_seconds: float = Field(45.0, ge=5.0, le=600.0)
    swarm_total_timeout_seconds: float = Field(120.0, ge=10.0, le=1800.0)
    swarm_trace_enabled: bool = True
    agent_policies_path: Optional[Path] = None
    agent_registry_path: Optional[Path] = None
    agent_default_role: str = "primary"
    agent_default_workspace_mode: str = "shared"  # shared | isolated
    agent_workspace_root: Optional[Path] = None
    agent_primary_workspace: Optional[Path] = None
    agent_isolation_enabled: bool = True
    # Phase 26: workspace abstraction + bounded autonomy
    workspace_api_enabled: bool = True
    workspace_default_runtime_profile: str = "safe_mode"  # safe_mode | balanced | high_trust
    workspace_root_dir: Optional[Path] = None
    workspace_receipts_dir: Optional[Path] = None
    workspace_checkpoints_dir: Optional[Path] = None
    workspace_remote_sandbox_enabled: bool = False
    workspace_untrusted_channels: List[str] = Field(
        default_factory=lambda: ["telegram", "remote", "webhook"]
    )
    workspace_sandbox_default_for_shell: bool = True

    # Docker Sandbox (MCP)
    docker_sandbox_image: str = "python:3.11-slim"
    docker_sandbox_network_mode: str = "none"
    docker_sandbox_workdir: str = "/app"
    docker_sandbox_workspace: Optional[Path] = None
    mcp_docker_enabled: bool = False
    mcp_docker_command: str = "python"
    mcp_docker_args: List[str] = Field(default_factory=lambda: ["-m", "chintu_backend.interfaces.mcp.docker_server"])
    mcp_enabled: bool = True
    # MCP servers can be provided as JSON via CHINTU_MCP_SERVERS, e.g.:
    # ["npx -y @modelcontextprotocol/server-github"]
    mcp_servers: List[str] = Field(default_factory=list)
    mcp_tool_cache_ttl_seconds: float = 300.0
    mcp_server_allowlist: List[str] = Field(default_factory=list)
    mcp_tool_allowlist: List[str] = Field(default_factory=list)
    mcp_tool_denylist: List[str] = Field(default_factory=list)

    # Browser-as-Model fallback
    browser_fallback_enabled: bool = True
    docker_healthcheck_enabled: bool = False
    browser_fallback_threshold: float = Field(0.8, ge=0.0, le=1.0)
    browser_cdp_url: str = "http://localhost:9222"
    browser_fallback_url: str = "https://chatgpt.com"
    browser_fallback_timeout_seconds: float = 90.0
    browser_relevance_policy_enabled: bool = True
    browser_relevance_blocked_domains: List[str] = Field(
        default_factory=lambda: ["x.com", "twitter.com", "t.co"]
    )
    browser_relevance_allow_search_domains: List[str] = Field(
        default_factory=lambda: ["google.com", "bing.com", "duckduckgo.com", "search.brave.com"]
    )
    browser_relevance_min_score: float = Field(0.28, ge=0.0, le=1.0)
    browser_pilot_min_relevance_score: float = Field(0.2, ge=0.0, le=1.0)
    browser_relevance_factual_min_sources: int = Field(2, ge=1, le=10)
    browser_factual_claim_min_supported_ratio: float = Field(0.6, ge=0.0, le=1.0)
    browser_factual_claim_min_score: float = Field(0.16, ge=0.0, le=1.0)
    browser_factual_claim_max_claims: int = Field(6, ge=1, le=20)
    browser_prompt_sanitizer_enabled: bool = True
    browser_prompt_sanitizer_max_chars: int = Field(1200, ge=200, le=10000)

    # Autonomous Tools (code-first replacements for manual GUI steps)
    thumbnail_enabled: bool = True
    thumbnail_output_dir: Optional[Path] = None
    thumbnail_width: int = Field(1280, ge=640, le=4096)
    thumbnail_height: int = Field(720, ge=360, le=4096)

    email_reader_enabled: bool = True
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
    jira_enabled: bool = True
    jira_base_url: Optional[str] = None
    jira_email: Optional[str] = None
    jira_api_token: Optional[str] = None
    jira_project_key: Optional[str] = None
    jira_issue_type: str = "Task"

    # Identity Vault (keyring-backed secrets with local encryption)
    identity_vault_enabled: bool = True
    identity_vault_key_path: Optional[Path] = None
    identity_vault_meta_path: Optional[Path] = None
    identity_vault_keyring_service_name: str = "chintu_ai_identity"
    # Phase 20: OAuth onboarding + integration receipts
    integrations_receipts_dir: Optional[Path] = None
    google_calendar_default_write_access: bool = False

    # Telegram Gateway (headless control + push alerts)
    telegram_enabled: bool = False
    telegram_bot_token: Optional[str] = Field(default=None, validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_user_id: int = Field(default=0, validation_alias="TELEGRAM_ALLOWED_USER_ID")
    telegram_allow_orchestrator_approvals: bool = True
    telegram_allow_code_approvals: bool = False
    telegram_approval_signing_secret: Optional[str] = Field(
        default=None,
        validation_alias="TELEGRAM_APPROVAL_SIGNING_SECRET",
    )
    telegram_require_signed_approvals: bool = True
    telegram_mini_app_enabled: bool = False
    telegram_mini_app_url: Optional[str] = None
    telegram_mini_app_token_ttl_seconds: int = Field(900, ge=60, le=86400)
    telegram_max_message_length: int = Field(3000, ge=200, le=4096)
    # Phase 21: Telegram inbox intake + content intelligence
    telegram_inbox_enabled: bool = True
    telegram_inbox_auto_process: bool = True
    telegram_inbox_max_queue_size: int = Field(500, ge=10, le=10000)
    telegram_inbox_process_batch_size: int = Field(5, ge=1, le=100)
    telegram_inbox_media_dir: Optional[Path] = None
    telegram_inbox_db_path: Optional[Path] = None
    telegram_inbox_items_dir: Optional[Path] = None
    telegram_inbox_video_max_frames: int = Field(16, ge=4, le=80)
    # Phase 23: LLM-in-browser research profiles
    research_browser_enabled: bool = True
    research_browser_submit_requires_confirmation: bool = True
    research_browser_default_profile: str = "research"
    research_browser_loggedin_profile: str = "assistant_accounts"
    research_browser_capture_dir: Optional[Path] = None
    # Phase 24: Communications + reservations
    communications_enabled: bool = True
    communications_allow_owner_call_without_confirmation: bool = True
    communications_owner_profile_path: Optional[Path] = None
    communications_receipts_dir: Optional[Path] = None
    communications_default_adapter: str = "google_voice_browser"

    # WhatsApp (Twilio)
    whatsapp_enabled: bool = False
    whatsapp_account_sid: Optional[str] = Field(default=None, validation_alias="TWILIO_ACCOUNT_SID")
    whatsapp_auth_token: Optional[str] = Field(default=None, validation_alias="TWILIO_AUTH_TOKEN")
    whatsapp_from_number: Optional[str] = Field(default=None, validation_alias="TWILIO_WHATSAPP_FROM")
    whatsapp_allowed_numbers: str = ""
    whatsapp_provider: str = "twilio"  # twilio | baileys
    whatsapp_baileys_url: Optional[str] = None
    whatsapp_baileys_token: Optional[str] = None
    whatsapp_baileys_send_path: str = "send"
    whatsapp_baileys_webhook_secret: Optional[str] = None

    # Slack (Webhook/Event API)
    slack_enabled: bool = False
    slack_bot_token: Optional[str] = None
    slack_signing_secret: Optional[str] = None
    slack_allowed_channels: str = ""
    slack_allowed_users: str = ""

    # Discord (Interactions/Webhook)
    discord_enabled: bool = False
    discord_application_id: Optional[str] = None
    discord_public_key: Optional[str] = None
    discord_bot_token: Optional[str] = None
    discord_allowed_channels: str = ""
    discord_allowed_users: str = ""

    # Teams (Webhook relay)
    
    # Job application automation
    job_apply_enabled: bool = True
    job_apply_require_submit_confirm: bool = True
    job_apply_require_upload_confirm: bool = True
    job_apply_max_per_run: int = Field(5, ge=1, le=50)
    job_apply_default_location: str = ""
    job_apply_default_keywords: List[str] = Field(default_factory=list)
    job_apply_default_max_years: int = Field(3, ge=0, le=20)
    job_apply_sites: List[str] = Field(default_factory=lambda: ["linkedin.com/jobs"])
    resume_tex_path: Optional[Path] = None
    resume_auto_edit_enabled: bool = True
    resume_compile_enabled: bool = False
    resume_compile_command: str = "pdflatex"
    job_apply_require_no_citizenship: bool = True
    job_apply_preferred_keywords: List[str] = Field(default_factory=list)
    job_apply_block_keywords: List[str] = Field(default_factory=list)
    job_apply_min_salary: Optional[int] = None
    job_apply_require_remote: bool = False
    job_apply_require_hybrid: bool = False
    teams_enabled: bool = False
    teams_webhook_secret: Optional[str] = None

    # Signal (Relay)
    signal_enabled: bool = False
    signal_webhook_secret: Optional[str] = None

    # iMessage (Relay)
    imessage_enabled: bool = False
    imessage_webhook_secret: Optional[str] = None
    orchestrator_run_window_start_hour: int = Field(9, ge=0, le=23)
    orchestrator_run_window_end_hour: int = Field(21, ge=1, le=24)
    orchestrator_require_idle: bool = False
    orchestrator_idle_min_seconds: int = Field(10 * 60, ge=0, le=24 * 3600)
    orchestrator_idle_max_cpu_percent: int = Field(30, ge=1, le=100)
    orchestrator_idle_max_gpu_util_percent: int = Field(25, ge=1, le=100)
    night_run_start_hour: int = Field(1, ge=0, le=23)
    night_run_end_hour: int = Field(6, ge=0, le=24)
    orchestrator_daily_budget_minutes: int = Field(120, ge=15, le=24 * 60)
    orchestrator_retry_backoff_minutes: int = Field(15, ge=1, le=24 * 60)
    orchestrator_max_step_attempts: int = Field(2, ge=1, le=10)
    verification_max_attempts: int = Field(2, ge=1, le=5)
    verification_retry_capabilities: List[str] = Field(
        default_factory=lambda: ["take_screenshot", "open_app", "write_file", "move_file"]
    )
    
    # API Keys (loaded from .env - NO prefix for compatibility)
    google_ai_key: Optional[str] = Field(default=None, validation_alias="GOOGLE_AI_KEY")  # Gemini API key
    groq_api_key: Optional[str] = Field(default=None, validation_alias="GROQ_API_KEY")    # Groq API key
    deepseek_api_key: Optional[str] = Field(default=None, validation_alias="DEEPSEEK_API_KEY")  # DeepSeek API key
    nvidia_api_key: Optional[str] = Field(default=None, validation_alias="NVIDIA_API_KEY")  # NVIDIA API key (NIM)

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
    memory_markdown_sync_enabled: bool = True
    memory_markdown_dir: Optional[Path] = None
    workflows_dir: Optional[Path] = None
    obsidian_vault_dir: Optional[Path] = None
    memory_markdown_sync_interval_seconds: float = Field(60.0, ge=5.0, le=3600.0)
    memory_markdown_chunk_lines: int = Field(28, ge=4, le=200)

    # Finance Watchlist + Briefs (read-only analysis)
    finance_watchlist_path: Optional[Path] = None
    finance_brief_dir: Optional[Path] = None
    finance_portfolio_store_path: Optional[Path] = None
    finance_receipts_dir: Optional[Path] = None
    finance_daily_brief_time: str = "08:00"
    finance_asset_focus: str = "both"  # crypto | stocks | both
    finance_regions: str = "us,india"
    finance_max_candidates_per_day: int = Field(3, ge=1, le=10)
    finance_auto_capture_interest: bool = True
    finance_auto_schedule_pulse: bool = True
    finance_rebalance_max_single_position_pct: float = Field(40.0, ge=15.0, le=90.0)
    memory_markdown_max_chunk_chars: int = Field(2400, ge=400, le=20000)
    memory_lifecycle_enabled: bool = True
    memory_lifecycle_interval_hours: float = Field(6.0, ge=0.5, le=168.0)
    memory_migrate_chroma: bool = False
    memory_decay_days: int = Field(90, ge=7, le=3650)

    # Image evidence -> memory (image RAG)
    # When enabled, screenshots produced as run evidence can be summarized/OCR'd (via vision)
    # and stored into HybridMemory so they become searchable like normal text memories.
    memory_image_ingest_enabled: bool = True
    memory_image_ingest_allow_cloud_vision: bool = True
    memory_image_ingest_allow_ollama_vision: bool = False
    memory_image_ingest_max_chars: int = Field(1800, ge=200, le=20000)
    memory_image_ingest_max_bytes: int = Field(8 * 1024 * 1024, ge=50_000, le=200 * 1024 * 1024)
    memory_image_ingest_max_per_run: int = Field(40, ge=1, le=1000)
    rag_require_citations: bool = True
    rag_min_confidence: float = Field(0.35, ge=0.0, le=1.0)
    rag_min_sources_contested: int = Field(2, ge=0, le=10)
    rag_contested_keywords: List[str] = Field(default_factory=list)
    rag_fallback_on_low_confidence: bool = True
    training_log_enabled: bool = True  # Enable JSONL training data logging
    training_auto_approve: bool = False  # DISABLED: Manual review required for safety
    training_selective_auto_approve: bool = True
    training_auto_approve_max_risk: str = "medium"  # none | low | medium | high | critical
    training_auto_approve_rating: int = Field(4, ge=1, le=5)
    training_log_path: Optional[Path] = None
    training_exports_dir: Optional[Path] = None
    training_style_tags: List[str] = Field(default_factory=lambda: ["style", "behavior", "tone", "persona"])
    training_fact_tags: List[str] = Field(default_factory=lambda: ["facts", "knowledge", "source"])
    task_history_enabled: bool = True
    history_event_store_path: Optional[Path] = None
    task_dossiers_dir: Optional[Path] = None
    task_history_index_path: Optional[Path] = None

    # Learning + Evolution
    learning_enabled: bool = True
    learning_auto_save: bool = True
    learning_train_enabled: bool = True
    learning_export_format: str = "chat"  # chat | instruction
    learning_weekly_enabled: bool = True
    learning_schedule_days: int = Field(14, ge=1, le=365)
    learning_weekly_day: int = Field(6, ge=0, le=6)  # 0=Mon ... 6=Sun
    learning_weekly_hour: int = Field(2, ge=0, le=23)
    learning_weekly_min_events: int = Field(10, ge=1, le=10000)
    learning_require_idle: bool = True
    learning_require_night_window: bool = True
    learning_idle_min_seconds: int = Field(10 * 60, ge=0, le=24 * 3600)
    learning_idle_max_cpu_percent: int = Field(30, ge=1, le=100)
    learning_idle_max_gpu_util_percent: int = Field(25, ge=1, le=100)
    learning_train_command: Optional[str] = None
    learning_train_timeout_seconds: int = Field(3600, ge=60, le=86400)
    learning_base_model_id: str = "Qwen/Qwen2.5-1.5B-Instruct"
    learning_adapter_dir: Optional[Path] = None
    learning_activation_requires_approval: bool = True
    learning_auto_activate_adapter: bool = False
    learning_pending_activation_path: Optional[Path] = None
    learning_activation_require_phase29_gate: bool = False
    learning_phase29_reports_dir: Optional[Path] = None
    learning_phase29_gate_max_age_hours: int = Field(168, ge=1, le=24 * 365)
    learning_phase29_gate_file_prefix: str = "phase29_autonomy_integration_gate_"
    learning_use_finetuned_model: bool = True
    persona_mode_enabled: bool = True
    persona_default_name: str = "default"
    persona_registry_path: Optional[Path] = None
    learning_train_max_steps: int = Field(80, ge=10, le=10000)
    learning_train_max_seq_len: int = Field(1024, ge=256, le=4096)
    learning_train_grad_accum: int = Field(8, ge=1, le=128)
    learning_active_cooldown_seconds: int = Field(300, ge=10, le=86400)
    learning_active_max_cpu_percent: int = Field(50, ge=1, le=100)
    learning_auto_web_on_gap: bool = True
    learning_auto_propose_skill_on_gap: bool = True
    # Phase 22: curiosity engine + scheduled learning loops
    curiosity_enabled: bool = True
    curiosity_daily_enabled: bool = True
    curiosity_daily_hour: int = Field(7, ge=0, le=23)
    curiosity_daily_categories: List[str] = Field(default_factory=lambda: ["tech", "finance", "healthcare"])
    curiosity_process_telegram_inbox: bool = True
    curiosity_model_catalog_refresh: bool = True
    curiosity_state_path: Optional[Path] = None
    curiosity_runs_dir: Optional[Path] = None
    code_interpreter_max_attempts: int = Field(3, ge=1, le=8)
    code_interpreter_timeout_seconds: int = Field(30, ge=5, le=300)

    # Git Context Controller (GCC-style memory scaffolding)
    gcc_enabled: bool = True
    gcc_auto_log: bool = True
    gcc_auto_commit: bool = True
    gcc_auto_commit_every: int = Field(25, ge=1, le=10000)
    gcc_root_dir: Optional[Path] = None
    gcc_default_goal: str = "Long-horizon execution with persistent, navigable context"

    # Evaluation gates
    eval_gate_enabled: bool = False
    eval_min_score: float = Field(0.8, ge=0.0, le=1.0)
    eval_cases_path: Optional[Path] = None
    reliability_gate_enabled: bool = False
    reliability_gate_interval_seconds: float = Field(300.0, ge=30.0, le=86400.0)
    metrics_gate_enabled: bool = False
    metrics_gate_min_requests: int = Field(20, ge=1, le=100000)
    metrics_gate_error_rate_max: float = Field(0.05, ge=0.0, le=1.0)
    metrics_gate_total_p95_ms: float = Field(5000.0, ge=0.0, le=600000.0)
    metrics_gate_total_avg_ms: float = Field(2000.0, ge=0.0, le=600000.0)

    # Curated library (Chintus_Library)
    library_root_dir: Optional[Path] = None
    library_require_sources: bool = True
    library_min_sources: int = Field(1, ge=0, le=10)
    library_allow_unreviewed: bool = False
    
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
    gateway_version: str = "1.0.0"
    gateway_remote_ip_allowlist: List[str] = Field(default_factory=list)
    gateway_untrusted_channels: List[str] = Field(
        default_factory=lambda: ["telegram", "discord", "slack", "whatsapp", "relay", "remote", "api"]
    )
    gateway_untrusted_group_denylist: List[str] = Field(
        default_factory=lambda: ["runtime", "browser", "mcp"]
    )
    gateway_audit_history_limit: int = Field(300, ge=50, le=5000)
    gateway_ops_rate_limit_per_minute: int = Field(60, ge=5, le=600)
    gateway_ops_approval_rate_limit_per_minute: int = Field(30, ge=1, le=300)
    gateway_approval_payload_ttl_seconds: int = Field(600, ge=60, le=3600)
    gateway_http_enabled: bool = False
    gateway_http_host: str = "127.0.0.1"
    gateway_http_port: int = 18889
    gateway_http_auth_token: Optional[str] = None

    # Skills (Phase 3)
    skills_enabled: bool = True
    skills_allow_shell: bool = False
    skills_use_docker: bool = False
    skills_docker_image: str = "python:3.11-slim"
    skills_docker_network_mode: str = "none"
    skills_docker_workdir: str = "/app"
    skills_require_approval: bool = True
    skills_allowlist: Optional[str] = None  # Comma-separated skill name patterns
    skills_denylist: Optional[str] = None  # Comma-separated skill name patterns
    skills_dir: Optional[Path] = None  # Workspace skills (project root)
    skills_user_dir: Optional[Path] = None  # User-level skills (~/.chintu/skills)
    skills_bundled_dir: Optional[Path] = None  # Bundled skills shipped with app
    skills_learned_dir: Optional[Path] = None  # Learned skills (active learning)
    skills_proposals_dir: Optional[Path] = None  # Pending skill proposals (awaiting approval)
    skills_test_enabled: bool = True
    skills_test_timeout_seconds: int = Field(20, ge=5, le=600)
    skills_watch_enabled: bool = True
    skills_watch_interval_seconds: int = Field(5, ge=1, le=120)
    skills_autogeneralize_enabled: bool = True
    skills_generalization_enforced: bool = True
    skills_generalization_similarity_threshold: float = Field(0.78, ge=0.5, le=1.0)
    # Skill/plugin trust + supply-chain controls (Phase 25)
    skills_supply_chain_enforced: bool = True
    skills_trusted_source_labels: List[str] = Field(default_factory=lambda: ["bundled", "learned", "workspace"])
    skills_third_party_allowlist: List[str] = Field(default_factory=list)
    skills_third_party_require_provenance: bool = True
    skills_third_party_require_approval: bool = True
    skills_untrusted_force_sandbox: bool = True
    skills_block_postinstall_scripts: bool = True
    skills_supply_chain_receipts_dir: Optional[Path] = None

    # Channel policies (Phase 4)
    channel_pairing_enabled: bool = False
    resource_protection_enabled: bool = True  # Auto-route to cloud if GPU is under high load
    channel_allowlist_path: Optional[Path] = None
    telegram_dm_policy: str = "pairing"  # pairing | open
    orchestrator_db_path: Optional[Path] = None

    # System control arbitration
    system_control_lock_timeout_seconds: float = Field(2.0, ge=0.1, le=30.0)

    # Coding agent change control
    coding_agent_change_log_enabled: bool = True
    coding_agent_change_log_dir: Optional[Path] = None
    coding_agent_auto_commit: bool = False
    coding_agent_commit_message: str = "chintu: {file} {issue}"
    coding_agent_self_update_enabled: bool = True
    coding_agent_self_update_default_tests: str = "pytest -q"

    # Audit logging
    audit_enabled: bool = True
    audit_log_path: Optional[Path] = None
    
    # Paths
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".chintu")
    models_dir: Optional[Path] = None
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        fast_init = bool(os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules)
        if fast_init:
            apply_fast_defaults(self)
            return
        initialize_runtime_paths(self)

    def _apply_fast_defaults(self) -> None:
        """Apply defaults without filesystem writes (used in tests)."""
        apply_fast_defaults(self)

    def _apply_env_overrides(self) -> None:
        """Apply lightweight env overrides for CHINTU_* keys."""
        prefix = "CHINTU_"
        for env_key, env_val in os.environ.items():
            if not env_key.startswith(prefix):
                continue
            field_name = env_key[len(prefix):].lower()
            if not hasattr(self, field_name):
                continue
            current = getattr(self, field_name)
            try:
                if isinstance(current, bool):
                    setattr(self, field_name, env_val.strip().lower() in ("1", "true", "yes", "on"))
                elif isinstance(current, int):
                    setattr(self, field_name, int(env_val))
                elif isinstance(current, float):
                    setattr(self, field_name, float(env_val))
                elif isinstance(current, Path):
                    setattr(self, field_name, Path(env_val))
                else:
                    setattr(self, field_name, env_val)
            except Exception:
                setattr(self, field_name, env_val)


# Global config instance
_config: Optional[Config] = None
_config_loading = False  # Prevent recursive loading


def get_config() -> Config:
    """Get or create the global configuration instance."""
    global _config, _config_loading
    if _config is None and not _config_loading:
        _config_loading = True
        try:
            test_env = bool(os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules)
            # Load non-secret integration settings from ~/.chintu so BaseSettings can pick them up.
            # Secrets (passwords/API keys) are loaded via IdentityVault below.
            if not test_env:
                try:
                    from chintu_backend.integrations.integration_store import (
                        load_integrations,
                        get_email_imap_config,
                        get_jira_config,
                    )

                    integrations = load_integrations()
                    email_cfg = get_email_imap_config(integrations) if isinstance(integrations, dict) else None
                    jira_cfg = get_jira_config(integrations) if isinstance(integrations, dict) else None
                    if email_cfg:
                        os.environ.setdefault("CHINTU_EMAIL_IMAP_HOST", str(email_cfg.host))
                        os.environ.setdefault("CHINTU_EMAIL_IMAP_PORT", str(int(email_cfg.port)))
                        if email_cfg.user:
                            os.environ.setdefault("CHINTU_EMAIL_IMAP_USER", str(email_cfg.user))
                        if email_cfg.folder:
                            os.environ.setdefault("CHINTU_EMAIL_IMAP_FOLDER", str(email_cfg.folder))
                    if jira_cfg:
                        os.environ.setdefault("CHINTU_JIRA_BASE_URL", str(jira_cfg.base_url))
                        os.environ.setdefault("CHINTU_JIRA_EMAIL", str(jira_cfg.email))
                        os.environ.setdefault("CHINTU_JIRA_PROJECT_KEY", str(jira_cfg.project_key))
                        if jira_cfg.issue_type:
                            os.environ.setdefault("CHINTU_JIRA_ISSUE_TYPE", str(jira_cfg.issue_type))
                except Exception:
                    pass
            # Audit Fix: Load credentials from Identity Vault before Config init
            # This ensures keys saved securely are available to the app as environment variables
            if not test_env:
                try:
                    from ..security import get_identity_vault
                    vault = get_identity_vault()
                    if vault.available:
                        vault_map = [
                            ("groq", "api_key", "GROQ_API_KEY"),
                            ("gemini", "api_key", "GOOGLE_AI_KEY"),
                            ("deepseek", "api_key", "DEEPSEEK_API_KEY"),
                            ("nvidia", "api_key", "NVIDIA_API_KEY"),
                            ("email", "imap_password", "CHINTU_EMAIL_IMAP_PASSWORD"),
                            ("openai", "api_key", "OPENAI_API_KEY"),
                            ("github", "api_key", "GITHUB_TOKEN"),
                            ("notion", "api_key", "NOTION_TOKEN"),
                            ("hass_url", "url", "HASS_URL"),
                            ("hass_token", "api_key", "HASS_TOKEN"),
                            ("google_client_id", "api_key", "GOOGLE_CLIENT_ID"),
                            ("google_client_secret", "api_key", "GOOGLE_CLIENT_SECRET"),
                            ("telegram", "bot_token", "TELEGRAM_BOT_TOKEN"),
                            ("jira", "api_token", "CHINTU_JIRA_API_TOKEN"),
                        ]
                        
                        for site, username, env_var in vault_map:
                            if env_var in os.environ:
                                continue
                            secret = vault.get_secret(site, username)
                            if secret:
                                os.environ[env_var] = secret
                except Exception as e:
                    # Don't fail startup if vault is broken, just log to stderr (logger might not be ready)
                    print(f"Warning: Failed to load credentials from identity vault: {e}")

            if test_env:
                try:
                    _config = Config.model_construct()
                except Exception:
                    _config = Config.construct()
                _config._apply_fast_defaults()
                _config._apply_env_overrides()
            else:
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
        'nvidia_api_key': ('NVIDIA_API_KEY', None),
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
