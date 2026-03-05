"""Phase 4 probe: compare baseline local routing vs AirLLM on hard reasoning tasks.

This probe is intentionally small and deterministic:
- Forces complex_reasoning routing for each case.
- Captures route source, latency, and simple correctness checks.
- Writes JSON + Markdown reports under generated_reports/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.core import model_router as model_router_module
from chintu_backend.core.model_router import Intent, RoutingDecision, TaskComplexity


@dataclass
class ReasoningCase:
    name: str
    prompt: str
    expected_regex: str


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _default_cases() -> List[ReasoningCase]:
    return [
        ReasoningCase(
            name="math_mix",
            prompt="Compute exactly: (17 * 19) + (23 * 11). Return only the final number.",
            expected_regex=r"\b576\b",
        ),
        ReasoningCase(
            name="distance_rate",
            prompt="A car travels 60 mph for 1.5 hours and 30 mph for 2 hours. What total distance in miles? Return only the number.",
            expected_regex=r"\b150\b",
        ),
        ReasoningCase(
            name="set_logic",
            prompt="All wugs are zips. No zips are red. Can any wug be red? Answer with one word only: yes or no.",
            expected_regex=r"\bno\b",
        ),
        ReasoningCase(
            name="calendar_mod",
            prompt="If today is Wednesday, what day is 45 days from now? Answer with one day name only.",
            expected_regex=r"\bsaturday\b",
        ),
        ReasoningCase(
            name="linear_equation",
            prompt="Solve for x: 3x + 7 = 52. Return only the number.",
            expected_regex=r"\b15\b",
        ),
    ]


def _force_complex_reasoning(router) -> None:
    decision = RoutingDecision(
        intent=Intent.REASONING,
        complexity=TaskComplexity.COMPLEX_REASONING,
        use_llm=True,
        prefer_cloud=False,
        extracted_params={},
    )
    router.intent_detector.detect = lambda _text: decision


def _run_variant(
    name: str,
    *,
    airllm_enabled: bool,
    model_id: str,
    allow_download: bool,
    runtime_mode: str,
    request_timeout_seconds: int,
    startup_timeout_seconds: int,
) -> Dict[str, Any]:
    cfg = model_router_module.get_config()
    cfg.airllm_enabled = bool(airllm_enabled)
    cfg.airllm_model_id = str(model_id or "")
    cfg.airllm_allow_download = bool(allow_download)
    cfg.airllm_runtime_mode = str(runtime_mode or "auto")
    cfg.airllm_request_timeout_seconds = int(request_timeout_seconds or 900)
    cfg.airllm_startup_timeout_seconds = int(startup_timeout_seconds or 1800)

    # Reset singleton to apply fresh config each variant.
    model_router_module._router = None
    router = model_router_module.get_model_router()
    _force_complex_reasoning(router)

    rows: List[Dict[str, Any]] = []
    for case in _default_cases():
        started = time.perf_counter()
        response, source = router.route_and_execute(case.prompt)
        latency_s = time.perf_counter() - started
        text = str(response or "")
        ok = bool(re.search(case.expected_regex, text, flags=re.IGNORECASE))
        rows.append(
            {
                "name": case.name,
                "source": source,
                "latency_s": round(latency_s, 3),
                "ok": ok,
                "expected_regex": case.expected_regex,
                "response_excerpt": text[:280],
            }
        )

    pass_count = sum(1 for row in rows if row.get("ok"))
    sources = sorted({str(row.get("source") or "") for row in rows})
    return {
        "variant": name,
        "airllm_enabled": bool(airllm_enabled),
        "airllm_model_id": str(model_id or ""),
        "airllm_allow_download": bool(allow_download),
        "airllm_runtime_mode": str(runtime_mode or "auto"),
        "airllm_request_timeout_seconds": int(request_timeout_seconds or 900),
        "airllm_startup_timeout_seconds": int(startup_timeout_seconds or 1800),
        "summary": {
            "total": len(rows),
            "pass": pass_count,
            "pass_rate": round((pass_count / len(rows)) if rows else 0.0, 3),
            "avg_latency_s": round(mean(float(row.get("latency_s") or 0.0) for row in rows), 3) if rows else 0.0,
            "sources": sources,
        },
        "rows": rows,
    }


def _write_markdown(report: Dict[str, Any], out_path: Path) -> None:
    lines: List[str] = []
    lines.append("# AirLLM Hard Reasoning Probe")
    lines.append("")
    lines.append(f"- timestamp_utc: `{report.get('timestamp_utc', '')}`")
    lines.append(f"- model_id: `{report.get('model_id', '')}`")
    lines.append(f"- forced_complex_reasoning: `{report.get('forced_complex_reasoning', False)}`")
    lines.append("")

    baseline = report.get("baseline", {}) if isinstance(report, dict) else {}
    airllm = report.get("airllm", {}) if isinstance(report, dict) else {}
    baseline_summary = baseline.get("summary", {}) if isinstance(baseline, dict) else {}
    airllm_summary = airllm.get("summary", {}) if isinstance(airllm, dict) else {}
    lines.append("## Summary")
    lines.append("")
    lines.append("| Variant | Pass/Total | Pass Rate | Avg Latency (s) | Sources |")
    lines.append("|---|---:|---:|---:|---|")
    lines.append(
        "| baseline | {p}/{t} | {r} | {lat} | {src} |".format(
            p=baseline_summary.get("pass", 0),
            t=baseline_summary.get("total", 0),
            r=baseline_summary.get("pass_rate", 0.0),
            lat=baseline_summary.get("avg_latency_s", 0.0),
            src=", ".join(baseline_summary.get("sources", []) or []),
        )
    )
    lines.append(
        "| airllm | {p}/{t} | {r} | {lat} | {src} |".format(
            p=airllm_summary.get("pass", 0),
            t=airllm_summary.get("total", 0),
            r=airllm_summary.get("pass_rate", 0.0),
            lat=airllm_summary.get("avg_latency_s", 0.0),
            src=", ".join(airllm_summary.get("sources", []) or []),
        )
    )
    lines.append("")
    lines.append("## AirLLM Cases")
    lines.append("")
    lines.append("| Case | Source | OK | Latency (s) | Excerpt |")
    lines.append("|---|---|---:|---:|---|")
    for row in (airllm.get("rows", []) if isinstance(airllm, dict) else []):
        excerpt = str(row.get("response_excerpt", "")).replace("\n", " ").replace("|", "\\|")
        lines.append(
            "| {name} | {source} | {ok} | {lat} | {excerpt} |".format(
                name=row.get("name", ""),
                source=row.get("source", ""),
                ok="Y" if row.get("ok") else "N",
                lat=row.get("latency_s", 0.0),
                excerpt=excerpt,
            )
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_probe(
    model_id: str,
    *,
    allow_download: bool = False,
    runtime_mode: str = "auto",
    request_timeout_seconds: int = 900,
    startup_timeout_seconds: int = 1800,
) -> Dict[str, Any]:
    baseline = _run_variant(
        "baseline",
        airllm_enabled=False,
        model_id="",
        allow_download=False,
        runtime_mode=runtime_mode,
        request_timeout_seconds=request_timeout_seconds,
        startup_timeout_seconds=startup_timeout_seconds,
    )
    airllm = _run_variant(
        "airllm",
        airllm_enabled=True,
        model_id=model_id,
        allow_download=allow_download,
        runtime_mode=runtime_mode,
        request_timeout_seconds=request_timeout_seconds,
        startup_timeout_seconds=startup_timeout_seconds,
    )
    baseline_summary = baseline.get("summary", {}) if isinstance(baseline, dict) else {}
    airllm_summary = airllm.get("summary", {}) if isinstance(airllm, dict) else {}

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model_id": model_id,
        "allow_download": bool(allow_download),
        "runtime_mode": str(runtime_mode or "auto"),
        "request_timeout_seconds": int(request_timeout_seconds or 900),
        "startup_timeout_seconds": int(startup_timeout_seconds or 1800),
        "forced_complex_reasoning": True,
        "baseline": baseline,
        "airllm": airllm,
        "delta": {
            "pass_rate": round(
                float(airllm_summary.get("pass_rate", 0.0)) - float(baseline_summary.get("pass_rate", 0.0)),
                3,
            ),
            "avg_latency_s": round(
                float(airllm_summary.get("avg_latency_s", 0.0)) - float(baseline_summary.get("avg_latency_s", 0.0)),
                3,
            ),
        },
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare baseline vs AirLLM on forced hard-reasoning cases.")
    parser.add_argument(
        "--model-id",
        default="",
        help="Hugging Face model id for AirLLM (required for AirLLM run).",
    )
    parser.add_argument(
        "--allow-download",
        action="store_true",
        help="Allow AirLLM to download missing shards (can take a long time).",
    )
    parser.add_argument(
        "--runtime-mode",
        default="auto",
        help="AirLLM runtime mode: auto|inprocess|subprocess.",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=int,
        default=900,
        help="Per-response timeout for AirLLM path before fallback.",
    )
    parser.add_argument(
        "--startup-timeout-seconds",
        type=int,
        default=1800,
        help="Timeout for AirLLM worker startup handshake.",
    )
    parser.add_argument("--out-dir", default="generated_reports")
    args = parser.parse_args()

    cfg = model_router_module.get_config()
    model_id = str(args.model_id or getattr(cfg, "airllm_model_id", "") or "").strip()
    if not model_id:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "Missing model id. Set CHINTU_AIRLLM_MODEL_ID or pass --model-id.",
                },
                ensure_ascii=True,
            )
        )
        return 2

    report = run_probe(
        model_id=model_id,
        allow_download=bool(args.allow_download),
        runtime_mode=str(args.runtime_mode or "auto"),
        request_timeout_seconds=max(30, int(args.request_timeout_seconds or 900)),
        startup_timeout_seconds=max(60, int(args.startup_timeout_seconds or 1800)),
    )
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    json_path = out_dir / f"chintu_airllm_reasoning_probe_{stamp}.json"
    md_path = out_dir / f"chintu_airllm_reasoning_probe_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    _write_markdown(report, md_path)

    baseline_summary = report.get("baseline", {}).get("summary", {})
    airllm_summary = report.get("airllm", {}).get("summary", {})
    print(
        json.dumps(
            {
                "ok": True,
                "json_report": str(json_path),
                "markdown_report": str(md_path),
                "baseline": baseline_summary,
                "airllm": airllm_summary,
                "delta": report.get("delta", {}),
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
