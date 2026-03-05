"""A2UI (Agent-to-UI) service: versioned, safe, declarative UI messages."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ...core.config import get_config
from ...core.events import Event, EventType, get_event_bus
from ...core.state import get_state_manager
from ...core.websocket_server import get_ws_server

logger = logging.getLogger(__name__)

A2UI_SCHEMA_VERSION = "a2ui-1.0"

SECRET_MARKERS = {
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
    "key",
    "access_key",
    "client_secret",
}


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _is_secret_key(key: str) -> bool:
    key_lower = (key or "").strip().lower()
    if key_lower in SECRET_MARKERS:
        return True
    return any(marker in key_lower for marker in SECRET_MARKERS)


def _humanize_key(key: str) -> str:
    text = (key or "").strip().replace("_", " ").replace("-", " ")
    return " ".join(word.capitalize() for word in text.split()) or key


@dataclass
class A2UIAction:
    """Declarative action metadata rendered as a trusted button."""

    id: str
    label: str
    style: str = "secondary"  # primary | secondary | danger
    action_type: str = "action"  # action | submit | dismiss | open_url
    form_id: Optional[str] = None
    requires_confirmation: bool = False
    confirmation_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "label": self.label,
            "style": self.style,
            "action_type": self.action_type,
        }
        if self.form_id:
            data["form_id"] = self.form_id
        if self.requires_confirmation:
            data["requires_confirmation"] = True
            if self.confirmation_message:
                data["confirmation_message"] = self.confirmation_message
        return data


@dataclass
class A2UIComponent:
    """A single trusted UI component rendered by the client."""

    type: str
    id: str = ""
    text: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = {"type": self.type}
        if self.id:
            payload["id"] = self.id
        if self.text:
            payload["text"] = self.text
        if self.data:
            payload["data"] = dict(self.data)
        return payload


@dataclass
class A2UIView:
    """A complete declarative view the client can render safely."""

    id: str
    kind: str
    title: str
    description: str = ""
    priority: int = 5
    severity: str = "info"  # info | warning | error | success
    components: List[A2UIComponent] = field(default_factory=list)
    actions: List[A2UIAction] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    schema_version: str = A2UI_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
            "priority": int(self.priority),
            "severity": self.severity,
            "components": [c.to_dict() for c in self.components],
            "actions": [a.to_dict() for a in self.actions],
            "meta": dict(self.meta),
            "created_at": self.created_at,
        }


class A2UIService:
    """Centralized, versioned UI orchestration with safe action handling."""

    def __init__(self) -> None:
        self.config = get_config()
        self.state_manager = get_state_manager()
        self.event_bus = get_event_bus()
        self._active_view_ids: set[str] = set()
        self._view_meta: Dict[str, Dict[str, Any]] = {}

        # Subscribe once; safe even if called multiple times due to singleton.
        self.event_bus.subscribe(EventType.A2UI_ACTION, self._on_action_event, is_async=True)
        self.state_manager.update_feature("a2ui", enabled=True, status="active", error=None)

    # ------------------------------------------------------------------
    # Public render helpers
    # ------------------------------------------------------------------
    def render_view(self, view: A2UIView) -> None:
        self._active_view_ids.add(view.id)
        self._view_meta[view.id] = dict(view.meta)
        self._broadcast(
            {
                "type": "a2ui_render",
                "data": {
                    "schema_version": A2UI_SCHEMA_VERSION,
                    "view": view.to_dict(),
                },
            }
        )

    def update_view(self, view: A2UIView) -> None:
        self._active_view_ids.add(view.id)
        self._view_meta[view.id] = dict(view.meta)
        self._broadcast(
            {
                "type": "a2ui_update",
                "data": {
                    "schema_version": A2UI_SCHEMA_VERSION,
                    "view": view.to_dict(),
                },
            }
        )

    def clear_view(self, view_id: str) -> None:
        if not view_id:
            return
        self._active_view_ids.discard(view_id)
        self._view_meta.pop(view_id, None)
        self._broadcast(
            {
                "type": "a2ui_clear",
                "data": {"view_ids": [view_id], "schema_version": A2UI_SCHEMA_VERSION},
            }
        )

    def clear_views(self, view_ids: Iterable[str]) -> None:
        ids = [vid for vid in view_ids if vid]
        if not ids:
            return
        for vid in ids:
            self._active_view_ids.discard(vid)
            self._view_meta.pop(vid, None)
        self._broadcast(
            {
                "type": "a2ui_clear",
                "data": {"view_ids": ids, "schema_version": A2UI_SCHEMA_VERSION},
            }
        )

    def toast(self, message: str, severity: str = "info") -> None:
        if not message:
            return
        self._broadcast(
            {
                "type": "a2ui_toast",
                "data": {
                    "schema_version": A2UI_SCHEMA_VERSION,
                    "message": message,
                    "severity": severity,
                    "timestamp": _now_iso(),
                },
            }
        )

    def action_result(self, action_id: str, success: bool, message: str, view_id: str = "") -> None:
        self._broadcast(
            {
                "type": "a2ui_action_result",
                "data": {
                    "schema_version": A2UI_SCHEMA_VERSION,
                    "action_id": action_id,
                    "success": bool(success),
                    "message": message,
                    "view_id": view_id,
                    "timestamp": _now_iso(),
                },
            }
        )

    def render_table(self, title: str, columns: List[str], rows: List[List[Any]], view_id: Optional[str] = None) -> None:
        """Render a simple table view for structured data."""
        view = A2UIView(
            id=view_id or f"table:{title.lower().replace(' ', '_')}",
            kind="table",
            title=title,
            description="",
            components=[
                A2UIComponent(
                    type="table",
                    data={
                        "columns": columns,
                        "rows": rows,
                    },
                )
            ],
        )
        self.render_view(view)

    def render_plan_canvas(
        self,
        goal: str,
        steps: List[str],
        *,
        risk: str = "low",
        eta_seconds: int = 0,
        view_id: Optional[str] = None,
    ) -> None:
        """Render a lightweight plan canvas view for executive plans."""
        items = [{"key": "Goal", "value": goal}]
        if eta_seconds:
            items.append({"key": "ETA", "value": f"~{eta_seconds}s"})
        items.append({"key": "Risk", "value": risk})
        steps_text = "\n".join(f"{idx+1}. {step}" for idx, step in enumerate(steps)) or "No steps found."

        view = A2UIView(
            id=view_id or "canvas:plan",
            kind="canvas",
            title="Execution Plan Canvas",
            description="Review the plan and confirm to proceed.",
            components=[
                A2UIComponent(type="key_value", data={"items": items}),
                A2UIComponent(type="markdown", text=steps_text),
            ],
            actions=[
                A2UIAction(
                    id="executive.confirm",
                    label="Confirm Plan",
                    style="primary",
                    requires_confirmation=True,
                    confirmation_message="Start executing this plan now?",
                ),
                A2UIAction(
                    id="executive.cancel",
                    label="Cancel",
                    style="secondary",
                ),
                A2UIAction(
                    id="a2ui.dismiss:canvas:plan",
                    label="Dismiss",
                    style="secondary",
                ),
            ],
        )
        self.render_view(view)

    def render_credential_prompt(
        self,
        keys: List[str],
        title: str = "Connect Required Credentials",
        description: str = "Provide the values below so I can continue.",
        view_id: Optional[str] = None,
        source: str = "skill",
    ) -> None:
        clean_keys = [k for k in keys if k]
        if not clean_keys:
            return

        view_id = view_id or f"credentials:{source}:{'-'.join(clean_keys).lower()}"
        form_id = f"credential_form:{view_id}"

        fields = []
        for key in clean_keys[:20]:
            field_type = "password" if _is_secret_key(key) else "text"
            fields.append(
                {
                    "name": key,
                    "label": _humanize_key(key),
                    "type": field_type,
                    "required": True,
                    "placeholder": f"Enter {_humanize_key(key)}",
                    "sensitive": field_type == "password",
                }
            )

        components = [
            A2UIComponent(type="text", text=description),
            A2UIComponent(
                type="form",
                id=form_id,
                data={
                    "title": "Credentials",
                    "fields": fields,
                    "submit_label": "Save Credentials",
                },
            ),
        ]

        actions = [
            A2UIAction(
                id=f"credentials.save_env:{view_id}",
                label="Save Credentials",
                style="primary",
                action_type="submit",
                form_id=form_id,
            ),
            A2UIAction(
                id=f"a2ui.dismiss:{view_id}",
                label="Dismiss",
                style="secondary",
                action_type="dismiss",
            ),
        ]

        view = A2UIView(
            id=view_id,
            kind="credentials",
            title=title,
            description=description,
            priority=10,
            severity="warning",
            components=components,
            actions=actions,
            meta={
                "category": "credentials",
                "credential_keys": list(clean_keys),
                "source": source,
            },
        )
        self.render_view(view)

    # ------------------------------------------------------------------
    # Specialized views
    # ------------------------------------------------------------------
    def render_orchestrator_missing_inputs(
        self,
        project_id: str,
        project_name: str,
        step_id: str,
        step_title: str,
        missing: List[str],
    ) -> None:
        view_id = f"orchestrator:missing_inputs:{project_id}"
        form_id = f"missing_inputs_form:{project_id}"

        fields = []
        for key in missing[:20]:
            field_type = "password" if _is_secret_key(key) else "text"
            fields.append(
                {
                    "name": key,
                    "label": _humanize_key(key),
                    "type": field_type,
                    "required": True,
                    "placeholder": f"Enter {_humanize_key(key)}",
                    "sensitive": field_type == "password",
                }
            )

        components = [
            A2UIComponent(
                type="text",
                text=(
                    "This project cannot continue until the required inputs are provided. "
                    "These values are stored securely and scoped to this project."
                ),
            ),
            A2UIComponent(
                type="key_value",
                data={
                    "items": [
                        {"key": "Project", "value": project_name},
                        {"key": "Step", "value": step_title},
                        {"key": "Missing", "value": ", ".join(missing[:8])},
                    ]
                },
            ),
            A2UIComponent(
                type="form",
                id=form_id,
                data={
                    "title": "Required Inputs",
                    "fields": fields,
                    "submit_label": "Save Inputs",
                },
            ),
        ]

        actions = [
            A2UIAction(
                id=f"orchestrator.submit_inputs:{project_id}:{step_id}",
                label="Save Inputs",
                style="primary",
                action_type="submit",
                form_id=form_id,
            ),
            A2UIAction(
                id=f"a2ui.dismiss:{view_id}",
                label="Dismiss",
                style="secondary",
                action_type="dismiss",
            ),
        ]

        view = A2UIView(
            id=view_id,
            kind="missing_inputs",
            title="Missing Project Inputs",
            description="Provide the required inputs so the project can continue.",
            priority=9,
            severity="warning",
            components=components,
            actions=actions,
            meta={
                "category": "orchestrator_missing_inputs",
                "project_id": project_id,
                "project_name": project_name,
                "step_id": step_id,
                "step_title": step_title,
                "missing": list(missing),
            },
        )
        self.render_view(view)

    def render_orchestrator_approval(
        self,
        project_id: str,
        project_name: str,
        step_id: str,
        step_title: str,
        reason: str,
        risk_level: str,
    ) -> None:
        view_id = f"orchestrator:approval:{step_id}"

        components = [
            A2UIComponent(
                type="text",
                text="This step requires your approval before it can run.",
            ),
            A2UIComponent(
                type="key_value",
                data={
                    "items": [
                        {"key": "Project", "value": project_name},
                        {"key": "Step", "value": step_title},
                        {"key": "Risk", "value": risk_level.upper()},
                    ]
                },
            ),
            A2UIComponent(type="text", text=reason or "Approval required by policy."),
        ]

        actions = [
            A2UIAction(
                id=f"orchestrator.approve:{step_id}",
                label="Approve",
                style="primary",
                action_type="action",
            ),
            A2UIAction(
                id=f"orchestrator.reject:{step_id}",
                label="Reject",
                style="danger",
                action_type="action",
                requires_confirmation=True,
                confirmation_message="Rejecting will skip this step. Continue?",
            ),
        ]

        view = A2UIView(
            id=view_id,
            kind="approval",
            title="Step Approval Required",
            description="Review the step details and decide whether to proceed.",
            priority=10,
            severity="warning",
            components=components,
            actions=actions,
            meta={
                "category": "orchestrator_approval",
                "project_id": project_id,
                "project_name": project_name,
                "step_id": step_id,
                "step_title": step_title,
                "risk_level": risk_level,
            },
        )
        self.render_view(view)

    def render_code_approval(self, request_id: str, file_path: str, diff_text: str) -> None:
        view_id = f"coding:approval:{request_id}"

        components = [
            A2UIComponent(
                type="text",
                text="Chintu proposes the following code change. Review carefully.",
            ),
            A2UIComponent(
                type="key_value",
                data={"items": [{"key": "File", "value": file_path}]},
            ),
            A2UIComponent(
                type="code_diff",
                id=f"code_diff:{request_id}",
                data={
                    "language": "diff",
                    "content": diff_text[:120000],
                    "max_height": 420,
                },
            ),
        ]

        actions = [
            A2UIAction(
                id=f"coding.approve:{request_id}",
                label="Approve & Apply",
                style="primary",
                action_type="action",
            ),
            A2UIAction(
                id=f"coding.reject:{request_id}",
                label="Reject",
                style="danger",
                action_type="action",
            ),
        ]

        view = A2UIView(
            id=view_id,
            kind="code_approval",
            title="Code Change Approval",
            description="No code will be changed until you approve.",
            priority=10,
            severity="warning",
            components=components,
            actions=actions,
            meta={
                "category": "code_approval",
                "request_id": request_id,
                "file_path": file_path,
            },
        )
        self.render_view(view)

    def render_workflow_approval(
        self,
        prompt: str,
        preview: Optional[str] = None,
        resume_token: Optional[str] = None,
    ) -> None:
        token_hint = (resume_token or "")[:12]
        view_id = f"workflow:approval:{token_hint or 'pending'}"

        components = [
            A2UIComponent(type="text", text=prompt or "Approval required."),
        ]
        if preview:
            components.append(A2UIComponent(type="text", text=f"Preview:\n{preview}"))
        if resume_token:
            components.append(
                A2UIComponent(
                    type="key_value",
                    data={"items": [{"key": "Resume Token", "value": resume_token}]},
                )
            )

        actions = [
            A2UIAction(
                id=f"a2ui.dismiss:{view_id}",
                label="Dismiss",
                style="secondary",
                action_type="dismiss",
            ),
        ]

        view = A2UIView(
            id=view_id,
            kind="workflow_approval",
            title="Workflow Approval Required",
            description="Approve this workflow step to continue.",
            priority=9,
            severity="warning",
            components=components,
            actions=actions,
            meta={
                "category": "workflow_approval",
                "resume_token": resume_token or "",
            },
        )
        self.render_view(view)

    # ------------------------------------------------------------------
    # Action handling
    # ------------------------------------------------------------------
    async def _on_action_event(self, event: Event) -> None:
        try:
            await self.handle_action(event.data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("A2UI action handling failed: %s", exc)
            self.state_manager.update_feature("a2ui", status="testing", error=str(exc)[:200])

    async def handle_action(self, payload: Dict[str, Any]) -> None:
        action_id = str(payload.get("action_id") or "").strip()
        view_id = str(payload.get("view_id") or "").strip()
        data = payload.get("payload")
        if not isinstance(data, dict):
            data = {}

        # Some clients may send form values in a "form" envelope.
        form_data = payload.get("form")
        if isinstance(form_data, dict):
            data = {**data, **form_data}

        if not action_id:
            return

        if action_id.startswith("a2ui.dismiss:"):
            _, target_view = action_id.split(":", 1)
            self.clear_view(target_view or view_id)
            self.action_result(action_id, True, "Dismissed.", view_id=target_view or view_id)
            return

        if action_id.startswith("orchestrator.approve:"):
            step_id = action_id.split(":", 1)[1]
            ok, message = self._handle_orchestrator_approval(step_id, approve=True)
            if ok:
                self.clear_view(view_id or f"orchestrator:approval:{step_id}")
                self.toast(message, severity="success")
            self.action_result(action_id, ok, message, view_id=view_id)
            return

        if action_id.startswith("orchestrator.reject:"):
            step_id = action_id.split(":", 1)[1]
            ok, message = self._handle_orchestrator_approval(step_id, approve=False)
            if ok:
                self.clear_view(view_id or f"orchestrator:approval:{step_id}")
                self.toast(message, severity="warning")
            self.action_result(action_id, ok, message, view_id=view_id)
            return

        if action_id.startswith("orchestrator.submit_inputs:"):
            ok, message = self._handle_orchestrator_inputs(action_id, data)
            if ok:
                self.clear_view(view_id)
                self.toast(message, severity="success")
            self.action_result(action_id, ok, message, view_id=view_id)
            return

        if action_id.startswith("coding.approve:"):
            request_id = action_id.split(":", 1)[1]
            self._publish_code_approval(request_id, approved=True)
            self.clear_view(view_id or f"coding:approval:{request_id}")
            self.action_result(action_id, True, "Approved.", view_id=view_id)
            return

        if action_id == "executive.confirm":
            try:
                from chintu_backend.core.executive import get_executive_brain
                from chintu_backend.core.capabilities import get_registry

                executive = get_executive_brain()
                if not executive.confirm_plan():
                    self.action_result(action_id, False, "No pending plan to confirm.", view_id=view_id)
                    return
                result = executive.execute_plan(get_registry())
                message = result.message
                if result.errors:
                    message += f" Errors: {', '.join(result.errors[:3])}"
                self.clear_view(view_id or "canvas:plan")
                self.toast(message, severity="success" if result.success else "warning")
                self.action_result(action_id, result.success, message, view_id=view_id)
            except Exception as exc:  # noqa: BLE001
                self.action_result(action_id, False, f"Plan execution failed: {exc}", view_id=view_id)
            return

        if action_id == "executive.cancel":
            try:
                from chintu_backend.core.executive import get_executive_brain

                executive = get_executive_brain()
                executive.cancel_plan()
                self.clear_view(view_id or "canvas:plan")
                self.toast("Plan cancelled.", severity="warning")
                self.action_result(action_id, True, "Plan cancelled.", view_id=view_id)
            except Exception as exc:  # noqa: BLE001
                self.action_result(action_id, False, f"Failed to cancel plan: {exc}", view_id=view_id)
            return

        if action_id.startswith("coding.reject:"):
            request_id = action_id.split(":", 1)[1]
            self._publish_code_approval(request_id, approved=False)
            self.clear_view(view_id or f"coding:approval:{request_id}")
            self.action_result(action_id, True, "Rejected.", view_id=view_id)
            return

        if action_id.startswith("credentials.save_env:"):
            target_view = action_id.split(":", 1)[1]
            ok, message = self._handle_credential_inputs(target_view, data, view_id=view_id)
            if ok:
                self.clear_view(view_id or target_view)
                self.toast(message, severity="success")
            self.action_result(action_id, ok, message, view_id=view_id)
            return

        if action_id == "news.feedback.submit":
            ok, message = self._handle_news_feedback(data)
            if ok:
                self.toast(message, severity="success")
            self.action_result(action_id, ok, message, view_id=view_id)
            return

        self.action_result(action_id, False, "Unknown action.", view_id=view_id)

    def _handle_orchestrator_approval(self, step_id: str, approve: bool) -> Tuple[bool, str]:
        try:
            from ..orchestrator import get_orchestrator_manager

            manager = get_orchestrator_manager()
            updated = manager.approve_step(step_id, approve=approve)
            if not updated:
                return False, "Could not update that step."
            action = "Approved" if approve else "Rejected"
            return True, f"{action} step {updated.id[:8]}."
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed orchestrator approval: %s", exc)
            return False, f"Approval failed: {exc}"

    def _handle_orchestrator_inputs(self, action_id: str, values: Dict[str, Any]) -> Tuple[bool, str]:
        try:
            _, project_id, step_id = action_id.split(":", 2)
        except ValueError:
            return False, "Invalid submit action."

        clean_values = {
            str(k).strip().lower(): ("" if v is None else str(v).strip())
            for k, v in (values or {}).items()
        }
        if not clean_values:
            return False, "No inputs provided."

        try:
            from ..orchestrator import get_orchestrator_manager

            manager = get_orchestrator_manager()
            saved = 0
            for key, value in clean_values.items():
                if not value:
                    continue
                manager.set_input(key, value, is_secret=_is_secret_key(key), project_id=project_id)
                saved += 1

            missing = manager.list_missing_inputs(project_id)
            if missing:
                # Keep the view but update the message in-place.
                project = manager.get_project(project_id)
                step = manager.store.get_step(step_id)
                if project and step:
                    self.render_orchestrator_missing_inputs(
                        project_id=project.id,
                        project_name=project.name,
                        step_id=step.id,
                        step_title=step.title,
                        missing=missing,
                    )
                return False, f"Saved {saved} input(s). Still missing: {', '.join(missing[:6])}."
            return True, f"Saved {saved} input(s). Project can continue."
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save orchestrator inputs: %s", exc)
            return False, f"Failed to save inputs: {exc}"

    def _publish_code_approval(self, request_id: str, approved: bool) -> None:
        try:
            event = Event(
                type=EventType.CODE_APPROVAL_RESPONSE,
                data={"request_id": request_id, "approved": bool(approved)},
                source="a2ui",
            )
            self.event_bus.publish_sync(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to publish code approval: %s", exc)

    def _handle_credential_inputs(self, target_view: str, values: Dict[str, Any], view_id: str = "") -> Tuple[bool, str]:
        meta = self._view_meta.get(view_id or target_view, {})
        allowed = set(k for k in meta.get("credential_keys", []) if isinstance(k, str))
        if not allowed:
            return False, "No credential fields configured."

        clean_values = {
            str(k).strip(): ("" if v is None else str(v).strip())
            for k, v in (values or {}).items()
            if str(k).strip() in allowed
        }
        if not clean_values:
            return False, "No credentials provided."

        try:
            self._save_env_vars(clean_values)
            return True, f"Saved {len(clean_values)} credential value(s)."
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save credentials: %s", exc)
            return False, f"Failed to save credentials: {exc}"

    def _handle_news_feedback(self, values: Dict[str, Any]) -> Tuple[bool, str]:
        try:
            from chintu_backend.automation.automation_capabilities import handle_morning_briefing_feedback
        except Exception as exc:
            return False, f"News feedback handler unavailable: {exc}"

        number_raw = str(values.get("headline_number") or values.get("number") or "").strip()
        sentiment = str(values.get("sentiment") or "like").strip().lower()
        archive_full_article = bool(values.get("archive_full_article") or values.get("archive"))

        if not number_raw:
            return False, "Select a headline number."
        try:
            number = int(number_raw)
        except Exception:
            return False, "Headline number must be numeric."
        if number <= 0:
            return False, "Headline number must be greater than zero."

        if sentiment in {"dislike", "less", "negative", "downvote"}:
            feedback_text = f"not interested in #{number}"
        else:
            feedback_text = f"I like #{number}"
            if archive_full_article:
                feedback_text = f"{feedback_text} and archive full article"

        result = handle_morning_briefing_feedback(
            feedback_text,
            {"archive_full_article": archive_full_article},
        )
        if bool(getattr(result, "success", False)):
            return True, str(getattr(result, "message", "") or "Feedback saved.")
        return False, str(getattr(result, "message", "") or "Could not save feedback.")

    @staticmethod
    def _save_env_vars(values: Dict[str, str]) -> None:
        from pathlib import Path
        import os
        import re

        env_path = Path.cwd() / ".env"
        existing = ""
        if env_path.exists():
            existing = env_path.read_text(encoding="utf-8")

        def _replace(content: str, key: str, value: str) -> str:
            pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
            if pattern.search(content):
                return pattern.sub(f"{key}={value}", content)
            return content + ("" if content.endswith("\n") or content == "" else "\n") + f"{key}={value}\n"

        updated = existing
        for key, value in values.items():
            updated = _replace(updated, key, value)
            os.environ[key] = value

        env_path.write_text(updated, encoding="utf-8")

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _broadcast(self, payload: Dict[str, Any]) -> None:
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


_service: Optional[A2UIService] = None


def get_a2ui_service() -> A2UIService:
    global _service
    if _service is None:
        _service = A2UIService()
    return _service
