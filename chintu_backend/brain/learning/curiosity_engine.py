"""Curiosity engine + scheduled learning orchestration (Phase 22)."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_ts(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class CuriosityEngine:
    """Runs daily knowledge refresh + periodic learning proposals."""

    def __init__(self) -> None:
        self.config = get_config()
        self.enabled = bool(getattr(self.config, "curiosity_enabled", True))
        self.daily_enabled = bool(getattr(self.config, "curiosity_daily_enabled", True))
        self.daily_hour = int(getattr(self.config, "curiosity_daily_hour", 7) or 7)
        self.state_path = Path(getattr(self.config, "curiosity_state_path"))
        self.runs_dir = Path(getattr(self.config, "curiosity_runs_dir"))
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if not self.enabled or not self.daily_enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="CuriosityDaily")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def status(self) -> Dict[str, Any]:
        state = self._load_state()
        return {
            "enabled": self.enabled,
            "daily_enabled": self.daily_enabled,
            "daily_hour": self.daily_hour,
            "running": bool(self._thread and self._thread.is_alive()),
            "last_run_utc": str(state.get("last_run_utc") or ""),
            "last_daily_date": str(state.get("last_daily_date") or ""),
            "last_biweekly_proposal_utc": str(state.get("last_biweekly_proposal_utc") or ""),
            "last_run_path": str(state.get("last_run_path") or ""),
            "state_path": str(self.state_path),
            "runs_dir": str(self.runs_dir),
        }

    def run_cycle(self, *, reason: str = "manual", categories: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "message": "Curiosity engine is disabled."}

        with self._lock:
            state = self._load_state()
            run_payload: Dict[str, Any] = {
                "ok": True,
                "reason": str(reason or "manual"),
                "started_at_utc": _utc_now_iso(),
                "categories": [
                    str(c).strip().lower()
                    for c in (categories or getattr(self.config, "curiosity_daily_categories", ["tech", "finance", "healthcare"]))
                    if str(c).strip()
                ],
                "steps": {},
            }

            if not run_payload["categories"]:
                run_payload["categories"] = ["tech", "finance", "healthcare"]

            # Step 1: ingest Telegram inbox queue (optional).
            run_payload["steps"]["telegram_inbox"] = self._process_telegram_inbox()

            # Step 2: refresh daily knowledge.
            run_payload["steps"]["knowledge_refresh"] = self._refresh_knowledge(run_payload["categories"])

            # Step 3: refresh model catalog/provider view.
            run_payload["steps"]["model_catalog"] = self._refresh_model_catalog()

            # Step 4: bi-weekly fine-tune proposal (gated, proposal-only).
            run_payload["steps"]["biweekly_proposal"] = self._maybe_create_biweekly_proposal(state)

            run_payload["completed_at_utc"] = _utc_now_iso()
            run_path = self._write_run_artifact(run_payload)
            state.update(
                {
                    "last_run_utc": run_payload["completed_at_utc"],
                    "last_run_path": str(run_path),
                    "last_daily_date": _utc_now().date().isoformat(),
                }
            )
            proposal = run_payload["steps"].get("biweekly_proposal")
            if isinstance(proposal, dict) and proposal.get("proposed"):
                state["last_biweekly_proposal_utc"] = run_payload["completed_at_utc"]
            self._save_state(state)
            return run_payload

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                now = datetime.now()
                state = self._load_state()
                today = now.date().isoformat()
                if now.hour == self.daily_hour and state.get("last_daily_date") != today:
                    self.run_cycle(reason="scheduled_daily")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Curiosity scheduler loop error: %s", exc)
            self._stop_event.wait(300)

    def _process_telegram_inbox(self) -> Dict[str, Any]:
        if not bool(getattr(self.config, "curiosity_process_telegram_inbox", True)):
            return {"ok": True, "enabled": False, "processed_count": 0}
        try:
            from chintu_backend.channels.telegram_inbox import get_telegram_inbox_manager

            manager = get_telegram_inbox_manager()
            batch_size = int(getattr(self.config, "telegram_inbox_process_batch_size", 5) or 5)
            result = manager.process_pending(max_items=batch_size)
            return {
                "ok": bool(result.get("ok", False)),
                "enabled": True,
                "processed_count": int(result.get("processed_count") or 0),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "enabled": True, "error": str(exc)}

    def _refresh_knowledge(self, categories: Sequence[str]) -> Dict[str, Any]:
        try:
            from chintu_backend.brain.knowledge.knowledge_updater import get_knowledge_updater

            updater = get_knowledge_updater()
            ingest = updater.ingest_daily_updates(categories=categories, include_model_releases=True)
            digest = updater.build_daily_digest(total=20, categories=categories)
            return {
                "ok": True,
                "ingested_count": int(ingest.get("ingested_count") or 0),
                "digest_id": str(digest.get("digest_id") or ""),
                "digest_count": len(digest.get("items") or []),
                "vector_backend": str(ingest.get("vector_backend") or ""),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _refresh_model_catalog(self) -> Dict[str, Any]:
        if not bool(getattr(self.config, "curiosity_model_catalog_refresh", True)):
            return {"ok": True, "enabled": False}
        try:
            from chintu_backend.core.model_catalog import get_model_catalog_updater

            snapshot = get_model_catalog_updater().refresh(fetch_releases=True, write_memory=True)
            return {
                "ok": True,
                "enabled": True,
                "catalog_path": str(snapshot.get("catalog_path") or ""),
                "release_updates": len(snapshot.get("release_updates") or []),
                "local_models": len(snapshot.get("local_models") or []),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "enabled": True, "error": str(exc)}

    def _maybe_create_biweekly_proposal(self, state: Dict[str, Any]) -> Dict[str, Any]:
        last = _parse_ts(str(state.get("last_biweekly_proposal_utc") or ""))
        if last and (_utc_now() - last) < timedelta(days=14):
            return {
                "ok": True,
                "proposed": False,
                "reason": "cooldown_active",
                "next_eligible_utc": (last + timedelta(days=14)).isoformat().replace("+00:00", "Z"),
            }

        try:
            from chintu_backend.brain.learning.weekly_trainer import get_biweekly_learning_status

            status = get_biweekly_learning_status()
            proposal = {
                "ok": True,
                "proposed": True,
                "requires_approval": True,
                "message": "Bi-weekly fine-tune candidate is ready for approval review.",
                "status_snapshot": status,
            }
            return proposal
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "proposed": False, "error": str(exc)}

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(state, indent=2, ensure_ascii=True), encoding="utf-8")

    def _write_run_artifact(self, payload: Dict[str, Any]) -> Path:
        stamp = _utc_now().strftime("%Y%m%d_%H%M%S")
        out = self.runs_dir / f"curiosity_{stamp}.json"
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return out


_curiosity_engine: Optional[CuriosityEngine] = None


def get_curiosity_engine() -> CuriosityEngine:
    global _curiosity_engine
    if _curiosity_engine is None:
        _curiosity_engine = CuriosityEngine()
    return _curiosity_engine
