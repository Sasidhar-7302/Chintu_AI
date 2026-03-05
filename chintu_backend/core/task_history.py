"""Phase 5 task history, dossier indexing, and training export pipeline."""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "")
    if not text:
        return ""
    masked = text
    try:
        from chintu_backend.privacy.pii import mask_pii

        masked = mask_pii(masked)
    except Exception:
        masked = text

    masked = re.sub(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s\]\}\),;]+", r"\1=<redacted>", masked)
    masked = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}", r"\1<redacted>", masked)
    masked = re.sub(r"(?i)(authorization\s*[:=]\s*)[^\s\]\}\),;]+", r"\1<redacted>", masked)
    if len(masked) > limit:
        return masked[:limit].rstrip() + "..."
    return masked


class TaskHistoryManager:
    """Maintains unified history events, run dossiers, and retrieval/training exports."""

    def __init__(self, config: Optional[Any] = None) -> None:
        if config is None:
            from chintu_backend.core.config import get_config

            config = get_config()
        self.config = config
        self.enabled = bool(getattr(config, "task_history_enabled", True))

        base_dir = Path(getattr(config, "data_dir", Path.home() / ".chintu"))
        self.events_path = Path(getattr(config, "history_event_store_path", base_dir / "history" / "events.jsonl"))
        self.dossiers_dir = Path(getattr(config, "task_dossiers_dir", base_dir / "history" / "dossiers"))
        self.index_path = Path(getattr(config, "task_history_index_path", base_dir / "history" / "dossier_index.sqlite3"))
        self.runs_dir = base_dir / "runs"
        self.sessions_dir = base_dir / "sessions"
        self.training_exports_dir = Path(getattr(config, "training_exports_dir", base_dir / "training" / "exports"))

        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.dossiers_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.training_exports_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._init_index()

    def record_conversation_turn(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return
        payload = {
            "timestamp": _utc_now_iso(),
            "event_type": "conversation_turn",
            "session_id": str(session_id or "main"),
            "run_id": str((meta or {}).get("run_id") or ""),
            "role": str(role or "unknown"),
            "content": _safe_text(content, limit=3000),
            "meta": self._sanitize_meta(meta or {}),
        }
        self._append_event(payload)

    def record_run_update(self, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        if not isinstance(payload, dict):
            return

        run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
        step = payload.get("step") if isinstance(payload.get("step"), dict) else {}
        action = str(payload.get("action") or "")

        artifacts: List[str] = []
        evidence = step.get("evidence") if isinstance(step, dict) else None
        if isinstance(evidence, list):
            for row in evidence:
                if not isinstance(row, dict):
                    continue
                value = str(row.get("value") or "").strip()
                if value:
                    artifacts.append(value)

        event = {
            "timestamp": str(payload.get("timestamp") or _utc_now_iso()),
            "event_type": "execution_event",
            "action": action,
            "run_id": str(run.get("id") or ""),
            "session_id": str(run.get("session_id") or "main"),
            "outcome_label": str(run.get("outcome_label") or run.get("status") or ""),
            "prompt": _safe_text(run.get("user_text") or "", limit=2000),
            "plan_step": _safe_text(step.get("title") or "", limit=800),
            "tool_call": str(step.get("capability") or ""),
            "output": _safe_text(step.get("message") or run.get("result_summary") or run.get("error") or "", limit=2400),
            "artifacts": artifacts[:20],
            "payload": self._sanitize_payload(payload),
        }
        self._append_event(event)

    def ingest_run_record(self, record: Any, *, trigger: str = "") -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None

        run = self._run_record_to_dict(record)
        run_id = str(run.get("id") or "").strip()
        if not run_id:
            return None

        dossier = self._build_dossier(run, trigger=trigger)
        dossier_path = self.dossiers_dir / f"{run_id}.json"
        with self._lock:
            dossier_path.write_text(json.dumps(dossier, indent=2, ensure_ascii=True), encoding="utf-8")
        self._upsert_index(dossier, dossier_path)

        self._append_event(
            {
                "timestamp": _utc_now_iso(),
                "event_type": "dossier_upserted",
                "run_id": run_id,
                "session_id": str(run.get("session_id") or "main"),
                "outcome_label": str(self._resolve_outcome_label(run)),
                "dossier_path": str(dossier_path),
                "trigger": str(trigger or "runtime"),
            }
        )
        return dossier

    def reindex_existing_runs(self, *, limit: int = 0) -> Dict[str, Any]:
        if not self.enabled:
            return {"success": False, "reason": "disabled"}

        runs_dir = self.runs_dir
        if not runs_dir.exists():
            return {"success": True, "indexed": 0, "skipped": 0}

        indexed = 0
        skipped = 0
        run_dirs = sorted([p for p in runs_dir.iterdir() if p.is_dir()], key=lambda p: p.name)
        if limit and limit > 0:
            run_dirs = run_dirs[-int(limit) :]

        for run_dir in run_dirs:
            snapshot = self._build_run_snapshot_from_events(run_dir)
            if not snapshot:
                skipped += 1
                continue
            try:
                self.ingest_run_record(snapshot, trigger="reindex")
                indexed += 1
            except Exception:
                skipped += 1
        return {"success": True, "indexed": indexed, "skipped": skipped}

    def query_dossiers(self, query: str, *, limit: int = 5, session_id: str = "") -> List[Dict[str, Any]]:
        text = str(query or "").strip().lower()
        if not text:
            return []

        candidates = self._load_index_candidates(session_id=session_id)
        tokens = [t for t in re.findall(r"[a-z0-9_]+", text) if len(t) > 2]

        ranked: List[Dict[str, Any]] = []
        for row in candidates:
            searchable = str(row.get("searchable_text") or "").lower()
            score = 0.0
            if text in searchable:
                score += 5.0
            for token in tokens:
                if token in searchable:
                    score += 1.0
            if score <= 0:
                continue
            row_copy = dict(row)
            row_copy["score"] = score
            ranked.append(row_copy)

        ranked.sort(key=lambda item: (float(item.get("score") or 0.0), str(item.get("created_at") or "")), reverse=True)

        results: List[Dict[str, Any]] = []
        for row in ranked[: max(1, int(limit))]:
            provenance = {}
            try:
                raw = str(row.get("provenance_json") or "")
                provenance = json.loads(raw) if raw else {}
            except Exception:
                provenance = {}
            results.append(
                {
                    "run_id": str(row.get("run_id") or ""),
                    "session_id": str(row.get("session_id") or ""),
                    "status": str(row.get("status") or ""),
                    "created_at": str(row.get("created_at") or ""),
                    "ended_at": str(row.get("ended_at") or ""),
                    "intent": str(row.get("intent") or ""),
                    "final_result": str(row.get("final_result") or ""),
                    "lessons": str(row.get("lessons") or ""),
                    "dossier_path": str(row.get("dossier_path") or ""),
                    "provenance": provenance,
                    "score": float(row.get("score") or 0.0),
                }
            )
        return results

    def answer_history_question(self, query: str, *, limit: int = 3, session_id: str = "") -> Dict[str, Any]:
        matches = self.query_dossiers(query, limit=limit, session_id=session_id)
        if not matches:
            return {
                "message": "I could not find matching task history yet. Ask me to run a task first so I can store a dossier.",
                "matches": [],
            }

        lines: List[str] = ["Here are the closest task-history matches with provenance:"]
        for idx, row in enumerate(matches, start=1):
            rid = row.get("run_id", "")
            short_id = rid[:8] if rid else "unknown"
            intent = row.get("intent") or "(no intent captured)"
            result = row.get("final_result") or "(no final result captured)"
            status = row.get("status") or "unknown"
            provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
            receipt = str(provenance.get("receipt_path") or "")
            dossier = row.get("dossier_path") or str(provenance.get("dossier_path") or "")
            lines.append(
                f"{idx}. Run {short_id} ({status}): {intent}\n"
                f"   Result: {result}\n"
                f"   Provenance: dossier={dossier} receipt={receipt}"
            )

        return {
            "message": "\n".join(lines),
            "matches": matches,
        }

    def export_training_bundle(self, *, limit: int = 300) -> Dict[str, Any]:
        rows = self._load_index_candidates(session_id="")
        rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        rows = rows[: max(1, int(limit))]

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        chat_path = self.training_exports_dir / f"phase5_chat_{stamp}.jsonl"
        rag_path = self.training_exports_dir / f"phase5_rag_{stamp}.jsonl"
        manifest_path = self.training_exports_dir / f"phase5_manifest_{stamp}.json"

        chat_rows: List[Dict[str, Any]] = []
        rag_rows: List[Dict[str, Any]] = []

        for row in rows:
            intent = _safe_text(row.get("intent") or "", limit=1800)
            final_result = _safe_text(row.get("final_result") or "", limit=2200)
            lessons = _safe_text(row.get("lessons") or "", limit=1200)
            if intent and final_result:
                chat_rows.append(
                    {
                        "messages": [
                            {"role": "user", "content": intent},
                            {"role": "assistant", "content": final_result},
                        ],
                        "metadata": {
                            "run_id": str(row.get("run_id") or ""),
                            "session_id": str(row.get("session_id") or ""),
                            "status": str(row.get("status") or ""),
                            "source": "task_dossier",
                        },
                    }
                )

            snippet = "\n".join(
                part
                for part in (
                    f"Intent: {intent}" if intent else "",
                    f"Result: {final_result}" if final_result else "",
                    f"Lessons: {lessons}" if lessons else "",
                )
                if part
            ).strip()
            if snippet:
                rag_rows.append(
                    {
                        "text": snippet,
                        "metadata": {
                            "run_id": str(row.get("run_id") or ""),
                            "session_id": str(row.get("session_id") or ""),
                            "status": str(row.get("status") or ""),
                            "dossier_path": str(row.get("dossier_path") or ""),
                        },
                    }
                )

        self._write_jsonl(chat_path, chat_rows)
        self._write_jsonl(rag_path, rag_rows)

        manifest = {
            "generated_at": _utc_now_iso(),
            "chat_path": str(chat_path),
            "rag_path": str(rag_path),
            "counts": {
                "dossiers_considered": len(rows),
                "chat": len(chat_rows),
                "rag": len(rag_rows),
            },
            "source": "task_history_index",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")

        self._copy_latest(chat_path, self.training_exports_dir / "latest_phase5_chat.jsonl")
        self._copy_latest(rag_path, self.training_exports_dir / "latest_phase5_rag.jsonl")
        self._copy_latest(manifest_path, self.training_exports_dir / "latest_phase5_manifest.json")

        return {
            "chat_path": str(chat_path),
            "rag_path": str(rag_path),
            "manifest_path": str(manifest_path),
            "chat_count": len(chat_rows),
            "rag_count": len(rag_rows),
            "dossiers_considered": len(rows),
        }

    def _init_index(self) -> None:
        with sqlite3.connect(self.index_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dossiers (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    source TEXT,
                    status TEXT,
                    created_at TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    intent TEXT,
                    final_result TEXT,
                    lessons TEXT,
                    capabilities TEXT,
                    evidence_count INTEGER,
                    dossier_path TEXT,
                    provenance_json TEXT,
                    searchable_text TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dossiers_created ON dossiers(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dossiers_session ON dossiers(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dossiers_status ON dossiers(status)")
            conn.commit()

    def _append_event(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def _sanitize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
        step = payload.get("step") if isinstance(payload.get("step"), dict) else {}
        return {
            "action": str(payload.get("action") or ""),
            "run": {
                "id": str(run.get("id") or ""),
                "session_id": str(run.get("session_id") or ""),
                "status": str(run.get("status") or ""),
            },
            "step": {
                "id": str(step.get("id") or ""),
                "title": _safe_text(step.get("title") or "", limit=240),
                "capability": str(step.get("capability") or ""),
                "status": str(step.get("status") or ""),
                "message": _safe_text(step.get("message") or "", limit=800),
                "evidence": self._sanitize_evidence(step.get("evidence")),
            },
        }

    def _sanitize_meta(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        safe: Dict[str, Any] = {}
        for key, value in (meta or {}).items():
            if value is None:
                continue
            key_text = str(key)
            if isinstance(value, (dict, list)):
                safe[key_text] = _safe_text(json.dumps(value, ensure_ascii=True), limit=600)
            else:
                safe[key_text] = _safe_text(value, limit=600)
        return safe

    def _sanitize_evidence(self, rows: Any) -> List[Dict[str, str]]:
        safe_rows: List[Dict[str, str]] = []
        if not isinstance(rows, list):
            return safe_rows
        for row in rows[:20]:
            if not isinstance(row, dict):
                continue
            safe_rows.append(
                {
                    "kind": str(row.get("kind") or ""),
                    "value": _safe_text(row.get("value") or "", limit=500),
                    "summary": _safe_text(row.get("summary") or "", limit=200),
                }
            )
        return safe_rows

    def _run_record_to_dict(self, record: Any) -> Dict[str, Any]:
        if isinstance(record, dict):
            payload = dict(record)
        else:
            payload = {
                "id": getattr(record, "id", ""),
                "session_id": getattr(record, "session_id", ""),
                "source": getattr(record, "source", ""),
                "user_text": getattr(record, "user_text", ""),
                "status": str(getattr(getattr(record, "status", ""), "value", getattr(record, "status", ""))),
                "created_at": getattr(record, "created_at", ""),
                "started_at": getattr(record, "started_at", ""),
                "ended_at": getattr(record, "ended_at", ""),
                "error": getattr(record, "error", ""),
                "meta": getattr(record, "meta", {}) or {},
                "steps": [],
            }
            for step in list(getattr(record, "steps", []) or []):
                payload["steps"].append(
                    {
                        "id": getattr(step, "id", ""),
                        "title": getattr(step, "title", ""),
                        "capability": getattr(step, "capability", ""),
                        "status": getattr(step, "status", ""),
                        "started_at": getattr(step, "started_at", ""),
                        "ended_at": getattr(step, "ended_at", ""),
                        "message": getattr(step, "message", ""),
                        "meta": getattr(step, "meta", {}) or {},
                        "evidence": [
                            {
                                "kind": getattr(ev, "kind", ""),
                                "value": getattr(ev, "value", ""),
                                "summary": getattr(ev, "summary", ""),
                            }
                            for ev in list(getattr(step, "evidence", []) or [])
                        ],
                    }
                )

        payload.setdefault("meta", {})
        payload.setdefault("steps", [])
        return payload

    def _build_dossier(self, run: Dict[str, Any], *, trigger: str = "") -> Dict[str, Any]:
        run_id = str(run.get("id") or "")
        session_id = str(run.get("session_id") or "main")
        run_dir = self.runs_dir / run_id
        events_path = run_dir / "events.jsonl"
        transcript_path = self.sessions_dir / session_id / "transcript.jsonl"

        steps = self._normalize_steps(run.get("steps"))
        run_events = self._read_jsonl(events_path)

        if not steps:
            steps = self._extract_steps_from_events(run_events)

        evidence = self._collect_evidence(steps)
        capabilities = sorted({str(step.get("capability") or "").strip() for step in steps if str(step.get("capability") or "").strip()})

        created_at = str(run.get("created_at") or "")
        ended_at = str(run.get("ended_at") or "")
        transcript_turns = self._collect_transcript_turns(
            transcript_path,
            created_at=created_at,
            ended_at=ended_at,
            limit=14,
        )

        meta = run.get("meta") if isinstance(run.get("meta"), dict) else {}
        final_result = _safe_text(meta.get("result_summary") or "", limit=2200)
        if not final_result:
            for step in reversed(steps):
                if step.get("status") == "completed" and step.get("message"):
                    final_result = _safe_text(step.get("message"), limit=2200)
                    break
        if not final_result:
            final_result = _safe_text(run.get("error") or "", limit=2200)

        run_status = str(run.get("status") or "")
        lessons = self._derive_lessons(steps, status=run_status, final_result=final_result)
        outcome_label = self._resolve_outcome_label(run)

        receipt_path = str(meta.get("receipt_path") or "")
        if not receipt_path:
            candidate = run_dir / "receipt.md"
            if candidate.exists():
                receipt_path = str(candidate)

        dossier = {
            "schema_version": "phase5.v1",
            "generated_at": _utc_now_iso(),
            "run": {
                "id": run_id,
                "session_id": session_id,
                "source": str(run.get("source") or ""),
                "status": run_status,
                "outcome_label": outcome_label,
                "created_at": created_at,
                "started_at": str(run.get("started_at") or ""),
                "ended_at": ended_at,
                "intent": _safe_text(run.get("user_text") or "", limit=2200),
                "error": _safe_text(run.get("error") or "", limit=2000),
            },
            "plan": [
                {
                    "step_id": str(step.get("id") or ""),
                    "title": _safe_text(step.get("title") or "", limit=320),
                    "capability": str(step.get("capability") or ""),
                    "status": str(step.get("status") or ""),
                    "message": _safe_text(step.get("message") or "", limit=1800),
                    "started_at": str(step.get("started_at") or ""),
                    "ended_at": str(step.get("ended_at") or ""),
                    "failure_type": str((step.get("meta") or {}).get("failure_type") or ""),
                    "verification": (step.get("meta") or {}).get("verification") if isinstance(step.get("meta"), dict) else {},
                }
                for step in steps
            ],
            "execution_events": [
                {
                    "timestamp": str(event.get("timestamp") or ""),
                    "action": str(event.get("action") or ""),
                    "step_id": str((event.get("step") or {}).get("id") or ""),
                    "capability": str((event.get("step") or {}).get("capability") or ""),
                    "status": str(((event.get("step") or {}).get("status") or (event.get("run") or {}).get("status") or "")),
                }
                for event in run_events
            ],
            "tool_calls": capabilities,
            "evidence": evidence,
            "outputs": {
                "final_result": final_result,
                "result_summary": _safe_text(meta.get("result_summary") or "", limit=2200),
            },
            "lessons": lessons,
            "conversation": transcript_turns,
            "provenance": {
                "events_path": str(events_path) if events_path.exists() else "",
                "receipt_path": receipt_path,
                "transcript_path": str(transcript_path) if transcript_path.exists() else "",
                "trigger": str(trigger or "runtime"),
            },
            "outcome_label": outcome_label,
        }
        return dossier

    def _normalize_steps(self, steps_raw: Any) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not isinstance(steps_raw, list):
            return rows
        for step in steps_raw:
            if not isinstance(step, dict):
                continue
            rows.append(
                {
                    "id": str(step.get("id") or ""),
                    "title": str(step.get("title") or ""),
                    "capability": str(step.get("capability") or ""),
                    "status": str(step.get("status") or ""),
                    "started_at": str(step.get("started_at") or ""),
                    "ended_at": str(step.get("ended_at") or ""),
                    "message": str(step.get("message") or ""),
                    "meta": step.get("meta") if isinstance(step.get("meta"), dict) else {},
                    "evidence": self._sanitize_evidence(step.get("evidence") or []),
                }
            )
        return rows

    def _extract_steps_from_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        steps: Dict[str, Dict[str, Any]] = {}
        for event in events:
            step = event.get("step") if isinstance(event.get("step"), dict) else None
            if not step:
                continue
            step_id = str(step.get("id") or "").strip()
            if not step_id:
                continue
            current = steps.get(step_id, {"id": step_id, "meta": {}, "evidence": []})
            current.update(
                {
                    "title": str(step.get("title") or current.get("title") or ""),
                    "capability": str(step.get("capability") or current.get("capability") or ""),
                    "status": str(step.get("status") or current.get("status") or ""),
                    "started_at": str(step.get("started_at") or current.get("started_at") or ""),
                    "ended_at": str(step.get("ended_at") or current.get("ended_at") or ""),
                    "message": str(step.get("message") or current.get("message") or ""),
                }
            )
            meta = step.get("meta") if isinstance(step.get("meta"), dict) else {}
            if meta:
                base = current.get("meta") if isinstance(current.get("meta"), dict) else {}
                merged = dict(base)
                merged.update(meta)
                current["meta"] = merged
            evidence = self._sanitize_evidence(step.get("evidence") or [])
            if evidence:
                existing = current.get("evidence") if isinstance(current.get("evidence"), list) else []
                current["evidence"] = existing + evidence
            steps[step_id] = current
        return [steps[key] for key in sorted(steps.keys())]

    def _collect_evidence(self, steps: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        seen = set()
        for step in steps:
            for ev in step.get("evidence") if isinstance(step.get("evidence"), list) else []:
                if not isinstance(ev, dict):
                    continue
                kind = str(ev.get("kind") or "")
                value = str(ev.get("value") or "")
                key = (kind, value)
                if not value or key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "kind": kind,
                        "value": _safe_text(value, limit=400),
                        "summary": _safe_text(ev.get("summary") or "", limit=200),
                    }
                )
        return rows

    def _collect_transcript_turns(
        self,
        transcript_path: Path,
        *,
        created_at: str,
        ended_at: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        rows = self._read_jsonl(transcript_path)
        if not rows:
            return []

        start_dt = _parse_iso(created_at)
        end_dt = _parse_iso(ended_at)

        filtered: List[Dict[str, Any]] = []
        for row in rows:
            ts = _parse_iso(str(row.get("ts") or ""))
            if start_dt and ts and ts < start_dt:
                continue
            if end_dt and ts and ts > end_dt:
                continue
            filtered.append(row)

        if not filtered:
            filtered = rows[-limit:]
        else:
            filtered = filtered[-limit:]

        out: List[Dict[str, Any]] = []
        for row in filtered:
            out.append(
                {
                    "ts": str(row.get("ts") or ""),
                    "role": str(row.get("role") or ""),
                    "content": _safe_text(row.get("content") or "", limit=1200),
                    "meta": self._sanitize_meta(row.get("meta") if isinstance(row.get("meta"), dict) else {}),
                }
            )
        return out

    def _derive_lessons(self, steps: List[Dict[str, Any]], *, status: str, final_result: str) -> List[str]:
        lessons: List[str] = []
        total = len(steps)
        completed = sum(1 for step in steps if str(step.get("status") or "") == "completed")

        if status == "completed":
            lessons.append(f"Completed successfully with {completed}/{total} steps marked completed.")
            if any(bool((step.get("meta") or {}).get("dependency_recovery")) for step in steps):
                lessons.append("Recovered from a missing dependency during execution and resumed automatically.")
        elif status:
            lessons.append(f"Run finished with status '{status}'.")

        failure_types = []
        for step in steps:
            meta = step.get("meta") if isinstance(step.get("meta"), dict) else {}
            ftype = str(meta.get("failure_type") or "").strip()
            if ftype and ftype not in failure_types:
                failure_types.append(ftype)
        if failure_types:
            lessons.append("Failure categories observed: " + ", ".join(failure_types[:4]) + ".")

        if final_result:
            lessons.append("Final result captured with provenance in the run dossier.")
        else:
            lessons.append("No final result summary was captured; check step evidence in the dossier.")

        return lessons[:4]

    def _upsert_index(self, dossier: Dict[str, Any], dossier_path: Path) -> None:
        run = dossier.get("run") if isinstance(dossier.get("run"), dict) else {}
        capabilities = dossier.get("tool_calls") if isinstance(dossier.get("tool_calls"), list) else []
        lessons_rows = dossier.get("lessons") if isinstance(dossier.get("lessons"), list) else []
        lessons = " ".join(str(item) for item in lessons_rows if item)
        provenance = dossier.get("provenance") if isinstance(dossier.get("provenance"), dict) else {}

        searchable_parts: List[str] = [
            str(run.get("intent") or ""),
            str(dossier.get("outputs", {}).get("final_result") if isinstance(dossier.get("outputs"), dict) else ""),
            lessons,
            " ".join(str(c) for c in capabilities),
            str(dossier.get("outcome_label") or run.get("status") or ""),
        ]
        searchable = "\n".join(part for part in searchable_parts if part)

        with sqlite3.connect(self.index_path) as conn:
            conn.execute(
                """
                INSERT INTO dossiers (
                    run_id, session_id, source, status, created_at, started_at, ended_at,
                    intent, final_result, lessons, capabilities, evidence_count,
                    dossier_path, provenance_json, searchable_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    session_id=excluded.session_id,
                    source=excluded.source,
                    status=excluded.status,
                    created_at=excluded.created_at,
                    started_at=excluded.started_at,
                    ended_at=excluded.ended_at,
                    intent=excluded.intent,
                    final_result=excluded.final_result,
                    lessons=excluded.lessons,
                    capabilities=excluded.capabilities,
                    evidence_count=excluded.evidence_count,
                    dossier_path=excluded.dossier_path,
                    provenance_json=excluded.provenance_json,
                    searchable_text=excluded.searchable_text
                """,
                (
                    str(run.get("id") or ""),
                    str(run.get("session_id") or ""),
                    str(run.get("source") or ""),
                    str(dossier.get("outcome_label") or run.get("status") or ""),
                    str(run.get("created_at") or ""),
                    str(run.get("started_at") or ""),
                    str(run.get("ended_at") or ""),
                    _safe_text(run.get("intent") or "", limit=2200),
                    _safe_text(
                        (dossier.get("outputs") or {}).get("final_result") if isinstance(dossier.get("outputs"), dict) else "",
                        limit=2600,
                    ),
                    _safe_text(lessons, limit=1600),
                    json.dumps([str(c) for c in capabilities], ensure_ascii=True),
                    int(len(dossier.get("evidence") if isinstance(dossier.get("evidence"), list) else [])),
                    str(dossier_path),
                    json.dumps(provenance, ensure_ascii=True),
                    _safe_text(searchable, limit=10000),
                ),
            )
            conn.commit()

    def _load_index_candidates(self, *, session_id: str = "") -> List[Dict[str, Any]]:
        query = (
            "SELECT run_id, session_id, source, status, created_at, ended_at, intent, final_result, "
            "lessons, dossier_path, provenance_json, searchable_text "
            "FROM dossiers"
        )
        params: List[Any] = []
        if session_id:
            query += " WHERE session_id = ?"
            params.append(session_id)
        query += " ORDER BY created_at DESC LIMIT 800"

        rows: List[Dict[str, Any]] = []
        with sqlite3.connect(self.index_path) as conn:
            cursor = conn.execute(query, tuple(params))
            for row in cursor.fetchall():
                rows.append(
                    {
                        "run_id": row[0],
                        "session_id": row[1],
                        "source": row[2],
                        "status": row[3],
                        "created_at": row[4],
                        "ended_at": row[5],
                        "intent": row[6],
                        "final_result": row[7],
                        "lessons": row[8],
                        "dossier_path": row[9],
                        "provenance_json": row[10],
                        "searchable_text": row[11],
                    }
                )
        return rows

    def _build_run_snapshot_from_events(self, run_dir: Path) -> Optional[Dict[str, Any]]:
        events_path = run_dir / "events.jsonl"
        events = self._read_jsonl(events_path)
        if not events:
            return None

        latest_run: Dict[str, Any] = {}
        steps = self._extract_steps_from_events(events)
        for event in events:
            run = event.get("run") if isinstance(event.get("run"), dict) else None
            if run:
                latest_run.update(run)

        run_id = str(latest_run.get("id") or run_dir.name)
        if not run_id:
            return None

        receipt_path = run_dir / "receipt.md"
        meta = {}
        if receipt_path.exists():
            meta["receipt_path"] = str(receipt_path)

        return {
            "id": run_id,
            "session_id": str(latest_run.get("session_id") or "main"),
            "source": str(latest_run.get("source") or "unknown"),
            "user_text": str(latest_run.get("user_text") or ""),
            "status": str(latest_run.get("status") or ""),
            "created_at": str(latest_run.get("created_at") or ""),
            "started_at": str(latest_run.get("started_at") or ""),
            "ended_at": str(latest_run.get("ended_at") or ""),
            "error": str(latest_run.get("error") or ""),
            "meta": meta,
            "steps": steps,
        }

    def _resolve_outcome_label(self, run: Dict[str, Any]) -> str:
        meta = run.get("meta") if isinstance(run.get("meta"), dict) else {}
        return str(
            (meta.get("phase15_outcome_label") if isinstance(meta, dict) else "")
            or (meta.get("outcome_label") if isinstance(meta, dict) else "")
            or run.get("outcome_label")
            or run.get("status")
            or ""
        )

    def _read_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, dict):
                        rows.append(data)
        except Exception:
            return []
        return rows

    def _write_jsonl(self, path: Path, rows: Iterable[Dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    def _copy_latest(self, source: Path, target: Path) -> None:
        if not source.exists():
            target.write_text("", encoding="utf-8")
            return
        shutil.copyfile(source, target)


_task_history_manager: Optional[TaskHistoryManager] = None


def get_task_history_manager() -> TaskHistoryManager:
    global _task_history_manager
    if _task_history_manager is None:
        _task_history_manager = TaskHistoryManager()
    return _task_history_manager


def reset_task_history_manager() -> None:
    global _task_history_manager
    _task_history_manager = None
