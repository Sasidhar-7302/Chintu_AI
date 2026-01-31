"""Core module - Configuration, events, and state management."""

from .config import Config, get_config
from .events import EventBus, Event, EventType, get_event_bus
from .state import AssistantState, StateManager, get_state_manager
from .command_handler import CommandHandler
from .websocket_server import WebSocketServer

# Reliability & Intelligence Enhancements (Phase 1-3)
from .policy import (
    ActionPolicyEngine, RiskLevel, PolicyDecision, CapabilityContract,
    ActionPolicy, SystemState, get_policy_engine
)
from .budget_manager import (
    RateLimitBudgetManager, ProviderLimits, get_budget_manager
)
from .degraded_mode import (
    OfflineDegradedMode, SystemMode, CapabilityAvailability, get_degraded_mode
)
from .metrics import MetricsCollector, get_metrics
from .logging_config import (
    StructuredLogger, new_trace_id, get_trace_id, timed,
    ErrorCategory, categorize_error
)
from .executive import (
    ExecutiveBrain, ExecutionPhase, ExecutionPlan, ExecutionResult,
    get_executive_brain
)

__all__ = [
    # Original exports
    "Config", "get_config",
    "EventBus", "Event", "EventType", "get_event_bus",
    "AssistantState", "StateManager", "get_state_manager",
    "CommandHandler", "WebSocketServer",
    
    # Policy Engine
    "ActionPolicyEngine", "RiskLevel", "PolicyDecision", "CapabilityContract",
    "ActionPolicy", "SystemState", "get_policy_engine",
    
    # Budget Manager
    "RateLimitBudgetManager", "ProviderLimits", "get_budget_manager",
    
    # Degraded Mode
    "OfflineDegradedMode", "SystemMode", "CapabilityAvailability", "get_degraded_mode",
    
    # Metrics & Logging
    "MetricsCollector", "get_metrics",
    "StructuredLogger", "new_trace_id", "get_trace_id", "timed",
    "ErrorCategory", "categorize_error",
    
    # Executive Brain
    "ExecutiveBrain", "ExecutionPhase", "ExecutionPlan", "ExecutionResult",
    "get_executive_brain",
]
