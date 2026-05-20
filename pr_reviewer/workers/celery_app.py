"""Celery application with queue configuration and dead-letter handling."""

import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from celery import Celery, signals

from pr_reviewer.logging import get_logger
from pr_reviewer.store.github_client import GitHubAPIClient

REVIEW_JOBS_CONCURRENCY = 10
FEEDBACK_JOBS_CONCURRENCY = 5
INDEXER_JOBS_CONCURRENCY = 2

_logger = get_logger(__name__)

celery_app = Celery(
    "pr_reviewer",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    include=[
        "pr_reviewer.workers.tasks",
        "pr_reviewer.workers.feedback_processor",
        "pr_reviewer.workers.indexer",
    ],
)

celery_app.conf.update(
    task_acks_late=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_routes={
        "pr_reviewer.workers.tasks.process_review_job": {"queue": "review_jobs"},
        "pr_reviewer.workers.tasks.process_feedback_job": {"queue": "feedback_jobs"},
        "pr_reviewer.workers.indexer.run_index_refresh_task": {"queue": "indexer_jobs"},
    },
    # Per-queue concurrency is set via --concurrency on each worker process;
    # worker_concurrency must be an int, not a per-queue dict.
    worker_concurrency=REVIEW_JOBS_CONCURRENCY,
)


def _get_job(payload: dict) -> Any:
    """Look up a job record from the payload. Returns None if not found."""
    return None


def _handle_task_failure(
    task_id: str,
    exception: Exception,
    traceback: Any,
    einfo: Any,
    args: tuple,
    kwargs: dict,
    sender: Any,
    **kw: Any,
) -> None:
    if sender.request.retries < sender.max_retries:
        return

    payload = kwargs.get("payload", {})
    installation_id = payload.get("installation", {}).get("id")
    repo_full_name = payload.get("repository", {}).get("full_name")
    pr_number = payload.get("pull_request", {}).get("number")

    _logger.error(
        f"Task dead-lettered: task_id={task_id} repo={repo_full_name}"
        f" pr={pr_number} exc={exception!s}"
    )

    _get_job(payload)  # future: update job.status = dead_letter

    if not all([installation_id, repo_full_name, pr_number]):
        return

    try:
        from redis import Redis  # noqa: PLC0415

        client = GitHubAPIClient(
            installation_id=installation_id,
            redis_client=Redis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
            ),
            app_id=os.environ["GITHUB_APP_ID"],
            private_key=os.environ["GITHUB_APP_PRIVATE_KEY"],
        )
        client.post_review(
            repo=repo_full_name,
            pr_number=pr_number,
            body="Review job failed after maximum retries. Please check the service logs.",
            event="COMMENT",
            comments=[],
        )
    except Exception as notify_err:
        _logger.error(f"Dead-letter GitHub notify failed: {notify_err}")


signals.task_failure.connect(_handle_task_failure)


@signals.worker_process_init.connect
def _setup_worker_telemetry(**_kwargs: Any) -> None:
    from pr_reviewer.telemetry import setup_telemetry  # noqa: PLC0415

    setup_telemetry("pr-reviewer-worker")
