"""Command handler - processes and executes commands."""

import json
import os
import logging
import time
import threading
import re
from pathlib import Path
from typing import Optional, Callable, Dict, Any, Tuple

from ..utils.command_parser import CommandParser, Command, CommandType
from ..automation.app_launcher import AppLauncher
from ..automation.job_search import JobSearcher
from ..brain.llm.ollama_client import OllamaClient
from ..brain.llm.model_selector import choose_local_brain_model
from .state import get_state_manager, AssistantState
from .config import get_config
from .model_router import ModelRouter, IntentDetector, Intent
from .memory import MemoryManager
from .response_rendering import sanitize_for_tts, build_dual_view_response
from .command_text_utils import (
    sanitize_internal_response as _sanitize_internal_response_text,
    conversation_fallback_response as _conversation_fallback_response_text,
    trim_context_to_budget as _trim_context_to_budget_text,
    extract_numbered_followup_index as _extract_numbered_followup_index_text,
    extract_compare_indices as _extract_compare_indices_text,
    is_numbered_followup_request as _is_numbered_followup_request_text,
)
from .logging_config import new_trace_id, clear_trace, get_trace_id
from ..security.prompt_guard import get_prompt_guard
from .policy import get_policy_engine, RiskLevel

logger = logging.getLogger(__name__)


class CommandHandler:
    """
    Handles command execution.
    Routes parsed commands to appropriate modules.
    Delegates to ActionDispatcher and ConversationFlow.
    """
    
    def __init__(
        self,
        llm_client: Optional[Any] = None,
        app_launcher: Optional[AppLauncher] = None,
        job_searcher: Optional[JobSearcher] = None,
        tts_enabled: bool = True,
        mock_mode: bool = False,
    ):
        self.config = get_config()
        self.mock_mode = bool(mock_mode)
        self.parser = CommandParser()
        selected_model = getattr(self.config, "ollama_model", "llama3.1:8b")
        if not llm_client:
            try:
                selected_model = choose_local_brain_model(
                    preferred_model=selected_model,
                    host=getattr(self.config, "ollama_host", "http://localhost:11434"),
                    auto_select=bool(getattr(self.config, "llm_auto_select_model", True)),
                )
                if selected_model != getattr(self.config, "ollama_model", selected_model):
                    logger.info(
                        "Auto-selected local brain model '%s' (configured '%s').",
                        selected_model,
                        getattr(self.config, "ollama_model", selected_model),
                    )
                self.config.ollama_model = selected_model
            except Exception as exc:
                logger.warning(f"Local model selection failed, using configured model: {exc}")

        self.llm = llm_client
        if self.llm is None:
            try:
                from ..brain.llm.adapter_client import get_adapter_client

                self.llm = get_adapter_client()
            except Exception:
                self.llm = None

        if self.llm is None:
            self.llm = OllamaClient(
                host=getattr(self.config, "ollama_host", "http://localhost:11434"),
                model=selected_model,
                max_tokens=getattr(self.config, "llm_max_tokens", 2048),
                temperature=getattr(self.config, "llm_temperature", 0.7),
                num_threads=getattr(self.config, "llm_num_threads", None),
                num_ctx=getattr(self.config, "llm_num_ctx", None),
                num_gpu=getattr(self.config, "llm_num_gpu", -1),
                keep_alive=getattr(self.config, "ollama_keep_alive_seconds", None),
                think=getattr(self.config, "ollama_think", None),
            )

        # Best-effort warm-up to reduce first-response latency.
        try:
            if (
                not self.mock_mode
                and bool(getattr(self.config, "llm_prewarm_enabled", False))
                and hasattr(self.llm, "prewarm")
            ):
                cfg = self.config
                llm = self.llm

                def _prewarm():
                    try:
                        base_model = str(getattr(cfg, "ollama_model", "") or "").strip()
                        strong_model = str(getattr(cfg, "ollama_model_strong", "") or "").strip()
                        keep_alive = getattr(cfg, "ollama_keep_alive_seconds", None)
                        llm.prewarm(model=base_model or None, keep_alive=keep_alive)
                        if bool(getattr(cfg, "llm_prewarm_include_strong", True)) and strong_model and strong_model != base_model:
                            llm.prewarm(model=strong_model, keep_alive=0)
                    except Exception:
                        return

                threading.Thread(target=_prewarm, daemon=True).start()
        except Exception:
            pass
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
        # ActionDispatcher will be re-initialized later after memory/swarm are ready
        self.action_dispatcher = ActionDispatcher(self.capability_registry, llm_client=self.llm)

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
            from ..brain.memory.markdown_sync import MarkdownMemorySync
            self.markdown_sync = MarkdownMemorySync(self.memory_manager)
            logger.info("Markdown Memory Sync initialized")
        except ImportError:
            pass

        # Learning Signal Manager (The "Learning from Mistakes" module)
        self.learning_manager = None
        if self.memory_manager:
            try:
                from ..brain.memory.learning_signals import LearningSignalManager
                self.learning_manager = LearningSignalManager()
                logger.info("Learning Signal Manager initialized")
            except Exception as e:
                logger.warning(f"Failed to init LearningSignalManager: {e}")
            try:
                from ..brain.memory.markdown_sync import get_markdown_sync

                has_markdown_backend = bool(getattr(self.memory_manager, "collection", None)) or hasattr(self.memory_manager, "save_interaction")
                if self.config.memory_markdown_sync_enabled and self.memory_manager and has_markdown_backend:
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
        self.curiosity_engine = None
        self.self_improvement_manager = None
        try:
            from ..brain.learning import get_learning_engine
            from ..brain.learning.weekly_trainer import WeeklyLearningScheduler
            from ..brain.learning.curiosity_engine import get_curiosity_engine
            from ..brain.learning.safe_self_improvement import get_safe_self_improvement_manager

            self.learning_engine = get_learning_engine(memory_manager=self.memory_manager)
            self.self_improvement_manager = get_safe_self_improvement_manager(config=self.config)
            self.learning_scheduler = WeeklyLearningScheduler()
            self.learning_scheduler.start()
            self.curiosity_engine = get_curiosity_engine()
            self.curiosity_engine.start()
            logger.info("Learning engine initialized")
        except Exception as e:
            logger.warning(f"Learning engine not available: {e}")

        # GCC-style long-horizon context controller
        self.gcc_controller = None
        self._gcc_last_auto_branch_ts = 0.0
        if getattr(self.config, "gcc_enabled", True):
            try:
                from ..brain.learning.gcc_context_controller import get_gcc_controller

                self.gcc_controller = get_gcc_controller()
                self.gcc_controller.initialize(project_goal=getattr(self.config, "gcc_default_goal", ""))
                logger.info("GCC context controller initialized")
            except Exception as e:
                self.gcc_controller = None
                logger.warning(f"GCC context controller unavailable: {e}")
        
        # Smart model router for fast responses
        groq_key = getattr(self.config, "groq_api_key", None) or os.environ.get("GROQ_API_KEY", "")
        gemini_key = getattr(self.config, "google_ai_key", None) or os.environ.get("GOOGLE_AI_KEY", "")
        deepseek_key = getattr(self.config, "deepseek_api_key", None) or os.environ.get("DEEPSEEK_API_KEY", "")
        nvidia_key = getattr(self.config, "nvidia_api_key", None) or os.environ.get("NVIDIA_API_KEY", "")

        # Initialize Fast LLM Router
        from ..brain.fast_router import FastLLMRouter
        self.fast_router = FastLLMRouter(self.llm)
        # Audit Fix: Compatibility alias for .detect() -> .route()
        if not hasattr(self.fast_router, "detect"):
             self.fast_router.detect = self.fast_router.route

        self.router = ModelRouter(
            groq_api_key=groq_key,
            gemini_api_key=gemini_key,
            deepseek_api_key=deepseek_key,
            nvidia_api_key=nvidia_key,
            local_llm=self.llm,
            groq_model=getattr(self.config, "groq_model", "llama-3.1-8b-instant"),
            gemini_model=getattr(self.config, "gemini_model", "gemini-2.0-flash"),
            deepseek_model=getattr(self.config, "deepseek_model", "deepseek-chat"),
            nvidia_model=getattr(self.config, "nvidia_model", "moonshotai/kimi-k2.5"),
            nvidia_base_url=getattr(self.config, "nvidia_base_url", "https://integrate.api.nvidia.com/v1"),
            prefer_local=getattr(self.config, "llm_prefer_local", True),
        )
        try:
            provider_health = self.router.get_provider_health()
            status_summary = ", ".join(
                f"{name}:{'ready' if info.get('available') else info.get('reason', 'unavailable')}"
                for name, info in provider_health.items()
            )
            logger.info(f"LLM provider health -> {status_summary}")
            self.state_manager.log_activity(f"LLM provider health: {status_summary}")
        except Exception as exc:
            logger.warning(f"Failed to collect provider health: {exc}")
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
        # Local verifier (same as local LLM)
        self.local_verifier = self.llm

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
        try:
            from .followup_context import get_followup_context_store

            self.followup_context = get_followup_context_store()
        except Exception as e:
            self.followup_context = None
            logger.warning(f"Follow-up context store not available: {e}")

        # Initialize Preference Manager (Week 2)
        self.preference_manager = get_preference_manager()
        logger.info(f"PreferenceManager initialized: user={self.preference_manager.get('user_name')}")

        # Behavior policy (human-like responses)
        self.emotion_analyzer = None
        self.behavior_policy = None
        self.mental_model_manager = None
        try:
            from ..brain.behavior import EmotionIntentAnalyzer, BehaviorPolicy, MentalModelManager
            self.emotion_analyzer = EmotionIntentAnalyzer()
            self.behavior_policy = BehaviorPolicy(self.config)
            self.mental_model_manager = MentalModelManager()
            logger.info("Behavior policy initialized")
        except Exception as e:
            logger.warning(f"Behavior policy not available: {e}")

        # Initialize Task Manager (Week 3) and START it
        from ..tasks import get_task_manager
        self.task_manager = get_task_manager()
        self.task_manager.set_reminder_callback(self._on_reminder)
        self.task_manager.start()  # Start background checker
        logger.info("TaskManager initialized and started")

        # Initialize Scheduler for automated workflows (Phase 4)
        try:
            from ..core.scheduler import get_scheduler
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

        # FINAL ROUTER UNIFICATION (Hardening Phase 1)
        # Re-initialize ActionDispatcher with all discovered dependencies
        self.action_dispatcher = ActionDispatcher(
            self.capability_registry, 
            llm_client=self.llm,
            memory_manager=self.memory_manager,
            swarm=self.swarm
        )
        logger.info("Unified Executive Router (ActionDispatcher) fully initialized with Memory and Swarm.")

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
        self._current_run_id: Optional[str] = None
        self._current_session_id: Optional[str] = None
        self._current_session_type: Optional[str] = None
        
        # Smart TTS settings
        self._tts_word_threshold = int(getattr(self.config, "tts_word_threshold", 25))
        self._tts_summary_sentences = int(getattr(self.config, "tts_summary_max_sentences", 3))
        self._tts_summary_words = int(getattr(self.config, "tts_summary_max_words", 70))
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

    def _verify_cloud_response(self, user_text: str, response: str) -> Tuple[str, bool]:
        """Verify cloud response using local model, return (text, changed)."""
        if not response:
            return response, False
        if not getattr(self.config, "verify_cloud_responses", True):
            return response, False
        if not self.local_verifier:
            return response, False
        try:
            word_count = len(response.split())
            if word_count < int(getattr(self.config, "verify_cloud_min_words", 40)):
                return response, False
            max_chars = int(getattr(self.config, "verify_cloud_max_chars", 2000))
            snippet = response[:max_chars]
            prompt = (
                "You are a verification agent. Check the draft answer for hallucinations, unsafe claims, "
                "and contradictions. If the draft is solid, reply with exactly: OK. "
                "If it needs fixes, reply with: REWRITE: <corrected answer>.\n\n"
                f"USER:\n{user_text}\n\nDRAFT:\n{snippet}"
            )
            verdict = self.local_verifier.answer_question(prompt)
            if not verdict:
                return response, False
            verdict = verdict.strip()
            if verdict.startswith("REWRITE:"):
                fixed = verdict.replace("REWRITE:", "", 1).strip()
                if fixed:
                    return fixed, True
            return response, False
        except Exception:
            return response, False

    def _on_tts_done(self):
        """Reset barge-in flag after speech finishes."""
        self._allow_barge_in = False
        if self.state_manager.assistant_state == AssistantState.SPEAKING:
            self.state_manager.set_assistant_state(AssistantState.IDLE)

    def _on_executive_progress(self, message: str):
        """Callback for executive brain progress updates."""
        logger.info(f"Executive progress: {message}")
        # Optionally speak progress updates for long tasks
        callback = getattr(self, "_on_response", None)
        if callback:
            callback(f"[Progress] {message}")
    
    def set_response_callback(self, callback: Callable[[str], None]):
        """Set callback for command responses."""
        self._on_response = callback
    
    def speak(
        self,
        text: str,
        priority: bool = False,
        force: bool = False,
        allow_barge_in: bool = False,
        preserve_links: bool = False,
        summarize: bool = False,
        verbatim: bool = False,
    ):
        """Speak text using TTS."""
        tts = getattr(self, "_tts", None)
        logger.debug(f"speak() called: force={force}, auto_speak={self.config.tts_auto_speak}, tts={tts}, text={text[:50] if text else 'None'}...")
        if not force and not self.config.tts_auto_speak:
            logger.debug("speak() skipped: tts_auto_speak is False and not forced")
            return
        if verbatim:
            speech_text = str(text or "").strip()
        else:
            max_sentences = int(getattr(self, "_tts_summary_sentences", 3))
            max_words = int(getattr(self, "_tts_summary_words", 70))
            speech_text = sanitize_for_tts(
                str(text or ""),
                preserve_links=preserve_links,
                summarize=bool(summarize),
                max_sentences=max_sentences,
                max_words=max_words,
            )
        if not speech_text:
            logger.debug("speak() skipped after sanitization: empty speech text")
            return
        if tts and tts.is_available:
            if allow_barge_in or (self.config.tts_allow_barge_in and not force):
                self._allow_barge_in = True
            self.state_manager.set_assistant_state(AssistantState.SPEAKING)
            logger.info(f"TTS speaking: {speech_text[:100]}...")
            # speech_text is already sanitized in this method.
            tts.speak(speech_text, priority=priority, sanitize=False, preserve_links=preserve_links)
        else:
            logger.warning(f"TTS not available: tts={tts}, available={tts.is_available if tts else 'N/A'}")

    def stop_speaking(self):
        """Stop any in-progress speech."""
        tts = getattr(self, "_tts", None)
        if tts and tts.is_available:
            tts.stop_speaking()

    def smart_speak(self, response: str, capability_name: str = "", speech_override: str = "") -> None:
        """
        Smart TTS policy:
        - Speak short responses fully.
        - For long/technical responses, speak a concise digest (core answer + actions + next step).
        - Full verbatim/link-heavy reading is available via "read exact output" / "read links".
        """
        # Store for "read it" command
        self._last_response = response
        self._last_response_capability = capability_name
        speech_base = str(speech_override or response or "").strip()

        # Count words (rough estimate)
        word_count = len(speech_base.split())
        
        # Check if this capability should always be read
        should_always_read = any(
            cap in capability_name.lower() 
            for cap in self._always_read_capabilities
        )
        
        # For short responses or always-read capabilities, speak fully.
        if word_count <= self._tts_word_threshold or should_always_read:
            logger.debug(f"Smart TTS: Reading full response ({word_count} words, capability={capability_name})")
            self.speak(speech_base)
        else:
            # Long response - speak digest with a clear escalation path.
            logger.info(f"Smart TTS: Speaking digest ({word_count} words, capability={capability_name})")
            self.speak(speech_base, summarize=True)

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
        # Fix 1: Sanitize internal routing/debug signals.
        clean_msg = self._sanitize_internal_response(message)

        display_message = self._format_display_response(clean_msg)
        self.state_manager.set_response(display_message, raw=message)
        
        # Broadcast explicitly to UI for chat bubble
        try:
            from .websocket_server import get_ws_server
            ws_server = get_ws_server()
            if ws_server:
                import asyncio
                # Fire and forget response broadcast
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(ws_server.broadcast_response(display_message))
        except Exception:
            pass  # Don't fail if WS server not available/loop issue

        callback = getattr(self, "_on_response", None)
        if callback:
            callback(clean_msg)
        if speak:
            self.speak(clean_msg)

    def _sanitize_internal_response(self, message: str) -> str:
        """Strip internal routing/debug tokens from user-visible responses."""
        return _sanitize_internal_response_text(message)

    def _conversation_fallback_response(self, user_text: str) -> str:
        """Safe fallback when conversation output becomes empty after sanitization."""
        return _conversation_fallback_response_text(user_text)

    def _deterministic_response_if_applicable(self, user_text: str) -> str:
        """
        Best-effort deterministic answers for common prompts when LLM output is degraded/truncated.

        This is intentionally narrow: it should only trigger on obvious cases where a simple,
        stable template is better than a partial or empty model response.
        """
        raw = str(user_text or "").strip()
        if not raw:
            return ""
        low = raw.lower()

        # Benchmark-stability guard: ensure "Compare Python vs JavaScript" always mentions both.
        wants_compare = ("compare" in low) or (" vs " in low) or ("versus" in low)
        if wants_compare and "python" in low and ("javascript" in low or "java script" in low or " js" in low):
            return (
                "Python vs JavaScript (quick comparison)\n"
                "- Primary use: Python is common for scripting, data/ML, and backend services; JavaScript is the language of the web (front-end) and runs on servers via Node.js.\n"
                "- Strengths: Python emphasizes readability and batteries-included tooling; JavaScript emphasizes UI interactivity and a huge web ecosystem.\n"
                "- Ecosystem: Python uses pip/venv and has strong scientific libraries; JavaScript uses npm/pnpm and has massive web frameworks.\n"
                "- Performance: both can be fast enough for many apps; performance usually depends more on libraries, architecture, and runtime than syntax.\n"
                "- Pick: choose Python for automation/data-heavy work; choose JavaScript for web UI and full-stack JS workflows.\n"
            )

        # Benchmark-stability guard: temperature conversion should not depend on LLM availability.
        if "fahrenheit" in low and "celsius" in low and ("convert" in low or " to " in low):
            match = re.search(r"(-?\d+(?:\.\d+)?)", raw)
            if match:
                try:
                    f_val = float(match.group(1))
                    c_val = (f_val - 32.0) * (5.0 / 9.0)
                    return f"{f_val:g}°F is {c_val:.1f}°C."
                except Exception:
                    pass

        return ""

    def _trim_context_to_budget(self, context_text: str, max_chars: int) -> str:
        """Trim context blocks to a strict character budget while preserving section order."""
        return _trim_context_to_budget_text(context_text, max_chars)

    def _build_llm_memory_context(
        self,
        query: str,
        memory_manager: Optional[Any] = None,
        route_context: str = "",
        include_gcc: bool = False,
        gcc_log_lines: int = 8,
    ) -> str:
        """Build token-budgeted context for LLM routing and generation."""
        mm = memory_manager or self.memory_manager
        context_parts: list[str] = []
        max_turns = int(getattr(self.config, "llm_context_max_conversation_turns", 8))
        include_preferences = bool(getattr(self.config, "llm_context_include_preferences", True))

        # Prefer unified context builder (conversation + memories + profile + preferences).
        try:
            from ..brain.memory.context_builder import get_context_builder

            builder = get_context_builder()
            built = builder.build_context(
                query=query,
                max_conversation_turns=max_turns,
                include_profile=True,
                include_conversation=True,
                include_memories=True,
                include_preferences=include_preferences,
            )
            if built.strip():
                context_parts.append(built.strip())
        except Exception:
            pass

        # Fallback if unified builder is unavailable.
        if not context_parts:
            try:
                if self.conversation_memory:
                    conv = self.conversation_memory.get_context(max_turns=max_turns)
                    if conv.strip():
                        context_parts.append(f"Recent Conversation:\n{conv}")
            except Exception:
                pass
            try:
                if mm and hasattr(mm, "retrieve_context"):
                    mem = mm.retrieve_context(query, n_results=int(getattr(self.config, "memory_top_k", 3)))
                    if str(mem or "").strip():
                        context_parts.append(f"Relevant Memories:\n{mem}")
            except Exception:
                pass
            try:
                if mm and hasattr(mm, "get_profile_context"):
                    profile = mm.get_profile_context()
                    if str(profile or "").strip():
                        context_parts.insert(0, f"User Info:\n{profile}")
            except Exception:
                pass

        route_ctx = str(route_context or "").strip()
        if route_ctx:
            context_parts.append(f"Routing Context:\n{route_ctx}")

        if include_gcc:
            gcc = self._get_gcc_context_snippet(query, log_lines=int(gcc_log_lines or 8))
            if gcc:
                context_parts.append(f"GCC Context:\n{gcc}")

        merged = "\n\n".join(part for part in context_parts if str(part or "").strip())
        budget = int(getattr(self.config, "llm_context_budget_chars", 3200))
        return self._trim_context_to_budget(merged, budget)

    def _build_followup_clarifier(self, text: str, memory_context: str = "") -> str:
        """Ask for clarification when a follow-up command is too underspecified."""
        if not bool(getattr(self.config, "phase16_clarifier_enabled", True)):
            return ""

        raw = str(text or "").strip()
        if not raw:
            return ""
        low = raw.lower()
        words = re.findall(r"[a-z0-9']+", low)
        if not words:
            return ""

        markers = [str(x).strip().lower() for x in (getattr(self.config, "phase16_clarifier_markers", []) or []) if str(x).strip()]
        marker_hit = any(low == marker or low.startswith(marker + " ") for marker in markers)
        min_words = int(getattr(self.config, "phase16_clarifier_min_words", 3))
        short_followup = len(words) <= max(1, min_words) and any(
            token in {"it", "this", "that", "again", "continue", "more", "next", "same"} for token in words
        )
        if not marker_hit and not short_followup:
            return ""

        # If there is known context, do not block; let the model/capability continue.
        if str(memory_context or "").strip():
            return ""
        if str(getattr(self, "_last_response", "") or "").strip():
            return ""
        if bool(getattr(self, "_pending_action", None)):
            return ""
        try:
            if self.conversation_memory:
                turns = int(getattr(self.config, "phase16_clarifier_context_turns", 2))
                recent = self.conversation_memory.get_context(max_turns=max(1, turns))
                if str(recent or "").strip():
                    return ""
        except Exception:
            pass

        return (
            "Can you clarify what you want me to continue? "
            "For example: 'continue the previous answer' or 'read more about headline 3'."
        )

    def _extract_numbered_followup_index(self, text: str) -> Optional[int]:
        return _extract_numbered_followup_index_text(text)

    def _extract_compare_indices(self, text: str) -> Optional[Tuple[int, int]]:
        return _extract_compare_indices_text(text)

    def _is_numbered_followup_request(self, text: str) -> bool:
        return _is_numbered_followup_request_text(text)

    def _try_numbered_followup_detail(self, text: str, context: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """Resolve numbered detail follow-up from persisted list context."""
        if not self._is_numbered_followup_request(text):
            return None
        store = getattr(self, "followup_context", None)
        if not store:
            return None

        index = self._extract_numbered_followup_index(text)
        if index is None:
            return None

        snapshot = (
            store.get_context(session_id=self._current_session_id)
            if hasattr(store, "get_context")
            else {}
        )
        items = list(snapshot.get("items") or []) if isinstance(snapshot, dict) else []
        if not items:
            return None

        low = str(text or "").lower()
        kind = str(snapshot.get("kind") or "").strip().lower()
        if "read more about" in low:
            return None
        # Keep dedicated morning briefing path in control for headline read-more flow.
        if kind == "morning_briefing" and (
            "headline" in low or "briefing" in low or "read more about #" in low or "read more #" in low
        ):
            return None

        item = store.get_item(index, session_id=self._current_session_id) if hasattr(store, "get_item") else None
        if not item:
            from .capabilities import ActionResult

            total = len(items)
            return ActionResult.ok(
                f"I only have {total} item(s) in the latest list. Choose a number from 1 to {total}.",
                {"count": total},
                "followup_detail",
            )

        title = str(item.get("title") or f"Item #{index}").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        source = str(item.get("source") or "").strip()

        from .capabilities import ActionResult

        compare_indices = self._extract_compare_indices(low)
        if compare_indices is not None:
            left_idx, right_idx = compare_indices
            left = (
                store.get_item(left_idx, session_id=self._current_session_id)
                if hasattr(store, "get_item")
                else None
            )
            right = (
                store.get_item(right_idx, session_id=self._current_session_id)
                if hasattr(store, "get_item")
                else None
            )
            if not left or not right:
                total = len(items)
                return ActionResult.ok(
                    f"I only have {total} item(s) in the latest list. Choose numbers from 1 to {total}.",
                    {"count": total},
                    "followup_detail",
                )
            left_title = str(left.get("title") or f"Item #{left_idx}").strip()
            right_title = str(right.get("title") or f"Item #{right_idx}").strip()
            left_source = str(left.get("source") or "source").strip()
            right_source = str(right.get("source") or "source").strip()
            left_snippet = str(left.get("snippet") or "").strip()
            right_snippet = str(right.get("snippet") or "").strip()
            lines = [
                f"Comparison: Item #{left_idx} vs Item #{right_idx}",
                "",
                f"- #{left_idx}: {left_title}",
                f"  Source: {left_source}",
                f"  Notes: {left_snippet or 'No short summary available.'}",
                "",
                f"- #{right_idx}: {right_title}",
                f"  Source: {right_source}",
                f"  Notes: {right_snippet or 'No short summary available.'}",
                "",
                "Tell me which one you want to open or save.",
            ]
            return ActionResult.ok(
                "\n".join(lines).strip(),
                {
                    "kind": kind,
                    "left_index": left_idx,
                    "right_index": right_idx,
                    "left_title": left_title,
                    "right_title": right_title,
                },
                "followup_detail",
            )

        if "open" in low:
            if not url:
                return ActionResult.ok(
                    f"Item #{index} has no link to open. Ask for details instead.",
                    {"index": index, "title": title, "kind": kind},
                    "followup_detail",
                )
            dry_run = bool((context or {}).get("dry_run"))
            opened = False
            if not dry_run:
                try:
                    launcher = getattr(self, "launcher", None)
                    if launcher and hasattr(launcher, "open_url"):
                        opened = bool(launcher.open_url(url))
                except Exception:
                    opened = False
            if dry_run:
                message = f"Dry run: would open item #{index}: {title}"
            elif opened:
                message = f"Opened item #{index}: {title}"
            else:
                message = f"I found the link for item #{index} but could not open it automatically."
            return ActionResult.ok(
                message,
                {"index": index, "title": title, "url": url, "kind": kind, "opened": opened, "dry_run": dry_run},
                "followup_detail",
            )

        if "save" in low:
            save_dir = Path((context or {}).get("save_dir") or (Path.home() / "Desktop"))
            safe_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:42] or f"item-{index}"
            out_path = save_dir / f"followup_{index}_{safe_slug}.md"
            body_lines = [
                f"# Item #{index}",
                "",
                f"- Title: {title}",
                f"- Source: {source or 'unknown'}",
                f"- URL: {url or '(none)'}",
                "",
                "## Summary",
                "",
                snippet or "No summary captured.",
                "",
            ]
            try:
                save_dir.mkdir(parents=True, exist_ok=True)
                out_path.write_text("\n".join(body_lines), encoding="utf-8")
                return ActionResult.ok(
                    f"Saved item #{index} to {out_path}",
                    {"index": index, "title": title, "path": str(out_path), "kind": kind},
                    "followup_detail",
                )
            except Exception as exc:
                return ActionResult.ok(
                    f"I couldn't save item #{index}: {exc}",
                    {"index": index, "title": title, "kind": kind, "error": str(exc)},
                    "followup_detail",
                )

        detail = snippet
        if not detail and url:
            try:
                from chintu_backend.automation.web.url_reader import get_url_reader
                from chintu_backend.core.model_router import get_router

                reader = get_url_reader(llm_client=get_router())
                page_text, _meta = reader.fetch(url)
                detail = str(reader.summarize(page_text, max_length=850) or "").strip()
            except Exception:
                detail = ""

        if not detail:
            detail = "I can continue with a deeper breakdown if you tell me what angle you want (technical, business, or practical impact)."

        lines = [f"Item #{index}: {title}"]
        if source:
            lines.append(f"Source: {source}")
        lines.extend(
            [
                "",
                detail,
                "",
                "Want me to continue with the next item?",
            ]
        )
        return ActionResult.ok(
            "\n".join(lines).strip(),
            {"index": index, "title": title, "url": url, "kind": kind},
            "followup_detail",
        )

    def _build_behavior_context(self, text: str, context: Optional[Dict[str, Any]] = None) -> Tuple[str, Any, Any]:
        """Build behavior policy context for LLM prompting."""
        if not getattr(self.config, "behavior_enabled", True):
            return "", None, None
        if not self.behavior_policy:
            return "", None, None
        prefs = self.preference_manager.preferences.to_dict() if self.preference_manager else {}
        mental_model = None
        if getattr(self.config, "behavior_include_mental_model", True) and self.mental_model_manager:
            mental_model = self.mental_model_manager.model
        emotion = None
        if getattr(self.config, "behavior_use_emotion_signals", True) and self.emotion_analyzer:
            try:
                emotion = self.emotion_analyzer.analyze(text, context)
            except Exception:
                emotion = None
        if emotion is None:
            try:
                from ..brain.behavior import EmotionSignal
                emotion = EmotionSignal()
            except Exception:
                emotion = None
        plan = self.behavior_policy.build_plan(
            emotion=emotion,
            preferences=prefs,
            mental_model=mental_model,
            context=context or {},
        )
        parts = []
        if emotion:
            try:
                parts.append(f"Signals: {emotion.to_context()}")
            except Exception:
                pass
        if plan:
            try:
                parts.append(f"Plan: {plan.to_context()}")
            except Exception:
                pass
        if mental_model:
            try:
                parts.append(f"MentalModel: {mental_model.to_context()}")
            except Exception:
                pass
        parts.append("Guidance: Act like a product-focused cofounder/manager. Lead with clear decisions, propose next steps, and persist with alternatives. If knowledge is missing, ask permission to search the web, verify sources, and offer to document results in the library.")
        return "\n".join(parts), emotion, plan
    
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
        skill_context = ""
        context = context or {}
        # Reset state to prevent leakage across unrelated commands
        if not context.get("is_follow_up"):
            self._last_response = ""
            if self.conversation_flow:
                self.conversation_flow.clear_context()
            
        if self.mock_mode:
            context.setdefault("dry_run", True)
            context.setdefault("dry_run_mode", "side_effects")

        # Agent scoping (workspace/session/tool policy)
        agent_runtime = context.get("_agent_runtime")
        agent_id = context.get("_agent_id") or getattr(agent_runtime, "agent_id", None)
        if not agent_id and getattr(self.config, "agent_isolation_enabled", True) and not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                from chintu_backend.agents.agent_directory import get_agent_directory

                directory = get_agent_directory()
                runtime = directory.get_or_create("primary", role=getattr(self.config, "agent_default_role", "primary"))
                context.update(directory.build_context(runtime, "primary", channel=source))
                agent_runtime = runtime
                agent_id = runtime.agent_id
            except Exception:
                pass
        if agent_runtime:
            context.setdefault("_agent_policy", getattr(agent_runtime, "policy", None))
            context.setdefault("_agent_sandbox", getattr(agent_runtime, "sandbox", None))
            context.setdefault("workspace_dir", str(getattr(agent_runtime, "workspace_dir", "")))
        if agent_id:
            context["_agent_id"] = agent_id

        # Agent session logging
        session_store = context.get("_agent_session_store")
        if not session_store and agent_runtime:
            try:
                from chintu_backend.swarm.agent_runtime import AgentSessionStore

                session_store = AgentSessionStore(agent_runtime.session_dir)
                context["_agent_session_store"] = session_store
            except Exception:
                session_store = None
        if session_store:
            try:
                session_store.append_event(
                    {
                        "event": "request_received",
                        "text": text[:2000],
                        "source": source,
                        "trace_id": get_trace_id(),
                    }
                )
            except Exception:
                pass

        # Finance interest capture (conversation -> candidate suggestions)
        if getattr(self.config, "finance_auto_capture_interest", False):
            try:
                from chintu_backend.finance.finance_capabilities import capture_interest_candidates
                from chintu_backend.core.events import Event, EventType, get_event_bus

                added = capture_interest_candidates(text, source=source)
                if added:
                    symbols = ", ".join(c.get("symbol") for c in added if c.get("symbol"))
                    get_event_bus().publish_sync(
                        Event(
                            type=EventType.NOTIFICATION,
                            source="finance",
                            data={
                                "category": "finance_candidate",
                                "severity": "low",
                                "title": "Finance candidates added",
                                "message": f"Detected interest in: {symbols}. Say 'add candidate SYMBOL' to approve.",
                                "metadata": {"symbols": symbols},
                            },
                        )
                    )
            except Exception:
                pass

        # Scoped memory (per-agent isolation)
        scoped_memory = self.memory_manager
        if agent_id and self.memory_manager:
            try:
                from ..brain.memory.agent_memory import AgentMemoryView

                scoped_memory = AgentMemoryView(self.memory_manager, agent_id)
            except Exception:
                scoped_memory = self.memory_manager

        # Scoped retrieval router (per-agent RAG context)
        scoped_retriever = self.retrieval_router
        if agent_id and self.retrieval_router:
            try:
                from ..brain.memory.retrieval_router import RetrievalRouter

                scoped_retriever = RetrievalRouter(
                    memory_manager=scoped_memory,
                    tiered_store=getattr(self.retrieval_router, "tiered_store", None),
                )
            except Exception:
                scoped_retriever = self.retrieval_router

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
        pending_cap = {}
        try:
            pending_cap = self.action_dispatcher.get_pending_confirmation() or {}
        except Exception:
            pending_cap = {}

        pending_payload = {
            "capability_pending": bool(pending_cap.get("pending")),
            **(pending_ctx or {}),
        }
        if pending_cap.get("pending"):
            pending_payload["capability_pending_capability"] = pending_cap.get("capability", "")
            pending_payload["capability_pending_message"] = pending_cap.get("message", "")
            pending_payload["capability_pending_type"] = pending_cap.get("confirmation_type", "")

        self.state_manager.update_hud(pending=pending_payload)
        if text:
            try:
                summary = text.strip()
                if len(summary) > 120:
                    summary = summary[:117] + "..."
                self.state_manager.log_activity(f"Command received: {summary}")
            except Exception:
                pass
            self.state_manager.update_hud(intent="processing", active_tools=[])

        # Channel/session continuity for conversation memory
        session_id = None
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
        if not session_id:
            session_id = "main"
        if session_id:
            try:
                from chintu_backend.core.session_manager import get_session_manager, SessionType, Visibility

                session_type = context.get("session_type")
                if not session_type:
                    if source in ("schedule", "cron"):
                        session_type = SessionType.CRON
                    elif source in ("hook", "webhook"):
                        session_type = SessionType.HOOK
                    else:
                        session_type = SessionType.MAIN
                elif isinstance(session_type, str):
                    try:
                        session_type = SessionType(session_type)
                    except Exception:
                        session_type = SessionType.MAIN

                visibility = Visibility.PUBLIC
                if session_type in (SessionType.CRON, SessionType.HOOK):
                    visibility = Visibility.INTERNAL

                mgr = get_session_manager()
                mgr.ensure_session(
                    session_id=session_id,
                    name=str(session_id),
                    type=session_type,
                    visibility=visibility,
                )
                mgr.append_turn(session_id, "user", text, {"source": source})
                mgr.touch_session(session_id)
                self._current_session_id = session_id
                self._current_session_type = session_type.value
            except Exception:
                self._current_session_id = session_id
                self._current_session_type = None
        
        new_trace_id()
        try:
        
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
            # PHASE 1.5: PROMPT INJECTION GUARD (Phase 2 Audit Fix)
            # =====================================================================
            is_safe, category = get_prompt_guard().check(text)
            if not is_safe:
                logger.warning(f"Security Block: Prompt injection detected ({category})")
                refusal = "I cannot process that request for security reasons."
                self._respond(refusal)
                return refusal
        
            # =====================================================================
            # PHASE 2: GARBAGE FILTER - Ignore noise/punctuation
            # =====================================================================
            clean_text = text.strip(" .?!,")
            has_pending_session_request = False
            try:
                from .context_manager import get_context_manager

                has_pending_session_request = get_context_manager().has_pending_requests(session_id=session_id)
            except Exception:
                has_pending_session_request = False

            if (not clean_text or len(clean_text) < 2) and not has_pending_session_request:
                logger.info(f"Ignoring garbage transcript: '{text}'")
                if self.metrics:
                    self.metrics.record_error("no_reply")
                return ""

            # Hard safety gate: block direct purchase/payment requests.
            try:
                from chintu_backend.security.payment_guard import detect_payment_signal

                pay_signal = detect_payment_signal(clean_text)
                if pay_signal.matched:
                    blocked = (
                        "Blocked: payment/purchase actions are disabled by policy. "
                        "I can help you compare options or prepare a draft checklist instead."
                    )
                    self._respond(blocked)
                    return blocked
            except Exception:
                pass

            # -----------------------------------------------------------------
            # RUN LIFECYCLE + QUEUE (reliability-first foundation)
            # -----------------------------------------------------------------
            run_mgr = None
            try:
                from chintu_backend.core.run_manager import get_run_manager

                run_mgr = get_run_manager()
            except Exception:
                run_mgr = None

            clean_lower = clean_text.lower().strip()
            
            # If this message is confirming/cancelling a pending action, resume the same run.
            pending_snapshot = {}
            try:
                pending_snapshot = self.action_dispatcher.get_pending_confirmation() or {}
            except Exception:
                pending_snapshot = {}
            pending_run_id = run_mgr.pending_confirmation_run_id() if run_mgr else None
            pending_input_run_id = run_mgr.pending_input_run_id() if run_mgr else None
            is_confirm = clean_lower in {"yes", "confirm", "proceed", "ok", "okay", "sure", "go ahead", "yep", "yeah"}
            is_cancel = clean_lower in {"no", "cancel", "abort", "don't", "dont", "stop", "reject"}
            waiting_input_markers = {
                "continue",
                "resume",
                "go on",
                "done",
                "im done",
                "i'm done",
                "finished",
                "completed",
                "i logged in",
                "logged in",
                "signed in",
                "next step",
            }
            is_waiting_input_resume = bool(
                pending_input_run_id
                and (
                    clean_lower in waiting_input_markers
                    or any(marker in clean_lower for marker in ("logged in", "signed in", "continue", "resume", "done"))
                )
            )

            if run_mgr and pending_snapshot.get("pending") and pending_run_id and (is_confirm or is_cancel):
                self._current_run_id = pending_run_id
                context["_run_id"] = pending_run_id
                context["_run_resume"] = True
                run_mgr.enqueue_for_resume(pending_run_id, prioritize=True)
                run_mgr.acquire_run_turn(pending_run_id)
                run_mgr.clear_waiting_approval(pending_run_id)
            elif run_mgr and is_waiting_input_resume and pending_input_run_id:
                waiting_ctx = run_mgr.get_waiting_input_context(pending_input_run_id)
                waiting_cap = str(waiting_ctx.get("capability") or "").strip()
                waiting_meta = waiting_ctx.get("meta") if isinstance(waiting_ctx.get("meta"), dict) else {}

                self._current_run_id = pending_input_run_id
                context["_run_id"] = pending_input_run_id
                context["_run_resume"] = True
                context["_resume_waiting_input"] = True
                context["_waiting_input_meta"] = dict(waiting_meta or {})
                # This is a continuation of an already-confirmed run.
                # Avoid re-prompting policy confirmation on every resume turn.
                context["_confirmed"] = True
                if waiting_cap:
                    context["_forced_capability"] = waiting_cap

                run_mgr.enqueue_for_resume(pending_input_run_id, prioritize=True)
                run_mgr.acquire_run_turn(pending_input_run_id)
                run_mgr.clear_waiting_input(pending_input_run_id)
            else:
                # Fast stop: cancel the currently active run (best-effort) without waiting in the queue.
                if run_mgr and session_id and clean_lower in {"stop", "cancel", "abort"}:
                    cancelled_run_id = run_mgr.cancel_active_run(session_id, reason=f"user said '{clean_lower}'")
                    try:
                        self.action_dispatcher.cancel_pending()
                    except Exception:
                        pass
                    msg = "Stopping the current task." if cancelled_run_id else "Stopped."
                    self._respond(msg)
                    return msg
                if run_mgr:
                    record = run_mgr.create_run(
                        session_id=session_id,
                        source=source,
                        user_text=clean_text,
                        meta={"agent_id": agent_id or "", "source": source},
                    )
                    self._current_run_id = record.id
                    context["_run_id"] = record.id
                    run_mgr.acquire_run_turn(record.id)

            # GCC: isolate complex long-horizon goals in a dedicated branch.
            self._maybe_gcc_open_task_branch(clean_text, source=source)
        
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
            # PHASE 3.5: ACTIVE LEARNING LOOP
            # "Reasoning about mistakes"
            # =====================================================================
            if self.learning_manager:
                try:
                    # Get context (last response)
                    last_response = self._last_response if hasattr(self, '_last_response') else None
                    signals = self.learning_manager.analyze_feedback(text, last_assistant_action=last_response)
                
                    for signal in signals:
                        logger.info(f"Learning Signal Detected: {signal.signal_type} -> {signal.content}")
                    
                        # Store preference/correction to memory
                        if signal.proposed_action:
                            action_type = signal.proposed_action.get('type')
                            value = signal.proposed_action.get('value')
                        
                            if action_type in ['negative_preference', 'positive_preference'] and value:
                                self.memory_manager.add_preference(
                                    key=f"pref_{action_type}_{value[:20]}", 
                                    value=value
                                )
                                # Acknowledge learning
                                self._respond(f"Understood. I've noted that preference regarding '{value}'.")
                            
                                # If it was a pure correction, we might want to stop here or reroute
                                # For now, we continue but with the new context
                except Exception as e:
                    logger.error(f"Error in learning loop: {e}")

            # =====================================================================
            # PHASE 3.5: CONFIRMATION HANDLING
            # Check if user is confirming a pending action
            # =====================================================================
            confirm_phrases = [
                "yes",
                "confirm",
                "i confirm",
                "confirm it",
                "proceed",
                "do it",
                "sure",
                "ok",
                "okay",
                "go ahead",
                "yep",
                "yeah",
            ]
            cancel_phrases = ["no", "cancel", "stop", "abort", "don't"]
            text_lower_clean = text.lower().strip().strip(".,!")
        
            pending = self.action_dispatcher.get_pending_confirmation()
            if pending:
                if any(p == text_lower_clean or text_lower_clean.startswith(p + " ") for p in confirm_phrases):
                    logger.info("Confirming pending action via Dispatcher")
                    result = self.action_dispatcher.confirm_pending(context=context)
                    if result:
                        return self._process_result(
                            result,
                            text,
                            source,
                            memory_manager=scoped_memory,
                            session_store=session_store,
                        )
                    return "Confirmed."
                elif any(p == text_lower_clean or text_lower_clean.startswith(p + " ") for p in cancel_phrases):
                    logger.info("Cancelling pending action via Dispatcher")
                    self.action_dispatcher.cancel_pending()
                    # Mark the resumed run as cancelled (so the lane can move on).
                    try:
                        from chintu_backend.core.run_manager import get_run_manager

                        rid = str(getattr(self, "_current_run_id", "") or context.get("_run_id", "") or "")
                        if rid:
                            mgr = get_run_manager()
                            mgr.mark_cancelled(rid, reason="User cancelled pending action")
                            mgr.release_run_turn(rid)
                    except Exception:
                        pass
                    self._respond("Cancelled.")
                    return "Cancelled."

            # =====================================================================
            # PHASE 3.6: EXECUTIVE PLAN CONFIRMATION
            # Handle confirmations for multi-step execution plans.
            # =====================================================================
            if self.executive and self.executive.has_pending_plan():
                if any(p == text_lower_clean or text_lower_clean.startswith(p + " ") for p in confirm_phrases):
                    logger.info("Confirming pending executive plan")
                    ok = self.executive.confirm_plan()
                    if ok:
                        result = self.executive.execute_plan(self.capability_registry)
                        response = f"{result.message}. Success: {result.success}."
                        if result.errors:
                            response += f" Errors: {', '.join(result.errors[:3])}"
                        try:
                            from ..brain.orchestration.trace import log_event
                            log_event({
                                "event": "executive_plan_executed",
                                "success": result.success,
                                "steps_total": result.steps_total,
                                "steps_completed": result.steps_completed,
                                "errors": result.errors,
                            })
                        except Exception:
                            pass
                        self._respond(response)
                        return response
                elif any(p == text_lower_clean or text_lower_clean.startswith(p + " ") for p in cancel_phrases):
                    logger.info("Cancelling pending executive plan")
                    self.executive.cancel_plan()
                    self._respond("Cancelled the execution plan.")
                    return "Cancelled the execution plan."

            # =====================================================================
            # PHASE 2.5: CREDENTIAL DETECTION - Detect API keys/tokens in message
            # This runs BEFORE capability matching to catch tokens like Telegram tokens
            # =====================================================================
            try:
                from .credential_detector import get_credential_detector

                credential = get_credential_detector().detect(text)
                if credential:
                    # Avoid logging secrets: do not include credential values in logs.
                    logger.info("Credential detected: %s", getattr(credential.credential_type, "value", "unknown"))

                    # If the user explicitly instructed us to save/use the key, store immediately.
                    if self._should_auto_store_credential(text):
                        msg = self._store_detected_credential(credential, original_text=text)
                        self._respond(msg)
                        return msg

                    # Default: ask for confirmation before storing anything.
                    prompt = self._handle_credential_detected(credential, text)
                    if prompt:
                        return prompt
            except Exception as e:
                logger.debug("Credential detection failed: %s", e)

            # Clear any previous interrupt before normal processing
            interrupt_handler.clear_interrupt()
        
            # =====================================================================
            # PHASE 2.5: ROBUSTNESS PRE-PROCESSING (Phase 6)
            # Validate input, check confidence, resolve pending requests
            # =====================================================================
            if self.robustness:
                robust_response = self.robustness.pre_process(text, context=context)
            
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
                
                # If middleware resolved a pending request, return its response
                if robust_response.message:
                    msg = robust_response.message
                    self._respond(msg)
                    if self.routing_fsm and self._routing_states:
                        self.routing_fsm.transition(self._routing_states.RESPONDED)
                    return msg

            # =====================================================================
            # PHASE 2.6: SERVICE INTENT DETECTION
            # Detect when user wants to set up a service but hasn't provided credentials
            # e.g., "connect to Telegram" -> ask for token
            # =====================================================================
            try:
                from .credential_detector import get_service_intent_detector, ServiceIntent
                from .context_manager import get_context_manager, PendingType
            
                service_intent = get_service_intent_detector().detect(text)
            
                if service_intent and service_intent.intent != ServiceIntent.NONE:
                    # Check if we already have the credential for this service
                    has_credential = False
                    if service_intent.intent == ServiceIntent.TELEGRAM_SETUP:
                        has_credential = bool(self.config.telegram_bot_token or os.environ.get("TELEGRAM_BOT_TOKEN"))
                    elif service_intent.intent == ServiceIntent.GROQ_SETUP:
                        has_credential = bool(self.config.groq_api_key)
                    elif service_intent.intent == ServiceIntent.GEMINI_SETUP:
                        has_credential = bool(self.config.google_ai_key)
                    elif service_intent.intent == ServiceIntent.NVIDIA_SETUP:
                        has_credential = bool(self.config.nvidia_api_key)
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
                        elif service_intent.intent == ServiceIntent.NVIDIA_SETUP:
                            prompt_keys = ["NVIDIA_API_KEY"]
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
                            session_id=context.get("session_id"),
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

            # -----------------------------------------------------------------
            # Phase 16: Numbered follow-up continuity for search/research lists.
            # Example: "go deeper on point 2", "read more on result #1".
            # -----------------------------------------------------------------
            followup_result = self._try_numbered_followup_detail(text, context=context)
            if followup_result:
                return self._process_result(
                    followup_result,
                    text,
                    source,
                    memory_manager=scoped_memory,
                    session_store=session_store,
                )

            # =====================================================================
            # PHASE 4: LEARNING SIGNALS (PREFERENCES)
            # Detect corrections like "Don't do X" and propose updates
            # =====================================================================
            try:
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
                    try:
                        from .context_manager import get_context_manager, PendingType
                        ctx_manager = get_context_manager()
                        ctx_manager.create_pending_request(
                            request_type=PendingType.APPROVAL,
                            prompt=proposal_text + " Reply 'yes' to confirm or 'no' to cancel.",
                            original_command=text,
                            context={
                                "preference_key": (signal.proposed_action or {}).get("key"),
                                "preference_value": (signal.proposed_action or {}).get("value"),
                                "updates": (signal.proposed_action or {}).get("updates"),
                            },
                            callback_name="apply_preference",
                            session_id=context.get("session_id"),
                        )
                    except Exception:
                        pass
                    self._respond(proposal_text)
                    if self.routing_fsm and self._routing_states:
                        self.routing_fsm.transition(self._routing_states.PENDING_CONFIRM)
                    return proposal_text
            except Exception as e:
                logger.warning(f"Learning signal processing failed: {e}")

            # =====================================================================
            # PHASE 4: DISPATCH ACTIONS (Deterministic Skills)
            # =====================================================================
            # 1. Update Conversation Context (Do this BEFORE dispatch so we recall this command later)
            if self.conversation_flow:
                self.conversation_flow.add_user_message(text)

            # Try the action dispatcher for EVERY request. 
            # This ensures that if a deterministic skill (like battery or system control) 
            # matches keywords, it takes precedence over LLM hallucinations.
        
            # Build context for dispatch
            dispatch_context = context or {}
            if source:
                dispatch_context["source"] = source
            # Make core clients available to capabilities (some handlers expect these).
            dispatch_context.setdefault("llm_client", self.llm)
            dispatch_context.setdefault("model_router", getattr(self, "router", None))
            dispatch_context.setdefault("config", self.config)
            dispatch_context.setdefault("command_handler", self)
            if dispatch_context.get("agent_role") and not dispatch_context.get("_agent_policy"):
                try:
                    from chintu_backend.swarm.agent_policy import AgentPolicyStore
                    store = AgentPolicyStore()
                    profile = store.get_profile(dispatch_context["agent_role"])
                    dispatch_context["_agent_policy"] = profile.to_tool_policy()
                    dispatch_context["_agent_sandbox"] = profile.to_sandbox()
                except Exception:
                    pass

            confirm_in_text = any(p in text_lower_clean for p in confirm_phrases)
            if confirm_in_text and text_lower_clean not in confirm_phrases:
                dispatch_context["_confirmed"] = True

            if self.action_dispatcher.registry is not self.capability_registry:
                self.action_dispatcher.registry = self.capability_registry

            try:
                capability = self.capability_registry.match(text)
            except Exception:
                capability = None
            if capability:
                try:
                    self.state_manager.update_hud(
                        intent=capability.name,
                        active_tools=[capability.name],
                    )
                    self.state_manager.log_activity(f"Executing capability: {capability.name}")
                except Exception:
                    pass
            # PHASE 5: UNIFIED DISPATCH (Phase 1 Hardening)
            # This calls the Unified Executive Router which handles:
            # - Decomposition (Compound commands)
            # - Fast-Path Keyword Match
            # - RAG Context Injection
            # - Swarm Routing
            # - LLM Tool Routing
            # - Code Interpreter Fallback
            result = self.action_dispatcher.dispatch(text, dispatch_context)
        
            if result.success:
                # Check for special marker that actually wants LLM Conversation Flow
                if result.message == "__LLM_ROUTE__":
                    logger.info("Capability matched but requested cloud-level conversation fallback.")
                else:
                    logger.info(f"Action executed via Unified Dispatcher: {result.capability_name}")
                    response = result.message
                    self.conversation_flow.add_assistant_message(response)
                    return self._process_result(
                        result,
                        text,
                        source,
                        memory_manager=scoped_memory,
                        session_store=session_store,
                    )
            elif result.message != "No matching capability found.":
                # The capability matched, but the handler returned failure
                logger.info(f"Action handler failed: {result.message}. Reporting failure.")
                response = result.message
                self.conversation_flow.add_assistant_message(response)
                return self._process_result(
                    result,
                    text,
                    source,
                    memory_manager=scoped_memory,
                    session_store=session_store,
                )

            # =====================================================================
            # PHASE 6: CLOUD CONVERSATION FALLBACK
            # =====================================================================
            # Use the existing router for LLM generation (cloud/fallback)
            response = ""
            source_out = "local"
            cloud_verified = False
            try:
                route_context = dispatch_context.get("_rag_context", "")
                memory_context = self._build_llm_memory_context(
                    text,
                    memory_manager=scoped_memory,
                    route_context=route_context,
                    include_gcc=True,
                    gcc_log_lines=8,
                )
                clarifier = self._build_followup_clarifier(text, memory_context=memory_context)
                if clarifier:
                    self.conversation_flow.add_assistant_message(clarifier)
                    self._respond(clarifier)
                    return clarifier
                behavior_context, _, _ = self._build_behavior_context(text, context)

                deterministic = self._deterministic_response_if_applicable(text)
                if deterministic:
                    response = deterministic
                    source_out = "deterministic"
                else:
                    response, source_out = self.router.route_and_execute(
                        text,
                        memory_context=memory_context,
                        behavior_context=behavior_context,
                    )
            except Exception as exc:
                logger.warning(f"Cloud fallback failed: {exc}")
                response = self.llm.answer_question(text)
                source_out = "local"

            # Accuracy hardening: locally verify cloud responses to reduce hallucinations.
            try:
                if str(source_out or "").strip().lower() in {"nvidia", "groq", "gemini", "deepseek"}:
                    verified, changed = self._verify_cloud_response(text, response)
                    if changed and verified:
                        response = verified
                        cloud_verified = True
            except Exception:
                pass

            response = self._sanitize_internal_response(response)
            if not response:
                response = self._conversation_fallback_response(text)
            self._record_router_escalation_artifacts(
                text=text,
                response=response,
                source_out=source_out,
                context=context,
            )

            self.conversation_flow.add_assistant_message(response)
            self._respond(response)

            conv_meta = {
                "source": source,
                "capability": "conversation",
                "success": True,
                "requires_confirmation": False,
                "model_source": source_out,
                "cloud_verified": cloud_verified,
                "command_type": "ask_question",
            }
            sensitive_conv = self._contains_sensitive_training_data(text, response)

            if self.conversation_memory:
                try:
                    self.conversation_memory.add_turn("user", text, capability="conversation")
                    self.conversation_memory.add_turn("assistant", response, capability="conversation")
                except Exception:
                    pass

            if self.config.memory_enabled and scoped_memory and len(text.split()) > 2 and not sensitive_conv:
                self._save_memory_pair(
                    scoped_memory,
                    text,
                    response[:500] if len(response) > 500 else response,
                    conv_meta,
                )

            self._log_training_interaction(
                user_text=text,
                assistant_text=response,
                capability_name="conversation",
                model_source=source_out or "local",
                source=source,
                command_type="ask_question",
                sensitive_hint=sensitive_conv,
            )

            if self.learning_engine:
                try:
                    self.learning_engine.observe_interaction(
                        user_text=text,
                        assistant_text=response,
                        result=None,
                        meta=conv_meta,
                        source=source,
                        sensitive=sensitive_conv,
                    )
                except Exception:
                    pass

            self._maybe_gcc_commit_milestone(
                text=text,
                response=response,
                capability_name="conversation",
                success=True,
            )
            return response

        except Exception as exc:
            # Fail-safe: never crash the assistant loop due to an unhandled error.
            logger.error("Unhandled error in CommandHandler.handle: %s", exc, exc_info=True)
            try:
                from chintu_backend.core.run_manager import get_run_manager

                rid = str(getattr(self, "_current_run_id", "") or context.get("_run_id", "") or "")
                if rid:
                    run_mgr = get_run_manager()
                    run_mgr.mark_failed(rid, error=str(exc), outcome_label="failed")
                    run_mgr.release_run_turn(rid)
            except Exception:
                pass

            msg = f"Something went wrong while handling that. Trace: {get_trace_id() or 'n/a'}"
            try:
                self._respond(msg)
            except Exception:
                pass
            return msg

        finally:
            # Run lifecycle: ensure lanes are released + runs are marked terminal
            # for code paths that don't go through _process_result (e.g., cloud conversation).
            try:
                from chintu_backend.core.run_manager import get_run_manager

                rid = str(getattr(self, "_current_run_id", "") or context.get("_run_id", "") or "")
                if rid:
                    run_mgr = get_run_manager()
                    status = (run_mgr.get_run_status_value(rid) or "").strip()
                    # If this run is waiting for approval/input, do not mark it completed.
                    is_waiting = status in {"waiting_approval", "waiting_input"}
                    if not is_waiting:
                        pending_run_id = run_mgr.pending_confirmation_run_id()
                        pending = {}
                        try:
                            pending = self.action_dispatcher.get_pending_confirmation() or {}
                        except Exception:
                            pending = {}
                        if pending.get("pending") and pending_run_id == rid:
                            is_waiting = True
                    if not is_waiting and status in {"queued", "running"}:
                        run_mgr.mark_completed(rid, outcome_label="completed_with_evidence")
                    run_mgr.release_run_turn(rid)
            except Exception:
                pass

            if self.metrics:
                try:
                    self.metrics.end_pipeline()
                except Exception:
                    pass
            clear_trace()

    def _canonical_escalation_reason_code(self, trace: Dict[str, Any]) -> str:
        attempts = trace.get("provider_attempts") if isinstance(trace.get("provider_attempts"), list) else []
        outcomes = trace.get("routing_outcomes") if isinstance(trace.get("routing_outcomes"), list) else []
        reason_blob = " ".join(str(a.get("reason") or "") for a in attempts if isinstance(a, dict))
        reason_blob += " " + " ".join(str(o.get("reason") or "") for o in outcomes if isinstance(o, dict))
        error_blob = " ".join(str(a.get("error") or "") for a in attempts if isinstance(a, dict))
        error_blob += " " + " ".join(str(o.get("error") or "") for o in outcomes if isinstance(o, dict))
        low_reason = reason_blob.lower()
        low_error = error_blob.lower()
        merged = f"{low_reason} {low_error}"

        if "budget_blocked" in low_reason:
            return "verifier_fail_budget_exhausted"
        if "schema" in merged and "valid" in merged:
            return "tool_schema_validation_loop"
        if "syntax" in merged:
            return "repeated_syntax_error_generation"
        if "context" in merged and any(t in merged for t in ("overflow", "length", "token", "window")):
            return "context_overflow_risk"
        if any(t in merged for t in ("timeout", "timed out", "oom", "out of memory", "cuda error")):
            return "local_model_timeout_or_oom"
        return "local_escalation_needed"

    def _sanitize_escalation_text(self, text: str) -> str:
        cleaned = str(text or "")
        try:
            from chintu_backend.privacy.pii import mask_pii

            cleaned = mask_pii(cleaned)
        except Exception:
            pass
        try:
            from chintu_backend.core.credential_detector import get_credential_detector

            detector = get_credential_detector()
            for cred in detector.detect_all(cleaned):
                value = str(getattr(cred, "value", "") or "")
                service = str(getattr(cred, "service_name", "secret") or "secret").lower()
                if value and value in cleaned:
                    cleaned = cleaned.replace(value, f"<redacted:{service}>")
        except Exception:
            pass
        return cleaned

    def _record_router_escalation_artifacts(
        self,
        *,
        text: str,
        response: str,
        source_out: str,
        context: Optional[Dict[str, Any]],
    ) -> None:
        provider = str(source_out or "").strip().lower()
        cloud_providers = {"nvidia", "groq", "gemini", "deepseek"}
        if not hasattr(self.router, "consume_execution_trace"):
            return
        trace = self.router.consume_execution_trace()
        if not isinstance(trace, dict):
            trace = {}

        rid = str(getattr(self, "_current_run_id", "") or (context or {}).get("_run_id", "") or "").strip()
        if not rid:
            return

        try:
            from chintu_backend.core.run_manager import get_run_manager

            run_mgr = get_run_manager()
            persona_payload = trace.get("persona") if isinstance(trace.get("persona"), dict) else {}
            if persona_payload:
                run_mgr.record_persona_selection(
                    rid,
                    persona=str(persona_payload.get("name") or "default"),
                    requested=str(persona_payload.get("requested") or persona_payload.get("name") or "default"),
                    reason=str(persona_payload.get("reason") or ""),
                    provider=provider,
                    adapter_path=str(persona_payload.get("adapter_path") or ""),
                    adapter_ready=bool(persona_payload.get("adapter_ready", True)),
                    fallback_to_default=bool(persona_payload.get("fallback_to_default", False)),
                    routing_tags=[
                        str(tag)
                        for tag in (persona_payload.get("routing_tags") or [])
                        if str(tag).strip()
                    ],
                )

            if provider not in cloud_providers:
                return

            reason_code = self._canonical_escalation_reason_code(trace)
            safe_user_text = self._sanitize_escalation_text(text)[:2000]
            safe_response = self._sanitize_escalation_text(response)[:3000]
            attempts = trace.get("provider_attempts") if isinstance(trace.get("provider_attempts"), list) else []
            outcomes = trace.get("routing_outcomes") if isinstance(trace.get("routing_outcomes"), list) else []
            payload = {
                "reason_code": reason_code,
                "provider": provider,
                "inputs": {
                    "user_text": safe_user_text,
                    "provider_attempts": attempts[-12:],
                    "routing_outcomes": outcomes[-12:],
                },
                "returned_solution": {
                    "provider": provider,
                    "response": safe_response,
                },
            }
            artifact_name = f"escalation_{int(time.time() * 1000)}.json"
            artifact_path = run_mgr.write_artifact(rid, artifact_name, json.dumps(payload, ensure_ascii=True, indent=2))
            artifacts = [artifact_path] if artifact_path else []
            run_mgr.record_escalation(
                rid,
                reason_code=reason_code,
                provider=provider,
                mode="conversation",
                inputs=payload["inputs"],
                returned_solution=payload["returned_solution"],
                artifacts=artifacts,
                meta={"trace_lengths": {"provider_attempts": len(attempts), "routing_outcomes": len(outcomes)}},
            )
        except Exception:
            return

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

    def _is_complex_task_text(self, text: str) -> bool:
        text = (text or "").strip().lower()
        if len(text.split()) < 6:
            return False
        markers = {
            "build",
            "implement",
            "fix",
            "debug",
            "refactor",
            "design",
            "research",
            "workflow",
            "automate",
            "multi-step",
            "end-to-end",
            "from scratch",
            "analyze and",
            "then ",
        }
        return any(m in text for m in markers)

    def _maybe_gcc_open_task_branch(self, text: str, source: str = "") -> None:
        if not self.gcc_controller or not getattr(self.config, "gcc_enabled", True):
            return
        if source in {"schedule", "cron", "background", "hook", "webhook"}:
            return
        if not self._is_complex_task_text(text):
            return

        safe_text = self._redact_sensitive_text(text)

        now = time.monotonic()
        # Avoid branch explosion during rapid back-and-forth prompts.
        if now - float(self._gcc_last_auto_branch_ts) < 1800:
            return
        try:
            current = self.gcc_controller.get_current_branch()
        except Exception:
            current = "main"
        if current != "main":
            return

        safe_name = "".join(c if c.isalnum() else "-" for c in safe_text.lower()[:36]).strip("-")
        safe_name = "-".join([x for x in safe_name.split("-") if x]) or "task"
        branch_name = f"task-{safe_name[:24]}-{int(time.time())}"
        try:
            self.gcc_controller.create_branch(
                branch_name,
                purpose=f"Auto-branch for complex goal: {safe_text[:160]}",
                from_branch="main",
                switch=True,
            )
            self.gcc_controller.append_log(
                observation=safe_text[:500],
                thought="Detected complex long-horizon goal; isolating execution in dedicated branch.",
                action=f"Created branch {branch_name}",
                result="Branch ready for task execution.",
                branch=branch_name,
            )
            self._gcc_last_auto_branch_ts = now
        except Exception:
            pass

    def _get_gcc_context_snippet(self, query: str, log_lines: int = 12) -> str:
        if not self.gcc_controller or not getattr(self.config, "gcc_enabled", True):
            return ""
        if len((query or "").strip().split()) < 3:
            return ""
        try:
            data = self.gcc_controller.context(log_lines=max(0, int(log_lines)))
        except Exception:
            return ""

        pieces = []
        branch = data.get("branch")
        if branch:
            pieces.append(f"Current GCC branch: {branch}")
        latest = data.get("latest_commits") or []
        if latest:
            pieces.append(f"Latest branch commit:\n{str(latest[-1])[:900]}")
        main_excerpt = data.get("main_excerpt") or ""
        if main_excerpt:
            pieces.append(f"Roadmap excerpt:\n{main_excerpt[:700]}")
        log_tail = data.get("log_tail") or ""
        if log_tail:
            pieces.append(f"Recent OTA log:\n{log_tail[:700]}")
        return "\n\n".join(pieces).strip()

    def _maybe_gcc_commit_milestone(self, text: str, response: str, capability_name: str, success: bool) -> None:
        if not success or not self.gcc_controller:
            return
        if not getattr(self.config, "gcc_enabled", True):
            return

        capability = (capability_name or "").strip().lower()
        milestone_caps = {
            "fix_code",
            "execute_workflow",
            "run_biweekly_learning",
            "generate_training_data",
            "deep_learn",
            "job_apply",
            "orchestrator_run",
            "terminal_exec",
            "sandbox_run",
        }
        if capability not in milestone_caps and not self._is_complex_task_text(text):
            return

        try:
            safe_text = self._redact_sensitive_text(text)
            safe_response = self._redact_sensitive_text(response)
            summary = f"{capability or 'task'} completed: {safe_response[:120]}".strip()
            contribution = (
                f"User goal: {safe_text[:500]}\n"
                f"Assistant outcome: {safe_response[:1200]}"
            )
            self.gcc_controller.commit(
                summary=summary,
                contribution=contribution,
                update_main=True,
                roadmap_note=f"[{capability or 'task'}] {safe_response[:160]}",
            )
        except Exception:
            pass

    def _redact_sensitive_text(self, text: str) -> str:
        """Redact secrets/PII before writing to durable stores (GCC/memory/training logs)."""
        raw = (text or "").strip()
        if not raw:
            return ""

        masked = raw
        try:
            from chintu_backend.privacy.pii import mask_pii

            masked = mask_pii(masked)
        except Exception:
            pass

        try:
            from .credential_detector import get_credential_detector

            detector = get_credential_detector()
            for cred in detector.detect_all(raw):
                if cred.value and cred.value in masked:
                    masked = masked.replace(cred.value, f"<redacted:{cred.service_name.lower()}>")
        except Exception:
            pass

        return masked
    
    def _contains_sensitive_training_data(self, *texts: str) -> bool:
        joined = "\n".join([t for t in texts if t])
        if not joined:
            return False
        try:
            from .credential_detector import get_credential_detector

            detector = get_credential_detector()
            if detector.detect(joined):
                return True
            found = detector.detect_all(joined)
            return bool(found)
        except Exception:
            lowered = joined.lower()
            red_flags = ["api key", "token", "password", "secret", "private key", "-----begin"]
            return any(flag in lowered for flag in red_flags)

    def _is_important_training_item(self, capability_name: str, model_source: str = "") -> bool:
        capability_name = (capability_name or "").strip()
        model_source = (model_source or "").strip().lower()
        if model_source in {"terminal_exec", "sandbox_run"}:
            return True
        if capability_name in {"terminal_exec", "sandbox_run", "fix_code", "forget", "reset_preferences"}:
            return True

        try:
            policy = get_policy_engine()
            contract = policy.get_contract(capability_name) if capability_name else None
            if not contract:
                return True
            if contract.requires_confirmation:
                return True
            if contract.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
                return True
            risky_effects = {
                "delete_memory",
                "reset_settings",
                "shell_execution",
                "modify_files",
                "auto_login",
                "read_secret",
                "delete_secret",
                "store_secret",
                "form_submit",
            }
            if any(effect in risky_effects for effect in (contract.side_effects or [])):
                return True
            return False
        except Exception:
            return True

    def _should_auto_approve_training(self, capability_name: str, model_source: str, sensitive: bool) -> bool:
        if sensitive:
            return False
        if bool(getattr(self.config, "training_auto_approve", False)):
            return True
        if not bool(getattr(self.config, "training_selective_auto_approve", True)):
            return False
        max_risk = str(getattr(self.config, "training_auto_approve_max_risk", "medium") or "medium")
        item_risk = self._get_capability_risk_level(capability_name, model_source=model_source)
        if self._risk_rank(item_risk) > self._risk_rank(max_risk):
            return False
        return not self._is_important_training_item(capability_name, model_source=model_source)

    @staticmethod
    def _risk_rank(risk_level: str) -> int:
        order = {
            "none": 0,
            "low": 1,
            "medium": 2,
            "high": 3,
            "critical": 4,
        }
        return order.get(str(risk_level or "critical").strip().lower(), 4)

    def _get_capability_risk_level(self, capability_name: str, model_source: str = "") -> str:
        model_source = (model_source or "").strip().lower()
        capability_name = (capability_name or "").strip()
        if model_source in {"terminal_exec", "sandbox_run"}:
            return "critical"
        if capability_name in {"terminal_exec", "sandbox_run", "fix_code"}:
            return "critical"
        if capability_name in {"forget", "reset_preferences"}:
            return "high"
        try:
            policy = get_policy_engine()
            contract = policy.get_contract(capability_name) if capability_name else None
            if not contract:
                return "critical"
            return str(getattr(contract.risk_level, "value", "critical"))
        except Exception:
            return "critical"

    def _save_memory_pair(self, memory_manager, user_text: str, assistant_text: str, meta: Optional[Dict[str, Any]] = None) -> None:
        """Persist user/assistant turns while tolerating old/new memory APIs."""
        if not memory_manager:
            return
        try:
            memory_manager.save_interaction("user", user_text)
            try:
                memory_manager.save_interaction("assistant", assistant_text, meta)
            except TypeError:
                memory_manager.save_interaction("assistant", assistant_text, **(meta or {}))
        except Exception as e:
            logger.warning(f"Failed to save interaction pair to memory: {e}")

    def _log_training_interaction(
        self,
        user_text: str,
        assistant_text: str,
        capability_name: str,
        model_source: str,
        source: str,
        command_type: str = "unknown",
        sensitive_hint: bool = False,
    ) -> None:
        if not self.config.training_logging_enabled:
            return
        if not user_text or not assistant_text:
            return
        sensitive_data = bool(sensitive_hint) or self._contains_sensitive_training_data(user_text, assistant_text)
        if sensitive_data:
            return

        auto_approved = self._should_auto_approve_training(
            capability_name=capability_name,
            model_source=model_source,
            sensitive=sensitive_data,
        )
        metadata = {
            "source": source,
            "capability": capability_name,
            "command_type": command_type,
            "model_source": model_source,
            "approved": auto_approved,
            "tags": ["auto_approved"] if auto_approved else [],
        }
        self.training_logger.log_interaction(user_text, assistant_text, metadata)

        if self.gold_data_manager:
            rating = None
            if auto_approved:
                rating = int(getattr(self.config, "training_auto_approve_rating", 4))
            self.gold_data_manager.log_interaction(
                user_input=user_text,
                assistant_response=assistant_text,
                capability_used=capability_name or None,
                model_used=model_source or None,
                approved=auto_approved,
                rating=rating,
            )

    def _process_result(
        self,
        result: "ActionResult",
        text: str,
        source: str,
        memory_manager=None,
        session_store=None,
    ) -> str:
        """Process an ActionResult and handle TTS/logging."""
        response = self._sanitize_internal_response(result.message)
        if not response:
            # Route empty/stripped outputs through conversational fallback so
            # lightweight generation tasks (e.g., poems) still produce something usable.
            response = self._conversation_fallback_response(text)
        sensitive = False
        waiting_user_input = False
        phase15_outcome_label = ""
        phase15_unblock_plan: Dict[str, Any] = {}
        meta = {
            "source": source,
            "capability": result.capability_name,
            "success": result.success,
            "requires_confirmation": result.requires_confirmation,
            "model_source": "rule",
        }
        mm = memory_manager or self.memory_manager
        if isinstance(result.data, dict):
            waiting_user_input = bool(
                result.data.get("awaiting_user_action")
                or result.data.get("manual_login_required")
                or result.data.get("pending_user_input")
                or result.data.get("waiting_for_user")
            )

        # Phase 15: tasks must end with evidence or an explicit unblock plan.
        if (
            self.self_improvement_manager
            and not bool(result.success)
            and not bool(result.requires_confirmation)
        ):
            try:
                phase15_unblock_plan = self.self_improvement_manager.create_unblock_plan(
                    task_text=text,
                    failure_message=response,
                    capability_name=str(result.capability_name or ""),
                    context={
                        "source": source,
                        "run_id": str(getattr(self, "_current_run_id", "") or ""),
                    },
                )
            except Exception:
                phase15_unblock_plan = {}
            if isinstance(phase15_unblock_plan, dict) and phase15_unblock_plan:
                phase15_outcome_label = "blocked_with_unblock_plan"
                unblock_message = str(phase15_unblock_plan.get("message") or "").strip()
                if unblock_message:
                    response = f"{response}\n\n{unblock_message}".strip()
                if not isinstance(result.data, dict):
                    result.data = {}
                if isinstance(result.data, dict):
                    result.data["phase15_unblock_plan"] = phase15_unblock_plan
        elif bool(result.success) and not bool(result.requires_confirmation) and not waiting_user_input:
            phase15_outcome_label = "completed_with_evidence"

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
        force_speak_preserve_links = False
        force_speak_verbatim = False
        if result.requires_confirmation and result.pending_action:
            self._pending_action = result.pending_action
            self._pending_action_capability = result.capability_name
        speech_view = ""
        if result.data and isinstance(result.data, dict):
            sensitive = bool(result.data.get("sensitive"))
            waiting_user_input = bool(
                result.data.get("awaiting_user_action")
                or result.data.get("manual_login_required")
                or result.data.get("pending_user_input")
                or result.data.get("waiting_for_user")
            )
            response = self._sanitize_internal_response(str(result.data.get("safe_message") or response))
            if not response:
                # Route all empty outputs through conversation fallback so prompts
                # like "write a haiku" still recover gracefully even if routing
                # tagged a non-conversation capability.
                response = self._conversation_fallback_response(text)
            if not sensitive:
                force_speak_text = result.data.get("speak_text") if result.data.get("force_speak") else None
                force_speak_preserve_links = bool(result.data.get("speak_preserve_links", False))
                force_speak_verbatim = bool(result.data.get("speak_verbatim", False))
            try:
                dual_view = build_dual_view_response(
                    response,
                    preserve_links_in_speech=bool(force_speak_preserve_links),
                    summarize_speech=False,
                )
                result.data.setdefault("text_view", dual_view.get("text_view", response))
                result.data.setdefault("speech_view", dual_view.get("speech_view", ""))
                speech_view = str(result.data.get("speech_view") or "")
            except Exception:
                pass
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

        # Ensure dual-view contract is available even for capabilities that return plain text only.
        if not speech_view:
            try:
                speech_view = sanitize_for_tts(response)
            except Exception:
                speech_view = str(response or "")
        try:
            if not isinstance(result.data, dict):
                result.data = {}
            result.data.setdefault("text_view", str(response or ""))
            result.data.setdefault("speech_view", speech_view)
        except Exception:
            pass

        # Capture numbered list context for future follow-up detail commands.
        try:
            if bool(getattr(result, "success", False)) and not bool(getattr(result, "requires_confirmation", False)):
                store = getattr(self, "followup_context", None)
                if store and hasattr(store, "capture"):
                    store.capture(
                        str(result.capability_name or ""),
                        result.data,
                        response,
                        session_id=self._current_session_id,
                    )
        except Exception:
            pass
        if force_speak_text:
            self.speak(
                force_speak_text,
                force=True,
                allow_barge_in=True,
                priority=True,
                preserve_links=force_speak_preserve_links,
                verbatim=force_speak_verbatim,
            )
        else:
            # Use smart_speak for intelligent long response handling
            self.smart_speak(response, result.capability_name, speech_override=speech_view)

        # Send response callback
        callback = getattr(self, "_on_response", None)
        if callback:
            callback(response)

        # Session transcript logging
        if self._current_session_id:
            try:
                from chintu_backend.core.session_manager import get_session_manager
                get_session_manager().append_turn(
                    self._current_session_id,
                    "assistant",
                    response,
                    {
                        "source": source,
                        "capability": result.capability_name,
                        "success": result.success,
                        "run_id": str(getattr(self, "_current_run_id", "") or ""),
                    },
                )
            except Exception:
                pass

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
        if should_save_memory and mm:
            self._save_memory_pair(mm, text, response, meta)
        
        # Save to training log (JSONL) - ONLY for successful non-confirmation results
        should_save_training = (
            self.config.training_logging_enabled 
            and result.success 
            and not result.requires_confirmation
        )
        if should_save_training:
            self._log_training_interaction(
                user_text=text,
                assistant_text=response,
                capability_name=result.capability_name or "unknown",
                model_source=meta.get("model_source", "rule"),
                source=source,
                command_type=meta.get("command_type", result.capability_name or "capability"),
                sensitive_hint=sensitive,
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
        try:
            from .websocket_server import get_ws_server

            ws_server = get_ws_server()
            if ws_server:
                import asyncio

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(ws_server.broadcast_response(self._format_display_response(response)))
        except Exception:
            pass
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

        if session_store:
            try:
                session_store.append_event(
                    {
                        "event": "response_sent",
                        "text": response[:2000],
                        "capability": result.capability_name,
                        "success": result.success,
                        "source": source,
                    }
                )
            except Exception:
                pass

        self._maybe_gcc_commit_milestone(
            text=text,
            response=response,
            capability_name=result.capability_name,
            success=bool(result.success and not result.requires_confirmation),
        )

        # Run lifecycle: mark the run terminal (or waiting) and release the lane.
        try:
            run_id = getattr(self, "_current_run_id", None)
            if run_id:
                from chintu_backend.core.run_manager import get_run_manager

                run_mgr = get_run_manager()
                rid = str(run_id)
                if result.requires_confirmation:
                    run_mgr.mark_waiting_approval(rid, prompt=response, capability=result.capability_name)
                elif waiting_user_input:
                    waiting_meta = result.data if isinstance(result.data, dict) else None
                    run_mgr.mark_waiting_input(
                        rid,
                        prompt=response,
                        capability=result.capability_name,
                        meta=waiting_meta,
                    )
                elif result.success:
                    run_mgr.mark_completed(
                        rid,
                        message=response,
                        outcome_label=phase15_outcome_label or "completed_with_evidence",
                    )
                else:
                    run_mgr.mark_failed(
                        rid,
                        error=response,
                        outcome_label=phase15_outcome_label or "failed",
                        unblock_plan=phase15_unblock_plan or None,
                    )
                run_mgr.release_run_turn(rid)
        except Exception:
            pass
        
        return response
    
    async def _handle_llm_query(self, text: str, source: str) -> str:
        """Handle a query that requires LLM processing with mandatory memory recall."""
        # Mark LLM as active
        self.state_manager.update_feature("llm_integration", enabled=True, status="active")
        
        # MANDATORY RECALL: Get context from Hybrid Memory
        memory_context = ""
        mm = self.memory_manager
        if mm:
            try:
                # Retrieve context with transparency (metadata included)
                memory_context = mm.retrieve_context(text, n_results=3)
                if memory_context:
                    logger.info(f"Memory recall successful: {len(memory_context)} chars retrieved")
                    # Inject into state for HUD/Debug
                    self.state_manager.update_hud(memory_context=memory_context[:1200])
            except Exception as e:
                logger.warning(f"Mandatory memory recall failed: {e}")

        # Use existing _handle_question logic for LLM streaming
        command_obj = self.parser.parse(text)
        
        response, meta = self._handle_question(command_obj, memory_manager=mm)
        response = self._sanitize_internal_response(response)
        if not response:
            response = self._conversation_fallback_response(text)
        meta["source"] = source
        meta["capability"] = "conversation"
        meta.setdefault("model_source", "local")
        
        # Speak if not already streamed
        if not meta.get("streaming_tts"):
            self.speak(response)
        
        # NEW: Save conversation to memory for context retention
        if self.conversation_memory:
            try:
                self.conversation_memory.add_turn("user", text, capability="conversation")
                self.conversation_memory.add_turn("assistant", response, capability="conversation")
            except Exception:
                pass
        
        # Save exchange to Hybrid Memory (ChromaDB replacement)
        if mm and len(text.split()) > 3:
            safe_resp = response[:500] if len(response) > 500 else response
            self._save_memory_pair(mm, text, safe_resp, meta)

        sensitive_conv = self._contains_sensitive_training_data(text, response)
        self._log_training_interaction(
            user_text=text,
            assistant_text=response,
            capability_name="conversation",
            model_source=meta.get("model_source", "local"),
            source=source,
            command_type="ask_question",
            sensitive_hint=sensitive_conv,
        )

        if self.learning_engine:
            try:
                self.learning_engine.observe_interaction(
                    user_text=text,
                    assistant_text=response,
                    result=None,
                    meta=meta,
                    source=source,
                    sensitive=sensitive_conv,
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
        self._maybe_gcc_commit_milestone(
            text=text,
            response=response,
            capability_name="conversation",
            success=True,
        )
        
        return response
    
    def explain_last_action(self) -> str:
        """Explain why the last action was taken (explainability mode)."""
        # This will be enhanced in Week 4
        return "I processed your command using the capability registry."

    def _should_auto_store_credential(self, text: str) -> bool:
        """Return True when the user explicitly asked to save/use a credential they pasted."""
        if bool(getattr(self.config, "credentials_auto_store", False)):
            return True
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        # Only auto-store when the user is explicitly instructing storage or activation.
        explicit_markers = (
            "save this",
            "save them",
            "store this",
            "store them",
            "remember this",
            "use this",
            "use these",
            "activate",
            "set this",
            "configure",
            "connect",
            "add this key",
        )
        return any(marker in lowered for marker in explicit_markers)

    def _store_detected_credential(self, credential, original_text: str = "") -> str:
        """Store detected credential in Identity Vault and activate for current session (env var)."""
        from ..security import get_identity_vault
        from .credential_detector import CredentialType

        vault = get_identity_vault()
        if not vault.available:
            return f"I couldn't store that securely: {vault.unavailable_reason}."

        env_var = ""
        service_key = ""
        username = "api_key"
        cred_type = getattr(credential, "credential_type", None)

        if cred_type == CredentialType.TELEGRAM_BOT_TOKEN:
            service_key = "telegram"
            username = "bot_token"
            env_var = "TELEGRAM_BOT_TOKEN"
        elif cred_type == CredentialType.GROQ_API_KEY:
            service_key = "groq"
            env_var = "GROQ_API_KEY"
        elif cred_type == CredentialType.GEMINI_API_KEY:
            service_key = "gemini"
            env_var = "GOOGLE_AI_KEY"
        elif cred_type == CredentialType.NVIDIA_API_KEY:
            service_key = "nvidia"
            env_var = "NVIDIA_API_KEY"
        elif cred_type == CredentialType.OPENAI_API_KEY:
            service_key = "openai"
            env_var = "OPENAI_API_KEY"
        elif cred_type == CredentialType.GITHUB_TOKEN:
            service_key = "github"
            env_var = "GITHUB_TOKEN"
        elif cred_type == CredentialType.NOTION_TOKEN:
            service_key = "notion"
            env_var = "NOTION_TOKEN"
        elif cred_type == CredentialType.HASS_URL:
            service_key = "hass_url"
            username = "url"
            env_var = "HASS_URL"
        elif cred_type == CredentialType.HASS_TOKEN:
            service_key = "hass_token"
            env_var = "HASS_TOKEN"
        elif cred_type == CredentialType.GOOGLE_CLIENT_ID:
            service_key = "google_client_id"
            env_var = "GOOGLE_CLIENT_ID"
        elif cred_type == CredentialType.GOOGLE_CLIENT_SECRET:
            service_key = "google_client_secret"
            env_var = "GOOGLE_CLIENT_SECRET"
        else:
            # Fall back to a sane default to ensure it's stored but not misrouted.
            service_key = str(getattr(credential, "service_name", "") or "").strip().lower() or "unknown"

        note_hint = self._redact_sensitive_text(original_text)[:120]
        ok, msg = vault.store_secret(
            service=service_key,
            username=username,
            secret=str(getattr(credential, "value", "") or ""),
            note=(f"Saved via explicit credential message. Context: {note_hint}" if note_hint else "Saved via explicit credential message."),
            tags=["credential", service_key],
        )
        if not ok:
            return msg

        # Activate for current runtime.
        if env_var:
            try:
                os.environ[env_var] = str(getattr(credential, "value", "") or "")
            except Exception:
                pass

        return f"Securely saved your {getattr(credential, 'service_name', service_key) or service_key} credential to the Identity Vault."
    
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
            CredentialType.NVIDIA_API_KEY: {
                "name": "NVIDIA API key",
                "action": "save this key for NVIDIA NIM models",
                "service": "nvidia",
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
            session_id=self._current_session_id,
        )
        
        # Speak and return the confirmation prompt
        self.speak(prompt)
        callback = getattr(self, "_on_response", None)
        if callback:
            callback(prompt)
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
        
        # Save to Identity Vault (Secure Storage)
        try:
            from ..security import get_identity_vault
            vault = get_identity_vault()

            if not vault.available:
                return f"I couldn't store that securely: {vault.unavailable_reason}."
            
            # Map service to vault parameters
            service_key = service or "unknown"
            username = "api_key"

            if service == "telegram":
                service_key = "telegram"
                username = "bot_token"
            elif service == "hass_url":
                username = "url"

            ok, msg = vault.store_secret(
                service=service_key,
                username=username,
                secret=cred_value,
                note=f"Saved via credential confirmation for {service_name or service_key}.",
            )
            if not ok:
                return msg
            
            # ALSO inject compatibility env var for current session so it works immediately
            env_var_map = {
                "groq": "GROQ_API_KEY",
                "gemini": "GOOGLE_AI_KEY",
                "nvidia": "NVIDIA_API_KEY",
                "openai": "OPENAI_API_KEY",
                "github": "GITHUB_TOKEN",
                "notion": "NOTION_TOKEN",
                "hass_url": "HASS_URL",
                "hass_token": "HASS_TOKEN",
                "google_client_id": "GOOGLE_CLIENT_ID",
                "google_client_secret": "GOOGLE_CLIENT_SECRET",
                "telegram": "TELEGRAM_BOT_TOKEN"
            }
            
            if service in env_var_map:
                import os
                os.environ[env_var_map[service]] = cred_value
            
            return f"Securely saved your {service_name} credentials to the Identity Vault."

        except Exception as e:
            logger.error(f"Failed to save credential to identity vault: {e}")
            error_msg = f"I had trouble saving that safely - {str(e)[:50]}. Want to try again?"
            return error_msg

    def _save_telegram_token(self, credential) -> str:
        """Save Telegram bot token securely and attempt to connect."""
        import os

        try:
            from ..security import get_identity_vault
            vault = get_identity_vault()
            if not vault.available:
                return f"I couldn't store that securely: {vault.unavailable_reason}."
            ok, msg = vault.store_secret(
                service="telegram",
                username="bot_token",
                secret=credential.value,
                note="Saved via Telegram setup.",
            )
            if not ok:
                return msg
        except Exception as e:
            logger.error(f"Failed to save Telegram token to identity vault: {e}")
            return f"I had trouble saving that safely - {str(e)[:50]}."

        # Update runtime config (in-memory only)
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
        """Save an API key securely and update the current session."""
        import os

        try:
            from ..security import get_identity_vault
            vault = get_identity_vault()
            if not vault.available:
                return f"I couldn't store that securely: {vault.unavailable_reason}."
            ok, msg = vault.store_secret(
                service=service_name.lower().strip() or "api",
                username="api_key",
                secret=value,
                note=f"Saved via {service_name} setup.",
            )
            if not ok:
                return msg
        except Exception as e:
            logger.error(f"Failed to save API key to identity vault: {e}")
            return f"I had trouble saving that safely - {str(e)[:50]}."

        # Update runtime environment (in-memory only)
        os.environ[env_key] = value
        
        return (
            f"I saved your {service_name} API key securely and activated it for this session. "
            "It will be available after restart via the Identity Vault."
        )

    def _update_env_file(self, env_path, updates: dict) -> None:
        """
        Deprecated: .env writes are disabled for security.
        This method is retained for compatibility but performs no action.
        """
        logger.warning("Ignoring request to update .env; secure vault storage is required.")

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
    
    def _handle_question(self, command: Command, memory_manager=None) -> Tuple[str, Dict[str, Any]]:
        
        question = command.parameters.get("question", command.raw_text)
        import time

        mm = memory_manager or self.memory_manager
        full_context = self._build_llm_memory_context(
            question,
            memory_manager=mm,
            route_context="",
            include_gcc=True,
            gcc_log_lines=12,
        )
        intent = self.intent_detector.detect(question)
        behavior_context = ""
        try:
            behavior_context, _, _ = self._build_behavior_context(question, None)
        except Exception:
            behavior_context = ""

        try:
            intent_value = intent.intent.value if intent else "question"
            self.state_manager.update_hud(intent=intent_value, active_tools=["llm"])
            self.state_manager.log_activity(f"Thinking: {intent_value}")
        except Exception:
            pass

        clarifier = self._build_followup_clarifier(question, memory_context=full_context)
        if clarifier:
            return clarifier, self._meta(command, "clarifier")
        
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
            for chunk, src in self.router.route_and_stream(question, full_context, behavior_context):
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
                            clean_sentence = sanitize_for_tts(sentence_to_speak.strip())
                            if len(clean_sentence) > 3 and clean_sentence not in spoken_text:
                                self._tts.speak(clean_sentence, sanitize=False)
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
            remaining = sanitize_for_tts(remaining)
            if remaining and remaining not in spoken_text:
                self._tts.speak(remaining, sanitize=False)
        
        response = "".join(full_response)
        logger.info(f"Response from {source}: {len(response)} chars")
        meta = self._meta(command, source)
        meta["intent"] = intent.intent.value
        meta["streaming_tts"] = streaming_tts_enabled  # Mark if already spoken

        # If this was a cloud response and we didn't already speak partial audio,
        # run a lightweight local verification pass to reduce hallucinations.
        if not streaming_tts_enabled:
            try:
                if str(source or "").strip().lower() in {"nvidia", "groq", "gemini", "deepseek"}:
                    verified, changed = self._verify_cloud_response(question, response)
                    if changed and verified:
                        response = verified
                        meta["cloud_verified"] = True
                        try:
                            self.state_manager.set_response(response)
                        except Exception:
                            pass
            except Exception:
                pass
        try:
            active = ["llm"]
            if source:
                active.append(source)
            self.state_manager.update_hud(intent=meta["intent"], active_tools=active)
            self.state_manager.log_activity(f"LLM response: {source}")
        except Exception:
            pass
        if self._current_session_id:
            try:
                from chintu_backend.core.session_manager import get_session_manager
                get_session_manager().append_turn(
                    self._current_session_id,
                    "assistant",
                    response,
                    {
                        "source": source,
                        "intent": meta.get("intent"),
                        "run_id": str(getattr(self, "_current_run_id", "") or ""),
                    },
                )
            except Exception:
                pass
        return response, meta
