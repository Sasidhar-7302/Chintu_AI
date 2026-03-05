"""Execution approval ledger with TTL."""

from __future__ import annotations

import json
import logging
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class ExecApproval:
    command_hash: str
    expires_at: float


class ExecApprovalLedger:
    def __init__(self, path: Optional[Path] = None, ttl_minutes: int = 10):
        config = get_config()
        self.path = path or config.exec_approval_path or (config.data_dir / "exec_approvals.json")
        self.ttl_minutes = ttl_minutes
        self._cache: Dict[str, ExecApproval] = {}
        self._loaded = False

    def _hash(self, command: str, cwd: Optional[str]) -> str:
        payload = f"{command}|{cwd or ''}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for item in data:
                approval = ExecApproval(
                    command_hash=item["command_hash"],
                    expires_at=float(item["expires_at"]),
                )
                self._cache[approval.command_hash] = approval
        except Exception as exc:
            logger.warning("Failed to load exec approvals: %s", exc)

    def _save(self) -> None:
        try:
            payload = [
                {"command_hash": a.command_hash, "expires_at": a.expires_at}
                for a in self._cache.values()
            ]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to save exec approvals: %s", exc)

    def _prune(self) -> None:
        now = time.time()
        expired = [k for k, v in self._cache.items() if v.expires_at <= now]
        for key in expired:
            self._cache.pop(key, None)

    def is_approved(self, command: str, cwd: Optional[str]) -> bool:
        self._load()
        self._prune()
        command_hash = self._hash(command, cwd)
        approval = self._cache.get(command_hash)
        return bool(approval and approval.expires_at > time.time())

    def record_approval(self, command: str, cwd: Optional[str], ttl_minutes: Optional[int] = None) -> None:
        self._load()
        ttl = ttl_minutes if ttl_minutes is not None else self.ttl_minutes
        expires_at = time.time() + (ttl * 60)
        command_hash = self._hash(command, cwd)
        self._cache[command_hash] = ExecApproval(command_hash=command_hash, expires_at=expires_at)
        self._save()


_ledger: Optional[ExecApprovalLedger] = None


def get_exec_approval_ledger() -> ExecApprovalLedger:
    global _ledger
    if _ledger is None:
        config = get_config()
        _ledger = ExecApprovalLedger(
            path=config.exec_approval_path,
            ttl_minutes=config.exec_approval_ttl_minutes,
        )
    return _ledger
