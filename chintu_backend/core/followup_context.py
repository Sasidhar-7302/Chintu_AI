"""Persistent context for numbered follow-up requests (e.g., point #2)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class FollowupContextStore:
    """Stores the latest numbered list context for cross-turn follow-up expansion."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or (Path.home() / ".chintu" / "followup_context.json")
        self._context: Dict[str, Any] = {}
        self._session_contexts: Dict[str, Dict[str, Any]] = {}
        self._history: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    if isinstance(payload.get("global_context"), dict):
                        self._context = dict(payload.get("global_context") or {})
                        raw_sessions = payload.get("sessions")
                        if isinstance(raw_sessions, dict):
                            self._session_contexts = {
                                str(k): dict(v)
                                for k, v in raw_sessions.items()
                                if isinstance(v, dict) and str(k).strip()
                            }
                        raw_history = payload.get("history")
                        if isinstance(raw_history, list):
                            self._history = [dict(row) for row in raw_history if isinstance(row, dict)]
                    else:
                        # Backward compatibility: older payloads stored only one context object.
                        self._context = payload
        except Exception as exc:
            logger.debug("Failed to load follow-up context: %s", exc)
            self._context = {}
            self._session_contexts = {}
            self._history = []

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at": _utc_now_iso(),
                "global_context": self._context,
                "sessions": self._session_contexts,
                "history": self._history[-30:],
            }
            self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to save follow-up context: %s", exc)

    @staticmethod
    def _normalize_item(row: Dict[str, Any]) -> Dict[str, str]:
        title = str(row.get("title") or row.get("name") or "").strip()
        url = str(row.get("url") or row.get("link") or "").strip()
        snippet = str(row.get("snippet") or row.get("summary") or row.get("description") or "").strip()
        source = str(row.get("source") or "").strip()
        category = str(row.get("category") or "").strip()
        return {
            "title": title,
            "url": url,
            "snippet": snippet,
            "source": source,
            "category": category,
        }

    @staticmethod
    def _parse_numbered_lines(message: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for line in str(message or "").splitlines():
            raw = str(line or "").strip()
            match = re.match(r"^\s*(\d{1,2})[.)]\s+(.+)$", raw)
            if not match:
                continue
            title = str(match.group(2) or "").strip()
            if title:
                rows.append({"title": title, "url": "", "snippet": "", "source": "", "category": ""})
        return rows

    def capture(
        self,
        capability_name: str,
        data: Any,
        message: str = "",
        session_id: Optional[str] = None,
    ) -> bool:
        """Capture structured numbered items from an action result."""
        cap = str(capability_name or "").strip().lower()
        payload = data if isinstance(data, dict) else {}
        items: List[Dict[str, str]] = []

        if isinstance(payload.get("items"), list):
            for row in payload.get("items") or []:
                if isinstance(row, dict):
                    item = self._normalize_item(row)
                    if item["title"]:
                        items.append(item)

        if not items and isinstance(payload.get("results"), list):
            for row in payload.get("results") or []:
                if isinstance(row, dict):
                    item = self._normalize_item(row)
                    if item["title"]:
                        items.append(item)

        if not items and isinstance(payload.get("sources"), list):
            for row in payload.get("sources") or []:
                if isinstance(row, dict):
                    item = self._normalize_item(row)
                    if item["title"]:
                        items.append(item)

        if not items:
            parsed = self._parse_numbered_lines(message)
            urls = [str(u).strip() for u in (payload.get("urls") or []) if str(u).strip()]
            if parsed:
                for idx, row in enumerate(parsed):
                    if idx < len(urls):
                        row["url"] = urls[idx]
                items = parsed

        if not items:
            return False

        kind = "generic_list"
        if cap in {"morning_briefing", "skill::daily-briefing", "skill::daily_briefing"}:
            kind = "morning_briefing"
        elif cap in {"live_search", "news_search", "web_search"}:
            kind = "search_results"
        elif cap in {"web_research", "deep_researcher", "agentic_research"}:
            kind = "research_results"

        context_row = {
            "kind": kind,
            "capability": cap,
            "query": str(payload.get("query") or "").strip(),
            "updated_at": _utc_now_iso(),
            "items": items[:30],
        }
        self._context = dict(context_row)
        sid = str(session_id or "").strip()
        if sid:
            self._session_contexts[sid] = dict(context_row)
        self._history.append(
            {
                "session_id": sid or "global",
                "captured_at": _utc_now_iso(),
                "kind": kind,
                "capability": cap,
                "count": len(items),
                "query": str(payload.get("query") or "").strip(),
            }
        )
        if len(self._history) > 50:
            self._history = self._history[-50:]
        self._save()
        return True

    def get_context(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        sid = str(session_id or "").strip()
        if not self._context and not self._session_contexts:
            self._load()
        if sid and isinstance(self._session_contexts.get(sid), dict):
            return dict(self._session_contexts.get(sid) or {})
        return dict(self._context or {})

    def get_item(self, index_1_based: int, session_id: Optional[str] = None) -> Optional[Dict[str, str]]:
        try:
            idx = int(index_1_based) - 1
        except Exception:
            return None
        items = list((self.get_context(session_id=session_id) or {}).get("items") or [])
        if idx < 0 or idx >= len(items):
            return None
        row = items[idx]
        return dict(row) if isinstance(row, dict) else None

    def get_recent_lists(self, session_id: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        sid = str(session_id or "").strip()
        rows = list(self._history or [])
        if sid:
            rows = [row for row in rows if str(row.get("session_id") or "") == sid]
        rows = rows[-max(1, int(limit)) :]
        return [dict(row) for row in rows]


_STORE: Optional[FollowupContextStore] = None


def get_followup_context_store() -> FollowupContextStore:
    global _STORE
    if _STORE is None:
        _STORE = FollowupContextStore()
    return _STORE
