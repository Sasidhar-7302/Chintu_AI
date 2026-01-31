"""Training data logger for future fine-tuning."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class TrainingDataLogger:
    """Append-only JSONL logger for training data."""

    def __init__(
        self,
        log_path: Path,
        enabled: bool = True,
        auto_approve: bool = False,
    ):
        self.log_path = log_path
        self.enabled = enabled
        self.auto_approve = auto_approve
        self._lock = threading.Lock()
        if self.enabled:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_interaction(
        self,
        user_text: str,
        assistant_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        if not user_text or not assistant_text:
            return None
        payload = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "user": user_text.strip(),
            "assistant": assistant_text.strip(),
            "approved": bool((metadata or {}).get("approved", self.auto_approve)),
            "source": (metadata or {}).get("source", "unknown"),
            "model_source": (metadata or {}).get("model_source", "unknown"),
            "command_type": (metadata or {}).get("command_type", "unknown"),
            "tags": (metadata or {}).get("tags", []),
        }
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
        return payload
