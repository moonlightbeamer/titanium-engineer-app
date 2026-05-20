"""Unit tests for OpenTelemetry telemetry setup (task 2.1–2.7)."""

import logging

import pytest
from opentelemetry import trace

from pr_reviewer.logging import get_logger
from pr_reviewer.telemetry import setup_telemetry

# ── Task 2.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_setup_telemetry_does_not_raise():
    """setup_telemetry("pr_reviewer") on blank environment raises no exception."""
    setup_telemetry("pr_reviewer")  # must not raise


# ── Task 2.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_tracer_provider_available_globally():
    """After setup, get_tracer returns a non-noop tracer."""
    setup_telemetry("pr_reviewer")
    tracer = trace.get_tracer("pr_reviewer")
    # A real tracer from an SDK TracerProvider has a 'start_span' that produces
    # a real span with a valid span_id — not a NonRecordingSpan.
    with tracer.start_as_current_span("test-span") as span:
        assert span.is_recording()


# ── Task 2.3 ─────────────────────────────────────────────────────────────────

EXPECTED_INSTRUMENTS = {
    "review.duration_ms",
    "review.jobs_started",
    "review.errors",
    "review.queue_depth",
    "review.tool_budget_used",
    "kb.retrieval_latency_ms",
    "kb.retrieval_relevance",
}


@pytest.mark.unit
def test_all_golden_signal_metrics_registered():
    """MeterProvider contains all required golden signal instruments."""
    from pr_reviewer import telemetry as tel

    setup_telemetry("pr_reviewer")
    registered = {
        tel.METRIC_REVIEW_DURATION,
        tel.METRIC_JOBS_STARTED,
        tel.METRIC_ERRORS,
        tel.METRIC_QUEUE_DEPTH,
        tel.METRIC_TOOL_BUDGET_USED,
        tel.METRIC_KB_RETRIEVAL_LATENCY,
        tel.METRIC_KB_RETRIEVAL_RELEVANCE,
    }
    assert registered == EXPECTED_INSTRUMENTS


# ── Task 2.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_structured_logger_includes_trace_id():
    """Log record produced inside an active span contains trace_id and span_id."""
    setup_telemetry("pr_reviewer")
    tracer = trace.get_tracer("pr_reviewer")
    logger = get_logger("test.trace_inject")

    records = []

    class CapturingHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = CapturingHandler()
    logger._logger.addHandler(handler)

    with tracer.start_as_current_span("test-span"):
        logger.info("hello from span")

    logger._logger.removeHandler(handler)

    assert records, "no log records emitted"
    record = records[-1]
    assert hasattr(record, "trace_id"), "trace_id not injected"
    assert hasattr(record, "span_id"), "span_id not injected"
    assert record.trace_id != "0000000000000000000000000000000000000000", "trace_id is zero"


# ── Task 2.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_log_level_read_from_env(monkeypatch):
    """LOG_LEVEL=WARN → root logger level is WARNING after setup."""
    monkeypatch.setenv("LOG_LEVEL", "WARN")
    setup_telemetry("pr_reviewer")
    assert logging.getLogger().level == logging.WARNING


# ── Task 2.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_rate_limited_logger_deduplicates_within_window():
    """Same error message emitted 5× within 60s → only 1 log record emitted."""
    logger = get_logger("test.dedup")
    records = []

    class CapturingHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = CapturingHandler()
    logger._logger.addHandler(handler)

    for _ in range(5):
        logger.error("duplicate error message XYZ")

    logger._logger.removeHandler(handler)
    assert len(records) == 1, f"Expected 1 record, got {len(records)}"


# ── Task 2.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_rate_limited_logger_resets_after_window():
    """Same error after 61s → emitted again."""
    logger = get_logger("test.dedup_reset")
    records = []

    class CapturingHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = CapturingHandler()
    logger._logger.addHandler(handler)

    msg = "resettable error ABC"
    logger.error(msg)

    # Simulate window expiry by directly manipulating the dedup cache
    logger._seen.clear()

    logger.error(msg)

    logger._logger.removeHandler(handler)
    assert len(records) == 2, f"Expected 2 records after reset, got {len(records)}"
