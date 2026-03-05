"""Skill proposal storage + approval workflow."""

from __future__ import annotations

import json
import time
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from chintu_backend.core.config import get_config
from chintu_backend.automation.skills.skill_registry import parse_skills_from_markdown, slugify
from chintu_backend.automation.skills.skill_tester import validate_skill_spec
from chintu_backend.automation.skills.supply_chain import evaluate_skill_supply_chain
from chintu_backend.automation.skills.skill_generalization import (
    autogeneralize_skill_markdown,
    load_existing_skill_specs,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class SkillProposal:
    id: str
    names: List[str]
    status: str
    created_at: str
    source: str
    reason: str
    md_path: str
    meta_path: str
    issues: List[str]
    tests: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "names": self.names,
            "status": self.status,
            "created_at": self.created_at,
            "source": self.source,
            "reason": self.reason,
            "md_path": self.md_path,
            "meta_path": self.meta_path,
            "issues": list(self.issues or []),
            "tests": self.tests or {},
        }


def _proposal_paths(proposal_id: str, base_dir: Path) -> tuple[Path, Path]:
    md_path = base_dir / f"{proposal_id}.md"
    meta_path = base_dir / f"{proposal_id}.json"
    return md_path, meta_path


def _history_dir(skills_dir: Path) -> Path:
    hist = skills_dir / ".history"
    hist.mkdir(parents=True, exist_ok=True)
    return hist


def create_proposal(content: str, source: str, reason: str = "") -> SkillProposal:
    config = get_config()
    base_dir = config.skills_proposals_dir
    if not base_dir:
        raise RuntimeError("skills_proposals_dir not configured")

    generalization_notes: List[str] = []
    if bool(getattr(config, "skills_autogeneralize_enabled", True)):
        try:
            content, generalization_notes = autogeneralize_skill_markdown(content)
        except Exception as exc:
            logger.debug("Skill auto-generalization skipped: %s", exc)

    specs = parse_skills_from_markdown(content)
    if not specs:
        raise ValueError("No valid SKILL.md blocks found.")

    names = [slugify(s.name) for s in specs if s.name]
    first = names[0] if names else "skill"
    proposal_id = f"proposal_{first}_{int(time.time())}"
    md_path, meta_path = _proposal_paths(proposal_id, base_dir)
    md_path.write_text(content, encoding="utf-8")

    issues: List[str] = []
    existing_specs = load_existing_skill_specs(config) if bool(getattr(config, "skills_generalization_enforced", True)) else None
    for spec in specs:
        issues.extend(
            validate_skill_spec(
                spec,
                config,
                proposal_mode=True,
                existing_specs=existing_specs,
            )
        )
        try:
            decision = evaluate_skill_supply_chain(
                spec=spec,
                skill_path=md_path,
                source_label="learned",
                config=config,
            )
            for item in decision.issues:
                issues.append(f"Supply-chain: {item}")
        except Exception:
            pass
    for note in generalization_notes:
        issues.append(f"Generalization: {note}")

    proposal = SkillProposal(
        id=proposal_id,
        names=names or ["unknown"],
        status="pending",
        created_at=_utc_now(),
        source=source or "unknown",
        reason=reason or "",
        md_path=str(md_path),
        meta_path=str(meta_path),
        issues=issues,
    )

    meta_path.write_text(json.dumps(proposal.to_dict(), indent=2), encoding="utf-8")
    return proposal


def list_proposals(status: Optional[str] = None) -> List[SkillProposal]:
    config = get_config()
    base_dir = config.skills_proposals_dir
    if not base_dir or not base_dir.exists():
        return []
    proposals: List[SkillProposal] = []
    for meta_path in sorted(base_dir.glob("*.json")):
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            if status and data.get("status") != status:
                continue
            proposals.append(
                SkillProposal(
                    id=data["id"],
                    names=data.get("names", []),
                    status=data.get("status", "pending"),
                    created_at=data.get("created_at", ""),
                    source=data.get("source", ""),
                    reason=data.get("reason", ""),
                    md_path=data.get("md_path", ""),
                    meta_path=str(meta_path),
                    issues=data.get("issues", []),
                    tests=data.get("tests", {}),
                )
            )
        except Exception:
            continue
    return proposals


def approve_proposal(proposal_id: str, approver: str = "user") -> SkillProposal:
    config = get_config()
    base_dir = config.skills_proposals_dir
    if not base_dir:
        raise RuntimeError("skills_proposals_dir not configured")
    md_path, meta_path = _proposal_paths(proposal_id, base_dir)
    if not meta_path.exists():
        raise FileNotFoundError(f"Proposal not found: {proposal_id}")

    data = json.loads(meta_path.read_text(encoding="utf-8"))
    content = md_path.read_text(encoding="utf-8")

    specs = parse_skills_from_markdown(content)
    if not specs:
        raise ValueError("Proposal contains no valid SKILL.md blocks.")

    # Re-validate against current policy before approving.
    issues: List[str] = []
    supply_chain_records: List[Dict[str, Any]] = []
    existing_specs = load_existing_skill_specs(config) if bool(getattr(config, "skills_generalization_enforced", True)) else None
    for spec in specs:
        issues.extend(
            validate_skill_spec(
                spec,
                config,
                proposal_mode=True,
                existing_specs=existing_specs,
            )
        )
        try:
            decision = evaluate_skill_supply_chain(
                spec=spec,
                skill_path=md_path,
                source_label="learned",
                config=config,
            )
            supply_chain_records.append(decision.to_metadata())
            for item in decision.issues:
                issues.append(f"Supply-chain: {item}")
        except Exception:
            pass
    if supply_chain_records:
        data["supply_chain"] = supply_chain_records
    if issues:
        data["issues"] = issues
        data["status"] = "blocked"
        data["approved_by"] = approver
        meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return SkillProposal(
            id=data["id"],
            names=data.get("names", []),
            status=data.get("status", "blocked"),
            created_at=data.get("created_at", ""),
            source=data.get("source", ""),
            reason=data.get("reason", ""),
            md_path=str(md_path),
            meta_path=str(meta_path),
            issues=data.get("issues", []),
            tests=data.get("tests", {}),
        )

    # Run regression tests if provided
    from chintu_backend.automation.skills.skill_tester import run_skill_tests
    test_report = run_skill_tests(specs, config)

    data["tests"] = test_report
    data["tested_at"] = _utc_now()

    if not test_report.get("passed", True):
        data["status"] = "failed"
        data["approved_by"] = approver
        meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return SkillProposal(
            id=data["id"],
            names=data.get("names", []),
            status=data.get("status", "failed"),
            created_at=data.get("created_at", ""),
            source=data.get("source", ""),
            reason=data.get("reason", ""),
            md_path=str(md_path),
            meta_path=str(meta_path),
            issues=data.get("issues", []),
            tests=data.get("tests", {}),
        )

    # Save to learned skills directory
    skills_dir = config.skills_learned_dir
    if not skills_dir:
        raise RuntimeError("skills_learned_dir not configured")

    history_dir = _history_dir(skills_dir)
    handlers_dir = skills_dir / "handlers"
    handlers_dir.mkdir(exist_ok=True)

    logger.debug("Extracting associated handler files from %s", md_path)
    # Extract associated files
    import re
    # Pattern: <!-- ASSOCIATED_FILE: filename.py --> \n ```python \n code \n ```
    file_matches = re.findall(r"<!-- ASSOCIATED_FILE: ([\w\.-]+) -->\s*```python\s*\n(.*?)\n```", content, re.DOTALL)
    logger.debug("Associated handler file blocks found: %d", len(file_matches))
    for filename, code in file_matches:
        handler_path = handlers_dir / filename
        logger.debug("Writing associated handler to %s", handler_path)
        handler_path.write_text(code.strip(), encoding="utf-8")
        logger.info("Deployed associated handler: %s", filename)

    for spec in specs:
        target_name = f"{slugify(spec.name)}.md"
        target_path = skills_dir / target_name
        if target_path.exists():
            backup = history_dir / f"{slugify(spec.name)}_{int(time.time())}.md"
            backup.write_text(target_path.read_text(encoding="utf-8"), encoding="utf-8")
        target_path.write_text(content, encoding="utf-8")

    data["status"] = "approved"
    data["approved_at"] = _utc_now()
    data["approved_by"] = approver
    meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return SkillProposal(
        id=data["id"],
        names=data.get("names", []),
        status=data.get("status", "approved"),
        created_at=data.get("created_at", ""),
        source=data.get("source", ""),
        reason=data.get("reason", ""),
        md_path=str(md_path),
        meta_path=str(meta_path),
        issues=data.get("issues", []),
        tests=data.get("tests", {}),
    )


def reject_proposal(proposal_id: str, reason: str = "") -> SkillProposal:
    config = get_config()
    base_dir = config.skills_proposals_dir
    if not base_dir:
        raise RuntimeError("skills_proposals_dir not configured")
    md_path, meta_path = _proposal_paths(proposal_id, base_dir)
    if not meta_path.exists():
        raise FileNotFoundError(f"Proposal not found: {proposal_id}")
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["status"] = "rejected"
    data["rejected_at"] = _utc_now()
    data["rejection_reason"] = reason
    meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return SkillProposal(
        id=data["id"],
        names=data.get("names", []),
        status=data.get("status", "rejected"),
        created_at=data.get("created_at", ""),
        source=data.get("source", ""),
        reason=data.get("reason", ""),
        md_path=str(md_path),
        meta_path=str(meta_path),
        issues=data.get("issues", []),
        tests=data.get("tests", {}),
    )


def rollback_skill(name: str) -> Optional[Path]:
    config = get_config()
    skills_dir = config.skills_learned_dir
    if not skills_dir:
        return None
    history_dir = _history_dir(skills_dir)
    slug = slugify(name)
    backups = sorted(history_dir.glob(f"{slug}_*.md"), reverse=True)
    if not backups:
        return None
    latest = backups[0]
    target_path = skills_dir / f"{slug}.md"
    target_path.write_text(latest.read_text(encoding="utf-8"), encoding="utf-8")
    return target_path
