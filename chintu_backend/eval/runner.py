"""Evaluation harness for routing + safety consistency."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Tuple

from chintu_backend.core.capabilities import get_registry
from chintu_backend.security.prompt_guard import get_prompt_guard
from chintu_backend.core.config import get_config


@dataclass
class EvalCase:
    text: str
    expected_capability: str | None = None
    expect_refusal: bool = False
    memory_seed: List[Dict[str, str]] | None = None
    memory_query: str | None = None
    expect_memory_contains: str | None = None
    expected_signal_type: str | None = None
    expected_preference_key: str | None = None
    expected_preference_value: Any | None = None


def _load_cases(path: Path) -> List[EvalCase]:
    cases: List[EvalCase] = []
    if not path.exists():
        return cases
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            cases.append(
                EvalCase(
                    text=data.get("text", ""),
                    expected_capability=data.get("expected_capability"),
                    expect_refusal=bool(data.get("expect_refusal", False)),
                    memory_seed=data.get("memory_seed"),
                    memory_query=data.get("memory_query"),
                    expect_memory_contains=data.get("expect_memory_contains"),
                    expected_signal_type=data.get("expected_signal_type"),
                    expected_preference_key=data.get("expected_preference_key"),
                    expected_preference_value=data.get("expected_preference_value"),
                )
            )
        except Exception:
            continue
    return cases


def run_eval(cases: List[EvalCase]) -> Tuple[float, List[Dict[str, Any]]]:
    registry = get_registry()
    guard = get_prompt_guard()
    results: List[Dict[str, Any]] = []
    passed = 0
    for case in cases:
        matched = registry.match(case.text)
        is_safe, _category = guard.check(case.text)
        actual_cap = matched.name if matched else None
        refusal = not is_safe
        memory_ok = True
        memory_context = ""

        if case.memory_seed or case.expect_memory_contains:
            try:
                from chintu_backend.brain.memory.hybrid_memory import HybridMemoryManager
                config = get_config()
                eval_dir = Path(config.data_dir) / "eval"
                eval_dir.mkdir(parents=True, exist_ok=True)
                db_path = eval_dir / f"memory_eval_{int(time.time()*1000)}.db"
                memory = HybridMemoryManager(db_path=db_path)
                for entry in case.memory_seed or []:
                    role = entry.get("role", "user")
                    content = entry.get("content") or entry.get("text") or ""
                    if content:
                        memory.save_interaction(role, content)
                query = case.memory_query or case.text
                memory_context = memory.retrieve_context(query, n_results=3)
                if case.expect_memory_contains:
                    memory_ok = case.expect_memory_contains.lower() in memory_context.lower()
            except Exception:
                memory_ok = False

        signal_ok = True
        if case.expected_signal_type or case.expected_preference_key:
            try:
                from chintu_backend.brain.memory.learning_signals import get_signal_manager
                manager = get_signal_manager()
                signals = manager.analyze_feedback(case.text)
                if not signals:
                    signal_ok = False
                else:
                    if case.expected_signal_type:
                        signal_ok &= any(s.signal_type == case.expected_signal_type for s in signals)
                    if case.expected_preference_key:
                        match = False
                        for s in signals:
                            action = s.proposed_action or {}
                            if action.get("key") == case.expected_preference_key:
                                if case.expected_preference_value is None or action.get("value") == case.expected_preference_value:
                                    match = True
                                    break
                        signal_ok &= match
            except Exception:
                signal_ok = False

        ok = True
        if case.expected_capability:
            ok &= (actual_cap == case.expected_capability)
        if case.expect_refusal:
            ok &= refusal
        if case.expect_memory_contains:
            ok &= memory_ok
        if case.expected_signal_type or case.expected_preference_key:
            ok &= signal_ok
        results.append(
            {
                "text": case.text,
                "expected_capability": case.expected_capability,
                "actual_capability": actual_cap,
                "expected_refusal": case.expect_refusal,
                "actual_refusal": refusal,
                "expected_memory_contains": case.expect_memory_contains,
                "memory_ok": memory_ok,
                "expected_signal_type": case.expected_signal_type,
                "expected_preference_key": case.expected_preference_key,
                "expected_preference_value": case.expected_preference_value,
                "signal_ok": signal_ok,
                "memory_context": memory_context[:500] if memory_context else "",
                "passed": ok,
            }
        )
        if ok:
            passed += 1
    score = passed / len(cases) if cases else 0.0
    return score, results


def main() -> int:
    parser = argparse.ArgumentParser(description="Chintu evaluation harness")
    parser.add_argument("--cases", type=str, default="", help="Path to JSONL cases")
    parser.add_argument("--min-score", type=float, default=None, help="Minimum pass score")
    args = parser.parse_args()

    config = get_config()
    cases_path = Path(args.cases) if args.cases else Path(config.data_dir) / "eval" / "cases.jsonl"
    cases = _load_cases(cases_path)
    score, results = run_eval(cases)

    print(f"Eval score: {score:.2f} ({len(cases)} cases)")
    for r in results:
        if not r["passed"]:
            print(f"FAIL: {r}")

    min_score = args.min_score
    if min_score is None:
        min_score = float(getattr(config, "eval_min_score", 0.8))
    gate_enabled = bool(getattr(config, "eval_gate_enabled", False))
    if gate_enabled and score < min_score:
        print(f"Gate failed (min={min_score:.2f}).")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
