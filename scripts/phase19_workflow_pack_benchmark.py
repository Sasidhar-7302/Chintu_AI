"""Phase 19 benchmark: execute cofounder workflow packs with deterministic evidence checks."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
OUTPUT_DIR = REPO_ROOT / "generated_reports"

from chintu_backend.core.config import get_config
from chintu_backend.workflows.workflow_runner import get_workflow_runner


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class PackCase:
    name: str
    workflow_path: str
    args: Dict[str, Any]


def _default_cases() -> List[PackCase]:
    return [
        PackCase(
            name="build_app_pack",
            workflow_path="chintu_backend/workflows/recipes/build_app_pack.yaml",
            args={"project": "phase19_demo_app"},
        ),
        PackCase(
            name="research_decision_pack",
            workflow_path="chintu_backend/workflows/recipes/research_decision_pack.yaml",
            args={"topic": "phase19 autonomous roadmap"},
        ),
        PackCase(
            name="finance_readonly_pack",
            workflow_path="chintu_backend/workflows/recipes/finance_readonly_pack.yaml",
            args={"portfolio": "phase19_portfolio"},
        ),
        PackCase(
            name="content_studio_pack",
            workflow_path="chintu_backend/workflows/recipes/content_studio_pack.yaml",
            args={"topic": "phase19 autonomous systems", "platform": "youtube"},
        ),
    ]


def _try_parse_json(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _extract_artifacts(result_output: List[Any]) -> List[str]:
    artifacts: List[str] = []
    for row in result_output:
        if not isinstance(row, dict):
            continue
        stdout = row.get("stdout")
        parsed = _try_parse_json(str(stdout or ""))
        for path in parsed.get("artifacts") or []:
            p = str(path or "").strip()
            if p:
                artifacts.append(p)
    return artifacts


def run_benchmark(cases: List[PackCase]) -> Dict[str, Any]:
    cfg = get_config()
    cfg.skills_allow_shell = True
    runner = get_workflow_runner()
    rows: List[Dict[str, Any]] = []

    for case in cases:
        workflow_path = str((REPO_ROOT / case.workflow_path).resolve())
        try:
            result = runner.run_file(workflow_path, args=case.args, mode="tool")
            artifacts = _extract_artifacts(list(result.output or []))
            existing = [p for p in artifacts if Path(p).exists()]
            ok = result.status == "ok" and len(existing) >= 1
            rows.append(
                {
                    "case": case.name,
                    "workflow_path": case.workflow_path,
                    "status": result.status,
                    "ok": bool(ok),
                    "artifacts": artifacts,
                    "existing_artifacts": existing,
                    "output_preview": [str(x)[:300] for x in (result.output or [])][:3],
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "case": case.name,
                    "workflow_path": case.workflow_path,
                    "status": "error",
                    "ok": False,
                    "error": str(exc),
                    "artifacts": [],
                    "existing_artifacts": [],
                }
            )

    passed = sum(1 for r in rows if r.get("ok"))
    total = len(rows)
    return {
        "timestamp_utc": _utc_iso(),
        "summary": {
            "total": total,
            "passed": passed,
            "pass_rate": round((passed / total), 3) if total else 0.0,
        },
        "results": rows,
    }


def _render_md(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    summary = report.get("summary") if isinstance(report, dict) else {}
    lines.append("# Phase 19 Workflow Pack Benchmark")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{report.get('timestamp_utc', '')}`")
    lines.append(f"- Total: `{summary.get('total', 0)}`")
    lines.append(f"- Passed: `{summary.get('passed', 0)}`")
    lines.append(f"- Pass rate: `{summary.get('pass_rate', 0.0)}`")
    lines.append("")
    for row in report.get("results", []):
        lines.append(f"## {row.get('case')}")
        lines.append(f"- status: `{row.get('status')}`")
        lines.append(f"- ok: `{row.get('ok')}`")
        artifacts = row.get("existing_artifacts") or []
        if artifacts:
            for item in artifacts:
                lines.append(f"- artifact: `{item}`")
        if row.get("error"):
            lines.append(f"- error: `{row.get('error')}`")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 19 workflow pack benchmark.")
    args = parser.parse_args()
    report = run_benchmark(_default_cases())

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    json_path = OUTPUT_DIR / f"phase19_workflow_pack_benchmark_{stamp}.json"
    md_path = OUTPUT_DIR / f"phase19_workflow_pack_benchmark_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")

    passed = int((report.get("summary") or {}).get("passed", 0) or 0)
    total = int((report.get("summary") or {}).get("total", 0) or 0)
    return 0 if total > 0 and passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
