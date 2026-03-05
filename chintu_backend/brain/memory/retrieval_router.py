"""
Retrieval Router for Chintu's RAG Pipeline.
Intelligently routes queries to the appropriate memory collections.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class QueryType(Enum):
    """Types of queries for routing."""
    PERSONAL = "personal"       # About the user, preferences, history
    RESEARCH = "research"       # Documents, web research, facts
    KNOWLEDGE = "knowledge"     # General knowledge (skip RAG)
    TASK = "task"               # Tasks, reminders, notes


@dataclass
class RetrievalResult:
    """Result from retrieval."""
    content: str
    source: str  # collection name
    relevance: float
    metadata: Dict[str, Any] = None
    sources: List[str] = None


@dataclass
class RagAssessment:
    confidence: float
    needs_clarification: bool
    needs_web_search: bool
    reason: str
    sources_count: int


class RetrievalRouter:
    """
    Routes queries to appropriate memory collections.
    
    This is the "Executive Recall" step of the brain:
    - Analyze query intent
    - Decide which collections to search
    - Merge and rank results
    """
    
    # Keywords for personal queries
    PERSONAL_KEYWORDS = {
        "my", "i", "me", "myself", "prefer", "like", "want",
        "remember", "told you", "said", "we discussed", "we talked",
        "last time", "yesterday", "earlier", "before", "history"
    }
    
    # Keywords for research/document queries
    RESEARCH_KEYWORDS = {
        "document", "paper", "article", "research", "source",
        "read", "file", "pdf", "notes", "findings", "study"
    }
    
    # Keywords for task queries
    TASK_KEYWORDS = {
        "task", "reminder", "todo", "schedule", "deadline",
        "meeting", "appointment", "when", "due"
    }
    
    def __init__(self, memory_manager=None, tiered_store=None):
        """
        Initialize with memory backends.
        
        Args:
            memory_manager: ChromaDB-based memory (semantic search)
            tiered_store: SQLite-based memory (structured)
        """
        self.memory_manager = memory_manager
        self.tiered_store = tiered_store
    
    def classify_query(self, query: str) -> QueryType:
        """
        Classify a query to determine which memory to search.
        
        Uses keyword matching first, then falls back to semantic search
        if no strong keyword match is found.
        """
        query_lower = query.lower()
        
        # Check for personal keywords
        personal_score = sum(1 for kw in self.PERSONAL_KEYWORDS if kw in query_lower)
        research_score = sum(1 for kw in self.RESEARCH_KEYWORDS if kw in query_lower)
        task_score = sum(1 for kw in self.TASK_KEYWORDS if kw in query_lower)
        
        # Determine winner
        scores = {
            QueryType.PERSONAL: personal_score,
            QueryType.RESEARCH: research_score,
            QueryType.TASK: task_score,
            QueryType.KNOWLEDGE: 0  # Default if no keywords match
        }
        
        best_type = max(scores, key=scores.get)
        
        # If no keywords matched, try semantic fallback
        if scores[best_type] == 0:
            # SEMANTIC FALLBACK: Check if ChromaDB has relevant personal content
            semantic_type = self._semantic_classify(query)
            if semantic_type:
                logger.debug(f"Semantic fallback: classified as {semantic_type.value}")
                return semantic_type
            return QueryType.KNOWLEDGE
        
        logger.debug(f"Query classified as {best_type.value}: '{query[:50]}...'")
        return best_type
    
    def _semantic_classify(self, query: str) -> Optional[QueryType]:
        """
        Use semantic similarity to classify queries that don't match keywords.
        
        Checks if ChromaDB has similar content, indicating this might be
        a personal memory query.
        """
        if not self.memory_manager:
            return None
            
        try:
            # Try to get ChromaDB collection
            collection = getattr(self.memory_manager, 'collection', None)
            if not collection:
                return None
            
            # Query with low n_results to check for relevance
            results = collection.query(
                query_texts=[query],
                n_results=1,
                include=["distances"]
            )
            
            # Check if we have a close semantic match
            if results and results.get("distances") and results["distances"][0]:
                distance = results["distances"][0][0]
                
                # Distance threshold: lower = more similar
                # Typical range: 0.0 (identical) to 2.0 (unrelated)
                if distance < 0.7:
                    logger.debug(f"Semantic match found (distance={distance:.3f})")
                    return QueryType.PERSONAL
                    
        except Exception as e:
            logger.debug(f"Semantic classification failed: {e}")
            
        return None
    
    def retrieve(self, query: str, max_results: int = 5) -> List[RetrievalResult]:
        """
        Retrieve relevant context for a query.
        
        This is the main entry point for the Executive Brain.
        """
        query_type = self.classify_query(query)
        results = []
        
        try:
            if query_type == QueryType.KNOWLEDGE:
                results.extend(self._search_library(query, max_results))
            
            elif query_type == QueryType.PERSONAL:
                # Search personal facts + conversation history
                results.extend(self._search_personal(query, max_results))
                
            elif query_type == QueryType.RESEARCH:
                # Search documents + curated library
                results.extend(self._search_documents(query, max_results))
                results.extend(self._search_library(query, max_results))
                
            elif query_type == QueryType.TASK:
                # Search tasks/notes from SQLite
                results.extend(self._search_tasks(query, max_results))
            
            # Sort by relevance
            results.sort(key=lambda x: x.relevance, reverse=True)
            return results[:max_results]
            
        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            return []
    
    def _search_personal(self, query: str, max_results: int) -> List[RetrievalResult]:
        """Search personal facts and conversation history."""
        results = []
        
        # ChromaDB semantic search (if available)
        if self.memory_manager and hasattr(self.memory_manager, 'retrieve_context'):
            try:
                context = self.memory_manager.retrieve_context(query, n_results=max_results)
                if context:
                    results.append(RetrievalResult(
                        content=context,
                        source="conversation_memory",
                        relevance=0.8
                    ))
            except Exception as e:
                logger.warning(f"ChromaDB search failed: {e}")
        
        # SQLite facts (if available)
        if self.tiered_store:
            try:
                facts = self.tiered_store.search_facts(query)
                for fact in facts[:max_results]:
                    results.append(RetrievalResult(
                        content=fact.content,
                        source="personal_facts",
                        relevance=fact.importance,
                        metadata=fact.metadata
                    ))
            except Exception as e:
                logger.warning(f"SQLite facts search failed: {e}")
        
        return results
    
    def _search_documents(self, query: str, max_results: int) -> List[RetrievalResult]:
        """Search document collection."""
        results = []
        
        # ChromaDB documents collection (if available)
        if self.memory_manager and hasattr(self.memory_manager, 'search_documents'):
            try:
                docs = self.memory_manager.search_documents(query, n_results=max_results)
                for doc in docs:
                    results.append(RetrievalResult(
                        content=doc.get("content", ""),
                        source="documents",
                        relevance=doc.get("relevance", 0.5),
                        metadata=doc.get("metadata", {})
                    ))
            except Exception as e:
                logger.warning(f"Document search failed: {e}")
        
        return results

    def _search_library(self, query: str, max_results: int) -> List[RetrievalResult]:
        """Search curated library content indexed into hybrid memory."""
        results: List[RetrievalResult] = []
        if not self.memory_manager or not hasattr(self.memory_manager, "search"):
            return results
        try:
            hits = self.memory_manager.search(
                query,
                limit=max_results,
                filters={"category": "library"},
                min_score=0.05,
            )
        except Exception as exc:
            logger.warning(f"Library search failed: {exc}")
            return results

        for hit in hits:
            tags = hit.metadata.get("tags") if hit.metadata else []
            tags = tags or []
            sources = [t[4:] for t in tags if isinstance(t, str) and t.startswith("src:")]
            file_tag = next((t for t in tags if isinstance(t, str) and t.startswith("file:")), "")
            meta = dict(hit.metadata or {})
            if file_tag:
                meta["file"] = file_tag.replace("file:", "")
            results.append(
                RetrievalResult(
                    content=hit.content,
                    source="library",
                    relevance=float(hit.score),
                    metadata=meta,
                    sources=sources,
                )
            )
        return results

    def assess(self, query: str, results: List[RetrievalResult]) -> RagAssessment:
        """Assess confidence and decide if clarification or web search is needed."""
        from chintu_backend.core.config import get_config

        config = get_config()
        min_conf = float(getattr(config, "rag_min_confidence", 0.35))
        contested_min_sources = int(getattr(config, "rag_min_sources_contested", 2))
        require_citations = bool(getattr(config, "rag_require_citations", True))

        sources = set()
        for res in results:
            for src in (res.sources or []):
                sources.add(src)
        sources_count = len(sources)

        if results:
            avg_rel = sum(r.relevance for r in results) / len(results)
        else:
            avg_rel = 0.0

        confidence = min(1.0, avg_rel * 0.7 + min(1.0, sources_count / 3.0) * 0.3)

        tokens = [t for t in query.strip().split() if t]
        needs_clarification = len(tokens) < 3

        contested = self._is_contested(query)
        needs_web = False
        reason = ""
        if contested and sources_count < contested_min_sources:
            needs_web = True
            reason = "contested topic needs more sources"
        elif require_citations and confidence < min_conf:
            needs_web = True
            reason = "low confidence in local sources"

        return RagAssessment(
            confidence=confidence,
            needs_clarification=needs_clarification,
            needs_web_search=needs_web,
            reason=reason or "sufficient",
            sources_count=sources_count,
        )
    
    def _search_tasks(self, query: str, max_results: int) -> List[RetrievalResult]:
        """Search tasks and notes from SQLite."""
        results = []
        
        if self.tiered_store:
            try:
                notes = self.tiered_store.search_notes(query)
                for note in notes[:max_results]:
                    results.append(RetrievalResult(
                        content=note.content,
                        source="notes",
                        relevance=note.importance,
                        metadata=note.metadata
                    ))
            except Exception as e:
                logger.warning(f"Notes search failed: {e}")
        
        return results
    
    def format_for_llm(self, results: List[RetrievalResult]) -> str:
        """Format retrieval results as context for LLM injection with citations."""
        if not results:
            return ""

        lines = ["[Retrieved Context]"]
        all_sources: List[str] = []
        for r in results:
            source_label = r.source.replace("_", " ").title()
            lines.append(f"- ({source_label}) {r.content}")
            for src in r.sources or []:
                if src not in all_sources:
                    all_sources.append(src)

        if all_sources:
            lines.append("")
            lines.append("Sources:")
            for idx, src in enumerate(all_sources, start=1):
                lines.append(f"[{idx}] {src}")
            lines.append("If you state facts, cite sources like [1].")

        return "\n".join(lines)

    def _is_contested(self, query: str) -> bool:
        from chintu_backend.core.config import get_config

        config = get_config()
        keywords = getattr(config, "rag_contested_keywords", None)
        if not keywords:
            keywords = [
                "best",
                "worst",
                "cure",
                "politics",
                "religion",
                "controversial",
                "debate",
                "conspiracy",
                "health",
                "medical",
                "finance",
            ]
        query_lower = query.lower()
        return any(word in query_lower for word in keywords)


# Global instance
_router: Optional[RetrievalRouter] = None


def get_retrieval_router() -> RetrievalRouter:
    """Get or create the global retrieval router."""
    global _router
    if _router is None:
        # Try to get memory backends
        try:
            from ...core.config import get_config
            from .tiered_memory import get_memory_store
            config = get_config()
            if getattr(config, "memory_backend", "hybrid") == "hybrid":
                from .hybrid_memory import HybridMemoryManager

                mm = HybridMemoryManager(db_path=getattr(config, "memory_sqlite_path", None))
            else:
                from ...core.memory import MemoryManager

                mm = MemoryManager()
            ts = get_memory_store()
            _router = RetrievalRouter(memory_manager=mm, tiered_store=ts)
        except Exception as e:
            logger.warning(f"Could not initialize memory backends: {e}")
            _router = RetrievalRouter()
    return _router
