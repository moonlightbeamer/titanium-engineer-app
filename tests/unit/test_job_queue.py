"""Unit tests for JobQueue / Celery configuration (tasks 6.1–6.8)."""

from unittest.mock import MagicMock, patch

import pytest

# ── Task 6.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_review_task_routes_to_review_jobs_queue():
    from pr_reviewer.workers.tasks import process_review_job

    assert process_review_job.queue == "review_jobs"


# ── Task 6.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_feedback_task_routes_to_feedback_jobs_queue():
    from pr_reviewer.workers.tasks import process_feedback_job

    assert process_feedback_job.queue == "feedback_jobs"


# ── Task 6.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_indexer_task_routes_to_indexer_jobs_queue():
    from pr_reviewer.workers.tasks import process_indexer_job

    assert process_indexer_job.queue == "indexer_jobs"


# ── Task 6.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_review_jobs_max_10_concurrent():
    from pr_reviewer.workers.celery_app import REVIEW_JOBS_CONCURRENCY

    assert REVIEW_JOBS_CONCURRENCY == 10


# ── Task 6.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_task_retried_up_to_3_times_on_failure():
    from pr_reviewer.workers.tasks import process_review_job

    assert process_review_job.max_retries == 3


# ── Task 6.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_dead_letter_status_set_after_exhausted_retries():
    from celery import signals

    from pr_reviewer.workers.celery_app import _handle_task_failure  # noqa: F401

    # Verify task_failure signal has our handler connected
    receiver_funcs = [ref() for (_, ref) in signals.task_failure.receivers if ref() is not None]

    assert _handle_task_failure in receiver_funcs


# ── Task 6.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.workers.celery_app.GitHubAPIClient")
@patch("pr_reviewer.workers.celery_app._get_job")
def test_failure_comment_posted_on_dead_letter(mock_get_job, mock_client_cls):
    from pr_reviewer.workers.celery_app import _handle_task_failure

    mock_job = MagicMock()
    mock_job.installation_id = 99
    mock_job.repo_full_name = "org/repo"
    mock_job.pr_number = 5
    mock_get_job.return_value = mock_job

    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    _handle_task_failure(
        task_id="tid-1",
        exception=RuntimeError("boom"),
        traceback=None,
        einfo=None,
        args=(),
        kwargs={
            "payload": {
                "installation": {"id": 99},
                "repository": {"full_name": "org/repo"},
                "pull_request": {"number": 5},
            }
        },
        sender=MagicMock(max_retries=3, request=MagicMock(retries=3)),
    )

    mock_client.post_review.assert_called_once()
    call_args = mock_client.post_review.call_args
    body_arg = call_args.kwargs.get("body") or call_args.args[2]
    assert "error" in body_arg.lower() or "failed" in body_arg.lower()


# ── Task 6.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.workers.tasks._queue_depth")
def test_queue_depth_gauge_decremented_on_task_start(mock_gauge):
    from pr_reviewer.workers.tasks import _on_task_prerun

    _on_task_prerun(task_id="t1", task=MagicMock(queue="review_jobs"))
    mock_gauge.add.assert_called_once_with(-1, {"queue": "review_jobs"})
