"""OpenTelemetry setup: TracerProvider, MeterProvider, and golden signal instruments."""

import logging
import os

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Golden signal metric names — referenced by other modules
METRIC_REVIEW_DURATION = "review.duration_ms"
METRIC_JOBS_STARTED = "review.jobs_started"
METRIC_ERRORS = "review.errors"
METRIC_QUEUE_DEPTH = "review.queue_depth"
METRIC_TOOL_BUDGET_USED = "review.tool_budget_used"
METRIC_KB_RETRIEVAL_LATENCY = "kb.retrieval_latency_ms"
METRIC_KB_RETRIEVAL_RELEVANCE = "kb.retrieval_relevance"

_initialized = False


def setup_telemetry(service_name: str) -> None:
    """Initialize TracerProvider and MeterProvider; apply log level from env."""
    global _initialized

    _configure_log_level()
    _setup_tracer(service_name)
    _setup_meter(service_name)
    _initialized = True


def _configure_log_level() -> None:
    raw = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, raw, logging.INFO)
    logging.getLogger().setLevel(level)


def _setup_tracer(service_name: str) -> None:
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    # HTTP/protobuf exporter: endpoint must include the signal path.
    # ACA proxies port 80 → 4318 on the collector container; path is preserved.
    base = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318").rstrip("/")
    try:
        exporter = OTLPSpanExporter(endpoint=f"{base}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
    except Exception:  # noqa: S110
        logging.getLogger(__name__).debug("OTLP trace exporter unavailable")

    trace.set_tracer_provider(provider)


def _setup_meter(service_name: str) -> None:
    resource = Resource.create({"service.name": service_name})
    base = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318").rstrip("/")

    readers = []
    try:
        exporter = OTLPMetricExporter(endpoint=f"{base}/v1/metrics")
        readers.append(PeriodicExportingMetricReader(exporter, export_interval_millis=15_000))
    except Exception:  # noqa: S110
        logging.getLogger(__name__).debug("OTLP metric exporter unavailable")

    provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(provider)

    meter = metrics.get_meter(service_name)

    # Declare all golden signal instruments so they exist from startup
    meter.create_histogram(METRIC_REVIEW_DURATION, unit="ms", description="PR review job duration")
    meter.create_counter(METRIC_JOBS_STARTED, description="Review jobs started")
    meter.create_counter(METRIC_ERRORS, description="Review pipeline errors by type")
    meter.create_up_down_counter(METRIC_QUEUE_DEPTH, description="Current review queue depth")
    meter.create_histogram(METRIC_TOOL_BUDGET_USED, description="Tool budget consumed per job")
    meter.create_histogram(
        METRIC_KB_RETRIEVAL_LATENCY, unit="ms", description="KB retrieval latency"
    )
    meter.create_histogram(
        METRIC_KB_RETRIEVAL_RELEVANCE, description="KB retrieval relevance score"
    )
