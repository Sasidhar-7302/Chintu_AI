"""Command handler - processes and executes commands."""

import os
import logging
from typing import Optional, Callable, Dict, Any, Tuple

from ..utils.command_parser import CommandParser, Command, CommandType
from ..automation.app_launcher import AppLauncher
from ..automation.job_search import JobSearcher
from ..llm.ollama_client import OllamaClient
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

        # Initialize Memory Manager (ChromaDB)
        self.memory_manager = None
        if self.config.memory_enabled:
            try:
                self.memory_manager = MemoryManager(
                    persistence_path=str(self.config.memory_store_path or "memory_store")
                )
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
        
        # Initialize Training Data Logger (JSONL for fine-tuning)
        from ..memory.training_logger import TrainingDataLogger
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
        
        # Smart model router for fast responses
        groq_key = os.environ.get("GROQ_API_KEY", "")
        gemini_key = os.environ.get("GOOGLE_AI_KEY", "")
        self.router = ModelRouter(groq_api_key=groq_key, gemini_api_key=gemini_key, local_llm=self.llm)
        self.intent_detector = IntentDetector()
        
        # Initialize Capability Registry (new capability-based routing)
        from .capabilities import get_registry
        from .capability_handlers import register_core_capabilities
        from ..memory.memory_capabilities import register_memory_capabilities
        from ..memory.temporal_capabilities import register_temporal_capabilities
        from ..memory.preferences import get_preference_manager
        from ..tasks.task_capabilities import register_task_capabilities
        from .help_capabilities import register_help_capabilities
        from ..vision.app_listing import register_app_listing_capabilities
        
        self.capability_registry = get_registry()
        register_core_capabilities()
        register_memory_capabilities()
        
        # Initialize Learning Signal Manager
        from ..memory.learning_signals import get_signal_manager
        self.signal_manager = get_signal_manager()
        
        # Initialize Preference Manager
        from ..memory.preferences import get_preference_manager
        self.preference_manager = get_preference_manager()
        
        # Initialize Retrieval Router (RAG Pipeline)
        from ..memory.retrieval_router import get_retrieval_router
        self.retrieval_router = get_retrieval_router()
        logger.info("RetrievalRouter initialized for RAG pipeline")
        
        # Initialize Deep Reasoner (Phase 3 Integration)
        from ..llm.reasoning import get_deep_reasoner
        get_deep_reasoner(self.llm)
        logger.info("Deep Reasoning Engine initialized")
        register_temporal_capabilities()
        register_task_capabilities()
        register_help_capabilities()
        register_app_listing_capabilities()
        
        # Register enhancement capabilities (screenshot, clipboard, repeat, context)
        try:
            from .capability_handlers import register_enhancement_capabilities
            register_enhancement_capabilities()
        except Exception as e:
            logger.warning(f"Enhancement capabilities not available: {e}")
        
        # Register Phase 1 capabilities (search, files)
        try:
            from ..search import register_search_capabilities
            register_search_capabilities(self.capability_registry)
        except ImportError as e:
            logger.warning(f"Search capabilities not available: {e}")
            try:
                from .error_reporter import report_error, ErrorSeverity
                report_error(
                    e,
                    severity=ErrorSeverity.WARNING,
                    component="capabilities",
                    user_message=f"Search capabilities unavailable: {e}",
                )
            except Exception:
                pass
        
        try:
            from ..files import register_file_capabilities
            register_file_capabilities(self.capability_registry)
        except ImportError as e:
            logger.warning(f"File capabilities not available: {e}")
            try:
                from .error_reporter import report_error, ErrorSeverity
                report_error(
                    e,
                    severity=ErrorSeverity.WARNING,
                    component="capabilities",
                    user_message=f"File capabilities unavailable: {e}",
                )
            except Exception:
                pass
        
        # Register Phase 2 capabilities (browser automation)
        try:
            from ..browser import register_browser_capabilities
            register_browser_capabilities(self.capability_registry)
        except ImportError as e:
            logger.warning(f"Browser capabilities not available: {e}")
            try:
                from .error_reporter import report_error, ErrorSeverity
                report_error(
                    e,
                    severity=ErrorSeverity.WARNING,
                    component="capabilities",
                    user_message=f"Browser capabilities unavailable: {e}",
                )
            except Exception:
                pass
        
        # Register Phase 3 capabilities (agentic workflows)
        try:
            from ..agents import register_agent_capabilities
            register_agent_capabilities(self.capability_registry)
        except ImportError as e:
            logger.warning(f"Agent capabilities not available: {e}")
            try:
                from .error_reporter import report_error, ErrorSeverity
                report_error(
                    e,
                    severity=ErrorSeverity.WARNING,
                    component="capabilities",
                    user_message=f"Agent capabilities unavailable: {e}",
                )
            except Exception:
                pass
        
        # Register Phase 4 capabilities (automation)
        try:
            from ..automation import register_automation_capabilities
            register_automation_capabilities(self.capability_registry)
        except ImportError as e:
            logger.warning(f"Automation capabilities not available: {e}")
            try:
                from .error_reporter import report_error, ErrorSeverity
                report_error(
                    e,
                    severity=ErrorSeverity.WARNING,
                    component="capabilities",
                    user_message=f"Automation capabilities unavailable: {e}",
                )
            except Exception:
                pass
        
        logger.info(f"Capability Registry initialized with {len(self.capability_registry.list_capabilities())} capabilities")
        
        # Initialize Conversation Memory for context tracking
        try:
            from ..memory.conversation_memory import get_conversation_memory
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
        
        # Initialize Explainability Engine (Week 4)
        from .explainability import get_explainability
        self.explainability = get_explainability()
        logger.info("ExplainabilityEngine initialized")
        
        self._on_response: Optional[Callable[[str], None]] = None
        self._allow_barge_in = False
        self._last_response: str = ""  # Store for "read it" command
        self._last_response_capability: str = ""  # Track what generated the response
        
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
        # Also send to UI if response callback is set
        if self._on_response:
            self._on_response(reminder_msg)

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
    
    def handle(self, text: str, source: str = "unknown") -> str:
        """
        Handle a transcribed command using the Capability Registry.
        
        Flow: STT -> Capability Match -> Action -> Result -> TTS
        No LLM executes OS actions directly - all go through capability handlers.
        
        Args:
            text: Transcribed text from speech
            source: Source of the command (audio, text, etc.)
            
        Returns:
            Response text
        """
        from .capabilities import ActionResult
        
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
            return ""
        
        # =====================================================================
        # PHASE 3: CONFIDENCE REPAIR LOOP
        # If transcript came with low confidence marker, ask to repeat
        # =====================================================================
        if text.startswith("__LOW_CONFIDENCE__"):
            logger.info("Low confidence transcript, asking for repeat")
            repair_response = "I didn't catch that clearly. Could you repeat?"
            self.speak(repair_response)
            return repair_response

        logger.info(f"Handling command: '{text}'")
        
        # Clear any previous interrupt before normal processing
        interrupt_handler.clear_interrupt()
        
        try:
            # Check for pending confirmation
            if self.capability_registry.has_pending():
                if any(word in text.lower() for word in ["yes", "confirm", "proceed", "do it", "go ahead"]):
                    result = self.capability_registry.confirm_pending()
                    if result:
                        return self._process_result(result, text, source)
                    return "Action completed."
                elif any(word in text.lower() for word in ["no", "cancel", "stop", "nevermind"]):
                    self.capability_registry.cancel_pending()
                    return "Okay, I've cancelled that."

            # =====================================================================
            # PHASE 4: LEARNING SIGNALS (PREFERENCES)
            # Detect corrections like "Don't do X" and propose updates
            # =====================================================================
            signals = self.signal_manager.analyze_feedback(text)
            if signals:
                # If we detect a preference correction, prioritize handling it
                # We only handle the first/strongest signal for now
                signal = signals[0]
                proposal_text = self.signal_manager.process_signal(signal)
                
                # We structure this as a confirmation request for the next turn
                self.capability_registry.request_confirmation(
                    action_name="update_preference",
                    description=f"save preference: {signal.content}",
                    data=signal.proposed_action,  # Store the proposed update
                    command=text
                )
                self.speak(proposal_text)
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
            
            context = {
                "source": source,
                "command_handler": self,
                "user_preferences": user_prefs.to_dict(),
                "rag_context": rag_context  # Injected RAG context
            }

            # Try to match a capability
            capability = self.capability_registry.match(text)

            if capability:
                logger.info(f"Matched capability: {capability.name}")
                
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
                        self.speak(clarify_msg)
                        return clarify_msg

                # Execute capability
                result = self.capability_registry.execute(
                    capability,
                    text,
                    context,  # Pass the enriched context (with preferences)
                )

                # Handle LLM routing (conversation capability)
                if result.data and result.data.get("use_llm"):
                    return self._handle_llm_query(text, source)

                return self._process_result(result, text, source)

            # No capability matched - try semantic intent classification first
            logger.info("No capability matched, trying semantic intent routing...")
            semantic_capability = self._classify_intent_semantically(text)
            
            if semantic_capability:
                # Found a matching capability through semantic understanding
                logger.info(f"Semantic match found: {semantic_capability}")
                result = self.capability_registry.execute(
                    semantic_capability,
                    text,
                    text,
                    context,  # Pass enriched context
                )
                return self._process_result(result, text, source)
            
            # Truly no match - route to LLM for conversation
            logger.info("No capability matched (even semantically), routing to LLM")
            return self._handle_llm_query(text, source)
        finally:
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
        if result.data and isinstance(result.data, dict):
            force_speak_text = result.data.get("speak_text") if result.data.get("force_speak") else None
        if force_speak_text:
            self.speak(force_speak_text, force=True, allow_barge_in=True, priority=True)
        else:
            # Use smart_speak for intelligent long response handling
            self.smart_speak(response, result.capability_name)
        
        # Send response callback
        if self._on_response:
            self._on_response(response)
        
        # Save to memory (ChromaDB) - ONLY if action was SUCCESSFUL and not a confirmation
        # This prevents polluting memory with failed actions or pending confirmations
        should_save_memory = (
            self.config.memory_enabled 
            and result.success 
            and not result.requires_confirmation
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

        self.state_manager.set_response(
            self._format_display_response(response),
            raw=response,
        )
        self.state_manager.set_debug_info(
            last_capability=result.capability_name,
            last_model="rule",
            trace_id=get_trace_id(),
        )
        
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
        
        # LLM chat is not saved to memory/training logs (only explicit actions are)
        
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
        
        # Retrieve context from memory
        memory_context = ""
        user_profile = ""
        if self.config.memory_enabled and self.memory_manager:
            memory_context = self.memory_manager.retrieve_context(question, n_results=self.config.memory_top_k)
            user_profile = self.memory_manager.get_profile_context()
            
        full_context = f"{user_profile}\n\nRelevant Context:\n{memory_context}".strip()
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
        
        try:
            for chunk, src in self.router.route_and_stream(question, full_context):
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
                return "I'm having trouble processing that request.", self._meta(command, "error")
        
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
