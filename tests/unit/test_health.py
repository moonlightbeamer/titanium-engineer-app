"""Unit tests for health check endpoint (task 17)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(
    *,
    db_raises: bool = False,
    redis_raises: bool = False,
    chromadb_raises: bool = False,
) -> TestClient:
    from pr_reviewer.api.health import create_health_router

    def db_probe() -> None:
        if db_raises:
            raise RuntimeError("db connection failed")

    def redis_probe() -> None:
        if redis_raises:
            raise RuntimeError("redis ping failed")

    def chromadb_probe() -> None:
        if chromadb_raises:
            raise RuntimeError("chromadb heartbeat failed")

    app = FastAPI()
    app.include_router(create_health_router(db_probe, redis_probe, chromadb_probe))
    return TestClient(app)


# ── Task 17.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_health_200_when_all_deps_reachable():
    """All probes succeed → 200 with all statuses 'ok'."""
    resp = _make_client().get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok", "redis": "ok", "chromadb": "ok"}


# ── Task 17.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_health_503_when_postgres_down():
    """DB probe raises → 503 with 'db': 'error'."""
    resp = _make_client(db_raises=True).get("/health")
    assert resp.status_code == 503
    assert resp.json()["db"] == "error"


# ── Task 17.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_health_checks_each_dependency_independently():
    """DB down, Redis up → both statuses present independently."""
    resp = _make_client(db_raises=True).get("/health")
    body = resp.json()
    assert body["db"] == "error"
    assert body["redis"] == "ok"
    assert body["chromadb"] == "ok"


# ── Task 17.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_health_status_field_ok_only_when_all_ok():
    """Any one dependency down → top-level 'status' is 'degraded'."""
    resp = _make_client(chromadb_raises=True).get("/health")
    assert resp.json()["status"] == "degraded"
