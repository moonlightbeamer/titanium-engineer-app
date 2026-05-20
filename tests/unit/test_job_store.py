"""Unit tests for JobStore."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, call, patch

import pytest
import sqlalchemy as sa

from pr_reviewer.models.enums import JobStatus
from pr_reviewer.store.job_store import JobStore

_PAYLOAD = {
    "installation": {"id": 42},
    "repository": {"full_name": "org/repo"},
    "pull_request": {
        "number": 7,
        "head": {"sha": "abc123"},
    },
}


def _make_engine() -> MagicMock:
    engine = MagicMock(spec=sa.Engine)
    conn = MagicMock()
    engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    connect_ctx = MagicMock()
    connect_ctx.__enter__ = MagicMock(return_value=conn)
    connect_ctx.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value = connect_ctx
    return engine, conn


class TestCreateFromPayload:
    def test_returns_job_with_payload_fields(self) -> None:
        engine, conn = _make_engine()
        conn.execute.return_value.fetchone.return_value = None

        store = JobStore(engine)
        job = store.create_from_payload(_PAYLOAD)

        assert job.repo_id == "org/repo"
        assert job.installation_id == 42
        assert job.pr_number == 7
        assert job.commit_sha == "abc123"
        assert job.status == JobStatus.queued
        assert job.attempts == 0

    def test_last_reviewed_sha_set_when_previous_complete_exists(self) -> None:
        engine, conn = _make_engine()
        conn.execute.return_value.fetchone.return_value = ("prev_sha",)

        store = JobStore(engine)
        job = store.create_from_payload(_PAYLOAD)

        assert job.last_reviewed_sha == "prev_sha"

    def test_last_reviewed_sha_none_for_first_pr(self) -> None:
        engine, conn = _make_engine()
        conn.execute.return_value.fetchone.return_value = None

        store = JobStore(engine)
        job = store.create_from_payload(_PAYLOAD)

        assert job.last_reviewed_sha is None

    def test_job_id_is_unique_per_call(self) -> None:
        engine, conn = _make_engine()
        conn.execute.return_value.fetchone.return_value = None

        store = JobStore(engine)
        job1 = store.create_from_payload(_PAYLOAD)
        job2 = store.create_from_payload(_PAYLOAD)

        assert job1.id != job2.id

    def test_missing_payload_fields_produce_safe_defaults(self) -> None:
        engine, conn = _make_engine()
        conn.execute.return_value.fetchone.return_value = None

        store = JobStore(engine)
        job = store.create_from_payload({})

        assert job.repo_id == ""
        assert job.installation_id == 0
        assert job.pr_number == 0
        assert job.commit_sha == ""


class TestUpdateStatus:
    def test_update_status_executes_update(self) -> None:
        engine, conn = _make_engine()
        job_id = uuid.uuid4()

        store = JobStore(engine)
        store.update_status(job_id, JobStatus.failed)

        assert conn.execute.called

    def test_update_status_processing(self) -> None:
        engine, conn = _make_engine()
        store = JobStore(engine)
        store.update_status(uuid.uuid4(), JobStatus.processing)
        assert conn.execute.called


class TestUpdateSuccess:
    def test_update_success_executes_update(self) -> None:
        engine, conn = _make_engine()
        job_id = uuid.uuid4()

        store = JobStore(engine)
        store.update_success(job_id, "newsha", 1500)

        assert conn.execute.called
