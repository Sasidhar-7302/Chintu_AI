"""Skill runner implementation."""

from __future__ import annotations

import shlex
import subprocess
import os
from typing import Dict

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .skill_registry import SkillSpec


def run_skill(spec: "SkillSpec", text: str, context: Dict) -> str:
    """Run a skill; currently supports shell commands only."""
    if spec.kind != "shell":
        raise ValueError(f"Unsupported skill type: {spec.kind}")

    params = _extract_args(spec, text)
    cmd = spec.command.format(**params)
    return _run_shell(cmd)


def _extract_args(spec: SkillSpec, text: str) -> Dict[str, str]:
    # Basic heuristic: if args defined, try to fill from text using "arg=value"
    params: Dict[str, str] = {}
    lowered = text.lower()
    for arg in spec.args:
        marker = f"{arg}="
        if marker in lowered:
            raw = text.lower().split(marker, 1)[1].strip()
            params[arg] = raw.split()[0]
    # Fallback: single arg uses full text
    if len(spec.args) == 1 and spec.args[0] not in params:
        params[spec.args[0]] = text
    return params


def _run_shell(command: str) -> str:
    # Restrict execution to project directory
    cwd = os.getcwd()
    args = shlex.split(command, posix=False)
    result = subprocess.run(args, capture_output=True, text=True, timeout=30, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Skill command failed")
    return result.stdout.strip() or "Done."


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
