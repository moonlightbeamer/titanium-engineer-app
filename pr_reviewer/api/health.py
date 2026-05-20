"""Health check endpoint — probes DB, Redis, and ChromaDB independently."""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from pr_reviewer.logging import get_logger

_logger = get_logger(__name__)


def create_health_router(
    db_probe: Callable[[], None],
    redis_probe: Callable[[], None],
    chromadb_probe: Callable[[], None],
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> JSONResponse:
        results: dict[str, str] = {}

        for key, probe in (
            ("db", db_probe),
            ("redis", redis_probe),
            ("chromadb", chromadb_probe),
        ):
            try:
                probe()
                results[key] = "ok"
            except Exception as exc:
                _logger.warning(f"Health probe '{key}' failed: {exc}")
                results[key] = "error"

        all_ok = all(v == "ok" for v in results.values())
        results["status"] = "ok" if all_ok else "degraded"
        return JSONResponse(results, status_code=200 if all_ok else 503)

    return router


# ── Default probe implementations (used by the production app) ────────────────


def make_db_probe(engine: object) -> Callable[[], None]:
    from sqlalchemy import text

    def probe() -> None:
        with engine.connect() as conn:  # type: ignore[attr-defined]
            conn.execute(text("SELECT 1"))

    return probe


def make_redis_probe(redis_client: object) -> Callable[[], None]:
    def probe() -> None:
        redis_client.ping()  # type: ignore[attr-defined]

    return probe


def make_chromadb_probe(url: str) -> Callable[[], None]:
    import httpx

    def probe() -> None:
        resp = httpx.get(f"{url}/api/v2/heartbeat", timeout=5.0)
        resp.raise_for_status()

    return probe
