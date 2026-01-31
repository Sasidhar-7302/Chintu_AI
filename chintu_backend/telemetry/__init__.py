"""Telemetry and observability utilities for Chintu."""

from .trace import (
    StructuredJsonFormatter,
    StructuredLogger,
    new_trace_id,
    get_trace_id,
    get_request_duration_ms,
    clear_trace,
    timed,
    setup_json_logging,
    ErrorCategory,
    categorize_error,
)
from .metrics import MetricsCollector, get_metrics, reset_metrics

__all__ = [
    "StructuredJsonFormatter",
    "StructuredLogger",
    "new_trace_id",
    "get_trace_id",
    "get_request_duration_ms",
    "clear_trace",
    "timed",
    "setup_json_logging",
    "ErrorCategory",
    "categorize_error",
    "MetricsCollector",
    "get_metrics",
    "reset_metrics",
]
