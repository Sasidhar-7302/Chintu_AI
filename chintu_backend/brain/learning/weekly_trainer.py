"""Weekly learning export and optional fine-tune hook."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from chintu_backend.core.config import get_config
from chintu_backend.brain.learning.learning_engine import get_learning_engine
from chintu_backend.brain.learning.train_adapter import train_adapter
from chintu_backend.training.gold_data import get_gold_data_manager


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class WeeklyRunStatus:
    ok: bool
    message: str
    export_path: Optional[str] = None


class WeeklyLearningScheduler:
    """Background scheduler for weekly learning exports."""

    def __init__(self) -> None:
        self.config = get_config()
        self.engine = get_learning_engine()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if not getattr(self.config, "learning_weekly_enabled", True):
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="LearningWeekly")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._maybe_run()
            except Exception:
                pass
            self._stop_event.wait(3600)

    def _maybe_run(self) -> None:
        state = self.engine.store.load_state()
        last_run = state.get("last_weekly_run")
        now = datetime.now()
        if last_run:
            try:
                last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                if (now - last_dt).days < 6:
                    return
            except Exception:
                pass

        target_day = int(getattr(self.config, "learning_weekly_day", 6))
        target_hour = int(getattr(self.config, "learning_weekly_hour", 2))
        if now.weekday() != target_day or now.hour != target_hour:
            return

        status = run_weekly_learning()
        if status.ok:
            state["last_weekly_run"] = _utc_now()
            state["last_export_path"] = status.export_path or ""
            self.engine.store.save_state(state)


def run_weekly_learning() -> WeeklyRunStatus:
    config = get_config()
    engine = get_learning_engine()

    export_dir = Path(config.training_exports_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    export_path = export_dir / f"weekly_learning_{stamp}.jsonl"

    learning_count = engine.export_training_dataset(
        export_path,
        format=getattr(config, "learning_export_format", "chat"),
    )

    gold_count = _append_gold_data(export_path, format=getattr(config, "learning_export_format", "chat"))
    total = learning_count + gold_count

    if total < int(getattr(config, "learning_weekly_min_events", 10)):
        return WeeklyRunStatus(False, "Not enough new learning data yet.")

    train_cmd = getattr(config, "learning_train_command", None)
    if not train_cmd and getattr(config, "learning_train_enabled", True):
        outcome = train_adapter(export_path, Path(config.learning_adapter_dir))
        message = outcome.message
        status = WeeklyRunStatus(True, message, str(export_path))
        _record_training_state(message, outcome.adapter_path)
        return status
    if not train_cmd:
        return WeeklyRunStatus(True, "Weekly dataset exported (training disabled).", str(export_path))

    env = os.environ.copy()
    env["CHINTU_LEARNING_DATASET"] = str(export_path)
    env["CHINTU_LEARNING_OUTPUT_DIR"] = str(export_dir)
    timeout = int(getattr(config, "learning_train_timeout_seconds", 3600))

    try:
        subprocess.run(train_cmd, shell=True, env=env, timeout=timeout, check=True)
        _record_training_state("Weekly training complete.", None)
        return WeeklyRunStatus(True, "Weekly training complete.", str(export_path))
    except Exception as exc:
        _record_training_state(f"Weekly training failed: {exc}", None)
        return WeeklyRunStatus(False, f"Weekly training failed: {exc}", str(export_path))


def _append_gold_data(output_path: Path, format: str = "chat") -> int:
    gold = get_gold_data_manager()
    approved = gold.get_approved(limit=2000)
    if not approved:
        return 0
    count = 0
    with output_path.open("a", encoding="utf-8") as handle:
        for item in approved:
            payload = item.to_chat_format() if format == "chat" else item.to_training_format()
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
            count += 1
    return count


def _record_training_state(message: str, adapter_path: Optional[str]) -> None:
    engine = get_learning_engine()
    state = engine.store.load_state()
    state["last_training_message"] = message
    if adapter_path:
        state["last_adapter_path"] = adapter_path
    state["last_training_at"] = _utc_now()
    engine.store.save_state(state)
