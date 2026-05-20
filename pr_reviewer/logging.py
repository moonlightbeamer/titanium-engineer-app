"""Structured JSON logger with trace injection and error deduplication."""

import contextvars
import json
import logging
import time
from typing import Any

from opentelemetry import trace

# Context variables for per-request correlation
_job_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("job_id", default="")
_repo_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("repo_id", default="")


def set_log_context(job_id: str = "", repo_id: str = "") -> None:
    _job_id_var.set(job_id)
    _repo_id_var.set(repo_id)


class _TraceInjectingFilter(logging.Filter):
    """Inject trace_id, span_id, job_id, repo_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            record.trace_id = format(ctx.trace_id, "032x")
            record.span_id = format(ctx.span_id, "016x")
        else:
            record.trace_id = "0" * 32
            record.span_id = "0" * 16
        record.job_id = _job_id_var.get()
        record.repo_id = _repo_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": getattr(record, "trace_id", ""),
            "span_id": getattr(record, "span_id", ""),
            "job_id": getattr(record, "job_id", ""),
            "repo_id": getattr(record, "repo_id", ""),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


class RateLimitedLogger:
    """Logger that deduplicates identical error messages within a 60-second window."""

    _DEDUP_WINDOW = 60.0

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(_JsonFormatter())
            handler.addFilter(_TraceInjectingFilter())
            self._logger.addHandler(handler)
        self._seen: dict[str, float] = {}

    def _should_emit(self, msg: str) -> bool:
        now = time.monotonic()
        last = self._seen.get(msg)
        if last is None or (now - last) >= self._DEDUP_WINDOW:
            self._seen[msg] = now
            return True
        return False

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._logger.debug(msg, **kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._logger.info(msg, **kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._logger.warning(msg, **kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        if self._should_emit(msg):
            self._logger.error(msg, **kwargs)

    def critical(self, msg: str, **kwargs: Any) -> None:
        self._logger.critical(msg, **kwargs)


_loggers: dict[str, RateLimitedLogger] = {}


def get_logger(name: str) -> RateLimitedLogger:
    if name not in _loggers:
        _loggers[name] = RateLimitedLogger(name)
    return _loggers[name]
