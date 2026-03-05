"""Workspace abstraction capabilities (Phase 26)."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType
from chintu_backend.workspace import get_workspace_manager


class WorkspaceShellSchema(BaseModel):
    command: str = Field(..., description="Shell command to run")
    placement: Optional[str] = Field(None, description="auto | local_host | sandbox | remote_sandbox")
    allow_network: bool = Field(False, description="Allow network in sandbox placements")
    timeout_seconds: int = Field(60, ge=1, le=1800)
    cwd: Optional[str] = Field(None, description="Optional working directory")


class WorkspaceCheckpointSchema(BaseModel):
    session_id: str = Field(..., description="Workflow session identifier")
    step: str = Field(..., description="Step id/name")
    payload_json: Optional[str] = Field(None, description="Optional JSON object payload")


class WorkspaceResumeSchema(BaseModel):
    session_id: str = Field(..., description="Workflow session identifier")


def handle_workspace_status(_: str, context: Dict[str, Any]) -> ActionResult:
    manager = get_workspace_manager()
    profile = manager.runtime_profile(context)
    msg = (
        "Workspace runtime status:\n"
        f"- Profile: {profile}\n"
        f"- Root: {manager.root_dir}\n"
        f"- Receipts: {manager.receipts_dir}\n"
        f"- Checkpoints: {manager.checkpoints_dir}"
    )
    return ActionResult.ok(
        msg,
        {
            "runtime_profile": profile,
            "root_dir": str(manager.root_dir),
            "receipts_dir": str(manager.receipts_dir),
            "checkpoints_dir": str(manager.checkpoints_dir),
        },
        capability="workspace_status",
    )


def handle_workspace_run_shell(text: str, context: Dict[str, Any]) -> ActionResult:
    manager = get_workspace_manager()
    params = context.get("_validated_params")
    if not isinstance(params, WorkspaceShellSchema):
        command = str(text or "").strip()
        for prefix in ("workspace run", "workspace shell", "run in workspace"):
            low = command.lower()
            idx = low.find(prefix)
            if idx != -1:
                command = command[idx + len(prefix):].strip(" :")
        if not command:
            return ActionResult.fail("Provide a command to run in workspace.", "workspace_run_shell")
        params = WorkspaceShellSchema(command=command)

    try:
        result = manager.run_shell(
            params.command,
            action_kind="shell",
            context=context,
            cwd=params.cwd,
            requested_placement=params.placement,
            allow_network=bool(params.allow_network),
            timeout_seconds=int(params.timeout_seconds),
        )
    except Exception as exc:
        return ActionResult.fail(f"Workspace run failed: {exc}", "workspace_run_shell")

    preview = (result.stdout or "").strip()[:1000]
    message = result.message
    if preview:
        message += f"\n\nOutput:\n{preview}"
    if (result.stderr or "").strip():
        message += f"\n\nErrors:\n{result.stderr.strip()[:1000]}"
    message += f"\n\nPlacement: {result.placement.value}"
    if not result.success:
        message += (
            f"\nRuntime profile: {result.runtime_profile}"
            f"\nReceipt: {result.receipt_path}"
        )
    return ActionResult.ok(
        message if result.success else message,
        {
            "success": result.success,
            "exit_code": result.exit_code,
            "placement": result.placement.value,
            "runtime_profile": result.runtime_profile,
            "receipt_path": str(result.receipt_path),
        },
        capability="workspace_run_shell",
    ) if result.success else ActionResult.fail(message, capability="workspace_run_shell")


def handle_workspace_checkpoint(_: str, context: Dict[str, Any]) -> ActionResult:
    params = context.get("_validated_params")
    if not isinstance(params, WorkspaceCheckpointSchema):
        return ActionResult.fail("Provide session_id and step for workspace checkpoint.", "workspace_checkpoint")

    payload: Dict[str, Any] = {}
    if params.payload_json:
        try:
            parsed = json.loads(params.payload_json)
            if isinstance(parsed, dict):
                payload = parsed
            else:
                payload = {"value": parsed}
        except Exception as exc:
            return ActionResult.fail(f"Invalid payload_json: {exc}", "workspace_checkpoint")

    manager = get_workspace_manager()
    path = manager.save_checkpoint(params.session_id, params.step, payload)
    return ActionResult.ok(
        f"Workspace checkpoint saved for session '{params.session_id}' step '{params.step}'.",
        {"checkpoint_path": str(path)},
        capability="workspace_checkpoint",
    )


def handle_workspace_resume(_: str, context: Dict[str, Any]) -> ActionResult:
    params = context.get("_validated_params")
    if not isinstance(params, WorkspaceResumeSchema):
        return ActionResult.fail("Provide session_id to resume workspace checkpoint.", "workspace_resume")
    manager = get_workspace_manager()
    latest = manager.load_latest_checkpoint(params.session_id)
    if not latest:
        return ActionResult.fail(f"No checkpoint found for session '{params.session_id}'.", "workspace_resume")
    step = str(latest.get("step") or "unknown")
    return ActionResult.ok(
        f"Loaded latest checkpoint for session '{params.session_id}' at step '{step}'.",
        {"checkpoint": latest},
        capability="workspace_resume",
    )


def register_workspace_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="workspace_status",
            triggers=["workspace status", "show workspace status", "autonomy mode status"],
            handler=handle_workspace_status,
            capability_type=CapabilityType.SYSTEM,
            description="Show workspace runtime profile and checkpoint locations",
        )
    )
    registry.register(
        Capability(
            name="workspace_run_shell",
            triggers=["workspace run", "workspace shell", "run in workspace"],
            handler=handle_workspace_run_shell,
            capability_type=CapabilityType.AUTOMATION,
            description="Run shell command through workspace abstraction (local/sandbox/remote)",
            schema=WorkspaceShellSchema,
        )
    )
    registry.register(
        Capability(
            name="workspace_checkpoint",
            triggers=["save workspace checkpoint", "checkpoint workspace", "workspace checkpoint"],
            handler=handle_workspace_checkpoint,
            capability_type=CapabilityType.AI_AGENT,
            description="Save a resumable workspace checkpoint",
            schema=WorkspaceCheckpointSchema,
        )
    )
    registry.register(
        Capability(
            name="workspace_resume",
            triggers=["resume workspace checkpoint", "workspace resume", "load workspace checkpoint"],
            handler=handle_workspace_resume,
            capability_type=CapabilityType.AI_AGENT,
            description="Load latest checkpoint for a workspace session",
            schema=WorkspaceResumeSchema,
        )
    )
