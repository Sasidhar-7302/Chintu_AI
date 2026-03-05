"""
Structured JSON logging and trace utilities for Chintu.

Provides:
- JSON-formatted logs for easy parsing
- Trace IDs for correlating logs across a request
- Component-level timing
- Error categorization
"""

import logging
import json
import uuid
import time
import os
import re
from datetime import datetime, timezone
from typing import Optional
from contextvars import ContextVar
from functools import wraps

trace_id: ContextVar[str] = ContextVar("trace_id", default="")
request_start: ContextVar[float] = ContextVar("request_start", default=0.0)


class SecretRedactionFilter(logging.Filter):
    """Redact known secret formats from log output."""

    _GENERIC_TELEGRAM_TOKEN = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,80}\b")
    _BOT_URL_TOKEN = re.compile(r"bot(\d{8,12}:[A-Za-z0-9_-]{30,80})")

    def __init__(self) -> None:
        super().__init__()
        self._literal_secrets = []
        for key in ("TELEGRAM_BOT_TOKEN", "GROQ_API_KEY", "GOOGLE_AI_KEY", "DEEPSEEK_API_KEY", "NVIDIA_API_KEY"):
            value = str(os.environ.get(key, "") or "").strip()
            if value:
                self._literal_secrets.append(value)

    def _redact(self, value: str) -> str:
        if not value:
            return value

        redacted = value
        for secret in self._literal_secrets:
            redacted = redacted.replace(secret, "[REDACTED_SECRET]")
        redacted = self._GENERIC_TELEGRAM_TOKEN.sub("[REDACTED_TELEGRAM_TOKEN]", redacted)
        redacted = self._BOT_URL_TOKEN.sub("bot[REDACTED_TELEGRAM_TOKEN]", redacted)
        return redacted

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            cleaned = self._redact(message)
            if cleaned != message:
                record.msg = cleaned
                record.args = ()
        except Exception:
            pass
        return True


class StructuredJsonFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.

    Output format:
    {
        "timestamp": "2026-01-05T19:30:00.000Z",
        "level": "INFO",
        "logger": "chintu_backend.core.model_router",
        "message": "Routed to Groq",
        "trace_id": "a1b2c3d4",
        "extra": {...}
    }
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        tid = trace_id.get("")
        if tid:
            log_data["trace_id"] = tid

        if hasattr(record, "extra") and record.extra:
            log_data["extra"] = record.extra

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        if record.levelno >= logging.ERROR:
            log_data["location"] = f"{record.filename}:{record.lineno}"

        return json.dumps(log_data)


class StructuredLogger:
    """
    Wrapper around standard logger with structured logging support.

    Usage:
        log = StructuredLogger("chintu_backend.core")
        log.info("Processing request", query="hello", model="groq")
    """

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _log(self, level: int, message: str, **kwargs):
        extra = kwargs if kwargs else None
        record = self._logger.makeRecord(
            self._logger.name, level, "", 0, message, (), None
        )
        if extra:
            record.extra = extra
        self._logger.handle(record)

    def debug(self, message: str, **kwargs):
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log(logging.ERROR, message, **kwargs)

    def exception(self, message: str, **kwargs):
        self._log(logging.ERROR, message, **kwargs)


def new_trace_id() -> str:
    """Generate a new trace ID for a request."""
    tid = uuid.uuid4().hex[:8]
    trace_id.set(tid)
    request_start.set(time.time())
    return tid


def get_trace_id() -> str:
    """Get current trace ID."""
    return trace_id.get("")


def get_request_duration_ms() -> float:
    """Get duration since request start in milliseconds."""
    start = request_start.get(0.0)
    if start == 0.0:
        return 0.0
    return (time.time() - start) * 1000


def clear_trace():
    """Clear trace context (call after request completes)."""
    trace_id.set("")
    request_start.set(0.0)


def timed(component_name: str):
    """
    Decorator to time a function and log its duration.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000
                logging.getLogger(f"chintu_backend.timing.{component_name}").debug(
                    "%s completed in %.1fms", func.__name__, duration_ms
                )
                try:
                    from .metrics import get_metrics
                    get_metrics().record_latency(component_name, duration_ms)
                except Exception:
                    pass
                return result
            except Exception as exc:
                duration_ms = (time.time() - start) * 1000
                logging.getLogger(f"chintu_backend.timing.{component_name}").error(
                    "%s failed after %.1fms: %s", func.__name__, duration_ms, exc
                )
                raise
        return wrapper

    return decorator


class WebSocketLogHandler(logging.Handler):
    """Logging handler that broadcasts logs to UI via WebSocket."""
    
    def emit(self, record):
        try:
            from chintu_backend.core.websocket_server import get_ws_server
            ws = get_ws_server()
            if ws and ws._running:
                log_entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
                
                tid = trace_id.get("")
                if tid:
                    log_entry["trace_id"] = tid
                    
                # Schedule broadcast on the event loop
                import asyncio
                if ws._loop:
                    if ws._loop.is_running():
                        try:
                            if asyncio.get_event_loop() == ws._loop:
                                asyncio.create_task(ws.broadcast_log(log_entry))
                            else:
                                ws._loop.call_soon_threadsafe(
                                    lambda: asyncio.create_task(ws.broadcast_log(log_entry))
                                )
                        except RuntimeError:
                            ws._loop.call_soon_threadsafe(
                                lambda: asyncio.create_task(ws.broadcast_log(log_entry))
                            )
        except Exception:
            pass # Silent fail to avoid infinite logging loops


def setup_json_logging(level: int = logging.INFO, log_file: Optional[str] = None):
    """
    Setup JSON logging for the application.

    Args:
        level: Log level (default INFO)
        log_file: Optional file path for logs
    """
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    secret_filter = SecretRedactionFilter()

    try:
        import sys
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        console = logging.StreamHandler(stream=sys.stdout)
    except Exception:
        console = logging.StreamHandler()
    # console.setFormatter(StructuredJsonFormatter())
    # Use human-readable format for console
    console.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))
    console.addFilter(secret_filter)
    root.addHandler(console)

    if log_file:
        from pathlib import Path
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(StructuredJsonFormatter())
        file_handler.addFilter(secret_filter)
        root.addHandler(file_handler)

    # Add WebSocket handler for UI log streaming
    ws_handler = WebSocketLogHandler()
    ws_handler.setLevel(level)
    ws_handler.addFilter(secret_filter)
    root.addHandler(ws_handler)

    # Quiet noisy transport logs that can leak full request URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)

    logging.getLogger("chintu").info("Structured JSON logging configured (with WebSocket streaming)")


class ErrorCategory:
    """Error categories for metrics."""

    NETWORK = "network"
    API_RATE_LIMIT = "api_rate_limit"
    API_ERROR = "api_error"
    CAPABILITY_ERROR = "capability_error"
    AUDIO_ERROR = "audio_error"
    STT_ERROR = "stt_error"
    TTS_ERROR = "tts_error"
    MEMORY_ERROR = "memory_error"
    BROWSER_ERROR = "browser_error"
    UNKNOWN = "unknown"


def categorize_error(exception: Exception) -> str:
    """
    Categorize an exception for metrics.

    Args:
        exception: The exception to categorize

    Returns:
        ErrorCategory string
    """
    error_str = str(exception).lower()

    if any(x in error_str for x in ["connection", "timeout", "network", "socket", "dns", "resolve"]):
        return ErrorCategory.NETWORK

    if any(x in error_str for x in ["rate limit", "ratelimit", "429", "too many"]):
        return ErrorCategory.API_RATE_LIMIT

    if any(x in error_str for x in ["api", "401", "403", "500", "502", "503"]):
        return ErrorCategory.API_ERROR

    if any(x in error_str for x in ["audio", "microphone", "sounddevice"]):
        return ErrorCategory.AUDIO_ERROR

    if any(x in error_str for x in ["whisper", "transcri", "speech"]):
        return ErrorCategory.STT_ERROR

    if any(x in error_str for x in ["tts", "edge-tts", "speak"]):
        return ErrorCategory.TTS_ERROR

    if any(x in error_str for x in ["chroma", "sqlite", "memory", "database"]):
        return ErrorCategory.MEMORY_ERROR

    if any(x in error_str for x in ["playwright", "browser", "page"]):
        return ErrorCategory.BROWSER_ERROR

    return ErrorCategory.UNKNOWN
