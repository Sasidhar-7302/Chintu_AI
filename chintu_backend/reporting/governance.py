"""Phase 9 governance pipeline for benchmark tracking and regression alerts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from chintu_backend.core.config import get_config


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: Optional[datetime] = None) -> str:
    value = dt or _utc_now()
    return value.isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw).astimezone(timezone.utc)
    except Exception:
        return None


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(fallback)


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(fallback)


@dataclass(frozen=True)
class BenchmarkSignal:
    label: str
    pass_rate: float
    total: int
    passed: int
    source_path: str
    timestamp_utc: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "pass_rate": round(float(self.pass_rate), 3),
            "total": int(self.total),
            "passed": int(self.passed),
            "source_path": self.source_path,
            "timestamp_utc": self.timestamp_utc,
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class GovernanceAlert:
    severity: str
    category: str
    signal: str
    message: str
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "signal": self.signal,
            "message": self.message,
            "details": dict(self.details or {}),
        }


class BenchmarkGovernance:
    """Collect benchmark signals, detect regressions, and generate governance artifacts."""

    _REPORT_PATTERNS = {
        "daily_9_tasks": "chintu_9_task_validation_*.json",
        "extended_50": "chintu_50_realistic_*.json",
        "security_doctor": "phase8_security_doctor_*.json",
        "social_replay": "phase85_social_replay_*.json",
    }
    _WEIGHTS = {
        "daily_9_tasks": 0.35,
        "extended_50": 0.35,
        "security_doctor": 0.15,
        "social_replay": 0.15,
    }

    def __init__(
        self,
        *,
        config=None,
        reports_dir: Optional[Path] = None,
        history_path: Optional[Path] = None,
        alerts_path: Optional[Path] = None,
        monthly_review_dir: Optional[Path] = None,
    ):
        self.config = config or get_config()
        self.reports_dir = Path(reports_dir or self.config.phase9_reports_dir).resolve()
        self.history_path = Path(history_path or self.config.phase9_history_path).resolve()
        self.alerts_path = Path(alerts_path or self.config.phase9_alerts_path).resolve()
        self.monthly_review_dir = Path(
            monthly_review_dir or self.config.phase9_monthly_review_dir
        ).resolve()
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.alerts_path.parent.mkdir(parents=True, exist_ok=True)
        self.monthly_review_dir.mkdir(parents=True, exist_ok=True)

    def discover_latest_reports(self) -> Dict[str, Path]:
        found: Dict[str, Path] = {}
        for label, pattern in self._REPORT_PATTERNS.items():
            files = sorted(self.reports_dir.glob(pattern), key=lambda row: row.stat().st_mtime)
            if files:
                found[label] = files[-1]
        return found

    def load_signal(self, label: str, path: Path) -> Optional[BenchmarkSignal]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

        ts = str(payload.get("timestamp_utc") or payload.get("timestamp") or _utc_iso())
        if label in {"daily_9_tasks", "extended_50"}:
            summary = payload.get("summary") if isinstance(payload, dict) else {}
            if not isinstance(summary, dict):
                return None
            total = _safe_int(summary.get("total"), 0)
            passed = _safe_int(summary.get("pass"), _safe_int(summary.get("passed"), 0))
            pass_rate = _safe_float(summary.get("pass_rate"), fallback=(passed / total) if total else 0.0)
            if total > 0 and passed <= 0 and pass_rate > 0.0:
                passed = min(total, max(0, int(round(pass_rate * float(total)))))
            metadata = {
                "review": _safe_int(summary.get("review"), 0),
                "fail": _safe_int(summary.get("fail"), max(0, total - passed)),
                "elapsed_s": _safe_float(summary.get("elapsed_s"), 0.0),
            }
            return BenchmarkSignal(
                label=label,
                pass_rate=pass_rate,
                total=total,
                passed=passed,
                source_path=str(path),
                timestamp_utc=ts,
                metadata=metadata,
            )

        if label in {"security_doctor", "social_replay"}:
            success = bool(payload.get("success"))
            checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
            has_checks = isinstance(checks, dict) and bool(checks)
            total = len(checks) if has_checks else 1
            passed = sum(1 for ok in checks.values() if bool(ok)) if has_checks else (1 if success else 0)
            pass_rate = float(passed) / float(total) if total else 0.0
            return BenchmarkSignal(
                label=label,
                pass_rate=pass_rate,
                total=total,
                passed=passed,
                source_path=str(path),
                timestamp_utc=ts,
                metadata={"success": success, "checks": total},
            )
        return None

    def collect_signals(self) -> Dict[str, BenchmarkSignal]:
        discovered = self.discover_latest_reports()
        out: Dict[str, BenchmarkSignal] = {}
        for label, path in discovered.items():
            signal = self.load_signal(label, path)
            if signal:
                out[label] = signal
        return out

    def _aggregate_pass_rate(self, signals: Dict[str, BenchmarkSignal]) -> float:
        weighted_sum = 0.0
        weighted_total = 0.0
        for label, signal in signals.items():
            weight = float(self._WEIGHTS.get(label, 0.0))
            if weight <= 0:
                continue
            weighted_sum += weight * float(signal.pass_rate)
            weighted_total += weight
        if weighted_total <= 0:
            return 0.0
        return weighted_sum / weighted_total

    def build_snapshot(self, signals: Dict[str, BenchmarkSignal]) -> Dict[str, Any]:
        aggregate = self._aggregate_pass_rate(signals)
        return {
            "timestamp_utc": _utc_iso(),
            "signals": {label: signal.to_dict() for label, signal in sorted(signals.items())},
            "aggregate": {
                "pass_rate": round(float(aggregate), 3),
                "coverage": round(float(len(signals)) / float(len(self._REPORT_PATTERNS)), 3),
            },
        }

    def load_history(self, limit: int = 180) -> List[Dict[str, Any]]:
        if not self.history_path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in self.history_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
        rows = sorted(rows, key=lambda row: str(row.get("timestamp_utc") or ""))
        return rows[-max(1, int(limit)) :]

    def append_history(self, snapshot: Dict[str, Any]) -> None:
        line = json.dumps(snapshot, ensure_ascii=True)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def append_alerts(self, alerts: List[GovernanceAlert], run_timestamp_utc: str) -> None:
        if not alerts:
            return
        with self.alerts_path.open("a", encoding="utf-8") as handle:
            for alert in alerts:
                row = {"timestamp_utc": run_timestamp_utc, **alert.to_dict()}
                handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    def _previous_signal(self, history: List[Dict[str, Any]], label: str) -> Optional[float]:
        for row in reversed(history):
            signals = row.get("signals") if isinstance(row, dict) else None
            if not isinstance(signals, dict):
                continue
            signal = signals.get(label)
            if isinstance(signal, dict) and "pass_rate" in signal:
                return _safe_float(signal.get("pass_rate"), fallback=0.0)
        return None

    def _weekly_average(self, history: List[Dict[str, Any]], current: Dict[str, Any]) -> float:
        now = _parse_utc(str(current.get("timestamp_utc") or "")) or _utc_now()
        cutoff = now - timedelta(days=7)
        values: List[float] = []
        rows = history + [current]
        for row in rows:
            ts = _parse_utc(str(row.get("timestamp_utc") or ""))
            if ts is None or ts < cutoff:
                continue
            aggregate = row.get("aggregate") if isinstance(row, dict) else None
            if isinstance(aggregate, dict):
                values.append(_safe_float(aggregate.get("pass_rate"), fallback=0.0))
        if not values:
            return 0.0
        return float(sum(values) / len(values))

    def evaluate(self, snapshot: Dict[str, Any], history: List[Dict[str, Any]]) -> List[GovernanceAlert]:
        alerts: List[GovernanceAlert] = []
        signals = snapshot.get("signals") if isinstance(snapshot.get("signals"), dict) else {}
        required_labels = list(self._REPORT_PATTERNS.keys())
        for label in required_labels:
            if label not in signals:
                alerts.append(
                    GovernanceAlert(
                        severity="critical",
                        category="coverage",
                        signal=label,
                        message=f"Missing benchmark signal: {label}",
                        details={"required": True},
                    )
                )

        min_9 = float(getattr(self.config, "phase9_min_9_task_pass_rate", 0.85))
        min_extended = float(getattr(self.config, "phase9_min_extended_pass_rate", 0.70))
        drop_threshold = float(getattr(self.config, "phase9_drop_alert_threshold", 0.08))
        weekly_target = float(getattr(self.config, "phase9_weekly_target_pass_rate", 0.80))

        for label, row in signals.items():
            if not isinstance(row, dict):
                continue
            rate = _safe_float(row.get("pass_rate"), fallback=0.0)
            if label == "daily_9_tasks" and rate < min_9:
                alerts.append(
                    GovernanceAlert(
                        severity="critical",
                        category="threshold",
                        signal=label,
                        message=f"9-task pass rate below target ({rate:.3f} < {min_9:.3f}).",
                        details={"current": round(rate, 3), "min_target": round(min_9, 3)},
                    )
                )
            if label == "extended_50" and rate < min_extended:
                severity = "critical" if rate < max(0.0, min_extended - 0.10) else "warning"
                alerts.append(
                    GovernanceAlert(
                        severity=severity,
                        category="threshold",
                        signal=label,
                        message=f"Extended benchmark pass rate below target ({rate:.3f} < {min_extended:.3f}).",
                        details={"current": round(rate, 3), "min_target": round(min_extended, 3)},
                    )
                )
            if label in {"security_doctor", "social_replay"} and rate < 1.0:
                alerts.append(
                    GovernanceAlert(
                        severity="critical",
                        category="safety",
                        signal=label,
                        message=f"Safety replay failed for {label}.",
                        details={"current": round(rate, 3)},
                    )
                )

            previous_rate = self._previous_signal(history, label)
            if previous_rate is not None:
                drop = float(previous_rate) - rate
                if drop >= drop_threshold:
                    severity = "critical" if drop >= (drop_threshold * 1.5) else "warning"
                    alerts.append(
                        GovernanceAlert(
                            severity=severity,
                            category="regression",
                            signal=label,
                            message=f"Pass-rate regression detected for {label} (drop={drop:.3f}).",
                            details={
                                "previous": round(previous_rate, 3),
                                "current": round(rate, 3),
                                "drop": round(drop, 3),
                                "threshold": round(drop_threshold, 3),
                            },
                        )
                    )

        weekly_avg = self._weekly_average(history, snapshot)
        if weekly_avg < weekly_target:
            alerts.append(
                GovernanceAlert(
                    severity="warning",
                    category="weekly_target",
                    signal="aggregate",
                    message=f"Weekly aggregate pass rate below target ({weekly_avg:.3f} < {weekly_target:.3f}).",
                    details={"weekly_average": round(weekly_avg, 3), "target": round(weekly_target, 3)},
                )
            )

        return alerts

    def run_gate(self) -> Dict[str, Any]:
        signals = self.collect_signals()
        snapshot = self.build_snapshot(signals)
        history = self.load_history(limit=365)
        alerts = self.evaluate(snapshot, history)
        self.append_history(snapshot)
        self.append_alerts(alerts, str(snapshot.get("timestamp_utc") or _utc_iso()))

        critical = [row for row in alerts if row.severity == "critical"]
        warning = [row for row in alerts if row.severity == "warning"]
        report = {
            "timestamp_utc": str(snapshot.get("timestamp_utc") or _utc_iso()),
            "snapshot": snapshot,
            "alerts": [row.to_dict() for row in alerts],
            "summary": {
                "signal_count": len(signals),
                "critical_alerts": len(critical),
                "warning_alerts": len(warning),
                "aggregate_pass_rate": snapshot.get("aggregate", {}).get("pass_rate", 0.0),
                "ok": len(critical) == 0,
            },
        }
        return report

    def generate_monthly_review(self, month: Optional[str] = None) -> Dict[str, Any]:
        history = self.load_history(limit=2000)
        if not history:
            return {"success": False, "reason": "no_history"}

        if month:
            month_key = month.strip()
        else:
            month_key = _utc_now().strftime("%Y-%m")

        month_rows: List[Dict[str, Any]] = []
        for row in history:
            ts = _parse_utc(str(row.get("timestamp_utc") or ""))
            if not ts:
                continue
            if ts.strftime("%Y-%m") == month_key:
                month_rows.append(row)

        if not month_rows:
            return {"success": False, "reason": f"no_rows_for_month:{month_key}"}

        by_signal: Dict[str, List[float]] = {}
        aggregate_values: List[float] = []
        for row in month_rows:
            aggregate = row.get("aggregate") if isinstance(row, dict) else None
            if isinstance(aggregate, dict):
                aggregate_values.append(_safe_float(aggregate.get("pass_rate"), 0.0))
            signals = row.get("signals") if isinstance(row, dict) else None
            if not isinstance(signals, dict):
                continue
            for label, signal in signals.items():
                if not isinstance(signal, dict):
                    continue
                by_signal.setdefault(label, []).append(_safe_float(signal.get("pass_rate"), 0.0))

        alert_rows: List[Dict[str, Any]] = []
        if self.alerts_path.exists():
            for line in self.alerts_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                ts = _parse_utc(str(row.get("timestamp_utc") or ""))
                if ts and ts.strftime("%Y-%m") == month_key:
                    alert_rows.append(row)

        def _stats(values: List[float]) -> Dict[str, float]:
            if not values:
                return {"avg": 0.0, "min": 0.0, "max": 0.0}
            return {
                "avg": round(float(sum(values) / len(values)), 3),
                "min": round(float(min(values)), 3),
                "max": round(float(max(values)), 3),
            }

        aggregate_stats = _stats(aggregate_values)
        signal_stats = {label: _stats(vals) for label, vals in sorted(by_signal.items())}
        critical_count = sum(1 for row in alert_rows if str(row.get("severity") or "") == "critical")
        warning_count = sum(1 for row in alert_rows if str(row.get("severity") or "") == "warning")

        recommendations: List[str] = []
        if signal_stats.get("daily_9_tasks", {}).get("avg", 1.0) < float(
            getattr(self.config, "phase9_min_9_task_pass_rate", 0.85)
        ):
            recommendations.append(
                "Prioritize 9-task reliability triage and re-run `scripts/validate_9_tasks.py` after fixes."
            )
        if signal_stats.get("extended_50", {}).get("avg", 1.0) < float(
            getattr(self.config, "phase9_min_extended_pass_rate", 0.70)
        ):
            recommendations.append(
                "Stabilize extended benchmark coverage and re-run `scripts/chintu_50_realistic_benchmark.py`."
            )
        if signal_stats.get("security_doctor", {}).get("min", 1.0) < 1.0:
            recommendations.append(
                "Treat security-doctor failures as release blockers and resolve before feature rollout."
            )
        if not recommendations:
            recommendations.append(
                "No major regressions detected. Keep nightly runs and monitor weekly aggregate drift."
            )

        out_path = self.monthly_review_dir / f"phase9_monthly_review_{month_key.replace('-', '_')}.md"
        lines: List[str] = []
        lines.append(f"# Phase 9 Monthly Governance Review ({month_key})")
        lines.append("")
        lines.append("## Aggregate")
        lines.append("")
        lines.append(f"- runs: {len(month_rows)}")
        lines.append(f"- aggregate_avg: {aggregate_stats['avg']:.3f}")
        lines.append(f"- aggregate_min: {aggregate_stats['min']:.3f}")
        lines.append(f"- aggregate_max: {aggregate_stats['max']:.3f}")
        lines.append("")
        lines.append("## Signal Stats")
        lines.append("")
        lines.append("| Signal | Avg | Min | Max |")
        lines.append("| :-- | --: | --: | --: |")
        for label, stats in signal_stats.items():
            lines.append(f"| {label} | {stats['avg']:.3f} | {stats['min']:.3f} | {stats['max']:.3f} |")
        lines.append("")
        lines.append("## Alerts")
        lines.append("")
        lines.append(f"- critical: {critical_count}")
        lines.append(f"- warning: {warning_count}")
        lines.append("")
        lines.append("## Recommendations")
        lines.append("")
        for rec in recommendations:
            lines.append(f"- {rec}")
        lines.append("")
        out_path.write_text("\n".join(lines), encoding="utf-8")

        return {
            "success": True,
            "month": month_key,
            "runs": len(month_rows),
            "aggregate": aggregate_stats,
            "signals": signal_stats,
            "alerts": {"critical": critical_count, "warning": warning_count},
            "recommendations": recommendations,
            "path": str(out_path),
        }
