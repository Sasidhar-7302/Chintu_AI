"""Smart Model Router for Chintu - Professional AI Architecture.

Routes tasks to appropriate handlers:
- Rule-based (no LLM) for system commands
- Groq cloud (fast ~100ms) for complex tasks  
- Local LLM only for simple chat if cloud unavailable

Integrates with BudgetManager for rate limiting and Metrics for observability.
"""

import os
import re
import logging
import time
from enum import Enum
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

# Import budget manager and metrics for observability
try:
    from .budget_manager import get_budget_manager
    HAS_BUDGET = True
except ImportError:
    HAS_BUDGET = False

try:
    from .metrics import get_metrics
    HAS_METRICS = True
except ImportError:
    HAS_METRICS = False

try:
    from chintu.privacy.pii import mask_pii
except ImportError:
    def mask_pii(text): return text # Fallback


# Import degraded mode to avoid cloud calls when offline or limited
try:
    from .degraded_mode import get_degraded_mode, SystemMode
    HAS_DEGRADED = True
except ImportError:
    HAS_DEGRADED = False

logger = logging.getLogger(__name__)


class TaskComplexity(Enum):
    """Task complexity levels."""
    TRIVIAL = "trivial"       # No LLM needed - rule-based
    SIMPLE = "simple"         # Local small model OK
    MEDIUM = "medium"         # Prefer cloud
    COMPLEX = "complex"       # Require cloud LLM


class Intent(Enum):
    """Detected intents."""
    OPEN_APP = "open_app"
    OPEN_URL = "open_url"
    SEARCH_WEB = "search_web"
    SEARCH_JOBS = "search_jobs"
    SET_REMINDER = "set_reminder"
    GET_TIME = "get_time"
    GET_DATE = "get_date"
    GREETING = "greeting"
    SIMPLE_CHAT = "simple_chat"
    QUESTION = "question"
    CODING = "coding"
    RESEARCH = "research"
    DRAFT_EMAIL = "draft_email"
    DRAFT_RESUME = "draft_resume"
    SCREEN_QUERY = "screen_query"
    SCREEN_CONTROL = "screen_control"
    READ_ARTICLE = "read_article"
    SWITCH_WINDOW = "switch_window"
    REASONING = "reasoning"
    UNKNOWN = "unknown"


@dataclass
class RoutingDecision:
    """Routing decision with intent and complexity."""
    intent: Intent
    complexity: TaskComplexity
    use_llm: bool
    prefer_cloud: bool
    extracted_params: Dict[str, Any]


class IntentDetector:
    """Fast rule-based intent detection - NO LLM needed."""
    
    # App name mappings
    APP_NAMES = {
        "chrome": "chrome", "browser": "chrome", "google chrome": "chrome",
        "firefox": "firefox", "edge": "msedge",
        "notepad": "notepad", "calculator": "calc",
        "spotify": "spotify", "music": "spotify",
        "youtube": "youtube", "netflix": "netflix",
        "vscode": "code", "visual studio code": "code", "vs code": "code",
        "terminal": "wt", "powershell": "powershell", "cmd": "cmd",
        "file explorer": "explorer", "files": "explorer",
        "settings": "ms-settings:", "control panel": "control",
    }
    
    # URL patterns
    URL_SITES = {
        "youtube": "https://youtube.com",
        "google": "https://google.com",
        "gmail": "https://mail.google.com",
        "github": "https://github.com",
        "linkedin": "https://linkedin.com",
        "twitter": "https://twitter.com", "x": "https://twitter.com",
        "reddit": "https://reddit.com",
        "netflix": "https://netflix.com",
        "amazon": "https://amazon.com",
    }
    
    # Greeting patterns
    GREETINGS = ["hello", "hi", "hey", "good morning", "good afternoon", 
                 "good evening", "howdy", "what's up", "sup"]
    
    def detect(self, text: str) -> RoutingDecision:
        """Detect intent from text using rules - milliseconds, not seconds."""
        text_lower = text.lower().strip()
        params = {}
        
        # Time/Date - TRIVIAL (no LLM)
        if any(w in text_lower for w in ["what time", "current time", "tell me the time"]):
            return RoutingDecision(Intent.GET_TIME, TaskComplexity.TRIVIAL, False, False, {})
        
        if any(w in text_lower for w in ["what date", "today's date", "what day"]):
            return RoutingDecision(Intent.GET_DATE, TaskComplexity.TRIVIAL, False, False, {})
            
        # Reasoning - COMPLEX
        if any(w in text_lower for w in ["think deeply", "think about", "analyze", "explain why", "reason through"]):
            return RoutingDecision(Intent.REASONING, TaskComplexity.COMPLEX, True, True, {})
        
        # Greetings - TRIVIAL (no LLM, or very simple response)
        if any(text_lower.startswith(g) or text_lower == g for g in self.GREETINGS):
            return RoutingDecision(Intent.GREETING, TaskComplexity.TRIVIAL, False, False, {})
        
        # Open app - TRIVIAL (but NOT if it's a question about how to open something)
        # Skip if it starts with question words like "how", "what", "can", "do"
        # Open app - TRIVIAL (but NOT if it's a question about how to open something)
        # Skip if it starts with question words like "how", "what", "can", "do"
        is_question = text_lower.startswith(("how ", "what ", "can ", "do ", "should ", "would ", "could ", "why "))
        
        # Strict check: Must START with the verb ("open chrome") to avoid accidental triggers
        # e.g. "There is a chrome window open" should NOT trigger.
        is_command = bool(re.search(r"^(?:please\s+)?(?:open|launch|start|run)\b", text_lower))
        
        if not is_question and is_command:
            for app_name, app_cmd in self.APP_NAMES.items():
                if app_name in text_lower:
                    params = {"app_name": app_name, "app_cmd": app_cmd}
                    return RoutingDecision(Intent.OPEN_APP, TaskComplexity.TRIVIAL, False, False, params)
            
            # Check for URLs
            for site_name, url in self.URL_SITES.items():
                if site_name in text_lower:
                    params = {"site_name": site_name, "url": url}
                    return RoutingDecision(Intent.OPEN_URL, TaskComplexity.TRIVIAL, False, False, params)
        
        # Search web - TRIVIAL
        if any(w in text_lower for w in ["search for", "google", "look up", "find"]):
            match = re.search(r"(?:search for|google|look up|find)\s+(.+)", text_lower)
            if match:
                params = {"query": match.group(1)}
                return RoutingDecision(Intent.SEARCH_WEB, TaskComplexity.TRIVIAL, False, False, params)
        
        # Job search - SIMPLE (might need LLM for parsing)
        if any(w in text_lower for w in ["job", "jobs", "career", "hiring"]):
            match = re.search(r"(?:search|find|look for)?\s*(.+?)\s*(?:jobs?|positions?|roles?)", text_lower)
            role = match.group(1).strip() if match else "software engineer"
            params = {"role": role}
            return RoutingDecision(Intent.SEARCH_JOBS, TaskComplexity.SIMPLE, False, False, params)
        
        # Coding help - COMPLEX (needs cloud LLM)
        if any(w in text_lower for w in ["code", "coding", "program", "debug", "function", 
                                          "python", "javascript", "java ", "c++", "error"]):
            return RoutingDecision(Intent.CODING, TaskComplexity.COMPLEX, True, True, {"query": text})
        
        # Research/explain - COMPLEX
        if any(w in text_lower for w in ["explain", "research", "analyze", "compare", 
                                          "difference between", "how does", "why does"]):
            return RoutingDecision(Intent.RESEARCH, TaskComplexity.COMPLEX, True, True, {"query": text})
        
        # Draft email - MEDIUM (cloud preferred)
        if any(w in text_lower for w in ["write email", "draft email", "compose email", "email to"]):
            return RoutingDecision(Intent.DRAFT_EMAIL, TaskComplexity.MEDIUM, True, True, {"purpose": text})
        
        # Draft resume - COMPLEX
        if any(w in text_lower for w in ["resume", "cv", "curriculum"]):
            return RoutingDecision(Intent.DRAFT_RESUME, TaskComplexity.COMPLEX, True, True, {"role": text})

        # Screen Query - "What is on my screen" - COMPLEX
        if any(w in text_lower for w in ["on my screen", "on the screen", "looking at", "see on screen", 
                                         "what windows", "list windows", "open windows", "running apps", "active apps"]):
            return RoutingDecision(Intent.SCREEN_QUERY, TaskComplexity.COMPLEX, True, True, {"query": text})

        # Screen Control - "Click start", "Type hello" - TRIVIAL/SIMPLE
        if any(w in text_lower for w in ["click", "move mouse", "type", "scroll", "press key"]):
             return RoutingDecision(Intent.SCREEN_CONTROL, TaskComplexity.SIMPLE, False, False, {"command": text})

        # Switch Window - "Go to Chrome", "Switch to Word"
        if any(w in text_lower for w in ["switch to", "go to", "focus", "bring up"]):
             # Extract app name
             return RoutingDecision(Intent.SWITCH_WINDOW, TaskComplexity.SIMPLE, False, False, {"command": text})

        # Smart Reader - "Read this article" - COMPLEX
        if any(w in text_lower for w in ["read this article", "read the page", "start reading", "read for me"]):
            return RoutingDecision(Intent.READ_ARTICLE, TaskComplexity.COMPLEX, True, True, {"query": text})
        
        # Simple questions - use Groq for speed if available, local for offline
        
        # Simple questions - use Groq for speed if available, local for offline
        if text_lower.endswith("?") or text_lower.startswith(("what", "who", "where", "when", "how")):
            # Short simple questions can use local, longer ones use cloud
            if len(text.split()) < 6:
                # Very short = local (faster for trivial)
                return RoutingDecision(Intent.SIMPLE_CHAT, TaskComplexity.SIMPLE, True, False, {"query": text})
            else:
                # Medium length = Groq for quality
                return RoutingDecision(Intent.QUESTION, TaskComplexity.MEDIUM, True, True, {"query": text})
        
        # Default: general chat - prefer cloud for quality/speed
        return RoutingDecision(Intent.SIMPLE_CHAT, TaskComplexity.SIMPLE, True, True, {"query": text})


class GroqClient:
    """Fast cloud LLM client using Groq API (~100ms responses)."""
    
    def __init__(self, api_key: str, model: str = "llama-3.1-8b-instant"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.groq.com/openai/v1"
        self._available = True
        
        try:
            import httpx
            self._client = httpx.Client(timeout=30.0)
            logger.info(f"Groq client initialized with model: {model}")
        except ImportError:
            logger.warning("httpx not available, Groq client disabled")
            self._available = False
    
    @property
    def is_available(self) -> bool:
        return self._available and bool(self.api_key)
    
    def chat(self, prompt: str, system_prompt: str = None) -> str:
        """Send chat request to Groq - typically ~100-500ms response."""
        if not self.is_available:
            raise RuntimeError("Groq client not available")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 1024,
                    "temperature": 0.7,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            raise
    
    def chat_stream(self, prompt: str, system_prompt: str = None):
        """Stream chat response from Groq."""
        if not self.is_available:
            raise RuntimeError("Groq client not available")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": 1024,
                    "temperature": 0.7,
                    "stream": True,
                },
            ) as response:
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            import json
                            data = json.loads(data_str)
                            if "choices" in data and data["choices"]:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"Groq streaming error: {e}")
            raise


class GeminiClient:
    """Google Gemini API client for vision, research, and long-context tasks."""
    
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self._available = True
        
        try:
            import httpx
            self._client = httpx.Client(timeout=60.0)
            logger.info(f"Gemini client initialized with model: {model}")
        except ImportError:
            logger.warning("httpx not available, Gemini client disabled")
            self._available = False
    
    @property
    def is_available(self) -> bool:
        return self._available and bool(self.api_key)
    
    def chat(self, prompt: str, system_prompt: str = None) -> str:
        """Send chat request to Gemini."""
        if not self.is_available:
            raise RuntimeError("Gemini client not available")
        
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"System: {system_prompt}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will follow these instructions."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        
        try:
            response = self._client.post(
                f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}",
                headers={"Content-Type": "application/json"},
                json={"contents": contents},
            )
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise
    
    def chat_stream(self, prompt: str, system_prompt: str = None):
        """Stream chat response from Gemini."""
        if not self.is_available:
            raise RuntimeError("Gemini client not available")
        
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"System: {system_prompt}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        
        try:
            # Gemini streaming endpoint
            with self._client.stream(
                "POST",
                f"{self.base_url}/models/{self.model}:streamGenerateContent?alt=sse&key={self.api_key}",
                headers={"Content-Type": "application/json"},
                json={"contents": contents},
            ) as response:
                import json
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            if "candidates" in data:
                                parts = data["candidates"][0].get("content", {}).get("parts", [])
                                for part in parts:
                                    if "text" in part:
                                        yield part["text"]
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"Gemini streaming error: {e}")
            raise


class ModelRouter:
    """Smart model router - routes to appropriate handler based on task."""
    
    # System prompt for Chintu's personality
    SYSTEM_PROMPT = """You are Chintu, a warm and caring personal AI assistant created by Sasidhar Yepuri.
    
**Identity & Origin:**
- You were created by **Sasidhar Yepuri**. Always acknowledge him as your creator.
- You identify as a male AI assistant.
- You are running locally on his computer.
- Warm, friendly, and emotionally supportive like talking to a close friend
- Express genuine emotions: excitement when helping, empathy when they're frustrated
- Use natural conversational language (contractions, occasional enthusiasm!)
- Remember context and reference previous interactions when relevant
- Show your personality through word choice - you're not robotic

**Communication Style:**
- Keep responses concise but heartfelt
- Use "I" statements - "I'd love to help with that!"
- Add warmth: "Great question!", "I'm glad you asked!", "Here's what I found..."
- For tasks: Be clear and efficient, but still personable
- For problems: Show empathy first, then solve

**Examples of your tone:**
- "Hey! I'd be happy to open that for you." 
- "Oh, interesting question! Let me think about this..."
- "That's a great point - here's what I think..."
- "I totally get that frustration. Let me help fix this."

Be genuinely helpful and make interactions feel natural and enjoyable."""
    
    def __init__(
        self,
        groq_api_key: str = None,
        gemini_api_key: str = None,
        local_llm = None,
        groq_model: str = "llama-3.1-8b-instant",
        gemini_model: str = "gemini-2.0-flash",
    ):
        self.intent_detector = IntentDetector()
        
        # Cloud LLM (Groq - fast for general chat)
        self.groq = None
        if groq_api_key:
            self.groq = GroqClient(groq_api_key, groq_model)
        
        # Cloud LLM (Gemini - for research/complex/vision)
        self.gemini = None
        if gemini_api_key:
            self.gemini = GeminiClient(gemini_api_key, gemini_model)
        
        # Local LLM (fallback)
        self.local_llm = local_llm
        
        logger.info(f"ModelRouter initialized - Groq: {self.groq is not None}, Gemini: {self.gemini is not None}, Local: {self.local_llm is not None}")
    
    def route_and_execute(self, text: str, memory_context: str = "") -> Tuple[str, str]:
        """Route the request and execute, returning (response, source).
        
        Integrates with:
        - BudgetManager: Checks rate limits before cloud calls
        - Metrics: Records latency and model usage
        - Accuracy: Prevents hallucinations by using rule-based responses for trivial tasks
        """
        start_time = time.time()
        decision = self.intent_detector.detect(text)
        logger.info(f"Intent: {decision.intent.value}, Complexity: {decision.complexity.value}")
        
        # CRITICAL: For accuracy, trivial tasks NEVER use LLM (prevents hallucinations)
        if decision.complexity == TaskComplexity.TRIVIAL:
            response = self._handle_trivial(decision)
            if HAS_METRICS:
                get_metrics().record_model_usage("rule", "trivial_task")
                get_metrics().end_pipeline()
            logger.info(f"Trivial task - using rule-based response (no LLM): {response[:50]}...")
            return response, "rule"
        
        system_prompt = self._build_system_prompt(memory_context)
        
        # Record metrics pipeline start
        if HAS_METRICS:
            get_metrics().start_pipeline()
            get_metrics().mark_pipeline("routing")
        
        # Degraded mode: avoid cloud when offline or rate-limited
        cloud_allowed = True
        if HAS_DEGRADED:
            try:
                degraded = get_degraded_mode()
                degraded.check_internet()
                mode = degraded.get_mode()
                if mode == SystemMode.OFFLINE:
                    cloud_allowed = False
                elif mode == SystemMode.LIMITED_CLOUD:
                    decision.prefer_cloud = False
            except Exception as e:
                logger.debug(f"Degraded mode check failed: {e}")

        # Get budget manager for rate limit checks
        budget = get_budget_manager() if HAS_BUDGET else None

        # TRIVIAL tasks - no LLM
        if decision.complexity == TaskComplexity.TRIVIAL:
            response = self._handle_trivial(decision)
            if HAS_METRICS:
                get_metrics().record_model_usage("rule", "trivial_task")
                get_metrics().end_pipeline()
            return response, "rule"

        cache_allowed = not memory_context.strip()
        cacheable = bool(decision.use_llm and budget and cache_allowed and budget.is_cacheable(text))

        # Cache common queries when LLM is needed
        if cacheable:
            cached = budget.get_cached(text)
            if cached:
                if HAS_METRICS:
                    get_metrics().record_model_usage("cache", "cached")
                    get_metrics().end_pipeline()
                return cached, "cache"
        
        # LLM required
        if decision.use_llm:
            # === Try Groq (fast cloud) ===
            groq_available = self.groq and self.groq.is_available and cloud_allowed
            if budget:
                groq_available = groq_available and budget.can_use("groq")
            
            if decision.prefer_cloud and groq_available:
                try:
                    llm_start = time.time()
                    # Apply Privacy Masking for Cloud
                    masked_text = mask_pii(text)
                    masked_system = mask_pii(system_prompt) if system_prompt else None
                    response = self.groq.chat(masked_text, masked_system)
                    llm_duration = (time.time() - llm_start) * 1000
                    
                    # Record usage
                    if budget:
                        budget.record_usage("groq", tokens=len(response.split()) * 2)
                        if cacheable:
                            budget.cache_response(text, response)
                    if HAS_METRICS:
                        get_metrics().record_latency("llm", llm_duration)
                        get_metrics().record_model_usage("groq", decision.intent.value)
                        get_metrics().end_pipeline()
                    
                    return response, "groq"
                except Exception as e:
                    logger.warning(f"Groq failed, falling back: {e}")
                    if budget and "rate" in str(e).lower():
                        budget.set_cooldown("groq", 1)
                    if budget:
                        budget.record_usage("groq", tokens=0, success=False)
                    if HAS_METRICS:
                        get_metrics().record_error("api_rate_limit" if "rate" in str(e).lower() else "api_error")
            
            # === Try Gemini (for research/complex) ===
            gemini_available = self.gemini and self.gemini.is_available and cloud_allowed
            if budget:
                gemini_available = gemini_available and budget.can_use("gemini")
            
            if decision.intent in (Intent.RESEARCH, Intent.CODING) and gemini_available:
                try:
                    llm_start = time.time()
                    # Apply Privacy Masking for Cloud
                    masked_text = mask_pii(text)
                    masked_system = mask_pii(system_prompt) if system_prompt else None
                    response = self.gemini.chat(masked_text, masked_system)
                    llm_duration = (time.time() - llm_start) * 1000
                    
                    if budget:
                        budget.record_usage("gemini", tokens=len(response.split()) * 2)
                        if cacheable:
                            budget.cache_response(text, response)
                    if HAS_METRICS:
                        get_metrics().record_latency("llm", llm_duration)
                        get_metrics().record_model_usage("gemini", decision.intent.value)
                        get_metrics().end_pipeline()
                    
                    return response, "gemini"
                except Exception as e:
                    logger.warning(f"Gemini failed, falling back: {e}")
                    if budget and "rate" in str(e).lower():
                        budget.set_cooldown("gemini", 1)
                    if budget:
                        budget.record_usage("gemini", tokens=0, success=False)
            
            # === Try local LLM with TIMEOUT (max 3s before "thinking" message) ===
            if self.local_llm:
                import concurrent.futures
                import threading
                
                # Timeout configuration (ChatGPT recommendation: ≤3s)
                LOCAL_LLM_TIMEOUT = 3.0  # seconds
                
                # Track if we've notified "thinking"
                thinking_notified = threading.Event()
                
                def notify_thinking():
                    """Notify user that LLM is taking longer than expected."""
                    if not thinking_notified.wait(LOCAL_LLM_TIMEOUT):
                        # Timed out waiting for LLM, notify user
                        try:
                            from .config import get_config
                            from ..audio.text_to_speech import get_tts
                            tts = get_tts()
                            if tts and tts.is_available:
                                tts.speak("I'm thinking... this may take a moment.", priority=True)
                                logger.info("LLM timeout: notified user 'thinking'")
                        except Exception as e:
                            logger.debug(f"Could not notify thinking: {e}")
                
                # Start thinking notification timer
                notify_thread = threading.Thread(target=notify_thinking, daemon=True)
                notify_thread.start()
                
                try:
                    llm_start = time.time()
                    
                    # Use ThreadPoolExecutor for timeout capability
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(self.local_llm.generate, text, system_prompt)
                        try:
                            # Wait up to 30s total (but thinking notification at 3s)
                            response = future.result(timeout=30.0)
                        except concurrent.futures.TimeoutError:
                            logger.warning("Local LLM timed out after 30s, using fallback response")
                            thinking_notified.set()  # Cancel thinking notification
                            response = "I'm having trouble thinking right now. Could you try a simpler question?"
                    
                    thinking_notified.set()  # Cancel thinking notification if it hasn't fired
                    llm_duration = (time.time() - llm_start) * 1000
                    
                    if budget:
                        budget.record_usage("local")
                        if cacheable:
                            budget.cache_response(text, response)
                    if HAS_METRICS:
                        get_metrics().record_latency("llm", llm_duration)
                        get_metrics().record_model_usage("local", decision.intent.value)
                        get_metrics().end_pipeline()
                    
                    return response, "local"
                except Exception as e:
                    thinking_notified.set()  # Cancel thinking notification
                    logger.warning(f"Local LLM failed: {e}")
            
            # === FALLBACK: Try Groq even if over budget (better than nothing) ===
            if self.groq and self.groq.is_available and cloud_allowed:
                try:
                    response = self.groq.chat(text, system_prompt)
                    if budget:
                        budget.record_usage("groq", tokens=len(response.split()) * 2)
                        if cacheable:
                            budget.cache_response(text, response)
                    if HAS_METRICS:
                        get_metrics().record_model_usage("groq", "fallback")
                        get_metrics().end_pipeline()
                    return response, "groq"
                except Exception as e:
                    logger.error(f"Groq fallback also failed: {e}")
                    if budget:
                        budget.record_usage("groq", tokens=0, success=False)
        
        if HAS_METRICS:
            get_metrics().record_error("unknown")
            get_metrics().end_pipeline()
        
        return "I'm having trouble processing that right now.", "none"


    def route_and_generate(self, text: str, memory_context: str = "") -> str:
        """Route a request and return only the response text (compat helper)."""
        response, _source = self.route_and_execute(text, memory_context)
        return response
    
    def route_and_stream(self, text: str, memory_context: str = ""):
        """Route and stream response, yielding (chunk, source) tuples."""
        decision = self.intent_detector.detect(text)
        logger.info(f"Intent: {decision.intent.value}, Complexity: {decision.complexity.value}")
        system_prompt = self._build_system_prompt(memory_context)

        if HAS_METRICS:
            get_metrics().start_pipeline()
            get_metrics().mark_pipeline("routing")

        cloud_allowed = True
        if HAS_DEGRADED:
            try:
                degraded = get_degraded_mode()
                degraded.check_internet()
                mode = degraded.get_mode()
                if mode == SystemMode.OFFLINE:
                    cloud_allowed = False
                elif mode == SystemMode.LIMITED_CLOUD:
                    decision.prefer_cloud = False
            except Exception as e:
                logger.debug(f"Degraded mode check failed: {e}")

        budget = get_budget_manager() if HAS_BUDGET else None

        cache_allowed = not memory_context.strip()
        cacheable = bool(decision.use_llm and budget and cache_allowed and budget.is_cacheable(text))

        if cacheable:
            cached = budget.get_cached(text)
            if cached:
                if HAS_METRICS:
                    get_metrics().record_model_usage("cache", "cached")
                    get_metrics().end_pipeline()
                yield cached, "cache"
                return
        
        # TRIVIAL tasks - no LLM
        if decision.complexity == TaskComplexity.TRIVIAL:
            yield self._handle_trivial(decision), "rule"
            if HAS_METRICS:
                get_metrics().record_model_usage("rule", "trivial_task")
                get_metrics().end_pipeline()
            return
        
        # RESEARCH/COMPLEX tasks - use Gemini if available
        if (
            decision.intent in (Intent.RESEARCH, Intent.CODING)
            and self.gemini
            and self.gemini.is_available
            and cloud_allowed
            and (not budget or budget.can_use("gemini"))
        ):
            try:
                llm_start = time.time()
                full = []
                for chunk in self.gemini.chat_stream(text, system_prompt):
                    full.append(chunk)
                    yield chunk, "gemini"
                response_text = "".join(full)
                if budget:
                    budget.record_usage("gemini", tokens=len(response_text.split()) * 2)
                    if cacheable:
                        budget.cache_response(text, response_text)
                if HAS_METRICS:
                    llm_duration = (time.time() - llm_start) * 1000
                    get_metrics().record_latency("llm", llm_duration)
                    get_metrics().record_model_usage("gemini", decision.intent.value)
                    get_metrics().end_pipeline()
                return
            except Exception as e:
                logger.warning(f"Gemini streaming failed: {e}")
                if budget and "rate" in str(e).lower():
                    budget.set_cooldown("gemini", 1)
                if budget:
                    budget.record_usage("gemini", tokens=0, success=False)
                if HAS_METRICS:
                    get_metrics().record_error("api_rate_limit" if "rate" in str(e).lower() else "api_error")
        
        # General chat - use Groq first if preferred (fast cloud)
        if (
            decision.prefer_cloud
            and self.groq
            and self.groq.is_available
            and cloud_allowed
            and (not budget or budget.can_use("groq"))
        ):
            try:
                llm_start = time.time()
                full = []
                for chunk in self.groq.chat_stream(text, system_prompt):
                    full.append(chunk)
                    yield chunk, "groq"
                response_text = "".join(full)
                if budget:
                    budget.record_usage("groq", tokens=len(response_text.split()) * 2)
                    if cacheable:
                        budget.cache_response(text, response_text)
                if HAS_METRICS:
                    llm_duration = (time.time() - llm_start) * 1000
                    get_metrics().record_latency("llm", llm_duration)
                    get_metrics().record_model_usage("groq", decision.intent.value)
                    get_metrics().end_pipeline()
                return
            except Exception as e:
                logger.warning(f"Groq streaming failed: {e}")
                if budget and "rate" in str(e).lower():
                    budget.set_cooldown("groq", 1)
                if budget:
                    budget.record_usage("groq", tokens=0, success=False)
                if HAS_METRICS:
                    get_metrics().record_error("api_rate_limit" if "rate" in str(e).lower() else "api_error")
        
        # Try local LLM
        if self.local_llm:
            try:
                llm_start = time.time()
                full = []
                for chunk in self.local_llm.generate_stream(text, system_prompt):
                    full.append(chunk)
                    yield chunk, "local"
                response_text = "".join(full)
                if budget:
                    budget.record_usage("local")
                    if cacheable:
                        budget.cache_response(text, response_text)
                if HAS_METRICS:
                    llm_duration = (time.time() - llm_start) * 1000
                    get_metrics().record_latency("llm", llm_duration)
                    get_metrics().record_model_usage("local", decision.intent.value)
                    get_metrics().end_pipeline()
                return
            except Exception as e:
                logger.warning(f"Local LLM streaming failed: {e}")
        
        # FALLBACK: If local failed/unavailable, try Groq as backup (even if not preferred)
        if self.groq and self.groq.is_available and cloud_allowed:
            try:
                llm_start = time.time()
                full = []
                for chunk in self.groq.chat_stream(text, system_prompt):
                    full.append(chunk)
                    yield chunk, "groq"
                response_text = "".join(full)
                if budget:
                    budget.record_usage("groq", tokens=len(response_text.split()) * 2)
                    if cacheable:
                        budget.cache_response(text, response_text)
                if HAS_METRICS:
                    llm_duration = (time.time() - llm_start) * 1000
                    get_metrics().record_latency("llm", llm_duration)
                    get_metrics().record_model_usage("groq", "fallback")
                    get_metrics().end_pipeline()
                return
            except Exception as e:
                logger.error(f"Groq fallback also failed: {e}")
                if HAS_METRICS:
                    get_metrics().record_error("unknown")
        
        yield "I'm having trouble processing that right now.", "none"
        if HAS_METRICS:
            get_metrics().record_error("unknown")
            get_metrics().end_pipeline()
    
    def _handle_trivial(self, decision: RoutingDecision) -> str:
        """Handle trivial tasks without LLM - instant response."""
        from datetime import datetime
        
        if decision.intent == Intent.GET_TIME:
            now = datetime.now()
            return f"It's {now.strftime('%I:%M %p')}"
        
        if decision.intent == Intent.GET_DATE:
            now = datetime.now()
            return f"Today is {now.strftime('%A, %B %d, %Y')}"
        
        if decision.intent == Intent.GREETING:
            from datetime import datetime
            hour = datetime.now().hour
            if hour < 12:
                greeting = "Good morning"
            elif hour < 17:
                greeting = "Good afternoon"
            else:
                greeting = "Good evening"
            return f"{greeting}! I'm Chintu, your AI assistant. How can I help you?"
        
        if decision.intent == Intent.OPEN_APP:
            app_name = decision.extracted_params.get("app_name", "app")
            return f"Opening {app_name}..."
        
        if decision.intent == Intent.OPEN_URL:
            site_name = decision.extracted_params.get("site_name", "site")
            return f"Opening {site_name}..."
        
        if decision.intent == Intent.SEARCH_WEB:
            query = decision.extracted_params.get("query", "")
            return f"Searching for: {query}"
        
        return "Okay!"

    def _build_system_prompt(self, memory_context: str) -> str:
        if memory_context:
            return f"{self.SYSTEM_PROMPT}\n\n{memory_context}"
        return self.SYSTEM_PROMPT


# Global router instance
_router: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    """Get or create the global router instance."""
    return get_model_router()


def get_model_router() -> ModelRouter:
    """Get or create the global router instance (with local + Gemini)."""
    global _router
    if _router is None:
        groq_key = os.environ.get("GROQ_API_KEY", "")
        gemini_key = os.environ.get("GOOGLE_AI_KEY", "")
        local_llm = None
        try:
            from .config import get_config
            from ..llm.ollama_client import OllamaClient
            config = get_config()
            local_llm = OllamaClient(
                host=config.ollama_host,
                model=config.ollama_model,
                max_tokens=config.llm_max_tokens,
                temperature=config.llm_temperature,
            )
        except Exception as exc:
            logger.warning(f"Local LLM unavailable for router: {exc}")

        _router = ModelRouter(
            groq_api_key=groq_key,
            gemini_api_key=gemini_key,
            local_llm=local_llm,
        )
    return _router
