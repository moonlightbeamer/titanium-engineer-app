"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from pr_reviewer.api.webhook import limiter
from pr_reviewer.api.webhook import router as webhook_router


def build_app() -> FastAPI:
    app = FastAPI(title="PR Reviewer", version="0.1.0")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(webhook_router)

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return app


app = build_app()
