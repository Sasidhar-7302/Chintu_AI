"""Persistent storage for deal-finder price watches."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional
from uuid import uuid4

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class DealWatch:
    id: str
    query: str
    vendors: List[str]
    include_web_search: bool
    max_results_per_vendor: int
    max_web_results: int
    interval_minutes: int
    target_price: Optional[float] = None
    enabled: bool = True
    scheduled_task_id: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    last_checked_at: Optional[str] = None
    last_best_total: Optional[float] = None
    last_best_vendor: Optional[str] = None
    last_best_url: Optional[str] = None
    last_alert_at: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "query": self.query,
            "vendors": list(self.vendors or []),
            "include_web_search": bool(self.include_web_search),
            "max_results_per_vendor": int(self.max_results_per_vendor),
            "max_web_results": int(self.max_web_results),
            "interval_minutes": int(self.interval_minutes),
            "target_price": self.target_price,
            "enabled": bool(self.enabled),
            "scheduled_task_id": self.scheduled_task_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_checked_at": self.last_checked_at,
            "last_best_total": self.last_best_total,
            "last_best_vendor": self.last_best_vendor,
            "last_best_url": self.last_best_url,
            "last_alert_at": self.last_alert_at,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> "DealWatch":
        return cls(
            id=str(raw.get("id") or ""),
            query=str(raw.get("query") or ""),
            vendors=[str(v).strip().lower() for v in (raw.get("vendors") or []) if str(v).strip()],
            include_web_search=bool(raw.get("include_web_search")),
            max_results_per_vendor=max(1, int(raw.get("max_results_per_vendor") or 6)),
            max_web_results=max(1, int(raw.get("max_web_results") or 8)),
            interval_minutes=max(10, int(raw.get("interval_minutes") or 180)),
            target_price=float(raw["target_price"]) if raw.get("target_price") is not None else None,
            enabled=bool(raw.get("enabled", True)),
            scheduled_task_id=(str(raw.get("scheduled_task_id")) if raw.get("scheduled_task_id") else None),
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
            last_checked_at=(str(raw.get("last_checked_at")) if raw.get("last_checked_at") else None),
            last_best_total=float(raw["last_best_total"]) if raw.get("last_best_total") is not None else None,
            last_best_vendor=(str(raw.get("last_best_vendor")) if raw.get("last_best_vendor") else None),
            last_best_url=(str(raw.get("last_best_url")) if raw.get("last_best_url") else None),
            last_alert_at=(str(raw.get("last_alert_at")) if raw.get("last_alert_at") else None),
        )


class DealWatchStore:
    """Persist deal watches to disk."""

    def __init__(self, path: Optional[Path] = None) -> None:
        config = get_config()
        self.path = Path(path or (config.data_dir / "automation" / "deal_watches.json"))
        self._lock = Lock()
        self._data: Dict[str, object] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        self._data = raw
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to load deal watches: %s", exc)
            if "watches" not in self._data or not isinstance(self._data.get("watches"), list):
                self._data["watches"] = []

    def _save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def list_watches(self) -> List[DealWatch]:
        watches: List[DealWatch] = []
        for raw in (self._data.get("watches") or []):
            if not isinstance(raw, dict):
                continue
            try:
                watch = DealWatch.from_dict(raw)
            except Exception:
                continue
            if watch.id and watch.query:
                watches.append(watch)
        watches.sort(key=lambda w: (w.updated_at or w.created_at or ""), reverse=True)
        return watches

    def get_watch(self, watch_id: str) -> Optional[DealWatch]:
        wid = str(watch_id or "").strip().lower()
        if not wid:
            return None
        for watch in self.list_watches():
            if watch.id.lower() == wid:
                return watch
        return None

    def add_watch(
        self,
        *,
        query: str,
        vendors: List[str],
        include_web_search: bool,
        max_results_per_vendor: int,
        max_web_results: int,
        interval_minutes: int,
        target_price: Optional[float],
    ) -> DealWatch:
        now = _now_iso()
        watch = DealWatch(
            id=uuid4().hex[:8],
            query=str(query).strip(),
            vendors=[str(v).strip().lower() for v in vendors if str(v).strip()],
            include_web_search=bool(include_web_search),
            max_results_per_vendor=max(1, int(max_results_per_vendor)),
            max_web_results=max(1, int(max_web_results)),
            interval_minutes=max(10, int(interval_minutes)),
            target_price=(float(target_price) if target_price is not None else None),
            created_at=now,
            updated_at=now,
        )
        items = [w.to_dict() for w in self.list_watches()]
        items.append(watch.to_dict())
        self._data["watches"] = items
        self._save()
        return watch

    def remove_watch(self, watch_id: str) -> Optional[DealWatch]:
        removed: Optional[DealWatch] = None
        kept: List[Dict[str, object]] = []
        wid = str(watch_id or "").strip().lower()
        for watch in self.list_watches():
            if watch.id.lower() == wid:
                removed = watch
            else:
                kept.append(watch.to_dict())
        if removed is not None:
            self._data["watches"] = kept
            self._save()
        return removed

    def set_scheduled_task(self, watch_id: str, task_id: Optional[str]) -> Optional[DealWatch]:
        wid = str(watch_id or "").strip().lower()
        now = _now_iso()
        updated: Optional[DealWatch] = None
        out: List[Dict[str, object]] = []
        for watch in self.list_watches():
            if watch.id.lower() == wid:
                watch.scheduled_task_id = str(task_id).strip() if task_id else None
                watch.updated_at = now
                updated = watch
            out.append(watch.to_dict())
        if updated:
            self._data["watches"] = out
            self._save()
        return updated

    def record_check(
        self,
        watch_id: str,
        *,
        best_total: Optional[float],
        best_vendor: Optional[str],
        best_url: Optional[str],
        alerted: bool,
    ) -> Optional[DealWatch]:
        wid = str(watch_id or "").strip().lower()
        now = _now_iso()
        updated: Optional[DealWatch] = None
        out: List[Dict[str, object]] = []
        for watch in self.list_watches():
            if watch.id.lower() == wid:
                watch.last_checked_at = now
                watch.last_best_total = float(best_total) if best_total is not None else None
                watch.last_best_vendor = str(best_vendor) if best_vendor else None
                watch.last_best_url = str(best_url) if best_url else None
                if alerted:
                    watch.last_alert_at = now
                watch.updated_at = now
                updated = watch
            out.append(watch.to_dict())
        if updated:
            self._data["watches"] = out
            self._save()
        return updated


_deal_watch_store: Optional[DealWatchStore] = None


def get_deal_watch_store(path: Optional[Path] = None) -> DealWatchStore:
    global _deal_watch_store
    if path is not None:
        return DealWatchStore(path=path)
    if _deal_watch_store is None:
        _deal_watch_store = DealWatchStore()
    return _deal_watch_store

