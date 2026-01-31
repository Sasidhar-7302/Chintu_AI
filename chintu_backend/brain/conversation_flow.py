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

    def get_context(self) -> List[Dict[str, str]]:
        """Get current conversation context for LLM."""
        return [{"role": m["role"], "content": m["content"]} for m in self._history]
    
    def clear_context(self):
        """Reset conversation context (e.g. after long idle)."""
        self._history = []
        logger.info("Conversation context cleared")
