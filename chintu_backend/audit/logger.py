"""Audit logging for critical system events."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from chintu_backend.core.config import get_config

_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class AuditEvent:
    event: str
    payload: Dict[str, Any]
    ts: str

    def to_dict(self) -> Dict[str, Any]:
        return {"event": self.event, "payload": self.payload, "ts": self.ts}


def log_event(event: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """Append a structured audit event if enabled."""
    config = get_config()
    if not getattr(config, "audit_enabled", True):
        return
    payload = payload or {}
    event_obj = AuditEvent(event=event, payload=payload, ts=_utc_now())
    log_path = Path(getattr(config, "audit_log_path", config.data_dir / "audit" / "audit_log.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event_obj.to_dict(), ensure_ascii=False) + "\n")
