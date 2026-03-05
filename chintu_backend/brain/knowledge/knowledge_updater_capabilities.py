"""Capabilities for Phase 13.5 Knowledge Updater."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType
from .knowledge_updater import get_knowledge_updater


class KnowledgeRefreshSchema(BaseModel):
    categories: Optional[List[str]] = Field(None, description="Optional categories to refresh.")
    max_per_category: Optional[int] = Field(None, ge=2, le=40, description="Items per category.")


class KnowledgeSearchSchema(BaseModel):
    query: str = Field(..., description="Knowledge query.")
    category: Optional[str] = Field(None, description="Optional category filter.")
    limit: Optional[int] = Field(5, ge=1, le=20, description="Result count.")


def _extract_categories(text: str) -> List[str]:
    found = []
    low = str(text or "").lower()
    for name in ("tech", "technology", "finance", "healthcare", "health"):
        if name in low:
            normalized = "tech" if name in {"technology"} else "healthcare" if name in {"health"} else name
            if normalized not in found:
                found.append(normalized)
    return found


def handle_knowledge_refresh(text: str, context: Dict[str, Any]) -> ActionResult:
    validated = context.get("_validated_params")
    categories = []
    max_per = None
    if isinstance(validated, KnowledgeRefreshSchema):
        categories = [str(c).strip().lower() for c in (validated.categories or []) if str(c).strip()]
        max_per = validated.max_per_category
    if not categories:
        categories = _extract_categories(text) or ["tech", "finance", "healthcare"]

    updater = get_knowledge_updater()
    result = updater.ingest_daily_updates(
        categories=categories,
        max_per_category=max_per,
        include_model_releases=True,
    )
    msg = (
        "Knowledge updater sync complete.\n"
        f"- Categories: {', '.join(result.get('categories') or [])}\n"
        f"- Ingested items: {result.get('ingested_count', 0)}\n"
        f"- Vector backend: {result.get('vector_backend', 'sqlite_lexical')}"
    )
    return ActionResult.ok(msg, result, "knowledge_updater_refresh")


def _extract_query(text: str) -> str:
    raw = str(text or "").strip()
    low = raw.lower()
    for marker in ("search knowledge for", "knowledge search", "find in knowledge", "read more about"):
        idx = low.find(marker)
        if idx >= 0:
            return raw[idx + len(marker) :].strip(" :,-")
    return raw


def handle_knowledge_search(text: str, context: Dict[str, Any]) -> ActionResult:
    validated = context.get("_validated_params")
    category = None
    limit = 5
    query = ""
    if isinstance(validated, KnowledgeSearchSchema):
        query = validated.query
        category = validated.category
        limit = int(validated.limit or 5)
    if not query:
        query = _extract_query(text)
    if not query:
        return ActionResult.fail("Tell me what to search in knowledge memory.", "knowledge_updater_search")

    updater = get_knowledge_updater()
    rows = updater.search(
        query=query,
        limit=limit,
        categories=[str(category).strip().lower()] if category else None,
    )
    if not rows:
        return ActionResult.ok("No matching knowledge items yet. Run a knowledge refresh first.", capability="knowledge_updater_search")

    lines = [f"Knowledge results for '{query}':"]
    for idx, row in enumerate(rows, start=1):
        category_name = str(row.get("category") or "news").replace("_", " ").title()
        title = str(row.get("title") or "").strip()
        freshness = str(row.get("freshness_label") or "").strip()
        score = float(row.get("score") or 0.0)
        suffix = f" ({freshness})" if freshness else ""
        lines.append(f"{idx}. [{category_name}] {title}{suffix} [score={score:.2f}]")
    lines.append("Say 'read more about #N' to expand one item.")
    return ActionResult.ok("\n".join(lines), {"query": query, "results": rows}, "knowledge_updater_search")


def register_knowledge_updater_capabilities(registry=None) -> None:
    from chintu_backend.core.capabilities import get_registry

    reg = registry or get_registry()
    reg.register(
        Capability(
            name="knowledge_updater_refresh",
            triggers=[
                "refresh knowledge updater",
                "update ai news knowledge",
                "sync model releases",
                "refresh daily knowledge",
            ],
            handler=handle_knowledge_refresh,
            requires_confirmation=False,
            description="ingest latest AI/tech/finance/health updates into local knowledge store",
            capability_type=CapabilityType.MEMORY,
            schema=KnowledgeRefreshSchema,
            examples=["Refresh knowledge updater for tech finance healthcare"],
        )
    )
    reg.register(
        Capability(
            name="knowledge_updater_search",
            triggers=[
                "knowledge search",
                "search knowledge for",
                "find in knowledge",
            ],
            handler=handle_knowledge_search,
            requires_confirmation=False,
            description="query local knowledge updater store",
            capability_type=CapabilityType.MEMORY,
            schema=KnowledgeSearchSchema,
            examples=["Search knowledge for latest open-source coding models"],
        )
    )

