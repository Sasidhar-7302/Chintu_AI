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
from collections import deque

logger = logging.getLogger("chintu")

class ChintuAssistant:
    """Main Chintu Assistant class that orchestrates all components."""
    
    def __init__(self):
        from chintu_backend.core import (
            get_config, get_event_bus, get_state_manager,
            CommandHandler, WebSocketServer, EventType, Event, AssistantState
        )
        from chintu_backend.audio import AudioCapture, WakeWordDetector, SpeechToText
        from chintu_backend.audio import WakeWordTrainer
        from chintu_backend.vision import HandTracker, GestureRecognizer

        from chintu_backend.brain.llm import OllamaClient
        from chintu_backend.core.scheduler import get_scheduler
        from chintu_backend.automation.parallel_executor import get_parallel_executor
        
        self.config = get_config()
        self.runtime_hardware_adapter = None
        self._hardware_adapt_task = None
        try:
            from chintu_backend.agents.agent_factory import ensure_templates
            ensure_templates()
        except Exception:
            pass
        # Auto-tune hardware settings based on detected CPU/GPU/VRAM
        if getattr(self.config, "hardware_auto_tune", False):
            try:
                from chintu_backend.core.hardware_optimizer import get_hardware_optimizer
                optimizer = get_hardware_optimizer()
                optimizer.optimize_config(self.config)
                if bool(getattr(self.config, "hardware_adapt_runtime_enabled", True)):
                    from chintu_backend.core.runtime_hardware_adapter import RuntimeHardwareAdapter

                    self.runtime_hardware_adapter = RuntimeHardwareAdapter(
                        config=self.config,
                        optimizer=optimizer,
                        on_applied=self._on_runtime_hardware_adapted,
                    )
            except Exception as e:
                logger.warning(f"Hardware auto-tune failed: {e}")
        if self.config.structured_logging:
            try:
                from chintu_backend.core.logging_config import setup_json_logging
                level = getattr(logging, self.config.log_level.upper(), logging.INFO)
                setup_json_logging(level=level, log_file=self.config.structured_log_file)
            except Exception as e:
                logger.warning(f"Failed to configure structured logging: {e}")
        self.event_bus = get_event_bus()
        self.state_manager = get_state_manager()
        if self.runtime_hardware_adapter:
            self.runtime_hardware_adapter.state_manager = self.state_manager
        try:
            from chintu_backend.canvas import get_canvas_manager

            self.canvas_manager = get_canvas_manager()
        except Exception:
            self.canvas_manager = None
        
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
        self._suppress_library_logs()

        # Wake word cooldown tracking (used after empty transcripts)
        self._wake_cooldown_until = 0.0

        # Conversation mode tracking
        self._in_conversation = False
        self._typing_active = False # New: Track user typing state
        self._conversation_retries = 0
        self._max_conversation_retries = 2  # Retry listening 2x in conversation mode
        self._audio_level_history = deque(maxlen=4000)
        self._stt_noise_calibrated = False

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
            reject_low_confidence_noise=self.config.stt_reject_low_confidence_noise,
            low_confidence_noise_word_limit=self.config.stt_low_confidence_noise_word_limit,
        )
        
        # Vision components
        self.hand_tracker = HandTracker(
            max_hands=self.config.gesture_max_hands,
            min_detection_confidence=self.config.gesture_confidence_threshold,
        )
        
        self.gesture_recognizer = GestureRecognizer()
        
        # LLM (prefer active fine-tuned adapter when available)
        self.llm = None
        try:
            from ..brain.llm.adapter_client import get_adapter_client

            self.llm = get_adapter_client()
        except Exception:
            self.llm = None

        if not self.llm:
            self.llm = OllamaClient(
                host=self.config.ollama_host,
                model=self.config.ollama_model,
                max_tokens=self.config.llm_max_tokens,
                temperature=self.config.llm_temperature,
                num_threads=getattr(self.config, 'llm_num_threads', None),
                num_ctx=getattr(self.config, 'llm_num_ctx', None),
                num_gpu=getattr(self.config, 'llm_num_gpu', -1),
                keep_alive=getattr(self.config, "ollama_keep_alive_seconds", None),
                think=getattr(self.config, "ollama_think", None),
            )

        # Best-effort model prewarm to reduce cold-start latency.
        self._start_prewarm_threads()
        
        # Command handling
        self.command_handler = CommandHandler(llm_client=self.llm)

        # Gateway (Phase 1) - Core Node Integration
        self.gateway_server_process = None
        self.core_node = None
        
        if self.config.gateway_enabled:
            try:
                # 1. Ensure Gateway Server is running
                self._ensure_gateway_running()
                
                # 2. Initialize Core Node SDK
                from chintu_backend.sdk.node import ChintuNode
                from chintu_backend.protocol.enums import Role
                
                self.core_node = ChintuNode(
                    role=Role.CORE,
                    device_id="core_main",
                    capabilities=["audio", "vision", "automation", "llm"],
                    gateway_url=f"ws://{self.config.gateway_host}:{self.config.gateway_port}"
                )
                
                # 3. Register Gateway Handlers
                @self.core_node.on("ui_action")
                async def handle_ui_action(data):
                    """Handle UI actions routed via Gateway."""
                    payload = data.get("payload", {}).get("data", {})
                    action_type = payload.get("action")

                    # Avoid logging user content / secrets (text_input, orchestrator inputs, etc).
                    try:
                        if action_type == "orchestrator_set_input":
                            logger.info(
                                "Gateway UI Action: %s (project_id=%s key=%s is_secret=%s)",
                                action_type,
                                payload.get("project_id"),
                                payload.get("key"),
                                bool(payload.get("is_secret")),
                            )
                        else:
                            logger.info("Gateway UI Action: %s", action_type)
                    except Exception:
                        logger.info("Gateway UI Action: %s", action_type)

                    if action_type == "text_input":
                        text = payload.get("text")
                        if text:
                            await self._process_transcript(text, source="ui_gateway")
                    elif action_type == "push_to_talk":
                        state = payload.get("state")
                        if state == "start":
                            await self.event_bus.publish(Event(type=EventType.PUSH_TO_TALK_START, source="ui_gateway"))
                        elif state == "stop":
                            await self.event_bus.publish(Event(type=EventType.PUSH_TO_TALK_STOP, source="ui_gateway"))
                    elif action_type == "wake_word_status_request":
                        await self.event_bus.publish(Event(type=EventType.WAKE_WORD_STATUS_REQUEST, source="ui_gateway"))
                    elif action_type == "wake_word_record_sample":
                        await self.event_bus.publish(
                            Event(
                                type=EventType.WAKE_WORD_RECORD_REQUEST,
                                data={
                                    "index": payload.get("index"),
                                    "kind": payload.get("kind", "positive"),
                                },
                                source="ui_gateway",
                            )
                        )
                    elif action_type == "wake_word_train":
                        await self.event_bus.publish(Event(type=EventType.WAKE_WORD_TRAIN_REQUEST, source="ui_gateway"))
                    elif action_type == "canvas_action":
                        try:
                            from chintu_backend.canvas import get_canvas_manager

                            manager = get_canvas_manager()
                            action = payload.get("canvas") or payload.get("canvas_action") or payload
                            if isinstance(action, dict):
                                manager.apply_action(action)
                        except Exception as exc:
                            logger.warning(f"Canvas action failed: {exc}")
                    elif action_type == "ui_ready":
                        try:
                            if self.canvas_manager:
                                self.canvas_manager.publish()
                        except Exception:
                            pass
                        # Send an initial orchestrator snapshot so the UI can render dashboards immediately.
                        try:
                            from chintu_backend.orchestrator import get_orchestrator_manager

                            snapshot = get_orchestrator_manager().get_overview(limit=50)
                            if self.core_node:
                                await self.core_node.emit("orchestrator_snapshot", snapshot)
                        except Exception as exc:
                            logger.debug(f"Failed to emit orchestrator snapshot: {exc}")
                    elif action_type == "a2ui_action":
                        await self.event_bus.publish(
                            Event(type=EventType.A2UI_ACTION, data=payload, source="ui_gateway")
                        )
                    elif action_type == "orchestrator_snapshot_request":
                        try:
                            from chintu_backend.orchestrator import get_orchestrator_manager

                            snapshot = get_orchestrator_manager().get_overview(limit=50)
                            if self.core_node:
                                await self.core_node.emit("orchestrator_snapshot", snapshot)
                        except Exception as exc:
                            logger.debug(f"Failed to emit orchestrator snapshot: {exc}")
                    elif action_type == "orchestrator_approve_step":
                        try:
                            from chintu_backend.orchestrator import get_orchestrator_manager

                            step_id = str(payload.get("step_id") or "").strip()
                            approve = bool(payload.get("approve", True))
                            if step_id:
                                get_orchestrator_manager().approve_step(step_id, approve=approve)
                            snapshot = get_orchestrator_manager().get_overview(limit=50)
                            if self.core_node:
                                await self.core_node.emit("orchestrator_snapshot", snapshot)
                        except Exception as exc:
                            logger.debug(f"Orchestrator approve failed: {exc}")
                    elif action_type == "orchestrator_set_input":
                        try:
                            from chintu_backend.orchestrator import get_orchestrator_manager

                            project_id = str(payload.get("project_id") or "").strip() or None
                            key = str(payload.get("key") or "").strip()
                            value = str(payload.get("value") or "")
                            is_secret = bool(payload.get("is_secret", False))
                            if key:
                                get_orchestrator_manager().set_input(
                                    key=key,
                                    value=value,
                                    is_secret=is_secret,
                                    project_id=project_id,
                                )
                            snapshot = get_orchestrator_manager().get_overview(limit=50)
                            if self.core_node:
                                await self.core_node.emit("orchestrator_snapshot", snapshot)
                        except Exception as exc:
                            logger.debug(f"Orchestrator set_input failed: {exc}")
                    elif action_type in {
                        "orchestrator_pause_project",
                        "orchestrator_resume_project",
                        "orchestrator_cancel_project",
                    }:
                        try:
                            from chintu_backend.orchestrator import get_orchestrator_manager

                            project_id = str(payload.get("project_id") or "").strip()
                            if project_id:
                                orch = get_orchestrator_manager()
                                if action_type == "orchestrator_pause_project":
                                    orch.pause_project(project_id)
                                elif action_type == "orchestrator_resume_project":
                                    orch.resume_project(project_id)
                                else:
                                    orch.cancel_project(project_id)

                            snapshot = get_orchestrator_manager().get_overview(limit=50)
                            if self.core_node:
                                await self.core_node.emit("orchestrator_snapshot", snapshot)
                        except Exception as exc:
                            logger.debug(f"Orchestrator project action failed: {exc}")

                logger.info("Core Node initialized (Gateway Client)")
                
                # 4. Initialize State Bridge (Events -> Gateway)
                from chintu_backend.core.gateway_bridge import GatewayStateBridge
                self.gateway_bridge = GatewayStateBridge(
                    core_node=self.core_node,
                    event_bus=self.event_bus,
                    state_manager=self.state_manager
                )
                
            except Exception as e:
                logger.warning(f"Gateway integration failed: {e}")
                self.core_node = None
                self.gateway_bridge = None

        # Optional headless gateway (Telegram) for remote control and alerts
        self.telegram_gateway = None
        try:
            from chintu_backend.io import get_telegram_gateway

            self.telegram_gateway = get_telegram_gateway(self.command_handler)
            ok, msg = self.telegram_gateway.start()
            logger.info(f"Telegram gateway: {msg}")
        except Exception as e:
            logger.warning(f"Telegram gateway not available: {e}")

        # Optional HTTP Gateway (webhooks + JSON-RPC)
        self.http_gateway = None
        if getattr(self.config, "gateway_http_enabled", False):
            try:
                from chintu_backend.interfaces.gateway import GatewayServer as HttpGatewayServer

                self.http_gateway = HttpGatewayServer(
                    self.command_handler,
                    host=getattr(self.config, "gateway_http_host", "127.0.0.1"),
                    port=int(getattr(self.config, "gateway_http_port", 18889)),
                    auth_token=getattr(self.config, "gateway_http_auth_token", None),
                )
                logger.info("HTTP Gateway server initialized")
            except Exception as e:
                logger.warning(f"HTTP Gateway not available: {e}")
        
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
        from chintu_backend.core.scheduler import get_scheduler
        from chintu_backend.automation.parallel_executor import get_parallel_executor
        from chintu_backend.orchestrator import get_orchestrator_manager
        
        # Connect Scheduler to CommandHandler
        scheduler = get_scheduler()
        scheduler.set_callback(self.command_handler.handle)
        logger.info("Scheduler initialized and connected to CommandHandler")

        # Auto-schedule finance market pulse if configured
        try:
            if getattr(self.config, "finance_auto_schedule_pulse", False):
                existing = [
                    task for task in scheduler.list_tasks()
                    if (task.name or "").lower() == "finance daily pulse"
                ]
                if not existing:
                    from chintu_backend.automation.scheduled_tasks import ScheduleType

                    scheduler.start()
                    scheduler.schedule(
                        name="Finance Daily Pulse",
                        workflow="finance news pulse",
                        schedule_type=ScheduleType.DAILY,
                        schedule_time=getattr(self.config, "finance_daily_brief_time", "08:00"),
                    )
                    logger.info("Scheduled Finance Daily Pulse")
        except Exception as exc:
            logger.warning("Failed to auto-schedule finance pulse: %s", exc)
        
        # Connect ParallelExecutor to CommandHandler
        executor = get_parallel_executor()
        executor.set_command_handler(self.command_handler.handle)
        logger.info("ParallelExecutor initialized and connected to CommandHandler")

        # Start Orchestrator (night-time projects, approvals, idle gating)
        try:
            orch = get_orchestrator_manager()
            ok, msg = orch.start()
            logger.info("Orchestrator: %s", msg)
        except Exception as exc:
            logger.warning("Failed to start Orchestrator: %s", exc)

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
        speaker_available = False
        if self.command_handler._tts:
            speaker_available = self.command_handler._tts.is_available
        sm.update_feature("speaker", enabled=speaker_available, status="active" if speaker_available else "inactive", error=None if speaker_available else "No audio output detected")
        
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

        # Reliability gates
        if (
            getattr(self.config, "reliability_gate_enabled", False)
            or getattr(self.config, "eval_gate_enabled", False)
            or getattr(self.config, "metrics_gate_enabled", False)
        ):
            sm.update_feature("reliability", enabled=True, status="testing")
        else:
            sm.update_feature("reliability", enabled=True, status="inactive")
        
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

        # Live Canvas
        if getattr(self, "canvas_manager", None):
            sm.update_feature("canvas", enabled=True, status="active")
        else:
            sm.update_feature("canvas", enabled=True, status="inactive")
        
        logger.info("Feature statuses initialized")

    def _suppress_library_logs(self):
        """Mute chatty libraries for professional output."""
        suppress = [
            "faster_whisper", "websockets", "pyttsx3", "urllib3", 
            "requests", "asyncio", "vlc", "pydantic", "matplotlib"
        ]
        for lib in suppress:
            logging.getLogger(lib).setLevel(logging.WARNING)
        logger.info("Chatty library logs suppressed (level=WARNING)")

    def _start_prewarm_threads(self) -> None:
        """Warm up local models in the background (best-effort)."""
        try:
            cfg = getattr(self, "config", None)
            if not cfg:
                return
            if not (bool(getattr(cfg, "llm_prewarm_enabled", False)) or bool(getattr(cfg, "vision_prewarm_enabled", False))):
                return
            if getattr(self, "_prewarm_thread", None):
                return

            self._prewarm_thread = threading.Thread(target=self._run_prewarm, daemon=True)
            self._prewarm_thread.start()
        except Exception:
            return

    def _run_prewarm(self) -> None:
        cfg = getattr(self, "config", None)
        if not cfg:
            return

        if bool(getattr(cfg, "llm_prewarm_enabled", False)) and hasattr(getattr(self, "llm", None), "prewarm"):
            try:
                base_model = str(getattr(cfg, "ollama_model", "") or "").strip()
                strong_model = str(getattr(cfg, "ollama_model_strong", "") or "").strip()
                keep_alive = getattr(cfg, "ollama_keep_alive_seconds", None)
                ok = bool(self.llm.prewarm(model=base_model or None, keep_alive=keep_alive))
                logger.info("LLM prewarm (model=%s): %s", base_model or getattr(self.llm, "model", "?"), ok)

                if bool(getattr(cfg, "llm_prewarm_include_strong", True)) and strong_model and strong_model != base_model:
                    ok2 = bool(self.llm.prewarm(model=strong_model, keep_alive=0))
                    logger.info("Strong LLM prewarm (model=%s): %s", strong_model, ok2)
            except Exception as exc:
                logger.warning("LLM prewarm failed: %s", exc)

        if bool(getattr(cfg, "vision_prewarm_enabled", False)):
            try:
                from chintu_backend.automation.vision_automation import get_vision_automation

                va = get_vision_automation()
                if hasattr(va, "prewarm"):
                    ok = bool(va.prewarm())
                    logger.info("Vision prewarm (model=%s): %s", getattr(va, "model", "?"), ok)
            except Exception as exc:
                logger.warning("Vision prewarm failed: %s", exc)

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

    async def _process_transcript(self, text: str, source: str = "audio", context: Optional[dict] = None):
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
        
        # Noise filter: Ignore single non-alphanumeric chars (like '.')
        if len(text) < 2 and not text.isalnum():
            logger.debug(f"Ignored noise transcript: '{text}'")
            self.state_manager.set_assistant_state(AssistantState.IDLE)
            self.state_manager.set_transcript("", is_final=False)
            return
        
        if not text:
            self._wake_cooldown_until = time.time() + self.config.wake_word_cooldown_seconds
            self.state_manager.set_assistant_state(AssistantState.IDLE)
            self.state_manager.set_assistant_state(AssistantState.IDLE) # Duplicate line removed in cleanup, keeping logic same
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

        await asyncio.to_thread(self.command_handler.handle, text, source, context)

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
        
        # Only greet if speaker is available
        speaker_available = self.command_handler._tts and self.command_handler._tts.is_available
        if speaker_available:
            await self._speak_greeting()
            
        if self.config.auto_listen_on_connect:
            if self.audio_capture.is_running and self.audio_capture.check_hardware_available():
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
        if not self.command_handler._tts or not self.command_handler._tts.is_available:
            logger.info("Skipping voice greeting: TTS not available or no speaker.")
            return
        
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

    @staticmethod
    def _compute_calibrated_stt_threshold(
        levels: list[float],
        *,
        base_threshold: float,
        noise_multiplier: float,
    ) -> float:
        """Compute a stable silence threshold from ambient microphone levels."""
        if not levels:
            return max(0.0, min(1.0, float(base_threshold)))
        sorted_levels = sorted(max(0.0, min(1.0, float(v))) for v in levels)
        n = len(sorted_levels)
        p70 = sorted_levels[int((n - 1) * 0.70)]
        p90 = sorted_levels[int((n - 1) * 0.90)]
        noise_floor = max(p70, p90 * 0.75)
        candidate = max(float(base_threshold), noise_floor * float(noise_multiplier))
        return max(0.005, min(0.20, candidate))

    async def _auto_calibrate_stt_noise(self) -> None:
        """Auto-calibrate STT silence threshold using ambient audio levels."""
        if not bool(getattr(self.config, "stt_auto_calibrate", False)):
            return
        if not self.audio_capture.is_running:
            return

        calibration_seconds = float(getattr(self.config, "stt_noise_calibration_seconds", 0.8) or 0.8)
        min_samples = int(getattr(self.config, "stt_noise_calibration_min_samples", 20) or 20)
        if calibration_seconds <= 0:
            return

        baseline = len(self._audio_level_history)
        await asyncio.sleep(calibration_seconds)

        samples = list(self._audio_level_history)[baseline:]
        if len(samples) < min_samples:
            # Fall back to latest available ambient window.
            samples = list(self._audio_level_history)[-min_samples:]
        if len(samples) < min_samples:
            logger.info("Skipping STT noise calibration (insufficient samples: %s)", len(samples))
            return

        new_threshold = self._compute_calibrated_stt_threshold(
            samples,
            base_threshold=float(self.config.stt_silence_threshold),
            noise_multiplier=float(self.config.stt_noise_multiplier),
        )
        self.stt.set_silence_threshold(new_threshold)
        self._stt_noise_calibrated = True
        logger.info(
            "STT noise calibration complete: threshold=%.4f (samples=%s, window=%.2fs)",
            new_threshold,
            len(samples),
            calibration_seconds,
        )

    def _setup_callbacks(self):
        """Setup component callbacks."""
        from chintu_backend.core import AssistantState
        
        def update_levels(l):
            try:
                self._audio_level_history.append(float(l))
            except Exception:
                pass
            self.state_manager.update_audio_level(l)
            if hasattr(self, 'gateway_bridge') and self.gateway_bridge:
                self.gateway_bridge.update_audio_level(l)
                
        self.audio_capture.set_level_callback(update_levels)
        
        def on_audio_chunk(chunk):
            # CRITICAL: Block ALL audio processing if typing is active
            # This prevents STT transcripts from flickering or overwriting UI input
            if self._typing_active:
                return

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
                # Prevent state change if transcript was just noise/dot (handled in _process_transcript)
                # But here we ensure AssistantState stays IDLE instead of flashing.
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
        
        # Typing events (Pause/Resume Wake Word)
        def on_typing_start(e):
            self._typing_active = True
        
        def on_typing_stop(e):
            self._typing_active = False
            
        self.event_bus.subscribe(EventType.TYPING_START, on_typing_start)
        self.event_bus.subscribe(EventType.TYPING_STOP, on_typing_stop)
        
        def on_ptt_start(e):
            if not self.stt.is_listening and self.audio_capture.is_running:
                self.state_manager.set_assistant_state(AssistantState.LISTENING)
                self.stt.start_listening()
        
        self.event_bus.subscribe(EventType.PUSH_TO_TALK_START, on_ptt_start)
        self.event_bus.subscribe(EventType.PUSH_TO_TALK_STOP, lambda e: self.stt.stop_listening() if self.stt.is_listening else None)
        
        # Connect text input from UI (Missing link fixed)
        self.event_bus.subscribe(EventType.TRANSCRIPT_READY, lambda e: self._schedule_coroutine(
            self._process_transcript(
                e.data.get("text", ""), 
                source=e.data.get("source", "ui"),
                context=e.data.get("context")
            )
        ))

    def _ensure_gateway_running(self):
        """Check if Gateway is running, spawn if not."""
        import socket
        import subprocess
        import sys
        
        host = self.config.gateway_host
        port = self.config.gateway_port
        
        # Check if port is in use
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            logger.info(f"Gateway already running on {host}:{port}")
            return

        logger.info(f"Spawning Gateway Server on {host}:{port}...")
        # Spawn as detatched process
        cmd = [sys.executable, "-m", "chintu_backend.gateway.server"]
        try:
            # Creation flags for independent process on Windows
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS if hasattr(subprocess, "DETACHED_PROCESS") else 0
            
            self.gateway_server_process = subprocess.Popen(
                cmd,
                creationflags=creationflags,
                close_fds=True
            )
            logger.info(f"Gateway spawned (PID: {self.gateway_server_process.pid}). Waiting for startup...")
            time.sleep(2) # Give it a moment to bind
        except Exception as e:
            logger.error(f"Failed to spawn Gateway: {e}")

    async def start(self):
        """Start the assistant."""
        self._running = True
        self._loop = asyncio.get_running_loop()

        if self.runtime_hardware_adapter and not self._hardware_adapt_task:
            self._hardware_adapt_task = asyncio.create_task(self._runtime_hardware_adaptation_loop())

        # Phase 1: Connect Core Node to Gateway
        if self.core_node:
            asyncio.create_task(self.core_node.connect())
            # We don't block on this, it runs in background
        
        # Legacy/UI
        await self.ws_server.start()
        if self.http_gateway:
            await self.http_gateway.start()
        
        self.audio_capture.start()
        # Only start wake word if audio capture actually identifies hardware
        if self.audio_capture.is_running:
            await self._auto_calibrate_stt_noise()
            self.wake_word.start()
        else:
            logger.warning("Wake word detection disabled: No microphone hardware available.")

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
        if self._hardware_adapt_task:
            self._hardware_adapt_task.cancel()
            try:
                await self._hardware_adapt_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._hardware_adapt_task = None
        
        if self.core_node:
            await self.core_node.disconnect()
            
        if self.gateway_server_process:
            logger.info("Stopping Gateway Server subprocess...")
            self.gateway_server_process.terminate()
            
        self.audio_capture.stop()
        self.wake_word.stop()
        if self.wake_word_process: self.wake_word_process.stop()
        self.hand_tracker.stop()
        self.event_bus.stop()
        await self.ws_server.stop()
        if self.http_gateway:
            await self.http_gateway.stop()
        if self.gateway_server: await self.gateway_server.stop()
        logger.info("Chintu Assistant stopped.")

    async def _runtime_hardware_adaptation_loop(self) -> None:
        """Periodically refresh hardware topology and re-apply tuning."""
        if not self.runtime_hardware_adapter:
            return
        interval = float(getattr(self.config, "hardware_adapt_check_interval_seconds", 120.0) or 120.0)
        interval = max(5.0, interval)
        try:
            # Prime baseline signature on startup.
            self.runtime_hardware_adapter.maybe_refresh(force=True)
        except Exception as exc:
            logger.warning("Initial runtime hardware adaptation check failed: %s", exc)

        while self._running:
            try:
                self.runtime_hardware_adapter.maybe_refresh()
            except Exception as exc:
                logger.warning("Runtime hardware adaptation check failed: %s", exc)
            await asyncio.sleep(interval)

    def _on_runtime_hardware_adapted(self, payload: Optional[dict] = None) -> None:
        """Apply runtime-tuned config values to active LLM client instances."""
        try:
            from chintu_backend.core.runtime_llm_sync import sync_runtime_llm_clients

            targets = [getattr(self, "llm", None)]
            handler = getattr(self, "command_handler", None)
            if handler:
                targets.extend(
                    [
                        getattr(handler, "llm", None),
                        getattr(handler, "local_verifier", None),
                        getattr(getattr(handler, "router", None), "local_llm", None),
                        getattr(getattr(handler, "action_dispatcher", None), "llm", None),
                        getattr(getattr(handler, "conversation_flow", None), "llm", None),
                        getattr(getattr(handler, "conversation_flow", None), "llm_client", None),
                        getattr(getattr(handler, "fast_router", None), "llm", None),
                    ]
                )
            receipt = sync_runtime_llm_clients(self.config, targets)
            if int(receipt.get("changed_targets") or 0) <= 0:
                return
            if getattr(self, "state_manager", None):
                self.state_manager.log_activity(
                    f"Runtime LLM settings updated for {int(receipt.get('changed_targets') or 0)} client(s)."
                )
        except Exception as exc:
            logger.warning("Runtime LLM sync failed: %s", exc)


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
