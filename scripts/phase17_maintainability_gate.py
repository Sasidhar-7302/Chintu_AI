"""Phase 17 maintainability gate: file-size guardrails + type/error taxonomy checks."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
OUTPUT_DIR = REPO_ROOT / "generated_reports"

EXCLUDED_PARTS = {".git", "venv", "__pycache__", ".pytest_cache", ".tmp", "generated_reports", ".dart_tool", "build"}

TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".txt", ".ps1"}

DEFAULT_TYPED_TARGETS = [
    "chintu_backend/interfaces/gateway/server.py",
    "chintu_backend/interfaces/gateway/control_plane.py",
    "chintu_backend/interfaces/gateway/mini_app_html.py",
    "chintu_backend/workflows/workflow_runner.py",
    "chintu_backend/brain/learning/weekly_trainer.py",
]


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iter_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if set(rel.parts) & EXCLUDED_PARTS:
            continue
        if p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield p


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        return sum(1 for _ in f)


def _top_large_files(root: Path, top_n: int = 10) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for p in _iter_files(root):
        try:
            lines = _line_count(p)
        except Exception:
            continue
        rows.append({"path": str(p.relative_to(root)).replace("\\", "/"), "lines": lines})
    rows.sort(key=lambda x: int(x["lines"]), reverse=True)
    return rows[: max(1, int(top_n))]


def _guardrail_breaches(files: Sequence[Dict[str, Any]], threshold: int = 1200) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in files:
        if int(row.get("lines", 0) or 0) >= int(threshold):
            out.append(dict(row))
    return out


def _parse_module(path: Path) -> ast.AST:
    src = path.read_text(encoding="utf-8", errors="ignore")
    return ast.parse(src, filename=str(path))


def _function_is_typed(node: ast.AST) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return True
    # Skip private dunder and test helpers to keep adoption incremental.
    if node.name.startswith("_"):
        return True
    has_return = node.returns is not None
    args = list(node.args.args) + list(node.args.kwonlyargs)
    if node.args.vararg:
        args.append(node.args.vararg)
    if node.args.kwarg:
        args.append(node.args.kwarg)
    has_arg_annotations = all(getattr(a, "annotation", None) is not None for a in args)
    return bool(has_return and has_arg_annotations)


def _scan_untyped_functions(path: Path) -> List[str]:
    try:
        tree = _parse_module(path)
    except Exception:
        return ["<parse_error>"]
    missing: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not _function_is_typed(node):
            missing.append(node.name)
    return sorted(set(missing))


def _type_gate(root: Path, targets: Sequence[str]) -> Dict[str, Any]:
    results: Dict[str, List[str]] = {}
    for rel in targets:
        path = root / rel
        if not path.exists():
            results[rel] = ["<missing_file>"]
            continue
        missing = _scan_untyped_functions(path)
        if missing:
            results[rel] = missing
    return {
        "targets": list(targets),
        "violations": results,
        "passed": len(results) == 0,
    }


def _error_taxonomy_gate() -> Dict[str, Any]:
    try:
        from chintu_backend.core.exceptions import (  # noqa: F401
            ChintuError,
            ValidationFailure,
            PolicyViolation,
            ExternalServiceFailure,
            QualityGateFailure,
        )

        return {"passed": True, "message": "exception taxonomy available"}
    except Exception as exc:
        return {"passed": False, "message": f"exception taxonomy unavailable: {exc}"}


@dataclass
class Phase17GateResult:
    timestamp_utc: str
    top_files: List[Dict[str, Any]]
    guardrail_breaches: List[Dict[str, Any]]
    type_gate: Dict[str, Any]
    error_taxonomy_gate: Dict[str, Any]
    ok: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "top_files": self.top_files,
            "guardrail_breaches": self.guardrail_breaches,
            "type_gate": self.type_gate,
            "error_taxonomy_gate": self.error_taxonomy_gate,
            "ok": bool(self.ok),
        }


def run_phase17_gate(
    *,
    root: Path = REPO_ROOT,
    top_n: int = 10,
    large_file_threshold: int = 1200,
    typed_targets: Sequence[str] = DEFAULT_TYPED_TARGETS,
) -> Phase17GateResult:
    top_files = _top_large_files(root, top_n=top_n)
    breaches = _guardrail_breaches(top_files, threshold=large_file_threshold)
    type_gate = _type_gate(root, typed_targets)
    taxonomy_gate = _error_taxonomy_gate()
    ok = bool(type_gate.get("passed")) and bool(taxonomy_gate.get("passed"))
    return Phase17GateResult(
        timestamp_utc=_utc_iso(),
        top_files=top_files,
        guardrail_breaches=breaches,
        type_gate=type_gate,
        error_taxonomy_gate=taxonomy_gate,
        ok=ok,
    )


def _render_md(result: Phase17GateResult) -> str:
    lines: List[str] = []
    lines.append("# Phase 17 Maintainability Gate")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{result.timestamp_utc}`")
    lines.append(f"- Gate pass: `{result.ok}`")
    lines.append("")
    lines.append("## Top Largest Files")
    for row in result.top_files:
        lines.append(f"- `{row['path']}` ({row['lines']} lines)")
    lines.append("")
    lines.append("## Guardrail Breaches (>=1200 lines)")
    if not result.guardrail_breaches:
        lines.append("- None")
    else:
        for row in result.guardrail_breaches:
            lines.append(f"- `{row['path']}` ({row['lines']} lines)")
    lines.append("")
    lines.append("## Type Gate")
    lines.append(f"- Passed: `{result.type_gate.get('passed')}`")
    violations = result.type_gate.get("violations") if isinstance(result.type_gate, dict) else {}
    if isinstance(violations, dict) and violations:
        lines.append("- Violations:")
        for path, funcs in violations.items():
            lines.append(f"  - `{path}` -> {', '.join(funcs)}")
    else:
        lines.append("- Violations: none")
    lines.append("")
    lines.append("## Error Taxonomy Gate")
    lines.append(f"- Passed: `{result.error_taxonomy_gate.get('passed')}`")
    lines.append(f"- Message: {result.error_taxonomy_gate.get('message')}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 17 maintainability gate.")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--large-file-threshold", type=int, default=1200)
    parser.add_argument("--typed-target", action="append", default=[])
    args = parser.parse_args()

    targets = list(args.typed_target or DEFAULT_TYPED_TARGETS)
    result = run_phase17_gate(
        top_n=max(1, int(args.top_n)),
        large_file_threshold=max(300, int(args.large_file_threshold)),
        typed_targets=targets,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    json_path = OUTPUT_DIR / f"phase17_maintainability_gate_{stamp}.json"
    md_path = OUTPUT_DIR / f"phase17_maintainability_gate_{stamp}.md"
    json_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_md(result), encoding="utf-8")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
