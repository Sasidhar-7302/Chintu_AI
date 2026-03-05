"""Workspace API for placement-aware execution and resumable checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Dict, Iterable, Optional

from chintu_backend.core.config import get_config
from chintu_backend.policy.runtime_profiles import resolve_runtime_profile
from chintu_backend.sandbox import SandboxExecutor


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class WorkspacePlacement(str, Enum):
    LOCAL_HOST = "local_host"
    SANDBOX = "sandbox"
    REMOTE_SANDBOX = "remote_sandbox"


@dataclass(frozen=True)
class WorkspaceExecutionResult:
    success: bool
    placement: WorkspacePlacement
    command: str
    runtime_profile: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    receipt_path: Path

    @property
    def message(self) -> str:
        if self.success:
            return "Workspace command completed."
        return f"Workspace command failed (exit {self.exit_code})."


class WorkspaceManager:
    """Abstraction over local/sandbox execution with receipts and checkpoints."""

    def __init__(self, config=None):
        self.config = config or get_config()
        self.root_dir = Path(
            getattr(self.config, "workspace_root_dir", None)
            or getattr(self.config, "terminal_workspace_root", Path.cwd())
        ).expanduser()
        self.receipts_dir = Path(
            getattr(self.config, "workspace_receipts_dir", None)
            or (Path(self.config.data_dir) / "workspace" / "receipts")
        ).expanduser()
        self.checkpoints_dir = Path(
            getattr(self.config, "workspace_checkpoints_dir", None)
            or (Path(self.config.data_dir) / "workspace" / "checkpoints")
        ).expanduser()
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Placement and runtime profile
    # ------------------------------------------------------------------
    def runtime_profile(self, context: Optional[Dict[str, Any]] = None) -> str:
        return resolve_runtime_profile(
            context if isinstance(context, dict) else {},
            default_profile=str(getattr(self.config, "workspace_default_runtime_profile", "safe_mode") or "safe_mode"),
            safe_mode_channels=getattr(self.config, "workspace_untrusted_channels", []),
        )

    def choose_placement(
        self,
        action_kind: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        requested: Optional[str] = None,
    ) -> WorkspacePlacement:
        req = str(requested or "").strip().lower()
        if req in {x.value for x in WorkspacePlacement}:
            return WorkspacePlacement(req)
        if req == "local":
            return WorkspacePlacement.LOCAL_HOST
        if req == "sandbox":
            return WorkspacePlacement.SANDBOX
        if req == "remote":
            return WorkspacePlacement.REMOTE_SANDBOX

        kind = str(action_kind or "").strip().lower()
        ctx = context if isinstance(context, dict) else {}
        profile = self.runtime_profile(ctx)
        remote_enabled = bool(getattr(self.config, "workspace_remote_sandbox_enabled", False))
        remote_hint = bool(ctx.get("remote_channel")) or str(ctx.get("channel_trust") or "").strip().lower() == "untrusted"

        local_kinds = {"ui", "app_control", "screen", "audio", "desktop"}
        sandbox_kinds = {"shell", "code", "install", "dependency", "web_fetch", "web_process"}

        if kind in local_kinds:
            return WorkspacePlacement.LOCAL_HOST
        if kind in sandbox_kinds:
            if kind == "shell" and not bool(getattr(self.config, "workspace_sandbox_default_for_shell", True)):
                return WorkspacePlacement.LOCAL_HOST
            if remote_enabled and remote_hint:
                return WorkspacePlacement.REMOTE_SANDBOX
            return WorkspacePlacement.SANDBOX

        if profile == "safe_mode":
            return WorkspacePlacement.SANDBOX
        return WorkspacePlacement.LOCAL_HOST

    # ------------------------------------------------------------------
    # Checkpointing
    # ------------------------------------------------------------------
    def save_checkpoint(self, session_id: str, step: str, payload: Dict[str, Any]) -> Path:
        sid = self._clean_session_id(session_id)
        record = {
            "timestamp_utc": _utc_now(),
            "session_id": sid,
            "step": str(step or "checkpoint"),
            "payload": payload if isinstance(payload, dict) else {"value": payload},
        }
        path = self.checkpoints_dir / f"{sid}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=True) + "\n")
        return path

    def load_latest_checkpoint(self, session_id: str) -> Optional[Dict[str, Any]]:
        sid = self._clean_session_id(session_id)
        path = self.checkpoints_dir / f"{sid}.jsonl"
        if not path.exists():
            return None
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            for row in reversed(lines):
                row = row.strip()
                if not row:
                    continue
                data = json.loads(row)
                if isinstance(data, dict):
                    return data
        except Exception:
            return None
        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def run_shell(
        self,
        command: str,
        *,
        action_kind: str = "shell",
        context: Optional[Dict[str, Any]] = None,
        cwd: Optional[Path | str] = None,
        env: Optional[Dict[str, str]] = None,
        requested_placement: Optional[str] = None,
        allow_network: bool = False,
        timeout_seconds: Optional[int] = None,
    ) -> WorkspaceExecutionResult:
        cmd = str(command or "").strip()
        if not cmd:
            raise ValueError("command is required")
        ctx = context if isinstance(context, dict) else {}
        profile = self.runtime_profile(ctx)
        placement = self.choose_placement(action_kind, context=ctx, requested=requested_placement)
        timeout = int(timeout_seconds or getattr(self.config, "terminal_timeout_seconds", 60))
        start = datetime.now(timezone.utc)
        stdout = ""
        stderr = ""
        exit_code = 1

        if placement == WorkspacePlacement.LOCAL_HOST:
            exec_cwd = self._resolve_local_cwd(cwd)
            proc = subprocess.run(
                cmd,
                shell=True,  # noqa: S602 - explicit local-host mode, policy-gated upstream
                cwd=str(exec_cwd),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            exit_code = int(proc.returncode)
        else:
            network_mode = "bridge" if allow_network else "none"
            executor = SandboxExecutor()
            workspace_dir = self._resolve_sandbox_workspace(cwd)
            result = executor.run(
                command=cmd,
                workspace_dir=str(workspace_dir) if workspace_dir else None,
                env=env,
                network_mode=network_mode,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            exit_code = int(result.exit_code)

        elapsed = max((datetime.now(timezone.utc) - start).total_seconds(), 0.0)
        success = exit_code == 0
        receipt_path = self._write_receipt(
            {
                "timestamp_utc": _utc_now(),
                "command": cmd,
                "placement": placement.value,
                "runtime_profile": profile,
                "action_kind": action_kind,
                "success": success,
                "exit_code": exit_code,
                "duration_seconds": round(elapsed, 6),
                "stdout": stdout,
                "stderr": stderr,
                "context": {
                    "channel": str(ctx.get("channel") or ""),
                    "channel_trust": str(ctx.get("channel_trust") or ""),
                    "session_id": str(ctx.get("session_id") or ""),
                },
            }
        )
        return WorkspaceExecutionResult(
            success=success,
            placement=placement,
            command=cmd,
            runtime_profile=profile,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=elapsed,
            receipt_path=receipt_path,
        )

    def read_text(self, path: str | Path, *, encoding: str = "utf-8") -> str:
        target = self._resolve_local_path(path)
        return target.read_text(encoding=encoding)

    def write_text(self, path: str | Path, content: str, *, encoding: str = "utf-8") -> Path:
        target = self._resolve_local_path(path, ensure_parent=True)
        target.write_text(content, encoding=encoding)
        return target

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _clean_session_id(self, session_id: str) -> str:
        raw = str(session_id or "default").strip().lower()
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in raw).strip("-")
        return safe or "default"

    def _write_receipt(self, payload: Dict[str, Any]) -> Path:
        blob = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        digest = hashlib.sha256(blob).hexdigest()[:10]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self.receipts_dir / f"{stamp}_{digest}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return path

    def _allowed_roots(self) -> Iterable[Path]:
        roots = [self.root_dir]
        extra = getattr(self.config, "terminal_extra_roots", None) or []
        for row in extra:
            try:
                roots.append(Path(row).expanduser())
            except Exception:
                continue
        return roots

    def _resolve_local_cwd(self, cwd: Optional[Path | str]) -> Path:
        target = Path(cwd).expanduser() if cwd else self.root_dir
        resolved = target.resolve()
        for root in self._allowed_roots():
            try:
                if resolved.is_relative_to(root.resolve()):
                    return resolved
            except AttributeError:
                if str(resolved).startswith(str(root.resolve())):
                    return resolved
        raise ValueError(f"cwd '{resolved}' is outside allowed workspace roots")

    def _resolve_sandbox_workspace(self, cwd: Optional[Path | str]) -> Path:
        if cwd:
            return Path(cwd).expanduser()
        sandbox_root = getattr(self.config, "docker_sandbox_workspace", None)
        if sandbox_root:
            return Path(sandbox_root).expanduser()
        return self.root_dir

    def _resolve_local_path(self, path: str | Path, *, ensure_parent: bool = False) -> Path:
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = self.root_dir / target
        resolved = target.resolve()
        for root in self._allowed_roots():
            try:
                if resolved.is_relative_to(root.resolve()):
                    if ensure_parent:
                        resolved.parent.mkdir(parents=True, exist_ok=True)
                    return resolved
            except AttributeError:
                if str(resolved).startswith(str(root.resolve())):
                    if ensure_parent:
                        resolved.parent.mkdir(parents=True, exist_ok=True)
                    return resolved
        raise ValueError(f"path '{resolved}' is outside allowed workspace roots")


_manager: Optional[WorkspaceManager] = None


def get_workspace_manager() -> WorkspaceManager:
    global _manager
    if _manager is None:
        _manager = WorkspaceManager()
    return _manager
