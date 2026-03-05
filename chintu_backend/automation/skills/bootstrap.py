"""Skill bootstrap planner and installer."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from chintu_backend.automation.skills.catalog import SkillCatalogEntry, list_catalog_entries
from chintu_backend.automation.skills.skill_registry import SkillRegistry, parse_skills_from_markdown


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class BootstrapAction:
    skill_id: str
    name: str
    stage: str
    install_strategy: str
    source_label: str
    target_path: str
    action: str  # install | already_installed | manual_review | blocked
    reason: str
    risk: str
    tags: List[str] = field(default_factory=list)
    source_path: str = ""
    reference_url: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class BootstrapReport:
    planned_at_utc: str
    stage: str
    workspace_dir: str
    apply: bool
    actions: List[BootstrapAction] = field(default_factory=list)
    installed_paths: List[str] = field(default_factory=list)
    validation: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "planned_at_utc": self.planned_at_utc,
            "stage": self.stage,
            "workspace_dir": self.workspace_dir,
            "apply": self.apply,
            "actions": [row.to_dict() for row in self.actions],
            "installed_paths": list(self.installed_paths),
            "validation": dict(self.validation),
        }


def _target_skill_file(workspace_dir: Path, entry: SkillCatalogEntry) -> Path:
    return workspace_dir / "bootstrap" / entry.effective_target_dir_name() / "skill.md"


def build_skill_bootstrap_plan(
    *,
    workspace_dir: Path,
    stage: str = "initial",
    selected_ids: Optional[Iterable[str]] = None,
    existing_skill_names: Optional[Iterable[str]] = None,
) -> BootstrapReport:
    existing = {str(x).strip().lower() for x in (existing_skill_names or []) if str(x).strip()}
    report = BootstrapReport(
        planned_at_utc=_now_iso(),
        stage=str(stage or "initial"),
        workspace_dir=str(workspace_dir),
        apply=False,
    )
    entries = list_catalog_entries(stage=stage, selected_ids=selected_ids)
    for entry in entries:
        target_file = _target_skill_file(workspace_dir, entry)
        if entry.install_strategy == "reference_only":
            report.actions.append(
                BootstrapAction(
                    skill_id=entry.skill_id,
                    name=entry.name,
                    stage=entry.stage,
                    install_strategy=entry.install_strategy,
                    source_label=entry.source_label,
                    target_path=str(target_file),
                    action="manual_review",
                    reason="Reference-only entry. Import after manual review and provenance checks.",
                    risk=entry.risk,
                    tags=list(entry.tags),
                    source_path=entry.source_path,
                    reference_url=entry.reference_url,
                )
            )
            continue
        source_file = entry.bundled_file()
        if source_file is None:
            report.actions.append(
                BootstrapAction(
                    skill_id=entry.skill_id,
                    name=entry.name,
                    stage=entry.stage,
                    install_strategy=entry.install_strategy,
                    source_label=entry.source_label,
                    target_path=str(target_file),
                    action="blocked",
                    reason="No source file configured for install strategy.",
                    risk=entry.risk,
                    tags=list(entry.tags),
                    source_path=entry.source_path,
                    reference_url=entry.reference_url,
                )
            )
            continue
        if not source_file.exists():
            report.actions.append(
                BootstrapAction(
                    skill_id=entry.skill_id,
                    name=entry.name,
                    stage=entry.stage,
                    install_strategy=entry.install_strategy,
                    source_label=entry.source_label,
                    target_path=str(target_file),
                    action="blocked",
                    reason=f"Source file missing: {source_file}",
                    risk=entry.risk,
                    tags=list(entry.tags),
                    source_path=str(source_file),
                    reference_url=entry.reference_url,
                )
            )
            continue
        source_names: List[str] = []
        try:
            content = source_file.read_text(encoding="utf-8")
            source_names = [spec.name.lower() for spec in parse_skills_from_markdown(content)]
        except Exception:
            source_names = []
        if source_names and any(name in existing for name in source_names):
            report.actions.append(
                BootstrapAction(
                    skill_id=entry.skill_id,
                    name=entry.name,
                    stage=entry.stage,
                    install_strategy=entry.install_strategy,
                    source_label=entry.source_label,
                    target_path=str(target_file),
                    action="already_installed",
                    reason=f"Skill already available in registry ({', '.join(source_names)}).",
                    risk=entry.risk,
                    tags=list(entry.tags),
                    source_path=str(source_file),
                    reference_url=entry.reference_url,
                )
            )
            continue
        if target_file.exists():
            report.actions.append(
                BootstrapAction(
                    skill_id=entry.skill_id,
                    name=entry.name,
                    stage=entry.stage,
                    install_strategy=entry.install_strategy,
                    source_label=entry.source_label,
                    target_path=str(target_file),
                    action="already_installed",
                    reason="Target skill already exists.",
                    risk=entry.risk,
                    tags=list(entry.tags),
                    source_path=str(source_file),
                    reference_url=entry.reference_url,
                )
            )
            continue
        report.actions.append(
            BootstrapAction(
                skill_id=entry.skill_id,
                name=entry.name,
                stage=entry.stage,
                install_strategy=entry.install_strategy,
                source_label=entry.source_label,
                target_path=str(target_file),
                action="install",
                reason="Installable bundled entry.",
                risk=entry.risk,
                tags=list(entry.tags),
                source_path=str(source_file),
                reference_url=entry.reference_url,
            )
        )
    return report


def apply_skill_bootstrap_plan(
    *,
    workspace_dir: Path,
    stage: str = "initial",
    selected_ids: Optional[Iterable[str]] = None,
    existing_skill_names: Optional[Iterable[str]] = None,
    overwrite: bool = False,
    receipt_path: Optional[Path] = None,
) -> BootstrapReport:
    report = build_skill_bootstrap_plan(
        workspace_dir=workspace_dir,
        stage=stage,
        selected_ids=selected_ids,
        existing_skill_names=existing_skill_names,
    )
    report.apply = True
    installed: List[str] = []
    for action in report.actions:
        if action.action not in {"install", "already_installed"}:
            continue
        target_file = Path(action.target_path)
        source_file = Path(action.source_path)
        if action.action == "already_installed" and not overwrite:
            continue
        if not source_file.exists():
            continue
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target_file)
        installed.append(str(target_file))
    report.installed_paths = installed
    report.validation = validate_bootstrap_install(workspace_dir=workspace_dir)

    out_path = receipt_path
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8")

    return report


def validate_bootstrap_install(*, workspace_dir: Path) -> Dict[str, object]:
    registry = SkillRegistry()
    loaded = registry.load_dir(workspace_dir, source_label="workspace")
    blocked = registry.get_blocked_supply_chain()
    return {
        "loaded_count": int(loaded),
        "registered_count": int(len(registry._skills)),
        "blocked_count": int(len(blocked)),
        "blocked_skills": sorted(blocked.keys()),
    }
