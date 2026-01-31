"""Backward-compatible logging exports (moved to chintu.telemetry)."""

from ..telemetry.trace import (
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
]
