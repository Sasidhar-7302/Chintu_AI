"""Capabilities for managing the Chintu curated library."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Any

from chintu_backend.core.capabilities import Capability, CapabilityType, ActionResult
from chintu_backend.core.config import get_config
from .library_indexer import LibraryIndexer, LibraryReviewStore

logger = logging.getLogger(__name__)


def _get_library_indexer() -> LibraryIndexer:
    config = get_config()
    root = Path(getattr(config, "library_root_dir", Path.cwd() / "Chintus_Library"))
    memory = None
    try:
        from chintu_backend.brain.memory.hybrid_memory import get_hybrid_memory

        memory = get_hybrid_memory()
        if memory is None and getattr(config, "memory_enabled", True):
            from chintu_backend.brain.memory.hybrid_memory import HybridMemoryManager

            memory = HybridMemoryManager(db_path=getattr(config, "memory_sqlite_path", None))
    except Exception:
        memory = None
    return LibraryIndexer(root_dir=root, memory_manager=memory, config=config)


def handle_library_index(text: str, context: Dict[str, Any]) -> ActionResult:
    indexer = _get_library_indexer()
    result = indexer.index_all()
    msg = (
        "Library indexed.\n"
        f"- Indexed: {result['indexed']}\n"
        f"- Skipped: {result['skipped']}\n"
        f"- Pending review: {result['pending']}"
    )
    return ActionResult.ok(msg, result, "library_index")


def handle_library_status(text: str, context: Dict[str, Any]) -> ActionResult:
    indexer = _get_library_indexer()
    entries = indexer.load_index()
    pending = 0
    for path in entries:
        if not indexer.review_store.is_approved(path):
            pending += 1
    msg = (
        f"Library status:\n"
        f"- Documents indexed: {len(entries)}\n"
        f"- Pending review: {pending}\n"
        f"- Root: {indexer.root_dir}"
    )
    return ActionResult.ok(msg, {"indexed": len(entries), "pending": pending}, "library_status")


def handle_library_approve(text: str, context: Dict[str, Any]) -> ActionResult:
    indexer = _get_library_indexer()
    rel_path = text.split("approve", 1)[-1].strip().strip(":")
    if not rel_path:
        return ActionResult.fail("Provide a library relative path to approve.", "library_approve")
    review = LibraryReviewStore(indexer.index_dir)
    review.mark_approved(rel_path, reviewer="user")
    return ActionResult.ok(f"Approved library doc: {rel_path}", {"path": rel_path}, "library_approve")


def handle_library_search(text: str, context: Dict[str, Any]) -> ActionResult:
    indexer = _get_library_indexer()
    entries = indexer.load_index()
    query = text.lower().replace("search library", "").strip()
    if not query:
        return ActionResult.fail("Provide search terms. Example: 'search library neural networks'", "library_search")

    hits = []
    for entry in entries.values():
        hay = " ".join([entry.title, entry.summary, " ".join(entry.keywords), " ".join(entry.tags)]).lower()
        if query in hay:
            hits.append(entry)
    hits = hits[:10]
    if not hits:
        return ActionResult.ok("No library matches found.", {"count": 0}, "library_search")
    lines = [f"Library matches ({len(hits)}):"]
    for item in hits:
        lines.append(f"- {item.title} ({item.path})")
    return ActionResult.ok("\n".join(lines), {"count": len(hits)}, "library_search")


def register_library_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="library_index",
            triggers=["index library", "update library", "scan library"],
            handler=handle_library_index,
            requires_confirmation=False,
            description="index Chintu's curated library",
            capability_type=CapabilityType.AUTOMATION,
            examples=["Index library", "Update library index"],
        )
    )
    registry.register(
        Capability(
            name="library_status",
            triggers=["library status", "show library status", "library overview"],
            handler=handle_library_status,
            requires_confirmation=False,
            description="show library indexing status",
            capability_type=CapabilityType.PRODUCTIVITY,
            examples=["Library status"],
        )
    )
    registry.register(
        Capability(
            name="library_approve",
            triggers=["approve library", "approve knowledge", "approve library doc"],
            handler=handle_library_approve,
            requires_confirmation=True,
            description="approve a library document for indexing",
            capability_type=CapabilityType.AI_AGENT,
            examples=["Approve library domains/ai/transformers.md"],
        )
    )
    registry.register(
        Capability(
            name="library_search",
            triggers=["search library", "find in library"],
            handler=handle_library_search,
            requires_confirmation=False,
            description="search the curated knowledge library",
            capability_type=CapabilityType.PRODUCTIVITY,
            examples=["Search library transformers"],
        )
    )
