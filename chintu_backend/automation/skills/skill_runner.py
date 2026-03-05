"""Skill runner implementation."""

from __future__ import annotations

import shlex
import subprocess
import os
import sys
from pathlib import Path
from typing import Any, Dict

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .skill_registry import SkillSpec


def run_skill(spec: SkillSpec, text: str, context: Dict[str, Any]) -> Any:
    """Run a skill with security and confirmation checks."""
    from chintu_backend.security.command_guard import get_command_guard
    guard = get_command_guard()
    
    params = _extract_args(spec, text)
    
    # Expand {SKILL_DIR} if present
    if "{SKILL_DIR}" in spec.command:
        skill_dir = os.path.dirname(spec.source) if spec.source else os.getcwd()
        cmd_template = spec.command.replace("{SKILL_DIR}", skill_dir)
    else:
        cmd_template = spec.command
        
    cmd = cmd_template.format(**params)
    
    # Security Check
    safe, reason = guard.is_safe(cmd)
    if not safe:
        raise ValueError(f"Security Block: {reason}")
    
    # Confirmation Check
    if _requires_confirmation(spec, cmd) and not context.get("_confirmed"):
        def pending():
            updated_ctx = dict(context)
            updated_ctx["_confirmed"] = True
            return run_skill(spec, text, updated_ctx)
            
        from chintu_backend.core.capabilities import ActionResult
        return ActionResult.confirm(
            f"I'm about to run this shell command:\n`{cmd}`\n\nDo you want to proceed?",
            pending,
            f"skill:{spec.name}"
        )

    return _run_shell(cmd)


def _requires_confirmation(spec: "SkillSpec", command: str) -> bool:
    """Confirm only high-impact skill commands unless overridden in metadata."""
    meta = spec.metadata if isinstance(getattr(spec, "metadata", None), dict) else {}
    explicit = meta.get("requires_confirmation")
    if explicit is not None:
        return bool(explicit)

    # Low-risk local skill scripts should not prompt on every run.
    if _is_safe_local_python_command(command):
        return False

    try:
        from chintu_backend.core.safe_exec import CommandRisk, get_safe_executor

        tokens = shlex.split(command, posix=False)
        if not tokens:
            return False
        risk = get_safe_executor().get_risk_level(tokens[0])
        return risk == CommandRisk.HIGH
    except Exception:
        # Conservative fallback to existing guard behavior.
        from chintu_backend.security.command_guard import get_command_guard

        return get_command_guard().needs_confirmation(command)


def _is_safe_local_python_command(command: str) -> bool:
    """Allow non-interactive project skill scripts without confirmation prompts."""
    raw = str(command or "").strip()
    if not raw:
        return False
    if any(token in raw for token in ("&&", "||", "|", ";", ">", "<", "`")):
        return False
    try:
        tokens = shlex.split(raw, posix=os.name != "nt")
    except Exception:
        return False
    if len(tokens) < 2:
        return False
    first = Path(str(tokens[0])).name.lower()
    if first not in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}:
        return False
    script = Path(str(tokens[1]).strip("\"'"))
    if script.suffix.lower() != ".py":
        return False
    try:
        resolved = script.resolve()
    except Exception:
        return False
    if not resolved.exists():
        return False
    return "skills" in {part.lower() for part in resolved.parts}


def _extract_args(spec: SkillSpec, text: str) -> Dict[str, str]:
    # Basic heuristic: if args defined, try to fill from text using "arg=value"
    params: Dict[str, str] = {}
    lowered = text.lower()
    for arg in spec.args:
        marker = f"{arg}="
        if marker in lowered:
            raw = text.lower().split(marker, 1)[1].strip()
            params[arg] = _sanitize_skill_arg(raw.split()[0])
    # Fallback: single arg uses full text
    if len(spec.args) == 1 and spec.args[0] not in params:
        params[spec.args[0]] = _sanitize_skill_arg(text)
    return params


def _sanitize_skill_arg(value: str) -> str:
    """Normalize user arg text to avoid markdown/control tokens in shell commands."""
    raw = str(value or "")
    # Strip markdown code ticks and normalize smart quotes.
    raw = raw.replace("`", "")
    raw = raw.replace("\u201c", "\"").replace("\u201d", "\"")
    raw = raw.replace("\u2018", "'").replace("\u2019", "'")
    return raw.strip()


def _run_shell(command: str) -> str:
    # Use global SafeExecutor for consistent policy enforcement
    from chintu_backend.core.safe_exec import get_safe_executor
    executor = get_safe_executor()
    
    # Split into args
    import shlex
    try:
        args = shlex.split(command, posix=False)
    except Exception:
        args = [command]

    # Ensure skill scripts run with the current interpreter (venv-safe).
    if args:
        first = Path(str(args[0])).name.lower()
        if first in {"python", "python.exe", "python3", "python3.exe"}:
            args[0] = sys.executable
        
    result = executor.run(args)
    if result.success:
        return result.stdout or "Done."
    else:
        raise RuntimeError(result.error or result.stderr or "Skill execution failed")


def run_skill_in_docker(command: str, image: str, network_mode: str, workdir: str) -> str:
    cwd = os.getcwd()
    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        network_mode,
        "-v",
        f"{cwd}:{workdir}",
        "-w",
        workdir,
        image,
        "sh",
        "-lc",
        command,
    ]
    result = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Skill docker command failed")
    return result.stdout.strip() or "Done."
