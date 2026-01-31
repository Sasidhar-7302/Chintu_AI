"""Workflow capabilities: run and resume deterministic workflows."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType
from chintu_backend.workflows.workflow_runner import (
    WorkflowRunResult,
    get_workflow_runner,
    resume_requires_approval,
)


def handle_workflow_run(text: str, context: Dict[str, Any]) -> ActionResult:
    file_path = _extract_file_path(text)
    if not file_path:
        return ActionResult.fail(
            "Please provide a workflow file path. Example: run workflow C:\\workflows\\daily.yaml",
            "workflow_run",
        )

    args = _extract_args_json(text)
    runner = get_workflow_runner()

    try:
        result = runner.run_file(file_path, args=args, mode="tool")
    except Exception as exc:
        return ActionResult.fail(f"Workflow failed: {exc}", "workflow_run")

    return _render_workflow_result(result)


def handle_workflow_resume(text: str, context: Dict[str, Any]) -> ActionResult:
    token = _extract_resume_token(text)
    if not token:
        return ActionResult.fail(
            "Please provide a resume token. Example: approve workflow <token> yes",
            "workflow_resume",
        )

    approved = _extract_approval_decision(text)
    if approved is None:
        try:
            if resume_requires_approval(token):
                return ActionResult.fail(
                    "Tell me yes or no. Example: approve workflow <token> yes",
                    "workflow_resume",
                )
        except Exception as exc:
            return ActionResult.fail(f"Workflow resume failed: {exc}", "workflow_resume")

    runner = get_workflow_runner()
    try:
        result = runner.resume(token, approved=approved, mode="tool")
    except Exception as exc:
        return ActionResult.fail(f"Workflow resume failed: {exc}", "workflow_resume")

    return _render_workflow_result(result)


def handle_workflow_list(text: str, context: Dict[str, Any]) -> ActionResult:
    workflows = _discover_workflows()
    if not workflows:
        return ActionResult.ok(
            "No workflows found. Add .yaml/.json workflows in chintu/workflows/recipes "
            "or a local ./workflows folder.",
            capability="workflow_list",
        )

    grouped = _group_workflows(workflows)
    lines: List[str] = ["Available workflows:"]
    for label, items in grouped:
        lines.append(f"{label}:")
        for item in items:
            desc = f" - {item['description']}" if item.get("description") else ""
            lines.append(f"- {item['name']}{desc} ({item['path']})")

    return ActionResult.ok("\n".join(lines), capability="workflow_list")


def _render_workflow_result(result: WorkflowRunResult) -> ActionResult:
    if result.status == "needs_approval" and result.requires_approval:
        prompt = result.requires_approval.prompt
        preview = result.requires_approval.preview
        token = result.requires_approval.resume_token
        try:
            from chintu_backend.ui import get_a2ui_service

            get_a2ui_service().render_workflow_approval(
                prompt=prompt,
                preview=preview,
                resume_token=token,
            )
        except Exception:
            pass

        message = f"Approval required: {prompt}"
        if token:
            message += f"\n\nResume token: {token}"
            message += "\nSay: approve workflow <token> yes | no"
        if preview:
            message += f"\n\nPreview:\n{preview}"
        return ActionResult.ok(message, capability="workflow_run")

    if result.status == "needs_setup":
        message = result.message or "Workflow requires setup before it can continue."
        if result.resume_token:
            message += f"\n\nResume token: {result.resume_token}"
            message += "\nSay: resume workflow <token>"
        return ActionResult.ok(message, capability="workflow_run")

    if not result.output:
        return ActionResult.ok("Workflow complete.", capability="workflow_run")

    if len(result.output) == 1:
        return ActionResult.ok(str(result.output[0]), capability="workflow_run")

    pretty = "\n".join(str(item) for item in result.output[:10])
    return ActionResult.ok(pretty, capability="workflow_run")


def _extract_file_path(text: str) -> Optional[str]:
    if not text:
        return None
    quoted = re.search(r"\"([^\"]+)\"|'([^']+)'", text)
    if quoted:
        return quoted.group(1) or quoted.group(2)
    drive = re.search(r"([A-Za-z]:[\\/][^\s]+)", text)
    if drive:
        return drive.group(1)
    # Fallback: last token that looks like a file
    for token in reversed(text.split()):
        if any(token.lower().endswith(ext) for ext in (".yaml", ".yml", ".json", ".lobster")):
            return token
    return None


def _extract_args_json(text: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"args(?:-json)?\s*[:=]\s*(\{.*\})", text)
    if not match:
        return None
    raw = match.group(1)
    try:
        return json.loads(raw)
    except Exception:
        return None


def _extract_resume_token(text: str) -> Optional[str]:
    match = re.search(r"token\s*[:=]\s*([A-Za-z0-9._-]+)", text)
    if match:
        return match.group(1)
    # Use last token if it looks like a token with a dot
    tokens = text.split()
    for token in reversed(tokens):
        if "." in token and len(token) > 20:
            return token
    return None


def _extract_approval_decision(text: str) -> Optional[bool]:
    lowered = text.lower()
    if any(word in lowered for word in ("reject", "no", "n")):
        return False
    if any(word in lowered for word in ("approve", "yes", "y")):
        return True
    return None


def _discover_workflows() -> List[Dict[str, str]]:
    sources: List[Tuple[str, Path]] = [
        ("Built-in workflows", Path(__file__).resolve().parent / "recipes"),
        ("Workspace workflows", Path.cwd() / "workflows"),
    ]
    workflows: List[Dict[str, str]] = []
    for label, root in sources:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in (".yaml", ".yml", ".json", ".lobster"):
                continue
            meta = _read_workflow_metadata(path)
            workflows.append(
                {
                    "source": label,
                    "name": meta.get("name") or path.stem,
                    "description": meta.get("description") or "",
                    "path": str(path),
                }
            )
    return workflows


def _read_workflow_metadata(path: Path) -> Dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}

    data: Any = None
    ext = path.suffix.lower()
    if ext in (".yaml", ".yml", ".lobster"):
        try:
            import yaml

            data = yaml.safe_load(text)
        except Exception:
            data = None
    else:
        try:
            data = json.loads(text)
        except Exception:
            data = None

    meta: Dict[str, str] = {}
    if isinstance(data, dict):
        name = data.get("name")
        description = data.get("description")
        if isinstance(name, str):
            meta["name"] = name
        if isinstance(description, str):
            meta["description"] = description
        return meta

    for line in text.splitlines()[:20]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key not in ("name", "description"):
            continue
        clean = value.strip().strip("\"'")
        if clean:
            meta[key] = clean
    return meta


def _group_workflows(workflows: List[Dict[str, str]]) -> List[Tuple[str, List[Dict[str, str]]]]:
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for wf in workflows:
        label = wf.get("source") or "Workflows"
        grouped.setdefault(label, []).append(wf)

    ordered: List[Tuple[str, List[Dict[str, str]]]] = []
    for label, items in grouped.items():
        ordered.append((label, sorted(items, key=lambda item: item.get("name", ""))))
    ordered.sort(key=lambda item: item[0])
    return ordered


def register_workflow_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="workflow_run",
            triggers=[
                "run workflow",
                "workflow run",
                "execute workflow",
                "start workflow",
            ],
            handler=handle_workflow_run,
            requires_confirmation=False,
            description="run a deterministic workflow file",
            capability_type=CapabilityType.AUTOMATION,
            examples=["Run workflow C:\\workflows\\daily.yaml"],
        )
    )

    registry.register(
        Capability(
            name="workflow_resume",
            triggers=[
                "resume workflow",
                "approve workflow",
                "workflow approve",
                "workflow resume",
            ],
            handler=handle_workflow_resume,
            requires_confirmation=False,
            description="resume a workflow after approval",
            capability_type=CapabilityType.AUTOMATION,
            examples=["Approve workflow <token> yes"],
        )
    )

    registry.register(
        Capability(
            name="workflow_list",
            triggers=[
                "list workflows",
                "workflow list",
                "show workflows",
                "available workflows",
            ],
            handler=handle_workflow_list,
            requires_confirmation=False,
            description="list available workflow recipes",
            capability_type=CapabilityType.AUTOMATION,
            examples=["List workflows", "Show workflows"],
        )
    )
