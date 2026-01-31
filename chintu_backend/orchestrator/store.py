"""SQLite-backed persistence for orchestrated projects and steps."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import (
    ApprovalRequest,
    OrchestratorProject,
    OrchestratorStep,
    ProjectStatus,
    StepRun,
    StepStatus,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now()


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:  # noqa: BLE001
        return None


def _loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:  # noqa: BLE001
        return default


def _dumps(value: Any) -> str:
    return json.dumps(value or [])


class OrchestratorStore:
    """SQLite store with simple row-to-dataclass helpers."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    run_start_hour INTEGER NOT NULL,
                    run_end_hour INTEGER NOT NULL,
                    daily_budget_minutes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_run_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS steps (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    command TEXT NOT NULL,
                    capability TEXT,
                    depends_on_json TEXT NOT NULL DEFAULT '[]',
                    required_inputs_json TEXT NOT NULL DEFAULT '[]',
                    risk_level TEXT NOT NULL DEFAULT 'low',
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 2,
                    last_run_at TEXT,
                    next_eligible_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    estimated_minutes INTEGER NOT NULL DEFAULT 10,
                    auto_retry INTEGER NOT NULL DEFAULT 1,
                    approval_required INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    result TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    duration_seconds REAL NOT NULL DEFAULT 0.0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS inputs (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    is_secret INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user'
                )
                """
            )
            # Project-scoped inputs to avoid cross-project key collisions.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS inputs_scoped (
                    project_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    is_secret INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user',
                    PRIMARY KEY (project_id, key)
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def create_project(
        self,
        name: str,
        description: str,
        run_start_hour: int,
        run_end_hour: int,
        daily_budget_minutes: int,
        metadata: Optional[Dict[str, Any]] = None,
        status: ProjectStatus = ProjectStatus.ACTIVE,
    ) -> OrchestratorProject:
        project_id = str(uuid.uuid4())
        now = _now_iso()
        meta_json = json.dumps(metadata or {})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO projects (
                    id, name, description, status, run_start_hour, run_end_hour,
                    daily_budget_minutes, created_at, updated_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    name.strip()[:200] or "Untitled Project",
                    (description or "").strip(),
                    status.value,
                    int(run_start_hour),
                    int(run_end_hour),
                    int(daily_budget_minutes),
                    now,
                    now,
                    meta_json,
                ),
            )
            conn.commit()
        return self.get_project(project_id)  # type: ignore[return-value]

    def get_project(self, project_id: str) -> Optional[OrchestratorProject]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            return None
        return self._row_to_project(row)

    def list_projects(self, statuses: Optional[Iterable[ProjectStatus]] = None) -> List[OrchestratorProject]:
        params: List[Any] = []
        query = "SELECT * FROM projects"
        if statuses:
            status_values = [s.value for s in statuses]
            placeholders = ", ".join("?" for _ in status_values)
            query += f" WHERE status IN ({placeholders})"
            params.extend(status_values)
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_project(r) for r in rows]

    def update_project(self, project_id: str, **fields: Any) -> Optional[OrchestratorProject]:
        if not fields:
            return self.get_project(project_id)
        allowed = {
            "name",
            "description",
            "status",
            "run_start_hour",
            "run_end_hour",
            "daily_budget_minutes",
            "last_run_at",
            "metadata_json",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_project(project_id)
        updates["updated_at"] = _now_iso()
        sets = ", ".join(f"{k} = ?" for k in updates.keys())
        values = [self._normalize_project_field(k, v) for k, v in updates.items()]
        values.append(project_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE projects SET {sets} WHERE id = ?", values)
            conn.commit()
        return self.get_project(project_id)

    def _normalize_project_field(self, key: str, value: Any) -> Any:
        if key == "status" and isinstance(value, ProjectStatus):
            return value.value
        if key in {"run_start_hour", "run_end_hour", "daily_budget_minutes"}:
            return int(value)
        if key == "last_run_at" and isinstance(value, datetime):
            return value.isoformat(timespec="seconds")
        if key == "metadata_json" and isinstance(value, dict):
            return json.dumps(value)
        return value

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------
    def add_steps(self, project_id: str, step_specs: List[Dict[str, Any]]) -> List[OrchestratorStep]:
        if not step_specs:
            return []
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT COALESCE(MAX(order_index), 0) AS max_idx FROM steps WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            start_index = int(existing["max_idx"] or 0)
            for i, spec in enumerate(step_specs, start=1):
                step_id = str(uuid.uuid4())
                order_index = start_index + i
                conn.execute(
                    """
                    INSERT INTO steps (
                        id, project_id, order_index, title, command, capability,
                        depends_on_json, required_inputs_json, risk_level, status,
                        attempts, max_attempts, last_run_at, next_eligible_at,
                        last_error, estimated_minutes, auto_retry, approval_required
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, NULL, '', ?, ?, ?)
                    """,
                    (
                        step_id,
                        project_id,
                        order_index,
                        (spec.get("title") or f"Step {order_index}").strip()[:200],
                        (spec.get("command") or "").strip(),
                        (spec.get("capability") or None),
                        _dumps(spec.get("depends_on") or []),
                        _dumps(spec.get("required_inputs") or []),
                        (spec.get("risk_level") or "low"),
                        StepStatus.PENDING.value,
                        int(spec.get("max_attempts") or 2),
                        int(spec.get("estimated_minutes") or 10),
                        1 if bool(spec.get("auto_retry", True)) else 0,
                        1 if bool(spec.get("approval_required", False)) else 0,
                    ),
                )
            conn.commit()
        return self.list_steps(project_id)

    def list_steps(self, project_id: str) -> List[OrchestratorStep]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM steps WHERE project_id = ? ORDER BY order_index ASC",
                (project_id,),
            ).fetchall()
        return [self._row_to_step(r) for r in rows]

    def get_step(self, step_id: str) -> Optional[OrchestratorStep]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM steps WHERE id = ?", (step_id,)).fetchone()
        if not row:
            return None
        return self._row_to_step(row)

    def update_step(self, step_id: str, **fields: Any) -> Optional[OrchestratorStep]:
        if not fields:
            return self.get_step(step_id)
        allowed = {
            "title",
            "command",
            "capability",
            "depends_on_json",
            "required_inputs_json",
            "risk_level",
            "status",
            "attempts",
            "max_attempts",
            "last_run_at",
            "next_eligible_at",
            "last_error",
            "estimated_minutes",
            "auto_retry",
            "approval_required",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_step(step_id)
        sets = ", ".join(f"{k} = ?" for k in updates.keys())
        values = [self._normalize_step_field(k, v) for k, v in updates.items()]
        values.append(step_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE steps SET {sets} WHERE id = ?", values)
            conn.commit()
        return self.get_step(step_id)

    def _normalize_step_field(self, key: str, value: Any) -> Any:
        if key == "status" and isinstance(value, StepStatus):
            return value.value
        if key in {"attempts", "max_attempts", "estimated_minutes"}:
            return int(value)
        if key in {"auto_retry", "approval_required"}:
            return 1 if bool(value) else 0
        if key in {"last_run_at", "next_eligible_at"} and isinstance(value, datetime):
            return value.isoformat(timespec="seconds")
        if key in {"depends_on_json", "required_inputs_json"} and isinstance(value, list):
            return json.dumps(value)
        return value

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------
    def create_approval(self, project_id: str, step_id: str, reason: str) -> ApprovalRequest:
        existing = self.get_pending_approval(step_id)
        if existing:
            return existing
        approval_id = str(uuid.uuid4())
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals (id, project_id, step_id, reason, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (approval_id, project_id, step_id, reason.strip()[:400], now),
            )
            conn.commit()
        return self.get_pending_approval(step_id)  # type: ignore[return-value]

    def get_pending_approval(self, step_id: str) -> Optional[ApprovalRequest]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE step_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
                (step_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_approval(row)

    def get_latest_approval(self, step_id: str) -> Optional[ApprovalRequest]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE step_id = ? ORDER BY created_at DESC LIMIT 1",
                (step_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_approval(row)

    def decide_approval(
        self,
        step_id: str,
        approve: bool,
        decided_by: str = "user",
    ) -> Optional[ApprovalRequest]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE step_id = ? ORDER BY created_at DESC LIMIT 1",
                (step_id,),
            ).fetchone()
            if not row:
                return None
            approval_id = str(row["id"])
            status = "approved" if approve else "rejected"
            decided_at = _now_iso()
            conn.execute(
                """
                UPDATE approvals
                SET status = ?, decided_at = ?, decided_by = ?
                WHERE id = ?
                """,
                (status, decided_at, decided_by[:80], approval_id),
            )
            conn.commit()
        with self._connect() as conn:
            updated = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return self._row_to_approval(updated) if updated else None

    def list_pending_approvals(self, project_id: Optional[str] = None) -> List[ApprovalRequest]:
        params: List[Any] = []
        query = "SELECT * FROM approvals WHERE status = 'pending'"
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " ORDER BY created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_approval(r) for r in rows]

    # ------------------------------------------------------------------
    # Runs and budgets
    # ------------------------------------------------------------------
    def record_run(
        self,
        project_id: str,
        step_id: str,
        started_at: datetime,
        finished_at: datetime,
        success: bool,
        result: str = "",
        error: str = "",
        duration_seconds: float = 0.0,
    ) -> StepRun:
        run_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    id, project_id, step_id, started_at, finished_at,
                    success, result, error, duration_seconds
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    project_id,
                    step_id,
                    started_at.isoformat(timespec="seconds"),
                    finished_at.isoformat(timespec="seconds"),
                    1 if success else 0,
                    (result or "")[:2000],
                    (error or "")[:2000],
                    float(duration_seconds),
                ),
            )
            conn.commit()
        # Update project last_run_at for quick status
        self.update_project(project_id, last_run_at=finished_at)
        return StepRun(
            id=run_id,
            project_id=project_id,
            step_id=step_id,
            started_at=started_at,
            finished_at=finished_at,
            success=success,
            result=result,
            error=error,
            duration_seconds=duration_seconds,
        )

    def list_runs(self, project_id: str, limit: int = 50) -> List[StepRun]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM runs
                WHERE project_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (project_id, int(limit)),
            ).fetchall()
        runs: List[StepRun] = []
        for row in rows:
            runs.append(
                StepRun(
                    id=str(row["id"]),
                    project_id=str(row["project_id"]),
                    step_id=str(row["step_id"]),
                    started_at=_parse_dt(row["started_at"]) or _now(),
                    finished_at=_parse_dt(row["finished_at"]) or _now(),
                    success=bool(row["success"]),
                    result=str(row["result"] or ""),
                    error=str(row["error"] or ""),
                    duration_seconds=float(row["duration_seconds"] or 0.0),
                )
            )
        return runs

    def minutes_used_today(self, project_id: str) -> int:
        today = _now().date()
        total_minutes = 0.0
        for run in self.list_runs(project_id, limit=200):
            if run.started_at.date() != today:
                continue
            total_minutes += max(0.0, float(run.duration_seconds)) / 60.0
        return int(total_minutes)

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------
    def set_input(
        self,
        key: str,
        value: str,
        is_secret: bool = False,
        source: str = "user",
        project_id: Optional[str] = None,
    ) -> None:
        norm_key = (key or "").strip().lower()
        if not norm_key:
            return
        now = _now_iso()
        safe_source = (source or "user")[:80] or "user"
        with self._connect() as conn:
            if project_id:
                conn.execute(
                    """
                    INSERT INTO inputs_scoped (project_id, key, value, is_secret, updated_at, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id, key) DO UPDATE SET
                        value = excluded.value,
                        is_secret = excluded.is_secret,
                        updated_at = excluded.updated_at,
                        source = excluded.source
                    """,
                    (project_id, norm_key, value, 1 if is_secret else 0, now, safe_source),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO inputs (key, value, is_secret, updated_at, source)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        is_secret = excluded.is_secret,
                        updated_at = excluded.updated_at,
                        source = excluded.source
                    """,
                    (norm_key, value, 1 if is_secret else 0, now, safe_source),
                )
            conn.commit()

    def get_input(self, key: str, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        norm_key = (key or "").strip().lower()
        if not norm_key:
            return None
        with self._connect() as conn:
            scoped_row = None
            if project_id:
                scoped_row = conn.execute(
                    "SELECT * FROM inputs_scoped WHERE project_id = ? AND key = ?",
                    (project_id, norm_key),
                ).fetchone()
            row = scoped_row or conn.execute("SELECT * FROM inputs WHERE key = ?", (norm_key,)).fetchone()
        if not row:
            return None
        is_secret = bool(row["is_secret"])
        value = str(row["value"] or "")
        masked = value if not is_secret else ("*" * min(8, max(4, len(value))))
        scope = "project" if scoped_row else "global"
        return {
            "key": str(row["key"]),
            "value": value,
            "masked_value": masked,
            "is_secret": is_secret,
            "updated_at": str(row["updated_at"]),
            "source": str(row["source"]),
            "scope": scope,
            "project_id": project_id if scoped_row else None,
        }

    def list_inputs(
        self,
        keys: Optional[Iterable[str]] = None,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        norm_keys = [(k or "").strip().lower() for k in (keys or []) if k]
        params: List[Any] = []
        where = ""
        if norm_keys:
            placeholders = ", ".join("?" for _ in norm_keys)
            where = f" WHERE key IN ({placeholders})"
            params.extend(norm_keys)

        with self._connect() as conn:
            scoped_rows = []
            if project_id:
                scoped_rows = conn.execute(
                    f"SELECT * FROM inputs_scoped WHERE project_id = ?{where} ORDER BY key ASC",
                    ([project_id] + params),
                ).fetchall()
            global_rows = conn.execute(
                f"SELECT * FROM inputs{where} ORDER BY key ASC",
                params,
            ).fetchall()

        inputs: List[Dict[str, Any]] = []

        for row in scoped_rows:
            item = self.get_input(str(row["key"]), project_id=project_id)
            if item:
                inputs.append(item)

        for row in global_rows:
            # Skip globals shadowed by project-scoped values.
            if project_id and any(i["key"] == str(row["key"]) and i["scope"] == "project" for i in inputs):
                continue
            item = self.get_input(str(row["key"]), project_id=None)
            if item:
                inputs.append(item)

        return inputs

    # ------------------------------------------------------------------
    # Row helpers
    # ------------------------------------------------------------------
    def _row_to_project(self, row: sqlite3.Row) -> OrchestratorProject:
        return OrchestratorProject(
            id=str(row["id"]),
            name=str(row["name"]),
            description=str(row["description"] or ""),
            status=ProjectStatus(str(row["status"])),
            run_start_hour=int(row["run_start_hour"]),
            run_end_hour=int(row["run_end_hour"]),
            daily_budget_minutes=int(row["daily_budget_minutes"]),
            created_at=_parse_dt(row["created_at"]) or _now(),
            updated_at=_parse_dt(row["updated_at"]) or _now(),
            last_run_at=_parse_dt(row["last_run_at"]),
            metadata=_loads(row["metadata_json"], {}),
        )

    def _row_to_step(self, row: sqlite3.Row) -> OrchestratorStep:
        return OrchestratorStep(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            order_index=int(row["order_index"]),
            title=str(row["title"] or ""),
            command=str(row["command"] or ""),
            capability=str(row["capability"]) if row["capability"] else None,
            depends_on=_loads(row["depends_on_json"], []),
            required_inputs=_loads(row["required_inputs_json"], []),
            risk_level=str(row["risk_level"] or "low"),
            status=StepStatus(str(row["status"])),
            attempts=int(row["attempts"] or 0),
            max_attempts=int(row["max_attempts"] or 2),
            last_run_at=_parse_dt(row["last_run_at"]),
            next_eligible_at=_parse_dt(row["next_eligible_at"]),
            last_error=str(row["last_error"] or ""),
            estimated_minutes=int(row["estimated_minutes"] or 10),
            auto_retry=bool(row["auto_retry"]),
            approval_required=bool(row["approval_required"]),
        )

    def _row_to_approval(self, row: sqlite3.Row) -> ApprovalRequest:
        return ApprovalRequest(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            step_id=str(row["step_id"]),
            reason=str(row["reason"] or ""),
            status=str(row["status"] or "pending"),
            created_at=_parse_dt(row["created_at"]) or _now(),
            decided_at=_parse_dt(row["decided_at"]),
            decided_by=str(row["decided_by"]) if row["decided_by"] else None,
        )
