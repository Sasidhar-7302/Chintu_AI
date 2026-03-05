"""Run lifecycle + queueing for robust task execution.

This module is the backbone for "finish the task + prove it worked":
- Every user request becomes a Run (run_id) with status transitions.
- Runs are serialized per session_id to prevent collisions with per-session queue lanes.
- Runs emit structured events to:
  - the internal Python WebSocket server (legacy UI)
  - the internal EventBus (Gateway bridge / other listeners)
- Run events are persisted to disk under ~/.chintu/runs/<run_id>/events.jsonl

The implementation is intentionally lightweight and defensive: failures to log
or broadcast must never break the actual task execution.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    waiting_approval = "waiting_approval"
    waiting_input = "waiting_input"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    timed_out = "timed_out"


@dataclass
class EvidenceRef:
    kind: str
    value: str
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "value": self.value, "summary": self.summary}


@dataclass
class RunStep:
    id: str
    title: str
    capability: str = ""
    status: str = "running"  # running|completed|failed|skipped
    started_at: str = field(default_factory=_utc_now_iso)
    ended_at: Optional[str] = None
    message: str = ""
    evidence: List[EvidenceRef] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "capability": self.capability,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "message": self.message,
            "evidence": [e.to_dict() for e in self.evidence],
            "meta": self.meta,
        }


@dataclass
class RunRecord:
    id: str
    session_id: str
    source: str
    user_text: str
    status: RunStatus = RunStatus.queued
    created_at: str = field(default_factory=_utc_now_iso)
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    error: str = ""
    steps: List[RunStep] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    cancel_requested: bool = False

    def summary(self) -> Dict[str, Any]:
        outcome_label = str(self.meta.get("phase15_outcome_label") or self.meta.get("outcome_label") or self.status.value)
        return {
            "id": self.id,
            "session_id": self.session_id,
            "source": self.source,
            "user_text": self.user_text,
            "status": self.status.value,
            "outcome_label": outcome_label,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "error": self.error,
            "result_summary": str(self.meta.get("result_summary") or "")[:2000],
            "receipt_path": str(self.meta.get("receipt_path") or ""),
            "steps_total": len(self.steps),
            "steps_completed": sum(1 for s in self.steps if s.status == "completed"),
        }


class _RunLane:
    """Per-session FIFO lane with a single active run."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self.queue: Deque[str] = deque()
        self.active_run_id: Optional[str] = None

    def enqueue(self, run_id: str) -> Tuple[int, int]:
        with self._cond:
            self.queue.append(run_id)
            return len(self.queue), (len(self.queue) + (1 if self.active_run_id else 0))

    def prioritize(self, run_id: str) -> None:
        """Move run_id to the front of the queue (best-effort)."""
        with self._cond:
            if run_id in self.queue:
                self.queue = deque([run_id] + [x for x in self.queue if x != run_id])
            self._cond.notify_all()

    def remove(self, run_id: str) -> None:
        with self._cond:
            if run_id in self.queue:
                self.queue = deque([x for x in self.queue if x != run_id])
            self._cond.notify_all()

    def acquire_turn(self, run_id: str, timeout_s: float = 0.0) -> bool:
        start = time.monotonic()
        with self._cond:
            while True:
                if self.active_run_id is None and self.queue and self.queue[0] == run_id:
                    self.active_run_id = run_id
                    self.queue.popleft()
                    return True
                if timeout_s and (time.monotonic() - start) >= timeout_s:
                    return False
                self._cond.wait(timeout=0.5)

    def release_turn(self, run_id: str) -> None:
        with self._cond:
            if self.active_run_id == run_id:
                self.active_run_id = None
            self._cond.notify_all()

    def snapshot(self) -> Dict[str, Any]:
        with self._cond:
            return {
                "active": self.active_run_id,
                "queued": list(self.queue),
                "queued_count": len(self.queue),
            }


class RunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: Dict[str, RunRecord] = {}
        self._lanes: Dict[str, _RunLane] = {}
        self._global_pending_confirmation_run_id: Optional[str] = None
        self._global_pending_input_run_id: Optional[str] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_stop = threading.Event()
        self._timeout_enabled: bool = False
        self._timeout_seconds: float = 0.0
        self._watchdog_interval: float = 60.0

        try:
            from chintu_backend.core.config import get_config

            cfg = get_config()
            self._runs_dir = Path(cfg.data_dir) / "runs"
            # Configure run-level timeout watchdog.
            self._timeout_seconds = float(getattr(cfg, "run_timeout_seconds", 0.0) or 0.0)
            self._timeout_enabled = bool(getattr(cfg, "run_timeout_enabled", True)) and self._timeout_seconds > 0
            self._watchdog_interval = float(getattr(cfg, "watchdog_interval_seconds", 60.0) or 60.0)
        except Exception:
            self._runs_dir = Path.home() / ".chintu" / "runs"
            self._timeout_enabled = False
            self._timeout_seconds = 0.0
            self._watchdog_interval = 60.0
        self._runs_dir.mkdir(parents=True, exist_ok=True)

        # Start lightweight watchdog thread for stale runs (best-effort).
        if self._timeout_enabled:
            self._start_watchdog()

    @staticmethod
    def _is_terminal(status: RunStatus) -> bool:
        return status in {RunStatus.completed, RunStatus.failed, RunStatus.cancelled, RunStatus.timed_out}

    def get_run_status_value(self, run_id: str) -> Optional[str]:
        record = self._runs.get(run_id)
        if not record:
            return None
        try:
            return record.status.value
        except Exception:
            return str(record.status)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------
    def create_run(
        self,
        *,
        session_id: str,
        source: str,
        user_text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> RunRecord:
        run_id = uuid.uuid4().hex
        record = RunRecord(
            id=run_id,
            session_id=session_id or "main",
            source=source or "unknown",
            user_text=(user_text or "").strip()[:2000],
            meta=dict(meta or {}),
        )
        with self._lock:
            self._runs[run_id] = record
            lane = self._lanes.get(record.session_id)
            if lane is None:
                lane = _RunLane()
                self._lanes[record.session_id] = lane
        pos, depth = self._lane(record.session_id).enqueue(run_id)
        self._emit_update(
            action="created",
            run=record.summary(),
            queue={"position": pos, "depth": depth, **self._lane(record.session_id).snapshot()},
        )
        return record

    def acquire_run_turn(self, run_id: str, *, timeout_s: float = 0.0) -> bool:
        record = self._runs.get(run_id)
        if not record:
            return False
        ok = self._lane(record.session_id).acquire_turn(run_id, timeout_s=timeout_s)
        if not ok:
            return False
        record.status = RunStatus.running
        record.started_at = record.started_at or _utc_now_iso()
        self._emit_update(action="started", run=record.summary(), queue=self._lane(record.session_id).snapshot())
        return True

    def release_run_turn(self, run_id: str) -> None:
        record = self._runs.get(run_id)
        if not record:
            return
        self._lane(record.session_id).release_turn(run_id)
        self._emit_update(action="lane.released", run=record.summary(), queue=self._lane(record.session_id).snapshot())

    def request_cancel(self, run_id: str, reason: str = "") -> None:
        record = self._runs.get(run_id)
        if not record:
            return
        record.cancel_requested = True
        record.error = record.error or (reason or "cancel requested")
        self._emit_update(action="cancel_requested", run=record.summary())

    def is_cancel_requested(self, run_id: str) -> bool:
        record = self._runs.get(run_id)
        return bool(record and record.cancel_requested)

    def mark_waiting_approval(
        self,
        run_id: str,
        prompt: str = "",
        capability: str = "",
        *,
        set_global_pending: bool = True,
    ) -> None:
        record = self._runs.get(run_id)
        if not record:
            return
        if self._is_terminal(record.status):
            return
        record.status = RunStatus.waiting_approval
        if set_global_pending:
            self._global_pending_confirmation_run_id = run_id
        self._emit_update(
            action="waiting_approval",
            run=record.summary(),
            event={"prompt": (prompt or "")[:2000], "capability": capability or ""},
        )

    def mark_waiting_input(
        self,
        run_id: str,
        prompt: str = "",
        capability: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mark a run as waiting for user input (not an approval decision)."""
        record = self._runs.get(run_id)
        if not record:
            return
        if self._is_terminal(record.status):
            return
        record.status = RunStatus.waiting_input
        self._global_pending_input_run_id = run_id
        waiting_ctx = {
            "prompt": (prompt or "")[:2000],
            "capability": capability or "",
        }
        if isinstance(meta, dict) and meta:
            safe_meta = {}
            for key, value in meta.items():
                if key in {
                    "site",
                    "url",
                    "awaiting_user_action_type",
                    "user_action",
                    "next_step",
                    "channel_name",
                    "profile",
                }:
                    safe_meta[str(key)] = value
            if safe_meta:
                waiting_ctx["meta"] = safe_meta
        record.meta["waiting_input_context"] = waiting_ctx
        self._emit_update(
            action="waiting_input",
            run=record.summary(),
            event=waiting_ctx,
        )

    def clear_waiting_approval(self, run_id: str) -> None:
        if self._global_pending_confirmation_run_id == run_id:
            self._global_pending_confirmation_run_id = None
        record = self._runs.get(run_id)
        if record and self._is_terminal(record.status):
            return
        if record and record.status == RunStatus.waiting_approval:
            record.status = RunStatus.running
            self._emit_update(action="resumed", run=record.summary())

    def pending_confirmation_run_id(self) -> Optional[str]:
        return self._global_pending_confirmation_run_id

    def clear_waiting_input(self, run_id: str) -> None:
        if self._global_pending_input_run_id == run_id:
            self._global_pending_input_run_id = None
        record = self._runs.get(run_id)
        if record and self._is_terminal(record.status):
            return
        if record and record.status == RunStatus.waiting_input:
            record.status = RunStatus.running
            self._emit_update(action="resumed", run=record.summary())

    def pending_input_run_id(self) -> Optional[str]:
        return self._global_pending_input_run_id

    def get_waiting_input_context(self, run_id: str) -> Dict[str, Any]:
        """Return stored waiting-input metadata for a run (best-effort)."""
        record = self._runs.get(run_id)
        if not record:
            return {}
        ctx = record.meta.get("waiting_input_context")
        if not isinstance(ctx, dict):
            return {}
        return dict(ctx)

    def cancel_active_run(self, session_id: str, reason: str = "") -> Optional[str]:
        """Best-effort: request cancellation for the currently active run in a session lane."""
        lane = self._lane(session_id)
        active = lane.snapshot().get("active")
        if not active:
            return None
        run_id = str(active)
        self.request_cancel(run_id, reason=reason or "cancelled by user")
        # Mark cancelled + release lane so the UI doesn't appear stuck.
        try:
            self.mark_cancelled(run_id, reason=reason or "cancelled by user")
        except Exception:
            pass
        try:
            self.release_run_turn(run_id)
        except Exception:
            pass
        return run_id

    def cancel_run(self, run_id: str, reason: str = "") -> bool:
        """Cancel a specific run id (used by UI run cancel)."""
        record = self._runs.get(run_id)
        if not record:
            return False
        self.request_cancel(run_id, reason=reason or "cancelled by user")
        try:
            self.mark_cancelled(run_id, reason=reason or "cancelled by user")
        except Exception:
            pass
        try:
            self.release_run_turn(run_id)
        except Exception:
            pass
        return True

    def enqueue_for_resume(self, run_id: str, *, prioritize: bool = True) -> bool:
        """Put an existing run back onto its lane so it can resume (used for confirmations)."""
        record = self._runs.get(run_id)
        if not record:
            return False
        lane = self._lane(record.session_id)
        snap = lane.snapshot()
        if snap.get("active") == run_id:
            return True
        if run_id not in (snap.get("queued") or []):
            lane.enqueue(run_id)
        if prioritize:
            lane.prioritize(run_id)
        self._emit_update(action="resume.enqueued", run=record.summary(), queue=lane.snapshot())
        return True

    def start_step(
        self,
        run_id: str,
        *,
        title: str,
        capability: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        record = self._runs.get(run_id)
        if not record:
            return ""
        step_id = uuid.uuid4().hex[:10]
        step = RunStep(id=step_id, title=(title or "").strip()[:240], capability=capability or "", meta=dict(meta or {}))
        record.steps.append(step)
        self._emit_update(action="step.started", run=record.summary(), step=step.to_dict())
        return step_id

    def end_step(
        self,
        run_id: str,
        step_id: str,
        *,
        status: str,
        message: str = "",
        capability: str = "",
        evidence: Optional[List[EvidenceRef]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = self._runs.get(run_id)
        if not record:
            return
        step = next((s for s in record.steps if s.id == step_id), None)
        if not step:
            return
        step.status = status
        step.ended_at = _utc_now_iso()
        if message:
            step.message = str(message)[:2000]
        if capability:
            step.capability = capability
        if evidence:
            step.evidence.extend(evidence)
        if meta:
            step.meta.update(meta)

        # Best-effort: index any screenshot/image evidence into long-term memory so it can
        # be retrieved later via memory_search (image RAG). This must never block or fail
        # the run lifecycle.
        try:
            if evidence:
                from chintu_backend.brain.memory.image_evidence_ingestor import get_image_evidence_ingestor

                get_image_evidence_ingestor().enqueue_from_evidence(
                    evidence,
                    run_id=str(run_id),
                    step_id=str(step_id),
                    capability=str(step.capability or capability or ""),
                )
        except Exception:
            pass
        self._emit_update(action="step.ended", run=record.summary(), step=step.to_dict())

    def find_last_step_id(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> str:
        """Return the most recent step id that matches the filters (best-effort)."""
        record = self._runs.get(run_id)
        if not record:
            return ""
        want_status = (status or "").strip()
        want_cap = (capability or "").strip()
        for step in reversed(record.steps):
            if want_status and str(step.status or "") != want_status:
                continue
            if want_cap and str(step.capability or "") != want_cap:
                continue
            return str(step.id or "")
        return ""

    def mark_completed(self, run_id: str, message: str = "", *, outcome_label: str = "") -> None:
        record = self._runs.get(run_id)
        if not record:
            return
        if self._is_terminal(record.status):
            return
        record.status = RunStatus.completed
        record.ended_at = _utc_now_iso()
        if self._global_pending_confirmation_run_id == run_id:
            self._global_pending_confirmation_run_id = None
        if self._global_pending_input_run_id == run_id:
            self._global_pending_input_run_id = None
        if message:
            record.meta["result_summary"] = str(message)[:2000]
        record.meta.pop("waiting_input_context", None)
        label = str(outcome_label or "completed_with_evidence").strip()
        if label:
            record.meta["phase15_outcome_label"] = label
        # Durable receipt (best-effort).
        try:
            self._write_run_receipt(run_id)
        except Exception:
            pass
        self._emit_update(action="completed", run=record.summary())
        try:
            self._sync_task_history(record, trigger="completed")
        except Exception:
            pass

    def mark_failed(
        self,
        run_id: str,
        error: str = "",
        *,
        outcome_label: str = "",
        unblock_plan: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = self._runs.get(run_id)
        if not record:
            return
        if self._is_terminal(record.status):
            return
        record.status = RunStatus.failed
        record.ended_at = _utc_now_iso()
        if self._global_pending_confirmation_run_id == run_id:
            self._global_pending_confirmation_run_id = None
        if self._global_pending_input_run_id == run_id:
            self._global_pending_input_run_id = None
        record.error = str(error or record.error or "failed")[:2000]
        label = str(outcome_label or "").strip()
        if not label and isinstance(unblock_plan, dict) and unblock_plan:
            label = "blocked_with_unblock_plan"
        if label:
            record.meta["phase15_outcome_label"] = label
        if isinstance(unblock_plan, dict) and unblock_plan:
            record.meta["phase15_unblock_plan"] = unblock_plan
        record.meta.pop("waiting_input_context", None)
        try:
            self._write_run_receipt(run_id)
        except Exception:
            pass
        self._emit_update(action="failed", run=record.summary())
        try:
            self._sync_task_history(record, trigger="failed")
        except Exception:
            pass

    def mark_cancelled(self, run_id: str, reason: str = "") -> None:
        record = self._runs.get(run_id)
        if not record:
            return
        if self._is_terminal(record.status):
            return
        record.status = RunStatus.cancelled
        record.ended_at = _utc_now_iso()
        record.error = str(reason or record.error or "cancelled")[:2000]
        record.meta.pop("waiting_input_context", None)
        self._lane(record.session_id).remove(run_id)
        if self._global_pending_confirmation_run_id == run_id:
            self._global_pending_confirmation_run_id = None
        if self._global_pending_input_run_id == run_id:
            self._global_pending_input_run_id = None
        try:
            self._write_run_receipt(run_id)
        except Exception:
            pass
        self._emit_update(action="cancelled", run=record.summary(), queue=self._lane(record.session_id).snapshot())
        try:
            self._sync_task_history(record, trigger="cancelled")
        except Exception:
            pass

    def mark_timed_out(self, run_id: str, reason: str = "") -> None:
        """Mark a run as timed out and free its lane."""
        record = self._runs.get(run_id)
        if not record:
            return
        if self._is_terminal(record.status):
            return
        record.status = RunStatus.timed_out
        record.ended_at = _utc_now_iso()
        record.error = str(reason or record.error or "timed out")[:2000]
        record.meta.pop("waiting_input_context", None)
        lane = self._lane(record.session_id)
        lane.remove(run_id)
        if self._global_pending_confirmation_run_id == run_id:
            self._global_pending_confirmation_run_id = None
        if self._global_pending_input_run_id == run_id:
            self._global_pending_input_run_id = None
        try:
            self._write_run_receipt(run_id)
        except Exception:
            pass
        self._emit_update(action="timed_out", run=record.summary(), queue=lane.snapshot())
        try:
            self._sync_task_history(record, trigger="timed_out")
        except Exception:
            pass
        # Best-effort: release the active turn if we own it.
        try:
            lane.release_turn(run_id)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------
    def snapshot(self, limit: int = 30) -> Dict[str, Any]:
        with self._lock:
            runs = list(self._runs.values())
            lanes = dict(self._lanes)
        # newest first
        runs_sorted = sorted(runs, key=lambda r: r.created_at, reverse=True)[: max(1, int(limit))]
        return {
            "runs": [r.summary() for r in runs_sorted],
            "lanes": {sid: lane.snapshot() for sid, lane in lanes.items()},
            "pending_confirmation_run_id": self._global_pending_confirmation_run_id,
            "pending_input_run_id": self._global_pending_input_run_id,
        }

    # ------------------------------------------------------------------
    # Evidence helpers
    # ------------------------------------------------------------------
    def write_artifact(self, run_id: str, name: str, content: str) -> Optional[str]:
        """Write a small artifact file to the run directory and return its path."""
        record = self._runs.get(run_id)
        if not record:
            return None
        safe_name = "".join(ch for ch in (name or "artifact.txt") if ch.isalnum() or ch in ("-", "_", ".", " ")).strip()
        if not safe_name:
            safe_name = "artifact.txt"
        run_dir = self._runs_dir / run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            path = run_dir / safe_name
            path.write_text(content or "", encoding="utf-8", errors="ignore")
            return str(path)
        except Exception:
            return None

    def record_escalation(
        self,
        run_id: str,
        *,
        reason_code: str,
        provider: str,
        mode: str,
        inputs: Dict[str, Any],
        returned_solution: Dict[str, Any],
        artifacts: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Attach a structured escalation record to a run and emit a lifecycle event."""
        record = self._runs.get(run_id)
        if not record:
            return
        safe_inputs = inputs if isinstance(inputs, dict) else {}
        safe_solution = returned_solution if isinstance(returned_solution, dict) else {}
        item: Dict[str, Any] = {
            "timestamp": _utc_now_iso(),
            "reason_code": str(reason_code or "unknown")[:120],
            "provider": str(provider or "unknown")[:80],
            "mode": str(mode or "sync")[:40],
            "inputs": safe_inputs,
            "returned_solution": safe_solution,
            "artifacts": [str(a) for a in (artifacts or []) if str(a).strip()][:10],
        }
        if isinstance(meta, dict) and meta:
            item["meta"] = dict(meta)
        escalations = record.meta.get("escalations")
        if not isinstance(escalations, list):
            escalations = []
            record.meta["escalations"] = escalations
        escalations.append(item)
        self._emit_update(action="escalation.logged", run=record.summary(), event=item)

    def record_persona_selection(
        self,
        run_id: str,
        *,
        persona: str,
        requested: str,
        reason: str,
        provider: str = "",
        adapter_path: str = "",
        adapter_ready: bool = True,
        fallback_to_default: bool = False,
        routing_tags: Optional[List[str]] = None,
    ) -> None:
        """Attach persona routing evidence to the run dossier."""
        record = self._runs.get(run_id)
        if not record:
            return
        item: Dict[str, Any] = {
            "timestamp": _utc_now_iso(),
            "persona": str(persona or "default")[:80],
            "requested": str(requested or persona or "default")[:80],
            "reason": str(reason or "")[:200],
            "provider": str(provider or "")[:80],
            "adapter_path": str(adapter_path or "")[:300],
            "adapter_ready": bool(adapter_ready),
            "fallback_to_default": bool(fallback_to_default),
            "routing_tags": [str(t) for t in (routing_tags or []) if str(t).strip()][:20],
        }
        personas = record.meta.get("persona_selections")
        if not isinstance(personas, list):
            personas = []
            record.meta["persona_selections"] = personas
        personas.append(item)
        self._emit_update(action="persona.logged", run=record.summary(), event=item)

    def _redact_for_receipt(self, text: str) -> str:
        raw = str(text or "")
        if not raw:
            return ""
        masked = raw
        try:
            from chintu_backend.privacy.pii import mask_pii

            masked = mask_pii(masked)
        except Exception:
            pass
        try:
            from chintu_backend.core.credential_detector import get_credential_detector

            detector = get_credential_detector()
            for cred in detector.detect_all(masked):
                if cred.value and cred.value in masked:
                    masked = masked.replace(cred.value, f"<redacted:{cred.service_name.lower()}>")
        except Exception:
            pass
        return masked

    def _write_run_receipt(self, run_id: str) -> Optional[str]:
        record = self._runs.get(run_id)
        if not record:
            return None
        try:
            existing = str(record.meta.get("receipt_path") or "").strip()
            if existing:
                return existing
        except Exception:
            pass

        # Build a compact, durable receipt for debugging + later training.
        try:
            lines: List[str] = []
            lines.append("# Run Receipt")
            lines.append("")
            lines.append(f"- run_id: {record.id}")
            lines.append(f"- session_id: {record.session_id}")
            lines.append(f"- source: {record.source}")
            lines.append(f"- status: {record.status.value}")
            if record.created_at:
                lines.append(f"- created_at: {record.created_at}")
            if record.started_at:
                lines.append(f"- started_at: {record.started_at}")
            if record.ended_at:
                lines.append(f"- ended_at: {record.ended_at}")
            if record.user_text:
                lines.append(f"- user_text: {self._redact_for_receipt(record.user_text)[:2000]}")
            if record.error:
                lines.append(f"- error: {self._redact_for_receipt(record.error)[:2000]}")
            result_summary = str(record.meta.get("result_summary") or "").strip()
            if result_summary:
                lines.append(f"- result_summary: {self._redact_for_receipt(result_summary)[:2000]}")
            personas = record.meta.get("persona_selections")
            if isinstance(personas, list) and personas:
                lines.append(f"- persona_selections: {len(personas)}")
            escalations = record.meta.get("escalations")
            if isinstance(escalations, list) and escalations:
                lines.append(f"- escalations: {len(escalations)}")
            lines.append("")
            if isinstance(personas, list) and personas:
                lines.append("## Personas")
                for p in personas[:40]:
                    if not isinstance(p, dict):
                        continue
                    lines.append("")
                    lines.append(f"- persona: {self._redact_for_receipt(str(p.get('persona') or 'default'))[:80]}")
                    lines.append(f"- requested: {self._redact_for_receipt(str(p.get('requested') or 'default'))[:80]}")
                    lines.append(f"- reason: {self._redact_for_receipt(str(p.get('reason') or ''))[:200]}")
                    provider = str(p.get("provider") or "").strip()
                    if provider:
                        lines.append(f"- provider: {self._redact_for_receipt(provider)[:80]}")
                    adapter = str(p.get("adapter_path") or "").strip()
                    if adapter:
                        lines.append(f"- adapter_path: {self._redact_for_receipt(adapter)[:260]}")
                    lines.append(f"- adapter_ready: {bool(p.get('adapter_ready', True))}")
                    lines.append(f"- fallback_to_default: {bool(p.get('fallback_to_default', False))}")
                lines.append("")
            if isinstance(escalations, list) and escalations:
                lines.append("## Escalations")
                for esc in escalations[:30]:
                    if not isinstance(esc, dict):
                        continue
                    lines.append("")
                    lines.append(
                        f"- reason_code: {self._redact_for_receipt(str(esc.get('reason_code') or 'unknown'))[:120]}"
                    )
                    lines.append(f"- provider: {self._redact_for_receipt(str(esc.get('provider') or 'unknown'))[:80]}")
                    lines.append(f"- mode: {self._redact_for_receipt(str(esc.get('mode') or 'sync'))[:40]}")
                    artifacts = esc.get("artifacts") if isinstance(esc.get("artifacts"), list) else []
                    if artifacts:
                        lines.append("- artifacts:")
                        for path in artifacts[:8]:
                            lines.append(f"  - {self._redact_for_receipt(str(path))[:260]}")
                lines.append("")
            lines.append("## Steps")
            if not record.steps:
                lines.append("(none)")
            for step in record.steps:
                lines.append("")
                lines.append(f"### {self._redact_for_receipt(step.title)[:240]}")
                lines.append(f"- step_id: {step.id}")
                if step.capability:
                    lines.append(f"- capability: {step.capability}")
                lines.append(f"- status: {step.status}")
                if step.started_at:
                    lines.append(f"- started_at: {step.started_at}")
                if step.ended_at:
                    lines.append(f"- ended_at: {step.ended_at}")
                if step.message:
                    lines.append(f"- message: {self._redact_for_receipt(step.message)[:2000]}")
                try:
                    verification = step.meta.get("verification") if isinstance(step.meta, dict) else None
                except Exception:
                    verification = None
                try:
                    failure_type = step.meta.get("failure_type") if isinstance(step.meta, dict) else None
                except Exception:
                    failure_type = None
                try:
                    execution_contract = step.meta.get("execution_contract") if isinstance(step.meta, dict) else None
                except Exception:
                    execution_contract = None
                if isinstance(verification, dict):
                    ok = verification.get("ok")
                    lines.append(f"- verification_ok: {bool(ok)}")
                    checks = verification.get("checks") or []
                    if isinstance(checks, list) and checks:
                        lines.append("- verification_checks:")
                        for chk in checks[:20]:
                            if not isinstance(chk, dict):
                                continue
                            kind = chk.get("kind")
                            c_ok = chk.get("ok")
                            detail = chk.get("detail") or ""
                            lines.append(f"  - {kind}: {bool(c_ok)} {self._redact_for_receipt(detail)[:200]}")
                if isinstance(execution_contract, dict):
                    hooks = execution_contract.get("verification_hooks") or []
                    artifacts = execution_contract.get("expected_artifacts") or []
                    lines.append(
                        "- execution_contract: "
                        + f"enforce={bool(execution_contract.get('enforce'))}, "
                        + f"hooks={','.join([str(h) for h in hooks])}, "
                        + f"artifacts={','.join([str(a) for a in artifacts])}"
                    )
                if failure_type:
                    lines.append(f"- failure_type: {self._redact_for_receipt(str(failure_type))[:120]}")
                if step.evidence:
                    lines.append("- evidence:")
                    for ev in step.evidence[:30]:
                        try:
                            lines.append(
                                f"  - {ev.kind}: {self._redact_for_receipt(ev.value)[:400]} {self._redact_for_receipt(ev.summary)[:120]}"
                            )
                        except Exception:
                            continue

            receipt = "\n".join(lines).strip() + "\n"
            path = self.write_artifact(run_id, "receipt.md", receipt)
            if path:
                record.meta["receipt_path"] = path
            return path
        except Exception:
            return None

    def _sync_task_history(self, record: RunRecord, *, trigger: str) -> None:
        try:
            from chintu_backend.core.task_history import get_task_history_manager

            get_task_history_manager().ingest_run_record(record, trigger=trigger)
        except Exception:
            return

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _lane(self, session_id: str) -> _RunLane:
        sid = session_id or "main"
        with self._lock:
            lane = self._lanes.get(sid)
            if lane is None:
                lane = _RunLane()
                self._lanes[sid] = lane
            return lane

    def _persist_event(self, run_id: str, payload: Dict[str, Any]) -> None:
        run_dir = self._runs_dir / run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            path = run_dir / "events.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
        except Exception:
            return

    def _emit_update(self, *, action: str, run: Dict[str, Any], step: Optional[Dict[str, Any]] = None, event: Optional[Dict[str, Any]] = None, queue: Optional[Dict[str, Any]] = None) -> None:
        now_ts = _utc_now_iso()
        payload: Dict[str, Any] = {
            "timestamp": now_ts,
            "action": action,
            "run": run,
        }
        if step is not None:
            payload["step"] = step
        if event is not None:
            payload["event"] = event
        if queue is not None:
            payload["queue"] = queue

        run_id = str(run.get("id") or "")
        if run_id:
            # Update in-memory last-activity timestamp for watchdog logic.
            try:
                record = self._runs.get(run_id)
                if record and isinstance(record.meta, dict):
                    record.meta["last_activity_at"] = now_ts
            except Exception:
                pass
            self._persist_event(run_id, payload)
            try:
                from chintu_backend.core.task_history import get_task_history_manager

                get_task_history_manager().record_run_update(payload)
            except Exception:
                pass

        # 1) EventBus (gateway bridge / other observers)
        try:
            from chintu_backend.core.events import get_event_bus, Event, EventType

            get_event_bus().publish_sync(Event(type=EventType.RUN_UPDATE, source="run_manager", data=payload))
        except Exception:
            pass

        # 2) Legacy WebSocket server (older UIs)
        try:
            from chintu_backend.core.websocket_server import get_ws_server

            server = get_ws_server()
            if server:
                loop = getattr(server, "_loop", None)
                if loop and loop.is_running():
                    import asyncio

                    asyncio.run_coroutine_threadsafe(server.broadcast_message({"type": "run_update", "data": payload}), loop)
        except Exception:
            pass

    def _emit_snapshot(self) -> None:
        snap = self.snapshot(limit=30)
        # EventBus
        try:
            from chintu_backend.core.events import get_event_bus, Event, EventType

            get_event_bus().publish_sync(Event(type=EventType.RUN_SNAPSHOT, source="run_manager", data=snap))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Watchdog (run-level timeouts)
    # ------------------------------------------------------------------
    def _start_watchdog(self) -> None:
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return
        self._watchdog_stop.clear()
        thread = threading.Thread(target=self._watchdog_loop, daemon=True, name="RunManagerWatchdog")
        self._watchdog_thread = thread
        thread.start()

    def _watchdog_loop(self) -> None:
        """Background loop that marks long-running, inactive runs as timed out."""
        while not self._watchdog_stop.is_set():
            try:
                self._check_timeouts()
            except Exception:
                # Watchdog must never crash the process.
                pass
            # Interruptible sleep
            self._watchdog_stop.wait(self._watchdog_interval)

    def _check_timeouts(self) -> None:
        """Scan for runs that have exceeded the configured timeout."""
        if not self._timeout_enabled or self._timeout_seconds <= 0:
            return
        try:
            from datetime import datetime as _dt
        except Exception:
            return

        with self._lock:
            records = list(self._runs.values())

        now = _dt.now(timezone.utc)
        for record in records:
            try:
                if record.status != RunStatus.running:
                    continue
                # Prefer explicit last_activity_at if present, then started_at, then created_at.
                last_iso = ""
                try:
                    if isinstance(record.meta, dict):
                        last_iso = str(record.meta.get("last_activity_at") or "").strip()
                except Exception:
                    last_iso = ""
                if not last_iso:
                    last_iso = record.started_at or record.created_at or ""
                if not last_iso:
                    continue
                try:
                    # Support both Z-suffixed and offset-less ISO strings.
                    if last_iso.endswith("Z"):
                        last_dt = _dt.fromisoformat(last_iso.replace("Z", "+00:00"))
                    else:
                        last_dt = _dt.fromisoformat(last_iso)
                except Exception:
                    continue
                elapsed = (now - last_dt).total_seconds()
                if elapsed >= self._timeout_seconds:
                    reason = f"Run exceeded timeout of {int(self._timeout_seconds)}s (no activity for {int(elapsed)}s)."
                    self.mark_timed_out(record.id, reason=reason)
            except Exception:
                # Never let one bad record stop others from being checked.
                continue
        # Legacy WS
        try:
            from chintu_backend.core.websocket_server import get_ws_server

            server = get_ws_server()
            if server:
                loop = getattr(server, "_loop", None)
                if loop and loop.is_running():
                    import asyncio

                    asyncio.run_coroutine_threadsafe(server.broadcast_message({"type": "run_snapshot", "data": snap}), loop)
        except Exception:
            pass


_manager: Optional[RunManager] = None


def get_run_manager() -> RunManager:
    global _manager
    if _manager is None:
        _manager = RunManager()
    return _manager
