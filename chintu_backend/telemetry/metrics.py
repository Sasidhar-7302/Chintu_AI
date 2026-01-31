"""
Metrics collection for Chintu AI Assistant.

Tracks:
- Component latencies (wake, stt, routing, llm, tts)
- Model routing statistics
- Error rates by category
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional
from collections import defaultdict, deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class LatencyRecord:
    """A single latency measurement."""

    component: str
    duration_ms: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class ModelUsageRecord:
    """Record of a model routing decision."""

    model: str
    reason: str
    query_length: int
    success: bool
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    """
    Collects and aggregates metrics for debugging and optimization.
    """

    PIPELINE_COMPONENTS = [
        "wake_word",
        "stt",
        "routing",
        "llm",
        "tts",
        "total",
    ]

    def __init__(self, max_history: int = 1000):
        self._max_history = max_history
        self._latencies: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history))
        self._model_usage: Dict[str, int] = defaultdict(int)
        self._model_success: Dict[str, int] = defaultdict(int)
        self._errors: Dict[str, int] = defaultdict(int)
        self._request_count: int = 0
        self._lock = threading.Lock()
        self._current_pipeline: Dict[str, float] = {}
        self._last_model: str = "none"

        logger.info("MetricsCollector initialized (max_history=%s)", max_history)

    def record_latency(self, component: str, duration_ms: float):
        record = LatencyRecord(component=component, duration_ms=duration_ms)
        with self._lock:
            self._latencies[component].append(record)
        logger.debug("Latency: %s=%.1fms", component, duration_ms)

    def start_pipeline(self):
        self._current_pipeline = {"_start": time.time()}
        with self._lock:
            self._request_count += 1

    def mark_pipeline(self, component: str):
        if "_start" not in self._current_pipeline:
            return

        now = time.time()
        start = self._current_pipeline.get("_last", self._current_pipeline["_start"])
        duration_ms = (now - start) * 1000

        self._current_pipeline[component] = duration_ms
        self._current_pipeline["_last"] = now
        self.record_latency(component, duration_ms)

    def end_pipeline(self) -> Dict[str, float]:
        if "_start" not in self._current_pipeline:
            return {}

        total_ms = (time.time() - self._current_pipeline["_start"]) * 1000
        self.record_latency("total", total_ms)

        result = {k: v for k, v in self._current_pipeline.items() if not k.startswith("_")}
        result["total"] = total_ms

        self._current_pipeline = {}
        return result

    def get_avg_latency(self, component: str, window: int = 100) -> float:
        with self._lock:
            records = list(self._latencies.get(component, []))

        if not records:
            return 0.0

        recent = records[-window:]
        return sum(r.duration_ms for r in recent) / len(recent)

    def get_p95_latency(self, component: str, window: int = 100) -> float:
        with self._lock:
            records = list(self._latencies.get(component, []))

        if not records:
            return 0.0

        recent = sorted([r.duration_ms for r in records[-window:]])
        idx = int(len(recent) * 0.95)
        return recent[min(idx, len(recent) - 1)]

    def record_model_usage(self, model: str, reason: str, query_length: int = 0, success: bool = True):
        with self._lock:
            self._model_usage[model] += 1
            if success:
                self._model_success[model] += 1
            self._last_model = model
        logger.debug("Model usage: %s (%s), success=%s", model, reason, success)

    def get_model_stats(self) -> Dict:
        with self._lock:
            stats = {}
            for model, count in self._model_usage.items():
                success = self._model_success.get(model, 0)
                stats[model] = {
                    "total": count,
                    "success": success,
                    "success_rate": f"{(success/count*100):.1f}%" if count > 0 else "N/A",
                }
        return stats

    def record_error(self, category: str):
        with self._lock:
            self._errors[category] += 1
        logger.debug("Error recorded: %s", category)

    def get_error_stats(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._errors)

    def get_stats(self) -> Dict:
        with self._lock:
            total_requests = self._request_count
            total_errors = sum(self._errors.values())

        latency_stats = {}
        for component in self.PIPELINE_COMPONENTS:
            avg = self.get_avg_latency(component)
            p95 = self.get_p95_latency(component)
            if avg > 0:
                latency_stats[component] = {
                    "avg_ms": round(avg, 1),
                    "p95_ms": round(p95, 1),
                }

        return {
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate": f"{(total_errors/total_requests*100):.1f}%" if total_requests > 0 else "N/A",
            "latencies": latency_stats,
            "models": self.get_model_stats(),
            "errors": self.get_error_stats(),
        }

    def get_debug_info(self) -> Dict:
        stats = self.get_stats()
        with self._lock:
            last_model = self._last_model

        return {
            "last_model": last_model,
            "avg_total_latency_ms": stats["latencies"].get("total", {}).get("avg_ms", 0),
            "requests_handled": stats["total_requests"],
            "errors": stats["total_errors"],
        }

    def reset(self):
        with self._lock:
            self._latencies.clear()
            self._model_usage.clear()
            self._model_success.clear()
            self._errors.clear()
            self._request_count = 0
            self._last_model = "none"
        logger.info("Metrics reset")


_metrics: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """Get or create the global metrics collector."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


def reset_metrics():
    """Reset the global metrics collector (for testing)."""
    global _metrics
    _metrics = None
