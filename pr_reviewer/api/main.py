"""FastAPI application factory."""

import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from pr_reviewer.api.health import (
    create_health_router,
    make_chromadb_probe,
    make_db_probe,
    make_redis_probe,
)
from pr_reviewer.api.webhook import limiter
from pr_reviewer.api.webhook import router as webhook_router
from pr_reviewer.telemetry import setup_telemetry


def _noop() -> None:
    pass


def build_app() -> FastAPI:
    setup_telemetry("pr-reviewer-api")
    app = FastAPI(title="PR Reviewer", version="0.1.0")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(webhook_router)

    db_probe = _noop
    redis_probe = _noop
    chromadb_probe = _noop

    if db_url := os.getenv("DATABASE_URL"):
        from sqlalchemy import create_engine  # noqa: PLC0415

        db_probe = make_db_probe(create_engine(db_url, pool_pre_ping=True))

    if redis_url := os.getenv("REDIS_URL"):
        from redis import Redis  # noqa: PLC0415

        redis_probe = make_redis_probe(Redis.from_url(redis_url, decode_responses=True))

    if chromadb_url := os.getenv("CHROMADB_URL"):
        chromadb_probe = make_chromadb_probe(chromadb_url)

    app.include_router(create_health_router(db_probe, redis_probe, chromadb_probe))
    return app


app = build_app()
