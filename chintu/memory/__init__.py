"""Memory, preferences, temporal knowledge, and training data helpers."""

from .embedding import BaseEmbedder, HashingEmbedder
from .store import MemoryStore, MemoryRecord
from ..core.memory import MemoryManager  # Import from core (ChromaDB-based)
from .training_logger import TrainingDataLogger
from .preferences import UserPreferences, PreferenceManager, get_preference_manager
from .tiered_memory import TieredMemoryStore, MemoryItem, MemoryType, get_memory_store
from .temporal_graph import TemporalGraph, TemporalFact, get_temporal_graph
from .temporal_capabilities import register_temporal_capabilities
from .facade import MemoryFacade, get_memory_facade  # Unified interface

__all__ = [
    "BaseEmbedder",
    "HashingEmbedder",
    "MemoryStore",
    "MemoryRecord",
    "MemoryManager",
    "TrainingDataLogger",
    "UserPreferences",
    "PreferenceManager",
    "get_preference_manager",
    "TieredMemoryStore",
    "MemoryItem",
    "MemoryType",
    "get_memory_store",
    "TemporalGraph",
    "TemporalFact",
    "get_temporal_graph",
    "register_temporal_capabilities",
    "MemoryFacade",
    "get_memory_facade",
]

