"""
Conversation Flow Manager.
Handles chat history, context tracking, and response generation for pure conversation.
Replaces the "Greeting" and "Small Talk" logic previously buried in CommandHandler.
"""

import logging
from typing import List, Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class ConversationFlow:
    """
    Manages the conversational aspect of the assistant.
    - Tracks active context
    - formatting responses
    - ensuring personality consistency (via LLM, not regex)
    """

    def __init__(self, memory_manager=None, llm_client=None):
        self.memory_manager = memory_manager
        self.llm_client = llm_client
        self._history: List[Dict[str, str]] = []
        # Keep last 10 turns in memory for immediate context
        self.max_history = 10

    def add_user_message(self, text: str):
        """Add user message to history."""
        self._history.append({"role": "user", "content": text, "timestamp": datetime.now().isoformat()})
        self._trim_history()

    def add_assistant_message(self, text: str):
        """Add assistant response to history."""
        self._history.append({"role": "assistant", "content": text, "timestamp": datetime.now().isoformat()})
        self._trim_history()
        # Also save to long-term memory if available
        if self.memory_manager:
            self.memory_manager.save_interaction("assistant", text)

    def _trim_history(self):
        """Keep history within limits."""
        if len(self._history) > self.max_history * 2:
            self._history = self._history[-(self.max_history * 2):]

    def get_context(self, current_query: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Get current conversation context for LLM.
        Includes Short-Term history + Long-Term RAG.
        """
        messages = [{"role": m["role"], "content": m["content"]} for m in self._history]
        
        # 1. Retrieve detailed long-term memory if query matches
        if self.memory_manager and current_query:
            try:
                # Use searchable memory if available (Phase 3)
                relevant_memories = []
                
                # Check if it has the new search method (Phase 3 Upgrade)
                if hasattr(self.memory_manager, 'search'):
                    # Deterministic search
                    results = self.memory_manager.search(current_query, limit=3)
                    if results:
                        relevant_memories = [
                            f"[Memory {r.created_at[:10]}] {r.content}" for r in results
                        ]
                else:
                    # Fallback to legacy string context
                    ctx_str = self.memory_manager.retrieve_context(current_query, n_results=3)
                    if ctx_str:
                        relevant_memories = ctx_str.split("\n")

                if relevant_memories:
                    # Inject as system message or context
                    memory_block = "\n".join(relevant_memories)
                    system_msg = {
                        "role": "system", 
                        "content": f"Relevant Past Memories:\n{memory_block}"
                    }
                    # Insert before history
                    messages.insert(0, system_msg)
                    logger.info(f"Injected {len(relevant_memories)} memories into context.")
            except Exception as e:
                logger.warning(f"Memory retrieval failed: {e}")
                
        return messages
    
    def clear_context(self):
        """Reset conversation context (e.g. after long idle)."""
        self._history = []
        logger.info("Conversation context cleared")
