"""Approval ledger for sensitive browser submits/payments/destructive actions."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class ActionApproval:
    scope_hash: str
    capability_name: str
    categories: List[str]
    approved_at: float
    expires_at: float
    note: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "scope_hash": self.scope_hash,
            "capability_name": self.capability_name,
            "categories": list(self.categories),
            "approved_at": float(self.approved_at),
            "expires_at": float(self.expires_at),
            "note": self.note,
        }


class ActionApprovalLedger:
    """Persistent approval cache with TTL."""

    def __init__(self, path: Optional[Path] = None, ttl_minutes: int = 20):
        config = get_config()
        self.path = path or config.action_approval_path or (config.data_dir / "action_approvals.json")
        self.ttl_minutes = max(1, int(ttl_minutes))
        self._cache: Dict[str, ActionApproval] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return
            for row in data:
                if not isinstance(row, dict):
                    continue
                scope_hash = str(row.get("scope_hash") or "").strip()
                if not scope_hash:
                    continue
                categories = row.get("categories")
                if not isinstance(categories, list):
                    categories = []
                self._cache[scope_hash] = ActionApproval(
                    scope_hash=scope_hash,
                    capability_name=str(row.get("capability_name") or ""),
                    categories=[str(item) for item in categories if str(item).strip()],
                    approved_at=float(row.get("approved_at") or 0.0),
                    expires_at=float(row.get("expires_at") or 0.0),
                    note=str(row.get("note") or ""),
                )
        except Exception as exc:
            logger.warning("Failed to load action approvals: %s", exc)

    def _save(self) -> None:
        try:
            payload = [item.to_dict() for item in self._cache.values()]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to save action approvals: %s", exc)

    def _prune(self) -> None:
        now = time.time()
        expired = [key for key, value in self._cache.items() if float(value.expires_at) <= now]
        for key in expired:
            self._cache.pop(key, None)

    def is_approved(self, scope_hash: str, category: Optional[str] = None) -> bool:
        self._load()
        self._prune()
        key = str(scope_hash or "").strip()
        if not key:
            return False
        row = self._cache.get(key)
        if not row:
            return False
        if category and category not in (row.categories or []):
            return False
        return bool(float(row.expires_at) > time.time())

    def record_approval(
        self,
        *,
        scope_hash: str,
        capability_name: str,
        categories: List[str],
        ttl_minutes: Optional[int] = None,
        note: str = "",
    ) -> None:
        self._load()
        ttl = int(ttl_minutes if ttl_minutes is not None else self.ttl_minutes)
        now = time.time()
        entry = ActionApproval(
            scope_hash=str(scope_hash or "").strip(),
            capability_name=str(capability_name or "").strip(),
            categories=[str(item) for item in (categories or []) if str(item).strip()],
            approved_at=now,
            expires_at=now + (max(1, ttl) * 60),
            note=str(note or ""),
        )
        if not entry.scope_hash:
            return
        self._cache[entry.scope_hash] = entry
        self._save()

    def recent(self, limit: int = 20) -> List[Dict[str, object]]:
        self._load()
        self._prune()
        rows = sorted(self._cache.values(), key=lambda row: float(row.approved_at), reverse=True)
        return [row.to_dict() for row in rows[: max(1, int(limit))]]


_ledger: Optional[ActionApprovalLedger] = None


def get_action_approval_ledger() -> ActionApprovalLedger:
    global _ledger
    if _ledger is None:
        config = get_config()
        _ledger = ActionApprovalLedger(
            path=config.action_approval_path,
            ttl_minutes=config.action_approval_ttl_minutes,
        )
    return _ledger


def reset_action_approval_ledger() -> None:
    global _ledger
    _ledger = None
