"""Shared pytest configuration."""

import os

# Disable OTel SDK in tests to prevent GRPC exporter retry threads from
# blocking pytest exit when no collector is running.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
