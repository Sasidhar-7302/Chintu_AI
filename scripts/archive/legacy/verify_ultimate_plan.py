"""Verify the ultimate plan references real, present artifacts.

This is a lightweight structural check:
- Ensures lock reports referenced in the plan exist.
- Ensures files referenced in "Current progress (Locked)" sections exist.

It does NOT execute benchmarks; use Phase 9 governance gate for runtime checks.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = REPO_ROOT / "docs" / "PLANS" / "chintu_ultimate_plan.md"


def _extract_backticked_paths(text: str) -> List[str]:
    # Backticks are used consistently for file paths in the plan.
    return re.findall(r"`([^`]+)`", text)


def _is_repo_relative_path(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    if ":\\" in raw or raw.startswith("\\\\"):
        return False  # absolute Windows path or UNC
    if raw.startswith("http://") or raw.startswith("https://"):
        return False
    if raw.startswith("~"):
        return False
    if raw.startswith("/"):
        return False
    return True


def _candidate_file_path(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw or " " in raw:
        return False
    # Allow common file extensions + a few directories we expect.
    return bool(
        re.search(r"\.(py|md|json|jsonl|ps1|bat|txt)$", raw, flags=re.IGNORECASE)
        or raw.endswith("/")
    )


def _scan_locked_sections(plan_text: str) -> List[str]:
    """Extract paths only from 'Current progress (Locked)' sections for signal fidelity."""
    paths: List[str] = []
    lines = plan_text.splitlines()
    in_locked = False
    for ln in lines:
        if ln.strip().startswith("Current progress (Locked):"):
            in_locked = True
            continue
        if in_locked and ln.strip().startswith("Deliverables:"):
            in_locked = False
            continue
        if not in_locked:
            continue
        paths.extend(_extract_backticked_paths(ln))
    return paths


def _unique_existing_and_missing(paths: List[str]) -> Tuple[List[str], List[str]]:
    existing: List[str] = []
    missing: List[str] = []
    seen: Set[str] = set()
    for p in paths:
        if not _is_repo_relative_path(p):
            continue
        if not _candidate_file_path(p):
            continue
        if p in seen:
            continue
        seen.add(p)
        resolved = (REPO_ROOT / p).resolve()
        if resolved.exists():
            existing.append(p)
        else:
            missing.append(p)
    return sorted(existing), sorted(missing)


def main() -> int:
    if not PLAN_PATH.exists():
        print(json.dumps({"ok": False, "error": f"missing plan: {PLAN_PATH}"}, indent=2))
        return 2

    plan_text = PLAN_PATH.read_text(encoding="utf-8", errors="ignore")
    locked_paths = _scan_locked_sections(plan_text)
    lock_reports = re.findall(r"`(docs/PLANS/phase[^`]+_lock_report\.md)`", plan_text)

    existing_locked, missing_locked = _unique_existing_and_missing(locked_paths)
    existing_reports, missing_reports = _unique_existing_and_missing(lock_reports)

    summary: Dict[str, object] = {
        "ok": (len(missing_locked) == 0 and len(missing_reports) == 0),
        "plan_path": str(PLAN_PATH),
        "locked_refs": {
            "count": len(existing_locked) + len(missing_locked),
            "existing": len(existing_locked),
            "missing": len(missing_locked),
        },
        "lock_reports": {
            "count": len(existing_reports) + len(missing_reports),
            "existing": len(existing_reports),
            "missing": len(missing_reports),
        },
        "missing_paths": {
            "locked_section": missing_locked,
            "lock_reports": missing_reports,
        },
    }
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0 if bool(summary["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
