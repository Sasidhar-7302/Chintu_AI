"""
Retrieval Router.
Decides how to query memory based on user intent.
Prioritizes structured knowledge for factual queries.
"""

import logging
from typing import Dict, Any, Optional
from chintu_backend.brain.memory.hybrid_memory import get_hybrid_memory

logger = logging.getLogger(__name__)

class RetrievalRouter:
    def __init__(self):
        self.memory = get_hybrid_memory()

    def retrieve(self, query: str, context: Dict[str, Any] = None) -> str:
        """
        Smart retrieval with metadata filtering.
        """
        if not self.memory:
            return ""

        filters = {}
        
        # Simple heuristic routing (Upgrade to LLM-based later if needed)
        query_lower = query.lower()
        
        # Intent: Recall conversation history
        if "what did i say" in query_lower or "what did we talk" in query_lower or "history" in query_lower:
            filters["category"] = "conversation"
            logger.info("Routing to Conversation Memory")

        # Intent: Factual knowledge / Research
        elif "what is" in query_lower or "explain" in query_lower or "how to" in query_lower or "learn about" in query_lower:
            # We explicitly want knowledge base, but maybe conversation too?
            # Ideally we want both, but ranked. 
            # But if we force filters, we might miss conversation context.
            # Strategy: Search Knowledge Base FIRST (high priority).
            # If low score, search Conversation.
            # For now, let's try to pass NO filter to search EVERYTHING, 
            # BUT we could have a bias.
            # HybridMemory currently merges scores.
            
            # If "according to your research" or "from the book", force knowledge.
            if "research" in query_lower or "book" in query_lower:
                 filters["category"] = "research"
                 logger.info("Routing to Research Knowledge")
        
        return self.memory.retrieve_context(query, filters=filters)

# Singleton
_router = None
def get_retrieval_router() -> RetrievalRouter:
    global _router
    if not _router:
        _router = RetrievalRouter()
    return _router
