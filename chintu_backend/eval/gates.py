"""Reliability gates for eval and telemetry metrics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from chintu_backend.core.config import get_config
from chintu_backend.eval.runner import run_eval, _load_cases
from chintu_backend.telemetry.metrics import get_metrics


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class GateResult:
    name: str
    passed: bool
    score: float
    message: str
    details: Dict[str, Any]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "score": self.score,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
        }


def _store_gate_result(name: str, result: GateResult, base_dir: Optional[Path] = None) -> None:
    config = get_config()
    base_dir = base_dir or (Path(config.data_dir) / "reliability")
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"{name}.json"
    path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")


def _load_gate_result(name: str, base_dir: Optional[Path] = None) -> Optional[GateResult]:
    config = get_config()
    base_dir = base_dir or (Path(config.data_dir) / "reliability")
    path = base_dir / f"{name}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return GateResult(
            name=data.get("name", name),
            passed=bool(data.get("passed", False)),
            score=float(data.get("score", 0.0)),
            message=str(data.get("message", "")),
            details=data.get("details", {}) or {},
            timestamp=data.get("timestamp", ""),
        )
    except Exception:
        return None


def run_eval_gate(
    cases_path: Optional[Path] = None,
    min_score: Optional[float] = None,
    persist: bool = True,
) -> GateResult:
    config = get_config()
    cases_path = cases_path or getattr(config, "eval_cases_path", None)
    min_score = min_score if min_score is not None else float(getattr(config, "eval_min_score", 0.8))

    if not cases_path:
        result = GateResult(
            name="eval",
            passed=False,
            score=0.0,
            message="Eval cases path not configured",
            details={},
            timestamp=_utc_now(),
        )
        if persist:
            _store_gate_result("eval", result)
        return result

    cases = _load_cases(Path(cases_path))
    if not cases:
        result = GateResult(
            name="eval",
            passed=False,
            score=0.0,
            message="No eval cases found",
            details={"cases": 0},
            timestamp=_utc_now(),
        )
        if persist:
            _store_gate_result("eval", result)
        return result

    score, results = run_eval(cases)
    passed = score >= min_score
    failed = [r for r in results if not r.get("passed")]
    message = f"Eval score {score:.2f} ({len(cases)} cases)"
    if failed:
        message += f" - {len(failed)} failed"
    result = GateResult(
        name="eval",
        passed=passed,
        score=float(score),
        message=message,
        details={"failed": failed, "cases": len(cases), "min_score": min_score},
        timestamp=_utc_now(),
    )
    if persist:
        _store_gate_result("eval", result)
    return result


def run_metrics_gate(persist: bool = True) -> GateResult:
    config = get_config()
    metrics = get_metrics()
    stats = metrics.get_stats()

    min_requests = int(getattr(config, "metrics_gate_min_requests", 20))
    max_error_rate = float(getattr(config, "metrics_gate_error_rate_max", 0.05))
    max_p95_ms = float(getattr(config, "metrics_gate_total_p95_ms", 5000.0))
    max_avg_ms = float(getattr(config, "metrics_gate_total_avg_ms", 2000.0))

    total_requests = int(stats.get("total_requests", 0))
    total_errors = int(stats.get("total_errors", 0))
    error_rate = (total_errors / total_requests) if total_requests > 0 else 0.0

    latencies = stats.get("latencies", {}) or {}
    total_latency = latencies.get("total", {}) or {}
    avg_ms = float(total_latency.get("avg_ms", 0.0) or 0.0)
    p95_ms = float(total_latency.get("p95_ms", 0.0) or 0.0)

    if total_requests < min_requests:
        result = GateResult(
            name="metrics",
            passed=True,
            score=1.0,
            message=f"Insufficient telemetry ({total_requests}/{min_requests} requests)",
            details={
                "total_requests": total_requests,
                "total_errors": total_errors,
                "error_rate": error_rate,
                "avg_ms": avg_ms,
                "p95_ms": p95_ms,
                "min_requests": min_requests,
            },
            timestamp=_utc_now(),
        )
        if persist:
            _store_gate_result("metrics", result)
        return result

    passed = True
    failures = []
    if error_rate > max_error_rate:
        passed = False
        failures.append(f"error_rate {error_rate:.3f} > {max_error_rate:.3f}")
    if p95_ms and p95_ms > max_p95_ms:
        passed = False
        failures.append(f"p95_ms {p95_ms:.0f} > {max_p95_ms:.0f}")
    if avg_ms and avg_ms > max_avg_ms:
        passed = False
        failures.append(f"avg_ms {avg_ms:.0f} > {max_avg_ms:.0f}")

    message = "Metrics gate passed" if passed else "Metrics gate failed: " + "; ".join(failures)
    result = GateResult(
        name="metrics",
        passed=passed,
        score=1.0 if passed else 0.0,
        message=message,
        details={
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate": error_rate,
            "avg_ms": avg_ms,
            "p95_ms": p95_ms,
            "thresholds": {
                "max_error_rate": max_error_rate,
                "max_p95_ms": max_p95_ms,
                "max_avg_ms": max_avg_ms,
            },
        },
        timestamp=_utc_now(),
    )
    if persist:
        _store_gate_result("metrics", result)
    return result


def run_reliability_gate(persist: bool = True) -> GateResult:
    config = get_config()
    eval_enabled = bool(getattr(config, "eval_gate_enabled", False))
    metrics_enabled = bool(getattr(config, "metrics_gate_enabled", False))

    results = {}
    passed = True
    score = 1.0
    messages = []

    if eval_enabled:
        eval_result = run_eval_gate(persist=persist)
        results["eval"] = eval_result.to_dict()
        if not eval_result.passed:
            passed = False
        score = min(score, eval_result.score)
        messages.append(eval_result.message)

    if metrics_enabled:
        metrics_result = run_metrics_gate(persist=persist)
        results["metrics"] = metrics_result.to_dict()
        if not metrics_result.passed:
            passed = False
        score = min(score, metrics_result.score)
        messages.append(metrics_result.message)

    if not eval_enabled and not metrics_enabled:
        passed = True
        score = 1.0
        messages.append("Reliability gate disabled")

    message = " | ".join(messages) if messages else "Reliability gate complete"
    result = GateResult(
        name="reliability",
        passed=passed,
        score=score,
        message=message,
        details=results,
        timestamp=_utc_now(),
    )
    if persist:
        _store_gate_result("reliability", result)
    return result


__all__ = [
    "GateResult",
    "run_eval_gate",
    "run_metrics_gate",
    "run_reliability_gate",
    "_load_gate_result",
]
