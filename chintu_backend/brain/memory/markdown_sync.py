"""Two-way Markdown <-> vector memory sync for a glass-box memory layer."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from chintu_backend.core.config import get_config
from chintu_backend.core.state import get_state_manager

logger = logging.getLogger(__name__)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


@dataclass
class MarkdownSyncState:
    file_path: str
    mtime: float
    content_hash: str


class MarkdownMemorySync:
    """Sync Markdown files into ChromaDB for inspectable, editable memory."""

    def __init__(self, memory_manager) -> None:
        self.config = get_config()
        self.state_manager = get_state_manager()
        self.memory_manager = memory_manager

        base_dir = getattr(self.config, "memory_markdown_dir", None)
        self.brain_dir: Path = Path(base_dir) if base_dir else (self.config.data_dir / "brain_md")
        self.brain_dir.mkdir(parents=True, exist_ok=True)

        self._state_path = self.brain_dir / ".sync_state.json"
        self._state: Dict[str, MarkdownSyncState] = {}

        self._interval_seconds = float(
            getattr(self.config, "memory_markdown_sync_interval_seconds", 60.0)
        )
        self._chunk_lines = int(getattr(self.config, "memory_markdown_chunk_lines", 28))
        self._max_chunk_chars = int(getattr(self.config, "memory_markdown_max_chunk_chars", 2400))

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        self._load_state()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> Tuple[bool, str]:
        if not getattr(self.config, "memory_markdown_sync_enabled", False):
            self.state_manager.update_feature("memory_markdown_sync", enabled=False, status="inactive")
            return False, "Markdown sync disabled in config"
        has_collection = bool(getattr(self.memory_manager, "collection", None))
        has_hybrid = hasattr(self.memory_manager, "save_interaction")
        if not (has_collection or has_hybrid):
            self.state_manager.update_feature(
                "memory_markdown_sync",
                enabled=False,
                status="inactive",
                error="memory_unavailable",
            )
            return False, "Memory backend unavailable"
        if self._running:
            return True, "Markdown sync already running"

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="MarkdownMemorySync")
        self._thread.start()
        self._running = True
        self.state_manager.update_feature("memory_markdown_sync", enabled=True, status="active", error=None)

        # Prime an initial sync quickly.
        try:
            self.sync_once()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Initial markdown sync failed: %s", exc)

        return True, f"Markdown sync started ({self.brain_dir})"

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._running = False
        try:
            self.state_manager.update_feature("memory_markdown_sync", status="inactive")
        except Exception:
            pass

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.sync_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Markdown sync loop error: %s", exc)
                self.state_manager.update_feature(
                    "memory_markdown_sync", status="testing", error=str(exc)[:200]
                )
            self._stop_event.wait(self._interval_seconds)

    # ------------------------------------------------------------------
    # Public sync helpers
    # ------------------------------------------------------------------
    def sync_once(self) -> Dict[str, int]:
        collection = getattr(self.memory_manager, "collection", None)
        if not collection and not hasattr(self.memory_manager, "save_interaction"):
            return {"synced": 0, "skipped": 0}

        synced = 0
        skipped = 0
        for path in sorted(self.brain_dir.glob("*.md")):
            try:
                did_sync = self._sync_file_if_needed(path)
                if did_sync:
                    synced += 1
                else:
                    skipped += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("Markdown sync failed for %s: %s", path, exc)
        if synced:
            self.state_manager.update_feature("memory_markdown_sync", status="active", error=None)
        self._save_state()
        return {"synced": synced, "skipped": skipped}

    def append_fact(self, fact: str, file_name: str = "Personal.md") -> bool:
        """Append a remembered fact to Markdown and sync it immediately."""
        fact = (fact or "").strip()
        if not fact:
            return False
        path = self.brain_dir / file_name
        try:
            self._ensure_heading(path, "# Personal Memory")
            timestamp = time.strftime("%Y-%m-%d %H:%M")
            line = f"- [{timestamp}] {fact}\n"
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
            # Force sync for the updated file.
            self._sync_file(path, force=True)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to append fact to markdown: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal sync logic
    # ------------------------------------------------------------------
    def _sync_file_if_needed(self, path: Path) -> bool:
        state = self._state.get(str(path))
        mtime = path.stat().st_mtime
        if state and mtime <= state.mtime:
            return False
        return self._sync_file(path, force=False)

    def _sync_file(self, path: Path, force: bool) -> bool:
        collection = getattr(self.memory_manager, "collection", None)
        if not collection and hasattr(self.memory_manager, "save_interaction"):
            return self._sync_file_hybrid(path, force)
        if not collection:
            return False

        content = path.read_text(encoding="utf-8", errors="ignore")
        content_hash = _hash_text(content)
        mtime = path.stat().st_mtime
        prev = self._state.get(str(path))
        if not force and prev and prev.content_hash == content_hash:
            prev.mtime = mtime
            return False

        # Delete previous chunks for this file.
        try:
            collection.delete(where={"source": "markdown_sync", "file": path.name})
        except Exception:
            # Best-effort cleanup; duplicates are acceptable over failures.
            pass

        chunks = self._chunk_markdown(content)
        if not chunks:
            self._state[str(path)] = MarkdownSyncState(str(path), mtime, content_hash)
            return False

        ids: List[str] = []
        docs: List[str] = []
        metas: List[Dict[str, object]] = []
        for i, chunk in enumerate(chunks):
            ids.append(f"mdsync:{path.stem}:{i}:{content_hash[:10]}")
            docs.append(chunk)
            metas.append(
                {
                    "role": "markdown",
                    "source": "markdown_sync",
                    "file": path.name,
                    "chunk_index": i,
                    "content_hash": content_hash[:16],
                    "timestamp": time.time(),
                }
            )

        collection.add(documents=docs, metadatas=metas, ids=ids)

        # Invalidate memory query cache if present.
        try:
            cache = getattr(self.memory_manager, "_query_cache", None)
            if cache:
                cache.invalidate()
        except Exception:
            pass

        self._state[str(path)] = MarkdownSyncState(str(path), mtime, content_hash)
        logger.info("Markdown memory synced: %s (%d chunks)", path.name, len(chunks))
        return True

    def _sync_file_hybrid(self, path: Path, force: bool) -> bool:
        """Sync Markdown into HybridMemory (SQLite+embeddings)."""
        content = path.read_text(encoding="utf-8", errors="ignore")
        content_hash = _hash_text(content)
        mtime = path.stat().st_mtime
        prev = self._state.get(str(path))
        if not force and prev and prev.content_hash == content_hash:
            prev.mtime = mtime
            return False

        # Archive previous chunks for this file (best effort)
        source_key = f"markdown_sync:{path.name}"
        try:
            if hasattr(self.memory_manager, "archive_by_source"):
                self.memory_manager.archive_by_source(source_key)
        except Exception:
            pass

        chunks = self._chunk_markdown(content)
        if not chunks:
            self._state[str(path)] = MarkdownSyncState(str(path), mtime, content_hash)
            return False

        for i, chunk in enumerate(chunks):
            meta = {
                "category": "knowledge",
                "source": source_key,
                "tags": [path.stem, path.name, f"chunk:{i}"],
                "importance": 0.6,
            }
            try:
                self.memory_manager.save_interaction("markdown", chunk, meta=meta, category="knowledge", source=source_key)
            except Exception:
                # Continue syncing remaining chunks
                pass

        try:
            cache = getattr(self.memory_manager, "_cache", None)
            if cache:
                cache.clear()
        except Exception:
            pass

        self._state[str(path)] = MarkdownSyncState(str(path), mtime, content_hash)
        logger.info("Markdown memory synced (hybrid): %s (%d chunks)", path.name, len(chunks))
        return True

    def _chunk_markdown(self, content: str) -> List[str]:
        lines = content.splitlines()
        if not lines:
            return []
        chunks: List[str] = []
        buf: List[str] = []

        def flush() -> None:
            if not buf:
                return
            chunk = "\n".join(buf).strip()
            if chunk:
                chunks.append(chunk[: self._max_chunk_chars])
            buf.clear()

        for line in lines:
            is_heading = line.lstrip().startswith("#")
            buf.append(line)
            too_long = sum(len(x) + 1 for x in buf) > self._max_chunk_chars
            too_many = len(buf) >= self._chunk_lines
            if is_heading and len(buf) > 1:
                # Prefer to break at headings for semantic chunks.
                last = buf.pop()
                flush()
                buf.append(last)
                continue
            if too_long or too_many:
                flush()
        flush()
        return chunks

    # ------------------------------------------------------------------
    # State + file helpers
    # ------------------------------------------------------------------
    def _ensure_heading(self, path: Path, heading: str) -> None:
        if not path.exists():
            path.write_text(f"{heading}\n\n", encoding="utf-8")
            return
        content = path.read_text(encoding="utf-8", errors="ignore")
        if heading.lower() in content.lower():
            return
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n{heading}\n\n")

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        for path, data in raw.items():
            try:
                self._state[path] = MarkdownSyncState(
                    file_path=path,
                    mtime=float(data.get("mtime") or 0.0),
                    content_hash=str(data.get("content_hash") or ""),
                )
            except Exception:
                continue

    def _save_state(self) -> None:
        try:
            serializable = {
                path: {"mtime": s.mtime, "content_hash": s.content_hash} for path, s in self._state.items()
            }
            self._state_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
        except Exception:
            pass


_sync: Optional[MarkdownMemorySync] = None


def get_markdown_sync(memory_manager=None) -> Optional[MarkdownMemorySync]:
    """Get or create the global markdown sync service."""
    global _sync
    if _sync is None:
        if memory_manager is None:
            return None
        _sync = MarkdownMemorySync(memory_manager=memory_manager)
    return _sync

