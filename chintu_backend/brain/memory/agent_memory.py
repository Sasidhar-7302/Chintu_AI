"""Per-agent memory view for isolated agent sessions."""

from __future__ import annotations

from typing import Any, Dict, Optional


class AgentMemoryView:
    """Wraps the global memory manager to scope reads/writes to an agent."""

    def __init__(self, memory_manager, agent_id: str):
        self._memory = memory_manager
        self.agent_id = agent_id

    def save_interaction(
        self,
        role: str,
        content: str,
        meta: Optional[Dict[str, Any]] = None,
        category: str = "conversation",
        source: str = "chat",
    ) -> None:
        meta = dict(meta or {})
        tags = list(meta.get("tags", []))
        tag = f"agent:{self.agent_id}"
        if tag not in tags:
            tags.append(tag)
        meta["tags"] = tags
        if "source" not in meta:
            source = f"agent:{self.agent_id}"
        self._memory.save_interaction(role, content, meta=meta, category=category, source=source)

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        min_score: float = 0.0,
    ):
        filters = dict(filters or {})
        filters.setdefault("source", f"agent:{self.agent_id}")
        return self._memory.search(query, limit=limit, filters=filters, min_score=min_score)

    def retrieve_context(
        self,
        query: str,
        n_results: int = 4,
        filters: Optional[Dict[str, Any]] = None,
    ) -> str:
        filters = dict(filters or {})
        filters.setdefault("source", f"agent:{self.agent_id}")
        return self._memory.retrieve_context(query, n_results=n_results, filters=filters)
