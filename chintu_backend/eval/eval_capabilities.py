"""Capabilities for running evaluation harness."""

from __future__ import annotations

from typing import Dict, Any

from chintu_backend.core.capabilities import Capability, CapabilityType, ActionResult
from chintu_backend.eval.runner import run_eval, _load_cases
from chintu_backend.eval.gates import run_reliability_gate
from chintu_backend.core.config import get_config


def handle_eval_run(_text: str, _context: Dict[str, Any]) -> ActionResult:
    config = get_config()
    cases_path = getattr(config, "eval_cases_path", None)
    if not cases_path:
        return ActionResult.fail("Eval cases path not configured.", "eval_run")
    cases = _load_cases(cases_path)
    score, results = run_eval(cases)
    failed = [r for r in results if not r.get("passed")]
    msg = f"Eval score: {score:.2f} ({len(cases)} cases)."
    if failed:
        msg += f" Failed: {len(failed)}."
    return ActionResult.ok(msg, {"score": score, "failed": failed}, "eval_run")


def register_eval_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="eval_run",
            triggers=["run eval", "run evaluation", "eval status", "evaluation status"],
            handler=handle_eval_run,
            requires_confirmation=False,
            description="run the routing/safety evaluation harness",
            capability_type=CapabilityType.SYSTEM,
            examples=["Run eval", "Evaluation status"],
        )
    )

    registry.register(
        Capability(
            name="reliability_gate_run",
            triggers=[
                "run reliability gate",
                "reliability status",
                "metrics gate",
                "run metrics gate",
                "run reliability check",
            ],
            handler=handle_reliability_gate,
            requires_confirmation=False,
            description="run combined reliability gate (eval + metrics)",
            capability_type=CapabilityType.SYSTEM,
            examples=["Run reliability gate", "Reliability status"],
        )
    )


def handle_reliability_gate(_text: str, _context: Dict[str, Any]) -> ActionResult:
    config = get_config()
    if not (getattr(config, "eval_gate_enabled", False) or getattr(config, "metrics_gate_enabled", False)):
        return ActionResult.ok("Reliability gate is disabled in config.", capability="reliability_gate_run")
    result = run_reliability_gate()
    status = "passed" if result.passed else "failed"
    msg = f"Reliability gate {status}: {result.message}"
    return ActionResult.ok(msg, {"passed": result.passed, "details": result.details}, "reliability_gate_run")
