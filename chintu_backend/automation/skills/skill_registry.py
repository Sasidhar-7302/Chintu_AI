"""Skill registry for declarative SKILL.md capabilities (Phase 3)."""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType
from chintu_backend.core.config import get_config
from chintu_backend.automation.skills.skill_runner import run_skill

logger = logging.getLogger(__name__)


@dataclass
class SkillSpec:
    name: str
    description: str
    triggers: List[str]
    command: str
    args: List[str] = field(default_factory=list)
    kind: str = "shell"  # shell | http | python (future)
    requires_env: List[str] = field(default_factory=list)
    requires_bin: List[str] = field(default_factory=list)
    source: Optional[str] = None


class SkillRegistry:
    """Loads and registers skills as capabilities."""

    def __init__(self):
        self._skills: Dict[str, SkillSpec] = {}
        self.config = get_config()

    def load_sources(self, sources: List[tuple[Path, str]]) -> int:
        count = 0
        for skills_dir, label in sources:
            count += self.load_dir(skills_dir, source_label=label)
        return count

    def load_dir(self, skills_dir: Path, source_label: Optional[str] = None) -> int:
        count = 0
        if not skills_dir.exists():
            logger.info("Skills directory not found: %s", skills_dir)
            return 0
        for path in skills_dir.rglob("*.md"):
            count += self._load_file(path, source_label=source_label)
        return count

    def _load_file(self, path: Path, source_label: Optional[str] = None) -> int:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed reading skill file %s: %s", path, exc)
            return 0
        specs = parse_skills_from_markdown(content)
        added = 0
        for spec in specs:
            if source_label:
                spec.source = source_label
            if spec.source is None:
                spec.source = str(path)
            if spec.name in self._skills:
                logger.warning("Overwriting skill: %s", spec.name)
            self._skills[spec.name] = spec
            added += 1
        logger.info("Loaded %d skill(s) from %s", added, path.name)
        return added

    def register_capabilities(self, capability_registry) -> int:
        count = 0
        for spec in self._skills.values():
            if not _is_skill_available(spec):
                logger.info("Skipping skill %s (requirements not met)", spec.name)
                continue
            capability_registry.register(
                Capability(
                    name=f"skill::{spec.name}",
                    triggers=spec.triggers,
                    handler=self._make_handler(spec),
                    requires_confirmation=False,
                    description=spec.description,
                    capability_type=CapabilityType.AUTOMATION,
                    examples=[],
                )
            )
            count += 1
        return count

    def _make_handler(self, spec: SkillSpec):
        def handler(text: str, context: Dict) -> ActionResult:
            if not self.config.skills_enabled:
                return ActionResult.fail("Skills are disabled. Enable CHINTU_SKILLS_ENABLED to use them.")
            if spec.kind == "shell" and not self.config.skills_allow_shell:
                return ActionResult.fail("Shell skills are disabled by policy.")
            missing_env = [key for key in spec.requires_env if not os.getenv(key)]
            if missing_env:
                missing = ", ".join(missing_env)
                try:
                    from chintu_backend.ui import get_a2ui_service

                    a2ui = get_a2ui_service()
                    a2ui.render_credential_prompt(
                        keys=missing_env,
                        title="Connect Required Credentials",
                        description=(
                            "I need these credentials to run this skill. "
                            "Provide them below and I will save them securely."
                        ),
                        view_id=f"credentials:skill:{spec.name}",
                        source=f"skill:{spec.name}",
                    )
                    return ActionResult.fail(
                        f"Missing required credentials: {missing}. "
                        "Please enter them in the popup.",
                        capability=f"skill::{spec.name}",
                    )
                except Exception:
                    return ActionResult.fail(
                        f"Missing required environment variables: {missing}. "
                        "Tell me the values and I can save them to .env.",
                        capability=f"skill::{spec.name}",
                    )
            try:
                if not any(trigger in text.lower() for trigger in spec.triggers):
                    return ActionResult.fail("Skill not relevant for this request.")
                if self.config.skills_use_docker:
                    from chintu_backend.automation.skills.skill_runner import run_skill_in_docker
                    result = run_skill_in_docker(
                        spec.command.format(**_safe_args(spec, text)),
                        image=self.config.skills_docker_image,
                        network_mode=self.config.skills_docker_network_mode,
                        workdir=self.config.skills_docker_workdir,
                    )
                else:
                    result = run_skill(spec, text, context)
                return ActionResult.ok(result, capability=f"skill::{spec.name}")
            except Exception as exc:
                return ActionResult.fail(f"Skill failed: {exc}", capability=f"skill::{spec.name}")

        return handler


def parse_skills_from_markdown(content: str) -> List[SkillSpec]:
    """Parse skills from a SKILL.md file using key: value lines."""
    blocks = re.split(r"\n(?=#+\s+)", content.strip())
    specs: List[SkillSpec] = []
    for block in blocks:
        if not block.strip():
            continue
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        title = None
        data: Dict[str, str] = {}
        for ln in lines:
            if ln.startswith("#"):
                title = ln.lstrip("#").strip()
                continue
            if ":" in ln:
                key, val = ln.split(":", 1)
                data[key.strip().lower()] = val.strip()
        if not title or "command" not in data:
            continue
        triggers = []
        if "triggers" in data:
            triggers = [t.strip() for t in data["triggers"].split(",") if t.strip()]
        elif "trigger" in data:
            triggers = [t.strip() for t in data["trigger"].split(",") if t.strip()]
        description = data.get("description", f"Skill: {title}")
        args = [a.strip() for a in data.get("args", "").split(",") if a.strip()]
        kind = data.get("type", "shell").lower()
        requires_env = [a.strip() for a in data.get("requires-env", "").split(",") if a.strip()]
        requires_bin = [a.strip() for a in data.get("requires-bin", "").split(",") if a.strip()]
        specs.append(
            SkillSpec(
                name=slugify(title),
                description=description,
                triggers=triggers or [title.lower()],
                command=data["command"],
                args=args,
                kind=kind,
                requires_env=requires_env,
                requires_bin=requires_bin,
            )
        )
    return specs


def _safe_args(spec: SkillSpec, text: str) -> Dict[str, str]:
    # Use the same arg extraction logic as run_skill, but without executing
    params: Dict[str, str] = {}
    lowered = text.lower()
    for arg in spec.args:
        marker = f"{arg}="
        if marker in lowered:
            raw = text.lower().split(marker, 1)[1].strip()
            params[arg] = raw.split()[0]
    if len(spec.args) == 1 and spec.args[0] not in params:
        params[spec.args[0]] = text
    return params


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    return value.strip("-")


def _is_skill_available(spec: SkillSpec) -> bool:
    # Only gate on binaries; missing env vars should prompt the user at runtime.
    for bin_name in spec.requires_bin:
        if shutil.which(bin_name) is None:
            return False
    return True
