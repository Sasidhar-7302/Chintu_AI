"""Phase 4 dependency bootstrap agent.

This module detects environment/toolchain context, plans safe dependency
installs, executes them, validates outcomes, and writes install receipts.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import get_config

logger = logging.getLogger(__name__)


_PY_MISSING_PATTERNS = [
    re.compile(r"(?:ModuleNotFoundError|ImportError)\s*:\s*No module named ['\"]([A-Za-z0-9_.-]+)['\"]", re.IGNORECASE),
    re.compile(r"no module named ['\"]([A-Za-z0-9_.-]+)['\"]", re.IGNORECASE),
    re.compile(r"missing dependency[: ]+([A-Za-z0-9_.-]+)", re.IGNORECASE),
]
_NODE_MISSING_PATTERNS = [
    re.compile(r"(?:Cannot find module|Cannot find package) ['\"]([^'\"]+)['\"]", re.IGNORECASE),
]
_RUST_MISSING_PATTERNS = [
    re.compile(r"use of undeclared crate or module [`'\"]([A-Za-z0-9_-]+)[`'\"]", re.IGNORECASE),
]
_BINARY_MISSING_PATTERNS = [
    re.compile(r"No such file or directory:\s*['\"]?([A-Za-z0-9_.-]+)['\"]?", re.IGNORECASE),
    re.compile(r"'([A-Za-z0-9_.-]+)'\s+is not recognized as an internal or external command", re.IGNORECASE),
    re.compile(r"command not found:\s*([A-Za-z0-9_.-]+)", re.IGNORECASE),
]

_PY_IMPORT_TO_PACKAGE = {
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "yaml": "pyyaml",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "Crypto": "pycryptodome",
}

_SYSTEM_BINARY_INSTALLERS = {
    "ffmpeg": "Gyan.FFmpeg",
    "git": "Git.Git",
    "node": "OpenJS.NodeJS.LTS",
    "nodejs": "OpenJS.NodeJS.LTS",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_stamp() -> str:
    return _utc_now().strftime("%Y%m%d_%H%M%S_%f")


def _is_path_like(token: str) -> bool:
    value = str(token or "").strip()
    if not value:
        return False
    if "\\" in value or "/" in value:
        return True
    if ":" in value and len(value) > 2:
        return True
    return False


def _redact_command(command: List[str]) -> List[str]:
    cleaned: List[str] = []
    for item in command:
        token = str(item or "")
        low = token.lower()
        if any(secret_key in low for secret_key in ("token=", "password=", "apikey=", "api_key=", "secret=")):
            cleaned.append("[REDACTED]")
        else:
            cleaned.append(token)
    return cleaned


@dataclass(frozen=True)
class EnvironmentSnapshot:
    python_executable: str
    in_venv: bool
    venv_path: str
    cwd: str
    binaries: Dict[str, str]
    project_root: str = ""
    project_markers: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "python_executable": self.python_executable,
            "in_venv": bool(self.in_venv),
            "venv_path": self.venv_path,
            "cwd": self.cwd,
            "binaries": dict(self.binaries),
            "project_root": self.project_root,
            "project_markers": list(self.project_markers),
        }


@dataclass(frozen=True)
class InstallStep:
    manager: str
    package: str
    command: Tuple[str, ...]
    scope: str
    reason: str
    risky: bool = False
    validation_command: Tuple[str, ...] = field(default_factory=tuple)
    rollback_hint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manager": self.manager,
            "package": self.package,
            "command": list(self.command),
            "scope": self.scope,
            "reason": self.reason,
            "risky": bool(self.risky),
            "validation_command": list(self.validation_command),
            "rollback_hint": self.rollback_hint,
        }


@dataclass(frozen=True)
class InstallPlan:
    dependency_kind: str
    dependency_name: str
    failure_message: str
    steps: Tuple[InstallStep, ...]
    requires_confirmation: bool
    confirmation_reason: str
    capability_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dependency_kind": self.dependency_kind,
            "dependency_name": self.dependency_name,
            "failure_message": self.failure_message,
            "steps": [step.to_dict() for step in self.steps],
            "requires_confirmation": bool(self.requires_confirmation),
            "confirmation_reason": self.confirmation_reason,
            "capability_name": self.capability_name,
        }

    def command_preview(self) -> str:
        if not self.steps:
            return ""
        first = self.steps[0]
        return " ".join(_redact_command(list(first.command)))


@dataclass(frozen=True)
class CommandExecution:
    command: Tuple[str, ...]
    return_code: int
    stdout_preview: str
    stderr_preview: str
    kind: str = "install"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": list(self.command),
            "return_code": int(self.return_code),
            "stdout_preview": self.stdout_preview,
            "stderr_preview": self.stderr_preview,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class DependencyRecoveryResult:
    success: bool
    message: str
    receipt_path: str
    installed: Tuple[str, ...] = field(default_factory=tuple)
    rollback_hints: Tuple[str, ...] = field(default_factory=tuple)
    command_log: Tuple[CommandExecution, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": bool(self.success),
            "message": self.message,
            "receipt_path": self.receipt_path,
            "installed": list(self.installed),
            "rollback_hints": list(self.rollback_hints),
            "command_log": [entry.to_dict() for entry in self.command_log],
        }


CommandRunner = Callable[[List[str], Optional[str], int], Tuple[int, str, str]]


class DependencyBootstrapAgent:
    """Plan and execute environment dependency recovery."""

    def __init__(
        self,
        config=None,
        runner: Optional[CommandRunner] = None,
        which: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self.config = config or get_config()
        self._runner = runner or self._default_runner
        self._which = which or shutil.which

    def detect_environment(self, cwd: Optional[str] = None) -> EnvironmentSnapshot:
        current_cwd = str(Path(cwd or os.getcwd()).resolve())
        python_exe = str(Path(sys.executable).resolve())
        in_venv = bool(os.environ.get("VIRTUAL_ENV")) or bool(getattr(sys, "base_prefix", sys.prefix) != sys.prefix)
        venv_path = str(Path(os.environ.get("VIRTUAL_ENV", sys.prefix)).resolve()) if in_venv else ""
        binaries: Dict[str, str] = {}
        for name in ("python", "pip", "uv", "npm", "node", "cargo", "rustc", "winget", "docker", "ffmpeg"):
            path = self._which(name)
            if path:
                binaries[name] = str(Path(path).resolve())
        binaries.setdefault("python", python_exe)
        project_root, markers = self._detect_project_root(Path(current_cwd))
        return EnvironmentSnapshot(
            python_executable=python_exe,
            in_venv=in_venv,
            venv_path=venv_path,
            cwd=current_cwd,
            binaries=binaries,
            project_root=str(project_root) if project_root else "",
            project_markers=tuple(markers),
        )

    def plan_from_failure(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        environment: Optional[EnvironmentSnapshot] = None,
    ) -> Optional[InstallPlan]:
        error_text = str(message or "").strip()
        if not error_text:
            return None
        context = context or {}
        environment = environment or self.detect_environment(str(context.get("cwd") or ""))
        capability = str(context.get("capability_name") or context.get("capability") or "").strip()

        py_module = self._extract_python_missing_module(error_text)
        if py_module:
            return self._plan_python_module(py_module, error_text, capability, environment)

        node_module = self._extract_node_missing_module(error_text)
        if node_module:
            return self._plan_node_module(node_module, error_text, capability, environment)

        rust_crate = self._extract_rust_missing_crate(error_text)
        if rust_crate:
            return self._plan_rust_crate(rust_crate, error_text, capability, environment)

        missing_binary = self._extract_missing_binary(error_text)
        if missing_binary:
            return self._plan_system_binary(missing_binary, error_text, capability, environment)

        return None

    def execute_plan(
        self,
        plan: InstallPlan,
        *,
        context: Optional[Dict[str, Any]] = None,
        environment: Optional[EnvironmentSnapshot] = None,
    ) -> DependencyRecoveryResult:
        context = context or {}
        environment = environment or self.detect_environment(str(context.get("cwd") or ""))
        command_log: List[CommandExecution] = []
        installed: List[str] = []
        rollback_hints: List[str] = []

        for step in plan.steps:
            if step.risky and step.scope in {"global", "system"} and not bool(
                getattr(self.config, "dependency_bootstrap_allow_global_installs", False)
            ):
                message = (
                    "Dependency install requires global/system changes, but "
                    "CHINTU_DEPENDENCY_BOOTSTRAP_ALLOW_GLOBAL_INSTALLS is disabled. "
                    "Use a project venv/user-scope install (or container) instead."
                )
                receipt = self._write_receipt(
                    plan=plan,
                    environment=environment,
                    status="blocked",
                    command_log=command_log,
                    installed=installed,
                    rollback_hints=rollback_hints,
                    extra={"error": message},
                )
                return DependencyRecoveryResult(
                    success=False,
                    message=message,
                    receipt_path=receipt,
                    installed=tuple(installed),
                    rollback_hints=tuple(rollback_hints),
                    command_log=tuple(command_log),
                )

            rc, out, err = self._runner(list(step.command), environment.cwd, 900)
            command_log.append(
                CommandExecution(
                    command=tuple(_redact_command(list(step.command))),
                    return_code=int(rc),
                    stdout_preview=(out or "")[:1200],
                    stderr_preview=(err or "")[:1200],
                    kind="install",
                )
            )
            if rc != 0:
                receipt = self._write_receipt(
                    plan=plan,
                    environment=environment,
                    status="failed",
                    command_log=command_log,
                    installed=installed,
                    rollback_hints=rollback_hints,
                    extra={"error": f"Install command failed for {step.package}."},
                )
                return DependencyRecoveryResult(
                    success=False,
                    message=f"Dependency install failed for {step.package}.",
                    receipt_path=receipt,
                    installed=tuple(installed),
                    rollback_hints=tuple(rollback_hints),
                    command_log=tuple(command_log),
                )

            if step.validation_command:
                v_rc, v_out, v_err = self._runner(list(step.validation_command), environment.cwd, 120)
                command_log.append(
                    CommandExecution(
                        command=tuple(_redact_command(list(step.validation_command))),
                        return_code=int(v_rc),
                        stdout_preview=(v_out or "")[:800],
                        stderr_preview=(v_err or "")[:800],
                        kind="validate",
                    )
                )
                if v_rc != 0:
                    receipt = self._write_receipt(
                        plan=plan,
                        environment=environment,
                        status="failed_validation",
                        command_log=command_log,
                        installed=installed,
                        rollback_hints=rollback_hints,
                        extra={"error": f"Validation failed for {step.package}."},
                    )
                    return DependencyRecoveryResult(
                        success=False,
                        message=f"Dependency installed but validation failed for {step.package}.",
                        receipt_path=receipt,
                        installed=tuple(installed),
                        rollback_hints=tuple(rollback_hints),
                        command_log=tuple(command_log),
                    )

            installed.append(step.package)
            if step.rollback_hint:
                rollback_hints.append(step.rollback_hint)

        receipt = self._write_receipt(
            plan=plan,
            environment=environment,
            status="success",
            command_log=command_log,
            installed=installed,
            rollback_hints=rollback_hints,
        )
        message = f"Installed {', '.join(installed)} and validated dependencies."
        return DependencyRecoveryResult(
            success=True,
            message=message,
            receipt_path=receipt,
            installed=tuple(installed),
            rollback_hints=tuple(rollback_hints),
            command_log=tuple(command_log),
        )

    # ------------------------------------------------------------------
    # Planning internals
    # ------------------------------------------------------------------
    def _plan_python_module(
        self,
        module_name: str,
        failure_message: str,
        capability_name: str,
        environment: EnvironmentSnapshot,
    ) -> Optional[InstallPlan]:
        base_module = str(module_name or "").split(".", 1)[0]
        if not base_module or base_module.startswith("chintu_backend"):
            return None

        package_name = _PY_IMPORT_TO_PACKAGE.get(base_module, base_module.replace("_", "-"))
        python = environment.python_executable
        uv_bin = environment.binaries.get("uv", "")
        allow_global = bool(getattr(self.config, "dependency_bootstrap_allow_global_installs", False))
        prefer_user = bool(getattr(self.config, "dependency_bootstrap_prefer_user_installs", True))
        prefer_uv = bool(getattr(self.config, "dependency_bootstrap_prefer_uv", True))
        force_user_scope = bool(getattr(self.config, "dependency_bootstrap_force_user_scope", True))

        command: Tuple[str, ...]
        manager = "pip"
        scope = "venv"
        risky = False

        if environment.in_venv:
            if prefer_uv and uv_bin:
                command = (uv_bin, "pip", "install", "--python", python, package_name)
                manager = "uv"
                scope = "venv"
                risky = False
            else:
                command = (python, "-m", "pip", "install", package_name)
                manager = "pip"
                scope = "venv"
                risky = False
        elif prefer_user or force_user_scope or not allow_global:
            command = (python, "-m", "pip", "install", "--user", package_name)
            manager = "pip"
            scope = "user"
            risky = False
        elif prefer_uv and uv_bin:
            command = (uv_bin, "pip", "install", "--python", python, package_name)
            manager = "uv"
            scope = "global"
            risky = True
        else:
            command = (python, "-m", "pip", "install", package_name)
            manager = "pip"
            scope = "global"
            risky = True

        policy_notes: List[str] = []
        if scope == "user":
            policy_notes.append("using user-scoped install to avoid global site-packages")
        if manager == "uv":
            policy_notes.append("using uv as isolated package manager")
        if not allow_global:
            policy_notes.append("global installs disabled by policy")
        reason_suffix = f" ({'; '.join(policy_notes)})" if policy_notes else ""

        step = InstallStep(
            manager=manager,
            package=package_name,
            command=command,
            scope=scope,
            reason=f"Python import '{base_module}' was missing.{reason_suffix}",
            risky=risky,
            validation_command=(python, "-c", f"import {base_module}"),
            rollback_hint=f"{python} -m pip uninstall -y {package_name}",
        )
        needs_confirmation = any(s.risky for s in (step,))
        reason = "Global dependency install requires confirmation." if needs_confirmation else ""
        return InstallPlan(
            dependency_kind="python_module",
            dependency_name=base_module,
            failure_message=failure_message[:500],
            steps=(step,),
            requires_confirmation=needs_confirmation,
            confirmation_reason=reason,
            capability_name=capability_name,
        )

    def _plan_node_module(
        self,
        module_name: str,
        failure_message: str,
        capability_name: str,
        environment: EnvironmentSnapshot,
    ) -> Optional[InstallPlan]:
        npm_path = environment.binaries.get("npm")
        if not npm_path:
            return None

        project_root = self._find_project_root_with("package.json", Path(environment.cwd))
        allow_global = bool(getattr(self.config, "dependency_bootstrap_allow_global_installs", False))
        prefer_user = bool(getattr(self.config, "dependency_bootstrap_prefer_npm_user_scope", True))
        module = str(module_name or "").strip()
        if not module:
            return None

        if project_root:
            command = (npm_path, "install", module)
            scope = "project"
            risky = False
        elif prefer_user or not allow_global:
            command = (npm_path, "install", "--location=user", module)
            scope = "user"
            risky = False
        else:
            command = (npm_path, "install", "-g", module)
            scope = "global"
            risky = True

        step = InstallStep(
            manager="npm",
            package=module,
            command=command,
            scope=scope,
            reason=f"Node module '{module}' was missing.",
            risky=risky,
            validation_command=(),
            rollback_hint=(
                f"{npm_path} uninstall -g {module}"
                if scope == "global"
                else f"{npm_path} uninstall {module}"
            ),
        )
        needs_confirmation = any(s.risky for s in (step,))
        reason = "Global npm install requires confirmation." if needs_confirmation else ""
        return InstallPlan(
            dependency_kind="node_module",
            dependency_name=module,
            failure_message=failure_message[:500],
            steps=(step,),
            requires_confirmation=needs_confirmation,
            confirmation_reason=reason,
            capability_name=capability_name,
        )

    def _plan_rust_crate(
        self,
        crate_name: str,
        failure_message: str,
        capability_name: str,
        environment: EnvironmentSnapshot,
    ) -> Optional[InstallPlan]:
        cargo = environment.binaries.get("cargo")
        if not cargo:
            return None
        project_root = self._find_project_root_with("Cargo.toml", Path(environment.cwd))
        if not project_root:
            return None
        crate = str(crate_name or "").strip()
        if not crate:
            return None

        step = InstallStep(
            manager="cargo",
            package=crate,
            command=(cargo, "add", crate),
            scope="project",
            reason=f"Rust crate '{crate}' was missing.",
            risky=False,
            validation_command=(cargo, "check"),
            rollback_hint=f"Remove '{crate}' from Cargo.toml if needed.",
        )
        return InstallPlan(
            dependency_kind="rust_crate",
            dependency_name=crate,
            failure_message=failure_message[:500],
            steps=(step,),
            requires_confirmation=False,
            confirmation_reason="",
            capability_name=capability_name,
        )

    def _plan_system_binary(
        self,
        binary_name: str,
        failure_message: str,
        capability_name: str,
        environment: EnvironmentSnapshot,
    ) -> Optional[InstallPlan]:
        name = str(binary_name or "").strip().lower()
        if not name or _is_path_like(name):
            return None
        winget = environment.binaries.get("winget")
        installer_id = _SYSTEM_BINARY_INSTALLERS.get(name)
        if not winget or not installer_id:
            return None

        step = InstallStep(
            manager="winget",
            package=name,
            command=(winget, "install", "--id", installer_id, "-e"),
            scope="system",
            reason=f"System binary '{name}' is missing.",
            risky=True,
            validation_command=(name, "-version"),
            rollback_hint=f"Uninstall '{installer_id}' from Windows Apps settings if needed.",
        )
        return InstallPlan(
            dependency_kind="system_binary",
            dependency_name=name,
            failure_message=failure_message[:500],
            steps=(step,),
            requires_confirmation=True,
            confirmation_reason="System-level install requires confirmation.",
            capability_name=capability_name,
        )

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------
    def _extract_python_missing_module(self, message: str) -> str:
        for pattern in _PY_MISSING_PATTERNS:
            match = pattern.search(message or "")
            if match:
                return str(match.group(1) or "").strip()
        return ""

    def _extract_node_missing_module(self, message: str) -> str:
        for pattern in _NODE_MISSING_PATTERNS:
            match = pattern.search(message or "")
            if match:
                return str(match.group(1) or "").strip()
        return ""

    def _extract_rust_missing_crate(self, message: str) -> str:
        for pattern in _RUST_MISSING_PATTERNS:
            match = pattern.search(message or "")
            if match:
                return str(match.group(1) or "").strip()
        return ""

    def _extract_missing_binary(self, message: str) -> str:
        for pattern in _BINARY_MISSING_PATTERNS:
            match = pattern.search(message or "")
            if match:
                candidate = str(match.group(1) or "").strip().strip("'\"")
                if candidate and not _is_path_like(candidate):
                    return candidate
        return ""

    # ------------------------------------------------------------------
    # Execution internals
    # ------------------------------------------------------------------
    @staticmethod
    def _default_runner(command: List[str], cwd: Optional[str], timeout_s: int) -> Tuple[int, str, str]:
        proc = subprocess.run(
            command,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=max(10, int(timeout_s)),
            shell=False,
            check=False,
        )
        return int(proc.returncode), str(proc.stdout or ""), str(proc.stderr or "")

    @staticmethod
    def _find_project_root_with(filename: str, start_dir: Path) -> Optional[Path]:
        current = Path(start_dir).resolve()
        for parent in [current, *list(current.parents)]:
            if (parent / filename).exists():
                return parent
        return None

    @staticmethod
    def _detect_project_root(start_dir: Path) -> Tuple[Optional[Path], List[str]]:
        current = Path(start_dir).resolve()
        markers = ("pyproject.toml", "requirements.txt", "package.json", "Cargo.toml")
        for parent in [current, *list(current.parents)]:
            found = [marker for marker in markers if (parent / marker).exists()]
            if found:
                return parent, found
        return None, []

    def _write_receipt(
        self,
        *,
        plan: InstallPlan,
        environment: EnvironmentSnapshot,
        status: str,
        command_log: List[CommandExecution],
        installed: List[str],
        rollback_hints: List[str],
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        receipt_dir = Path(getattr(self.config, "dependency_bootstrap_receipts_dir", Path.cwd() / "generated_reports"))
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = receipt_dir / f"dependency_bootstrap_{_utc_stamp()}.json"
        payload: Dict[str, Any] = {
            "timestamp_utc": _utc_now().isoformat().replace("+00:00", "Z"),
            "status": status,
            "why": plan.failure_message,
            "environment": environment.to_dict(),
            "policy": {
                "allow_global_installs": bool(getattr(self.config, "dependency_bootstrap_allow_global_installs", False)),
                "prefer_user_installs": bool(getattr(self.config, "dependency_bootstrap_prefer_user_installs", True)),
                "force_user_scope": bool(getattr(self.config, "dependency_bootstrap_force_user_scope", True)),
                "prefer_uv": bool(getattr(self.config, "dependency_bootstrap_prefer_uv", True)),
                "prefer_npm_user_scope": bool(getattr(self.config, "dependency_bootstrap_prefer_npm_user_scope", True)),
            },
            "plan": plan.to_dict(),
            "installed": list(installed),
            "rollback_hints": list(dict.fromkeys([h for h in rollback_hints if h])),
            "commands": [entry.to_dict() for entry in command_log],
        }
        if extra:
            payload["extra"] = extra
        receipt_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        return str(receipt_path)


_dependency_bootstrap_agent: Optional[DependencyBootstrapAgent] = None


def get_dependency_bootstrap_agent(config=None) -> DependencyBootstrapAgent:
    global _dependency_bootstrap_agent
    if _dependency_bootstrap_agent is None:
        _dependency_bootstrap_agent = DependencyBootstrapAgent(config=config)
    return _dependency_bootstrap_agent
