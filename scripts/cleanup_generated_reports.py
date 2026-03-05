from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple


@dataclass
class CleanupResult:
    removed: List[str]
    kept: List[str]
    report_path: Path


def _latest_by_name(paths: Iterable[Path]) -> Path | None:
    items = sorted(paths, key=lambda p: p.name)
    return items[-1] if items else None


def cleanup_generated_reports(root: Path, dry_run: bool = False) -> CleanupResult:
    removed: List[str] = []
    kept: List[str] = []

    if not root.exists():
        raise FileNotFoundError(f"Reports directory not found: {root}")

    always_keep: Set[str] = {
        "REFERENCE_COMPARISON.md",
        "sample_portfolio.csv",
        "targeted_fix_validation_20260221_225228.md",
        "phase13_dashboards.json",
        "phase135_knowledge_refresh.json",
        "phase3_skill_generalization_audit_20260219_030022.json",
        "phase4_dependency_replay_20260219_033250.json",
        "phase45_project_builder_replay_20260219_033604.json",
        "phase5_memory_replay_20260219_035752.json",
        "phase6_voice_qa_replay_20260219_040857.json",
        "phase7_self_healing_replay_20260219_042923.json",
        "phase8_security_doctor_20260219_050052.json",
        "phase85_social_replay_20260219_050137.json",
        "phase9_governance_gate_20260219_162038.json",
        "routing_ab_eval_20260219_025700.json",
        "chintu_9_task_validation_20260219_025853.json",
        "codebase_audit_20260210_204207.md",
    }

    prefix_groups: Tuple[str, ...] = (
        "chintu_50_realistic_",
        "chintu_50_reasonableness_review_",
        "chintu_manual_review_",
        "parity_benchmark_",
    )

    drop_prefixes: Tuple[str, ...] = (
        "browser_automation_parity_",
        "night_runner_parity_",
        "head_to_head_",
        "exec_sandbox_",
        "generated_reports_cleanup_",
        "tests_cleanup_",
    )

    drop_exact: Set[str] = {
        "orchestrator_bench_20260210_211503.db",
    }

    files = [p for p in root.iterdir() if p.is_file()]
    latest_by_group_ext: Dict[Tuple[str, str], str] = {}
    for prefix in prefix_groups:
        candidates = [p for p in files if p.name.startswith(prefix)]
        if not candidates:
            continue
        ext_map: Dict[str, List[Path]] = {}
        for p in candidates:
            ext_map.setdefault(p.suffix.lower(), []).append(p)
        for ext, items in ext_map.items():
            latest = _latest_by_name(items)
            if latest:
                latest_by_group_ext[(prefix, ext)] = latest.name

    parity_dirs = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("parity_benchmark_")]
    latest_parity_dir = _latest_by_name(parity_dirs)

    phase45_root = root / "phase45_projects"
    latest_phase45_subdir = None
    if phase45_root.exists():
        latest_phase45_subdir = _latest_by_name([p for p in phase45_root.iterdir() if p.is_dir()])

    receipts_root = root / "phase4_dependency_receipts"
    latest_receipt = None
    if receipts_root.exists():
        latest_receipt = _latest_by_name([p for p in receipts_root.iterdir() if p.is_file()])

    def keep(path: Path) -> None:
        kept.append(str(path).replace("\\", "/"))

    def remove(path: Path) -> None:
        removed.append(str(path).replace("\\", "/"))
        if dry_run:
            return
        if path.is_dir():
            for sub in sorted(path.rglob("*"), reverse=True):
                if sub.is_file() or sub.is_symlink():
                    sub.unlink(missing_ok=True)
                elif sub.is_dir():
                    try:
                        sub.rmdir()
                    except OSError:
                        pass
            try:
                path.rmdir()
            except OSError:
                pass
        else:
            path.unlink(missing_ok=True)

    for item in sorted(root.iterdir(), key=lambda p: p.name):
        name = item.name
        if item.is_file():
            if name in always_keep:
                keep(item)
                continue

            if name in drop_exact or any(name.startswith(prefix) for prefix in drop_prefixes):
                remove(item)
                continue

            handled_group = False
            for prefix in prefix_groups:
                if not name.startswith(prefix):
                    continue
                handled_group = True
                ext = item.suffix.lower()
                if latest_by_group_ext.get((prefix, ext)) == name:
                    keep(item)
                else:
                    remove(item)
                break
            if handled_group:
                continue

            keep(item)
            continue

        # Directories
        if name == "validation_inputs":
            keep(item)
            continue

        if name == "phase45_projects":
            keep(item)
            for sub in sorted(item.iterdir(), key=lambda p: p.name):
                if latest_phase45_subdir and sub.name != latest_phase45_subdir.name:
                    remove(sub)
                else:
                    keep(sub)
            continue

        if name == "phase4_dependency_receipts":
            keep(item)
            for sub in sorted(item.iterdir(), key=lambda p: p.name):
                if latest_receipt and sub.name != latest_receipt.name:
                    remove(sub)
                else:
                    keep(sub)
            continue

        if name.startswith("parity_benchmark_"):
            if latest_parity_dir and name == latest_parity_dir.name:
                keep(item)
            else:
                remove(item)
            continue

        if any(name.startswith(prefix) for prefix in drop_prefixes):
            remove(item)
            continue

        keep(item)

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    report_path = root / f"generated_reports_cleanup_{stamp}.md"
    report_lines = [
        "# Generated Reports Cleanup",
        "",
        f"- Timestamp (UTC): {datetime.utcnow().isoformat()}Z",
        f"- Mode: {'dry-run' if dry_run else 'apply'}",
        f"- Removed items: {len(removed)}",
        f"- Kept markers: {len(kept)}",
        "",
        "## Retention policy",
        "- Keep latest run in benchmark/review families.",
        "- Keep lock and phase replay artifacts.",
        "- Keep newest dependency receipt and newest phase45 project artifact dir.",
        "- Remove stale temp/sandbox/parity artifacts and older duplicates.",
        "",
        "## Removed",
    ]
    report_lines.extend(f"- `{path}`" for path in removed)
    report_lines.append("")
    report_lines.append("## Kept markers")
    report_lines.extend(f"- `{path}`" for path in sorted(set(kept)))

    if not dry_run:
        report_path.write_text("\n".join(report_lines), encoding="utf-8")

    return CleanupResult(removed=removed, kept=kept, report_path=report_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean duplicate/stale artifacts from generated_reports.")
    parser.add_argument("--dir", default="generated_reports", help="Reports directory")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be removed")
    args = parser.parse_args()

    root = Path(args.dir)
    result = cleanup_generated_reports(root, dry_run=args.dry_run)
    print(f"removed={len(result.removed)} kept={len(result.kept)}")
    if args.dry_run:
        print("dry-run mode; no files were deleted.")
    else:
        print(result.report_path)


if __name__ == "__main__":
    main()
