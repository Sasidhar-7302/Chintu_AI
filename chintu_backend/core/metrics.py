"""Backward-compatible metrics exports (moved to chintu.telemetry)."""

from ..telemetry.metrics import MetricsCollector, get_metrics, reset_metrics

__all__ = [
    "MetricsCollector",
    "get_metrics",
    "reset_metrics",
]
