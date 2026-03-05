"""Capabilities for repository indexing and indexed code search."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType
from chintu_backend.core.config import get_config

from .repo_indexer import RepoIndexer


def _extract_path(text: str) -> Optional[Path]:
    if not text:
        return None
    quoted = re.search(r"\"([^\"]+)\"|'([^']+)'", text)
    if quoted:
        raw = quoted.group(1) or quoted.group(2) or ""
        if raw:
            return Path(raw).expanduser()
    drive = re.search(r"([A-Za-z]:[\\/][^\s]+)", text)
    if drive:
        return Path(drive.group(1)).expanduser()
    return None


def _extract_top_k(text: str, default: int = 8) -> int:
    match = re.search(r"\b(?:top|k|limit)\s*[:=]?\s*(\d{1,2})\b", str(text or "").lower())
    if not match:
        return max(1, min(20, int(default)))
    try:
        value = int(match.group(1))
    except Exception:
        return max(1, min(20, int(default)))
    return max(1, min(20, value))


def _extract_ext(text: str) -> Optional[str]:
    match = re.search(r"\bext\s*[:=]\s*([.\w]+)\b", str(text or "").lower())
    if match:
        value = match.group(1).strip()
        return value if value.startswith(".") else f".{value}"
    match = re.search(r"\bin\s+(\.[a-z0-9]+)\s+files?\b", str(text or "").lower())
    if match:
        return match.group(1).strip()
    return None


def _extract_path_prefix(text: str) -> Optional[str]:
    match = re.search(r"\bpath\s*[:=]\s*([^\s]+)", str(text or ""))
    if not match:
        return None
    value = str(match.group(1) or "").strip().strip("\"'")
    return value.replace("\\", "/") if value else None


def _extract_search_query(text: str) -> str:
    raw = str(text or "").strip()
    patterns = [
        r"(?i)^repo search\s*[:\-]?\s*",
        r"(?i)^search indexed repo\s*[:\-]?\s*",
        r"(?i)^search repo index\s*[:\-]?\s*",
    ]
    for pattern in patterns:
        raw = re.sub(pattern, "", raw).strip()
    raw = re.sub(r"\b(?:top|k|limit)\s*[:=]?\s*\d{1,2}\b", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"\bext\s*[:=]\s*[.\w]+\b", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"\bpath\s*[:=]\s*[^\s]+\b", "", raw, flags=re.IGNORECASE).strip()
    return raw


def handle_repo_index_build(text: str, context: Dict[str, Any]) -> ActionResult:
    user_path = _extract_path(text)
    target = user_path if user_path else Path(context.get("workspace_dir") or Path.cwd())
    incremental = "full" not in str(text or "").lower()
    indexer = RepoIndexer(root_path=target)
    stats = indexer.build(incremental=incremental)
    lines = [
        "Repository index build complete.",
        f"- Root: {stats.get('root_path', '')}",
        f"- Indexed files: {stats.get('files_indexed', 0)}",
        f"- Unchanged files: {stats.get('files_unchanged', 0)}",
        f"- Removed files: {stats.get('files_removed', 0)}",
        f"- Skipped files: {stats.get('files_skipped', 0)}",
        f"- Chunks added: {stats.get('chunks_added', 0)}",
        f"- Elapsed: {stats.get('elapsed_ms', 0)} ms",
    ]
    return ActionResult.ok("\n".join(lines), stats, "repo_index_build")


def handle_repo_index_search(text: str, context: Dict[str, Any]) -> ActionResult:
    query = _extract_search_query(text)
    if not query:
        return ActionResult.fail(
            "Please provide a search query. Example: repo search where is class RepoIndexer defined",
            "repo_index_search",
        )
    user_path = _extract_path(text)
    target = user_path if user_path else Path(context.get("workspace_dir") or Path.cwd())
    k = _extract_top_k(text, default=8)
    ext = _extract_ext(text)
    path_prefix = _extract_path_prefix(text)

    indexer = RepoIndexer(root_path=target)
    rows = indexer.search(query=query, k=k, path_prefix=path_prefix, ext=ext)
    if not rows:
        return ActionResult.ok(
            "No indexed matches found. Run 'repo index' first or adjust query filters.",
            {"query": query, "results": []},
            "repo_index_search",
        )

    lines = [f"Top {len(rows)} repo matches for: {query}"]
    for idx, row in enumerate(rows, start=1):
        rel_path = str(row.get("rel_path") or "")
        chunk_index = int(row.get("chunk_index", 0) or 0)
        score = row.get("score")
        snippet = str(row.get("content") or "").strip().replace("\n", " ")
        if len(snippet) > 140:
            snippet = snippet[:137] + "..."
        lines.append(
            f"{idx}. {rel_path} (chunk {chunk_index}, score={score})"
        )
        lines.append(f"   {snippet}")

    return ActionResult.ok(
        "\n".join(lines),
        {"query": query, "results": rows, "k": k, "path_prefix": path_prefix, "ext": ext},
        "repo_index_search",
    )


def handle_repo_index_status(text: str, context: Dict[str, Any]) -> ActionResult:
    user_path = _extract_path(text)
    target = user_path if user_path else Path(context.get("workspace_dir") or Path.cwd())
    indexer = RepoIndexer(root_path=target)
    status = indexer.status()
    lines = [
        "Repository index status:",
        f"- Root: {status.get('root_path', '')}",
        f"- Collection: {status.get('collection', '')}",
        f"- Files indexed: {status.get('files_indexed', 0)}",
        f"- Chunks indexed: {status.get('chunks_indexed', 0)}",
        f"- State file: {status.get('state_path', '')}",
    ]
    return ActionResult.ok("\n".join(lines), status, "repo_index_status")


def register_repo_index_capabilities(registry=None) -> None:
    if registry is None:
        from chintu_backend.core.capabilities import get_registry

        registry = get_registry()

    registry.register(
        Capability(
            name="repo_index_build",
            triggers=[
                "repo index",
                "index repo",
                "index codebase",
                "rebuild repo index",
            ],
            handler=handle_repo_index_build,
            requires_confirmation=False,
            description="build or refresh incremental repository index",
            capability_type=CapabilityType.DEVELOPER,
            examples=["repo index", "rebuild repo index full"],
        )
    )

    registry.register(
        Capability(
            name="repo_index_search",
            triggers=[
                "repo search",
                "search indexed repo",
                "search repo index",
            ],
            handler=handle_repo_index_search,
            requires_confirmation=False,
            description="semantic search across indexed repository chunks",
            capability_type=CapabilityType.DEVELOPER,
            examples=["repo search where is class RepoIndexer defined"],
        )
    )

    registry.register(
        Capability(
            name="repo_index_status",
            triggers=[
                "repo index status",
                "indexed repo status",
                "repo status index",
            ],
            handler=handle_repo_index_status,
            requires_confirmation=False,
            description="show repository index stats",
            capability_type=CapabilityType.DEVELOPER,
            examples=["repo index status"],
        )
    )
