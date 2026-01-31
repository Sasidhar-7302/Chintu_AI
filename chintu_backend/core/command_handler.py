"""Command handler - processes and executes commands."""

import os
import logging
from typing import Optional, Callable, Dict, Any, Tuple

from ..utils.command_parser import CommandParser, Command, CommandType
from ..automation.app_launcher import AppLauncher
from ..automation.job_search import JobSearcher
from ..brain.llm.ollama_client import OllamaClient
from .state import get_state_manager, AssistantState
from .config import get_config
from .model_router import ModelRouter, IntentDetector, Intent
from .memory import MemoryManager
from .logging_config import new_trace_id, clear_trace, get_trace_id

logger = logging.getLogger(__name__)


class CommandHandler:
    """
    Handles command execution.
    Routes parsed commands to appropriate modules.
    Delegates to ActionDispatcher and ConversationFlow.
    """
    
    def __init__(
        self,
        llm_client: Optional[OllamaClient] = None,
        app_launcher: Optional[AppLauncher] = None,
        job_searcher: Optional[JobSearcher] = None,
        tts_enabled: bool = True,
    ):
        self.config = get_config()
        self.parser = CommandParser()
        self.llm = llm_client or OllamaClient()
        self.launcher = app_launcher or AppLauncher()
        self.job_searcher = job_searcher or JobSearcher()
        self.state_manager = get_state_manager()
        
        # Initialize modular components
        from ..brain.conversation_flow import ConversationFlow
        from .action_dispatcher import ActionDispatcher
        
        # Initialize Capability Registry (centralized loader)
        from .capabilities import get_registry
        from .capability_loader import register_all_capabilities
        self.capability_registry = get_registry()
        
        self.conversation_flow = ConversationFlow(
            memory_manager=None, # Will set later if available
            llm_client=self.llm
        )
        self.action_dispatcher = ActionDispatcher(self.capability_registry)

        # Initialize Memory Manager (Hybrid by default)
        self.memory_manager = None
        if self.config.memory_enabled:
            try:
                if getattr(self.config, "memory_backend", "hybrid") == "hybrid":
                    from ..brain.memory.hybrid_memory import HybridMemoryManager
                    self.memory_manager = HybridMemoryManager(
                        db_path=getattr(self.config, "memory_sqlite_path", None)
                    )
                else:
                    self.memory_manager = MemoryManager(
                        persistence_path=str(self.config.memory_store_path or "memory_store")
                    )
                self.conversation_flow.memory_manager = self.memory_manager
                logger.info("Memory Manager initialized: True")
            except Exception as e:
                self.memory_manager = None
                logger.warning(f"Memory Manager unavailable: {e}")
                try:
                    from .error_reporter import report_error, ErrorSeverity
                    report_error(
                        e,
                        severity=ErrorSeverity.WARNING,
                        component="memory",
                        user_message=f"Memory system unavailable: {e}",
                    )
                except Exception:
                    pass
        else:
            logger.info("Memory Manager initialized: False")

        # Start memory lifecycle manager (dedupe/decay/summary/SOUL)
        self.memory_lifecycle = None
        if self.memory_manager and getattr(self.config, "memory_backend", "hybrid") == "hybrid":
            if getattr(self.config, "memory_lifecycle_enabled", True):
                try:
                    from ..brain.memory.lifecycle import MemoryLifecycleManager
                    self.memory_lifecycle = MemoryLifecycleManager(self.memory_manager)
                    self.memory_lifecycle.start()
                except Exception as e:
                    logger.warning(f"Memory lifecycle manager unavailable: {e}")

        # Optional Markdown memory sync (glass-box memory you can edit)
        self.markdown_sync = None
        try:
            from ..brain.memory.markdown_sync import get_markdown_sync

            if self.config.memory_markdown_sync_enabled and self.memory_manager and getattr(self.memory_manager, "collection", None):
                self.markdown_sync = get_markdown_sync(self.memory_manager)
                if self.markdown_sync:
                    ok, msg = self.markdown_sync.start()
                    logger.info(f"Markdown memory sync: {msg}")
        except Exception as e:
            logger.warning(f"Markdown memory sync not available: {e}")

        # Initialize Training Data Logger (JSONL for fine-tuning)
        from ..brain.memory.training_logger import TrainingDataLogger
        self.training_logger = TrainingDataLogger(
            log_path=self.config.training_log_path,
            enabled=self.config.training_logging_enabled,
            auto_approve=self.config.training_auto_approve  # Use config value
        )
        logger.info(f"Training Logger initialized: {self.config.training_logging_enabled}")

        # Initialize Gold Data Manager (approved training data workflow)
        try:
            from ..training.gold_data import get_gold_data_manager
            self.gold_data_manager = get_gold_data_manager()
            logger.info("GoldDataManager initialized")
        except Exception as e:
            self.gold_data_manager = None
            logger.warning(f"GoldDataManager not available: {e}")

        # Initialize Learning Engine (categorize + store new knowledge)
        self.learning_engine = None
        self.learning_scheduler = None
        try:
            from ..brain.learning import get_learning_engine
            from ..brain.learning.weekly_trainer import WeeklyLearningScheduler

            self.learning_engine = get_learning_engine(memory_manager=self.memory_manager)
            self.learning_scheduler = WeeklyLearningScheduler()
            self.learning_scheduler.start()
            logger.info("Learning engine initialized")
        except Exception as e:
            logger.warning(f"Learning engine not available: {e}")
        
        # Smart model router for fast responses
        groq_key = os.environ.get("GROQ_API_KEY", "")
        gemini_key = os.environ.get("GOOGLE_AI_KEY", "")
        deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")

        # Initialize Fast LLM Router
        from ..brain.fast_router import FastLLMRouter
        self.fast_router = FastLLMRouter(self.llm)

        self.router = ModelRouter(
            groq_api_key=groq_key,
            gemini_api_key=gemini_key,
            deepseek_api_key=deepseek_key,
            local_llm=self.llm,
            groq_model=getattr(self.config, "groq_model", "llama-3.1-8b-instant"),
            gemini_model=getattr(self.config, "gemini_model", "gemini-2.0-flash"),
            deepseek_model=getattr(self.config, "deepseek_model", "deepseek-chat"),
            prefer_local=getattr(self.config, "llm_prefer_local", True),
        )
        # Replaces IntentDetector
        self.intent_detector = self.fast_router
        
        # Initialize Capability Registry (centralized loader)
        from .capabilities import get_registry
        from .capability_loader import register_all_capabilities
        from ..brain.memory.preferences import get_preference_manager

        self.capability_registry = get_registry()
        
        # Initialize Learning Signal Manager
        from ..brain.memory.learning_signals import get_signal_manager
        self.signal_manager = get_signal_manager()
        
        # Initialize Preference Manager
        from ..brain.memory.preferences import get_preference_manager
        self.preference_manager = get_preference_manager()
        
        # Initialize Retrieval Router (RAG Pipeline)
        from ..brain.memory.retrieval_router import get_retrieval_router
        self.retrieval_router = get_retrieval_router()
        logger.info("RetrievalRouter initialized for RAG pipeline")
        
        # Initialize Deep Reasoner (Phase 3 Integration)
        from ..brain.llm.reasoning import get_deep_reasoner
        get_deep_reasoner(self.llm)
        logger.info("Deep Reasoning Engine initialized")
        # Initialize Robustness Middleware (Phase 6)
        try:
            from .robustness import get_robustness_middleware
            self.robustness = get_robustness_middleware()
            logger.info("Robustness Middleware initialized")
        except ImportError:
            self.robustness = None
            logger.warning("Robustness Middleware not available")
        registration_summary = register_all_capabilities(self.capability_registry, self.config)
        logger.info(
            "Capability Registry initialized with %s capabilities (errors: %s)",
            registration_summary.get("total", 0),
            len(registration_summary.get("errors", [])),
        )

        # Start project watchdogs (post-deployment monitors)
        self.watchdog_manager = None
        try:
            from ..watchdog import get_watchdog_manager

            self.watchdog_manager = get_watchdog_manager()
            ok, msg = self.watchdog_manager.start()
            logger.info(f"Watchdog manager: {msg}")
        except Exception as e:
            logger.warning(f"Watchdog manager not available: {e}")

        # Start the long-running project orchestrator
        self.orchestrator_manager = None
        try:
            from ..orchestrator import get_orchestrator_manager

            self.orchestrator_manager = get_orchestrator_manager()
            ok, msg = self.orchestrator_manager.start()
            logger.info(f"Orchestrator manager: {msg}")
        except Exception as e:
            logger.warning(f"Orchestrator manager not available: {e}")

        # Initialize A2UI service (versioned, declarative agent-to-UI protocol)
        self.a2ui = None
        try:
            from ..interfaces.ui import get_a2ui_service

            self.a2ui = get_a2ui_service()
            logger.info("A2UI service initialized")
        except Exception as e:
            logger.warning(f"A2UI service not available: {e}")

        # Identity vault status update
        try:
            from ..security import get_identity_vault
            vault = get_identity_vault()
            if vault.available:
                self.state_manager.update_feature("identity_vault", status="active", error=None)
            else:
                self.state_manager.update_feature(
                    "identity_vault",
                    enabled=vault.enabled,
                    status="error",
                    error=(vault.unavailable_reason or "identity vault unavailable")[:200],
                )
        except Exception as e:
            logger.warning(f"Security capabilities not available: {e}")
        
        # Initialize Conversation Memory for context tracking
        try:
            from ..brain.memory.conversation_memory import get_conversation_memory
            self.conversation_memory = get_conversation_memory()
            logger.info("Conversation Memory initialized")
        except Exception as e:
            self.conversation_memory = None
            logger.warning(f"Conversation Memory not available: {e}")
        
        # Initialize Preference Manager (Week 2)
        self.preference_manager = get_preference_manager()
        logger.info(f"PreferenceManager initialized: user={self.preference_manager.get('user_name')}")
        
        # Initialize Task Manager (Week 3) and START it
        from ..tasks import get_task_manager
        self.task_manager = get_task_manager()
        self.task_manager.set_reminder_callback(self._on_reminder)
        self.task_manager.start()  # Start background checker
        logger.info("TaskManager initialized and started")

        # Initialize Scheduler for automated workflows (Phase 4)
        try:
            from ..automation import get_scheduler
            self.scheduler = get_scheduler()
            self.scheduler.set_callback(self._run_scheduled_workflow)
            self.scheduler.start()
            logger.info("Scheduler initialized and started")
        except Exception as e:
            logger.warning(f"Scheduler not available: {e}")

        # Initialize Parallel Executor for background tasks (Phase 4)
        try:
            from ..automation.parallel_executor import get_parallel_executor
            self.parallel_executor = get_parallel_executor()
            self.parallel_executor.set_command_handler(self._run_background_command)
            logger.info("Parallel executor initialized")
        except Exception as e:
            logger.warning(f"Parallel executor not available: {e}")

        # Initialize Swarm Integration (v5.1 - Multi-Agent System)
        self.swarm = None
        try:
            from ..swarm.swarm_integration import get_swarm_integration
            self.swarm = get_swarm_integration()
            if self.swarm.initialize():
                logger.info("Swarm Integration initialized - multi-agent routing enabled")
            else:
                logger.info("Swarm Integration disabled (config.swarm_enabled=False)")
        except Exception as e:
            logger.warning(f"Swarm Integration not available: {e}")

        # Initialize Goal Manager (v5.1 - Persistent Goals System)
        self.goal_manager = None
        try:
            from ..brain.goals import get_goal_manager
            self.goal_manager = get_goal_manager()
            self.goal_manager.set_command_callback(self._run_background_command)
            self.goal_manager.start_background_checker(interval_seconds=60)
            logger.info("Goal Manager initialized - persistent goals enabled")
        except Exception as e:
            logger.warning(f"Goal Manager not available: {e}")
        
        # Initialize Executive Brain (v5.1 - Multi-step Task Coordination)
        self.executive = None
        try:
            from .executive import get_executive_brain
            self.executive = get_executive_brain()
            self.executive.set_progress_callback(self._on_executive_progress)
            logger.info("Executive Brain initialized - multi-step coordination enabled")
        except Exception as e:
            logger.warning(f"Executive Brain not available: {e}")

        # Initialize Explainability Engine (Week 4)
        from .explainability import get_explainability
        self.explainability = get_explainability()
        logger.info("ExplainabilityEngine initialized")

        # Metrics collector
        try:
            from .metrics import get_metrics
            self.metrics = get_metrics()
        except Exception:
            self.metrics = None

        # Routing state machine
        try:
            from .routing_fsm import RoutingStateMachine, RoutingState
            self.routing_fsm = RoutingStateMachine()
            self._routing_states = RoutingState
        except Exception:
            self.routing_fsm = None
            self._routing_states = None
        
        self._on_response: Optional[Callable[[str], None]] = None
        self._allow_barge_in = False
        self._last_response: str = ""  # Store for "read it" command
        self._last_response_capability: str = ""  # Track what generated the response
        self._pending_action: Optional[Callable] = None
        self._pending_action_capability: str = ""
        
        # Smart TTS settings
        self._tts_word_threshold = 25  # Responses longer than this offer to read
        self._always_read_capabilities = {  # These always read fully
            "why", "explain", "help", "status", "greeting", "conversation"
        }
        
        # TTS support
        self._tts_enabled = tts_enabled
        self._tts = None
        if tts_enabled:
            try:
                from ..audio.text_to_speech import get_tts
                self._tts = get_tts()
                self._tts.set_callbacks(on_done=self._on_tts_done)
                self._tts.start()
                logger.info("TTS enabled for command responses")
            except Exception as e:
                logger.warning(f"TTS not available: {e}")

    def _on_tts_done(self):
        """Reset barge-in flag after speech finishes."""
        self._allow_barge_in = False
        if self.state_manager.assistant_state == AssistantState.SPEAKING:
            self.state_manager.set_assistant_state(AssistantState.IDLE)

    def _on_executive_progress(self, message: str):
        """Callback for executive brain progress updates."""
        logger.info(f"Executive progress: {message}")
        # Optionally speak progress updates for long tasks
        if self._on_response:
            self._on_response(f"[Progress] {message}")
    
    def set_response_callback(self, callback: Callable[[str], None]):
        """Set callback for command responses."""
        self._on_response = callback
    
    def speak(self, text: str, priority: bool = False, force: bool = False, allow_barge_in: bool = False):
        """Speak text using TTS."""
        logger.debug(f"speak() called: force={force}, auto_speak={self.config.tts_auto_speak}, tts={self._tts}, text={text[:50] if text else 'None'}...")
        if not force and not self.config.tts_auto_speak:
            logger.debug("speak() skipped: tts_auto_speak is False and not forced")
            return
        if self._tts and self._tts.is_available:
            if allow_barge_in or (self.config.tts_allow_barge_in and not force):
                self._allow_barge_in = True
            self.state_manager.set_assistant_state(AssistantState.SPEAKING)
            logger.info(f"TTS speaking: {text[:100]}...")
            self._tts.speak(text, priority=priority)
        else:
            logger.warning(f"TTS not available: tts={self._tts}, available={self._tts.is_available if self._tts else 'N/A'}")

    def stop_speaking(self):
        """Stop any in-progress speech."""
        if self._tts and self._tts.is_available:
            self._tts.stop_speaking()

    def smart_speak(self, response: str, capability_name: str = "") -> None:
        """
        Smart TTS: Speaks short responses, offers to read long ones.
        
        - Short responses (<25 words): Read aloud
        - Long responses: Say "Here's the response. Say 'read it' to hear it."
        - Explanations/help/why: Always read fully
        """
        # Store for "read it" command
        self._last_response = response
        self._last_response_capability = capability_name

        # If auto-speak is enabled, always read the full response.
        if self.config.tts_auto_speak:
            self.speak(response)
            return
        
        # Count words (rough estimate)
        word_count = len(response.split())
        
        # Check if this capability should always be read
        should_always_read = any(
            cap in capability_name.lower() 
            for cap in self._always_read_capabilities
        )
        
        # For short responses or always-read capabilities, speak fully
        if word_count <= self._tts_word_threshold or should_always_read:
            logger.debug(f"Smart TTS: Reading full response ({word_count} words, capability={capability_name})")
            self.speak(response)
        else:
            # Long response - offer to read
            offer_msg = "Here's the response. Say 'read it' if you'd like me to read it aloud."
            logger.info(f"Smart TTS: Offering to read ({word_count} words, capability={capability_name})")
            self.speak(offer_msg)

    def read_last_response(self) -> str:
        """Read the last response aloud (for 'read it' command)."""
        if self._last_response:
            self.speak(self._last_response, force=True, allow_barge_in=True)
            return "Reading the response now."
        else:
            return "There's no recent response to read."

    @property
    def allow_barge_in(self) -> bool:
        """Whether wake-word barge-in should be allowed during TTS."""
        return self._allow_barge_in

    def _format_display_response(self, response: str) -> str:
        """Format response text for display when TTS is off."""
        if self.config.tts_prompt_after_response and not self.config.tts_auto_speak:
            return f"{response}\n\nSay 'read it' if you'd like me to read this aloud."
        return response
    
    def _on_reminder(self, task) -> None:
        """Callback when a reminder is due - speak it via TTS."""
        reminder_msg = f"Reminder: {task.content}"
        logger.info(f"Reminder fired: {task.content}")
        self.speak(reminder_msg, priority=True, force=True, allow_barge_in=True)
        # Also send to UI without re-speaking
        self._respond(reminder_msg, speak=False)

    def _run_scheduled_workflow(self, workflow: str) -> None:
        """Execute a scheduled workflow command."""
        try:
            self.handle(workflow, source="schedule")
        except Exception as e:
            logger.error(f"Scheduled workflow failed: {e}")

    def _run_background_command(self, command: str) -> str:
        """Execute a background command through the main handler."""
        try:
            return self.handle(command, source="background")
        except Exception as e:
            logger.error(f"Background task failed: {e}")
            return f"Background task failed: {e}"

    def _respond(self, message: str, speak: bool = True) -> None:
        """Update UI state and optionally speak a response."""
        display_message = self._format_display_response(message)
        self.state_manager.set_response(display_message, raw=message)
        if self._on_response:
            self._on_response(message)
        if speak:
            self.speak(message)
    
    def handle(self, text: str, source: str = "unknown", context: Optional[Dict[str, Any]] = None) -> str:
        """
        Handle a transcribed command using the Capability Registry.
        
        Flow: STT -> Capability Match -> Action -> Result -> TTS
        No LLM executes OS actions directly - all go through capability handlers.
        
        Args:
            text: Transcribed text from speech
            source: Source of the command (audio, text, etc.)
            context: Optional context (channel/user/session metadata)
            
        Returns:
            Response text
        """
        from .capabilities import ActionResult

        if self.metrics:
            self.metrics.start_pipeline()
        if self.routing_fsm and self._routing_states:
            self.routing_fsm.transition(self._routing_states.RECEIVED)

        # HUD: update pending status early
        try:
            from .context_manager import get_context_manager
            ctx_mgr = get_context_manager()
            pending_ctx = ctx_mgr.get_status()
        except Exception:
            pending_ctx = {}
        self.state_manager.update_hud(
            pending={
                "capability_pending": self.capability_registry.has_pending(),
                **(pending_ctx or {}),
            }
        )

        # Channel/session continuity for conversation memory
        if self.conversation_memory and context:
            session_id = context.get("session_id")
            if not session_id:
                channel = context.get("channel")
                user_id = context.get("user_id")
                if channel and user_id is not None:
                    session_id = f"{channel}:{user_id}"
            if session_id:
                try:
                    self.conversation_memory.set_session(session_id)
                except Exception:
                    pass
        
        new_trace_id()
        
        # =====================================================================
        # PHASE 1: ACOUSTIC STOP - Hard interrupt, NO LLM, NO policy
        # =====================================================================
        from .interrupt_handler import get_interrupt_handler, InterruptType
        interrupt_handler = get_interrupt_handler()
        
        if interrupt_handler.handle_acoustic_stop(text):
            # Stop command handled - kill TTS, return silently
            logger.info(f"Acoustic stop command: '{text}'")
            return ""
        
        # =====================================================================
        # PHASE 2: GARBAGE FILTER - Ignore noise/punctuation
        # =====================================================================
        clean_text = text.strip(" .?!,")
        if not clean_text or len(clean_text) < 2:
            logger.info(f"Ignoring garbage transcript: '{text}'")
            if self.metrics:
                self.metrics.record_error("no_reply")
            return ""
        
        # =====================================================================
        # PHASE 3: CONFIDENCE REPAIR LOOP
        # If transcript came with low confidence marker, ask to repeat
        # =====================================================================
        if text.startswith("__LOW_CONFIDENCE__"):
            logger.info("Low confidence transcript, asking for repeat")
            repair_response = "I didn't catch that clearly. Could you repeat?"
            self._respond(repair_response)
            if self.routing_fsm and self._routing_states:
                self.routing_fsm.transition(self._routing_states.RESPONDED)
            if self.metrics:
                self.metrics.mark_pipeline("routing")
            return repair_response
        
        logger.info(f"Handling command: '{text}'")

        # =====================================================================
        # PHASE 4: DISPATCH ACTIONS (Deterministic Skills)
        # =====================================================================
        # Try the action dispatcher for EVERY request. 
        # This ensures that if a deterministic skill (like battery or system control) 
        # matches keywords, it takes precedence over LLM hallucinations.
        result = self.action_dispatcher.dispatch(text)
        
        if result.success:
            # Check for special marker that actually wants LLM
            if result.message == "__LLM_ROUTE__":
                logger.info("Capability matched but requested LLM route.")
            else:
                logger.info(f"Action executed via Dispatcher: {result.capability_name}")
                response = result.message
                self.conversation_flow.add_assistant_message(response)
                self._respond(response)
                return response
        elif result.message != "No matching capability found.":
            # The capability matched, but the handler returned failure (e.g., "No battery found")
            # We MUST NOT fall back to LLM here or it will hallucinate a value.
            logger.info(f"Action handler failed: {result.message}. Reporting failure.")
            response = result.message
            self.conversation_flow.add_assistant_message(response)
            self._respond(response)
            return response

        # =====================================================================
        # PHASE 5: FAST ROUTING & LLM FALLBACK
        # =====================================================================
        decision = self.fast_router.route(text)
        
        # 1. Update Conversation Context
        self.conversation_flow.add_user_message(text)
        
        logger.info(f"Routing to LLM (Intent: {decision.intent})")
        
        # Use the existing router for LLM generation (keeping existing deep integrations)
        response, source = self.router.route_and_execute(
            text, 
            memory_context="" # Context handled by ConversationFlow/FastRouter now
        )
        
        self.conversation_flow.add_assistant_message(response)
        self._respond(response)
        return response
        
        # =====================================================================
        # PHASE 3.5: CONFIRMATION HANDLING
        # Check if user is confirming a pending action
        # =====================================================================
        confirm_phrases = ["yes", "confirm", "proceed", "do it", "sure", "ok", "go ahead"]
        cancel_phrases = ["no", "cancel", "stop", "abort", "don't"]
        text_lower_clean = text.lower().strip().strip(".,!")
        
        pending = self.action_dispatcher.get_pending_confirmation()
        if pending:
            if any(p == text_lower_clean or text_lower_clean.startswith(p + " ") for p in confirm_phrases):
                logger.info("Confirming pending action via Dispatcher")
                result = self.action_dispatcher.confirm_pending()
                if result:
                    self._process_result(result, text, source)
                return "Confirmed."
            elif any(p == text_lower_clean or text_lower_clean.startswith(p + " ") for p in cancel_phrases):
                logger.info("Cancelling pending action via Dispatcher")
                self.action_dispatcher.cancel_pending()
                self._respond("Cancelled.")
                return "Cancelled."

        
        # =====================================================================
        # PHASE 2.5: ROBUSTNESS PRE-PROCESSING (Phase 6)
        # Validate input, check confidence, resolve pending requests
        # =====================================================================
        if self.robustness:
            robust_response = self.robustness.pre_process(text)
            
            # If middleware handled it (e.g. clarification needed, low confidence)
            if robust_response.needs_followup:
                followup = robust_response.followup_prompt
                # Surface to UI/state so the chat shows the assistant message
                self.state_manager.set_response(followup, raw=followup)
                self.speak(followup)
                return followup
                
            if not robust_response.success:
                msg = robust_response.message
                self._respond(msg)
                return msg
                
            # If middleware resolved a pending request (Confirm/Cancel)
            if robust_response.intent in ("confirm", "cancel"):
                msg = robust_response.message
                self._respond(msg)
                if self.routing_fsm and self._routing_states:
                    self.routing_fsm.transition(self._routing_states.RESPONDED)
                return msg

        # Clear any previous interrupt before normal processing
        interrupt_handler.clear_interrupt()
        
        # =====================================================================
        # PHASE 2.5: CREDENTIAL DETECTION - Detect API keys/tokens in message
        # This runs BEFORE capability matching to catch tokens like Telegram tokens
        # =====================================================================
        try:
            from .credential_detector import get_credential_detector, CredentialType
            credential = get_credential_detector().detect(text)
            
            if credential:
                logger.info(f"Detected credential: {credential.credential_type.value}")
                response = self._handle_credential_detected(credential, text)
                if response:
                    return response
        except Exception as e:
            logger.warning(f"Credential detection failed: {e}")
        
        # =====================================================================
        # PHASE 2.6: SERVICE INTENT DETECTION
        # Detect when user wants to set up a service but hasn't provided credentials
        # e.g., "connect to Telegram" → ask for token
        # =====================================================================
        try:
            from .credential_detector import get_service_intent_detector, ServiceIntent
            from .context_manager import get_context_manager, PendingType
            
            service_intent = get_service_intent_detector().detect(text)
            
            if service_intent and service_intent.intent != ServiceIntent.NONE:
                # Check if we already have the credential for this service
                has_credential = False
                if service_intent.intent == ServiceIntent.TELEGRAM_SETUP:
                    has_credential = bool(self.config.telegram_bot_token)
                elif service_intent.intent == ServiceIntent.GROQ_SETUP:
                    has_credential = bool(self.config.groq_api_key)
                elif service_intent.intent == ServiceIntent.GEMINI_SETUP:
                    has_credential = bool(self.config.google_ai_key)
                elif service_intent.intent == ServiceIntent.GITHUB_SETUP:
                    has_credential = bool(os.environ.get("GITHUB_TOKEN"))
                elif service_intent.intent == ServiceIntent.NOTION_SETUP:
                    has_credential = bool(os.environ.get("NOTION_TOKEN"))
                elif service_intent.intent == ServiceIntent.HASS_SETUP:
                    has_credential = bool(os.environ.get("HASS_URL")) and bool(os.environ.get("HASS_TOKEN"))
                elif service_intent.intent == ServiceIntent.GOOGLE_CALENDAR_SETUP:
                    has_credential = bool(os.environ.get("GOOGLE_CLIENT_ID")) and bool(os.environ.get("GOOGLE_CLIENT_SECRET"))
                
                if not has_credential:
                    # Ask for the credential (prefer A2UI prompt when available)
                    ctx_manager = get_context_manager()

                    prompt_keys = []
                    if service_intent.intent == ServiceIntent.TELEGRAM_SETUP:
                        prompt_keys = ["TELEGRAM_BOT_TOKEN"]
                    elif service_intent.intent == ServiceIntent.GROQ_SETUP:
                        prompt_keys = ["GROQ_API_KEY"]
                    elif service_intent.intent == ServiceIntent.GEMINI_SETUP:
                        prompt_keys = ["GOOGLE_AI_KEY"]
                    elif service_intent.intent == ServiceIntent.GITHUB_SETUP:
                        prompt_keys = ["GITHUB_TOKEN"]
                    elif service_intent.intent == ServiceIntent.NOTION_SETUP:
                        prompt_keys = ["NOTION_TOKEN"]
                    elif service_intent.intent == ServiceIntent.HASS_SETUP:
                        prompt_keys = ["HASS_URL", "HASS_TOKEN"]
                    elif service_intent.intent == ServiceIntent.GOOGLE_CALENDAR_SETUP:
                        prompt_keys = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]

                    prompt = None
                    if self.a2ui and prompt_keys:
                        try:
                            self.a2ui.render_credential_prompt(
                                keys=prompt_keys,
                                title=f"Connect {service_intent.service_name}",
                                description=service_intent.help_text,
                                view_id=f"credentials:setup:{service_intent.intent.value}",
                                source=f"setup:{service_intent.intent.value}",
                            )
                            prompt = (
                                f"Sure, I'd love to help you set up {service_intent.service_name}! "
                                f"I'll need your {service_intent.required_credential}. "
                                "Please enter it in the popup."
                            )
                        except Exception:
                            prompt = None

                    if prompt is None:
                        # Create a conversational prompt fallback
                        prompt = (
                            f"Sure, I'd love to help you set up {service_intent.service_name}! "
                            f"I'll need your {service_intent.required_credential}. "
                            f"\n\n{service_intent.help_text}"
                        )
                    
                    ctx_manager.create_pending_request(
                        request_type=PendingType.CREDENTIAL,
                        prompt=prompt,
                        original_command=text,
                        context={"service": service_intent.service_name.lower()},
                    )
                    
                    self._respond(prompt)
                    return prompt
                else:
                    # Already have the credential, inform user
                    response = (
                        f"Good news - {service_intent.service_name} is already configured! "
                        f"Is there something specific you'd like to do with it?"
                    )
                    self._respond(response)
                    return response
        except Exception as e:
            logger.warning(f"Service intent detection failed: {e}")
        
        try:
            # =====================================================================
            # PHASE 3.1: CONTEXT MANAGER PENDING REQUESTS
            # Handle pending approvals, credentials, and other context-aware requests
            # =====================================================================
            from .context_manager import get_context_manager
            ctx_manager = get_context_manager()
            
            if ctx_manager.has_pending_requests():
                # Process user input through context manager
                was_handled, response_msg, action_result = ctx_manager.process_user_input(text)
                
                if was_handled and response_msg:
                    # Update state and speak response
                    self._respond(response_msg)
                    return response_msg

            # =====================================================================
            # PHASE 3.5: CLARIFICATION HANDLING
            # Check for pending clarifications or if input needs clarification
            # =====================================================================
            from .clarification import get_clarification_manager
            clarification_mgr = get_clarification_manager()

            # Check if this is a response to a pending clarification
            if clarification_mgr.has_pending():
                combined = clarification_mgr.resolve_pending(text)
                if combined:
                    logger.info(f"Clarification resolved, processing: '{combined}'")
                    text = combined  # Use the combined command

            # Check if current input needs clarification
            clarification = clarification_mgr.check_needs_clarification(text)
            if clarification:
                clarification_mgr.set_pending(clarification)
                self._respond(clarification.question)
                if self.routing_fsm and self._routing_states:
                    self.routing_fsm.transition(self._routing_states.PENDING_CONFIRM)
                return clarification.question

            # =====================================================================
            # PHASE 4: LEARNING SIGNALS (PREFERENCES)
            # Detect corrections like "Don't do X" and propose updates
            # =====================================================================
            signals = self.signal_manager.analyze_feedback(text)
            if signals:
                # If we detect a preference correction, prioritize handling it
                # We only handle the first/strongest signal for now
                signal = signals[0]
                if self.learning_engine and signal.signal_type == "correction":
                    try:
                        last_response = self.state_manager.state.last_response_raw
                        last_cap = self.state_manager.state.last_capability
                        self.learning_engine.record_correction(text, last_response, last_capability=last_cap)
                    except Exception:
                        pass
                proposal_text = self.signal_manager.process_signal(signal)
                
                # We structure this as a confirmation request for the next turn
                self.capability_registry.request_confirmation(
                    action_name="update_preference",
                    description=f"save preference: {signal.content}",
                    data=signal.proposed_action,  # Store the proposed update
                    command=text
                )
                self._respond(proposal_text)
                if self.routing_fsm and self._routing_states:
                    self.routing_fsm.transition(self._routing_states.PENDING_CONFIRM)
                return proposal_text
            
            # =====================================================================
            # PHASE 5: EXECUTIVE RECALL (Context Injection)
            # Fetch user preferences & facts relevant to the task
            # =====================================================================
            user_prefs = self.preference_manager.preferences
                
            # RAG Retrieval: Get relevant context based on query type
            rag_context = ""
            try:
                rag_results = self.retrieval_router.retrieve(text, max_results=3)
                rag_context = self.retrieval_router.format_for_llm(rag_results)
                if rag_context:
                    logger.info(f"RAG retrieved {len(rag_results)} context items")
            except Exception as e:
                logger.warning(f"RAG retrieval failed: {e}")

            # HUD: intent + memory context
            try:
                intent = self.intent_detector.detect(text)
                intent_value = intent.intent.value if intent else ""
            except Exception:
                intent_value = ""
            self.state_manager.update_hud(
                intent=intent_value,
                memory_context=rag_context[:1200] if rag_context else "",
            )
            
            context = {
                "source": source,
                "command_handler": self,
                "llm_client": self.llm,
                "user_preferences": user_prefs.to_dict(),
                "rag_context": rag_context,  # Injected RAG context
                "_confirmed": contains_confirm,
            }

            # Try to match a capability
            capability = self.capability_registry.match(text)

            if capability:
                logger.info(f"Matched capability: {capability.name}")
                # HUD: active tools list
                try:
                    active_tools = list(dict.fromkeys([capability.name] + self.state_manager.state.hud_active_tools))
                except Exception:
                    active_tools = [capability.name]
                self.state_manager.update_hud(active_tools=active_tools)
                
                # PHASE 2 FIX: Verb+Object enforcement for action capabilities
                # Action capabilities (open_app, open_url, web_search) need an object
                ACTION_CAPABILITIES = {"open_app", "open_url", "web_search", "browser_navigate"}
                if capability.name in ACTION_CAPABILITIES:
                    # Check if we have an object (more than just the verb)
                    words = text.lower().strip().split()
                    action_verbs = {"open", "launch", "start", "go", "search", "find", "visit"}
                    non_verb_words = [w for w in words if w not in action_verbs and w not in {"to", "for", "the", "a", "an", "please"}]
                    
                    if len(non_verb_words) == 0:
                        # No object specified - ask for clarification
                        clarify_msg = f"What would you like me to {words[0] if words else 'do'}?"
                        logger.info(f"Verb+Object enforcement: missing object for {capability.name}")
                        self._respond(clarify_msg)
                        if self.routing_fsm and self._routing_states:
                            self.routing_fsm.transition(self._routing_states.PENDING_CONFIRM)
                        return clarify_msg

                # Execute capability with Error Recovery
                try:
                    if self.routing_fsm and self._routing_states:
                        self.routing_fsm.transition(self._routing_states.EXECUTING)
                    result = self.capability_registry.execute(
                        capability,
                        text,
                        context,  # Pass the enriched context (with preferences)
                    )

                    # Handle LLM routing (conversation capability)
                    if result.data and result.data.get("use_llm"):
                        return self._handle_llm_query(text, source)

                    return self._process_result(result, text, source)
                except Exception as e:
                    if self.robustness:
                        err_response = self.robustness.wrap_error(e, f"executing {capability.name}")
                        self._respond(err_response.message)
                        return err_response.message
                    raise e


            # No capability matched - try semantic intent classification first
            logger.info("No capability matched, trying semantic intent routing...")
            semantic_capability = self._classify_intent_semantically(text)
            
            if semantic_capability:
                # Found a matching capability through semantic understanding
                logger.info(f"Semantic match found: {semantic_capability}")
                capability = self.capability_registry.get(semantic_capability)
                if capability:
                    if self.routing_fsm and self._routing_states:
                        self.routing_fsm.transition(self._routing_states.EXECUTING)
                    result = self.capability_registry.execute(
                        capability,
                        text,
                        context,  # Pass enriched context
                    )
                    return self._process_result(result, text, source)
                logger.warning("Semantic capability not registered: %s", semantic_capability)
            
            # =====================================================================
            # PHASE 6: SWARM ROUTING (v5.1 - Multi-Agent for Complex Tasks)
            # If task is complex, route to swarm for multi-agent processing
            # =====================================================================
            if self.swarm and self.swarm.is_available and self.swarm.should_use_swarm(text):
                logger.info("Routing to swarm system for complex task processing")
                self.state_manager.set_assistant_state(AssistantState.THINKING)
                if self.metrics:
                    self.metrics.mark_pipeline("routing")

                # Build context from memory and preferences
                swarm_context = f"User Preferences: {user_prefs.to_dict()}\n"
                if rag_context:
                    swarm_context += f"Relevant Context: {rag_context}\n"

                swarm_result = self.swarm.process(text, context=swarm_context)

                if swarm_result.success:
                    logger.info(f"Swarm completed: source={swarm_result.source}, model={swarm_result.model_used}")
                    self._save_to_memory(text, swarm_result.content)
                    self._respond(swarm_result.content)
                    if self.routing_fsm and self._routing_states:
                        self.routing_fsm.transition(self._routing_states.RESPONDED)
                    return swarm_result.content
                else:
                    logger.warning(f"Swarm failed: {swarm_result.error}, falling back to LLM")

            # Truly no match - route to LLM for conversation
            logger.info("No capability matched (even semantically), routing to LLM")
            return self._handle_llm_query(text, source)
        finally:
            if self.metrics:
                try:
                    self.metrics.end_pipeline()
                except Exception:
                    pass
            clear_trace()
    
    def _classify_intent_semantically(self, text: str) -> Optional[str]:
        """
        Use LLM to classify user intent into a capability category.
        Returns the capability name if a match is found, None for general conversation.
        This enables smart routing like a human brain - understanding meaning, not just keywords.
        """
        # Comprehensive capability map covering all Chintu capabilities
        # Format: "capability_name": "description for LLM to understand"
        capability_map = {
            # === SYSTEM CAPABILITIES (Safe) ===
            "list_windows": "asking about open windows, running apps, active applications, what's open",
            "open_app": "asking to open, launch, start an application or website",
            "screenshot": "asking to take a screenshot, capture the screen, screen capture",
            "clipboard": "asking about clipboard contents, what was copied, paste history",
            "system_info": "asking about system info, battery level, CPU usage, memory, disk space",
            "time": "asking about the current time, date, today's date",
            "get_last_opened_app": "asking what was the last app opened",
            "context_query": "asking about current context, which app am I in, active window",
            
            # === SYSTEM CAPABILITIES (Need Confirmation) ===
            "close_app": "asking to close, exit, quit an application or window (NEEDS CONFIRMATION)",
            "volume": "asking to change volume, mute, unmute audio",
            
            # === MEMORY CAPABILITIES ===
            "note": "asking to take a note, save a note, create a note",
            "remember": "asking to remember something, save to memory, store information",
            "recall": "asking to recall something, what did I say about, memory search",
            "forget": "asking to forget, delete memory, remove from memory (NEEDS CONFIRMATION)",
            
            # === TASK CAPABILITIES ===
            "add_task": "asking to create a task, add a reminder, schedule something",
            "list_tasks": "asking about tasks, show my tasks, what's on my list",
            "complete_task": "asking to mark task as done, complete a task",
            "delete_task": "asking to delete or remove a task (NEEDS CONFIRMATION)",
            
            # === FILE CAPABILITIES ===
            "read_document": "asking to read a file, document, PDF, summarize a file",
            "find_file": "asking to find a file, search for a file, locate a document",
            "open_file": "asking to open a specific file or document",
            "delete_file": "asking to delete a file (HIGH RISK - NEEDS CONFIRMATION)",
            
            # === SEARCH CAPABILITIES ===
            "live_search": "asking to search the web, Google something, find information online",
            "deep_research": "asking for deep research, detailed analysis, comprehensive info",
            "browse_url": "asking to read a URL, summarize a webpage, browse a link",
            
            # === PREFERENCES ===
            "set_preference": "asking to change settings, preferences, my name, location",
            "get_preference": "asking about current settings or preferences",
            
            # === SCREEN CONTROL & VISION ===
            "mouse_click": "asking to click, press, tap a button or element (NEEDS CONFIRMATION)",
            "screen_find": "asking to find, locate, search for an element on the screen",
            "type_text": "asking to type something, enter text (NEEDS CONFIRMATION)",
            "scroll": "asking to scroll up, down, on screen",
            
            # === AUTOMATION ===
            "repeat_command": "asking to do it again, repeat that, one more time",
            "schedule_task": "asking to schedule something for later, run at a time",

            # === CODING AGENT ===
            "fix_code": "asking to fix code, debug a file, resolve errors, run tests and apply a fix",
            
            # === HELP ===
            "help": "asking for help, what can you do, capabilities",
            "status": "asking about system status, health check, are you working",
            "why": "asking why something happened, explain your reasoning",
        }
        
        # Build the classification prompt
        categories_text = "\n".join([f"- {name}: {desc}" for name, desc in capability_map.items()])
        
        prompt = f"""You are an intent classifier for a voice assistant. Classify this user request into ONE capability category.

IMPORTANT: If the request requires a SYSTEM ACTION (opening apps, listing windows, searching, etc.), you MUST classify it - don't say "none".
Only reply "none" for pure casual conversation like "hi", "how are you", "tell me a joke".

Capabilities:
{categories_text}
- none: ONLY for casual conversation that requires NO system action

User said: "{text}"

Reply with ONLY the capability name (e.g., "list_windows" or "open_app" or "none").
If you are less than 70% sure, reply "none".
However, if the user is clearly asking for a system action but you are unsure of the specific capability, choose the closest match rather than "none".
No explanation."""

        try:
            # Use fast/cheap model for classification - check API key directly
            groq_api_key = None
            if self.model_router and hasattr(self.model_router, '_groq_api_key'):
                groq_api_key = self.model_router._groq_api_key
            
            if not groq_api_key:
                # Try from environment
                import os
                groq_api_key = os.environ.get("GROQ_API_KEY")
            
            if groq_api_key:
                import httpx
                logger.debug("Attempting semantic classification via Groq...")
                response = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "llama-3.1-8b-instant",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 20,
                        "temperature": 0
                    },
                    timeout=5.0  # Slightly longer timeout
                )
                if response.status_code == 200:
                    result = response.json()["choices"][0]["message"]["content"].strip().lower()
                    # Clean up the result (remove quotes, extra text)
                    result = result.replace('"', '').replace("'", "").strip()
                    if ":" in result:
                        result = result.split(":")[0].strip()  # Handle "list_windows: asking about..."
                    logger.info(f"Semantic classification: '{result}'")
                    if result in capability_map:
                        return result
                    logger.debug(f"Semantic result '{result}' not in capability_map")
                else:
                    logger.debug(f"Semantic classification HTTP {response.status_code}")
            else:
                logger.debug("No Groq API key available for semantic routing")
        except Exception as e:
            logger.debug(f"Semantic intent classification failed: {e}")
        
        return None
    
    def _process_result(self, result: "ActionResult", text: str, source: str) -> str:
        """Process an ActionResult and handle TTS/logging."""
        response = result.message
        sensitive = False
        meta = {
            "source": source,
            "capability": result.capability_name,
            "success": result.success,
            "requires_confirmation": result.requires_confirmation,
            "model_source": "rule",
        }
        
        # Track action for explainability (Week 4)
        cap = self.capability_registry.get(result.capability_name)
        triggers_matched = []
        if cap:
            triggers_matched = [t for t in cap.triggers if t.lower() in text.lower()]
            self.explainability.record_action(
                user_input=text,
                capability_name=result.capability_name,
                action_description=cap.description if cap else "action",
                success=result.success,
                triggers_matched=triggers_matched,
                response=response
            )
        
        # Speak the response (or a forced alternate) using smart TTS
        force_speak_text = None
        if result.requires_confirmation and result.pending_action:
            self._pending_action = result.pending_action
            self._pending_action_capability = result.capability_name
        if result.data and isinstance(result.data, dict):
            sensitive = bool(result.data.get("sensitive"))
            response = str(result.data.get("safe_message") or response)
            if not sensitive:
                force_speak_text = result.data.get("speak_text") if result.data.get("force_speak") else None
            # A2UI structured render (tables/cards)
            if self.a2ui and result.data.get("ui_table"):
                try:
                    table = result.data.get("ui_table", {})
                    self.a2ui.render_table(
                        title=table.get("title", "Details"),
                        columns=table.get("columns", []),
                        rows=table.get("rows", []),
                        view_id=table.get("view_id"),
                    )
                except Exception:
                    pass
        if force_speak_text:
            self.speak(force_speak_text, force=True, allow_barge_in=True, priority=True)
        else:
            # Use smart_speak for intelligent long response handling
            self.smart_speak(response, result.capability_name)
        
        # Send response callback
        if self._on_response:
            self._on_response(response)

        if self.metrics:
            self.metrics.mark_pipeline("routing")
            self.metrics.record_model_usage(meta.get("model_source", "rule"), reason="capability", query_length=len(text), success=result.success)
            if not result.success:
                self.metrics.record_error("tool_failed")
        
        # Save to memory (ChromaDB) - ONLY if action was SUCCESSFUL and not a confirmation
        # This prevents polluting memory with failed actions or pending confirmations
        should_save_memory = (
            self.config.memory_enabled 
            and result.success 
            and not result.requires_confirmation
            and not sensitive
            and result.capability_name != "conversation"  # LLM chat is not saved
        )
        if should_save_memory and self.memory_manager:
            self.memory_manager.save_interaction("user", text)
            self.memory_manager.save_interaction("assistant", response, meta)
        
        # Save to training log (JSONL) - ONLY for successful non-confirmation results
        should_save_training = (
            self.config.training_logging_enabled 
            and result.success 
            and not result.requires_confirmation
            and not sensitive
        )
        if should_save_training:
            self.training_logger.log_interaction(text, response, meta)
            if self.gold_data_manager:
                self.gold_data_manager.log_interaction(
                    user_input=text,
                    assistant_response=response,
                    capability_used=result.capability_name,
                    model_used=meta.get("model_source", "rule"),
                )

        # Learning engine: categorize and store new knowledge
        if self.learning_engine:
            try:
                self.learning_engine.observe_interaction(
                    user_text=text,
                    assistant_text=response,
                    result=result,
                    meta=meta,
                    source=source,
                    sensitive=sensitive,
                )
            except Exception:
                pass

        self.state_manager.set_response(
            self._format_display_response(response),
            raw=response,
        )
        self.state_manager.set_debug_info(
            last_capability=result.capability_name,
            last_model="rule",
            trace_id=get_trace_id(),
        )
        if self.routing_fsm and self._routing_states:
            self.routing_fsm.transition(self._routing_states.RESPONDED)

        # Update feature status
        feature_map = {
            "open_app": "app_control",
            "open_url": "app_control",
            "note_taking": "voice_commands",
            "system_info": "voice_commands",
            "conversation": "llm_integration",
        }
        feature = feature_map.get(result.capability_name)
        if feature:
            self.state_manager.update_feature(feature, enabled=True, status="inactive")
        
        return response
    
    def _handle_llm_query(self, text: str, source: str) -> str:
        """Handle a query that requires LLM processing."""
        # Mark LLM as active
        self.state_manager.update_feature("llm_integration", enabled=True, status="active")
        
        # Use existing _handle_question logic for LLM streaming
        command_obj = self.parser.parse(text)
        response, meta = self._handle_question(command_obj)
        meta["source"] = source
        meta["capability"] = "conversation"
        
        # Speak if not already streamed
        if not meta.get("streaming_tts"):
            self.speak(response)
        
        # NEW: Save conversation to memory for context retention
        if self.conversation_memory:
            self.conversation_memory.add_turn("user", text, capability="conversation")
            self.conversation_memory.add_turn("assistant", response, capability="conversation")
        
        # NEW: Save important exchanges to ChromaDB for semantic retrieval
        if self.memory_manager and len(text.split()) > 3:
            try:
                self.memory_manager.save_interaction("user", text)
                # Only save first 500 chars of response to avoid bloating memory
                self.memory_manager.save_interaction("assistant", response[:500] if len(response) > 500 else response)
            except Exception as e:
                logger.warning(f"Failed to save conversation to ChromaDB: {e}")

        if self.learning_engine:
            try:
                self.learning_engine.observe_interaction(
                    user_text=text,
                    assistant_text=response,
                    result=None,
                    meta=meta,
                    source=source,
                    sensitive=False,
                )
            except Exception:
                pass
        
        self.state_manager.set_response(
            self._format_display_response(response),
            raw=response,
        )
        self.state_manager.set_debug_info(
            last_capability="conversation",
            last_model=meta.get("model_source", "llm"),
            trace_id=get_trace_id(),
        )
        self.state_manager.update_feature("llm_integration", enabled=True, status="inactive")
        
        return response
    
    def explain_last_action(self) -> str:
        """Explain why the last action was taken (explainability mode)."""
        # This will be enhanced in Week 4
        return "I processed your command using the capability registry."
    
    def _handle_credential_detected(self, credential, text: str) -> Optional[str]:
        """
        Handle a detected credential (API key, token, etc.).
        
        Instead of auto-saving, asks for user confirmation first.
        Returns a response string asking for confirmation.
        """
        from .credential_detector import CredentialType
        from .context_manager import get_context_manager, PendingType
        
        # Get friendly descriptions for each credential type
        credential_info = {
            CredentialType.TELEGRAM_BOT_TOKEN: {
                "name": "Telegram bot token",
                "action": "save this token and connect to your Telegram bot",
                "service": "telegram",
            },
            CredentialType.GROQ_API_KEY: {
                "name": "Groq API key",
                "action": "save this key for faster AI responses",
                "service": "groq",
            },
            CredentialType.GEMINI_API_KEY: {
                "name": "Gemini API key", 
                "action": "save this key for Google AI features",
                "service": "gemini",
            },
            CredentialType.OPENAI_API_KEY: {
                "name": "OpenAI API key",
                "action": "save this key for GPT features",
                "service": "openai",
            },
            CredentialType.GITHUB_TOKEN: {
                "name": "GitHub token",
                "action": "save this token for GitHub integrations",
                "service": "github",
            },
            CredentialType.NOTION_TOKEN: {
                "name": "Notion token",
                "action": "save this token for Notion integrations",
                "service": "notion",
            },
            CredentialType.HASS_URL: {
                "name": "Home Assistant URL",
                "action": "save this URL for Home Assistant",
                "service": "hass_url",
            },
            CredentialType.HASS_TOKEN: {
                "name": "Home Assistant token",
                "action": "save this token for Home Assistant",
                "service": "hass_token",
            },
            CredentialType.GOOGLE_CLIENT_ID: {
                "name": "Google client ID",
                "action": "save this client ID for Google Calendar",
                "service": "google_client_id",
            },
            CredentialType.GOOGLE_CLIENT_SECRET: {
                "name": "Google client secret",
                "action": "save this client secret for Google Calendar",
                "service": "google_client_secret",
            },
        }
        
        info = credential_info.get(credential.credential_type)
        if not info:
            return None
        
        # Get context manager and register callback if not already done
        ctx_manager = get_context_manager()
        
        # Register the save_detected_credential callback
        if "save_detected_credential" not in ctx_manager.callbacks:
            ctx_manager.callbacks["save_detected_credential"] = self._execute_credential_save
        
        # Create a masked preview of the credential for verification
        # Show first 10 chars and last 4 chars, mask the middle
        cred_value = credential.value
        if len(cred_value) > 16:
            masked_preview = f"{cred_value[:10]}...{cred_value[-4:]}"
        else:
            masked_preview = f"{cred_value[:4]}...{cred_value[-4:]}"
        
        # Create a confirmation request instead of auto-saving
        prompt = (
            f"I noticed you shared a {info['name']}:\n\n"
            f"   `{masked_preview}`\n\n"
            f"Would you like me to {info['action']}? Just say 'yes' or 'no'."
        )
        
        ctx_manager.create_pending_request(
            request_type=PendingType.APPROVAL,
            prompt=prompt,
            original_command=text,
            callback_name="save_detected_credential",
            context={
                "credential_type": credential.credential_type.value,
                "credential_value": credential.value,
                "service": info["service"],
                "service_name": credential.service_name,
            },
        )
        
        # Speak and return the confirmation prompt
        self.speak(prompt)
        if self._on_response:
            self._on_response(prompt)
        self.state_manager.set_response(prompt, raw=prompt)
        
        return prompt

    def _execute_credential_save(self, request) -> str:
        """
        Callback executed when user confirms saving a credential.
        This is called by ConversationContextManager when user says 'yes'.
        """
        from .credential_detector import CredentialType
        from dataclasses import dataclass
        
        # Reconstruct credential info from context
        cred_type_str = request.context.get("credential_type", "")
        cred_value = request.context.get("credential_value", "")
        service = request.context.get("service", "")
        service_name = request.context.get("service_name", "")
        
        if not cred_value:
            return "Hmm, I couldn't find the credential to save. Could you try again?"
        
        # Create a simple object to pass to save methods
        @dataclass
        class CredentialData:
            value: str
            service_name: str
        
        credential = CredentialData(value=cred_value, service_name=service_name)
        
        # Save based on service type
        try:
            if service == "telegram":
                response = self._save_telegram_token(credential)
            elif service == "groq":
                response = self._save_api_key_to_env("GROQ_API_KEY", cred_value, "Groq")
            elif service == "gemini":
                response = self._save_api_key_to_env("GOOGLE_AI_KEY", cred_value, "Gemini")
            elif service == "openai":
                response = self._save_api_key_to_env("OPENAI_API_KEY", cred_value, "OpenAI")
            elif service == "github":
                response = self._save_api_key_to_env("GITHUB_TOKEN", cred_value, "GitHub")
            elif service == "notion":
                response = self._save_api_key_to_env("NOTION_TOKEN", cred_value, "Notion")
            elif service == "hass_url":
                response = self._save_api_key_to_env("HASS_URL", cred_value, "Home Assistant URL")
            elif service == "hass_token":
                response = self._save_api_key_to_env("HASS_TOKEN", cred_value, "Home Assistant token")
            elif service == "google_client_id":
                response = self._save_api_key_to_env("GOOGLE_CLIENT_ID", cred_value, "Google client ID")
            elif service == "google_client_secret":
                response = self._save_api_key_to_env("GOOGLE_CLIENT_SECRET", cred_value, "Google client secret")
            else:
                response = f"Saved your {service_name} credentials!"
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to save credential: {e}")
            error_msg = f"I had trouble saving that - {str(e)[:50]}. Want to try again?"
            return error_msg

    def _save_telegram_token(self, credential) -> str:
        """Save Telegram bot token and attempt to connect."""
        from pathlib import Path
        import os
        
        # Save to .env file
        env_path = Path.cwd() / ".env"
        self._update_env_file(env_path, {
            "TELEGRAM_BOT_TOKEN": credential.value,
            "CHINTU_TELEGRAM_ENABLED": "true",
        })
        
        # Update runtime config
        os.environ["TELEGRAM_BOT_TOKEN"] = credential.value
        os.environ["CHINTU_TELEGRAM_ENABLED"] = "true"
        
        # Try to restart the Telegram gateway
        try:
            from ..io import get_telegram_gateway
            gateway = get_telegram_gateway()
            # Force rebuild config with new token
            gateway._tg = gateway._build_config()
            ok, msg = gateway.start()
            
            if ok:
                logger.info(f"Telegram gateway started successfully: {msg}")
                return (
                    "Perfect! I've saved your Telegram bot token and connected to it. "
                    "You should be able to send me messages through Telegram now! "
                    "Just send /start to your bot to get started. 🎉"
                )
            else:
                logger.warning(f"Telegram gateway start returned: {msg}")
                return (
                    f"Got it! I saved your Telegram bot token. "
                    f"I tried to connect but got: {msg}. "
                    "You might need to restart me for the full Telegram integration to work."
                )
        except Exception as e:
            logger.warning(f"Could not start Telegram gateway: {e}")
            return (
                "I saved your Telegram bot token to the configuration. "
                "Please restart me to activate the Telegram connection!"
            )

    def _save_api_key_to_env(self, env_key: str, value: str, service_name: str) -> str:
        """Save an API key to the .env file."""
        from pathlib import Path
        import os
        
        env_path = Path.cwd() / ".env"
        self._update_env_file(env_path, {env_key: value})
        
        # Update runtime environment
        os.environ[env_key] = value
        
        return (
            f"I saved your {service_name} API key! "
            f"It'll be active after you restart me, or you can continue using me "
            f"with the current configuration."
        )

    def _update_env_file(self, env_path, updates: dict) -> None:
        """
        Update .env file with new key-value pairs.
        Creates the file if it doesn't exist.
        Updates existing keys, appends new ones.
        """
        import re
        
        # Read existing content
        content = ""
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
        
        lines = content.splitlines()
        updated_keys = set()
        
        # Update existing keys
        for i, line in enumerate(lines):
            for key, value in updates.items():
                if line.strip().startswith(f"{key}=") or line.strip().startswith(f"{key} ="):
                    lines[i] = f"{key}={value}"
                    updated_keys.add(key)
                    break
        
        # Append new keys
        for key, value in updates.items():
            if key not in updated_keys:
                lines.append(f"{key}={value}")
        
        # Write back
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info(f"Updated .env with keys: {list(updates.keys())}")

    def _execute(self, command: Command) -> Tuple[str, Dict[str, Any]]:
        """Execute a parsed command."""
        try:
            if command.type == CommandType.OPEN_URL:
                return self._handle_open_url(command)
            
            elif command.type == CommandType.OPEN_APP:
                return self._handle_open_app(command)
            
            elif command.type == CommandType.SEARCH_JOBS:
                return self._handle_job_search(command)
            
            elif command.type == CommandType.DRAFT_RESUME:
                return self._handle_draft_resume(command)
            
            elif command.type == CommandType.DRAFT_SOP:
                return self._handle_draft_sop(command)
            
            elif command.type == CommandType.DRAFT_EMAIL:
                return self._handle_draft_email(command)
            
            elif command.type == CommandType.ASK_QUESTION:
                return self._handle_question(command)
            
            else:
                return (
                    f"I'm not sure how to handle that command: {command.raw_text}",
                    self._meta(command, "rule"),
                )
                
        except Exception as e:
            logger.error(f"Error executing command: {e}")
            return (f"Sorry, there was an error: {str(e)}", self._meta(command, "error"))

    def _meta(self, command: Command, model_source: str) -> Dict[str, Any]:
        return {
            "command_type": command.type.value,
            "model_source": model_source,
        }

    def _feature_for_command(self, command: Command) -> Optional[str]:
        if command.type in (CommandType.OPEN_URL, CommandType.OPEN_APP):
            return "app_control"
        if command.type == CommandType.SEARCH_JOBS:
            return "job_search"
        if command.type in (
            CommandType.DRAFT_RESUME,
            CommandType.DRAFT_SOP,
            CommandType.DRAFT_EMAIL,
            CommandType.ASK_QUESTION,
        ):
            return "llm_integration"
        return None
    
    def _handle_open_url(self, command: Command) -> Tuple[str, Dict[str, Any]]:
        """Handle opening a URL."""
        url = command.target
        app_name = command.parameters.get("app_name", url)
        
        if self.launcher.open_url(url):
            self.state_manager.update_feature("app_control", enabled=True, status="active")
            return f"Opening {app_name}", self._meta(command, "rule")
        return f"Sorry, I couldn't open {app_name}", self._meta(command, "rule")
    
    def _handle_open_app(self, command: Command) -> Tuple[str, Dict[str, Any]]:
        """Handle launching an application."""
        app = command.target
        app_name = command.parameters.get("app_name", app)
        
        if self.launcher.launch_app(app):
            self.state_manager.update_feature("app_control", enabled=True, status="active")
            return f"Launching {app_name}", self._meta(command, "rule")
        return f"Sorry, I couldn't launch {app_name}", self._meta(command, "rule")
    
    def _handle_job_search(self, command: Command) -> Tuple[str, Dict[str, Any]]:
        """Handle job search."""
        role = command.target or "software engineer"
        role, location = JobSearcher.parse_job_query(role)
        
        if self.job_searcher.search(role, location=location):
            self.state_manager.update_feature("job_search", enabled=True, status="active")
            return (
                f"Searching for {role} jobs" + (f" in {location}" if location else ""),
                self._meta(command, "rule"),
            )
        return f"Sorry, I couldn't search for jobs", self._meta(command, "rule")
    
    def _handle_draft_resume(self, command: Command) -> Tuple[str, Dict[str, Any]]:
        """Handle resume drafting."""
        self.state_manager.set_assistant_state(AssistantState.THINKING)
        self.state_manager.update_feature("llm_integration", enabled=True, status="active")
        
        role = command.target or "software engineer"
        response = self.llm.draft_resume(role)
        return response, self._meta(command, "local")
    
    def _handle_draft_sop(self, command: Command) -> Tuple[str, Dict[str, Any]]:
        """Handle SOP drafting."""
        self.state_manager.set_assistant_state(AssistantState.THINKING)
        self.state_manager.update_feature("llm_integration", enabled=True, status="active")
        
        program = command.target or "Masters in Computer Science"
        response = self.llm.draft_sop(program)
        return response, self._meta(command, "local")
    
    def _handle_draft_email(self, command: Command) -> Tuple[str, Dict[str, Any]]:
        """Handle email drafting."""
        self.state_manager.set_assistant_state(AssistantState.THINKING)
        self.state_manager.update_feature("llm_integration", enabled=True, status="active")
        
        purpose = command.target or command.raw_text
        response = self.llm.draft_email(purpose)
        return response, self._meta(command, "local")
    
    def _handle_question(self, command: Command) -> Tuple[str, Dict[str, Any]]:
        
        question = command.parameters.get("question", command.raw_text)
        import time
        
        # Retrieve context from memory
        memory_context = ""
        user_profile = ""
        conversation_context = ""
        
        # NEW: Get recent conversation history for multi-turn context
        if self.conversation_memory:
            conversation_context = self.conversation_memory.get_context(max_turns=6)
        
        if self.config.memory_enabled and self.memory_manager:
            memory_context = self.memory_manager.retrieve_context(question, n_results=self.config.memory_top_k)
            user_profile = self.memory_manager.get_profile_context()
        
        # Build comprehensive context with conversation history
        context_parts = []
        if user_profile.strip():
            context_parts.append(f"User Info:\n{user_profile}")
        if conversation_context.strip():
            context_parts.append(f"Recent Conversation:\n{conversation_context}")
        if memory_context.strip():
            context_parts.append(f"Relevant Memories:\n{memory_context}")
        
        full_context = "\n\n".join(context_parts)
        intent = self.intent_detector.detect(question)
        
        # Use smart router for streaming responses with streaming TTS
        full_response = []
        first_chunk = True
        source = "none"
        sentence_buffer = ""  # Buffer to accumulate complete sentences
        spoken_text = ""  # Track what we've already spoken
        streaming_tts_enabled = bool(
            self._tts and self._tts_enabled and self.config.tts_auto_speak and self.config.tts_streaming
        )
        timeout_seconds = getattr(self.config, "llm_stream_timeout", 12.0)
        start_time = time.time()
        
        try:
            for chunk, src in self.router.route_and_stream(question, full_context):
                if time.time() - start_time > timeout_seconds:
                    raise TimeoutError(f"LLM stream exceeded {timeout_seconds}s")
                source = src
                full_response.append(chunk)
                sentence_buffer += chunk
                
                if first_chunk:
                    first_chunk = False
                    logger.info(f"First token received from {source}")
                
                # Update state with partial response for live display
                self.state_manager.set_response("".join(full_response))
                
                # Streaming TTS: Speak complete sentences as they arrive
                if streaming_tts_enabled:
                    # Check for sentence endings
                    for end_char in ['.', '!', '?', '\n']:
                        if end_char in sentence_buffer:
                            # Split at sentence boundary
                            parts = sentence_buffer.split(end_char, 1)
                            sentence_to_speak = parts[0] + end_char
                            sentence_buffer = parts[1] if len(parts) > 1 else ""
                            
                            # Only speak if it's meaningful (not just punctuation)
                            clean_sentence = sentence_to_speak.strip()
                            if len(clean_sentence) > 3 and clean_sentence not in spoken_text:
                                self._tts.speak(clean_sentence)
                                spoken_text += clean_sentence + " "
                            break
                
        except Exception as e:
            logger.error(f"Router error: {e}")
            # Fall back to local LLM
            try:
                response = self.llm.answer_question(question)
                return response, self._meta(command, "local")
            except Exception as e2:
                logger.error(f"Fallback error: {e2}")
                # Provide helpful fallback message
                fallback_messages = [
                    "I'm having trouble reaching the model right now. Please try again.",
                    "Connection hiccup—could you try that again in a moment?",
                    "I didn't get a response from the model. Please rephrase or retry.",
                ]
                import random
                return random.choice(fallback_messages), self._meta(command, "error")
        
        # Speak any remaining text in buffer
        if streaming_tts_enabled and sentence_buffer.strip():
            remaining = sentence_buffer.strip()
            if remaining and remaining not in spoken_text:
                self._tts.speak(remaining)
        
        response = "".join(full_response)
        logger.info(f"Response from {source}: {len(response)} chars")
        meta = self._meta(command, source)
        meta["intent"] = intent.intent.value
        meta["streaming_tts"] = streaming_tts_enabled  # Mark if already spoken
        return response, meta
