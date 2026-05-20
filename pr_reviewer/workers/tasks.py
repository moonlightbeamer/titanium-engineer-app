"""Celery task stubs — bodies implemented in later tasks (8, 16)."""

from celery import signals
from opentelemetry import metrics

from pr_reviewer.telemetry import METRIC_QUEUE_DEPTH
from pr_reviewer.workers.celery_app import celery_app

_meter = metrics.get_meter(__name__)
_queue_depth = _meter.create_up_down_counter(METRIC_QUEUE_DEPTH)


def _on_task_prerun(task_id: str, task: object, **kwargs: object) -> None:
    queue = getattr(task, "queue", "unknown")
    _queue_depth.add(-1, {"queue": queue})


signals.task_prerun.connect(_on_task_prerun)


@celery_app.task(
    name="pr_reviewer.workers.tasks.process_review_job",
    queue="review_jobs",
    max_retries=3,
)
def process_review_job(payload: dict) -> None:
    raise NotImplementedError  # TODO task 8


@celery_app.task(
    name="pr_reviewer.workers.tasks.process_feedback_job",
    queue="feedback_jobs",
    max_retries=3,
)
def process_feedback_job(payload: dict, event: str) -> None:
    raise NotImplementedError  # TODO task 16


@celery_app.task(
    name="pr_reviewer.workers.tasks.process_indexer_job",
    queue="indexer_jobs",
    max_retries=3,
)
def process_indexer_job(payload: dict) -> None:
    raise NotImplementedError  # TODO task later
