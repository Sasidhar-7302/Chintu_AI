"""Skill registry for declarative SKILL.md capabilities (Phase 3)."""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType
from chintu_backend.core.config import get_config
from chintu_backend.automation.skills.skill_runner import run_skill
from chintu_backend.automation.skills.supply_chain import (
    evaluate_skill_supply_chain,
    write_skill_execution_receipt,
)

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
    test_command: Optional[str] = None
    instruction: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class SkillRegistry:
    """Loads and registers skills as capabilities."""

    def __init__(self):
        self._skills: Dict[str, SkillSpec] = {}
        self._blocked_supply_chain: Dict[str, Dict[str, Any]] = {}
        self.config = get_config()
        self._watcher_thread: Optional[threading.Thread] = None
        self._watcher_stop = threading.Event()
        self._watch_snapshot: Dict[str, float] = {}

    def load_sources(self, sources: List[tuple[Path, str]]) -> int:
        self._blocked_supply_chain.clear()
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
            # Learned-skill history snapshots are for rollback/debugging, not for execution.
            # Loading them re-registers the same skill dozens of times.
            if ".history" in path.parts:
                continue
            if not _looks_like_skill_file(path):
                continue
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
            spec.metadata.setdefault("source_label", source_label or "workspace")
            if spec.source is None:
                spec.source = str(path)
            try:
                decision = evaluate_skill_supply_chain(
                    spec=spec,
                    skill_path=path,
                    source_label=(source_label or "workspace"),
                    config=self.config,
                )
                supply_meta = decision.to_metadata()
                supply_meta["receipt_path"] = decision.receipt_path
                spec.metadata["supply_chain"] = supply_meta
                if decision.blocked:
                    self._blocked_supply_chain[spec.name] = supply_meta
                    logger.warning(
                        "Blocking skill %s by supply-chain policy: %s (%s)",
                        spec.name,
                        decision.reason,
                        ", ".join(decision.issues[:3]) if decision.issues else "no details",
                    )
                    continue
            except Exception as exc:
                logger.warning("Supply-chain scan failed for %s: %s", spec.name, exc)
            if spec.name in self._skills:
                logger.warning("Overwriting skill: %s", spec.name)
            self._skills[spec.name] = spec
            added += 1
        logger.info("Loaded %d skill(s) from %s", added, path.name)
        return added

    def register_capabilities(self, capability_registry) -> int:
        try:
            capability_registry.unregister_prefix("skill::")
        except Exception:
            pass
        count = 0
        for spec in self._skills.values():
            if (
                spec.kind == "shell"
                and not self.config.skills_allow_shell
                and not _is_safe_local_python_skill(spec)
            ):
                # Do not register blocked shell skills; they otherwise steal matches
                # from built-in capabilities and fail at runtime.
                logger.info("Skipping shell skill %s (shell disabled by policy)", spec.name)
                continue
            if not _is_skill_available(spec):
                logger.info("Skipping skill %s (requirements not met)", spec.name)
                continue
            capability_name = f"skill::{spec.name}"
            supply_meta = spec.metadata.get("supply_chain", {}) if isinstance(spec.metadata, dict) else {}
            requires_confirmation = bool(supply_meta.get("requires_explicit_approval", False))
            capability_registry.register(
                Capability(
                    name=capability_name,
                    triggers=spec.triggers,
                    handler=self._make_handler(spec),
                    requires_confirmation=requires_confirmation,
                    description=spec.description,
                    capability_type=CapabilityType.AUTOMATION if spec.kind != "instruction" else CapabilityType.AI_AGENT,
                    examples=[],
                )
            )
            self._register_skill_policy_contract(capability_name, spec)
            count += 1
        return count

    def start_watcher(self, capability_registry, sources: List[tuple[Path, str]]) -> None:
        if self._watcher_thread and self._watcher_thread.is_alive():
            return
        self._watch_snapshot = _snapshot_skills(sources)
        interval = getattr(self.config, "skills_watch_interval_seconds", 5)

        def _watch() -> None:
            while not self._watcher_stop.is_set():
                try:
                    latest = _snapshot_skills(sources)
                    if latest != self._watch_snapshot:
                        self._watch_snapshot = latest
                        self._skills.clear()
                        self.load_sources(sources)
                        self.register_capabilities(capability_registry)
                        logger.info("Skills watcher reloaded skills")
                except Exception as exc:
                    logger.debug("Skills watcher error: %s", exc)
                self._watcher_stop.wait(interval)

        self._watcher_thread = threading.Thread(target=_watch, daemon=True)
        self._watcher_thread.start()

    def stop_watcher(self) -> None:
        self._watcher_stop.set()

    def get_blocked_supply_chain(self) -> Dict[str, Dict[str, Any]]:
        """Return blocked skill metadata from supply-chain checks."""
        return {name: dict(meta) for name, meta in self._blocked_supply_chain.items()}

    def _make_handler(self, spec: SkillSpec):
        def handler(text: str, context: Dict) -> ActionResult:
            if not self.config.skills_enabled:
                return ActionResult.fail("Skills are disabled. Enable CHINTU_SKILLS_ENABLED to use them.")
            supply_meta = spec.metadata.get("supply_chain", {}) if isinstance(spec.metadata, dict) else {}
            trust_level = str(supply_meta.get("trust_level") or "unknown").strip()
            source_label = str(
                supply_meta.get("source_label")
                or spec.metadata.get("source_label")
                or "unknown"
            ).strip()
            force_sandbox = bool(supply_meta.get("force_sandbox", False))
            if spec.kind == "instruction":
                if not any(_skill_trigger_matches(trigger, text) for trigger in spec.triggers):
                    return ActionResult.fail("Skill not relevant for this request.")
                context_block = _format_instruction_skill(spec)
                return ActionResult.ok(
                    "__LLM_ROUTE__",
                    {"skill_context": context_block, "skill_name": spec.name},
                    capability=f"skill::{spec.name}",
                )
            if (
                spec.kind == "shell"
                and not self.config.skills_allow_shell
                and not _is_safe_local_python_skill(spec)
            ):
                return ActionResult.fail("Shell skills are disabled by policy.")
            if force_sandbox and not self.config.skills_use_docker:
                return ActionResult.fail(
                    "This skill is untrusted and must run in Docker sandbox mode. "
                    "Enable CHINTU_SKILLS_USE_DOCKER=true or approve a trusted source."
                )
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
                        "Tell me the values and I can save them securely.",
                        capability=f"skill::{spec.name}",
                    )
            try:
                if not any(_skill_trigger_matches(trigger, text) for trigger in spec.triggers):
                    return ActionResult.fail("Skill not relevant for this request.")
                cmd_rendered = spec.command
                try:
                    cmd_rendered = spec.command.format(**_safe_args(spec, text))
                except Exception:
                    cmd_rendered = spec.command
                use_docker = bool(self.config.skills_use_docker or force_sandbox)
                mode = "docker" if use_docker else "local"
                if use_docker:
                    from chintu_backend.automation.skills.skill_runner import run_skill_in_docker
                    result = run_skill_in_docker(
                        cmd_rendered,
                        image=self.config.skills_docker_image,
                        network_mode=self.config.skills_docker_network_mode,
                        workdir=self.config.skills_docker_workdir,
                    )
                else:
                    result = run_skill(spec, text, context)
                
                # If the skill runner returned an ActionResult (e.g. for confirmation), pass it through
                if isinstance(result, ActionResult):
                    # Ensure capability name is set
                    if not result.capability_name:
                        result.capability_name = f"skill::{spec.name}"
                    if not bool(result.requires_confirmation):
                        receipt = write_skill_execution_receipt(
                            skill_name=spec.name,
                            command=cmd_rendered,
                            mode=mode,
                            source_label=source_label,
                            trust_level=trust_level,
                            success=bool(result.success),
                            message=str(result.message or ""),
                            config=self.config,
                        )
                        if receipt and isinstance(result.data, dict):
                            result.data.setdefault("supply_chain_receipt", receipt)
                    return result

                action = ActionResult.ok(result, capability=f"skill::{spec.name}")
                receipt = write_skill_execution_receipt(
                    skill_name=spec.name,
                    command=cmd_rendered,
                    mode=mode,
                    source_label=source_label,
                    trust_level=trust_level,
                    success=True,
                    message=str(result),
                    config=self.config,
                )
                if receipt and isinstance(action.data, dict):
                    action.data.setdefault("supply_chain_receipt", receipt)
                return action
            except Exception as exc:
                receipt = write_skill_execution_receipt(
                    skill_name=spec.name,
                    command=str(spec.command or ""),
                    mode="docker" if bool(self.config.skills_use_docker or force_sandbox) else "local",
                    source_label=source_label,
                    trust_level=trust_level,
                    success=False,
                    message=str(exc),
                    config=self.config,
                )
                fail_result = ActionResult(
                    success=False,
                    message=f"Skill failed: {exc}",
                    data={"supply_chain_receipt": receipt} if receipt else None,
                    capability_name=f"skill::{spec.name}",
                )
                return fail_result

        return handler

    def _register_skill_policy_contract(self, capability_name: str, spec: SkillSpec) -> None:
        """Register a policy contract for a loaded skill capability."""
        try:
            from chintu_backend.policy import CapabilityContract, RiskLevel, get_policy_engine
        except Exception:
            return

        metadata = spec.metadata if isinstance(spec.metadata, dict) else {}
        policy_data = metadata.get("policy") if isinstance(metadata.get("policy"), dict) else {}

        risk_text = str(policy_data.get("risk") or "").strip().lower()
        risk_lookup = {
            "none": RiskLevel.NONE,
            "low": RiskLevel.LOW,
            "medium": RiskLevel.MEDIUM,
            "high": RiskLevel.HIGH,
            "critical": RiskLevel.CRITICAL,
        }
        if risk_text in risk_lookup:
            risk = risk_lookup[risk_text]
        elif spec.kind == "instruction":
            risk = RiskLevel.LOW
        elif spec.kind == "shell":
            risk = RiskLevel.MEDIUM
        else:
            risk = RiskLevel.LOW

        requires_confirmation = bool(
            policy_data.get("requires_confirmation", metadata.get("requires_confirmation", False))
        )
        requires_internet = bool(policy_data.get("requires_internet", False))
        can_run_background = bool(policy_data.get("can_run_background", True))

        side_effects = policy_data.get("side_effects", [])
        if not isinstance(side_effects, list):
            side_effects = [str(side_effects)] if side_effects else []
        side_effects = [str(effect).strip() for effect in side_effects if str(effect).strip()]

        if not side_effects and spec.kind == "shell":
            side_effects = ["skill_shell_exec"]

        contract = CapabilityContract(
            risk_level=risk,
            requires_internet=requires_internet,
            requires_confirmation=requires_confirmation,
            can_run_background=can_run_background,
            side_effects=side_effects,
            description=spec.description or f"Skill contract for {spec.name}",
        )
        try:
            get_policy_engine().register_contract(capability_name, contract)
        except Exception:
            return


def parse_skills_from_markdown(content: str) -> List[SkillSpec]:
    """Parse skills from a SKILL.md file (supports YAML frontmatter + legacy blocks)."""
    frontmatter, body = _split_frontmatter(content)
    if frontmatter:
        spec = _spec_from_frontmatter(frontmatter, body)
        return [spec] if spec else []

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
        if not title:
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
        test_command = data.get("test") or data.get("test-command") or data.get("tests")
        command = data.get("command", "")
        instruction = None
        if not command:
            kind = "instruction"
            instruction = block.strip()
        specs.append(
            SkillSpec(
                name=slugify(title),
                description=description,
                triggers=triggers or [title.lower()],
                command=command,
                args=args,
                kind=kind,
                requires_env=requires_env,
                requires_bin=requires_bin,
                test_command=test_command,
                instruction=instruction,
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


def _skill_trigger_matches(trigger: str, text: str) -> bool:
    needle = str(trigger or "").strip().lower()
    haystack = str(text or "").lower()
    if not needle or not haystack:
        return False
    if any(c in needle for c in "()[]?*+^$|"):
        try:
            return re.search(needle, haystack) is not None
        except re.error:
            return needle in haystack
    return needle in haystack


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    return value.strip("-")


def _looks_like_skill_file(path: Path) -> bool:
    if path.name.lower() == "skill.md":
        return True
    try:
        head = path.read_text(encoding="utf-8", errors="ignore").splitlines()[:40]
    except Exception:
        return False
    for line in head:
        text = line.strip().lower()
        if text.startswith("---"):
            return True
        if re.match(r"^(name|description|command|trigger|triggers)\s*:", text):
            return True
    return False


def _split_frontmatter(content: str) -> tuple[Optional[str], str]:
    text = content.lstrip()
    if not text.startswith("---"):
        return None, content
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, content
    frontmatter = parts[1].strip()
    body = parts[2].lstrip("\n")
    return frontmatter, body


def _spec_from_frontmatter(frontmatter: str, body: str) -> Optional[SkillSpec]:
    try:
        import yaml
        data = yaml.safe_load(frontmatter) or {}
    except Exception:
        data = {}

    if not isinstance(data, dict):
        return None

    name = str(data.get("name") or data.get("title") or "").strip()
    description = str(data.get("description") or "").strip() or f"Skill: {name}" if name else "Skill"
    triggers = data.get("triggers") or data.get("trigger") or []
    if isinstance(triggers, str):
        triggers = [t.strip() for t in triggers.split(",") if t.strip()]
    if not isinstance(triggers, list):
        triggers = []
    command = str(data.get("command") or data.get("run") or "").strip()
    kind = str(data.get("type") or data.get("kind") or "shell").lower()
    args = data.get("args") or []
    if isinstance(args, str):
        args = [a.strip() for a in args.split(",") if a.strip()]
    requires_env = data.get("requires-env") or data.get("requires_env") or []
    if isinstance(requires_env, str):
        requires_env = [a.strip() for a in requires_env.split(",") if a.strip()]
    requires_bin = data.get("requires-bin") or data.get("requires_bin") or []
    if isinstance(requires_bin, str):
        requires_bin = [a.strip() for a in requires_bin.split(",") if a.strip()]
    test_command = data.get("test") or data.get("test-command") or data.get("tests")
    metadata = data.get("metadata") or {}
    # Extended metadata (optional requires bins/env)
    if isinstance(metadata, dict):
        compat_requires = metadata.get("compat", {}).get("requires", {}) if isinstance(metadata.get("compat", {}), dict) else {}
        compat_bins = compat_requires.get("bins") or []
        compat_env = compat_requires.get("env") or []
        if isinstance(compat_bins, list):
            requires_bin = list(set(list(requires_bin) + [str(b) for b in compat_bins]))
        if isinstance(compat_env, list):
            requires_env = list(set(list(requires_env) + [str(e) for e in compat_env]))

    instruction = None
    if not command:
        kind = "instruction"
        instruction = body.strip()

    if not name:
        # Fallback to heading in body if missing
        for line in body.splitlines():
            if line.strip().startswith("#"):
                name = line.strip().lstrip("#").strip()
                break
        name = name or "skill"

    return SkillSpec(
        name=slugify(name),
        description=description,
        triggers=triggers or [name.lower()],
        command=command,
        args=list(args) if isinstance(args, list) else [],
        kind=kind,
        requires_env=list(requires_env) if isinstance(requires_env, list) else [],
        requires_bin=list(requires_bin) if isinstance(requires_bin, list) else [],
        test_command=test_command,
        instruction=instruction,
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def _is_skill_available(spec: SkillSpec) -> bool:
    # Enforce policy + safety checks at load time.
    try:
        from chintu_backend.automation.skills.skill_tester import validate_skill_spec
        issues = validate_skill_spec(spec)
        if not issues:
            return True
        # Registration should be allowed even if shell execution is disabled;
        # runtime checks will still block execution.
        soft_issues = {"Shell skills are disabled by policy."}
        if all(issue in soft_issues for issue in issues):
            return True
        return False
    except Exception:
        # Fallback to binary-only gate.
        for bin_name in spec.requires_bin:
            if shutil.which(bin_name) is None:
                return False
        return True


def _is_safe_local_python_skill(spec: SkillSpec) -> bool:
    """Allow tightly-scoped local python script skills when shell is disabled.

    This keeps low-risk project skills usable without globally enabling arbitrary shell.
    """
    if not spec or spec.kind != "shell":
        return False
    command = str(spec.command or "").strip()
    if not command:
        return False
    # Reject shell composition operators.
    if any(token in command for token in ("&&", "||", "|", ";", ">", "<", "`")):
        return False
    normalized = command.replace("\\", "/")
    if "{SKILL_DIR}" not in normalized:
        return False
    if not re.match(r"^\s*(python|python3|py)(?:\.exe)?\s+", normalized, flags=re.IGNORECASE):
        return False
    # First arg must be a python file under the skill directory template.
    if not re.search(r"\{SKILL_DIR\}/[^\s\"']+\.py(?:\s|$)", normalized, flags=re.IGNORECASE):
        return False
    return True


def _format_instruction_skill(spec: SkillSpec) -> str:
    lines = [
        f"Skill: {spec.name}",
        f"Description: {spec.description}",
    ]
    if spec.metadata:
        lines.append(f"Metadata: {spec.metadata}")
    if spec.instruction:
        lines.append("Instructions:")
        lines.append(spec.instruction.strip())
    return "\n".join(lines)


def _snapshot_skills(sources: List[tuple[Path, str]]) -> Dict[str, float]:
    snapshot: Dict[str, float] = {}
    for skills_dir, _label in sources:
        if not skills_dir or not skills_dir.exists():
            continue
        for path in skills_dir.rglob("*.md"):
            if not _looks_like_skill_file(path):
                continue
            try:
                snapshot[str(path)] = path.stat().st_mtime
            except Exception:
                continue
    return snapshot
