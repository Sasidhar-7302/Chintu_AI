"""Knowledge Updater (Phase 13.5): local news/model ingestion + retrieval-friendly store."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from chintu_backend.core.config import get_config
from chintu_backend.core.model_catalog import get_model_catalog_updater
from chintu_backend.search.news_quality import extract_domain, rank_news_results
from chintu_backend.search.web_search import get_search_engine
from chintu_backend.automation.web.url_reader import get_url_reader


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _safe_text(value: Any, max_chars: int = 600) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _tokenize(text: str) -> List[str]:
    return [tok for tok in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(tok) >= 2]


@dataclass
class KnowledgeItem:
    item_id: str
    kind: str
    category: str
    title: str
    summary: str
    url: str
    source: str
    published_at: str
    ingested_at: str
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "kind": self.kind,
            "category": self.category,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "ingested_at": self.ingested_at,
            "score": self.score,
            "freshness_label": self.freshness_label,
        }

    @property
    def freshness_label(self) -> str:
        ts = _parse_iso(self.published_at) or _parse_iso(self.ingested_at)
        if not ts:
            return "recent"
        delta = _utc_now() - ts
        hours = max(int(delta.total_seconds() // 3600), 0)
        if hours < 1:
            return "<1h"
        if hours < 24:
            return f"{hours}h"
        days = max(int(hours // 24), 1)
        return f"{days}d"


class KnowledgeUpdater:
    """Local-first knowledge ingestion with vector search fallback."""

    def __init__(
        self,
        *,
        store_dir: Optional[Path] = None,
        search_engine=None,
        model_catalog_updater=None,
    ) -> None:
        cfg = get_config()
        self.config = cfg
        root = store_dir or getattr(cfg, "knowledge_store_dir", None) or (cfg.data_dir / "knowledge_updater")
        self.store_dir = Path(root)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.store_dir / "knowledge.sqlite3"
        self.vector_path = self.store_dir / "chroma"
        self.search_engine = search_engine or get_search_engine()
        self.model_catalog_updater = model_catalog_updater or get_model_catalog_updater()
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()
        self._chroma_collection = self._init_chroma_collection()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_items (
                item_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                url TEXT,
                source TEXT,
                published_at TEXT,
                ingested_at TEXT NOT NULL,
                dedup_key TEXT UNIQUE NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_digests (
                digest_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                categories_json TEXT NOT NULL,
                item_ids_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_item_expansions (
                item_id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                citations_json TEXT NOT NULL,
                expanded_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_article_archives (
                item_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT,
                source TEXT,
                category TEXT,
                reason TEXT,
                text_content TEXT NOT NULL,
                html_content TEXT,
                text_chars INTEGER NOT NULL,
                html_chars INTEGER NOT NULL,
                archived_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_category_ingested ON knowledge_items(category, ingested_at DESC)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_kind_ingested ON knowledge_items(kind, ingested_at DESC)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_archive_archived_at ON knowledge_article_archives(archived_at DESC)"
        )
        self._conn.commit()

    def _init_chroma_collection(self):
        backend = str(getattr(self.config, "knowledge_vector_backend", "chroma") or "chroma").lower()
        if backend != "chroma":
            return None
        try:
            import chromadb  # type: ignore
            from chromadb.utils import embedding_functions  # type: ignore
        except Exception:
            return None
        try:
            client = chromadb.PersistentClient(path=str(self.vector_path))
            ef = embedding_functions.DefaultEmbeddingFunction()
            return client.get_or_create_collection(
                name=str(getattr(self.config, "knowledge_chroma_collection", "knowledge_updates")),
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            return None

    def ingest_daily_updates(
        self,
        *,
        categories: Optional[Sequence[str]] = None,
        max_per_category: Optional[int] = None,
        include_model_releases: bool = True,
    ) -> Dict[str, Any]:
        cats = [str(c).strip().lower() for c in (categories or ["tech", "finance", "healthcare"]) if str(c).strip()]
        if not cats:
            cats = ["tech", "finance", "healthcare"]
        per_cat = int(max_per_category or getattr(self.config, "knowledge_daily_fetch_per_category", 8) or 8)
        per_cat = max(2, min(per_cat, 25))

        ingested: List[KnowledgeItem] = []
        for category in cats:
            ingested.extend(self._ingest_news_for_category(category, limit=per_cat))

        if include_model_releases and bool(getattr(self.config, "knowledge_include_model_releases", True)):
            ingested.extend(self._ingest_model_release_updates(limit=per_cat))

        self._index_items_to_chroma(ingested)
        return {
            "ok": True,
            "ingested_count": len(ingested),
            "categories": cats,
            "vector_backend": "chroma" if self._chroma_collection is not None else "sqlite_lexical",
        }

    def build_daily_digest(
        self,
        *,
        total: int = 20,
        categories: Optional[Sequence[str]] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        total = max(1, min(int(total), 60))
        cats = [str(c).strip().lower() for c in (categories or ["tech", "finance", "healthcare"]) if str(c).strip()]
        if not cats:
            cats = ["tech", "finance", "healthcare"]
        weight_map = dict(weights or {})
        for cat in cats:
            weight_map.setdefault(cat, 1.0)

        # Ensure fresh data exists before digesting.
        self.ingest_daily_updates(categories=cats, include_model_releases=True)

        allocation = self._allocate_counts(cats, weight_map, total=total)
        selected: List[KnowledgeItem] = []
        seen: set[str] = set()
        for cat in cats:
            rows = self._recent_items(categories=[cat], limit=max(3, allocation.get(cat, 3) * 2))
            rows = self._filter_digest_candidates(rows, category=cat)
            for row in rows:
                if row.item_id in seen:
                    continue
                seen.add(row.item_id)
                selected.append(row)
                if sum(1 for item in selected if item.category == cat) >= allocation.get(cat, 0):
                    break

        if len(selected) < total:
            pool = self._recent_items(categories=None, limit=max(30, total * 3))
            pool = self._filter_digest_candidates(pool, category=None)
            for row in pool:
                if row.item_id in seen:
                    continue
                seen.add(row.item_id)
                selected.append(row)
                if len(selected) >= total:
                    break

        selected = selected[:total]
        digest_id = f"digest_{uuid.uuid4().hex[:12]}"
        self._conn.execute(
            "INSERT OR REPLACE INTO knowledge_digests(digest_id, created_at, categories_json, item_ids_json) VALUES (?, ?, ?, ?)",
            (
                digest_id,
                _utc_now_iso(),
                json.dumps(cats, ensure_ascii=True),
                json.dumps([item.item_id for item in selected], ensure_ascii=True),
            ),
        )
        self._conn.commit()
        return {
            "digest_id": digest_id,
            "created_at_utc": _utc_now_iso(),
            "items": [item.to_dict() for item in selected],
        }

    def ingest_external_item(
        self,
        *,
        category: str,
        title: str,
        summary: str,
        url: str = "",
        source: str = "external",
        kind: str = "external_note",
        published_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ingest external content (e.g., Telegram inbox extraction) into knowledge storage."""
        item = self._upsert_item(
            kind=_safe_text(kind or "external_note", max_chars=80),
            category=_safe_text(category or "general", max_chars=80).lower(),
            title=_safe_text(title or "Untitled item", max_chars=300),
            summary=_safe_text(summary or "", max_chars=1200),
            url=_safe_text(url or "", max_chars=700),
            source=_safe_text(source or "external", max_chars=120),
            published_at=_safe_text(published_at or _utc_now_iso(), max_chars=120),
        )
        if item is None:
            return {"ok": False, "message": "Failed to ingest external item."}
        self._index_items_to_chroma([item])
        return {"ok": True, "item": item.to_dict()}

    def expand_digest_item(self, digest_id: str, index: int) -> Dict[str, Any]:
        items = self._load_digest_items(digest_id)
        if not items:
            return {"ok": False, "error": "digest_not_found"}
        idx = int(index) - 1
        if idx < 0 or idx >= len(items):
            return {"ok": False, "error": "index_out_of_range"}

        item = items[idx]
        cached = self._get_cached_expansion(item.item_id)
        if cached:
            return {
                "ok": True,
                "item": item.to_dict(),
                "summary": str(cached.get("summary") or "").strip(),
                "citations": list(cached.get("citations") or []),
                "cached": True,
            }

        related = self.search(query=item.title, limit=4, categories=[item.category])
        citations = [
            {
                "title": row.get("title", ""),
                "source": row.get("source", ""),
                "url": row.get("url", ""),
            }
            for row in related
            if row.get("url")
        ][:3]
        summary = self._grounded_summary(item=item, related=related)
        self._store_item_expansion(item.item_id, summary=summary, citations=citations)
        return {
            "ok": True,
            "item": item.to_dict(),
            "summary": summary,
            "citations": citations,
            "cached": False,
        }

    def search(self, *, query: str, limit: int = 5, categories: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        query = str(query or "").strip()
        if not query:
            return []
        limit = max(1, min(int(limit), 25))
        categories_norm = [str(c).strip().lower() for c in (categories or []) if str(c).strip()]

        # Vector route when available.
        if self._chroma_collection is not None:
            try:
                result = self._chroma_collection.query(query_texts=[query], n_results=limit)
                ids = (result.get("ids") or [[]])[0]
                metas = (result.get("metadatas") or [[]])[0]
                rows: List[Dict[str, Any]] = []
                for idx, item_id in enumerate(ids):
                    if not item_id:
                        continue
                    row = self._get_item_by_id(str(item_id))
                    if not row:
                        continue
                    if categories_norm and row.category not in categories_norm:
                        continue
                    score = 1.0
                    meta = metas[idx] if idx < len(metas) and isinstance(metas[idx], dict) else {}
                    if meta and "score" in meta:
                        try:
                            score = float(meta["score"])
                        except Exception:
                            score = 1.0
                    payload = row.to_dict()
                    payload["score"] = score
                    rows.append(payload)
                if rows:
                    return rows[:limit]
            except Exception:
                pass

        # Lexical fallback route.
        candidates = self._recent_items(categories=categories_norm or None, limit=max(80, limit * 20))
        q_tokens = set(_tokenize(query))
        scored: List[Dict[str, Any]] = []
        for row in candidates:
            text_tokens = set(_tokenize(f"{row.title} {row.summary} {row.source}"))
            overlap = len(q_tokens.intersection(text_tokens))
            if overlap <= 0:
                continue
            score = overlap / max(len(q_tokens), 1)
            payload = row.to_dict()
            payload["score"] = round(float(score), 4)
            scored.append(payload)
        scored.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return scored[:limit]

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            return

    def archive_item_content(
        self,
        item: Dict[str, Any],
        *,
        reason: str = "liked",
        include_html: Optional[bool] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Archive full article text (and optional html) for a news item."""
        if not bool(getattr(self.config, "knowledge_archive_enabled", True)):
            return {"ok": False, "error": "archive_disabled"}

        row = dict(item or {})
        item_id = str(row.get("item_id") or "").strip()
        url = str(row.get("url") or "").strip()
        title = str(row.get("title") or "Untitled").strip() or "Untitled"
        source = str(row.get("source") or extract_domain(url) or "").strip()
        category = str(row.get("category") or "").strip().lower()
        if not item_id:
            dedup_key = hashlib.sha1(f"{title}|{url}|{source}".encode("utf-8")).hexdigest()
            item_id = f"archive_{dedup_key[:16]}"

        if not force_refresh:
            existing = self._conn.execute(
                "SELECT text_chars, html_chars, archived_at FROM knowledge_article_archives WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            if existing:
                return {
                    "ok": True,
                    "item_id": item_id,
                    "cached": True,
                    "text_chars": int(existing["text_chars"] or 0),
                    "html_chars": int(existing["html_chars"] or 0),
                    "archived_at": str(existing["archived_at"] or ""),
                }

        text_content = ""
        html_content = ""
        fetch_error = ""
        if url:
            try:
                reader = get_url_reader()
                text_content, _meta = reader.fetch(url)
            except Exception as exc:
                fetch_error = str(exc)
            include_html_value = bool(
                getattr(self.config, "knowledge_archive_include_html", False)
                if include_html is None
                else include_html
            )
            if include_html_value:
                try:
                    import requests  # type: ignore

                    response = requests.get(url, timeout=12, headers={"User-Agent": "Chintu/1.0"})
                    response.raise_for_status()
                    html_content = str(response.text or "")
                except Exception:
                    html_content = ""

        if not text_content:
            text_content = str(row.get("summary") or title).strip()

        max_text = int(getattr(self.config, "knowledge_archive_max_text_chars", 120000) or 120000)
        max_html = int(getattr(self.config, "knowledge_archive_max_html_chars", 120000) or 120000)
        text_content = str(text_content or "")[:max(2000, max_text)]
        html_content = str(html_content or "")[:max(2000, max_html)]
        text_chars = len(text_content)
        html_chars = len(html_content)

        self._conn.execute(
            """
            INSERT OR REPLACE INTO knowledge_article_archives(
                item_id, title, url, source, category, reason, text_content, html_content, text_chars, html_chars, archived_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                title,
                url,
                source,
                category,
                str(reason or "liked"),
                text_content,
                html_content,
                text_chars,
                html_chars,
                _utc_now_iso(),
            ),
        )
        self._conn.commit()
        return {
            "ok": True,
            "item_id": item_id,
            "cached": False,
            "text_chars": text_chars,
            "html_chars": html_chars,
            "fetch_error": fetch_error,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _ingest_news_for_category(self, category: str, limit: int) -> List[KnowledgeItem]:
        if not getattr(self.search_engine, "is_available", False):
            return []
        queries = self._news_queries_for_category(category)
        seen = set()
        inserted: List[KnowledgeItem] = []
        max_age_hours = int(getattr(self.config, "knowledge_news_max_age_hours", 48) or 48)
        min_reliability = float(getattr(self.config, "knowledge_news_min_reliability", 0.58) or 0.58)
        fallback_min_reliability = float(
            getattr(self.config, "knowledge_news_fallback_min_reliability", 0.35) or 0.35
        )
        extra_trusted_domains = list(getattr(self.config, "knowledge_news_extra_trusted_domains", []) or [])
        all_rows: List[Any] = []
        for query in queries:
            all_rows.extend(self.search_engine.search_news(query, max_results=max(10, limit * 3), timelimit="d"))

        ranked = rank_news_results(
            all_rows,
            category=category,
            limit=max(8, limit * 4),
            max_age_hours=max_age_hours,
            min_reliability=min_reliability,
            fallback_min_reliability=fallback_min_reliability,
            extra_trusted_domains=extra_trusted_domains,
        )
        for row in ranked:
            title = _safe_text(row.get("title"), max_chars=300)
            if not title:
                continue
            key = _normalize_title(title)
            if key in seen:
                continue
            seen.add(key)
            item = self._upsert_item(
                kind="news",
                category=category,
                title=title,
                summary=_safe_text(row.get("snippet"), max_chars=500),
                url=_safe_text(row.get("url"), max_chars=600),
                source=_safe_text(row.get("source") or row.get("domain") or "news", max_chars=120),
                published_at=_safe_text(row.get("published_at"), max_chars=120),
            )
            if item:
                inserted.append(item)
            if len(inserted) >= limit:
                return inserted
        return inserted

    def _ingest_model_release_updates(self, limit: int = 8) -> List[KnowledgeItem]:
        try:
            snapshot = self.model_catalog_updater.build_snapshot(fetch_releases=True)
        except Exception:
            return []
        releases = list(snapshot.get("release_updates") or [])
        inserted: List[KnowledgeItem] = []
        for row in releases[: max(1, limit)]:
            if not isinstance(row, dict):
                continue
            title = _safe_text(row.get("title"), max_chars=300)
            if not title:
                continue
            item = self._upsert_item(
                kind="model_release",
                category="tech",
                title=title,
                summary=_safe_text(row.get("published") or "Model/tool release update", max_chars=500),
                url=_safe_text(row.get("url"), max_chars=600),
                source=_safe_text(
                    extract_domain(
                        _safe_text(row.get("url"), max_chars=600),
                        _safe_text(row.get("source"), max_chars=120),
                    )
                    or _safe_text(row.get("source"), max_chars=120),
                    max_chars=120,
                ),
                published_at=_safe_text(row.get("published"), max_chars=120),
            )
            if item:
                inserted.append(item)
        return inserted

    def _upsert_item(
        self,
        *,
        kind: str,
        category: str,
        title: str,
        summary: str,
        url: str,
        source: str,
        published_at: str,
    ) -> Optional[KnowledgeItem]:
        dedup_seed = f"{_normalize_title(title)}::{url.strip().lower()}::{category}"
        dedup_key = hashlib.sha256(dedup_seed.encode("utf-8")).hexdigest()
        existing = self._conn.execute(
            "SELECT item_id FROM knowledge_items WHERE dedup_key = ?",
            (dedup_key,),
        ).fetchone()
        if existing:
            self._conn.execute(
                "UPDATE knowledge_items SET summary = ?, source = ?, published_at = ?, ingested_at = ? WHERE dedup_key = ?",
                (summary, source, published_at, _utc_now_iso(), dedup_key),
            )
            self._conn.commit()
            return self._get_item_by_id(str(existing["item_id"]))

        item_id = f"ku_{uuid.uuid4().hex[:16]}"
        self._conn.execute(
            """
            INSERT INTO knowledge_items(item_id, kind, category, title, summary, url, source, published_at, ingested_at, dedup_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                kind,
                category,
                title,
                summary,
                url,
                source,
                published_at,
                _utc_now_iso(),
                dedup_key,
            ),
        )
        self._conn.commit()
        return self._get_item_by_id(item_id)

    def _index_items_to_chroma(self, items: Sequence[KnowledgeItem]) -> None:
        if self._chroma_collection is None or not items:
            return
        ids = [item.item_id for item in items]
        docs = [f"{item.title}\n\n{item.summary}".strip() for item in items]
        metas = [{"category": item.category, "kind": item.kind, "source": item.source} for item in items]
        try:
            self._chroma_collection.upsert(ids=ids, documents=docs, metadatas=metas)
        except Exception:
            try:
                self._chroma_collection.add(ids=ids, documents=docs, metadatas=metas)
            except Exception:
                return

    def _recent_items(self, *, categories: Optional[Sequence[str]], limit: int = 50) -> List[KnowledgeItem]:
        max_age_hours = int(getattr(self.config, "knowledge_digest_max_age_hours", 72) or 72)
        cutoff = (_utc_now() - timedelta(hours=max(1, max_age_hours))).isoformat().replace("+00:00", "Z")
        if categories:
            placeholders = ",".join(["?"] * len(categories))
            rows = self._conn.execute(
                f"""
                SELECT * FROM knowledge_items
                WHERE category IN ({placeholders}) AND ingested_at >= ?
                ORDER BY ingested_at DESC
                LIMIT ?
                """,
                tuple([*categories, cutoff, int(limit)]),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM knowledge_items
                WHERE ingested_at >= ?
                ORDER BY ingested_at DESC
                LIMIT ?
                """,
                (cutoff, int(limit)),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def _filter_digest_candidates(
        self,
        rows: Sequence[KnowledgeItem],
        *,
        category: Optional[str],
    ) -> List[KnowledgeItem]:
        if not rows:
            return []
        if category is None:
            grouped: Dict[str, List[KnowledgeItem]] = {}
            for row in rows:
                grouped.setdefault(str(row.category or "general"), []).append(row)
            merged: List[KnowledgeItem] = []
            for cat, cat_rows in grouped.items():
                merged.extend(self._filter_digest_candidates(cat_rows, category=cat))
            merged.sort(
                key=lambda item: _parse_iso(item.published_at) or _parse_iso(item.ingested_at) or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            return merged

        max_age_hours = int(getattr(self.config, "knowledge_news_max_age_hours", 48) or 48)
        min_reliability = float(getattr(self.config, "knowledge_news_min_reliability", 0.58) or 0.58)
        fallback_min_reliability = float(
            getattr(self.config, "knowledge_news_fallback_min_reliability", 0.35) or 0.35
        )
        extra_trusted_domains = list(getattr(self.config, "knowledge_news_extra_trusted_domains", []) or [])

        row_map: Dict[str, KnowledgeItem] = {}
        ranked_source: List[Dict[str, Any]] = []
        for row in rows:
            key = f"{_normalize_title(row.title)}::{row.url.strip().lower()}"
            row_map[key] = row
            ranked_source.append(
                {
                    "title": row.title,
                    "snippet": row.summary,
                    "url": row.url,
                    "source": row.source,
                    "published_at": row.published_at,
                }
            )

        ranked = rank_news_results(
            ranked_source,
            category=str(category),
            limit=len(rows),
            max_age_hours=max_age_hours,
            min_reliability=min_reliability,
            fallback_min_reliability=fallback_min_reliability,
            extra_trusted_domains=extra_trusted_domains,
        )
        if not ranked:
            return []

        out: List[KnowledgeItem] = []
        for item in ranked:
            key = f"{_normalize_title(str(item.get('title') or ''))}::{str(item.get('url') or '').strip().lower()}"
            row = row_map.get(key)
            if row:
                out.append(row)
        return out

    def _load_digest_items(self, digest_id: str) -> List[KnowledgeItem]:
        row = self._conn.execute(
            "SELECT item_ids_json FROM knowledge_digests WHERE digest_id = ?",
            (digest_id,),
        ).fetchone()
        if not row:
            return []
        try:
            item_ids = json.loads(row["item_ids_json"])
        except Exception:
            return []
        out: List[KnowledgeItem] = []
        for item_id in item_ids:
            item = self._get_item_by_id(str(item_id))
            if item:
                out.append(item)
        return out

    def _get_cached_expansion(self, item_id: str, *, max_age_hours: int = 336) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT summary, citations_json, expanded_at FROM knowledge_item_expansions WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if not row:
            return None
        expanded_at = _parse_iso(str(row["expanded_at"] or ""))
        if expanded_at is not None:
            age_hours = max(0.0, (_utc_now() - expanded_at).total_seconds() / 3600.0)
            if age_hours > float(max_age_hours):
                return None
        try:
            citations = json.loads(str(row["citations_json"] or "[]"))
            if not isinstance(citations, list):
                citations = []
        except Exception:
            citations = []
        return {"summary": str(row["summary"] or ""), "citations": citations}

    def _store_item_expansion(self, item_id: str, *, summary: str, citations: List[Dict[str, Any]]) -> None:
        try:
            payload = json.dumps(list(citations or []), ensure_ascii=True)
            self._conn.execute(
                """
                INSERT OR REPLACE INTO knowledge_item_expansions(item_id, summary, citations_json, expanded_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(item_id), str(summary or "").strip(), payload, _utc_now_iso()),
            )
            self._conn.commit()
        except Exception:
            return

    def _get_item_by_id(self, item_id: str) -> Optional[KnowledgeItem]:
        row = self._conn.execute(
            "SELECT * FROM knowledge_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_item(row)

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> KnowledgeItem:
        return KnowledgeItem(
            item_id=str(row["item_id"]),
            kind=str(row["kind"]),
            category=str(row["category"]),
            title=str(row["title"]),
            summary=str(row["summary"] or ""),
            url=str(row["url"] or ""),
            source=str(row["source"] or ""),
            published_at=str(row["published_at"] or ""),
            ingested_at=str(row["ingested_at"] or ""),
            score=0.0,
        )

    @staticmethod
    def _allocate_counts(categories: List[str], weights: Dict[str, float], total: int) -> Dict[str, int]:
        total = max(total, len(categories))
        safe = {cat: max(float(weights.get(cat, 1.0)), 0.0) for cat in categories}
        weight_sum = sum(safe.values()) or float(len(categories))
        counts = {cat: max(1, int(round((safe[cat] / weight_sum) * total))) for cat in categories}
        current = sum(counts.values())
        idx = 0
        while current != total and categories:
            cat = categories[idx % len(categories)]
            if current > total and counts[cat] > 1:
                counts[cat] -= 1
                current -= 1
            elif current < total:
                counts[cat] += 1
                current += 1
            idx += 1
            if idx > 500:
                break
        return counts

    @staticmethod
    def _news_queries_for_category(category: str) -> List[str]:
        cat = category.replace("_", " ").strip().lower()
        if cat == "tech":
            return [
                "latest AI model launch Reuters",
                "open source AI release Hugging Face",
                "semiconductor GPU update Nvidia Reuters",
                "developer tools platform update TechCrunch",
                "technology policy update U.S. government",
            ]
        if cat == "finance":
            return [
                "stock market update Reuters",
                "federal reserve interest rate decision",
                "earnings and guidance update CNBC",
                "fintech regulation SEC update",
                "global markets inflation outlook Bloomberg",
            ]
        if cat == "healthcare":
            return [
                "FDA approval and safety update",
                "NIH clinical trial update",
                "WHO global health advisory",
                "biotech pharma update Reuters",
                "medical research breakthrough Nature",
            ]
        base = cat or "news"
        return [
            f"latest {base} updates",
            f"{base} major update today",
            f"{base} headlines",
        ]

    @staticmethod
    def _grounded_summary(item: KnowledgeItem, related: List[Dict[str, Any]]) -> str:
        lines = [
            f"{item.title}",
            "",
            f"Category: {item.category.title()} | Freshness: {item.freshness_label}",
        ]
        if item.summary:
            lines.append(f"Key update: {item.summary}")
        if related:
            supports = []
            for row in related[:3]:
                source = str(row.get("source") or "source").strip()
                title = str(row.get("title") or "").strip()
                if title:
                    supports.append(f"- {source}: {title}")
            if supports:
                lines.append("")
                lines.append("Supporting sources:")
                lines.extend(supports)
        lines.append("")
        lines.append("Ask for another item number if you want a deeper comparison.")
        return "\n".join(lines).strip()


_updater: Optional[KnowledgeUpdater] = None


def get_knowledge_updater() -> KnowledgeUpdater:
    global _updater
    if _updater is None:
        _updater = KnowledgeUpdater()
    return _updater
