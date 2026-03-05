"""Background project orchestrator with approvals, inputs, and scheduling."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..core.capabilities import Capability, ActionResult, get_registry
from ..core.config import get_config
from ..core.state import get_state_manager
from ..core.websocket_server import get_ws_server
from ..core.events import get_event_bus, Event, EventType
from .models import OrchestratorProject, OrchestratorStep, ProjectStatus, StepStatus
from .planner import OrchestratorPlanner
from .store import OrchestratorStore

logger = logging.getLogger(__name__)


class OrchestratorManager:
    """Coordinates long-running projects using existing capabilities."""

    def __init__(self) -> None:
        self.config = get_config()
        self.state_manager = get_state_manager()
        self.registry = get_registry()
        self.policy_engine = self._get_policy_engine()
        self.event_bus = get_event_bus()

        db_path = getattr(self.config, "orchestrator_db_path", self.config.data_dir / "orchestrator.db")
        self.store = OrchestratorStore(db_path)
        self.planner = OrchestratorPlanner(self.registry)

        self._interval_seconds = float(getattr(self.config, "orchestrator_interval_seconds", 60.0))
        self._retry_backoff_minutes = int(getattr(self.config, "orchestrator_retry_backoff_minutes", 15))
        self._enabled = bool(getattr(self.config, "orchestrator_enabled", True))

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        self._last_idle_block_log_ts = 0.0

        # Optional learning + long-horizon memory integration.
        self.learning_engine = None
        try:
            from chintu_backend.brain.learning import get_learning_engine

            self.learning_engine = get_learning_engine()
        except Exception:
            self.learning_engine = None

        self.gcc_controller = None
        if getattr(self.config, "gcc_enabled", True):
            try:
                from chintu_backend.brain.learning.gcc_context_controller import get_gcc_controller

                self.gcc_controller = get_gcc_controller()
                self.gcc_controller.initialize(project_goal=getattr(self.config, "gcc_default_goal", ""))
            except Exception:
                self.gcc_controller = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> Tuple[bool, str]:
        if not self._enabled:
            self.state_manager.update_feature("orchestrator", enabled=False, status="inactive")
            return False, "Orchestrator disabled in config"
        if self._running:
            return True, "Orchestrator already running"

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ChintuOrchestrator")
        self._thread.start()
        self._running = True
        self.state_manager.update_feature("orchestrator", enabled=True, status="active")
        return True, "Orchestrator started"

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._running = False
        self.state_manager.update_feature("orchestrator", status="inactive")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_due_steps(manual=False, max_steps=1)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Orchestrator loop error: %s", exc)
                self.state_manager.update_feature("orchestrator", status="testing", error=str(exc))
            self._stop_event.wait(self._interval_seconds)

    # ------------------------------------------------------------------
    # Project creation and inspection
    # ------------------------------------------------------------------
    def create_project_from_request(self, request: str, auto_run: bool = False) -> Dict[str, Any]:
        defaults = self._defaults()
        spec = self.planner.plan(request, defaults)
        return self.create_project_from_spec(spec, source_request=request, auto_run=auto_run)

    def create_project_from_spec(
        self,
        spec: Dict[str, Any],
        source_request: str = "",
        auto_run: bool = False,
    ) -> Dict[str, Any]:
        status_value = spec.get("status", ProjectStatus.ACTIVE.value)
        try:
            status = ProjectStatus(status_value)
        except Exception:  # noqa: BLE001
            status = ProjectStatus.ACTIVE
        metadata = dict(spec.get("metadata") or {})
        if source_request:
            metadata.setdefault("source_request", source_request.strip()[:400])
        project = self.store.create_project(
            name=spec["name"],
            description=spec["description"],
            run_start_hour=spec["run_start_hour"],
            run_end_hour=spec["run_end_hour"],
            daily_budget_minutes=spec["daily_budget_minutes"],
            metadata=metadata,
            status=status,
        )
        project = self._ensure_gcc_project_branch(project) or project
        steps = self._materialize_steps(project, spec.get("steps") or [])
        missing_inputs = self.list_missing_inputs(project.id)
        approvals = self.store.list_pending_approvals(project.id)

        try:
            from chintu_backend.brain.orchestration.trace import log_event

            log_event(
                {
                    "event": "orchestrator_project_created",
                    "project_id": project.id,
                    "name": project.name,
                    "steps": [s.title for s in steps],
                }
            )
        except Exception:
            pass

        self._broadcast(
            {
                "type": "orchestrator_update",
                "data": {
                    "action": "created",
                    "project": self._project_dict(project),
                    "steps": [self._step_dict(s) for s in steps],
                },
            }
        )

        if auto_run:
            self.run_due_steps(project_id=project.id, manual=True, max_steps=2)

        return {
            "project": project,
            "steps": steps,
            "missing_inputs": missing_inputs,
            "pending_approvals": approvals,
        }

    # ------------------------------------------------------------------
    # GCC integration
    # ------------------------------------------------------------------
    @staticmethod
    def _slugify(value: str) -> str:
        raw = (value or "").strip().lower()
        raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
        raw = re.sub(r"-{2,}", "-", raw).strip("-")
        return raw or "project"

    def _get_gcc_branch(self, project: OrchestratorProject) -> str:
        if not self.gcc_controller:
            return ""
        meta = project.metadata or {}
        branch = str(meta.get("gcc_branch") or "").strip()
        if branch:
            return branch
        updated = self._ensure_gcc_project_branch(project)
        return str((updated.metadata or {}).get("gcc_branch") or "") if updated else ""

    def _ensure_gcc_project_branch(self, project: OrchestratorProject) -> Optional[OrchestratorProject]:
        if not self.gcc_controller or not getattr(self.config, "gcc_enabled", True):
            return project

        meta = dict(project.metadata or {})
        if meta.get("gcc_branch"):
            return project

        slug = self._slugify(project.name)[:28]
        branch = f"proj-{project.id[:8]}-{slug}"
        purpose = f"Orchestrator project: {project.name}. {project.description}".strip()
        try:
            self.gcc_controller.create_branch(branch, purpose=purpose[:300], from_branch="main", switch=False)
            self.gcc_controller.append_log(
                observation=f"Created orchestrator project '{project.name}' ({project.id[:8]}).",
                thought=f"Branch='{branch}'. Run window={project.run_start_hour:02d}:00-{project.run_end_hour:02d}:00.",
                action="Initialized project memory branch.",
                result=(meta.get("source_request") or "")[:400],
                branch=branch,
            )
        except Exception:
            pass

        meta["gcc_branch"] = branch
        updated = self.store.update_project(project.id, metadata_json=meta)
        return updated or project

    def list_projects(self, statuses: Optional[Iterable[ProjectStatus]] = None) -> List[OrchestratorProject]:
        return self.store.list_projects(statuses=statuses)

    def get_project(self, project_id: str) -> Optional[OrchestratorProject]:
        return self.store.get_project(project_id)

    def set_project_status(self, project_id: str, status: ProjectStatus) -> Optional[OrchestratorProject]:
        return self.store.update_project(project_id, status=status.value)

    def pause_project(self, project_id: str) -> Optional[OrchestratorProject]:
        return self.set_project_status(project_id, ProjectStatus.PAUSED)

    def resume_project(self, project_id: str) -> Optional[OrchestratorProject]:
        return self.set_project_status(project_id, ProjectStatus.ACTIVE)

    def cancel_project(self, project_id: str) -> Optional[OrchestratorProject]:
        return self.set_project_status(project_id, ProjectStatus.CANCELLED)

    def get_project_summary(self, project_id: str) -> Dict[str, Any]:
        project = self.store.get_project(project_id)
        if not project:
            return {"found": False, "project_id": project_id}
        steps = self.store.list_steps(project_id)
        completed = sum(1 for s in steps if s.status == StepStatus.COMPLETED)
        failed = sum(1 for s in steps if s.status == StepStatus.FAILED)
        waiting = sum(1 for s in steps if s.status in {StepStatus.WAITING_APPROVAL, StepStatus.WAITING_INPUT})
        return {
            "found": True,
            "project": self._project_dict(project),
            "counts": {
                "total": len(steps),
                "completed": completed,
                "failed": failed,
                "waiting": waiting,
            },
            "missing_inputs": self.list_missing_inputs(project_id),
            "pending_approvals": [asdict(a) for a in self.store.list_pending_approvals(project_id)],
            "recent_runs": [asdict(r) for r in self.store.list_runs(project_id, limit=10)],
        }

    def get_overview(self, limit: int = 20) -> Dict[str, Any]:
        """Return a UI-friendly snapshot of orchestrator projects + approvals.

        This is designed for dashboards (black-box view). Keep it JSON-safe.
        """

        projects = self.store.list_projects()[: max(1, int(limit))]
        approvals = self.store.list_pending_approvals(project_id=None)

        steps_by_project: Dict[str, List[Dict[str, Any]]] = {}
        missing_inputs: Dict[str, List[str]] = {}
        for proj in projects:
            steps_by_project[proj.id] = [self._step_dict(s) for s in self.store.list_steps(proj.id)]
            missing_inputs[proj.id] = self.list_missing_inputs(proj.id)

        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "projects": [self._project_dict(p) for p in projects],
            "steps_by_project": steps_by_project,
            "missing_inputs": missing_inputs,
            "pending_approvals": [self._approval_dict(a) for a in approvals],
        }

    # ------------------------------------------------------------------
    # Inputs and approvals
    # ------------------------------------------------------------------
    def set_input(
        self,
        key: str,
        value: str,
        is_secret: bool = False,
        project_id: Optional[str] = None,
    ) -> None:
        self.store.set_input(key, value, is_secret=is_secret, source="user", project_id=project_id)
        # Unblock any waiting-input steps that now have all requirements.
        target_projects = (
            [self.store.get_project(project_id)] if project_id else self.store.list_projects(
                statuses=[ProjectStatus.ACTIVE, ProjectStatus.PAUSED]
            )
        )
        for project in target_projects:
            if not project:
                continue
            for step in self.store.list_steps(project.id):
                if step.status != StepStatus.WAITING_INPUT:
                    continue
                missing = self._missing_inputs(step, project.id)
                if missing:
                    continue
                self.store.update_step(step.id, status=StepStatus.PENDING.value, last_error="")
        self._broadcast(
            {
                "type": "orchestrator_update",
                "data": {
                    "action": "input_set",
                    "key": key.strip().lower(),
                    "is_secret": bool(is_secret),
                    "project_id": project_id,
                },
            }
        )

    def list_missing_inputs(self, project_id: str) -> List[str]:
        steps = self.store.list_steps(project_id)
        missing: List[str] = []
        for step in steps:
            missing.extend(self._missing_inputs(step, project_id))
        deduped = sorted({m for m in missing if m})
        return deduped

    def approve_step(self, step_id: str, approve: bool) -> Optional[OrchestratorStep]:
        approval = self.store.decide_approval(step_id, approve=approve)
        step = self.store.get_step(step_id)
        if not step:
            return None
        if approval and approval.status == "approved":
            self.store.update_step(step_id, status=StepStatus.PENDING.value, last_error="")
        elif approval and approval.status == "rejected":
            self.store.update_step(step_id, status=StepStatus.SKIPPED.value, last_error="Approval rejected")
        updated = self.store.get_step(step_id)
        if updated:
            self._broadcast(
                {
                    "type": "orchestrator_update",
                    "data": {
                        "action": "approval_decided",
                        "step": self._step_dict(updated),
                        "approved": bool(approve),
                    },
                }
            )
        return updated

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def run_due_steps(
        self,
        project_id: Optional[str] = None,
        manual: bool = False,
        max_steps: int = 1,
    ) -> Dict[str, Any]:
        projects = [self.store.get_project(project_id)] if project_id else self.store.list_projects()
        steps_run = 0
        errors: List[str] = []

        for project in projects:
            if not project or project.status != ProjectStatus.ACTIVE:
                continue
            while steps_run < max_steps:
                step = self._find_next_step(project, manual=manual)
                if not step:
                    break
                ok, message = self._execute_step(project, step, manual=manual)
                steps_run += 1
                if not ok and message:
                    errors.append(message)
                    break

        if errors:
            self.state_manager.update_feature("orchestrator", status="testing", error="; ".join(errors)[:200])
        else:
            self.state_manager.update_feature("orchestrator", status="active")

        return {"steps_run": steps_run, "errors": errors}

    def _find_next_step(self, project: OrchestratorProject, manual: bool) -> Optional[OrchestratorStep]:
        if not manual and not self._within_run_window(project):
            return None
        if not manual and self._requires_idle(project) and not self._within_idle_policy(project):
            return None
        if not manual and not self._within_daily_budget(project):
            return None

        steps = self.store.list_steps(project.id)
        steps_by_id = {s.id: s for s in steps}
        now = datetime.now()

        # Normalize waiting states that may now be unblocked.
        for step in steps:
            if step.status == StepStatus.WAITING_INPUT and not self._missing_inputs(step, project.id):
                self.store.update_step(step.id, status=StepStatus.PENDING.value, last_error="")
            if step.status == StepStatus.WAITING_APPROVAL:
                pending = self.store.get_pending_approval(step.id)
                if pending:
                    continue
                latest = self.store.get_latest_approval(step.id)
                if latest and latest.status == "approved":
                    self.store.update_step(step.id, status=StepStatus.PENDING.value, last_error="")
                elif latest and latest.status == "rejected":
                    self.store.update_step(step.id, status=StepStatus.SKIPPED.value, last_error="Approval rejected")

        for step in self.store.list_steps(project.id):
            if step.status in {StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED}:
                continue
            if step.next_eligible_at and now < step.next_eligible_at:
                continue
            if not self._dependencies_satisfied(step, steps_by_id):
                continue
            missing = self._missing_inputs(step, project.id)
            if missing:
                self._request_inputs(project, step, missing)
                continue
            policy_gate = self._policy_gate(step)
            if policy_gate:
                self._request_approval(project, step, policy_gate)
                continue
            self.store.update_step(step.id, status=StepStatus.RUNNABLE.value)
            return self.store.get_step(step.id)
        return None

    def _execute_step(self, project: OrchestratorProject, step: OrchestratorStep, manual: bool) -> Tuple[bool, str]:
        capability = self._resolve_capability(step)
        if not capability:
            self.store.update_step(step.id, status=StepStatus.FAILED.value, last_error="No matching capability")
            return False, f"No capability for step: {step.title}"

        # Step-level approval based on project + risk.
        if self._needs_step_approval(step, project) and not self._is_approved(step):
            self._request_approval(project, step, f"Step risk is {step.risk_level}")
            return False, ""

        agent_context, runtime = self._build_agent_context(project, step)
        context = {
            "_policy_checked": True,
            "_confirmed": True,
            "_orchestrator": True,
            "_orchestrator_step_id": step.id,
            "_orchestrator_project_id": project.id,
            "inputs": {
                k: (self.store.get_input(k, project_id=project.id) or {}).get("value")
                for k in step.required_inputs
            },
        }
        if agent_context:
            context = {**agent_context, **context}

        # Run lifecycle (unifies Orchestrator work with the Runs dashboard).
        run_mgr = None
        run_id = ""
        run_step_id = ""
        try:
            from chintu_backend.core.run_manager import EvidenceRef, get_run_manager

            run_mgr = get_run_manager()
            record = run_mgr.create_run(
                session_id="orchestrator",
                source="orchestrator",
                user_text=f"[{project.name}] {step.title}".strip()[:2000],
                meta={
                    "project_id": project.id,
                    "project_name": project.name,
                    "step_id": step.id,
                    "step_title": step.title,
                    "capability": capability.name,
                },
            )
            run_id = record.id
            context["_run_id"] = run_id
            run_mgr.acquire_run_turn(run_id)
            run_step_id = run_mgr.start_step(
                run_id,
                title=step.title or step.command,
                capability=capability.name,
                meta={"kind": "orchestrator_step", "project_id": project.id, "step_id": step.id},
            )

            def _evidence_from_result_data(data: Any) -> list[EvidenceRef]:
                if not isinstance(data, dict):
                    return []
                evidence: list[EvidenceRef] = []
                seen: set[str] = set()
                for key in (
                    "path",
                    "artifact_path",
                    "file_path",
                    "report_path",
                    "screenshot",
                    "filepath",
                ):
                    val = data.get(key)
                    if not val:
                        continue
                    sval = str(val)
                    if sval and sval not in seen:
                        seen.add(sval)
                        evidence.append(EvidenceRef(kind="path", value=sval, summary="artifact"))
                url = data.get("url")
                if url:
                    evidence.append(EvidenceRef(kind="url", value=str(url), summary="url"))
                app = data.get("app")
                if app:
                    evidence.append(EvidenceRef(kind="app", value=str(app), summary="app"))
                return evidence

        except Exception:
            run_mgr = None
            run_id = ""
            run_step_id = ""

        started_at = datetime.now()
        attempts = int(step.attempts) + 1
        self.store.update_step(step.id, status=StepStatus.RUNNING.value, attempts=attempts, last_error="")
        self._notify_step(project, step, status="starting")

        gcc_branch = self._get_gcc_branch(project)
        if gcc_branch:
            try:
                self.gcc_controller.append_log(
                    observation=f"Orchestrator step starting: {step.title}",
                    thought=f"project={project.name}; capability={capability.name}; attempts={attempts}",
                    action=step.command,
                    result="",
                    branch=gcc_branch,
                )
            except Exception:
                pass
        if runtime and getattr(runtime, "session_store", None):
            runtime.session_store.append_event(
                {
                    "event": "orchestrator_step_start",
                    "project_id": project.id,
                    "step_id": step.id,
                    "step_title": step.title,
                    "capability": capability.name,
                }
            )

        try:
            from chintu_backend.brain.orchestration.trace import log_event

            log_event(
                {
                    "event": "orchestrator_step_start",
                    "project_id": project.id,
                    "step_id": step.id,
                    "capability": capability.name,
                    "command": step.command,
                }
            )
        except Exception:
            pass

        try:
            result = self.registry.execute(capability, step.command, context)
        except Exception as exc:  # noqa: BLE001
            result = ActionResult.fail(f"Execution error: {exc}", capability.name)

        finished_at = datetime.now()
        duration_seconds = max(0.0, (finished_at - started_at).total_seconds())

        # Run lifecycle: close out the run step + run status (never block orchestrator on this).
        try:
            if run_mgr and run_id and run_step_id:
                verification = {}
                try:
                    from chintu_backend.core.verification import verify_action_result

                    verification = verify_action_result(result)
                except Exception:
                    verification = {}

                evidence = []
                try:
                    evidence = _evidence_from_result_data(getattr(result, "data", None))
                except Exception:
                    evidence = []

                status = "completed" if bool(getattr(result, "success", False)) else "failed"
                run_mgr.end_step(
                    run_id,
                    run_step_id,
                    status=status,
                    message=getattr(result, "message", "") or "",
                    capability=capability.name,
                    evidence=evidence,
                    meta={"verification": verification} if verification else None,
                )

                # If the user cancelled via UI (run cancel), treat as cancelled.
                if run_mgr.is_cancel_requested(run_id):
                    run_mgr.mark_cancelled(run_id, reason="cancelled by user")
                elif bool(getattr(result, "requires_confirmation", False)):
                    # Orchestrator approvals are handled separately; don't block the Runs dashboard.
                    run_mgr.mark_completed(run_id, message="Approval requested (see Approvals).")
                elif bool(getattr(result, "success", False)):
                    run_mgr.mark_completed(run_id, message=getattr(result, "message", "") or "")
                else:
                    run_mgr.mark_failed(run_id, error=getattr(result, "message", "") or "failed")
                run_mgr.release_run_turn(run_id)
        except Exception:
            pass

        if result.requires_confirmation:
            # Avoid leaving a dangling global pending confirmation.
            self.registry.cancel_pending()
            self._request_approval(project, step, result.message)
            self.store.record_run(
                project.id,
                step.id,
                started_at,
                finished_at,
                success=False,
                result="",
                error="Requires confirmation",
                duration_seconds=duration_seconds,
            )
            return False, ""

        # If a cancellation was requested mid-execution, reflect that in orchestrator state too.
        try:
            if run_mgr and run_id and run_mgr.is_cancel_requested(run_id):
                self.store.update_step(step.id, status=StepStatus.SKIPPED.value, last_error="Cancelled by user")
                self.store.record_run(
                    project.id,
                    step.id,
                    started_at,
                    finished_at,
                    success=False,
                    result="",
                    error="Cancelled by user",
                    duration_seconds=duration_seconds,
                )
                self._broadcast_step_update(project.id, step.id, "failed")
                self._notify_step(project, step, status="failed", detail="Cancelled by user")
                return False, "Cancelled by user"
        except Exception:
            pass

        if result.success:
            self.store.update_step(
                step.id,
                status=StepStatus.COMPLETED.value,
                last_run_at=finished_at,
                last_error="",
            )
            self.store.record_run(
                project.id,
                step.id,
                started_at,
                finished_at,
                success=True,
                result=result.message,
                error="",
                duration_seconds=duration_seconds,
            )
            self._broadcast_step_update(project.id, step.id, "completed")
            self._notify_step(project, step, status="completed", detail=result.message)
            if runtime and getattr(runtime, "session_store", None):
                runtime.session_store.append_event(
                    {
                        "event": "orchestrator_step_complete",
                        "project_id": project.id,
                        "step_id": step.id,
                        "step_title": step.title,
                        "success": True,
                        "duration_seconds": duration_seconds,
                    }
                )
            self._maybe_complete_project(project.id)

            # Record learning + GCC milestone (orchestrator bypasses CommandHandler).
            try:
                if self.learning_engine:
                    self.learning_engine.observe_interaction(
                        user_text=step.command,
                        assistant_text=result.message or "",
                        result=result,
                        meta={"model_source": "orchestrator"},
                        source="orchestrator",
                        sensitive=False,
                    )
            except Exception:
                pass
            if gcc_branch:
                try:
                    update_main = str(step.risk_level).lower() in {"high", "critical"}
                    safe_msg = (result.message or "").strip()
                    summary = f"[orchestrator] {capability.name}: {step.title}".strip()[:200]
                    contribution = (
                        f"Project: {project.name} ({project.id[:8]})\n"
                        f"Step: {step.order_index}. {step.title}\n"
                        f"Command: {step.command}\n"
                        f"Result: {safe_msg[:1200]}"
                    )
                    self.gcc_controller.commit(
                        summary=summary,
                        contribution=contribution,
                        update_main=update_main,
                        roadmap_note=f"[{project.name}] {step.title}: {safe_msg[:160]}",
                        branch=gcc_branch,
                    )
                except Exception:
                    pass
            try:
                from chintu_backend.brain.orchestration.trace import log_event

                log_event(
                    {
                        "event": "orchestrator_step_complete",
                        "project_id": project.id,
                        "step_id": step.id,
                        "success": True,
                        "duration_seconds": duration_seconds,
                    }
                )
            except Exception:
                pass
            return True, ""

        # Failure path with optional retry backoff.
        last_error = (result.message or "Step failed")[:400]
        updates: Dict[str, Any] = {"last_error": last_error}
        if step.auto_retry and attempts < int(step.max_attempts):
            updates["status"] = StepStatus.PENDING.value
            updates["next_eligible_at"] = finished_at + timedelta(minutes=self._retry_backoff_minutes)
        else:
            updates["status"] = StepStatus.FAILED.value
            updates["last_run_at"] = finished_at

        self.store.update_step(step.id, attempts=attempts, **updates)
        self.store.record_run(
            project.id,
            step.id,
            started_at,
            finished_at,
            success=False,
            result="",
            error=last_error,
            duration_seconds=duration_seconds,
        )
        self._broadcast_step_update(project.id, step.id, "failed")
        self._notify_step(project, step, status="failed", detail=last_error)
        try:
            if self.learning_engine:
                self.learning_engine.observe_interaction(
                    user_text=step.command,
                    assistant_text=last_error,
                    result=result,
                    meta={"model_source": "orchestrator"},
                    source="orchestrator",
                    sensitive=False,
                )
        except Exception:
            pass
        if gcc_branch:
            try:
                self.gcc_controller.append_log(
                    observation=f"Orchestrator step failed: {step.title}",
                    thought=f"project={project.name}; capability={capability.name}; attempts={attempts}",
                    action=step.command,
                    result=last_error,
                    branch=gcc_branch,
                )
            except Exception:
                pass
        if runtime and getattr(runtime, "session_store", None):
            runtime.session_store.append_event(
                {
                    "event": "orchestrator_step_complete",
                    "project_id": project.id,
                    "step_id": step.id,
                    "step_title": step.title,
                    "success": False,
                    "error": last_error,
                    "duration_seconds": duration_seconds,
                }
            )
        try:
            from chintu_backend.brain.orchestration.trace import log_event

            log_event(
                {
                    "event": "orchestrator_step_complete",
                    "project_id": project.id,
                    "step_id": step.id,
                    "success": False,
                    "error": last_error,
                    "duration_seconds": duration_seconds,
                }
            )
        except Exception:
            pass
        return False, last_error

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _materialize_steps(self, project: OrchestratorProject, steps: List[Dict[str, Any]]) -> List[OrchestratorStep]:
        if not steps:
            return []
        approval_mode = str((project.metadata or {}).get("approval_mode") or "").lower()
        force_approval = approval_mode in {"all_steps", "every_step", "always"}
        # First insert without dependencies, then resolve numeric dependencies to ids.
        blank_deps = [{**s, "depends_on": []} for s in steps]
        inserted = self.store.add_steps(project.id, blank_deps)
        index_to_id = {i + 1: step.id for i, step in enumerate(inserted)}
        for i, spec in enumerate(steps, start=1):
            step_id = index_to_id.get(i)
            if not step_id:
                continue
            raw_deps = spec.get("depends_on_numbers") or spec.get("depends_on") or []
            dep_nums = [int(x) for x in raw_deps if str(x).isdigit()]
            dep_ids = [index_to_id[n] for n in dep_nums if n in index_to_id]
            assigned_agent = spec.get("assigned_agent") or spec.get("agent_role")
            approval_required = bool(spec.get("approval_required", False)) or force_approval
            self.store.update_step(
                step_id,
                depends_on_json=dep_ids,
                required_inputs_json=spec.get("required_inputs") or [],
                risk_level=spec.get("risk_level") or "low",
                estimated_minutes=int(spec.get("estimated_minutes") or 10),
                approval_required=approval_required,
                assigned_agent=assigned_agent,
            )
        return self.store.list_steps(project.id)

    def _defaults(self) -> Dict[str, Any]:
        return {
            "run_start_hour": int(getattr(self.config, "orchestrator_run_window_start_hour", 9)),
            "run_end_hour": int(getattr(self.config, "orchestrator_run_window_end_hour", 21)),
            "daily_budget_minutes": int(getattr(self.config, "orchestrator_daily_budget_minutes", 120)),
        }

    def _resolve_capability(self, step: OrchestratorStep) -> Optional[Capability]:
        if step.capability:
            cap = self.registry.get(step.capability)
            if cap:
                return cap
        return self.registry.match(step.command)

    def _dependencies_satisfied(self, step: OrchestratorStep, steps_by_id: Dict[str, OrchestratorStep]) -> bool:
        if not step.depends_on:
            return True
        for dep_id in step.depends_on:
            dep = steps_by_id.get(dep_id)
            if not dep or dep.status != StepStatus.COMPLETED:
                return False
        return True

    def _missing_inputs(self, step: OrchestratorStep, project_id: Optional[str] = None) -> List[str]:
        missing: List[str] = []
        for key in step.required_inputs:
            info = self.store.get_input(key, project_id=project_id)
            if info and info.get("value"):
                continue
            if self._input_available_elsewhere(key):
                continue
            missing.append(key)
        return missing

    @staticmethod
    def _input_available_elsewhere(key: str) -> bool:
        """Best-effort check for inputs that are already configured outside OrchestratorStore.

        This avoids repeatedly asking for secrets that already exist in env vars / Identity Vault.
        """

        import os

        if not key:
            return False
        normalized = str(key).strip().upper().replace("-", "_")

        aliases = {
            # Common provider keys (Config loads these from Identity Vault into env on startup).
            "GROQ_API_KEY": "GROQ_API_KEY",
            "GEMINI_API_KEY": "GOOGLE_AI_KEY",
            "GOOGLE_AI_KEY": "GOOGLE_AI_KEY",
            "DEEPSEEK_API_KEY": "DEEPSEEK_API_KEY",
            "NVIDIA_API_KEY": "NVIDIA_API_KEY",
            # OAuth client creds (optional future YouTube upload step).
            "GOOGLE_CLIENT_ID": "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET": "GOOGLE_CLIENT_SECRET",
        }
        env_key = aliases.get(normalized) or aliases.get(normalized.replace("CHINTU_", "")) or normalized
        return bool(os.environ.get(env_key))

    def _needs_step_approval(self, step: OrchestratorStep, project: Optional[OrchestratorProject] = None) -> bool:
        if bool(step.approval_required):
            return True
        if project:
            mode = str((project.metadata or {}).get("approval_mode") or "").lower()
            if mode in {"all_steps", "every_step", "always"}:
                return True
        return str(step.risk_level).lower() in {"high", "critical"}

    def _is_approved(self, step: OrchestratorStep) -> bool:
        latest = self.store.get_latest_approval(step.id)
        return bool(latest and latest.status == "approved")

    def _policy_gate(self, step: OrchestratorStep) -> str:
        if not self.policy_engine:
            return ""
        cap = self._resolve_capability(step)
        if not cap:
            return ""
        try:
            policy = self.policy_engine.evaluate(cap.name, {"_orchestrator": True})
        except Exception:  # noqa: BLE001
            return ""
        if policy.decision.value == "deny":
            self.store.update_step(step.id, status=StepStatus.FAILED.value, last_error=policy.reason[:200])
            self._broadcast_step_update(step.project_id, step.id, "failed")
            return ""
        if policy.decision.value in {"confirm", "plan"}:
            return policy.reason or "Policy requires confirmation"
        return ""

    def _within_run_window(self, project: OrchestratorProject) -> bool:
        from ..core.time_window import is_hour_in_window

        now = datetime.now()
        hour = int(now.hour)
        start = int(project.run_start_hour)
        end = int(project.run_end_hour)
        return bool(is_hour_in_window(hour, start, end))

    def _requires_idle(self, project: OrchestratorProject) -> bool:
        if project and isinstance(project.metadata, dict):
            if str(project.metadata.get("require_idle", "")).lower() in {"1", "true", "yes", "on"}:
                return True
        return bool(getattr(self.config, "orchestrator_require_idle", False))

    def _within_idle_policy(self, project: OrchestratorProject) -> bool:
        """Return True if the PC appears idle enough to run background work."""

        from ..core.system_idle import is_idle

        min_idle_seconds = float(getattr(self.config, "orchestrator_idle_min_seconds", 10 * 60))
        max_cpu = float(getattr(self.config, "orchestrator_idle_max_cpu_percent", 30.0))
        max_gpu = float(getattr(self.config, "orchestrator_idle_max_gpu_util_percent", 25.0))

        if project and isinstance(project.metadata, dict):
            try:
                if project.metadata.get("idle_min_seconds") is not None:
                    min_idle_seconds = float(project.metadata["idle_min_seconds"])
            except Exception:
                pass
            try:
                if project.metadata.get("idle_max_cpu_percent") is not None:
                    max_cpu = float(project.metadata["idle_max_cpu_percent"])
            except Exception:
                pass
            try:
                if project.metadata.get("idle_max_gpu_util_percent") is not None:
                    max_gpu = float(project.metadata["idle_max_gpu_util_percent"])
            except Exception:
                pass

        ok, reason, snap = is_idle(
            min_idle_seconds=min_idle_seconds,
            max_cpu_percent=max_cpu,
            max_gpu_util_percent=max_gpu,
        )
        if ok:
            return True

        # Throttle log spam to ~1 message per 10 minutes.
        now_ts = time.time()
        if now_ts - self._last_idle_block_log_ts > 600:
            self._last_idle_block_log_ts = now_ts
            try:
                details = (
                    f"idle={snap.idle_seconds if snap.idle_seconds is not None else 'n/a'}s "
                    f"cpu={snap.cpu_percent if snap.cpu_percent is not None else 'n/a'}% "
                    f"gpu={snap.gpu_util_percent if snap.gpu_util_percent is not None else 'n/a'}%"
                )
                self.state_manager.log_activity(f"Orchestrator paused (waiting for idle): {reason} ({details})")
            except Exception:
                pass
        return False

    def _within_daily_budget(self, project: OrchestratorProject) -> bool:
        used = self.store.minutes_used_today(project.id)
        return used < int(project.daily_budget_minutes)

    def _request_inputs(self, project: OrchestratorProject, step: OrchestratorStep, missing: List[str]) -> None:
        self.store.update_step(
            step.id,
            status=StepStatus.WAITING_INPUT.value,
            last_error=f"Missing inputs: {', '.join(missing[:6])}",
        )
        self._broadcast(
            {
                "type": "orchestrator_request",
                "data": {
                    "kind": "missing_input",
                    "project_id": project.id,
                    "step_id": step.id,
                    "missing": missing,
                    "step": self._step_dict(step),
                },
            }
        )
        try:
            self.event_bus.publish_sync(
                Event(
                    type=EventType.NOTIFICATION,
                    source="orchestrator",
                    data={
                        "category": "orchestrator_missing_inputs",
                        "severity": "medium",
                        "title": f"Inputs Needed: {project.name}",
                        "message": f"Step '{step.title}' needs inputs: {', '.join(missing[:6])}",
                        "metadata": {
                            "project_id": project.id,
                            "project_name": project.name,
                            "step_id": step.id,
                            "step_title": step.title,
                            "missing": missing,
                        },
                    },
                )
            )
        except Exception:
            pass
        try:
            from ..ui import get_a2ui_service

            get_a2ui_service().render_orchestrator_missing_inputs(
                project_id=project.id,
                project_name=project.name,
                step_id=step.id,
                step_title=step.title,
                missing=missing,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("A2UI missing-input render failed: %s", exc)

    def _request_approval(self, project: OrchestratorProject, step: OrchestratorStep, reason: str) -> None:
        self.store.create_approval(project.id, step.id, reason or "Approval required")
        self.store.update_step(
            step.id,
            status=StepStatus.WAITING_APPROVAL.value,
            last_error=(reason or "Approval required")[:300],
        )
        self._broadcast(
            {
                "type": "orchestrator_request",
                "data": {
                    "kind": "approval",
                    "project_id": project.id,
                    "step_id": step.id,
                    "reason": reason,
                    "step": self._step_dict(step),
                },
            }
        )
        try:
            risk = str(step.risk_level or "medium").lower()
            severity = "high" if risk in {"high", "critical"} else "medium"
            self.event_bus.publish_sync(
                Event(
                    type=EventType.NOTIFICATION,
                    source="orchestrator",
                    data={
                        "category": "orchestrator_approval",
                        "severity": severity,
                        "title": f"Approval Needed: {project.name}",
                        "message": f"Approve step '{step.title}'? {reason or 'Approval required.'}",
                        "metadata": {
                            "project_id": project.id,
                            "project_name": project.name,
                            "step_id": step.id,
                            "step_title": step.title,
                            "risk_level": step.risk_level,
                            "reason": reason,
                        },
                    },
                )
            )
        except Exception:
            pass
        try:
            from ..ui import get_a2ui_service

            get_a2ui_service().render_orchestrator_approval(
                project_id=project.id,
                project_name=project.name,
                step_id=step.id,
                step_title=step.title,
                reason=reason or "Approval required",
                risk_level=str(step.risk_level or "medium"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("A2UI approval render failed: %s", exc)

    def _maybe_complete_project(self, project_id: str) -> None:
        steps = self.store.list_steps(project_id)
        if steps and all(s.status == StepStatus.COMPLETED for s in steps):
            self.store.update_project(project_id, status=ProjectStatus.COMPLETED.value)
            project = self.store.get_project(project_id)
            if project:
                self._broadcast(
                    {
                        "type": "orchestrator_update",
                        "data": {"action": "project_completed", "project": self._project_dict(project)},
                    }
                )

    def _broadcast_step_update(self, project_id: str, step_id: str, action: str) -> None:
        step = self.store.get_step(step_id)
        project = self.store.get_project(project_id)
        if not step or not project:
            return
        self._broadcast(
            {
                "type": "orchestrator_update",
                "data": {"action": action, "project": self._project_dict(project), "step": self._step_dict(step)},
            }
        )

    def _project_dict(self, project: OrchestratorProject) -> Dict[str, Any]:
        data = asdict(project)
        data["status"] = project.status.value
        if project.created_at:
            data["created_at"] = project.created_at.isoformat(timespec="seconds")
        if project.updated_at:
            data["updated_at"] = project.updated_at.isoformat(timespec="seconds")
        if project.last_run_at:
            data["last_run_at"] = project.last_run_at.isoformat(timespec="seconds")
        return data

    def _step_dict(self, step: OrchestratorStep) -> Dict[str, Any]:
        data = asdict(step)
        data["status"] = step.status.value
        if step.last_run_at:
            data["last_run_at"] = step.last_run_at.isoformat(timespec="seconds")
        if step.next_eligible_at:
            data["next_eligible_at"] = step.next_eligible_at.isoformat(timespec="seconds")
        return data

    @staticmethod
    def _approval_dict(approval) -> Dict[str, Any]:
        data = asdict(approval)
        try:
            created = getattr(approval, "created_at", None)
            decided = getattr(approval, "decided_at", None)
            if created:
                data["created_at"] = created.isoformat(timespec="seconds")
            if decided:
                data["decided_at"] = decided.isoformat(timespec="seconds")
        except Exception:
            pass
        return data

    def _broadcast(self, payload: Dict[str, Any]) -> None:
        # 1) Gateway path: publish structured events onto the EventBus so the Gateway bridge
        # can forward them to UI clients connected to the Node gateway.
        try:
            msg_type = str(payload.get("type") or "").strip()
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            if msg_type == "orchestrator_update":
                self.event_bus.publish_sync(
                    Event(
                        type=EventType.ORCHESTRATOR_UPDATE,
                        source="orchestrator",
                        data=data,
                    )
                )
            elif msg_type == "orchestrator_request":
                self.event_bus.publish_sync(
                    Event(
                        type=EventType.ORCHESTRATOR_REQUEST,
                        source="orchestrator",
                        data=data,
                    )
                )
        except Exception:
            pass

        # 2) Legacy path: broadcast via the internal Python WebSocket server (older UIs).
        server = get_ws_server()
        if not server:
            return
        loop = getattr(server, "_loop", None)
        if not loop or not loop.is_running():
            return
        try:
            import asyncio

            asyncio.run_coroutine_threadsafe(server.broadcast_message(payload), loop)
        except Exception:
            return

    def _build_agent_context(
        self,
        project: OrchestratorProject,
        step: OrchestratorStep,
    ) -> Tuple[Dict[str, Any], Optional[object]]:
        agent_key = (step.assigned_agent or "").strip()
        if not agent_key:
            return {}, None
        try:
            from ..agents.agent_directory import get_agent_directory

            directory = get_agent_directory()
            runtime = directory.get_or_create(agent_key, role=agent_key)
            context = directory.build_context(runtime, agent_key)
            return context, runtime
        except Exception:
            return {}, None

    def _notify_step(
        self,
        project: OrchestratorProject,
        step: OrchestratorStep,
        *,
        status: str,
        detail: str = "",
    ) -> None:
        try:
            agent = step.assigned_agent or "primary"
            title = f"{project.name}: {step.title}"
            status_label = status.replace("_", " ").title()
            message = f"{status_label} (agent: {agent})."
            if detail:
                message = f"{message} {detail[:200]}"
            self.event_bus.publish_sync(
                Event(
                    type=EventType.NOTIFICATION,
                    source="orchestrator",
                    data={
                        "category": "orchestrator_step",
                        "severity": "low" if status == "completed" else "medium",
                        "title": title,
                        "message": message,
                        "metadata": {
                            "project_id": project.id,
                            "project_name": project.name,
                            "step_id": step.id,
                            "step_title": step.title,
                            "status": status,
                            "agent": agent,
                        },
                    },
                )
            )
        except Exception:
            return

    def _get_policy_engine(self):
        try:
            from ..policy.policy_engine import get_policy_engine

            return get_policy_engine()
        except Exception:  # noqa: BLE001
            return None


_manager: Optional[OrchestratorManager] = None


def get_orchestrator_manager() -> OrchestratorManager:
    global _manager
    if _manager is None:
        _manager = OrchestratorManager()
    return _manager
