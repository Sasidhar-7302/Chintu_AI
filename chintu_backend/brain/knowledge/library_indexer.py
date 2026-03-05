"""Curated knowledge library indexer for Chintu."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class LibraryIndexEntry:
    path: str
    sha256: str
    version: int
    title: str
    summary: str
    keywords: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    reviewed: bool = False
    updated_at: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "version": self.version,
            "title": self.title,
            "summary": self.summary,
            "keywords": list(self.keywords),
            "tags": list(self.tags),
            "sources": list(self.sources),
            "reviewed": self.reviewed,
            "updated_at": self.updated_at,
        }


class LibraryReviewStore:
    """Simple review status store for library documents."""

    def __init__(self, index_dir: Path):
        self.path = index_dir / "reviews.json"
        self._data: Dict[str, Dict[str, object]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def is_approved(self, rel_path: str) -> bool:
        entry = self._data.get(rel_path, {})
        return bool(entry.get("approved"))

    def mark_approved(self, rel_path: str, reviewer: str = "user") -> None:
        self._data[rel_path] = {
            "approved": True,
            "reviewer": reviewer,
            "approved_at": _utc_now(),
        }
        self.save()


class LibraryIndexer:
    """Indexes Chintus_Library into the hybrid memory store."""

    def __init__(self, root_dir: Path, memory_manager=None, config=None):
        self.root_dir = Path(root_dir)
        self.index_dir = self.root_dir / ".index"
        self.index_path = self.index_dir / "library_index.json"
        self.review_store = LibraryReviewStore(self.index_dir)
        self.memory_manager = memory_manager
        self.config = config

    def ensure_structure(self) -> None:
        for name in ("domains", "principles", "playbooks", "sources", ".index"):
            (self.root_dir / name).mkdir(parents=True, exist_ok=True)
        index_md = self.root_dir / "index.md"
        if not index_md.exists():
            index_md.write_text("# Chintu's Library\n\nMaster index.\n", encoding="utf-8")

    def load_index(self) -> Dict[str, LibraryIndexEntry]:
        if not self.index_path.exists():
            return {}
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        entries: Dict[str, LibraryIndexEntry] = {}
        for key, value in raw.items():
            try:
                entries[key] = LibraryIndexEntry(
                    path=value.get("path", key),
                    sha256=value.get("sha256", ""),
                    version=int(value.get("version", 1)),
                    title=value.get("title", ""),
                    summary=value.get("summary", ""),
                    keywords=list(value.get("keywords", [])),
                    tags=list(value.get("tags", [])),
                    sources=list(value.get("sources", [])),
                    reviewed=bool(value.get("reviewed", False)),
                    updated_at=value.get("updated_at", ""),
                )
            except Exception:
                continue
        return entries

    def save_index(self, entries: Dict[str, LibraryIndexEntry]) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        data = {k: v.to_dict() for k, v in entries.items()}
        self.index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def index_all(self) -> Dict[str, int]:
        self.ensure_structure()
        entries = self.load_index()
        indexed = 0
        skipped = 0
        pending = 0

        for path in self.root_dir.rglob("*.md"):
            if ".index" in path.parts:
                continue
            if "sources" in path.parts:
                continue
            if path.name.lower() == "readme.md":
                continue
            rel_path = str(path.relative_to(self.root_dir))
            outcome = self._index_file(path, rel_path, entries)
            if outcome == "indexed":
                indexed += 1
            elif outcome == "pending":
                pending += 1
            else:
                skipped += 1

        self.save_index(entries)
        return {"indexed": indexed, "skipped": skipped, "pending": pending}

    def _index_file(self, path: Path, rel_path: str, entries: Dict[str, LibraryIndexEntry]) -> str:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            return "skipped"

        frontmatter, body = _split_frontmatter(raw)
        meta = _parse_frontmatter(frontmatter)
        reviewed = bool(meta.get("reviewed")) or str(meta.get("status", "")).lower() in {"approved", "reviewed"}
        reviewed = reviewed or self.review_store.is_approved(rel_path)

        sources = _normalize_list(meta.get("sources") or meta.get("citations") or [])
        min_sources = int(getattr(self.config, "library_min_sources", 1)) if self.config else 1
        require_sources = bool(getattr(self.config, "library_require_sources", True)) if self.config else True
        allow_unreviewed = bool(getattr(self.config, "library_allow_unreviewed", False)) if self.config else False

        if require_sources and len(sources) < min_sources:
            _log_audit("library_pending", {"path": rel_path, "reason": "missing_sources"})
            return "pending"
        if not reviewed and not allow_unreviewed:
            _log_audit("library_pending", {"path": rel_path, "reason": "unreviewed"})
            return "pending"

        content = body.strip()
        if not content:
            return "skipped"

        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        prev = entries.get(rel_path)
        if prev and prev.sha256 == digest:
            return "skipped"

        title = meta.get("title") or _infer_title(content) or path.stem
        summary = meta.get("summary") or _extract_summary(content)
        keywords = _extract_keywords(content, meta.get("tags") or [])
        tags = _derive_tags(rel_path, meta.get("tags") or [])
        tags.extend([f"src:{src}" for src in sources[:8]])
        tags.append(f"file:{rel_path}")

        version = (prev.version + 1) if prev else 1
        entries[rel_path] = LibraryIndexEntry(
            path=rel_path,
            sha256=digest,
            version=version,
            title=title,
            summary=summary,
            keywords=keywords,
            tags=tags,
            sources=sources,
            reviewed=reviewed,
            updated_at=_utc_now(),
        )

        if self.memory_manager:
            try:
                annotated = content
                if sources:
                    annotated = f"{content}\n\nSources:\n" + "\n".join(f"- {s}" for s in sources)
                self.memory_manager.add_knowledge_document(
                    content=annotated,
                    metadata={
                        "tags": tags,
                        "importance": 1.0,
                        "category": "library",
                        "source": "library",
                    },
                )
            except Exception:
                pass

        try:
            from chintu_backend.canvas import get_canvas_manager

            get_canvas_manager().add_knowledge_item(
                title=title,
                summary=summary,
                sources=sources,
                tag=tags[0] if tags else "",
            )
        except Exception:
            pass

        _log_audit("library_indexed", {"path": rel_path, "version": version, "sources": len(sources)})
        return "indexed"


def _split_frontmatter(text: str) -> Tuple[str, str]:
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return "", text
    parts = stripped.split("---", 2)
    if len(parts) < 3:
        return "", text
    return parts[1].strip(), parts[2].lstrip("\n")


def _parse_frontmatter(frontmatter: str) -> Dict[str, object]:
    if not frontmatter:
        return {}
    try:
        import yaml

        data = yaml.safe_load(frontmatter)
        return data or {}
    except Exception:
        return {}


def _normalize_list(value) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,\n]", value) if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _infer_title(content: str) -> str:
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def _extract_summary(content: str, max_chars: int = 400) -> str:
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if not paragraphs:
        return content[:max_chars]
    summary = paragraphs[0]
    return summary[:max_chars]


def _extract_keywords(content: str, tags: List[str]) -> List[str]:
    keywords = set()
    for tag in _normalize_list(tags):
        keywords.add(tag.lower())
    for line in content.splitlines():
        if line.strip().startswith("#"):
            keywords.add(line.strip().lstrip("#").strip().lower())
    words = re.findall(r"[a-zA-Z]{4,}", content.lower())
    stop = {"this", "that", "with", "from", "were", "have", "will", "your", "about"}
    for word in words[:200]:
        if word not in stop:
            keywords.add(word)
        if len(keywords) >= 25:
            break
    return sorted(keywords)


def _derive_tags(rel_path: str, tags: List[str]) -> List[str]:
    derived = []
    parts = Path(rel_path).parts
    if parts:
        derived.append(f"section:{parts[0]}")
    if len(parts) > 1:
        derived.append(f"domain:{parts[1]}")
    if len(parts) > 2:
        derived.append(f"topic:{parts[2]}")
    derived.extend(_normalize_list(tags))
    return [t.strip() for t in derived if t.strip()]


def _log_audit(event: str, payload: Dict[str, object]) -> None:
    try:
        from chintu_backend.audit import log_event

        log_event(event, payload)
    except Exception:
        pass
