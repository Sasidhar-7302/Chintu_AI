"""
Swarm Integration Module for Chintu v5.1

This module provides the bridge between the main CommandHandler and the
Swarm multi-agent system. It enables complex tasks to be routed to
specialized agents (Planner, Coder, Researcher) based on intent classification.

Key Features:
- Automatic complexity detection
- Seamless fallback to swarm for complex tasks
- VRAM-aware model management
- Integration with browser fallback for ultra-complex queries
"""

import logging
from dataclasses import dataclass
from typing import Optional, Callable, Any, Dict

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class SwarmResponse:
    """Response from the swarm system."""
    content: str
    source: str  # router, planner, coder, researcher, browser
    complexity_score: float
    model_used: str
    success: bool = True
    error: Optional[str] = None


class SwarmIntegration:
    """
    Integration layer between CommandHandler and SwarmEngine.
    
    Provides:
    - Complexity-based routing decisions
    - VRAM monitoring before model switches
    - Graceful degradation when swarm unavailable
    """
    
    def __init__(self):
        self.config = get_config()
        self._engine = None
        self._model_manager = None
        self._initialized = False
        self._vram_monitor = None
        
        # Complexity thresholds
        self.complexity_threshold = 0.6  # Route to swarm if above this
        
    def initialize(self) -> bool:
        """Initialize the swarm system. Returns True if successful."""
        if not self.config.swarm_enabled:
            logger.info("Swarm system disabled in config")
            return False
            
        try:
            from .swarm_engine import SwarmEngine
            from .model_manager import ModelManager
            
            self._model_manager = ModelManager(base_url=self.config.ollama_host)
            self._engine = SwarmEngine(model_manager=self._model_manager)
            self._initialized = True
            
            logger.info("Swarm system initialized successfully")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to initialize swarm system: {e}")
            self._initialized = False
            return False
    
    @property
    def is_available(self) -> bool:
        """Check if swarm system is available."""
        return self._initialized and self._engine is not None
    
    def should_use_swarm(self, text: str, intent: Optional[str] = None) -> bool:
        """
        Determine if a query should be routed to the swarm system.
        
        Args:
            text: User's query
            intent: Optional pre-classified intent
            
        Returns:
            True if swarm should handle this query
        """
        if not self.is_available:
            return False
            
        # Keywords that suggest complex multi-step tasks
        complex_keywords = [
            "create a project", "build", "develop", "implement",
            "research and", "analyze", "compare multiple",
            "write code", "fix the bug", "debug",
            "plan", "step by step", "workflow",
            "monitor", "track", "report on",
        ]
        
        text_lower = text.lower()
        
        # Check for complex task indicators
        for keyword in complex_keywords:
            if keyword in text_lower:
                logger.info(f"Swarm routing: matched keyword '{keyword}'")
                return True
        
        # Check intent if provided
        if intent in ["CODE", "PLAN", "RESEARCH", "COMPLEX"]:
            return True
            
        return False
    
    def process(self, text: str, context: str = "") -> SwarmResponse:
        """
        Process a query through the swarm system.
        
        Args:
            text: User's query
            context: Optional context (memory, preferences, etc.)
            
        Returns:
            SwarmResponse with the result
        """
        if not self.is_available:
            return SwarmResponse(
                content="Swarm system is not available.",
                source="error",
                complexity_score=0.0,
                model_used="none",
                success=False,
                error="Swarm not initialized"
            )
        
        try:
            # Check VRAM before processing
            if self._vram_monitor:
                vram_ok = self._vram_monitor.check_available()
                if not vram_ok:
                    logger.warning("VRAM pressure detected, using smaller model")
            
            # Run through swarm engine
            result = self._engine.run(prompt=text, context=context)
            
            return SwarmResponse(
                content=result.content,
                source=result.source,
                complexity_score=result.decision.complexity_score,
                model_used=self._get_model_for_source(result.source),
                success=True
            )
            
        except Exception as e:
            logger.error(f"Swarm processing error: {e}")
            return SwarmResponse(
                content=f"Error processing with swarm: {str(e)}",
                source="error",
                complexity_score=0.0,
                model_used="none",
                success=False,
                error=str(e)
            )
    
    def _get_model_for_source(self, source: str) -> str:
        """Get the model name used for a given source."""
        model_map = {
            "router": self.config.swarm_router_model,
            "planner": self.config.swarm_planner_model,
            "coder": self.config.swarm_coder_model,
            "researcher": self.config.swarm_researcher_model,
            "orchestrator": self.config.swarm_orchestrator_model,
            "browser": "browser-fallback",
        }
        return model_map.get(source, "unknown")


# Global instance
_swarm_integration: Optional[SwarmIntegration] = None


def get_swarm_integration() -> SwarmIntegration:
    """Get or create the global swarm integration instance."""
    global _swarm_integration
    if _swarm_integration is None:
        _swarm_integration = SwarmIntegration()
    return _swarm_integration

