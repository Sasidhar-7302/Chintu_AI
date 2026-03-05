"""Arbiter routing telemetry storage and aggregation."""

from __future__ import annotations

import json
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import get_config

_lock = threading.Lock()
_instance: Optional["ArbiterTelemetryStore"] = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass
class TelemetryEvent:
    event: str
    ts: str
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event,
            "ts": self.ts,
            "payload": self.payload,
        }


class ArbiterTelemetryStore:
    """JSONL-backed telemetry for arbiter decisions and route outcomes."""

    def __init__(self, path: Optional[Path] = None, max_events: int = 2000):
        config = get_config()
        telemetry_path = path or getattr(config, "arbiter_telemetry_path", None)
        if telemetry_path is None:
            telemetry_path = config.data_dir / "telemetry" / "arbiter_routing.jsonl"
        self.path = Path(telemetry_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_events = int(max_events)

    def _enforce_retention(self) -> None:
        if self.max_events <= 0:
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except Exception:
            return
        if len(lines) <= self.max_events:
            return
        try:
            with self.path.open("w", encoding="utf-8") as handle:
                handle.writelines(lines[-self.max_events :])
        except Exception:
            return

    def record(self, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
        cfg = get_config()
        if not bool(getattr(cfg, "arbiter_telemetry_enabled", True)):
            return
        item = TelemetryEvent(event=event, ts=_utc_now(), payload=payload or {})
        with _lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(item.to_dict(), ensure_ascii=True) + "\n")
            self._enforce_retention()

    def read_recent(self, limit: int = 300) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except Exception:
            return []
        lines = lines[-max(1, int(limit)) :]
        records: List[Dict[str, Any]] = []
        for line in lines:
            line = (line or "").strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    records.append(data)
            except Exception:
                continue
        return records

    def summarize(self, hours: int = 24, limit: int = 1200) -> Dict[str, Any]:
        records = self.read_recent(limit=limit)
        if not records:
            return {
                "events_scanned": 0,
                "decisions": {},
                "outcomes": {},
                "providers": {},
                "top_reasons": [],
            }

        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
        filtered: List[Dict[str, Any]] = []
        for row in records:
            ts = _parse_ts(str(row.get("ts", "")))
            if ts and ts >= cutoff:
                filtered.append(row)

        if not filtered:
            return {
                "events_scanned": 0,
                "decisions": {},
                "outcomes": {},
                "providers": {},
                "top_reasons": [],
            }

        decisions = [r for r in filtered if r.get("event") == "arbiter_decision"]
        outcomes = [r for r in filtered if r.get("event") == "routing_outcome"]
        provider_attempts = [r for r in filtered if r.get("event") == "provider_attempt"]

        need_cloud = 0
        force_local = 0
        confidence_vals: List[float] = []
        reason_counter: Counter = Counter()
        for row in decisions:
            payload = row.get("payload", {}) or {}
            if payload.get("need_cloud"):
                need_cloud += 1
            if payload.get("force_local"):
                force_local += 1
            try:
                confidence_vals.append(float(payload.get("confidence", 0.0)))
            except Exception:
                pass
            reason = str(payload.get("reason", "")).strip()
            if reason:
                reason_counter[reason] += 1

        route_counter: Counter = Counter()
        for row in outcomes:
            payload = row.get("payload", {}) or {}
            route = str(payload.get("source", "")).strip()
            if route:
                route_counter[route] += 1

        provider_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "attempts": 0,
                "success": 0,
                "failed": 0,
                "avg_latency_ms": 0.0,
            }
        )
        latency_buckets: Dict[str, List[float]] = defaultdict(list)
        for row in provider_attempts:
            payload = row.get("payload", {}) or {}
            provider = str(payload.get("provider", "unknown")).strip().lower()
            success = bool(payload.get("success"))
            provider_stats[provider]["attempts"] += 1
            if success:
                provider_stats[provider]["success"] += 1
            else:
                provider_stats[provider]["failed"] += 1
            try:
                latency = float(payload.get("latency_ms", 0.0))
                if latency > 0:
                    latency_buckets[provider].append(latency)
            except Exception:
                pass
        for provider, latencies in latency_buckets.items():
            if latencies:
                provider_stats[provider]["avg_latency_ms"] = round(sum(latencies) / len(latencies), 2)

        avg_conf = round(sum(confidence_vals) / len(confidence_vals), 3) if confidence_vals else 0.0

        return {
            "events_scanned": len(filtered),
            "decisions": {
                "total": len(decisions),
                "need_cloud": need_cloud,
                "force_local": force_local,
                "avg_confidence": avg_conf,
            },
            "outcomes": {
                "total": len(outcomes),
                "by_source": dict(route_counter),
            },
            "providers": dict(provider_stats),
            "top_reasons": reason_counter.most_common(8),
        }


def get_arbiter_telemetry() -> ArbiterTelemetryStore:
    global _instance
    if _instance is None:
        cfg = get_config()
        max_events = int(getattr(cfg, "arbiter_telemetry_retention_events", 2000))
        _instance = ArbiterTelemetryStore(max_events=max_events)
    return _instance
