"""
Core Application Module for Chintu AI.
Orchestrates audio, vision, LLM, and gateway components.
"""

import asyncio
import logging
import signal
import sys
import threading
import re
import os
import time
import warnings
from typing import Optional
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("chintu")

class ChintuAssistant:
    """Main Chintu Assistant class that orchestrates all components."""
    
    def __init__(self):
        from chintu_backend.core import (
            get_config, get_event_bus, get_state_manager,
            CommandHandler, WebSocketServer, EventType, AssistantState
        )
        from chintu_backend.audio import AudioCapture, WakeWordDetector, SpeechToText
        from chintu_backend.audio import WakeWordTrainer
        from chintu_backend.vision import HandTracker, GestureRecognizer

        from chintu_backend.brain.llm import OllamaClient
        from chintu_backend.automation.scheduled_tasks import get_scheduler
        from chintu_backend.automation.parallel_executor import get_parallel_executor
        
        self.config = get_config()
        if self.config.structured_logging:
            try:
                from chintu_backend.core.logging_config import setup_json_logging
                level = getattr(logging, self.config.log_level.upper(), logging.INFO)
                setup_json_logging(level=level, log_file=self.config.structured_log_file)
            except Exception as e:
                logger.warning(f"Failed to configure structured logging: {e}")
        self.event_bus = get_event_bus()
        self.state_manager = get_state_manager()
        
        # Initialize system integrator (platform, device registry, error reporting, health monitoring)
        try:
            from chintu_backend.core.system_integrator import get_system_integrator
            self.system_integrator = get_system_integrator()
            init_status = self.system_integrator.initialize()
            logger.info(f"System integrator initialized: {init_status}")
            
            # Log status message
            status_msg = self.system_integrator.get_status_message()
            safe_status = status_msg.encode("ascii", errors="replace").decode("ascii")
            logger.info(f"\n{safe_status}")
            
            # Report any initialization errors
            if init_status.get("errors"):
                from chintu_backend.core.error_reporter import ErrorSeverity, report_error
                for error_msg in init_status["errors"]:
                    try:
                        report_error(
                            Exception(error_msg),
                            severity=ErrorSeverity.WARNING,
                            component="system_integrator",
                            user_message=f"Some features may be unavailable: {error_msg}",
                        )
                    except Exception:
                        pass  # Degrade gracefully
        except Exception as e:
            logger.error(f"Failed to initialize system integrator: {e}", exc_info=True)
            # Continue without system integrator - graceful degradation
            self.system_integrator = None

        # Run v5.1 startup health checks
        self._run_startup_health_checks()

        # Wake word cooldown tracking (used after empty transcripts)
        self._wake_cooldown_until = 0.0

        # Conversation mode tracking
        self._in_conversation = False
        self._conversation_retries = 0
        self._max_conversation_retries = 2  # Retry listening 2x in conversation mode

        # Initialize components
        logger.info("Initializing Chintu Assistant...")
        
        # Audio components
        self.audio_capture = AudioCapture(
            sample_rate=self.config.audio_sample_rate,
            channels=self.config.audio_channels,
            chunk_size=self.config.audio_chunk_size,
        )
        
        # Wake word detector - use process-based for high priority (ChatGPT recommendation)
        self.wake_word_process = None
        if self.config.wake_word_use_process:
            try:
                from chintu_backend.audio.wake_word_process import WakeWordProcessWorker
                self.wake_word_process = WakeWordProcessWorker(
                    wake_word=self.config.wake_word,
                    sensitivity=self.config.wake_word_sensitivity,
                    sample_rate=self.config.audio_sample_rate,
                    model_path=self.config.wake_word_model_path,
                    base_model=self.config.wake_word_base_model,
                )
                logger.info("Using PROCESS-based wake word detector (high priority)")
            except Exception as e:
                logger.warning(f"Process-based wake word failed, using thread-based: {e}")
                self.wake_word_process = None
        
        # Thread-based wake word (fallback or primary if process disabled)
        self.wake_word = WakeWordDetector(
            wake_word=self.config.wake_word,
            sensitivity=self.config.wake_word_sensitivity,
            sample_rate=self.config.audio_sample_rate,
            model_path=self.config.wake_word_model_path,
            base_model=self.config.wake_word_base_model,
            backend=self.config.wake_word_backend,
            verifier_path=str(self.config.wake_word_verifier_path)
            if self.config.wake_word_verifier_path
            else None,
            verifier_threshold=self.config.wake_word_verifier_threshold,
            match_threshold=self.config.wake_word_match_threshold,
            require_prefix=self.config.wake_word_require_prefix,
            stt_model_name=self.config.wake_word_stt_model,
            cooldown_seconds=self.config.wake_word_cooldown_seconds,
            activation_frames=self.config.wake_word_activation_frames,
            confirm_with_stt=self.config.wake_word_confirm_with_stt,
            confirm_window_seconds=self.config.wake_word_confirm_window_seconds,
            stt_confidence_threshold=self.config.wake_word_stt_confidence_threshold,
            noise_mode=self.config.wake_word_noise_mode,
            min_word_count=self.config.wake_word_min_word_count,
        )

        self.wake_word_trainer = WakeWordTrainer(
            audio_capture=self.audio_capture,
            config=self.config,
        )
        
        self.stt = SpeechToText(
            model_name=self.config.whisper_model,
            device=self.config.whisper_device,
            language=self.config.whisper_language,
            silence_threshold=self.config.stt_silence_threshold,
            silence_duration=self.config.stt_silence_duration,
            vad_filter=self.config.stt_vad_filter,
            partial_interval=self.config.stt_partial_interval,
            partial_window_seconds=self.config.stt_partial_window_seconds,
            initial_prompt=self.config.stt_initial_prompt,
            timeout_seconds=self.config.stt_timeout_seconds,
            min_listen_seconds=self.config.stt_min_listen_seconds,
            min_confidence=self.config.stt_min_confidence,
            speech_frames_required=self.config.stt_speech_frames_required,
            compute_type=self.config.stt_compute_type,
            cpu_threads=self.config.stt_cpu_threads,
            num_workers=self.config.stt_num_workers,
            beam_size=self.config.stt_beam_size,
            best_of=self.config.stt_best_of,
            partial_beam_size=self.config.stt_partial_beam_size,
        )
        
        # Vision components
        self.hand_tracker = HandTracker(
            max_hands=self.config.gesture_max_hands,
            min_detection_confidence=self.config.gesture_confidence_threshold,
        )
        
        self.gesture_recognizer = GestureRecognizer()
        
        # LLM (with CPU-optimized settings)
        self.llm = OllamaClient(
            host=self.config.ollama_host,
            model=self.config.ollama_model,
            max_tokens=self.config.llm_max_tokens,
            temperature=self.config.llm_temperature,
            num_threads=getattr(self.config, 'llm_num_threads', None),
            num_ctx=getattr(self.config, 'llm_num_ctx', None),
            num_gpu=getattr(self.config, 'llm_num_gpu', -1),
        )
        
        # Command handling
        self.command_handler = CommandHandler(llm_client=self.llm)

        # Gateway (Phase 1) - optional JSON-RPC control plane
        self.gateway_server = None
        self.gateway_client = None
        if self.config.gateway_enabled:
            try:
                from chintu_backend.interfaces.gateway import GatewayServer, GatewayClient
                self.gateway_server = GatewayServer(
                    command_handler=self.command_handler,
                    host=self.config.gateway_host,
                    port=self.config.gateway_port,
                    auth_token=self.config.gateway_auth_token,
                )
                self.gateway_client = GatewayClient(
                    host=self.config.gateway_host,
                    port=self.config.gateway_port,
                    token=self.config.gateway_auth_token,
                )
                logger.info("Gateway server/client initialized")
            except Exception as e:
                logger.warning(f"Gateway init failed: {e}")
                self.gateway_server = None
                self.gateway_client = None

        # Optional headless gateway (Telegram) for remote control and alerts
        self.telegram_gateway = None
        try:
            from chintu_backend.io import get_telegram_gateway

            self.telegram_gateway = get_telegram_gateway(self.command_handler)
            ok, msg = self.telegram_gateway.start()
            logger.info(f"Telegram gateway: {msg}")
        except Exception as e:
            logger.warning(f"Telegram gateway not available: {e}")
        
        # WebSocket server for Flutter UI
        self.ws_server = WebSocketServer(
            host=self.config.websocket_host,
            port=self.config.websocket_port,
        )
        # Register globally for capability handlers to access
        from chintu_backend.core.websocket_server import set_ws_server
        set_ws_server(self.ws_server)

        self._greeting_spoken = False
        self._greeting_in_progress = False
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._setup_callbacks()
        self._setup_event_handlers()
        
        # Register interrupt handler for hard barge-in
        self._setup_interrupt_handler()
        
        # Initialize Automation
        self._init_automation()

    def _setup_interrupt_handler(self):
        """Setup hard interrupt handler for barge-in and stop commands."""
        from chintu_backend.core.interrupt_handler import get_interrupt_handler
        
        handler = get_interrupt_handler()
        
        # Register TTS kill callback
        if self.command_handler._tts:
            handler.register_tts_kill(self.command_handler._tts.stop_speaking)
            logger.info("Interrupt handler: TTS kill callback registered")
            
            # === DYNAMIC CONFIRMATION TOGGLE ===
            # Enable STT confirmation when TTS starts (prevent self-trigger)
            # Disable STT confirmation when TTS stops (instant re-trigger)
            
            original_on_start = self.command_handler._tts._on_start
            original_on_done = self.command_handler._tts._on_done
            
            def on_tts_start():
                if self.wake_word:
                    self.wake_word.set_confirm_with_stt(True)
                if original_on_start:
                    original_on_start()
            
            def on_tts_done():
                if self.wake_word:
                    self.wake_word.set_confirm_with_stt(False)
                # Clear speaking text when done
                self.state_manager.set_speaking_text("", is_complete=True)
                if original_on_done:
                    original_on_done()

            def on_speaking_text(text: str, is_complete: bool):
                """Live caption callback - broadcasts spoken text to UI."""
                self.state_manager.set_speaking_text(text, is_complete)

            # We need to set these callbacks safely
            self.command_handler._tts.set_callbacks(
                on_start=on_tts_start,
                on_done=on_tts_done,
                on_speaking_text=on_speaking_text
            )
            logger.info("Dynamic wake word confirmation hooked to TTS events (with live captions)")
        
        # Register on-interrupt callback to update state
        def on_interrupt(interrupt_type):
            from chintu_backend.core import AssistantState
            logger.info(f"Interrupt received: {interrupt_type.value}")
            self.state_manager.set_assistant_state(AssistantState.IDLE)
            self.state_manager.set_transcript("", is_final=False)
            # Ensure confirmation is disabled on interrupt (since TTS stops)
            if self.wake_word:
                self.wake_word.set_confirm_with_stt(False)
        
        handler.register_on_interrupt(on_interrupt)
        logger.info("Interrupt handler configured for hard barge-in")
        
        # === AUDIO BARGE-IN (FULL DUPLEX) ===
        # If enabled, hook the AudioLevelDetector to the TTS stop functionality
        if self.config.enable_barge_in and self.audio_capture and self.audio_capture.barge_in_detector:
             # Stop TTS when user speaks loudly enough
             self.audio_capture.barge_in_detector.set_callback(self.command_handler.stop_speaking)
             logger.info("Full Duplex Barge-In enabled: User speech stops TTS.")

    def _init_automation(self):
        """Initialize automation components."""
        from chintu_backend.automation.scheduled_tasks import get_scheduler
        from chintu_backend.automation.parallel_executor import get_parallel_executor
        
        # Connect Scheduler to CommandHandler
        scheduler = get_scheduler()
        scheduler.set_callback(self.command_handler.handle)
        logger.info("Scheduler initialized and connected to CommandHandler")
        
        # Connect ParallelExecutor to CommandHandler
        executor = get_parallel_executor()
        executor.set_command_handler(self.command_handler.handle)
        logger.info("ParallelExecutor initialized and connected to CommandHandler")

        # Initialize Proactivity Engine (Phase 5)
        try:
            from chintu_backend.proactivity.manager import get_proactivity_manager
            self.proactivity_manager = get_proactivity_manager()
            self.proactivity_manager.start()
            logger.info("Proactivity Engine initialized and started")
        except Exception as e:
            logger.warning(f"Failed to start Proactivity Engine: {e}")
            self.proactivity_manager = None

    def _initialize_all_feature_statuses(self):
        """Initialize all feature statuses based on actual availability."""
        sm = self.state_manager
        
        # Core audio features - check actual audio capture status
        audio_available = self.audio_capture.is_running
        if audio_available:
            sm.update_feature("wake_word", enabled=True, status="active")
            sm.update_feature("voice_commands", enabled=True, status="active")
            sm.update_feature("audio", enabled=True, status="active")
            sm.update_feature("microphone", enabled=True, status="active")
        else:
            sm.update_feature("wake_word", enabled=False, status="inactive", error="No microphone available")
            sm.update_feature("voice_commands", enabled=False, status="inactive", error="No microphone available")
            sm.update_feature("audio", enabled=False, status="inactive", error="No microphone available")
            sm.update_feature("microphone", enabled=False, status="inactive", error="No microphone available")
        sm.update_feature("speaker", enabled=True, status="active")
        
        # Hand gestures - starts inactive until explicitly enabled
        sm.update_feature("hand_gestures", enabled=True, status="inactive")
        
        # App control - available on Windows
        sm.update_feature("app_control", enabled=True, status="active")
        
        # Job search - check if capability is registered
        try:
            from chintu_backend.core.capabilities import get_registry
            registry = get_registry()
            if registry.get("job_search"):
                sm.update_feature("job_search", enabled=True, status="active")
            else:
                sm.update_feature("job_search", enabled=True, status="inactive")
        except Exception:
            sm.update_feature("job_search", enabled=True, status="inactive")
        
        # LLM integration - check Ollama connectivity
        try:
            import requests
            resp = requests.get(f"{self.config.ollama_host}/api/tags", timeout=2)
            if resp.status_code == 200:
                sm.update_feature("llm_integration", enabled=True, status="active")
                sm.update_feature("llm", enabled=True, status="active")
            else:
                sm.update_feature("llm_integration", enabled=True, status="inactive")
                sm.update_feature("llm", enabled=True, status="inactive")
        except Exception:
            sm.update_feature("llm_integration", enabled=True, status="inactive")
            sm.update_feature("llm", enabled=True, status="inactive")
        
        # Markdown memory sync - check if command handler has it
        if hasattr(self.command_handler, 'markdown_sync') and self.command_handler.markdown_sync:
            sm.update_feature("memory_markdown_sync", enabled=True, status="active")
        else:
            sm.update_feature("memory_markdown_sync", enabled=True, status="inactive")
        
        # MCP Tools - check if available
        try:
            from chintu_backend.interfaces.mcp import get_mcp_manager
            mcp = get_mcp_manager()
            if mcp and getattr(mcp, '_servers', None):
                sm.update_feature("mcp", enabled=True, status="active")
            else:
                sm.update_feature("mcp", enabled=True, status="inactive")
        except Exception:
            sm.update_feature("mcp", enabled=True, status="inactive")
        
        # Thumbnail generator - check Pillow
        try:
            from PIL import Image
            sm.update_feature("thumbnail", enabled=True, status="active")
        except ImportError:
            sm.update_feature("thumbnail", enabled=False, status="inactive", error="Pillow not installed")
        
        # Email reader - check if capability exists
        try:
            from chintu_backend.core.capabilities import get_registry
            registry = get_registry()
            if registry.get("read_email") or registry.get("email_reader"):
                sm.update_feature("email_reader", enabled=True, status="active")
            else:
                sm.update_feature("email_reader", enabled=True, status="inactive")
        except Exception:
            sm.update_feature("email_reader", enabled=True, status="inactive")
        
        # Identity vault - check if it can initialize
        try:
            from chintu_backend.security.identity_vault import get_identity_vault
            vault = get_identity_vault()
            if vault.enabled:
                sm.update_feature("identity_vault", enabled=True, status="active")
            else:
                sm.update_feature("identity_vault", enabled=True, status="inactive")
        except Exception as e:
            sm.update_feature("identity_vault", enabled=True, status="error", error=str(e)[:100])
        
        # Telegram - check if gateway started
        if self.telegram_gateway:
            sm.update_feature("telegram", enabled=True, status="active")
        else:
            sm.update_feature("telegram", enabled=True, status="inactive")
        
        logger.info("Feature statuses initialized")

    def _run_startup_health_checks(self):
        """Run v5.1 startup health checks for critical systems."""
        from chintu_backend.core.config import get_config

        config = get_config()
        logger.info("Running v5.1 startup health checks...")
        health_status = {"docker": None, "vram": None, "models": None, "browser": None}

        # 1. Docker Health Check
        docker_checks_enabled = (
            config.docker_healthcheck_enabled
            or config.mcp_docker_enabled
            or config.skills_use_docker
        )
        if not docker_checks_enabled:
            logger.info("[~] Docker check skipped (disabled)")
            health_status["docker"] = {"healthy": True, "message": "Docker check skipped"}
            try:
                import shutil
                import subprocess
                from chintu_backend.core.state import get_state_manager
                sm = get_state_manager()
                if shutil.which("docker"):
                    result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=2)
                    if result.returncode == 0:
                        sm.update_feature("docker", enabled=True, status="active", error=None)
                    else:
                        sm.update_feature("docker", enabled=False, status="inactive", error="Docker not running")
                else:
                    sm.update_feature("docker", enabled=False, status="inactive", error="Docker not installed")
            except Exception:
                pass
        else:
            try:
                from chintu_backend.sandbox.docker_sandbox import DockerSandbox
                healthy, msg = DockerSandbox.health_check()
                if not healthy and ("Docker Desktop" in msg or "daemon is not running" in msg):
                    logger.info("Docker not running. Attempting auto-start (non-blocking)...")
                    try:
                        docker_desktop_path = "C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe"
                        if Path(docker_desktop_path).exists():
                            import subprocess
                            subprocess.Popen([docker_desktop_path], creationflags=subprocess.DETACHED_PROCESS | 0x00000008)
                    except Exception as e:
                        logger.warning(f"Failed to auto-start Docker: {e}")

                health_status["docker"] = {"healthy": healthy, "message": msg}
                from chintu_backend.core.state import get_state_manager
                sm = get_state_manager()
                sm.update_feature("docker", enabled=healthy, status="active" if healthy else "inactive", error=None if healthy else msg)
            except Exception as e:
                logger.warning(f"[X] Docker check failed: {e}")
                health_status["docker"] = {"healthy": False, "message": str(e)}

        # 2. VRAM Monitoring
        try:
            from chintu_backend.swarm.vram_monitor import get_vram_monitor
            vram = get_vram_monitor()
            status = vram.get_status()
            health_status["vram"] = {"healthy": True, "total_mb": status.total_mb, "used_mb": status.used_mb, "pressure": status.pressure.value}
            logger.info(f"[OK] VRAM: {status.used_mb}MB/{status.total_mb}MB ({status.pressure.value} pressure)")
        except Exception as e:
            logger.warning(f"[X] VRAM monitoring unavailable: {e}")
            health_status["vram"] = {"healthy": False, "message": str(e)}

        # 3. Model Roster Validation
        try:
            from chintu_backend.swarm.model_validator import get_model_validator
            validator = get_model_validator()
            validation = validator.validate()
            health_status["models"] = {"healthy": validation.all_available, "missing_count": validation.missing_count, "message": validation.message}
            logger.info(f"[OK] Models: {validation.message}" if validation.all_available else f"[!] Models: {validation.message}")
        except Exception as e:
            logger.warning(f"[X] Model validation failed: {e}")
            health_status["models"] = {"healthy": False, "message": str(e)}

        # 4. Browser Fallback Check
        if config.browser_fallback_enabled:
            try:
                from chintu_backend.automation.browser.browser_fallback import BrowserFallbackAgent, PLAYWRIGHT_AVAILABLE
                if PLAYWRIGHT_AVAILABLE:
                    agent = BrowserFallbackAgent()
                    healthy, msg = agent.health_check()
                    health_status["browser"] = {"healthy": True, "available": healthy, "message": msg}
                    from chintu_backend.core.state import get_state_manager
                    sm = get_state_manager()
                    sm.update_feature("browser", enabled=healthy, status="active" if healthy else "inactive", error=None if healthy else msg)
                else:
                    health_status["browser"] = {"healthy": True, "available": False, "message": "Playwright not installed"}
            except Exception as e:
                health_status["browser"] = {"healthy": True, "available": False, "message": str(e)}

        self._health_status = health_status
        logger.info("Startup health checks complete")

    def _schedule_coroutine(self, coro):
        """Schedule a coroutine on the assistant loop (thread-safe)."""
        if not self._loop or not self._loop.is_running():
            return
        try:
            if asyncio.get_running_loop() == self._loop:
                asyncio.create_task(coro)
            else:
                asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError:
            asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _handle_wake_word_detected(self, source: str = "audio"):
        from chintu_backend.core import AssistantState
        if self._greeting_in_progress and source == "audio":
            return
        
        if self.command_handler._tts and self.command_handler._tts.is_speaking:
            self.command_handler.stop_speaking()
            self.state_manager.set_assistant_state(AssistantState.LISTENING)

        if self.stt.is_listening:
            return
        
        was_speaking = self.command_handler._tts and self.command_handler._tts.is_speaking
        if not was_speaking and time.time() < self._wake_cooldown_until:
            return
        
        logger.info(f"Wake word detected (source={source})")
        if self.ws_server:
            self.ws_server.bring_ui_to_front()
        
        self.state_manager.capture_window_snapshot()
        
        if not self.audio_capture.is_running:
            self.state_manager.set_assistant_state(AssistantState.IDLE)
            return
        
        self.state_manager.set_assistant_state(AssistantState.LISTENING)
        self.stt.start_listening()
        self._in_conversation = True
        self._conversation_retries = 0

    @staticmethod
    def _strip_wake_phrase(text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"^(hey|hi|hello)\s+chintu\b[, ]*", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    async def _process_transcript(self, text: str, source: str = "audio"):
        from chintu_backend.core import AssistantState
        text = self._strip_wake_phrase(text)
        text_lower = text.strip().lower()
        if text_lower in {"um", "uh", "erm", "hmm", "hm", "uhm", "umm", "urn", "uhh"}:
            if self.config.conversation_mode and self.audio_capture.is_running:
                self.stt.set_timeout(self.config.conversation_timeout_seconds)
                self.state_manager.set_assistant_state(AssistantState.LISTENING)
                self.state_manager.set_transcript("", is_final=False)
                self.stt.start_listening()
                return
            text = ""
        
        if not text:
            self._wake_cooldown_until = time.time() + self.config.wake_word_cooldown_seconds
            self.state_manager.set_assistant_state(AssistantState.IDLE)
            self.state_manager.set_transcript("", is_final=False)
            return

        logger.info(f"Transcript ({source}): {text}")
        self.state_manager.set_transcript(text, is_final=True)
        self.state_manager.set_assistant_state(AssistantState.PROCESSING)

        # Check for hand gesture toggle commands
        if any(phrase in text_lower for phrase in ["turn on hand gesture", "enable hand gesture", "start hand gesture"]):
            await self._toggle_hand_gestures(True)
            return
        elif any(phrase in text_lower for phrase in ["turn off hand gesture", "disable hand gesture", "stop hand gesture"]):
            await self._toggle_hand_gestures(False)
            return

        await asyncio.to_thread(self.command_handler.handle, text, source)

        if self.config.conversation_mode:
            if self.command_handler._tts:
                start_wait = time.monotonic()
                while self.command_handler._tts.is_speaking:
                    if time.monotonic() - start_wait > 10.0:
                        self.command_handler.stop_speaking()
                        break
                    await asyncio.sleep(0.1)
            
            self._in_conversation = True
            self._conversation_retries = 0
            
            if self.audio_capture.is_running:
                self.stt.set_timeout(self.config.conversation_timeout_seconds)
                self.state_manager.set_assistant_state(AssistantState.LISTENING)
                self.state_manager.set_transcript("", is_final=False)
                self.stt.start_listening()
            else:
                self.state_manager.set_assistant_state(AssistantState.IDLE)
        else:
            if self.command_handler._tts and self.command_handler._tts.is_speaking:
                self.state_manager.set_assistant_state(AssistantState.SPEAKING)
            else:
                self.state_manager.set_assistant_state(AssistantState.IDLE)
            self.state_manager.set_transcript("", is_final=False)

    async def _startup_sequence(self):
        """Run sequential startup: Greet -> Listen."""
        from chintu_backend.core import AssistantState
        await self._speak_greeting()
        if self.config.auto_listen_on_connect:
            if self.audio_capture.is_running:
                self.state_manager.set_assistant_state(AssistantState.LISTENING)
                self.stt.start_listening()
            else:
                self.state_manager.set_assistant_state(AssistantState.IDLE)
        else:
            self.state_manager.set_assistant_state(AssistantState.IDLE)

    async def _speak_greeting(self):
        """Speak a personalized voice greeting."""
        from chintu_backend.core import AssistantState, smart_greeting as sg
        from chintu_backend.brain.memory.preferences import get_preference_manager

        if not self.config.tts_greeting_enabled: return
        
        user_name = None
        try:
            prefs = get_preference_manager()
            user_name = prefs.get("user_name")
        except Exception: pass
        
        greeting = sg.get_smart_greeting(user_name)
        logger.info(f"Greeting: '{greeting}'")
        self.state_manager.set_response(greeting, raw=greeting)

        self._greeting_in_progress = True
        try:
            self.state_manager.set_assistant_state(AssistantState.SPEAKING)
            await asyncio.to_thread(self.command_handler.speak, greeting, False, True, False)
            if self.command_handler._tts:
                await asyncio.to_thread(self.command_handler._tts.wait_until_done, 15.0)
        except Exception as e:
            logger.warning(f"Greeting failed: {e}")
        finally:
            self._greeting_in_progress = False

    async def _toggle_hand_gestures(self, enable: bool):
        from chintu_backend.core import AssistantState
        if enable:
            self.hand_tracker.start()
            self.state_manager.update_feature("hand_gestures", enabled=True, status="active")
            response = "Hand gesture control enabled."
        else:
            self.hand_tracker.stop()
            self.state_manager.update_feature("hand_gestures", enabled=True, status="inactive")
            response = "Hand gesture control disabled."
        
        await asyncio.to_thread(self.command_handler.speak, response)
        self.state_manager.set_assistant_state(AssistantState.IDLE)

    def _setup_callbacks(self):
        """Setup component callbacks."""
        from chintu_backend.core import AssistantState
        self.audio_capture.set_level_callback(lambda l: self.state_manager.update_audio_level(l))
        
        def on_audio_chunk(chunk):
            if not self.stt.is_listening:
                if self.wake_word_process: self.wake_word_process.process_audio(chunk)
                self.wake_word.process_audio(chunk)
            else:
                self.stt.process_audio(chunk)
        
        self.audio_capture.add_callback(on_audio_chunk)
        self.wake_word.set_wake_callback(lambda: self._handle_wake_word_detected(source="audio"))
        
        def on_transcript(text: str, is_final: bool):
            if not is_final: return
            if text:
                self._schedule_coroutine(self._process_transcript(text, source="audio"))
            elif self._in_conversation and self._conversation_retries < self._max_conversation_retries:
                self._conversation_retries += 1
                self.stt.start_listening()
            else:
                self._in_conversation = False
                self.state_manager.set_assistant_state(AssistantState.IDLE)

        self.stt.set_transcript_callback(on_transcript)
        self.stt.set_partial_callback(lambda t: self.state_manager.set_transcript(t, is_final=False) if t else None)
        
        def on_landmarks(hands):
            result = self.gesture_recognizer.process_landmarks(hands)
            if result:
                self.state_manager.set_hand_detected(True, result.gesture.value)
                from chintu_backend.vision.gesture_recognition import GestureType
                if result.gesture == GestureType.OPEN_PALM:
                    self._handle_wake_word_detected(source="gesture")
        
        self.hand_tracker.set_landmarks_callback(on_landmarks)
    
    def _setup_event_handlers(self):
        """Setup event bus handlers."""
        from chintu_backend.core import EventType, AssistantState

        self.event_bus.subscribe(EventType.WAKE_WORD_DETECTED, lambda e: self._handle_wake_word_detected(source=e.source))
        self.event_bus.subscribe(EventType.UI_CONNECTED, lambda e: self._schedule_coroutine(self._startup_sequence()) if not self._greeting_spoken else None)
        
        def on_ptt_start(e):
            if not self.stt.is_listening and self.audio_capture.is_running:
                self.state_manager.set_assistant_state(AssistantState.LISTENING)
                self.stt.start_listening()
        
        self.event_bus.subscribe(EventType.PUSH_TO_TALK_START, on_ptt_start)
        self.event_bus.subscribe(EventType.PUSH_TO_TALK_STOP, lambda e: self.stt.stop_listening() if self.stt.is_listening else None)

    async def start(self):
        """Start the assistant."""
        self._running = True
        self._loop = asyncio.get_running_loop()

        if self.gateway_server: await self.gateway_server.start()
        await self.ws_server.start()
        
        self.audio_capture.start()
        self.wake_word.start()

        if self.wake_word_process:
            self.wake_word_process.set_wake_callback(lambda: self._schedule_coroutine(asyncio.to_thread(self._handle_wake_word_detected, "process")))
            self.wake_word_process.start()
        
        asyncio.create_task(self.event_bus.process_queue())
        self._initialize_all_feature_statuses()
        logger.info("Chintu Assistant Ready.")

        while self._running: await asyncio.sleep(0.1)
    
    async def stop(self):
        """Stop the assistant."""
        self._running = False
        self.audio_capture.stop()
        self.wake_word.stop()
        if self.wake_word_process: self.wake_word_process.stop()
        self.hand_tracker.stop()
        self.event_bus.stop()
        await self.ws_server.stop()
        if self.gateway_server: await self.gateway_server.stop()
        logger.info("Chintu Assistant stopped.")


async def main():
    """Application entry point."""
    assistant = ChintuAssistant()
    
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(sig, lambda: asyncio.create_task(assistant.stop()))
        except NotImplementedError: pass
    
    try: await assistant.start()
    except KeyboardInterrupt: await assistant.stop()
    except Exception as e:
        logger.critical(f"Fatal: {e}", exc_info=True)
        await assistant.stop()
