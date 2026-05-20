"""Unit tests for process_review_job task wiring."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from pr_reviewer.models.enums import JobStatus
from pr_reviewer.models.job import Job

_PAYLOAD = {
    "installation": {"id": 99},
    "repository": {"full_name": "acme/widget"},
    "pull_request": {"number": 3, "head": {"sha": "deadbeef"}},
}

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_JOB = Job(
    id=uuid.uuid4(),
    repo_id="acme/widget",
    installation_id=99,
    pr_number=3,
    commit_sha="deadbeef",
    last_reviewed_sha=None,
    status=JobStatus.queued,
    attempts=0,
    created_at=_NOW,
    updated_at=_NOW,
)


class TestProcessReviewJob:
    def test_creates_job_and_calls_processor(self) -> None:
        mock_container = MagicMock()
        mock_container.job_store.create_from_payload.return_value = _JOB
        mock_processor = MagicMock()
        mock_container.make_processor.return_value = mock_processor

        with patch(
            "pr_reviewer.workers.tasks.get_container",
            return_value=mock_container,
        ):
            from pr_reviewer.workers.tasks import process_review_job
            process_review_job(_PAYLOAD)

        mock_container.job_store.create_from_payload.assert_called_once_with(_PAYLOAD)
        mock_container.make_processor.assert_called_once_with(99)
        mock_processor.process.assert_called_once_with(_JOB)

    def test_uses_installation_id_from_payload(self) -> None:
        mock_container = MagicMock()
        mock_container.job_store.create_from_payload.return_value = _JOB

        with patch(
            "pr_reviewer.workers.tasks.get_container",
            return_value=mock_container,
        ):
            from pr_reviewer.workers.tasks import process_review_job
            process_review_job(_PAYLOAD)

        mock_container.make_processor.assert_called_once_with(99)

    def test_missing_installation_id_defaults_to_zero(self) -> None:
        payload = {**_PAYLOAD, "installation": {}}
        mock_container = MagicMock()
        mock_container.job_store.create_from_payload.return_value = _JOB

        with patch(
            "pr_reviewer.workers.tasks.get_container",
            return_value=mock_container,
        ):
            from pr_reviewer.workers.tasks import process_review_job
            process_review_job(payload)

        mock_container.make_processor.assert_called_once_with(0)
