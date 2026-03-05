"""Audit approved skill proposals for narrow-duplicate regressions (Phase 3 gate)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.automation.skills.skill_generalization import load_existing_skill_specs
from chintu_backend.automation.skills.skill_registry import parse_skills_from_markdown
from chintu_backend.automation.skills.skill_tester import validate_skill_spec
from chintu_backend.core.config import get_config


_NARROW_PATTERNS = (
    "likely duplicate",
    "too specific",
    "all triggers are entity-specific",
    "extend the existing skill family",
    "existing '",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_stamp() -> str:
    return _utc_now().strftime("%Y%m%d_%H%M%S")


def _parse_iso(ts: str) -> datetime | None:
    raw = str(ts or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass
class ProposalAuditRow:
    proposal_id: str
    approved_at: str
    names: List[str]
    narrow_issues: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "approved_at": self.approved_at,
            "names": list(self.names),
            "narrow_issues": list(self.narrow_issues),
        }


def run_audit(days: int = 14) -> Dict[str, Any]:
    cfg = get_config()
    base = Path(cfg.skills_proposals_dir)
    cutoff = _utc_now() - timedelta(days=max(1, int(days)))

    existing_specs = load_existing_skill_specs(cfg)
    rows: List[ProposalAuditRow] = []
    scanned = 0

    if base.exists():
        for meta_path in sorted(base.glob("*.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(meta.get("status", "")).lower() != "approved":
                continue
            approved_at_raw = str(meta.get("approved_at") or meta.get("created_at") or "")
            approved_at = _parse_iso(approved_at_raw)
            if approved_at is None or approved_at < cutoff:
                continue

            md_path = Path(str(meta.get("md_path") or ""))
            if not md_path.exists():
                continue
            scanned += 1
            try:
                content = md_path.read_text(encoding="utf-8")
                specs = parse_skills_from_markdown(content)
            except Exception:
                specs = []
            narrow_issues: List[str] = []
            for spec in specs:
                issues = validate_skill_spec(
                    spec,
                    cfg,
                    proposal_mode=True,
                    existing_specs=existing_specs,
                )
                for issue in issues:
                    low = str(issue or "").lower()
                    if any(pattern in low for pattern in _NARROW_PATTERNS):
                        narrow_issues.append(str(issue))

            rows.append(
                ProposalAuditRow(
                    proposal_id=str(meta.get("id") or meta_path.stem),
                    approved_at=approved_at_raw,
                    names=list(meta.get("names") or []),
                    narrow_issues=narrow_issues,
                )
            )

    violations = [row for row in rows if row.narrow_issues]
    return {
        "timestamp_utc": _utc_now().isoformat().replace("+00:00", "Z"),
        "window_days": int(days),
        "scanned_approved_proposals": scanned,
        "violations": [row.to_dict() for row in violations],
        "summary": {
            "total_checked": len(rows),
            "narrow_clone_violations": len(violations),
            "pass": len(violations) == 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit approved skill proposals for Phase 3 generalization policy.")
    parser.add_argument("--days", type=int, default=14, help="Lookback window for approved proposals.")
    parser.add_argument("--out-dir", default="generated_reports")
    args = parser.parse_args()

    report = run_audit(days=args.days)
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"phase3_skill_generalization_audit_{_utc_stamp()}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Wrote: {out_path}")
    print(json.dumps(report["summary"], indent=2, ensure_ascii=True))
    return 0 if bool(report["summary"]["pass"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

