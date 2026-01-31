"""
Memory Facade - Unified interface for all Chintu memory systems.

This module consolidates the various memory backends into a single, 
easy-to-use interface for the rest of the application.

Architecture:
- TieredMemoryStore (SQLite): FACT, HISTORY, NOTE, PREFERENCE
- MemoryManager (ChromaDB): Semantic search on conversations
- PreferenceManager (JSON): User preferences
- RetrievalRouter: Smart query routing

This facade provides:
- Single import for all memory operations
- Consistent API regardless of backend
- Future-proof abstraction for memory consolidation
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MemoryResult:
    """Result from memory query."""
    content: str
    source: str
    relevance: float = 1.0
    metadata: Dict[str, Any] = None


class MemoryFacade:
    """
    Unified memory interface for Chintu.
    
    Consolidates:
    - Personal facts (SQLite + ChromaDB)
    - Conversation history (SQLite + ChromaDB)
    - User preferences (JSON)
    - Notes and tasks (SQLite)
    """
    
    def __init__(self):
        self._tiered_store = None
        self._chroma_memory = None
        self._preferences = None
        self._retrieval_router = None
        self._initialized = False
    
    def _ensure_initialized(self):
        """Lazy initialization of memory backends."""
        if self._initialized:
            return
        
        try:
            from .tiered_memory import get_memory_store
            self._tiered_store = get_memory_store()
        except Exception as e:
            logger.warning(f"TieredMemoryStore not available: {e}")
        
        try:
            from ...core.memory import MemoryManager
            self._chroma_memory = MemoryManager()
        except Exception as e:
            logger.warning(f"ChromaDB MemoryManager not available: {e}")
        
        try:
            from .preferences import get_preference_manager
            self._preferences = get_preference_manager()
        except Exception as e:
            logger.warning(f"PreferenceManager not available: {e}")
        
        try:
            from .retrieval_router import get_retrieval_router
            self._retrieval_router = get_retrieval_router()
        except Exception as e:
            logger.warning(f"RetrievalRouter not available: {e}")
        
        self._initialized = True
        logger.info("MemoryFacade initialized")
    
    # =========================================================================
    # FACTS (Persistent personal information)
    # =========================================================================
    
    def save_fact(self, content: str, importance: float = 0.5, **metadata) -> bool:
        """Save a personal fact (e.g., 'User's name is John')."""
        self._ensure_initialized()
        if self._tiered_store:
            self._tiered_store.add_fact(content, importance=importance, metadata=metadata)
            return True
        return False
    
    def get_facts(self, query: str = None, limit: int = 10) -> List[MemoryResult]:
        """Get personal facts, optionally filtered by query."""
        self._ensure_initialized()
        results = []
        if self._tiered_store:
            facts = self._tiered_store.search_facts(query) if query else self._tiered_store.get_facts(limit)
            for fact in facts[:limit]:
                results.append(MemoryResult(
                    content=fact.content,
                    source="facts",
                    relevance=fact.importance,
                    metadata=fact.metadata
                ))
        return results
    
    # =========================================================================
    # PREFERENCES (User settings and style)
    # =========================================================================
    
    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a user preference value."""
        self._ensure_initialized()
        if self._preferences:
            return getattr(self._preferences.preferences, key, default)
        return default
    
    def set_preference(self, key: str, value: Any) -> bool:
        """Set a user preference."""
        self._ensure_initialized()
        if self._preferences:
            prefs = self._preferences.preferences
            if hasattr(prefs, key):
                setattr(prefs, key, value)
                self._preferences.save()
                return True
        return False
    
    def get_all_preferences(self) -> Dict[str, Any]:
        """Get all user preferences as dict."""
        self._ensure_initialized()
        if self._preferences:
            return self._preferences.preferences.to_dict()
        return {}
    
    # =========================================================================
    # NOTES (User-saved notes and reminders)
    # =========================================================================
    
    def save_note(self, content: str, **metadata) -> bool:
        """Save a note."""
        self._ensure_initialized()
        if self._tiered_store:
            self._tiered_store.add_note(content, metadata=metadata)
            return True
        return False
    
    def get_notes(self, query: str = None, limit: int = 10) -> List[MemoryResult]:
        """Get notes, optionally filtered by query."""
        self._ensure_initialized()
        results = []
        if self._tiered_store:
            notes = self._tiered_store.search_notes(query) if query else self._tiered_store.get_notes(limit)
            for note in notes[:limit]:
                results.append(MemoryResult(
                    content=note.content,
                    source="notes",
                    metadata=note.metadata
                ))
        return results
    
    # =========================================================================
    # CONVERSATION HISTORY
    # =========================================================================
    
    def save_interaction(self, role: str, content: str, **metadata) -> bool:
        """Save a conversation turn."""
        self._ensure_initialized()
        if self._chroma_memory:
            self._chroma_memory.save_interaction(role, content, metadata)
            return True
        return False
    
    def get_context(self, query: str, max_results: int = 3) -> str:
        """Get relevant conversation context via semantic search."""
        self._ensure_initialized()
        if self._chroma_memory:
            return self._chroma_memory.retrieve_context(query, n_results=max_results)
        return ""
    
    # =========================================================================
    # SMART RETRIEVAL (RAG)
    # =========================================================================
    
    def retrieve(self, query: str, max_results: int = 5) -> List[MemoryResult]:
        """Smart retrieval using RetrievalRouter."""
        self._ensure_initialized()
        if self._retrieval_router:
            rag_results = self._retrieval_router.retrieve(query, max_results)
            return [
                MemoryResult(
                    content=r.content,
                    source=r.source,
                    relevance=r.relevance,
                    metadata=r.metadata
                )
                for r in rag_results
            ]
        return []
    
    def format_context(self, results: List[MemoryResult]) -> str:
        """Format retrieval results for LLM injection."""
        if not results:
            return ""
        lines = ["[Retrieved Context]"]
        for r in results:
            lines.append(f"- ({r.source}) {r.content}")
        return "\n".join(lines)


# Global instance
_memory_facade: Optional[MemoryFacade] = None


def get_memory_facade() -> MemoryFacade:
    """Get or create the global memory facade."""
    global _memory_facade
    if _memory_facade is None:
        _memory_facade = MemoryFacade()
    return _memory_facade
