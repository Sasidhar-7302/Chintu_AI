"""Hybrid memory store (SQLite + FTS + embeddings)."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class EmbeddingProvider:
    def __init__(self):
        self._model = None
        self._dim = 128
        self._lock = threading.Lock()

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            self._dim = int(self._model.get_sentence_embedding_dimension())
        except Exception as exc:
            logger.warning("SentenceTransformer unavailable, using hash embeddings: %s", exc)
            self._model = None
            self._dim = 128

    def embed(self, text: str) -> List[float]:
        text = (text or "").strip()
        if not text:
            return [0.0] * self._dim
        with self._lock:
            self._load_model()
            if self._model:
                vec = self._model.encode([text], normalize_embeddings=True)[0]
                return [float(x) for x in vec]
        return self._hash_embed(text)

    def _hash_embed(self, text: str) -> List[float]:
        # Simple hashing trick for fallback embeddings
        vec = [0.0] * self._dim
        for token in text.lower().split():
            idx = abs(hash(token)) % self._dim
            vec[idx] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


class LRUCache:
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self._data: Dict[str, str] = {}
        self._order: List[str] = []
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            if key not in self._data:
                return None
            self._order.remove(key)
            self._order.append(key)
            return self._data[key]

    def set(self, key: str, value: str) -> None:
        with self._lock:
            if key in self._data:
                self._order.remove(key)
            elif len(self._order) >= self.max_size:
                oldest = self._order.pop(0)
                self._data.pop(oldest, None)
            self._data[key] = value
            self._order.append(key)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._order.clear()


class HybridMemoryManager:
    """SQLite-backed memory with FTS and embeddings."""

    def __init__(self, db_path: Optional[Path] = None):
        self.config = get_config()
        self.db_path = Path(db_path or (self.config.data_dir / "memory_hybrid.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        self._lock = threading.Lock()
        self._embedder = EmbeddingProvider()
        self._cache = LRUCache(max_size=128)
        self.collection = None  # For markdown sync compatibility (disabled)

        self._init_schema()
        self._maybe_migrate_from_chroma()
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
                    archived INTEGER DEFAULT 0
                );
                """
            )
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS interactions_fts
                USING fts5(content, content='interactions', content_rowid='id');
                """
            )
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
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _maybe_migrate_from_chroma(self) -> None:
        try:
            if not getattr(self.config, "memory_migrate_chroma", False):
                return
            if self._has_any_records():
                return
            from chintu_backend.core.memory import MemoryManager as ChromaMemoryManager

            chroma = ChromaMemoryManager(persistence_path=str(self.config.memory_store_path))
            if not chroma.collection:
                return
            results = chroma.collection.get(include=["documents", "metadatas"])
            docs = results.get("documents") or []
            metas = results.get("metadatas") or []
            for doc, meta in zip(docs, metas):
                role = (meta or {}).get("role", "assistant")
                self.save_interaction(role, doc)
            logger.info("Migrated %d memories from ChromaDB", len(docs))
        except Exception as exc:
            logger.warning("ChromaDB migration skipped: %s", exc)

    def _has_any_records(self) -> bool:
        cur = self._conn.execute("SELECT COUNT(1) FROM interactions")
        return cur.fetchone()[0] > 0

    def save_interaction(self, role: str, content: str, meta: Optional[Dict[str, Any]] = None) -> None:
        content = (content or "").strip()
        if not content:
            return
        now = datetime.now().isoformat()
        importance = float((meta or {}).get("importance", 0.0))
        tags = ",".join((meta or {}).get("tags", []))
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO interactions(role, content, created_at, importance, tags) VALUES (?, ?, ?, ?, ?)",
                (role, content, now, importance, tags),
            )
            row_id = cur.lastrowid
            self._conn.execute(
                "INSERT INTO interactions_fts(rowid, content) VALUES (?, ?)",
                (row_id, content),
            )
            vec = self._embedder.embed(content)
            self._conn.execute(
                "INSERT OR REPLACE INTO embeddings(id, vector, dim) VALUES (?, ?, ?)",
                (row_id, json.dumps(vec), len(vec)),
            )
            self._conn.commit()
        self._cache.clear()

    def retrieve_context(self, query: str, n_results: int = 4) -> str:
        query = (query or "").strip()
        if not query:
            return ""
        cache_key = f"{query}:{n_results}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        fts_hits = self._fts_search(query, n_results)
        vec_hits = self._vector_search(query, n_results)
        combined = self._merge_hits(fts_hits, vec_hits, n_results)
        context = "\n".join(f"- {hit['content']}" for hit in combined)
        self._cache.set(cache_key, context)
        return context

    def _fts_search(self, query: str, limit: int) -> List[Dict[str, Any]]:
        try:
            sql = """
                SELECT interactions.id, interactions.content, bm25(interactions_fts) as score
                FROM interactions_fts
                JOIN interactions ON interactions_fts.rowid = interactions.id
                WHERE interactions_fts MATCH ?
                AND interactions.archived = 0
                ORDER BY score
                LIMIT ?;
            """
            cur = self._conn.execute(sql, (query, limit))
            return [{"id": row[0], "content": row[1], "score": float(row[2])} for row in cur.fetchall()]
        except Exception:
            return []

    def _vector_search(self, query: str, limit: int) -> List[Dict[str, Any]]:
        query_vec = self._embedder.embed(query)
        with self._lock:
            cur = self._conn.execute(
                "SELECT embeddings.id, embeddings.vector FROM embeddings "
                "JOIN interactions ON embeddings.id = interactions.id "
                "WHERE interactions.archived = 0 "
                "ORDER BY interactions.id DESC LIMIT 2000"
            )
            results = []
            for row_id, vec_json in cur.fetchall():
                vec = json.loads(vec_json)
                score = cosine_similarity(query_vec, vec)
                results.append({"id": row_id, "score": score})
        results.sort(key=lambda x: x["score"], reverse=True)
        top = results[:limit]
        if not top:
            return []
        placeholders = ",".join("?" for _ in top)
        cur = self._conn.execute(
            f"SELECT id, content FROM interactions WHERE id IN ({placeholders})",
            [hit["id"] for hit in top],
        )
        content_map = {row[0]: row[1] for row in cur.fetchall()}
        for hit in top:
            hit["content"] = content_map.get(hit["id"], "")
        return top

    def _merge_hits(self, fts_hits: List[Dict[str, Any]], vec_hits: List[Dict[str, Any]], limit: int):
        scores: Dict[int, float] = {}
        content: Dict[int, str] = {}
        for hit in fts_hits:
            scores[hit["id"]] = scores.get(hit["id"], 0.0) + (1.0 / (1.0 + hit["score"]))
            content[hit["id"]] = hit["content"]
        for hit in vec_hits:
            scores[hit["id"]] = scores.get(hit["id"], 0.0) + hit["score"]
            content[hit["id"]] = hit["content"]
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [{"id": rid, "content": content.get(rid, ""), "score": score} for rid, score in ranked]

    def get_profile_context(self) -> str:
        profile_path = Path(self.config.data_dir) / "preferences.json"
        if profile_path.exists():
            try:
                data = json.loads(profile_path.read_text(encoding="utf-8"))
                return json.dumps(data, indent=2)
            except Exception:
                return ""
        return ""


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    norm_a = sum(a[i] * a[i] for i in range(n)) ** 0.5
    norm_b = sum(b[i] * b[i] for i in range(n)) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
