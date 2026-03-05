"""Phase 7 replay harness for reliability/self-healing gate."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chintu_backend.core.action_dispatcher import ActionDispatcher
from chintu_backend.core.capabilities import (
    ActionResult,
    Capability,
    CapabilityRegistry,
    CapabilityType,
)
from chintu_backend.core.self_healing import FailureAwareRetryPlanner, PlanWatchdog, ToolFallbackGraph
import chintu_backend.core.capabilities as capabilities_module


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _utc_now().strftime("%Y%m%d_%H%M%S")


def _result_snapshot(result: ActionResult) -> Dict[str, Any]:
    data = result.data if isinstance(result.data, dict) else {}
    healing = data.get("phase7_self_healing") if isinstance(data, dict) else {}
    return {
        "success": bool(result.success),
        "message": str(result.message or ""),
        "capability": str(result.capability_name or ""),
        "strategy": str((healing or {}).get("strategy") or ""),
        "status": str((healing or {}).get("status") or ""),
    }


def _run_retry_same(enable_self_healing: bool) -> Dict[str, Any]:
    registry = CapabilityRegistry()
    calls = {"count": 0}

    def flaky_handler(_text, _ctx):
        calls["count"] += 1
        if calls["count"] == 1:
            return ActionResult.fail("Operation timeout while reading page", "phase7_retry_same")
        return ActionResult.ok("Recovered after retry.", capability="phase7_retry_same")

    registry.register(
        Capability(
            name="phase7_retry_same",
            triggers=["phase7 replay retry same"],
            handler=flaky_handler,
            capability_type=CapabilityType.SYSTEM,
            description="phase7 retry case",
        )
    )
    dispatcher = ActionDispatcher(registry=registry, llm_client=None)
    dispatcher.config.phase7_self_healing_enabled = bool(enable_self_healing)
    dispatcher.config.phase7_cloud_fallback_enabled = True
    result = dispatcher.dispatch("phase7 replay retry same", context={"session_id": "phase7-replay-retry"})
    row = _result_snapshot(result)
    row["calls"] = int(calls["count"])
    return row


def _run_local_fallback(enable_self_healing: bool) -> Dict[str, Any]:
    registry = CapabilityRegistry()

    def primary_handler(_text, _ctx):
        return ActionResult.fail("verification failed for primary tool", "phase7_primary")

    def alt_handler(_text, _ctx):
        return ActionResult.ok("Alternative local tool succeeded.", capability="phase7_alt")

    registry.register(
        Capability(
            name="phase7_primary",
            triggers=["phase7 replay local fallback"],
            handler=primary_handler,
            capability_type=CapabilityType.SYSTEM,
            description="primary local case",
        )
    )
    registry.register(
        Capability(
            name="phase7_alt",
            triggers=["phase7 replay alt trigger"],
            handler=alt_handler,
            capability_type=CapabilityType.SYSTEM,
            description="alt local case",
        )
    )
    dispatcher = ActionDispatcher(registry=registry, llm_client=None)
    dispatcher.fallback_graph = ToolFallbackGraph({"phase7_primary": ("phase7_alt",)})
    dispatcher.retry_planner = FailureAwareRetryPlanner(dispatcher.fallback_graph)
    dispatcher.config.phase7_self_healing_enabled = bool(enable_self_healing)
    dispatcher.config.phase7_cloud_fallback_enabled = False
    result = dispatcher.dispatch("phase7 replay local fallback", context={"session_id": "phase7-replay-local"})
    return _result_snapshot(result)


def _run_cloud_fallback(enable_self_healing: bool) -> Dict[str, Any]:
    registry = CapabilityRegistry()

    def fail_handler(_text, _ctx):
        return ActionResult.fail("execution failed for deterministic tool", "phase7_cloud")

    registry.register(
        Capability(
            name="phase7_cloud",
            triggers=["phase7 replay cloud fallback"],
            handler=fail_handler,
            capability_type=CapabilityType.SYSTEM,
            description="cloud fallback case",
        )
    )
    dispatcher = ActionDispatcher(registry=registry, llm_client=None)
    dispatcher.fallback_graph = ToolFallbackGraph({"phase7_cloud": tuple()})
    dispatcher.retry_planner = FailureAwareRetryPlanner(dispatcher.fallback_graph)
    dispatcher.config.phase7_self_healing_enabled = bool(enable_self_healing)
    dispatcher.config.phase7_cloud_fallback_enabled = True
    result = dispatcher.dispatch("phase7 replay cloud fallback", context={"session_id": "phase7-replay-cloud"})
    return _result_snapshot(result)


def _run_blocked_by_policy(enable_self_healing: bool) -> Dict[str, Any]:
    registry = CapabilityRegistry()

    def blocked_handler(_text, _ctx):
        return ActionResult.fail("Action blocked by policy gate.", "phase7_blocked")

    registry.register(
        Capability(
            name="phase7_blocked",
            triggers=["phase7 replay blocked policy"],
            handler=blocked_handler,
            capability_type=CapabilityType.SYSTEM,
            description="blocked by policy case",
        )
    )
    dispatcher = ActionDispatcher(registry=registry, llm_client=None)
    dispatcher.config.phase7_self_healing_enabled = bool(enable_self_healing)
    dispatcher.config.phase7_cloud_fallback_enabled = True
    result = dispatcher.dispatch("phase7 replay blocked policy", context={"session_id": "phase7-replay-blocked"})
    return _result_snapshot(result)


def _run_watchdog(enable_self_healing: bool) -> Dict[str, Any]:
    registry = CapabilityRegistry()

    def hard_fail(_text, _ctx):
        return ActionResult.fail("hard failure still happening", "phase7_watchdog")

    registry.register(
        Capability(
            name="phase7_watchdog",
            triggers=["phase7 replay watchdog"],
            handler=hard_fail,
            capability_type=CapabilityType.SYSTEM,
            description="watchdog case",
        )
    )
    dispatcher = ActionDispatcher(registry=registry, llm_client=None)
    dispatcher.config.phase7_self_healing_enabled = bool(enable_self_healing)
    dispatcher.config.phase7_cloud_fallback_enabled = False
    dispatcher.plan_watchdog = PlanWatchdog(repeat_threshold=3, window_seconds=300.0)
    dispatcher._execute_with_loop_guard = lambda capability, text, context: dispatcher._execute_capability(  # type: ignore[method-assign]
        capability, text, context
    )
    context = {"session_id": "phase7-replay-watchdog"}
    first = dispatcher.dispatch("phase7 replay watchdog", context=dict(context))
    second = dispatcher.dispatch("phase7 replay watchdog", context=dict(context))
    third = dispatcher.dispatch("phase7 replay watchdog", context=dict(context))
    return {
        "first": _result_snapshot(first),
        "second": _result_snapshot(second),
        "third": _result_snapshot(third),
    }


def run_replay() -> Dict[str, Any]:
    logging.getLogger("chintu_backend.core.capabilities").setLevel(logging.ERROR)
    capabilities_module.HAS_POLICY = False

    cases: List[Dict[str, Any]] = []

    retry_case = {
        "name": "retry_same_timeout",
        "baseline": _run_retry_same(enable_self_healing=False),
        "phase7": _run_retry_same(enable_self_healing=True),
    }
    cases.append(retry_case)

    local_case = {
        "name": "fallback_local",
        "baseline": _run_local_fallback(enable_self_healing=False),
        "phase7": _run_local_fallback(enable_self_healing=True),
    }
    cases.append(local_case)

    cloud_case = {
        "name": "fallback_cloud",
        "baseline": _run_cloud_fallback(enable_self_healing=False),
        "phase7": _run_cloud_fallback(enable_self_healing=True),
    }
    cases.append(cloud_case)

    blocked_case = {
        "name": "blocked_by_policy",
        "baseline": _run_blocked_by_policy(enable_self_healing=False),
        "phase7": _run_blocked_by_policy(enable_self_healing=True),
    }
    cases.append(blocked_case)

    watchdog_case = {
        "name": "watchdog_loop_break",
        "baseline": _run_watchdog(enable_self_healing=False),
        "phase7": _run_watchdog(enable_self_healing=True),
    }

    baseline_failures = sum(1 for row in cases if not bool(row["baseline"]["success"]))
    phase7_failures = sum(1 for row in cases if not bool(row["phase7"]["success"]))
    failure_reduction = 0.0
    if baseline_failures > 0:
        failure_reduction = (baseline_failures - phase7_failures) / baseline_failures

    checks = {
        "retry_same_recovers": bool(retry_case["phase7"]["success"])
        and retry_case["phase7"].get("strategy") == "retry_same",
        "fallback_local_recovers": bool(local_case["phase7"]["success"])
        and local_case["phase7"].get("strategy") == "fallback_local",
        "fallback_cloud_recovers": bool(cloud_case["phase7"]["success"])
        and cloud_case["phase7"].get("strategy") == "fallback_cloud",
        "blocked_by_policy_not_retried": bool(blocked_case["phase7"]["success"]) is False,
        "watchdog_stops_loop": "repeated failure loop"
        in str(watchdog_case["phase7"]["third"]["message"]).lower(),
    }

    pass_gate = bool(failure_reduction >= 0.30 and all(checks.values()))
    return {
        "phase": "phase7",
        "timestamp_utc": _utc_now().isoformat().replace("+00:00", "Z"),
        "baseline_failures": baseline_failures,
        "phase7_failures": phase7_failures,
        "failure_reduction_ratio": round(failure_reduction, 3),
        "checks": checks,
        "pass_gate": pass_gate,
        "cases": cases,
        "watchdog_case": watchdog_case,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay Phase-7 self-healing scenarios.")
    parser.add_argument("--out-dir", default="generated_reports")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    report = run_replay()
    out_path = out_dir / f"phase7_self_healing_replay_{_stamp()}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Wrote: {out_path}")
    print(
        json.dumps(
            {
                "baseline_failures": report["baseline_failures"],
                "phase7_failures": report["phase7_failures"],
                "failure_reduction_ratio": report["failure_reduction_ratio"],
                "pass_gate": report["pass_gate"],
            },
            indent=2,
        )
    )
    return 0 if bool(report["pass_gate"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
