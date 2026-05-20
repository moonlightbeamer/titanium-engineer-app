"""FastAPI application factory."""

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from pr_reviewer.api.health import create_health_router
from pr_reviewer.api.webhook import limiter
from pr_reviewer.api.webhook import router as webhook_router


def _noop() -> None:
    pass


def build_app() -> FastAPI:
    app = FastAPI(title="PR Reviewer", version="0.1.0")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(webhook_router)
    # Health: wire real probes via env at startup; noops keep the app runnable
    app.include_router(create_health_router(_noop, _noop, _noop))
    return app


app = build_app()
