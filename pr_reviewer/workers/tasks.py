"""Celery task stubs — bodies implemented in later tasks (6, 8, 16)."""

from celery import Celery

# Celery app is configured in celery_app.py (task 6); imported here to register tasks
_app = Celery("pr_reviewer")


@_app.task(name="pr_reviewer.workers.tasks.process_review_job", queue="review_jobs")
def process_review_job(payload: dict) -> None:
    raise NotImplementedError  # TODO task 8


@_app.task(name="pr_reviewer.workers.tasks.process_feedback_job", queue="feedback_jobs")
def process_feedback_job(payload: dict, event: str) -> None:
    raise NotImplementedError  # TODO task 16
