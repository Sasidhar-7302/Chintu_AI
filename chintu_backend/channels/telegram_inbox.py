"""Telegram inbox intake + content intelligence pipeline (Phase 21)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import uuid

from chintu_backend.automation.media_pipeline import analyze_image, summarize_video
from chintu_backend.brain.knowledge.knowledge_updater import get_knowledge_updater
from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_first_url(text: str) -> str:
    match = re.search(r"(https?://[^\s]+)", str(text or ""), flags=re.IGNORECASE)
    return str(match.group(1)).strip() if match else ""


def _row_count(row: Any) -> int:
    if row is None:
        return 0
    try:
        return int(row["n"])
    except Exception:
        try:
            return int(row[0])
        except Exception:
            return 0


def _parse_utc(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _guess_category(text: str) -> str:
    low = str(text or "").lower()
    if any(tok in low for tok in ("financ", "stocks", "portfolio", "market", "crypto", "invest")):
        return "finance"
    if any(tok in low for tok in ("health", "medical", "hospital", "drug", "biotech")):
        return "healthcare"
    if any(tok in low for tok in ("ai", "llm", "model", "agent", "software", "tech", "gpu", "python", "code")):
        return "tech"
    if any(tok in low for tok in ("youtube", "instagram", "reel", "short", "content")):
        return "content"
    return "general"


class TelegramInboxManager:
    """Persistent intake queue and extraction store for Telegram-shared content."""

    def __init__(
        self,
        *,
        db_path: Optional[Path] = None,
        media_dir: Optional[Path] = None,
        items_dir: Optional[Path] = None,
    ) -> None:
        cfg = get_config()
        self.config = cfg
        self.enabled = bool(getattr(cfg, "telegram_inbox_enabled", True))
        self.db_path = Path(db_path or cfg.telegram_inbox_db_path)
        self.media_dir = Path(media_dir or cfg.telegram_inbox_media_dir)
        self.items_dir = Path(items_dir or cfg.telegram_inbox_items_dir)
        self.max_queue_size = int(getattr(cfg, "telegram_inbox_max_queue_size", 500) or 500)
        self.batch_size = int(getattr(cfg, "telegram_inbox_process_batch_size", 5) or 5)
        self.video_max_frames = int(getattr(cfg, "telegram_inbox_video_max_frames", 16) or 16)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.items_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_inbox_items (
                intake_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                message_text TEXT,
                url TEXT,
                media_path TEXT,
                media_type TEXT,
                source_message_id TEXT,
                source_chat_id TEXT,
                source_user_id TEXT,
                source_timestamp TEXT,
                provenance_json TEXT NOT NULL,
                status TEXT NOT NULL,
                category TEXT,
                summary TEXT,
                opinion_json TEXT,
                action_plan_json TEXT,
                created_at TEXT NOT NULL,
                processed_at TEXT
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tg_inbox_status_created ON telegram_inbox_items(status, created_at DESC)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tg_inbox_category_processed ON telegram_inbox_items(category, processed_at DESC)"
        )
        self._conn.commit()

    def enqueue_item(
        self,
        *,
        kind: str,
        message_text: str = "",
        media_path: str = "",
        media_type: str = "",
        source_message_id: str = "",
        source_chat_id: str = "",
        source_user_id: str = "",
        source_timestamp: str = "",
        provenance: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "message": "telegram inbox intake disabled"}
        pending = self._conn.execute(
            "SELECT COUNT(1) AS n FROM telegram_inbox_items WHERE status = 'pending'"
        ).fetchone()
        if _row_count(pending) >= self.max_queue_size:
            return {"ok": False, "message": "telegram inbox queue is full"}

        intake_id = f"tgin_{uuid.uuid4().hex[:12]}"
        text = str(message_text or "").strip()
        url = _extract_first_url(text)
        now = _utc_now_iso()
        payload = {
            "chat_id": str(source_chat_id or ""),
            "message_id": str(source_message_id or ""),
            "user_id": str(source_user_id or ""),
            "timestamp": str(source_timestamp or ""),
            **(provenance or {}),
        }
        self._conn.execute(
            """
            INSERT INTO telegram_inbox_items(
                intake_id, kind, message_text, url, media_path, media_type,
                source_message_id, source_chat_id, source_user_id, source_timestamp,
                provenance_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                intake_id,
                str(kind or "text"),
                text,
                url,
                str(media_path or ""),
                str(media_type or ""),
                str(source_message_id or ""),
                str(source_chat_id or ""),
                str(source_user_id or ""),
                str(source_timestamp or ""),
                json.dumps(payload, ensure_ascii=True),
                now,
            ),
        )
        self._conn.commit()
        return {"ok": True, "intake_id": intake_id}

    def process_pending(self, *, max_items: Optional[int] = None) -> Dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "message": "telegram inbox intake disabled"}
        limit = max(1, min(int(max_items or self.batch_size), 100))
        rows = self._conn.execute(
            """
            SELECT * FROM telegram_inbox_items
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        processed: List[Dict[str, Any]] = []
        for row in rows:
            item = self._process_row(row)
            if item:
                processed.append(item)
        return {"ok": True, "processed_count": len(processed), "items": processed}

    def recent_items(self, *, limit: int = 10, category: Optional[str] = None) -> List[Dict[str, Any]]:
        lim = max(1, min(int(limit), 100))
        if category:
            rows = self._conn.execute(
                """
                SELECT * FROM telegram_inbox_items
                WHERE status = 'processed' AND category = ?
                ORDER BY processed_at DESC
                LIMIT ?
                """,
                (str(category).strip().lower(), lim),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM telegram_inbox_items
                WHERE status = 'processed'
                ORDER BY processed_at DESC
                LIMIT ?
                """,
                (lim,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def recent_items_since(
        self,
        *,
        days: int = 7,
        limit: int = 50,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = self.recent_items(limit=max(1, min(int(limit), 200)), category=category)
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
        kept: List[Dict[str, Any]] = []
        for row in rows:
            ts = _parse_utc(str(row.get("processed_at") or row.get("created_at") or ""))
            if ts and ts >= cutoff:
                kept.append(row)
        return kept

    def search_items(self, query: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        q = f"%{str(query or '').strip()}%"
        lim = max(1, min(int(limit), 50))
        rows = self._conn.execute(
            """
            SELECT * FROM telegram_inbox_items
            WHERE status = 'processed'
              AND (message_text LIKE ? OR summary LIKE ? OR category LIKE ?)
            ORDER BY processed_at DESC
            LIMIT ?
            """,
            (q, q, q, lim),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_stats(self) -> Dict[str, Any]:
        total = self._conn.execute("SELECT COUNT(1) AS n FROM telegram_inbox_items").fetchone()
        pending = self._conn.execute(
            "SELECT COUNT(1) AS n FROM telegram_inbox_items WHERE status='pending'"
        ).fetchone()
        processed = self._conn.execute(
            "SELECT COUNT(1) AS n FROM telegram_inbox_items WHERE status='processed'"
        ).fetchone()
        cancelled = self._conn.execute(
            "SELECT COUNT(1) AS n FROM telegram_inbox_items WHERE status='cancelled'"
        ).fetchone()
        return {
            "enabled": self.enabled,
            "total": _row_count(total),
            "pending": _row_count(pending),
            "processed": _row_count(processed),
            "cancelled": _row_count(cancelled),
            "db_path": str(self.db_path),
            "items_dir": str(self.items_dir),
        }

    def cancel_item(self, intake_id: str) -> bool:
        key = str(intake_id or "").strip()
        if not key:
            return False
        cursor = self._conn.execute(
            "UPDATE telegram_inbox_items SET status='cancelled' WHERE intake_id=? AND status='pending'",
            (key,),
        )
        self._conn.commit()
        return int(cursor.rowcount or 0) > 0

    def resume_item(self, intake_id: str) -> bool:
        key = str(intake_id or "").strip()
        if not key:
            return False
        cursor = self._conn.execute(
            "UPDATE telegram_inbox_items SET status='pending' WHERE intake_id=? AND status='cancelled'",
            (key,),
        )
        self._conn.commit()
        return int(cursor.rowcount or 0) > 0

    def _process_row(self, row: sqlite3.Row) -> Optional[Dict[str, Any]]:
        intake_id = str(row["intake_id"])
        kind = str(row["kind"] or "text").strip().lower()
        message_text = str(row["message_text"] or "").strip()
        media_path = str(row["media_path"] or "").strip()
        source_url = str(row["url"] or "").strip()

        summary = ""
        category = _guess_category(message_text)
        action_plan: List[str] = []
        citations: List[str] = []
        extracted: Dict[str, Any] = {}

        try:
            if kind in {"photo", "image"} and media_path:
                result = analyze_image(media_path, mode="analyze")
                summary = str(result.get("summary") or "").strip()
                extracted = result if isinstance(result, dict) else {}
                category = category if category != "general" else "content"
            elif kind in {"video", "reel"} and media_path:
                result = summarize_video(media_path, max_frames=self.video_max_frames)
                summary = str(result.get("summary") or "").strip()
                extracted = result if isinstance(result, dict) else {}
                category = category if category != "general" else "content"
            elif source_url:
                domain = re.sub(r"^https?://", "", source_url, flags=re.IGNORECASE).split("/")[0]
                summary = f"Shared link from {domain}: {message_text[:200]}".strip()
                citations = [source_url]
            else:
                summary = message_text[:400]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram inbox extraction failed (%s): %s", intake_id, exc)
            summary = summary or message_text[:300] or f"{kind} item queued."

        opinion = self._build_opinion(message_text=message_text, summary=summary, category=category)
        action_plan = list(opinion.get("next_actions") or [])
        if source_url and source_url not in citations:
            citations.append(source_url)

        processed_at = _utc_now_iso()
        self._conn.execute(
            """
            UPDATE telegram_inbox_items
            SET status='processed',
                category=?,
                summary=?,
                opinion_json=?,
                action_plan_json=?,
                processed_at=?
            WHERE intake_id=?
            """,
            (
                category,
                summary,
                json.dumps(opinion, ensure_ascii=True),
                json.dumps(action_plan, ensure_ascii=True),
                processed_at,
                intake_id,
            ),
        )
        self._conn.commit()

        item = self._conn.execute(
            "SELECT * FROM telegram_inbox_items WHERE intake_id = ?",
            (intake_id,),
        ).fetchone()
        if not item:
            return None
        payload = self._row_to_dict(item)
        payload["citations"] = citations
        payload["extracted"] = extracted
        self._persist_item_file(payload)
        self._save_to_knowledge(payload)
        return payload

    def _save_to_knowledge(self, item: Dict[str, Any]) -> None:
        if not bool(getattr(self.config, "curiosity_process_telegram_inbox", True)):
            return
        try:
            updater = get_knowledge_updater()
            updater.ingest_external_item(
                category=str(item.get("category") or "general"),
                title=f"Telegram {str(item.get('kind') or 'item')}: {str(item.get('summary') or '')[:120]}",
                summary=str(item.get("summary") or ""),
                url=str(item.get("url") or ""),
                source="telegram",
                kind="telegram_inbox",
                published_at=str(item.get("source_timestamp") or item.get("created_at") or ""),
            )
        except Exception:
            return

    def _persist_item_file(self, item: Dict[str, Any]) -> None:
        intake_id = str(item.get("intake_id") or "")
        if not intake_id:
            return
        out = self.items_dir / f"{intake_id}.json"
        out.write_text(json.dumps(item, indent=2, ensure_ascii=True), encoding="utf-8")

    def _build_opinion(self, *, message_text: str, summary: str, category: str) -> Dict[str, Any]:
        low = f"{message_text}\n{summary}".lower()
        if any(tok in low for tok in ("agent", "automation", "workflow", "langgraph", "llm")):
            next_actions = [
                "Store in RAG for future retrieval.",
                "Propose follow-up research task with citations.",
            ]
        elif any(tok in low for tok in ("youtube", "instagram", "reel", "short")):
            next_actions = [
                "Attach to content pipeline backlog.",
                "Draft reusable content idea variants for review.",
            ]
        elif any(tok in low for tok in ("stock", "portfolio", "market", "finance")):
            next_actions = [
                "Add to finance watchlist briefing candidates.",
                "Generate risk-aware summary before suggesting actions.",
            ]
        else:
            next_actions = [
                "Store as searchable knowledge with provenance.",
                "Ask if deeper analysis is needed.",
            ]
        return {
            "what_i_learned": summary[:220] if summary else "New item stored from Telegram.",
            "why_it_matters": f"This item is categorized under {category}.",
            "next_actions": next_actions,
            "confidence": 0.68,
        }

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        raw = dict(row)
        for key in ("provenance_json", "opinion_json", "action_plan_json"):
            try:
                raw[key.replace("_json", "")] = json.loads(str(raw.get(key) or ""))
            except Exception:
                raw[key.replace("_json", "")] = {}
            raw.pop(key, None)
        return raw


_telegram_inbox_manager: Optional[TelegramInboxManager] = None


def get_telegram_inbox_manager() -> TelegramInboxManager:
    global _telegram_inbox_manager
    if _telegram_inbox_manager is None:
        _telegram_inbox_manager = TelegramInboxManager()
    return _telegram_inbox_manager
