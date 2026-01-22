"""
Chintu Personal AI Assistant - Main Entry Point

A Windows desktop personal AI assistant with:
- Voice activation ("Hey Chintu") + Speech-to-Text
- Hand gesture recognition via webcam
- Task automation (apps, job search, etc.)
- Local LLM integration via Ollama
"""

import asyncio
import logging
import signal
import sys
import threading
import re
from typing import Optional

import os
from datetime import datetime

# Configure logging
os.makedirs("logs", exist_ok=True)
session_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
log_filename = f"logs/session_{session_timestamp}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_filename, encoding='utf-8')
    ]
)
logger = logging.getLogger("chintu")
# Enable debug for wake word diagnosis
logging.getLogger("chintu.audio.wake_word").setLevel(logging.DEBUG)


class ChintuAssistant:
    """Main Chintu Assistant class that orchestrates all components."""
    
    def __init__(self):
        from chintu.core import (
            get_config, get_event_bus, get_state_manager,
            CommandHandler, WebSocketServer, EventType, AssistantState
        )
        from chintu.audio import AudioCapture, WakeWordDetector, SpeechToText
        from chintu.audio import WakeWordTrainer
        from chintu.vision import HandTracker, GestureRecognizer

        from chintu.llm import OllamaClient
        from chintu.automation.scheduled_tasks import get_scheduler
        from chintu.automation.parallel_executor import get_parallel_executor
        
        self.config = get_config()
        if self.config.structured_logging:
            try:
                from chintu.core.logging_config import setup_json_logging
                level = getattr(logging, self.config.log_level.upper(), logging.INFO)
                setup_json_logging(level=level, log_file=self.config.structured_log_file)
            except Exception as e:
                logger.warning(f"Failed to configure structured logging: {e}")
        self.event_bus = get_event_bus()
        self.state_manager = get_state_manager()
        
        # Initialize system integrator (platform, device registry, error reporting, health monitoring)
        try:
            from chintu.core.system_integrator import get_system_integrator
            self.system_integrator = get_system_integrator()
            init_status = self.system_integrator.initialize()
            logger.info(f"System integrator initialized: {init_status}")
            
            # Log status message
            status_msg = self.system_integrator.get_status_message()
            logger.info(f"\n{status_msg}")
            
            # Report any initialization errors
            if init_status.get("errors"):
                from chintu.core.error_reporter import ErrorSeverity, report_error
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
                from chintu.audio.wake_word_process import WakeWordProcessWorker
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
        
        # WebSocket server for Flutter UI
        self.ws_server = WebSocketServer(
            host=self.config.websocket_host,
            port=self.config.websocket_port,
        )
        # Register globally for capability handlers to access
        from chintu.core.websocket_server import set_ws_server
        set_ws_server(self.ws_server)

        self._greeting_spoken = False
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
        from chintu.core.interrupt_handler import get_interrupt_handler
        
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
                if original_on_done:
                    original_on_done()

            # We need to set these callbacks safely
            self.command_handler._tts.set_callbacks(
                on_start=on_tts_start,
                on_done=on_tts_done
            )
            logger.info("Dynamic wake word confirmation hooked to TTS events")
        
        # Register on-interrupt callback to update state
        def on_interrupt(interrupt_type):
            from chintu.core import AssistantState
            logger.info(f"Interrupt received: {interrupt_type.value}")
            self.state_manager.set_assistant_state(AssistantState.IDLE)
            self.state_manager.set_transcript("", is_final=False)
            # Ensure confirmation is disabled on interrupt (since TTS stops)
            if self.wake_word:
                self.wake_word.set_confirm_with_stt(False)
        
        handler.register_on_interrupt(on_interrupt)
        logger.info("Interrupt handler configured for hard barge-in")

    def _init_automation(self):
        """Initialize automation components."""
        from chintu.automation.scheduled_tasks import get_scheduler
        from chintu.automation.parallel_executor import get_parallel_executor
        
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
            from chintu.proactivity.manager import get_proactivity_manager
            self.proactivity_manager = get_proactivity_manager()
            self.proactivity_manager.start()
            logger.info("Proactivity Engine initialized and started")
        except Exception as e:
            logger.warning(f"Failed to start Proactivity Engine: {e}")
            self.proactivity_manager = None

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
        import time
        from chintu.core import AssistantState
        
        # CRITICAL FIX: ALWAYS stop TTS when wake word detected (Google Assistant style)
        # This ensures "Hey Chintu" can interrupt the assistant at any time
        if self.command_handler._tts and self.command_handler._tts.is_speaking:
            logger.info("Wake word detected during TTS - stopping speech for barge-in")
            self.command_handler.stop_speaking()
            # Reset state immediately
            self.state_manager.set_assistant_state(AssistantState.LISTENING)

        # Skip if already listening (avoid duplicate triggers)
        if self.stt.is_listening:
            logger.debug("Wake word detected but already listening - ignoring")
            return
        
        # Allow wake word during any state (conversation, speaking, processing)
        # This is the Google Assistant behavior - wake word always works
        
        # Cooldown check - prevent rapid re-triggers after empty transcriptions
        # But allow barge-in to bypass cooldown if TTS was speaking
        was_speaking = self.command_handler._tts and self.command_handler._tts.is_speaking
        now = time.time()
        if not was_speaking and now < self._wake_cooldown_until:
            remaining = self._wake_cooldown_until - now
            logger.debug(f"Wake word cooldown active ({remaining:.1f}s remaining)")
            return
        
        logger.info(f"Wake word detected (source={source}) - starting listening")
        print(f"\nWAKE WORD DETECTED! (source: {source}) - Listening...")
        
        # Bring UI to front when user summons Chintu
        if self.ws_server:
            self.ws_server.bring_ui_to_front()
        
        # PHASE 2 FIX: Capture window snapshot at wake word for consistent context
        self.state_manager.capture_window_snapshot()
        
        self.state_manager.set_assistant_state(AssistantState.LISTENING)
        self.state_manager.update_feature("wake_word", enabled=True, status="active")
        self.state_manager.update_feature("voice_commands", enabled=True, status="active")
        self.stt.start_listening()
        
        # CRITICAL FIX: Set in_conversation=True so empty transcripts get retries
        # This prevents immediately going to idle if user pauses after wake word
        self._in_conversation = True
        self._conversation_retries = 0

    @staticmethod
    def _strip_wake_phrase(text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"^(hey|hi|hello)\s+chintu\b[, ]*", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    async def _process_transcript(self, text: str, source: str = "audio"):
        from chintu.core import AssistantState
        text = self._strip_wake_phrase(text)
        if self.config.wake_word_noise_mode and source == "audio":
            word_count = len(text.split())
            if word_count < self.config.wake_word_min_word_count:
                logger.info("Noise mode: transcript too short (%s words)", word_count)
                text = ""
        if not text:
            # Silence timeout or no speech detected - go to sleep
            logger.info("No speech detected - going to sleep...")
            import time
            self._wake_cooldown_until = time.time() + self.config.wake_word_cooldown_seconds
            self.state_manager.set_assistant_state(AssistantState.IDLE)
            self.state_manager.set_transcript("", is_final=False)
            self.state_manager.update_feature("voice_commands", enabled=True, status="inactive")
            self.state_manager.update_feature("wake_word", enabled=True, status="inactive")
            return
        logger.info(f"Transcript ({source}): {text}")
        self.state_manager.set_transcript(text, is_final=True)
        self.state_manager.set_assistant_state(AssistantState.PROCESSING)
        self.state_manager.update_feature("voice_commands", enabled=True, status="active")

        # Check for hand gesture toggle commands
        text_lower = text.lower()
        if any(phrase in text_lower for phrase in ["turn on hand gesture", "enable hand gesture", "start hand gesture", "hand gesture control on"]):
            await self._toggle_hand_gestures(True)
            return
        elif any(phrase in text_lower for phrase in ["turn off hand gesture", "disable hand gesture", "stop hand gesture", "hand gesture control off"]):
            await self._toggle_hand_gestures(False)
            return

        await asyncio.to_thread(self.command_handler.handle, text, source)

        # Conversation Mode: Stay awake for follow-up commands
        if self.config.conversation_mode:
            # Wait for TTS to finish speaking before restarting listening
            if self.command_handler._tts:
                while self.command_handler._tts.is_speaking:
                    await asyncio.sleep(0.1)
            
            # Enter conversation mode
            self._in_conversation = True
            self._conversation_retries = 0
            
            # Restart listening for follow-up (no wake word needed)
            # Use conversation timeout (shorter) for follow-up detection
            self.stt.set_timeout(self.config.conversation_timeout_seconds)
            logger.info(f"Conversation mode: Listening for follow-up ({self.config.conversation_timeout_seconds}s timeout)...")
            self.state_manager.set_assistant_state(AssistantState.LISTENING)
            self.state_manager.set_transcript("", is_final=False)
            self.stt.start_listening()
        else:
            # Original behavior: go back to IDLE
            if self.command_handler._tts and self.command_handler._tts.is_speaking:
                self.state_manager.set_assistant_state(AssistantState.SPEAKING)
            else:
                self.state_manager.set_assistant_state(AssistantState.IDLE)
            self.state_manager.set_transcript("", is_final=False)
            self.state_manager.update_feature("voice_commands", enabled=True, status="inactive")
            self.state_manager.update_feature("wake_word", enabled=True, status="inactive")

    async def _speak_greeting(self):
        """Speak a personalized voice greeting when the assistant starts."""
        from chintu.core.smart_greeting import get_smart_greeting
        from chintu.memory.preferences import get_preference_manager
        
        # Get user name for personalization
        user_name = None
        try:
            prefs = get_preference_manager()
            user_name = prefs.get("user_name") if prefs else None
        except Exception:
            pass
        
        # Generate time-aware, personalized greeting
        greeting = get_smart_greeting(user_name)
        
        # Send greeting text to UI to match audio
        try:
            if self.ws_server:
                await self.ws_server.broadcast_response(greeting)
        except Exception as e:
            logger.warning(f"Failed to send greeting to UI: {e}")

        try:
            await asyncio.to_thread(self.command_handler.speak, greeting, False, True, False)
            logger.info("Voice greeting played")
        except Exception as e:
            logger.warning(f"Failed to play voice greeting: {e}")

    async def _toggle_hand_gestures(self, enable: bool):
        """Toggle hand gesture control on or off."""
        from chintu.core import AssistantState
        if enable:
            if not self.hand_tracker._running:
                self.hand_tracker.start()
                self.state_manager.update_feature("hand_gestures", enabled=True, status="active")
                response = "Hand gesture control is now enabled. Show your palm to interact."
                logger.info("Hand gestures enabled")
            else:
                response = "Hand gesture control is already enabled."
        else:
            if self.hand_tracker._running:
                self.hand_tracker.stop()
                self.state_manager.update_feature("hand_gestures", enabled=True, status="inactive")
                response = "Hand gesture control is now disabled."
                logger.info("Hand gestures disabled")
            else:
                response = "Hand gesture control is already disabled."
        
        try:
            await asyncio.to_thread(self.command_handler.speak, response)
        except Exception as e:
            logger.warning(f"Failed to speak response: {e}")
        
        self.state_manager.set_assistant_state(AssistantState.IDLE)
        self.state_manager.update_feature("voice_commands", enabled=True, status="active")
        self.state_manager.update_feature("wake_word", enabled=True, status="active")

    def _setup_callbacks(self):
        """Setup component callbacks."""
        from chintu.core import AssistantState
        # Audio level for waveform
        def on_audio_level(level: float):
            self.state_manager.update_audio_level(level)
        
        self.audio_capture.set_level_callback(on_audio_level)
        
        # Audio to wake word and STT
        _chunk_counter = [0]  # Use list for mutable counter in closure
        def on_audio_chunk(chunk):
            _chunk_counter[0] += 1
            is_listening = self.stt.is_listening
            
            # Log every 100 chunks to confirm audio is flowing (roughly every 6s at 16kHz)
            if _chunk_counter[0] % 100 == 0:
                logger.debug(f"Audio chunk #{_chunk_counter[0]}, is_listening={is_listening}, len={len(chunk)}")
            
            # ALWAYS process wake word when not actively listening for speech
            # This ensures barge-in works during greeting, TTS, and idle
            if not is_listening:
                # Send to process-based detector (high priority, never blocks)
                if self.wake_word_process:
                    self.wake_word_process.process_audio(chunk)
                # Also send to thread-based detector (fallback/confirmation)
                self.wake_word.process_audio(chunk)
            
            # Feed audio to STT when actively listening
            if is_listening:
                self.stt.process_audio(chunk)
        
        self.audio_capture.add_callback(on_audio_chunk)
        
        # Wake word detected
        def on_wake_word():
            self._handle_wake_word_detected(source="audio")
        
        self.wake_word.set_wake_callback(on_wake_word)
        
        # Transcript ready
        def on_transcript(text: str, is_final: bool):
            if not is_final:
                return
            if text:
                self._schedule_coroutine(self._process_transcript(text, source="audio"))
            else:
                # Empty transcript - check if we're in conversation mode
                if self._in_conversation and self._conversation_retries < self._max_conversation_retries:
                    # Retry listening in conversation mode
                    self._conversation_retries += 1
                    logger.info(f"Conversation mode: No speech, retrying ({self._conversation_retries}/{self._max_conversation_retries})")
                    self.stt.set_timeout(self.config.conversation_timeout_seconds)
                    self.state_manager.set_transcript("", is_final=False)
                    self.stt.start_listening()
                else:
                    # Exit conversation mode and go to idle
                    import time
                    self._in_conversation = False
                    self._conversation_retries = 0
                    self._wake_cooldown_until = time.time() + self.config.wake_word_cooldown_seconds
                    logger.info("Conversation ended - going to idle")
                    self.state_manager.set_assistant_state(AssistantState.IDLE)
                    self.state_manager.update_feature("voice_commands", enabled=True, status="inactive")
                    self.state_manager.update_feature("wake_word", enabled=True, status="inactive")

        def on_partial(text: str):
            if not text:
                return
            self.state_manager.set_transcript(text, is_final=False)
        
        self.stt.set_transcript_callback(on_transcript)
        self.stt.set_partial_callback(on_partial)
        
        # Hand tracking
        def on_landmarks(hands):
            result = self.gesture_recognizer.process_landmarks(hands)
            if result:
                logger.info(f"Gesture: {result.gesture.value}")
                self.state_manager.set_hand_detected(True, result.gesture.value)
                self.state_manager.update_feature("hand_gestures", enabled=True, status="active")
                
                # Trigger listening on open palm gesture
                from chintu.vision import GestureType
                if result.gesture == GestureType.OPEN_PALM:
                    self._handle_wake_word_detected(source="gesture")
        
        self.hand_tracker.set_landmarks_callback(on_landmarks)
    
    def _setup_event_handlers(self):
        """Setup event bus handlers."""
        from chintu.core import EventType, AssistantState

        def on_wake_event(event):
            self._handle_wake_word_detected(source=event.source)

        def on_ui_connected(event):
            if self._greeting_spoken:
                return
            self._greeting_spoken = True
            
            # Speak greeting
            self._schedule_coroutine(self._speak_greeting())
            
            # Auto-Listen on startup (only if configured - disabled by default to prevent noise issues)
            if self.config.auto_listen_on_connect:
                logger.info("Auto-listening on startup...")
                self.state_manager.set_assistant_state(AssistantState.LISTENING)
                self.state_manager.update_feature("voice_commands", enabled=True, status="active")
                self.stt.start_listening()
            else:
                logger.info("Ready - say 'Hey Chintu' to activate")

        def on_push_to_talk_start(event):
            if self.stt.is_listening or self.state_manager.assistant_state != AssistantState.IDLE:
                return
            self.state_manager.set_assistant_state(AssistantState.LISTENING)
            self.state_manager.update_feature("voice_commands", enabled=True, status="active")
            self.stt.start_listening()

        def on_push_to_talk_stop(event):
            if not self.stt.is_listening:
                return
            self.state_manager.set_assistant_state(AssistantState.PROCESSING)
            self.stt.stop_listening()

        async def on_transcript_event(event):
            text = event.data.get("text", "")
            await self._process_transcript(text, source=event.data.get("source", event.source))

        async def on_wake_word_record(event):
            index = int(event.data.get("index", 0))
            kind = event.data.get("kind", "positive")
            try:
                path = await asyncio.to_thread(
                    self.wake_word_trainer.record_sample,
                    index,
                    kind,
                )
                await self.ws_server.broadcast_message({
                    "type": "wake_word_sample",
                    "index": index,
                    "kind": kind,
                    "status": "recorded",
                    "path": str(path),
                })
            except Exception as exc:
                await self.ws_server.broadcast_message({
                    "type": "wake_word_sample",
                    "index": index,
                    "kind": kind,
                    "status": "error",
                    "message": str(exc),
                })

        async def on_wake_word_status(event):
            status = self.wake_word_trainer.get_status()
            await self.ws_server.broadcast_message({
                "type": "wake_word_status",
                "samples": status.samples,
                "count": status.count,
            })

        async def on_wake_word_train(event):
            def progress(status: str, message: str):
                self._schedule_coroutine(self.ws_server.broadcast_message({
                    "type": "wake_word_training",
                    "status": status,
                    "message": message,
                }))

            await self.ws_server.broadcast_message({
                "type": "wake_word_training",
                "status": "started",
                "message": "Training started.",
            })

            try:
                verifier_path = await asyncio.to_thread(
                    self.wake_word_trainer.train_verifier,
                    progress,
                )
                self.wake_word.reload(
                    verifier_path=str(verifier_path),
                    base_model=self.config.wake_word_base_model,
                )
                await self.ws_server.broadcast_message({
                    "type": "wake_word_training",
                    "status": "completed",
                    "message": "Wake word training completed.",
                    "verifier_path": str(verifier_path),
                })
            except Exception as exc:
                await self.ws_server.broadcast_message({
                    "type": "wake_word_training",
                    "status": "error",
                    "message": str(exc),
                })

        self.event_bus.subscribe(EventType.WAKE_WORD_DETECTED, on_wake_event)
        self.event_bus.subscribe(EventType.TRANSCRIPT_READY, on_transcript_event, is_async=True)
        self.event_bus.subscribe(EventType.WAKE_WORD_RECORD_REQUEST, on_wake_word_record, is_async=True)
        self.event_bus.subscribe(EventType.WAKE_WORD_STATUS_REQUEST, on_wake_word_status, is_async=True)
        self.event_bus.subscribe(EventType.WAKE_WORD_TRAIN_REQUEST, on_wake_word_train, is_async=True)
        self.event_bus.subscribe(EventType.UI_CONNECTED, on_ui_connected)
        self.event_bus.subscribe(EventType.PUSH_TO_TALK_START, on_push_to_talk_start)
        self.event_bus.subscribe(EventType.PUSH_TO_TALK_STOP, on_push_to_talk_stop)
    
    async def start(self):
        """Start the assistant."""
        logger.info("Starting Chintu Assistant...")
        self._running = True
        self._loop = asyncio.get_running_loop()
        
        # Start WebSocket server
        if not await self.ws_server.start():
            logger.error("WebSocket server failed to start. Is another instance running?")
            self._running = False
            return
        
        # Start audio capture and wake word
        self.audio_capture.start()
        self.wake_word.start()
        
        # Start process-based wake word (if enabled) with callback
        if self.wake_word_process:
            self.wake_word_process.set_wake_callback(
                lambda: self._schedule_coroutine(asyncio.to_thread(self._handle_wake_word_detected, "process"))
            )
            self.wake_word_process.start()
            logger.info("Process-based wake word detector started")
        
        # Hand tracking is disabled by default - enabled via voice command
        # if self.config.gesture_enabled:
        #     self.hand_tracker.start()
        
        # Start event queue processing
        asyncio.create_task(self.event_bus.process_queue())
        
        logger.info("Chintu Assistant is ready!")

        # Essential features - wake_word is ACTIVE because we're always listening
        self.state_manager.update_feature("wake_word", enabled=True, status="active")
        self.state_manager.update_feature("voice_commands", enabled=True, status="inactive")
        # Optional features - all start inactive until actually used
        self.state_manager.update_feature("llm_integration", enabled=True, status="inactive")
        self.state_manager.update_feature("app_control", enabled=True, status="inactive")
        self.state_manager.update_feature("job_search", enabled=True, status="inactive")
        self.state_manager.update_feature("hand_gestures", enabled=True, status="inactive")
        
        logger.info(f"Listening for wake word: '{self.config.wake_word}'")
        logger.info(f"WebSocket server: ws://{self.config.websocket_host}:{self.config.websocket_port}")
        
        # Smart Greeting
        if self.config.tts_greeting_enabled:
            try:
                from chintu.core.smart_greeting import get_smart_greeting
                from chintu.memory.preferences import get_preference_manager
                
                # Get user name from preferences
                prefs = get_preference_manager()
                user_name = prefs.get("user_name", None)
                
                greeting = get_smart_greeting(user_name)
                logger.info(f"Greeting user: {greeting}")
                
                # Speak greeting (async)
                if hasattr(self.command_handler, 'tts'):
                    threading.Thread(
                        target=self.command_handler.tts.speak, 
                        args=(greeting,),
                        daemon=True
                    ).start()
            except Exception as e:
                logger.warning(f"Failed to play voice greeting: {e}")
        
        # Keep running
        while self._running:
            await asyncio.sleep(0.1)
    
    async def stop(self):
        """Stop the assistant."""
        logger.info("Stopping Chintu Assistant...")
        self._running = False
        
        self.audio_capture.stop()
        self.wake_word.stop()
        
        # Stop process-based wake word
        if self.wake_word_process:
            self.wake_word_process.stop()
            logger.info("Process-based wake word detector stopped")
            
        self.hand_tracker.stop()
        self.event_bus.stop()
        await self.ws_server.stop()
        
        # Stop TaskManager background thread
        if hasattr(self.command_handler, 'task_manager'):
            self.command_handler.task_manager.stop()
            
        # Stop Scheduler
        from chintu.automation.scheduled_tasks import get_scheduler
        get_scheduler().stop()
        
        # Shutdown ParallelExecutor
        from chintu.automation.parallel_executor import get_parallel_executor
        get_parallel_executor().shutdown()
        
        # Shutdown Proactivity Engine
        if hasattr(self, 'proactivity_manager') and self.proactivity_manager:
            self.proactivity_manager.stop()
        
        # Shutdown system integrator
        if hasattr(self, 'system_integrator') and self.system_integrator:
            try:
                self.system_integrator.shutdown()
            except Exception as e:
                logger.warning(f"Error shutting down system integrator: {e}")
        
        logger.info("Chintu Assistant stopped.")


async def main():
    """Main entry point."""
    assistant = ChintuAssistant()
    
    # Handle shutdown signals
    def signal_handler():
        asyncio.create_task(assistant.stop())
    
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
    
    try:
        await assistant.start()
    except KeyboardInterrupt:
        await assistant.stop()


if __name__ == "__main__":
    asyncio.run(main())
