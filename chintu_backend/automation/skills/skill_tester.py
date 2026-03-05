"""Skill validation and safety checks."""

from __future__ import annotations

import fnmatch
import re
import shutil
import shlex
import subprocess
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from chintu_backend.core.config import get_config
from chintu_backend.automation.skills.skill_registry import SkillSpec


_DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bdel\s+/f\b",
    r"\bformat\s+\w+:",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpowershell\s+-enc\b",
    r"\bcurl\s+.+\|\s*(sh|bash)\b",
    r"\bwget\s+.+\|\s*(sh|bash)\b",
]


def _split_patterns(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _pattern_match(name: str, patterns: List[str]) -> bool:
    if not patterns:
        return True
    for pat in patterns:
        if fnmatch.fnmatch(name, pat):
            return True
    return False


def validate_skill_spec(
    spec: SkillSpec,
    config=None,
    *,
    proposal_mode: bool = False,
    existing_specs: Optional[List[SkillSpec]] = None,
) -> List[str]:
    """Return a list of issues for a proposed skill spec."""
    config = config or get_config()
    issues: List[str] = []

    allowlist = _split_patterns(getattr(config, "skills_allowlist", None))
    denylist = _split_patterns(getattr(config, "skills_denylist", None))

    if allowlist and not _pattern_match(spec.name, allowlist):
        issues.append("Skill name not in allowlist.")
    if denylist and _pattern_match(spec.name, denylist):
        issues.append("Skill name is blocked by denylist.")

    command = (spec.command or "").lower()
    if command:
        for pattern in _DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                issues.append(f"Dangerous command pattern detected: {pattern}")
                break
    test_command = (spec.test_command or "").lower()
    for pattern in _DANGEROUS_PATTERNS:
        if test_command and re.search(pattern, test_command):
            issues.append(f"Dangerous test command pattern detected: {pattern}")
            break

    if spec.kind == "shell" and not getattr(config, "skills_allow_shell", False):
        issues.append("Shell skills are disabled by policy.")

    for binary in (spec.requires_bin or []):
        if not shutil.which(binary):
            issues.append(f"Missing required binary: {binary}")

    if proposal_mode and bool(getattr(config, "skills_generalization_enforced", True)):
        try:
            from chintu_backend.automation.skills.skill_generalization import (
                analyze_proposal_generalization,
                load_existing_skill_specs,
            )

            if existing_specs is None:
                existing_specs = load_existing_skill_specs(config)
            threshold = float(getattr(config, "skills_generalization_similarity_threshold", 0.78))
            issues.extend(
                analyze_proposal_generalization(
                    spec,
                    existing_specs=existing_specs,
                    similarity_threshold=threshold,
                )
            )
        except Exception:
            # Proposal validation should keep running even if generalization checks fail.
            pass

    return issues


@dataclass
class SkillTestResult:
    name: str
    passed: bool
    message: str
    command: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "command": self.command,
        }


def run_skill_tests(specs: List[SkillSpec], config=None) -> Dict[str, Any]:
    """Run regression tests defined in SKILL.md (Test: ...)."""
    config = config or get_config()
    if not getattr(config, "skills_test_enabled", True):
        return {"passed": True, "skipped": True, "results": []}

    from chintu_backend.security.command_guard import get_command_guard
    guard = get_command_guard()
    timeout = int(getattr(config, "skills_test_timeout_seconds", 20))

    results: List[SkillTestResult] = []
    passed = True

    for spec in specs:
        test_cmd = (spec.test_command or "").strip()
        if not test_cmd:
            results.append(SkillTestResult(name=spec.name, passed=True, message="no test defined"))
            continue

        safe, reason = guard.is_safe(test_cmd)
        if not safe:
            results.append(SkillTestResult(name=spec.name, passed=False, message=f"blocked: {reason}", command=test_cmd))
            passed = False
            continue

        try:
            args = shlex.split(test_cmd, posix=False)
            proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=str(config.docker_sandbox_workspace or "."))  # noqa: S603,S607
            if proc.returncode != 0:
                msg = proc.stderr.strip() or proc.stdout.strip() or "test failed"
                results.append(SkillTestResult(name=spec.name, passed=False, message=msg, command=test_cmd))
                passed = False
            else:
                results.append(SkillTestResult(name=spec.name, passed=True, message="ok", command=test_cmd))
        except Exception as exc:  # noqa: BLE001
            results.append(SkillTestResult(name=spec.name, passed=False, message=str(exc), command=test_cmd))
            passed = False

    return {
        "passed": passed,
        "skipped": False,
        "results": [r.to_dict() for r in results],
    }
