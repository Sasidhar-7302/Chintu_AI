"""Small A/B routing evaluation harness for Phase 2.5 tuning."""

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

from chintu_backend.core.model_router import ModelRouter


@dataclass
class EvalCase:
    name: str
    text: str
    expected_route: str  # local | cloud


class _DummyLocalLLM:
    is_available = True
    model = "llama3.1:8b"
    model_name = "llama3.1:8b"

    def generate(self, prompt, system_prompt=None):
        return "local-ok"

    def generate_stream(self, prompt, system_prompt=None):
        yield "local-ok"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _evaluate_variant(name: str, *, prefer_local: bool, cases: List[EvalCase]) -> Dict[str, Any]:
    router = ModelRouter(local_llm=_DummyLocalLLM(), prefer_local=prefer_local)
    router.ThinkingManagerClass = None

    # Deterministic cloud mock: we only care about routing choice, not provider APIs.
    def _mock_cloud(provider, *_args, **_kwargs):
        return f"cloud-ok:{provider}"

    router._try_cloud_provider = _mock_cloud  # type: ignore[assignment]

    rows: List[Dict[str, Any]] = []
    passed = 0
    for case in cases:
        _response, source = router.route_and_execute(case.text)
        actual_route = "cloud" if source in {"nvidia", "groq", "gemini", "deepseek"} else "local"
        ok = actual_route == case.expected_route
        if ok:
            passed += 1
        rows.append(
            {
                "name": case.name,
                "text": case.text,
                "expected_route": case.expected_route,
                "actual_route": actual_route,
                "source": source,
                "ok": ok,
            }
        )

    total = len(cases)
    return {
        "variant": name,
        "prefer_local": prefer_local,
        "summary": {
            "total": total,
            "passed": passed,
            "pass_rate": round((passed / total) if total else 0.0, 3),
        },
        "cases": rows,
    }


def run_eval() -> Dict[str, Any]:
    cases = [
        EvalCase("simple_chat", "Hey Chintu, how are you?", "local"),
        EvalCase("coding_task", "Write Python code to parse JSON and validate schema.", "cloud"),
        EvalCase("deep_research", "Research latest AI model benchmarks and summarize.", "cloud"),
        EvalCase("credential_guard", "My api key is sk-123. summarize this safely.", "local"),
        EvalCase("timer", "Set a timer for 10 minutes.", "local"),
    ]
    local_first = _evaluate_variant("local_first", prefer_local=True, cases=cases)
    cloud_first = _evaluate_variant("cloud_first", prefer_local=False, cases=cases)

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "cases_total": len(cases),
        "variants": [local_first, cloud_first],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a small A/B routing evaluation suite.")
    parser.add_argument("--out-dir", default="generated_reports")
    args = parser.parse_args()

    report = run_eval()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"routing_ab_eval_{_utc_stamp()}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Wrote: {out_path}")
    for variant in report.get("variants", []):
        summary = variant.get("summary", {})
        print(
            f"{variant.get('variant')}: pass_rate={summary.get('pass_rate')} "
            f"({summary.get('passed')}/{summary.get('total')})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

