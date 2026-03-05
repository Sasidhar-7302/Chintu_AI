"""Hybrid memory store (SQLite + lightweight embeddings).

This is the default memory backend for Chintu. It supports:
- durable storage in SQLite
- basic full-text search (FTS5 when available)
- lightweight vector similarity via hashing embeddings
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from chintu_backend.core.config import get_config
from .embedding import HashingEmbedder

logger = logging.getLogger(__name__)


@dataclass
class MemoryResult:
    id: int
    content: str
    score: float
    match_type: str
    created_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class EmbeddingProvider:
    """Lightweight embedder wrapper."""

    def __init__(self, dim: int = 256) -> None:
        self._embedder = HashingEmbedder(dim=dim)
        self.dim = self._embedder.dim
        self._lock = threading.Lock()

    def warmup(self) -> None:
        return None

    def embed(self, text: str) -> List[float]:
        text = (text or "").strip()
        if not text:
            return [0.0] * self.dim
        with self._lock:
            return self._embedder.embed(text)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    norm_a = sum(a[i] * a[i] for i in range(n)) ** 0.5
    norm_b = sum(b[i] * b[i] for i in range(n)) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


_instance: Optional["HybridMemoryManager"] = None


def get_hybrid_memory() -> Optional["HybridMemoryManager"]:
    return _instance


class HybridMemoryManager:
    """SQLite-backed memory with optional FTS and embeddings."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        global _instance
        self.config = get_config()
        if _instance is None:
            _instance = self

        self.db_path = Path(db_path or self.config.memory_sqlite_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._embedder = EmbeddingProvider()
        self._fts_enabled = True

        self.collection = None  # compatibility shim (ChromaDB field)

        self._init_schema()
        logger.info("HybridMemoryManager initialized at %s", self.db_path)

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    importance REAL DEFAULT 0.0,
                    tags TEXT DEFAULT '',
                    category TEXT DEFAULT 'conversation',
                    source TEXT DEFAULT 'chat',
                    archived INTEGER DEFAULT 0
                );
                """
            )
            try:
                self._conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS interactions_fts
                    USING fts5(content, content='interactions', content_rowid='id');
                    """
                )
            except Exception as exc:
                logger.warning("FTS disabled: %s", exc)
                self._fts_enabled = False

            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    id INTEGER PRIMARY KEY,
                    vector TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    FOREIGN KEY(id) REFERENCES interactions(id) ON DELETE CASCADE
                );
                """
            )

            # Evidence/artifact de-dupe table. This lets us safely index screenshots (and other
            # artifacts) into memory without re-ingesting the same file repeatedly.
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    sha256 TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    run_id TEXT DEFAULT '',
                    step_id TEXT DEFAULT '',
                    interaction_id INTEGER DEFAULT NULL
                );
                """
            )

    def _build_filter_sql(self, filters: Optional[Dict[str, Any]]) -> Tuple[str, List[Any]]:
        if not filters:
            return "", []
        clauses = []
        params = []
        for key, value in filters.items():
            if not key.replace("_", "").isalnum():
                continue
            clauses.append(f"interactions.{key} = ?")
            params.append(value)
        if not clauses:
            return "", []
        return " AND " + " AND ".join(clauses), params

    def save_interaction(
        self,
        role: str,
        content: str,
        meta: Optional[Dict[str, Any]] = None,
        category: str = "conversation",
        source: str = "chat",
    ) -> None:
        content = (content or "").strip()
        if not content:
            return
        now = datetime.utcnow().isoformat()
        importance = float((meta or {}).get("importance", 0.0))
        tags = ",".join((meta or {}).get("tags", []))

        if meta and "category" in meta:
            category = meta["category"]
        if meta and "source" in meta:
            source = meta["source"]

        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO interactions(role, content, created_at, importance, tags, category, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (role, content, now, importance, tags, category, source),
            )
            row_id = cur.lastrowid
            if self._fts_enabled:
                try:
                    self._conn.execute(
                        "INSERT INTO interactions_fts(rowid, content) VALUES (?, ?)",
                        (row_id, content),
                    )
                except Exception:
                    self._fts_enabled = False
            vec = self._embedder.embed(content)
            self._conn.execute(
                "INSERT OR REPLACE INTO embeddings(id, vector, dim) VALUES (?, ?, ?)",
                (row_id, json.dumps(vec), len(vec)),
            )
            self._conn.commit()

    def add_preference(self, key: str, value: Any) -> None:
        """Persist a user preference via the preference manager when available."""
        try:
            from .preferences import get_preference_manager

            pm = get_preference_manager()
            pm.set_preference(key, value)
        except Exception:
            # Best-effort only; ignore if preference system unavailable.
            pass

    def add_knowledge_document(self, content: str, metadata: Dict[str, Any]) -> None:
        category = metadata.get("category", "knowledge")
        source = metadata.get("source", "library")
        tags = metadata.get("tags") or []
        self.save_interaction(
            role="system",
            content=content,
            meta={"tags": tags, "importance": 1.0, "category": category, "source": source},
            category=category,
            source=source,
        )

    def has_artifact(self, sha256: str) -> bool:
        sha256 = (sha256 or "").strip()
        if not sha256:
            return False
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT 1 FROM artifacts WHERE sha256 = ? LIMIT 1;",
                    (sha256,),
                )
                return cur.fetchone() is not None
        except Exception:
            return False

    def record_artifact(
        self,
        *,
        sha256: str,
        path: str,
        kind: str,
        run_id: str = "",
        step_id: str = "",
        interaction_id: Optional[int] = None,
    ) -> None:
        sha256 = (sha256 or "").strip()
        if not sha256:
            return
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO artifacts(sha256, path, kind, created_at, run_id, step_id, interaction_id)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    sha256,
                    str(path or ""),
                    str(kind or ""),
                    now,
                    str(run_id or ""),
                    str(step_id or ""),
                    int(interaction_id) if interaction_id is not None else None,
                ),
            )
            self._conn.commit()

    def archive_by_source(self, source: str) -> int:
        if not source:
            return 0
        with self._lock:
            cur = self._conn.execute(
                "UPDATE interactions SET archived = 1 WHERE source = ?",
                (source,),
            )
            self._conn.commit()
            return cur.rowcount

    def _fts_search(
        self,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not self._fts_enabled:
            return []
        try:
            filter_sql, filter_params = self._build_filter_sql(filters)
            sql = f"""
                SELECT interactions.id, interactions.content
                FROM interactions_fts
                JOIN interactions ON interactions_fts.rowid = interactions.id
                WHERE interactions_fts MATCH ?
                AND interactions.archived = 0
                {filter_sql}
                LIMIT ?;
            """
            params = [query] + filter_params + [limit]
            cur = self._conn.execute(sql, params)
            return [{"id": row[0], "content": row[1], "score": 0.6} for row in cur.fetchall()]
        except Exception:
            return []

    def _like_search(
        self,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        try:
            filter_sql, filter_params = self._build_filter_sql(filters)
            sql = f"""
                SELECT id, content FROM interactions
                WHERE archived = 0 AND content LIKE ?
                {filter_sql}
                ORDER BY id DESC
                LIMIT ?;
            """
            params = [f"%{query}%"] + filter_params + [limit]
            cur = self._conn.execute(sql, params)
            return [{"id": row[0], "content": row[1], "score": 0.4} for row in cur.fetchall()]
        except Exception:
            return []

    def _vector_search(
        self,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        query_vec = self._embedder.embed(query)
        if not query_vec:
            return []
        filter_sql, filter_params = self._build_filter_sql(filters)
        sql = f"""
            SELECT embeddings.id, embeddings.vector
            FROM embeddings
            JOIN interactions ON embeddings.id = interactions.id
            WHERE interactions.archived = 0
            {filter_sql}
            ORDER BY interactions.id DESC
            LIMIT 500;
        """
        results: List[Dict[str, Any]] = []
        try:
            cur = self._conn.execute(sql, filter_params)
            for row_id, vec_json in cur.fetchall():
                try:
                    vec = json.loads(vec_json)
                    score = cosine_similarity(query_vec, vec)
                    if score > 0.05:
                        results.append({"id": row_id, "score": score})
                except Exception:
                    continue
        except Exception:
            return []
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def _merge_hits(
        self,
        fts_hits: List[Dict[str, Any]],
        vec_hits: List[Dict[str, Any]],
        limit: int,
    ) -> List[MemoryResult]:
        scores: Dict[int, float] = {}
        types: Dict[int, str] = {}
        all_ids = set()

        for hit in fts_hits:
            rid = int(hit["id"])
            all_ids.add(rid)
            scores[rid] = scores.get(rid, 0.0) + float(hit.get("score", 0.4))
            types[rid] = "fts"

        for hit in vec_hits:
            rid = int(hit["id"])
            all_ids.add(rid)
            scores[rid] = scores.get(rid, 0.0) + float(hit.get("score", 0.0))
            types[rid] = "hybrid" if rid in types else "vector"

        if not all_ids:
            return []

        placeholders = ",".join("?" for _ in all_ids)
        sql = f"""
            SELECT id, content, created_at, role, source, category, tags
            FROM interactions
            WHERE id IN ({placeholders})
        """
        results: List[MemoryResult] = []
        cur = self._conn.execute(sql, list(all_ids))
        for row in cur.fetchall():
            tags = [t for t in (row["tags"] or "").split(",") if t]
            results.append(
                MemoryResult(
                    id=row["id"],
                    content=row["content"],
                    score=scores.get(int(row["id"]), 0.0),
                    match_type=types.get(int(row["id"]), "unknown"),
                    created_at=row["created_at"],
                    metadata={
                        "role": row["role"],
                        "source": row["source"],
                        "category": row["category"],
                        "tags": tags,
                    },
                )
            )
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _recent(self, limit: int = 5) -> List[MemoryResult]:
        try:
            cur = self._conn.execute(
                """
                SELECT id, content, created_at, role, source, category, tags
                FROM interactions
                WHERE archived = 0
                ORDER BY id DESC
                LIMIT ?;
                """,
                (limit,),
            )
            results: List[MemoryResult] = []
            for row in cur.fetchall():
                tags = [t for t in (row["tags"] or "").split(",") if t]
                results.append(
                    MemoryResult(
                        id=row["id"],
                        content=row["content"],
                        score=0.1,
                        match_type="recent",
                        created_at=row["created_at"],
                        metadata={
                            "role": row["role"],
                            "source": row["source"],
                            "category": row["category"],
                            "tags": tags,
                        },
                    )
                )
            return results
        except Exception:
            return []

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        min_score: float = 0.0,
    ) -> List[MemoryResult]:
        query = (query or "").strip()
        if not query:
            return []
        fts_hits = self._fts_search(query, limit * 2, filters)
        if not fts_hits:
            fts_hits = self._like_search(query, limit * 2, filters)
        vec_hits = self._vector_search(query, limit * 2, filters)
        merged = self._merge_hits(fts_hits, vec_hits, limit)
        merged = [r for r in merged if r.score >= min_score]
        if merged:
            return merged[:limit]
        return self._recent(limit)

    def retrieve_context(
        self,
        query: str,
        n_results: int = 4,
        filters: Optional[Dict[str, Any]] = None,
    ) -> str:
        results = self.search(query, n_results, filters)
        if not results:
            return ""
        return "\n".join(f"- {r.content}" for r in results)

    def get_profile_context(self) -> str:
        profile_path = Path(self.config.data_dir) / "preferences.json"
        if profile_path.exists():
            try:
                data = json.loads(profile_path.read_text(encoding="utf-8"))
                return json.dumps(data, indent=2)
            except Exception:
                return ""
        return ""

    def clear_all(self) -> None:
        """Wipe all interactions and embeddings (for testing/reset)."""
        with self._lock:
            try:
                self._conn.execute("DELETE FROM interactions")
                self._conn.execute("DELETE FROM embeddings")
                if self._fts_enabled:
                    self._conn.execute("DELETE FROM interactions_fts")
                self._conn.commit()
                logger.info("HybridMemoryManager: All data cleared.")
            except Exception as e:
                logger.error("Failed to clear HybridMemoryManager: %s", e)


__all__ = [
    "MemoryResult",
    "HybridMemoryManager",
    "EmbeddingProvider",
    "get_hybrid_memory",
]
