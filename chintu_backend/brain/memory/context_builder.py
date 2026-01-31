"""
Unified Memory Context Builder for Chintu AI.

This module consolidates all memory sources (ConversationMemory, ChromaDB, 
TieredMemory, Preferences) into a single context string for LLM injection.

Key Benefits:
- Reduces context fragmentation
- Ensures consistent formatting
- Provides intelligent context truncation
- Single point of control for memory retrieval
"""

import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ContextSection:
    """A section of context with priority weighting."""
    name: str
    content: str
    priority: int  # 1 = highest, 5 = lowest
    max_chars: int = 1000  # Max chars for this section


class MemoryContextBuilder:
    """
    Builds comprehensive context from all Chintu memory sources.
    
    Usage:
        builder = MemoryContextBuilder()
        context = builder.build_context("What's my favorite color?")
        # Returns formatted string with relevant memories, conversation history, etc.
    """
    
    # Maximum total context length (tokens ≈ chars/4)
    MAX_CONTEXT_CHARS = 4000
    
    def __init__(self):
        self._conversation_memory = None
        self._memory_manager = None
        self._tiered_store = None
        self._preference_manager = None
        self._initialized = False
        
    def _lazy_init(self):
        """Lazily initialize memory sources to avoid circular imports."""
        if self._initialized:
            return
            
        try:
            from .conversation_memory import get_conversation_memory
            self._conversation_memory = get_conversation_memory()
        except Exception as e:
            logger.debug(f"ConversationMemory not available: {e}")
            
        try:
            from ...core.memory import get_memory_manager
            self._memory_manager = get_memory_manager()
        except Exception as e:
            logger.debug(f"MemoryManager not available: {e}")
            
        try:
            from .tiered_memory import get_tiered_store
            self._tiered_store = get_tiered_store()
        except Exception as e:
            logger.debug(f"TieredMemoryStore not available: {e}")
            
        try:
            from ...core.preference_manager import get_preference_manager
            self._preference_manager = get_preference_manager()
        except Exception as e:
            logger.debug(f"PreferenceManager not available: {e}")
            
        self._initialized = True
        
    def build_context(
        self, 
        query: str, 
        max_conversation_turns: int = 6,
        include_profile: bool = True,
        include_conversation: bool = True,
        include_memories: bool = True,
        include_preferences: bool = True,
    ) -> str:
        """
        Build unified context for LLM injection.
        
        Args:
            query: The user's query (used for semantic retrieval)
            max_conversation_turns: Max recent turns to include
            include_profile: Include user profile info
            include_conversation: Include recent conversation history
            include_memories: Include semantically relevant memories
            include_preferences: Include active user preferences
            
        Returns:
            Formatted context string ready for LLM system prompt injection
        """
        self._lazy_init()
        
        sections: List[ContextSection] = []
        
        # 1. User Profile (highest priority - always relevant)
        if include_profile:
            profile = self._get_user_profile()
            if profile.strip():
                sections.append(ContextSection(
                    name="About the User",
                    content=profile,
                    priority=1,
                    max_chars=500
                ))
        
        # 2. Recent Conversation (high priority - immediate context)
        if include_conversation:
            conversation = self._get_conversation_context(max_conversation_turns)
            if conversation.strip():
                sections.append(ContextSection(
                    name="Recent Conversation",
                    content=conversation,
                    priority=2,
                    max_chars=1500
                ))
        
        # 3. Relevant Memories from semantic search (medium priority)
        if include_memories:
            memories = self._get_relevant_memories(query)
            if memories.strip():
                sections.append(ContextSection(
                    name="Relevant Memories",
                    content=memories,
                    priority=3,
                    max_chars=1200
                ))
        
        # 4. Personal Facts from tiered memory (medium priority)
        if include_memories:
            facts = self._get_personal_facts(query)
            if facts.strip():
                sections.append(ContextSection(
                    name="Known Facts",
                    content=facts,
                    priority=3,
                    max_chars=600
                ))
        
        # 5. User Preferences (lower priority but useful)
        if include_preferences:
            prefs = self._get_active_preferences()
            if prefs.strip():
                sections.append(ContextSection(
                    name="User Preferences",
                    content=prefs,
                    priority=4,
                    max_chars=400
                ))
        
        # Sort by priority and build final context
        sections.sort(key=lambda s: s.priority)
        
        return self._format_sections(sections)
    
    def _get_user_profile(self) -> str:
        """Get user profile information."""
        if not self._memory_manager:
            return ""
            
        try:
            return self._memory_manager.get_profile_context()
        except Exception as e:
            logger.debug(f"Failed to get user profile: {e}")
            return ""
    
    def _get_conversation_context(self, max_turns: int) -> str:
        """Get recent conversation history."""
        if not self._conversation_memory:
            return ""
            
        try:
            return self._conversation_memory.get_context(max_turns=max_turns)
        except Exception as e:
            logger.debug(f"Failed to get conversation context: {e}")
            return ""
    
    def _get_relevant_memories(self, query: str) -> str:
        """Get semantically relevant memories from ChromaDB."""
        if not self._memory_manager:
            return ""
            
        try:
            return self._memory_manager.retrieve_context(query, n_results=3)
        except Exception as e:
            logger.debug(f"Failed to retrieve memories: {e}")
            return ""
    
    def _get_personal_facts(self, query: str) -> str:
        """Get relevant personal facts from tiered memory."""
        if not self._tiered_store:
            return ""
            
        try:
            # Get all facts and filter by relevance
            facts = self._tiered_store.get_all_facts()
            if not facts:
                return ""
            
            # Simple keyword matching for now
            query_words = set(query.lower().split())
            relevant = []
            
            for fact in facts[:10]:  # Limit to 10 recent facts
                fact_text = fact.get("content", "")
                fact_words = set(fact_text.lower().split())
                
                # Check for any word overlap
                if query_words & fact_words:
                    relevant.append(f"- {fact_text}")
                    
            return "\n".join(relevant[:5])  # Max 5 relevant facts
        except Exception as e:
            logger.debug(f"Failed to get personal facts: {e}")
            return ""
    
    def _get_active_preferences(self) -> str:
        """Get user's active preferences."""
        if not self._preference_manager:
            return ""
            
        try:
            prefs = self._preference_manager.preferences
            if not prefs:
                return ""
                
            pref_dict = prefs.to_dict() if hasattr(prefs, 'to_dict') else dict(prefs)
            
            lines = []
            for key, value in pref_dict.items():
                if value and key != "raw":  # Skip empty and raw data
                    lines.append(f"- {key}: {value}")
                    
            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Failed to get preferences: {e}")
            return ""
    
    def _format_sections(self, sections: List[ContextSection]) -> str:
        """Format sections into final context string with truncation."""
        parts = []
        remaining_chars = self.MAX_CONTEXT_CHARS
        
        for section in sections:
            if remaining_chars <= 0:
                break
                
            # Truncate section content if needed
            content = section.content[:min(section.max_chars, remaining_chars)]
            
            if content.strip():
                parts.append(f"## {section.name}\n{content}")
                remaining_chars -= len(content) + len(section.name) + 5
        
        if not parts:
            return ""
            
        return "\n\n".join(parts)
    
    def get_conversation_for_api(self, max_turns: int = 5) -> List[Dict[str, str]]:
        """
        Get conversation history formatted for OpenAI-style message arrays.
        
        Returns:
            List of {"role": "user/assistant", "content": "..."}
        """
        self._lazy_init()
        
        if not self._conversation_memory:
            return []
            
        try:
            return self._conversation_memory.get_context_for_llm(max_turns=max_turns)
        except Exception as e:
            logger.debug(f"Failed to get conversation for API: {e}")
            return []


# Global instance
_context_builder: Optional[MemoryContextBuilder] = None


def get_context_builder() -> MemoryContextBuilder:
    """Get the global MemoryContextBuilder instance."""
    global _context_builder
    if _context_builder is None:
        _context_builder = MemoryContextBuilder()
    return _context_builder
