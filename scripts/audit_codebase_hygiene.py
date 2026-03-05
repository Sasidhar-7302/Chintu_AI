"""
Repository hygiene audit for Chintu AI.

Generates:
- generated_reports/codebase_hygiene_audit_YYYYMMDD_HHMMSS.json
- generated_reports/codebase_hygiene_audit_YYYYMMDD_HHMMSS.md
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "generated_reports"

EXCLUDED_DIRS = {
    ".git",
    "venv",
    ".pytest_cache",
    "__pycache__",
    ".tmp",
    ".chintu",
    "generated_reports",
}

TEXT_EXTENSIONS = {
    ".py",
    ".md",
    ".json",
    ".txt",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".ps1",
    ".bat",
    ".dart",
    ".sh",
}

ARTIFACT_DIR_CANDIDATES = [
    "chintu_ui/build",
    "chintu_ui/.dart_tool",
    ".tmp",
    "logs",
]

SCRIPT_ARCHIVE_HINT_PREFIXES = (
    "verify_",
    "quick_",
    "fix_",
    "apply_",
    "ultimate_",
    "extensive_test",
    "comprehensive_",
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_excluded(path: Path) -> bool:
    return bool(set(path.parts) & EXCLUDED_DIRS)


def _iter_repo_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if _is_excluded(p.relative_to(root)):
            continue
        yield p


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return sum(1 for _ in handle)


def _dir_stats(path: Path) -> Dict[str, float]:
    files = 0
    size = 0
    for p in path.rglob("*"):
        if not p.is_file():
            continue
        files += 1
        try:
            size += p.stat().st_size
        except OSError:
            pass
    return {"files": files, "size_mb": round(size / 1_048_576, 2)}


@dataclass
class AuditResult:
    timestamp_utc: str
    total_files_scanned: int
    large_files: List[Dict[str, int]]
    empty_directories: List[str]
    artifact_directories: List[Dict[str, float]]
    candidate_archive_scripts: List[str]
    duplicate_doc_names: Dict[str, int]

    def to_dict(self) -> Dict[str, object]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "total_files_scanned": self.total_files_scanned,
            "large_files": self.large_files,
            "empty_directories": self.empty_directories,
            "artifact_directories": self.artifact_directories,
            "candidate_archive_scripts": self.candidate_archive_scripts,
            "duplicate_doc_names": self.duplicate_doc_names,
        }


def run_audit(
    *,
    root: Path,
    large_file_threshold: int,
    top_n: int,
) -> AuditResult:
    files = list(_iter_repo_files(root))

    large_files: List[Dict[str, int]] = []
    for path in files:
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        try:
            lines = _count_lines(path)
        except OSError:
            continue
        if lines >= large_file_threshold:
            large_files.append(
                {
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "lines": lines,
                }
            )
    large_files.sort(key=lambda item: item["lines"], reverse=True)
    large_files = large_files[: max(1, top_n)]

    empty_dirs: List[str] = []
    for d in root.rglob("*"):
        if not d.is_dir():
            continue
        rel = d.relative_to(root)
        if _is_excluded(rel):
            continue
        try:
            if not any(d.iterdir()):
                empty_dirs.append(str(rel).replace("\\", "/"))
        except OSError:
            continue
    empty_dirs.sort()

    artifact_dirs: List[Dict[str, float]] = []
    for candidate in ARTIFACT_DIR_CANDIDATES:
        p = root / candidate
        if not p.exists():
            continue
        stats = _dir_stats(p)
        artifact_dirs.append(
            {
                "path": candidate,
                "files": int(stats["files"]),
                "size_mb": float(stats["size_mb"]),
            }
        )

    archive_candidates: List[str] = []
    scripts_dir = root / "scripts"
    if scripts_dir.exists():
        for p in scripts_dir.glob("*.py"):
            name = p.name.lower()
            if name.startswith(SCRIPT_ARCHIVE_HINT_PREFIXES):
                archive_candidates.append(str(p.relative_to(root)).replace("\\", "/"))
    archive_candidates.sort()

    doc_name_counts: Counter[str] = Counter()
    docs_dir = root / "docs"
    if docs_dir.exists():
        for p in docs_dir.rglob("*.md"):
            doc_name_counts[p.name.lower()] += 1
    duplicate_doc_names = {
        name: count for name, count in sorted(doc_name_counts.items()) if count > 1
    }

    return AuditResult(
        timestamp_utc=_utc_iso(),
        total_files_scanned=len(files),
        large_files=large_files,
        empty_directories=empty_dirs,
        artifact_directories=artifact_dirs,
        candidate_archive_scripts=archive_candidates,
        duplicate_doc_names=duplicate_doc_names,
    )


def render_markdown(result: AuditResult) -> str:
    lines: List[str] = []
    lines.append("# Codebase Hygiene Audit")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{result.timestamp_utc}`")
    lines.append(f"- Files scanned: `{result.total_files_scanned}`")
    lines.append("")

    lines.append("## Large Files")
    if not result.large_files:
        lines.append("- None")
    else:
        for item in result.large_files:
            lines.append(f"- `{item['path']}` ({item['lines']} lines)")
    lines.append("")

    lines.append("## Artifact Directories")
    if not result.artifact_directories:
        lines.append("- None")
    else:
        for item in result.artifact_directories:
            lines.append(
                f"- `{item['path']}` ({item['files']} files, {item['size_mb']:.2f} MB)"
            )
    lines.append("")

    lines.append("## Empty Directories")
    if not result.empty_directories:
        lines.append("- None")
    else:
        for rel in result.empty_directories:
            lines.append(f"- `{rel}`")
    lines.append("")

    lines.append("## Script Archive Candidates")
    if not result.candidate_archive_scripts:
        lines.append("- None")
    else:
        for rel in result.candidate_archive_scripts:
            lines.append(f"- `{rel}`")
    lines.append("")

    lines.append("## Duplicate Markdown Basenames")
    if not result.duplicate_doc_names:
        lines.append("- None")
    else:
        for name, count in result.duplicate_doc_names.items():
            lines.append(f"- `{name}` appears `{count}` times")
    lines.append("")

    lines.append("## Notes")
    lines.append("- This audit is heuristic and should be reviewed before deleting files.")
    lines.append("- Use this report for cleanup PRs and modularization planning.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run repository hygiene audit.")
    parser.add_argument(
        "--large-file-threshold",
        type=int,
        default=700,
        help="Minimum line count to include in large-file list.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=40,
        help="Maximum number of large files to include.",
    )
    args = parser.parse_args()

    result = run_audit(
        root=REPO_ROOT,
        large_file_threshold=max(200, int(args.large_file_threshold)),
        top_n=max(10, int(args.top_n)),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    json_path = OUTPUT_DIR / f"codebase_hygiene_audit_{stamp}.json"
    md_path = OUTPUT_DIR / f"codebase_hygiene_audit_{stamp}.md"

    json_path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(result), encoding="utf-8")

    print(f"Saved JSON: {json_path}")
    print(f"Saved Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

