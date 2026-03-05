"""Bi-weekly learning export and optional fine-tune hook."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from chintu_backend.brain.learning.learning_engine import get_learning_engine
from chintu_backend.brain.learning.train_adapter import set_active_adapter, train_adapter
from chintu_backend.core.config import get_config
from chintu_backend.training.biweekly_export import export_biweekly_datasets


def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now() -> str:
    return _utc_now_dt().isoformat().replace("+00:00", "Z")


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class WeeklyRunStatus:
    ok: bool
    message: str
    export_path: Optional[str] = None
    manifest_path: Optional[str] = None
    style_count: int = 0
    facts_count: int = 0
    memory_count: int = 0
    trained: bool = False
    activation_pending: bool = False
    pending_activation_path: Optional[str] = None


class WeeklyLearningScheduler:
    """Background scheduler for bi-weekly learning exports."""

    def __init__(self) -> None:
        self.config = get_config()
        self.engine = get_learning_engine()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self: "WeeklyLearningScheduler") -> None:
        if not getattr(self.config, "learning_weekly_enabled", True):
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="LearningWeekly")
        self._thread.start()

    def stop(self: "WeeklyLearningScheduler") -> None:
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
        now = _utc_now_dt()

        interval_days = int(getattr(self.config, "learning_schedule_days", 14))
        last_run = _parse_ts(state.get("last_biweekly_run") or state.get("last_weekly_run"))
        if last_run and (now - last_run) < timedelta(days=interval_days):
            return

        pending = bool(state.get("biweekly_pending"))
        if not pending:
            target_day = int(getattr(self.config, "learning_weekly_day", 6))
            target_hour = int(getattr(self.config, "learning_weekly_hour", 2))
            if now.weekday() != target_day or now.hour != target_hour:
                return
            # Mark the run as pending so we can wait for "night + idle" gating without missing the window.
            state["biweekly_pending"] = True
            state["biweekly_pending_since"] = _utc_now()
            self.engine.store.save_state(state)
            pending = True

        if pending and bool(getattr(self.config, "learning_require_night_window", True)):
            try:
                from chintu_backend.core.time_window import is_hour_in_window

                local_hour = int(datetime.now().hour)
                start = int(getattr(self.config, "night_run_start_hour", 1))
                end = int(getattr(self.config, "night_run_end_hour", 6))
                if not is_hour_in_window(local_hour, start, end):
                    return
            except Exception:
                # If gating fails, degrade gracefully and allow the run.
                pass

        if pending and bool(getattr(self.config, "learning_require_idle", True)):
            try:
                from chintu_backend.core.system_idle import is_idle

                ok, _reason, _snap = is_idle(
                    min_idle_seconds=float(getattr(self.config, "learning_idle_min_seconds", 10 * 60)),
                    max_cpu_percent=float(getattr(self.config, "learning_idle_max_cpu_percent", 30.0)),
                    max_gpu_util_percent=float(getattr(self.config, "learning_idle_max_gpu_util_percent", 25.0)),
                )
                if not ok:
                    return
            except Exception:
                # If we cannot detect idleness, don't block learning forever.
                pass

        status = run_biweekly_learning(force=False)
        # Whether successful or not, clear pending to avoid retry loops.
        state = self.engine.store.load_state()
        state["biweekly_pending"] = False
        state["biweekly_pending_since"] = ""
        if status.ok:
            state["last_biweekly_run"] = _utc_now()
            state["last_weekly_run"] = state["last_biweekly_run"]  # Compatibility
            if status.export_path:
                state["last_export_path"] = status.export_path
            if status.manifest_path:
                state["last_export_manifest"] = status.manifest_path
        self.engine.store.save_state(state)


def run_biweekly_learning(force: bool = False) -> WeeklyRunStatus:
    config = get_config()
    engine = get_learning_engine()
    state = engine.store.load_state()

    export_dir = Path(config.training_exports_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    since_ts = None if force else state.get("last_biweekly_approved_ts")
    export_result = export_biweekly_datasets(since_timestamp=since_ts)

    style_count = int(export_result.style_count)
    facts_count = int(export_result.facts_count)
    memory_count = int(export_result.memory_count)
    export_path = str(export_result.style_path)
    manifest_path = str(export_result.manifest_path) if export_result.manifest_path else None

    if export_result.latest_approved_timestamp:
        state["last_biweekly_approved_ts"] = export_result.latest_approved_timestamp

    if style_count <= 0:
        msg = "No new style training samples found for this bi-weekly cycle."
        _record_training_state(
            msg,
            None,
            {
                "last_export_path": export_path,
                "last_export_manifest": manifest_path or "",
                "last_export_style_count": style_count,
                "last_export_facts_count": facts_count,
                "last_export_memory_count": memory_count,
                "last_biweekly_approved_ts": state.get("last_biweekly_approved_ts", ""),
            },
        )
        return WeeklyRunStatus(
            ok=False,
            message=msg,
            export_path=export_path,
            manifest_path=manifest_path,
            style_count=style_count,
            facts_count=facts_count,
            memory_count=memory_count,
            trained=False,
        )

    min_events = int(getattr(config, "learning_weekly_min_events", 10))
    if style_count < min_events:
        msg = f"Not enough style data for training ({style_count} < {min_events})."
        _record_training_state(
            msg,
            None,
            {
                "last_export_path": export_path,
                "last_export_manifest": manifest_path or "",
                "last_export_style_count": style_count,
                "last_export_facts_count": facts_count,
                "last_export_memory_count": memory_count,
                "last_biweekly_approved_ts": state.get("last_biweekly_approved_ts", ""),
            },
        )
        return WeeklyRunStatus(
            ok=False,
            message=msg,
            export_path=export_path,
            manifest_path=manifest_path,
            style_count=style_count,
            facts_count=facts_count,
            memory_count=memory_count,
            trained=False,
        )

    train_cmd = getattr(config, "learning_train_command", None)
    if not train_cmd and getattr(config, "learning_train_enabled", True):
        prev_active = _read_active_adapter(Path(config.learning_adapter_dir))
        outcome = train_adapter(export_result.style_path, Path(config.learning_adapter_dir), activate=False)
        if not outcome.ok:
            _record_training_state(
                outcome.message,
                None,
                {
                    "last_export_path": export_path,
                    "last_export_manifest": manifest_path or "",
                    "last_export_style_count": style_count,
                    "last_export_facts_count": facts_count,
                    "last_export_memory_count": memory_count,
                    "last_biweekly_approved_ts": state.get("last_biweekly_approved_ts", ""),
                },
            )
            return WeeklyRunStatus(
                ok=False,
                message=outcome.message,
                export_path=export_path,
                manifest_path=manifest_path,
                style_count=style_count,
                facts_count=facts_count,
                memory_count=memory_count,
                trained=False,
            )

        gate_ok, gate_msg = _run_eval_gate()
        if not gate_ok:
            _restore_active_adapter(Path(config.learning_adapter_dir), prev_active)
            _record_training_state(
                gate_msg,
                None,
                {
                    "last_export_path": export_path,
                    "last_export_manifest": manifest_path or "",
                    "last_export_style_count": style_count,
                    "last_export_facts_count": facts_count,
                    "last_export_memory_count": memory_count,
                    "last_biweekly_approved_ts": state.get("last_biweekly_approved_ts", ""),
                },
            )
            _log_audit("model_swap_rejected", {"reason": gate_msg})
            return WeeklyRunStatus(
                ok=False,
                message=gate_msg,
                export_path=export_path,
                manifest_path=manifest_path,
                style_count=style_count,
                facts_count=facts_count,
                memory_count=memory_count,
                trained=False,
            )

        requires_approval = bool(getattr(config, "learning_activation_requires_approval", True))
        auto_activate = bool(getattr(config, "learning_auto_activate_adapter", False))
        if requires_approval or not auto_activate:
            pending_path = _write_pending_activation(
                adapter_path=str(outcome.adapter_path or ""),
                dataset_path=export_path,
                manifest_path=manifest_path,
                eval_message=gate_msg,
                previous_active=prev_active,
            )
            msg = "Bi-weekly training complete. Adapter candidate is pending explicit activation approval."
            _record_training_state(
                msg,
                None,
                {
                    "last_export_path": export_path,
                    "last_export_manifest": manifest_path or "",
                    "last_export_style_count": style_count,
                    "last_export_facts_count": facts_count,
                    "last_export_memory_count": memory_count,
                    "last_biweekly_run": _utc_now(),
                    "last_biweekly_approved_ts": state.get("last_biweekly_approved_ts", ""),
                    "last_adapter_candidate_path": str(outcome.adapter_path or ""),
                    "last_adapter_activation_pending_path": pending_path,
                },
            )
            _log_audit(
                "model_swap_pending_approval",
                {
                    "adapter_path": outcome.adapter_path or "",
                    "dataset": export_path,
                    "pending_activation_path": pending_path,
                },
            )
            return WeeklyRunStatus(
                ok=True,
                message=msg,
                export_path=export_path,
                manifest_path=manifest_path,
                style_count=style_count,
                facts_count=facts_count,
                memory_count=memory_count,
                trained=True,
                activation_pending=True,
                pending_activation_path=pending_path,
            )

        set_active_adapter(Path(outcome.adapter_path), config.learning_base_model_id, Path(config.learning_adapter_dir))
        _record_training_state(
            "Bi-weekly training complete.",
            outcome.adapter_path,
            {
                "last_export_path": export_path,
                "last_export_manifest": manifest_path or "",
                "last_export_style_count": style_count,
                "last_export_facts_count": facts_count,
                "last_export_memory_count": memory_count,
                "last_biweekly_run": _utc_now(),
                "last_biweekly_approved_ts": state.get("last_biweekly_approved_ts", ""),
            },
        )
        _log_audit(
            "model_swap",
            {"adapter_path": outcome.adapter_path or "", "dataset": export_path},
        )
        return WeeklyRunStatus(
            ok=True,
            message="Bi-weekly training complete.",
            export_path=export_path,
            manifest_path=manifest_path,
            style_count=style_count,
            facts_count=facts_count,
            memory_count=memory_count,
            trained=True,
        )

    if not train_cmd:
        msg = "Bi-weekly dataset exported (training disabled)."
        _record_training_state(
            msg,
            None,
            {
                "last_export_path": export_path,
                "last_export_manifest": manifest_path or "",
                "last_export_style_count": style_count,
                "last_export_facts_count": facts_count,
                "last_export_memory_count": memory_count,
                "last_biweekly_approved_ts": state.get("last_biweekly_approved_ts", ""),
            },
        )
        return WeeklyRunStatus(
            ok=True,
            message=msg,
            export_path=export_path,
            manifest_path=manifest_path,
            style_count=style_count,
            facts_count=facts_count,
            memory_count=memory_count,
            trained=False,
        )

    env = os.environ.copy()
    env["CHINTU_LEARNING_DATASET"] = export_path
    env["CHINTU_LEARNING_OUTPUT_DIR"] = str(export_dir)
    timeout = int(getattr(config, "learning_train_timeout_seconds", 3600))

    try:
        import shlex

        args = shlex.split(train_cmd, posix=os.name != "nt")
        subprocess.run(args, shell=False, env=env, timeout=timeout, check=True)
        msg = "Bi-weekly training complete."
        _record_training_state(
            msg,
            None,
            {
                "last_export_path": export_path,
                "last_export_manifest": manifest_path or "",
                "last_export_style_count": style_count,
                "last_export_facts_count": facts_count,
                "last_export_memory_count": memory_count,
                "last_biweekly_run": _utc_now(),
                "last_biweekly_approved_ts": state.get("last_biweekly_approved_ts", ""),
            },
        )
        return WeeklyRunStatus(
            ok=True,
            message=msg,
            export_path=export_path,
            manifest_path=manifest_path,
            style_count=style_count,
            facts_count=facts_count,
            memory_count=memory_count,
            trained=True,
        )
    except Exception as exc:
        msg = f"Bi-weekly training failed: {exc}"
        _record_training_state(
            msg,
            None,
            {
                "last_export_path": export_path,
                "last_export_manifest": manifest_path or "",
                "last_export_style_count": style_count,
                "last_export_facts_count": facts_count,
                "last_export_memory_count": memory_count,
                "last_biweekly_approved_ts": state.get("last_biweekly_approved_ts", ""),
            },
        )
        return WeeklyRunStatus(
            ok=False,
            message=msg,
            export_path=export_path,
            manifest_path=manifest_path,
            style_count=style_count,
            facts_count=facts_count,
            memory_count=memory_count,
            trained=False,
        )


def run_weekly_learning() -> WeeklyRunStatus:
    """Compatibility alias for existing callers."""
    return run_biweekly_learning(force=False)


def get_biweekly_learning_status() -> Dict[str, Any]:
    config = get_config()
    engine = get_learning_engine()
    state = engine.store.load_state()
    interval_days = int(getattr(config, "learning_schedule_days", 14))
    last_run = _parse_ts(state.get("last_biweekly_run") or state.get("last_weekly_run"))
    next_run = last_run + timedelta(days=interval_days) if last_run else None
    pending = get_pending_adapter_activation()
    return {
        "enabled": bool(getattr(config, "learning_weekly_enabled", True)),
        "interval_days": interval_days,
        "target_day": int(getattr(config, "learning_weekly_day", 6)),
        "target_hour": int(getattr(config, "learning_weekly_hour", 2)),
        "last_run": _utc_iso_or_empty(last_run),
        "next_run_estimate": _utc_iso_or_empty(next_run),
        "last_training_message": state.get("last_training_message", ""),
        "last_export_path": state.get("last_export_path", ""),
        "last_export_manifest": state.get("last_export_manifest", ""),
        "last_export_style_count": int(state.get("last_export_style_count", 0) or 0),
        "last_export_facts_count": int(state.get("last_export_facts_count", 0) or 0),
        "last_export_memory_count": int(state.get("last_export_memory_count", 0) or 0),
        "last_biweekly_approved_ts": state.get("last_biweekly_approved_ts", ""),
        "pending_adapter_activation": pending,
    }


def get_pending_adapter_activation() -> Dict[str, Any]:
    config = get_config()
    data = _read_pending_activation()
    if not data:
        return {
            "pending": False,
            "path": str(getattr(config, "learning_pending_activation_path", "") or ""),
        }
    gate_ok, gate_msg, gate_details = _validate_phase29_gate()
    adapter_path = str(data.get("adapter_path") or "")
    return {
        "pending": str(data.get("status") or "pending") == "pending",
        "path": str(getattr(config, "learning_pending_activation_path", "") or ""),
        "adapter_path": adapter_path,
        "adapter_exists": Path(adapter_path).exists() if adapter_path else False,
        "created_at": str(data.get("created_at") or ""),
        "eval_gate": str(data.get("eval_gate") or ""),
        "dataset_path": str(data.get("dataset_path") or ""),
        "manifest_path": str(data.get("manifest_path") or ""),
        "status": str(data.get("status") or ""),
        "phase29_gate": {
            "required": bool(getattr(config, "learning_activation_require_phase29_gate", False)),
            "ok": bool(gate_ok),
            "message": gate_msg,
            "details": gate_details,
        },
    }


def approve_pending_adapter_activation(
    *,
    actor: str = "operator",
    expected_adapter_path: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    config = get_config()
    pending_path = Path(config.learning_pending_activation_path)
    data = _read_pending_activation()
    if not data or str(data.get("status") or "") != "pending":
        return False, "No pending adapter activation found.", {}

    adapter_path = str(data.get("adapter_path") or "").strip()
    if expected_adapter_path and adapter_path and Path(adapter_path) != Path(expected_adapter_path):
        return False, "Pending adapter does not match requested adapter path.", {"pending_adapter_path": adapter_path}
    if not adapter_path or not Path(adapter_path).exists():
        return False, "Pending adapter artifact is missing.", {"pending_adapter_path": adapter_path}
    gate_ok, gate_msg, gate_details = _validate_phase29_gate()
    if not gate_ok:
        return False, gate_msg, {"pending_adapter_path": adapter_path, "phase29_gate": gate_details}

    set_active_adapter(Path(adapter_path), config.learning_base_model_id, Path(config.learning_adapter_dir))
    data["status"] = "activated"
    data["approved_at"] = _utc_now()
    data["approved_by"] = actor
    if gate_details:
        data["phase29_gate"] = gate_details
    pending_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    _record_training_state(
        "Adapter activation approved and applied.",
        adapter_path,
        {
            "last_adapter_activation_approved_at": data["approved_at"],
            "last_adapter_activation_approved_by": actor,
            "last_adapter_activation_pending_path": str(pending_path),
            "last_adapter_activation_phase29_gate_path": str(gate_details.get("report_path") or ""),
        },
    )
    _log_audit(
        "model_swap",
        {"adapter_path": adapter_path, "approved_by": actor, "source": "pending_activation"},
    )
    return True, "Adapter activation approved.", data


def _utc_iso_or_empty(value: Optional[datetime]) -> str:
    if not value:
        return ""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_eval_gate() -> Tuple[bool, str]:
    config = get_config()
    try:
        from chintu_backend.eval.runner import _load_cases, run_eval

        cases_path = Path(config.eval_cases_path)
        cases = _load_cases(cases_path)
        score, _results = run_eval(cases)
        min_score = float(getattr(config, "eval_min_score", 0.8))
        gate_enabled = bool(getattr(config, "eval_gate_enabled", False))
        if gate_enabled and score < min_score:
            return False, f"Eval gate failed ({score:.2f} < {min_score:.2f})"
        return True, f"Eval gate passed ({score:.2f})"
    except Exception as exc:
        return False, f"Eval gate error: {exc}"


def _read_active_adapter(output_dir: Path) -> Optional[dict]:
    path = output_dir / "active_adapter.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_pending_activation() -> Optional[dict]:
    config = get_config()
    path = Path(config.learning_pending_activation_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


def _write_pending_activation(
    *,
    adapter_path: str,
    dataset_path: str,
    manifest_path: Optional[str],
    eval_message: str,
    previous_active: Optional[dict],
) -> str:
    config = get_config()
    pending_path = Path(config.learning_pending_activation_path)
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "pending",
        "created_at": _utc_now(),
        "adapter_path": adapter_path,
        "base_model": str(getattr(config, "learning_base_model_id", "") or ""),
        "dataset_path": dataset_path,
        "manifest_path": str(manifest_path or ""),
        "eval_gate": eval_message,
        "previous_active": previous_active or {},
    }
    pending_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(pending_path)


def _validate_phase29_gate() -> Tuple[bool, str, Dict[str, Any]]:
    config = get_config()
    if not bool(getattr(config, "learning_activation_require_phase29_gate", False)):
        return True, "Phase 29 gate not required.", {}

    report_dir = Path(getattr(config, "learning_phase29_reports_dir", "") or (Path.cwd() / "generated_reports"))
    prefix = str(getattr(config, "learning_phase29_gate_file_prefix", "phase29_autonomy_integration_gate_") or "")
    if not report_dir.exists():
        return False, f"Phase 29 gate reports directory not found: {report_dir}", {"reports_dir": str(report_dir)}

    candidates = sorted(report_dir.glob(f"{prefix}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return False, "Phase 29 gate required but no report was found.", {"reports_dir": str(report_dir)}

    latest = candidates[0]
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"Phase 29 gate report is unreadable: {exc}", {"report_path": str(latest)}

    overall_ok = bool(payload.get("overall_ok")) if isinstance(payload, dict) else False
    if not overall_ok:
        return False, "Phase 29 gate report is not passing.", {"report_path": str(latest), "overall_ok": False}

    ts = _parse_ts(str(payload.get("timestamp_utc") or "")) if isinstance(payload, dict) else None
    max_age_h = int(getattr(config, "learning_phase29_gate_max_age_hours", 168) or 168)
    if ts is not None:
        age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
        if age_hours > float(max_age_h):
            return False, f"Phase 29 gate report is stale ({age_hours:.1f}h > {max_age_h}h).", {
                "report_path": str(latest),
                "age_hours": round(age_hours, 2),
            }

    return True, "Phase 29 gate passed.", {"report_path": str(latest), "overall_ok": True}


def _restore_active_adapter(output_dir: Path, data: Optional[dict]) -> None:
    if data is None:
        return
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "active_adapter.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _log_audit(event: str, payload: dict) -> None:
    try:
        from chintu_backend.audit import log_event

        log_event(event, payload)
    except Exception:
        pass


def _record_training_state(
    message: str,
    adapter_path: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    engine = get_learning_engine()
    state = engine.store.load_state()
    state["last_training_message"] = message
    if adapter_path:
        state["last_adapter_path"] = adapter_path
    state["last_training_at"] = _utc_now()
    if metadata:
        for key, value in metadata.items():
            state[key] = value
    engine.store.save_state(state)
