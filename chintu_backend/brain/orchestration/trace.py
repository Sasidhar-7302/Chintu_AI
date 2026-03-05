"""Lightweight orchestration trace logging."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from chintu_backend.core.config import get_config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def log_event(event: Dict[str, Any]) -> None:
    config = get_config()
    trace_dir = Path(config.data_dir) / "orchestration"
    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / "trace.jsonl"
    payload = dict(event or {})
    payload["timestamp"] = _utc_now()
    path.open("a", encoding="utf-8").write(json.dumps(payload, ensure_ascii=True) + "\n")
