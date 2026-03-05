"""
Model Router - Intelligent routing between LLM models.

Routes requests to appropriate model based on task type:
- Qwen2.5-Coder-14B (Q4_K_M): Code generation, tool calling, execution tasks
- Mistral Small 3 (12B): Strategy, conversation, planning, business thinking

Features:
- Task classification
- Automatic model selection
- Fallback handling
- Performance tracking
"""

import json
import logging
import inspect
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class TaskCategory(Enum):
    """Categories for routing decisions."""
    CODE = "code"  # Code generation, debugging, technical implementation
    STRATEGY = "strategy"  # Business thinking, planning, high-level decisions
    CONVERSATION = "conversation"  # General chat, questions, explanations
    ANALYSIS = "analysis"  # Data analysis, research, insights
    EXECUTION = "execution"  # Tool calling, task execution
    CREATIVE = "creative"  # Content creation, writing, ideas


class ModelTier(Enum):
    """Model tiers for different capabilities."""
    DOER = "doer"  # Fast, execution-focused (Qwen2.5-Coder)
    THINKER = "thinker"  # Strategy, conversation (Mistral Small 3)
    FAST = "fast"  # Quick responses for simple tasks
    FALLBACK = "fallback"  # When primary fails


@dataclass
class ModelConfig:
    """Configuration for a model."""
    name: str
    tier: ModelTier
    host: str
    model_id: str
    max_tokens: int = 4096
    temperature: float = 0.7
    categories: List[TaskCategory] = field(default_factory=list)
    priority: int = 1  # Higher = preferred
    enabled: bool = True
    
    # Performance tracking
    avg_latency_ms: float = 0
    success_rate: float = 1.0
    total_calls: int = 0


@dataclass
class RoutingDecision:
    """Result of a routing decision."""
    model_config: ModelConfig
    category: TaskCategory
    confidence: float
    reason: str


class ModelRouter:
    """
    Intelligent model router for multi-model setup.
    
    Optimized for 12GB VRAM on RTX 3060:
    - Primary doer: Qwen2.5-Coder-14B (Q4_K_M) - 8GB VRAM
    - Strategy/conversation: Mistral Small 3 (12B Q5_K_M) - swap as needed
    """
    
    def __init__(self):
        self.config = get_config()
        self.router_dir = self.config.data_dir / "model_router"
        self.router_dir.mkdir(parents=True, exist_ok=True)
        
        self.models: Dict[str, ModelConfig] = {}
        self.stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "calls": 0,
            "successes": 0,
            "total_latency_ms": 0,
            "errors": []
        })
        
        self._setup_default_models()
        self._load_stats()
    
    def _setup_default_models(self):
        """Setup default model configurations."""
        ollama_host = getattr(self.config, 'ollama_host', 'http://localhost:11434')
        
        # Primary doer - Qwen2.5-Coder-14B
        self.models["qwen-coder"] = ModelConfig(
            name="Qwen2.5-Coder-14B",
            tier=ModelTier.DOER,
            host=ollama_host,
            model_id="qwen2.5-coder:14b-instruct-q4_K_M",
            max_tokens=8192,
            temperature=0.3,
            categories=[
                TaskCategory.CODE,
                TaskCategory.EXECUTION,
                TaskCategory.ANALYSIS
            ],
            priority=10
        )
        
        # Strategy/conversation - Mistral Small 3
        self.models["mistral-small"] = ModelConfig(
            name="Mistral Small 3",
            tier=ModelTier.THINKER,
            host=ollama_host,
            model_id="mistral-small:latest",
            max_tokens=8192,
            temperature=0.7,
            categories=[
                TaskCategory.STRATEGY,
                TaskCategory.CONVERSATION,
                TaskCategory.CREATIVE
            ],
            priority=8
        )
        
        # Fast fallback - small model for quick responses
        self.models["qwen-fast"] = ModelConfig(
            name="Qwen2.5-3B",
            tier=ModelTier.FAST,
            host=ollama_host,
            model_id="qwen2.5:3b",
            max_tokens=4096,
            temperature=0.5,
            categories=list(TaskCategory),  # Can handle all
            priority=3
        )
        
        # Fallback for when others fail
        self.models["fallback"] = ModelConfig(
            name="Fallback",
            tier=ModelTier.FALLBACK,
            host=ollama_host,
            model_id="qwen2.5:3b",
            max_tokens=2048,
            temperature=0.5,
            categories=list(TaskCategory),
            priority=1
        )
    
    def classify_task(self, prompt: str) -> Tuple[TaskCategory, float]:
        """
        Classify the task type from the prompt.
        Returns (category, confidence).
        """
        prompt_lower = prompt.lower()
        
        # Code indicators
        code_keywords = [
            "code", "function", "class", "implement", "debug", "fix bug",
            "write", "python", "javascript", "typescript", "api", "endpoint",
            "database", "sql", "test", "unit test", "refactor", "optimize"
        ]
        
        # Strategy indicators
        strategy_keywords = [
            "plan", "strategy", "business", "market", "growth", "revenue",
            "product", "roadmap", "prioritize", "decide", "should i", "recommend",
            "budget", "invest", "startup", "competition", "positioning"
        ]
        
        # Conversation indicators
        conversation_keywords = [
            "explain", "what is", "how does", "why", "tell me", "describe",
            "help me understand", "clarify", "mean", "definition"
        ]
        
        # Execution indicators
        execution_keywords = [
            "run", "execute", "deploy", "install", "setup", "configure",
            "create file", "delete", "move", "copy", "send", "post"
        ]
        
        # Creative indicators
        creative_keywords = [
            "write content", "blog", "article", "story", "marketing",
            "social media", "caption", "headline", "slogan", "creative"
        ]
        
        # Analysis indicators
        analysis_keywords = [
            "analyze", "research", "data", "report", "metrics", "trends",
            "compare", "evaluate", "assess", "review"
        ]
        
        scores = {
            TaskCategory.CODE: sum(1 for kw in code_keywords if kw in prompt_lower),
            TaskCategory.STRATEGY: sum(1 for kw in strategy_keywords if kw in prompt_lower),
            TaskCategory.CONVERSATION: sum(1 for kw in conversation_keywords if kw in prompt_lower),
            TaskCategory.EXECUTION: sum(1 for kw in execution_keywords if kw in prompt_lower),
            TaskCategory.CREATIVE: sum(1 for kw in creative_keywords if kw in prompt_lower),
            TaskCategory.ANALYSIS: sum(1 for kw in analysis_keywords if kw in prompt_lower),
        }
        
        # Get best match
        max_score = max(scores.values())
        if max_score == 0:
            return TaskCategory.CONVERSATION, 0.5
        
        best_category = max(scores, key=scores.get)
        confidence = min(1.0, max_score / 3)  # Normalize
        
        return best_category, confidence
    
    def route(self, prompt: str, prefer_tier: ModelTier = None) -> RoutingDecision:
        """
        Route a prompt to the appropriate model.
        
        Args:
            prompt: The prompt to route
            prefer_tier: Optional tier preference
            
        Returns:
            RoutingDecision with selected model and reasoning
        """
        category, confidence = self.classify_task(prompt)
        
        # Find best model for this category
        candidates = []
        
        for model in self.models.values():
            if not model.enabled:
                continue
            
            # Check tier preference
            if prefer_tier and model.tier != prefer_tier:
                continue
            
            # Check if model handles this category
            if category in model.categories:
                candidates.append(model)
        
        if not candidates:
            # Fallback to any enabled model
            candidates = [m for m in self.models.values() if m.enabled]
        
        if not candidates:
            raise RuntimeError("No models available")
        
        # Sort by priority and success rate
        candidates.sort(key=lambda m: (m.priority * m.success_rate), reverse=True)
        
        selected = candidates[0]
        
        return RoutingDecision(
            model_config=selected,
            category=category,
            confidence=confidence,
            reason=f"Selected {selected.name} for {category.value} task (priority={selected.priority})"
        )
    
    def generate(
        self,
        prompt: str,
        prefer_tier: ModelTier = None,
        max_tokens: int = None,
        temperature: float = None
    ) -> Dict[str, Any]:
        """
        Generate a response using the routed model.
        
        Args:
            prompt: The prompt
            prefer_tier: Optional tier preference
            max_tokens: Override max tokens
            temperature: Override temperature
            
        Returns:
            Dict with response and metadata
        """
        decision = self.route(prompt, prefer_tier)
        model_config = decision.model_config
        
        start_time = time.time()
        
        try:
            # Try the selected model
            response = self._call_model(
                model_config,
                prompt,
                max_tokens or model_config.max_tokens,
                temperature if temperature is not None else model_config.temperature
            )
            
            latency_ms = (time.time() - start_time) * 1000
            self._record_success(model_config.name, latency_ms)
            
            return {
                "response": response,
                "model": model_config.name,
                "model_id": model_config.model_id,
                "category": decision.category.value,
                "confidence": decision.confidence,
                "latency_ms": latency_ms
            }
            
        except Exception as e:
            self._record_error(model_config.name, str(e))
            
            # Try fallback
            if model_config.tier != ModelTier.FALLBACK:
                logger.warning(f"Model {model_config.name} failed, trying fallback")
                fallback = self.models.get("fallback")
                if fallback and fallback.enabled:
                    try:
                        response = self._call_model(
                            fallback,
                            prompt,
                            max_tokens or fallback.max_tokens,
                            temperature if temperature is not None else fallback.temperature
                        )
                        
                        latency_ms = (time.time() - start_time) * 1000
                        self._record_success(fallback.name, latency_ms)
                        
                        return {
                            "response": response,
                            "model": fallback.name,
                            "model_id": fallback.model_id,
                            "category": decision.category.value,
                            "confidence": decision.confidence,
                            "latency_ms": latency_ms,
                            "fallback": True
                        }
                    except Exception as e2:
                        self._record_error(fallback.name, str(e2))
            
            raise RuntimeError(f"All models failed: {e}")
    
    def _call_model(
        self,
        config: ModelConfig,
        prompt: str,
        max_tokens: int,
        temperature: float
    ) -> str:
        """Call a specific model."""
        try:
            from chintu_backend.brain.llm.ollama_client import OllamaClient
            
            client = OllamaClient(
                host=config.host,
                model=config.model_id
            )

            # Keep runtime config in sync for clients that read instance attributes.
            try:
                client.max_tokens = int(max_tokens)
            except Exception:
                pass
            try:
                client.temperature = float(temperature)
            except Exception:
                pass

            # Prefer generate(), but only pass supported kwargs.
            if hasattr(client, "generate"):
                generate_fn = getattr(client, "generate")
                kwargs: Dict[str, Any] = {}
                try:
                    params = inspect.signature(generate_fn).parameters
                    if "max_tokens" in params:
                        kwargs["max_tokens"] = max_tokens
                    if "temperature" in params:
                        kwargs["temperature"] = temperature
                except Exception:
                    kwargs = {}
                response = generate_fn(prompt, **kwargs)
            else:
                response = client.chat(prompt)

            # Treat explicit model error strings as failures so fallback logic triggers.
            if isinstance(response, str) and response.strip().startswith("[Error"):
                raise RuntimeError(response.strip("[]"))
            return str(response)
                
        except ImportError:
            # Fallback to requests
            import requests
            
            response = requests.post(
                f"{config.host}/api/generate",
                json={
                    "model": config.model_id,
                    "prompt": prompt,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature
                    },
                    "stream": False
                },
                timeout=120
            )
            response.raise_for_status()
            payload = response.json()
            text = payload.get("response", "") if isinstance(payload, dict) else ""
            if isinstance(text, str) and text.strip().startswith("[Error"):
                raise RuntimeError(text.strip("[]"))
            return str(text)
    
    def _record_success(self, model_name: str, latency_ms: float):
        """Record a successful call."""
        stats = self.stats[model_name]
        stats["calls"] += 1
        stats["successes"] += 1
        stats["total_latency_ms"] += latency_ms
        
        # Update model config
        if model_name in self.models:
            model = self.models[model_name]
            model.total_calls += 1
            model.avg_latency_ms = stats["total_latency_ms"] / stats["calls"]
            model.success_rate = stats["successes"] / stats["calls"]
        
        self._save_stats()
    
    def _record_error(self, model_name: str, error: str):
        """Record a failed call."""
        stats = self.stats[model_name]
        stats["calls"] += 1
        stats["errors"].append({
            "error": error[:200],
            "timestamp": datetime.now().isoformat()
        })
        
        # Keep only last 10 errors
        stats["errors"] = stats["errors"][-10:]
        
        # Update model config
        if model_name in self.models:
            model = self.models[model_name]
            model.total_calls += 1
            model.success_rate = stats["successes"] / stats["calls"] if stats["calls"] > 0 else 0
        
        self._save_stats()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get routing statistics."""
        return {
            "models": {
                name: {
                    "name": config.name,
                    "tier": config.tier.value,
                    "enabled": config.enabled,
                    "total_calls": config.total_calls,
                    "success_rate": config.success_rate,
                    "avg_latency_ms": config.avg_latency_ms
                }
                for name, config in self.models.items()
            },
            "routing_stats": dict(self.stats)
        }
    
    def enable_model(self, model_key: str, enabled: bool = True):
        """Enable or disable a model."""
        if model_key in self.models:
            self.models[model_key].enabled = enabled
            logger.info(f"Model {model_key} {'enabled' if enabled else 'disabled'}")
    
    def set_model(self, key: str, model_id: str):
        """Update model ID (for switching between quantizations)."""
        if key in self.models:
            self.models[key].model_id = model_id
            logger.info(f"Model {key} updated to {model_id}")
    
    def _load_stats(self):
        """Load stats from disk."""
        stats_file = self.router_dir / "stats.json"
        if stats_file.exists():
            try:
                data = json.loads(stats_file.read_text())
                for name, model_stats in data.items():
                    self.stats[name] = model_stats
                    if name in self.models:
                        self.models[name].total_calls = model_stats.get("calls", 0)
                        if model_stats.get("calls", 0) > 0:
                            self.models[name].success_rate = model_stats.get("successes", 0) / model_stats["calls"]
                            self.models[name].avg_latency_ms = model_stats.get("total_latency_ms", 0) / model_stats["calls"]
            except Exception as e:
                logger.warning(f"Could not load router stats: {e}")
    
    def _save_stats(self):
        """Save stats to disk."""
        stats_file = self.router_dir / "stats.json"
        try:
            stats_file.write_text(json.dumps(dict(self.stats), indent=2))
        except Exception as e:
            logger.warning(f"Could not save router stats: {e}")


# Convenience functions for direct access
_router: Optional[ModelRouter] = None


def get_model_router() -> ModelRouter:
    """Get or create the model router singleton."""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def generate(prompt: str, prefer_tier: ModelTier = None, **kwargs) -> str:
    """Quick access to routed generation."""
    router = get_model_router()
    result = router.generate(prompt, prefer_tier, **kwargs)
    return result["response"]


def generate_code(prompt: str, **kwargs) -> str:
    """Generate code using the doer model."""
    router = get_model_router()
    result = router.generate(prompt, prefer_tier=ModelTier.DOER, **kwargs)
    return result["response"]


def generate_strategy(prompt: str, **kwargs) -> str:
    """Generate strategy using the thinker model."""
    router = get_model_router()
    result = router.generate(prompt, prefer_tier=ModelTier.THINKER, **kwargs)
    return result["response"]
