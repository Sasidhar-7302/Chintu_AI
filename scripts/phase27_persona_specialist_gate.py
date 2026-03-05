"""Phase 27 specialist-persona gate (routing correctness + safety fallback)."""

from __future__ import annotations

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

from chintu_backend.core.persona_registry import PersonaRegistry, PersonaSpec


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class PersonaCase:
    name: str
    prompt: str
    intent: str
    expected: str


def _default_cases() -> List[PersonaCase]:
    return [
        PersonaCase(
            name="coding_case",
            prompt="Please debug this Python API stack trace and propose a safe refactor plan.",
            intent="coding",
            expected="coding",
        ),
        PersonaCase(
            name="finance_case",
            prompt="Review my ETF portfolio allocation and downside risk before rebalancing.",
            intent="research",
            expected="finance",
        ),
        PersonaCase(
            name="medical_case",
            prompt="I have symptoms with fever and side effects from medication, what should I watch for?",
            intent="question",
            expected="medical",
        ),
        PersonaCase(
            name="default_case",
            prompt="Summarize my current project priorities for this week.",
            intent="general",
            expected="default",
        ),
    ]


def run_phase27_gate() -> Dict[str, Any]:
    registry = PersonaRegistry(enabled=True, specs=None)
    cases = _default_cases()
    rows: List[Dict[str, Any]] = []

    for case in cases:
        first = registry.select(text=case.prompt, intent=case.intent)
        second = registry.select(text=case.prompt, intent=case.intent)
        deterministic = first.name == second.name and first.reason == second.reason
        ok = (
            first.name == case.expected
            and deterministic
            and first.fallback_to_default is False
        )
        rows.append(
            {
                "case": case.name,
                "expected": case.expected,
                "selected": first.name,
                "requested": first.requested,
                "reason": first.reason,
                "fallback_to_default": bool(first.fallback_to_default),
                "deterministic": bool(deterministic),
                "ok": bool(ok),
            }
        )

    # Safety fallback contract: a missing adapter must fall back to default.
    missing_adapter = REPO_ROOT / "generated_reports" / "phase27_missing_adapter_marker"
    fallback_registry = PersonaRegistry(
        enabled=True,
        specs=[
            PersonaSpec(name="default", playbook="general", enabled=True),
            PersonaSpec(name="coding", adapter_path=str(missing_adapter), playbook="code", enabled=True),
        ],
    )
    fallback = fallback_registry.select(text="debug this python bug", intent="coding")
    fallback_ok = bool(fallback.name == "default" and fallback.fallback_to_default is True)

    pass_count = sum(1 for row in rows if row.get("ok"))
    overall_ok = bool(pass_count == len(rows) and fallback_ok)

    return {
        "phase": "phase27",
        "timestamp_utc": _utc_iso(),
        "summary": {
            "total": len(rows),
            "passed": pass_count,
            "pass_rate": round((pass_count / len(rows)), 3) if rows else 0.0,
            "fallback_contract_ok": fallback_ok,
        },
        "results": rows,
        "fallback_check": {
            "selected": fallback.name,
            "requested": fallback.requested,
            "reason": fallback.reason,
            "fallback_to_default": bool(fallback.fallback_to_default),
            "ok": fallback_ok,
        },
        "overall_ok": overall_ok,
    }


def _render_md(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    summary = report.get("summary") if isinstance(report, dict) else {}
    lines.append("# Phase 27 Multi-Persona Specialist Gate")
    lines.append("")
    lines.append(f"- Timestamp (UTC): `{report.get('timestamp_utc', '')}`")
    lines.append(f"- Overall gate pass: `{report.get('overall_ok')}`")
    lines.append(f"- Cases passed: `{summary.get('passed', 0)}` / `{summary.get('total', 0)}`")
    lines.append(f"- Fallback contract pass: `{summary.get('fallback_contract_ok')}`")
    lines.append("")
    for row in report.get("results", []):
        lines.append(f"## {row.get('case')}")
        lines.append(f"- expected: `{row.get('expected')}`")
        lines.append(f"- selected: `{row.get('selected')}`")
        lines.append(f"- requested: `{row.get('requested')}`")
        lines.append(f"- reason: `{row.get('reason')}`")
        lines.append(f"- fallback_to_default: `{row.get('fallback_to_default')}`")
        lines.append(f"- deterministic: `{row.get('deterministic')}`")
        lines.append(f"- ok: `{row.get('ok')}`")
        lines.append("")
    fb = report.get("fallback_check") or {}
    lines.append("## Safety Fallback")
    lines.append(f"- selected: `{fb.get('selected', '')}`")
    lines.append(f"- requested: `{fb.get('requested', '')}`")
    lines.append(f"- reason: `{fb.get('reason', '')}`")
    lines.append(f"- fallback_to_default: `{fb.get('fallback_to_default')}`")
    lines.append(f"- ok: `{fb.get('ok')}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = run_phase27_gate()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    json_path = OUTPUT_DIR / f"phase27_persona_specialist_gate_{stamp}.json"
    md_path = OUTPUT_DIR / f"phase27_persona_specialist_gate_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    return 0 if bool(report.get("overall_ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())

