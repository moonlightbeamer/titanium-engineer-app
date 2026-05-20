"""WebhookReceiver — POST /webhook/github."""

import hashlib
import hmac
import json
import os
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from opentelemetry import metrics
from slowapi import Limiter

from pr_reviewer.logging import get_logger
from pr_reviewer.telemetry import METRIC_QUEUE_DEPTH
from pr_reviewer.workers.tasks import process_feedback_job, process_review_job

router = APIRouter()
_logger = get_logger(__name__)
_meter = metrics.get_meter(__name__)
_queue_depth = _meter.create_up_down_counter(METRIC_QUEUE_DEPTH)


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


limiter = Limiter(key_func=_get_client_ip, storage_uri="memory://")


def _verify_signature(body: bytes, header: str, secret: str) -> None:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(), header.encode()):
        raise HTTPException(status_code=401, detail="Invalid signature")


@router.post("/webhook/github", status_code=202)
@limiter.limit("100/minute")
async def github_webhook(
    request: Request,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
    x_github_event: Annotated[str | None, Header()] = None,
) -> dict:
    if x_hub_signature_256 is None:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256")

    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    body = await request.body()
    _verify_signature(body, x_hub_signature_256, secret)

    review_draft_prs = os.getenv("REVIEW_DRAFT_PRS", "false").lower() == "true"

    if x_github_event == "pull_request":
        payload = json.loads(body)
        action = payload.get("action", "")
        if action not in ("opened", "synchronize", "reopened"):
            return {"status": "ignored"}

        if payload.get("pull_request", {}).get("draft") and not review_draft_prs:
            _logger.info("Skipping draft PR")
            return {"status": "draft_skipped"}

        process_review_job.apply_async(kwargs={"payload": payload}, queue="review_jobs")
        _queue_depth.add(1, {"queue": "review_jobs"})

    elif x_github_event in ("pull_request_review_comment", "pull_request_review"):
        payload = json.loads(body)
        process_feedback_job.apply_async(
            kwargs={"payload": payload, "event": x_github_event}, queue="feedback_jobs"
        )
        _queue_depth.add(1, {"queue": "feedback_jobs"})

    else:
        return JSONResponse(content={"status": "ignored"}, status_code=200)

    return {"status": "accepted"}
