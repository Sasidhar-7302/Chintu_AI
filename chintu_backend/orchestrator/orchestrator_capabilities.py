"""Capabilities for the long-running project orchestrator."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional

from ..core.capabilities import ActionResult, Capability, CapabilityRegistry, CapabilityType, get_registry
from .manager import get_orchestrator_manager
from .models import ProjectStatus, StepStatus

logger = logging.getLogger(__name__)


def _strip_prefix(text: str, prefixes: Iterable[str]) -> str:
    lowered = text.lower().strip()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()
    return text.strip()


def _extract_id(text: str, keyword: str) -> str:
    pattern = rf"{keyword}\\s+([0-9a-fA-F\\-]{{6,}})"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    # Fallback: grab the first uuid-like token.
    tokens = re.findall(r"[0-9a-fA-F\\-]{6,}", text)
    return tokens[0] if tokens else ""


def _resolve_project(identifier: str):
    manager = get_orchestrator_manager()
    projects = manager.list_projects()
    if identifier:
        exact = manager.get_project(identifier)
        if exact:
            return exact
        ident_lower = identifier.lower()
        for proj in projects:
            if ident_lower in proj.id.lower() or ident_lower in proj.name.lower():
                return proj
    return projects[0] if projects else None


def _resolve_step(identifier: str):
    manager = get_orchestrator_manager()
    if not identifier:
        return None
    step = manager.store.get_step(identifier)
    if step:
        return step
    ident_lower = identifier.lower()
    for proj in manager.list_projects():
        for st in manager.store.list_steps(proj.id):
            if ident_lower in st.id.lower() or ident_lower in st.title.lower():
                return st
    return None


def _format_preview(spec: Dict[str, Any]) -> str:
    lines = [
        f"Plan preview: {spec['name']}",
        f"Run window: {spec['run_start_hour']:02d}:00-{spec['run_end_hour']:02d}:00",
        f"Daily budget: ~{spec['daily_budget_minutes']} minutes",
        "",
        "Steps:",
    ]
    for i, step in enumerate(spec.get("steps") or [], start=1):
        risk = step.get("risk_level", "low")
        risk_flag = " [approval]" if risk in {"high", "critical"} else ""
        lines.append(f"{i}. {step.get('title', f'Step {i}')}{risk_flag}")
    return "\n".join(lines)


def handle_orchestrator_create(text: str, context: Dict[str, Any]) -> ActionResult:
    manager = get_orchestrator_manager()
    request = _strip_prefix(
        text,
        prefixes=(
            "create project",
            "start project",
            "orchestrate",
            "orchestrator",
            "manage project",
        ),
    )
    if not request:
        return ActionResult.fail("Describe the project you want me to manage.", "orchestrator_create_project")

    if context.get("_plan_only"):
        spec = manager.planner.plan(request, manager._defaults())
        return ActionResult.ok(_format_preview(spec), capability="orchestrator_create_project")

    result = manager.create_project_from_request(request, auto_run=False)
    project = result["project"]
    steps = result["steps"]
    missing_inputs = result["missing_inputs"]
    approvals = result["pending_approvals"]

    lines = [
        f"Created project '{project.name}' ({project.id[:8]}).",
        f"Steps: {len(steps)}. Run window: {project.run_start_hour:02d}:00-{project.run_end_hour:02d}:00.",
    ]
    if missing_inputs:
        lines.append("Missing inputs: " + ", ".join(missing_inputs[:8]))
    if approvals:
        lines.append(f"Pending approvals: {len(approvals)} step(s).")
    lines.append(f"Try: 'project status {project.id[:8]}' or 'run project {project.id[:8]}'.")

    return ActionResult.ok(
        "\n".join(lines),
        data={
            "project_id": project.id,
            "steps": len(steps),
            "missing_inputs": missing_inputs,
            "pending_approvals": len(approvals),
        },
        capability="orchestrator_create_project",
    )


def handle_orchestrator_status(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_orchestrator_manager()
    identifier = _extract_id(text, "project")
    project = _resolve_project(identifier)
    if not project:
        return ActionResult.ok("No projects yet. Say 'create project ...' to start one.", capability="orchestrator_project_status")

    summary = manager.get_project_summary(project.id)
    if not summary.get("found"):
        return ActionResult.fail("I could not find that project.", "orchestrator_project_status")

    counts = summary["counts"]
    missing = summary["missing_inputs"]
    approvals = summary["pending_approvals"]
    steps = manager.store.list_steps(project.id)

    lines: List[str] = [
        f"Project: {project.name} ({project.id[:8]})",
        f"Status: {project.status.value}",
        f"Steps: {counts['completed']}/{counts['total']} complete, {counts['failed']} failed, {counts['waiting']} waiting.",
    ]
    if missing:
        lines.append("Missing inputs: " + ", ".join(missing[:8]))
    if approvals:
        lines.append(f"Pending approvals: {len(approvals)}.")

    lines.append("")
    lines.append("Next steps:")
    for step in steps[:6]:
        status = step.status.value
        marker = " -> needs approval" if status == StepStatus.WAITING_APPROVAL.value else ""
        lines.append(f"- {step.order_index}. {step.title} [{status}]{marker} ({step.id[:8]})")

    return ActionResult.ok("\n".join(lines), capability="orchestrator_project_status")


def handle_orchestrator_run(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_orchestrator_manager()
    identifier = _extract_id(text, "project")
    project = _resolve_project(identifier)
    max_steps = 1
    match = re.search(r"(?:for|run)\\s+(\\d+)\\s+steps?", text, flags=re.IGNORECASE)
    if match:
        max_steps = max(1, min(5, int(match.group(1))))

    if project:
        result = manager.run_due_steps(project_id=project.id, manual=True, max_steps=max_steps)
    else:
        result = manager.run_due_steps(project_id=None, manual=True, max_steps=max_steps)

    if result["steps_run"] == 0:
        return ActionResult.ok(
            "No runnable steps right now. Check missing inputs or approvals.",
            capability="orchestrator_run",
        )
    return ActionResult.ok(
        f"Ran {result['steps_run']} step(s).",
        data=result,
        capability="orchestrator_run",
    )


def handle_orchestrator_approve(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_orchestrator_manager()
    identifier = _extract_id(text, "step")
    step = _resolve_step(identifier)
    if not step:
        return ActionResult.fail("Specify the step id to approve, e.g. 'approve step abc123'.", "orchestrator_approve_step")

    reject_words = {"reject", "deny", "decline", "no"}
    approve = not any(word in text.lower() for word in reject_words)
    updated = manager.approve_step(step.id, approve=approve)
    if not updated:
        return ActionResult.fail("I could not update that step.", "orchestrator_approve_step")
    status = updated.status.value
    action = "Approved" if approve else "Rejected"
    return ActionResult.ok(f"{action} step {updated.id[:8]} ({status}).", capability="orchestrator_approve_step")


def handle_orchestrator_set_input(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_orchestrator_manager()
    match = re.search(
        r"(?:set|provide|add|update)\\s+(?:input\\s+)?([a-zA-Z0-9_\\-]+)\\s*(?:to|=)\\s*(.+)$",
        text.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return ActionResult.fail("Use: set input api_key=VALUE", "orchestrator_set_input")

    key = match.group(1).strip().lower()
    value = match.group(2).strip()
    # Optionally scope the input to a specific project.
    explicit_project_id = ""
    proj_match = re.search(r"\\bfor\\s+project\\s+([0-9a-fA-F\\-]{6,})", text, flags=re.IGNORECASE)
    if not proj_match:
        proj_match = re.search(r"\\bproject\\s+([0-9a-fA-F\\-]{6,})", text, flags=re.IGNORECASE)
    if proj_match:
        explicit_project_id = proj_match.group(1)
        # Remove trailing project clauses from the captured value.
        value = re.sub(
            rf"\\bfor\\s+project\\s+{re.escape(explicit_project_id)}\\b.*$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        value = re.sub(
            rf"\\bproject\\s+{re.escape(explicit_project_id)}\\b.*$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()

    secret_markers = {"password", "token", "secret", "api_key", "apikey", "key"}
    is_secret = key in secret_markers or any(m in text.lower() for m in {"secret", "password", "token"})
    project = _resolve_project(explicit_project_id) if explicit_project_id else _resolve_project("")
    project_id = project.id if project else None
    manager.set_input(key, value, is_secret=is_secret, project_id=project_id)

    if project_id:
        return ActionResult.ok(
            f"Stored input '{key}' for project {project_id[:8]}.",
            capability="orchestrator_set_input",
        )
    return ActionResult.ok(f"Stored input '{key}'.", capability="orchestrator_set_input")


def handle_orchestrator_missing_inputs(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_orchestrator_manager()
    identifier = _extract_id(text, "project")
    project = _resolve_project(identifier)
    if not project:
        return ActionResult.ok("No projects yet.", capability="orchestrator_missing_inputs")

    missing = manager.list_missing_inputs(project.id)
    if not missing:
        return ActionResult.ok("No missing inputs.", capability="orchestrator_missing_inputs")
    return ActionResult.ok(
        "Missing inputs: " + ", ".join(missing[:12]),
        data={"missing_inputs": missing},
        capability="orchestrator_missing_inputs",
    )


def handle_orchestrator_list_inputs(_text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_orchestrator_manager()
    identifier = _extract_id(_text, "project")
    project = _resolve_project(identifier) if identifier else _resolve_project("")
    project_id = project.id if project else None
    items = manager.store.list_inputs(project_id=project_id)
    if not items:
        return ActionResult.ok("No stored inputs yet.", capability="orchestrator_list_inputs")
    lines = ["Stored inputs:"]
    for item in items[:20]:
        masked = item.get("masked_value") or ""
        secret_flag = " (secret)" if item.get("is_secret") else ""
        scope = item.get("scope")
        scope_flag = f" [{scope}]" if scope else ""
        lines.append(f"- {item['key']}: {masked}{secret_flag}{scope_flag}")
    return ActionResult.ok("\n".join(lines), capability="orchestrator_list_inputs")


def handle_orchestrator_pause(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_orchestrator_manager()
    identifier = _extract_id(text, "project")
    project = _resolve_project(identifier)
    if not project:
        return ActionResult.fail("Specify which project to pause.", "orchestrator_pause_project")
    updated = manager.pause_project(project.id)
    if not updated:
        return ActionResult.fail("Could not pause that project.", "orchestrator_pause_project")
    return ActionResult.ok(f"Paused project {updated.name}.", capability="orchestrator_pause_project")


def handle_orchestrator_resume(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_orchestrator_manager()
    identifier = _extract_id(text, "project")
    project = _resolve_project(identifier)
    if not project:
        return ActionResult.fail("Specify which project to resume.", "orchestrator_resume_project")
    updated = manager.resume_project(project.id)
    if not updated:
        return ActionResult.fail("Could not resume that project.", "orchestrator_resume_project")
    return ActionResult.ok(f"Resumed project {updated.name}.", capability="orchestrator_resume_project")


def handle_orchestrator_cancel(text: str, _context: Dict[str, Any]) -> ActionResult:
    manager = get_orchestrator_manager()
    identifier = _extract_id(text, "project")
    project = _resolve_project(identifier)
    if not project:
        return ActionResult.fail("Specify which project to cancel.", "orchestrator_cancel_project")
    updated = manager.cancel_project(project.id)
    if not updated:
        return ActionResult.fail("Could not cancel that project.", "orchestrator_cancel_project")
    return ActionResult.ok(f"Cancelled project {updated.name}.", capability="orchestrator_cancel_project")


def register_orchestrator_capabilities(registry: Optional[CapabilityRegistry] = None) -> None:
    registry = registry or get_registry()

    registry.register(
        Capability(
            name="orchestrator_create_project",
            triggers=[
                "create project",
                "start project",
                "orchestrate",
                "manage project",
            ],
            handler=handle_orchestrator_create,
            description="create a long-running managed project",
            capability_type=CapabilityType.AI_AGENT,
        )
    )

    registry.register(
        Capability(
            name="orchestrator_project_status",
            triggers=[
                "project status",
                "orchestrator status",
                "list projects",
                "show projects",
            ],
            handler=handle_orchestrator_status,
            description="show managed project status",
            capability_type=CapabilityType.AI_AGENT,
        )
    )

    registry.register(
        Capability(
            name="orchestrator_run",
            triggers=[
                "run project",
                "orchestrator run",
                "run due steps",
            ],
            handler=handle_orchestrator_run,
            description="run the next due orchestrator step",
            capability_type=CapabilityType.AI_AGENT,
        )
    )

    registry.register(
        Capability(
            name="orchestrator_approve_step",
            triggers=[
                "approve step",
                "reject step",
                "deny step",
            ],
            handler=handle_orchestrator_approve,
            description="approve or reject a guarded orchestrator step",
            capability_type=CapabilityType.AI_AGENT,
            requires_confirmation=False,
        )
    )

    registry.register(
        Capability(
            name="orchestrator_set_input",
            triggers=[
                "set input",
                "provide input",
                "project input",
            ],
            handler=handle_orchestrator_set_input,
            description="set a required input for projects",
            capability_type=CapabilityType.PRODUCTIVITY,
        )
    )

    registry.register(
        Capability(
            name="orchestrator_missing_inputs",
            triggers=[
                "missing inputs",
                "what inputs missing",
                "project inputs missing",
            ],
            handler=handle_orchestrator_missing_inputs,
            description="list missing project inputs",
            capability_type=CapabilityType.PRODUCTIVITY,
        )
    )

    registry.register(
        Capability(
            name="orchestrator_list_inputs",
            triggers=[
                "list inputs",
                "show inputs",
                "project inputs",
            ],
            handler=handle_orchestrator_list_inputs,
            description="list stored orchestrator inputs",
            capability_type=CapabilityType.PRODUCTIVITY,
        )
    )

    registry.register(
        Capability(
            name="orchestrator_pause_project",
            triggers=["pause project"],
            handler=handle_orchestrator_pause,
            description="pause a managed project",
            capability_type=CapabilityType.AI_AGENT,
        )
    )

    registry.register(
        Capability(
            name="orchestrator_resume_project",
            triggers=["resume project"],
            handler=handle_orchestrator_resume,
            description="resume a managed project",
            capability_type=CapabilityType.AI_AGENT,
        )
    )

    registry.register(
        Capability(
            name="orchestrator_cancel_project",
            triggers=["cancel project", "stop project"],
            handler=handle_orchestrator_cancel,
            description="cancel a managed project",
            capability_type=CapabilityType.AI_AGENT,
            requires_confirmation=False,
        )
    )

    logger.info("Registered orchestrator capabilities")
