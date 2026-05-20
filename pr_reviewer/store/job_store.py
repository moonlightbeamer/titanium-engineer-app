"""JobStore — persists and retrieves Job rows via SQLAlchemy Core."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from pr_reviewer.models.enums import JobStatus
from pr_reviewer.models.job import Job

_TABLE = sa.Table(
    "jobs",
    sa.MetaData(),
    sa.Column("id", sa.UUID(), primary_key=True),
    sa.Column("repo_id", sa.String(), nullable=False),
    sa.Column("installation_id", sa.Integer(), nullable=False),
    sa.Column("pr_number", sa.Integer(), nullable=False),
    sa.Column("commit_sha", sa.String(), nullable=False),
    sa.Column("last_reviewed_sha", sa.String(), nullable=True),
    sa.Column("status", sa.String(), nullable=False),
    sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("context_tokens_used", sa.Integer(), nullable=True),
)


class JobStore:
    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def create_from_payload(self, payload: dict) -> Job:
        installation_id = payload.get("installation", {}).get("id", 0)
        repo_id = payload.get("repository", {}).get("full_name", "")
        pr_number = payload.get("pull_request", {}).get("number", 0)
        commit_sha = payload.get("pull_request", {}).get("head", {}).get("sha", "")
        last_reviewed_sha = self._get_last_reviewed_sha(repo_id, pr_number)

        now = datetime.now(tz=UTC)
        job_id = uuid.uuid4()

        with self._engine.begin() as conn:
            conn.execute(
                _TABLE.insert().values(
                    id=job_id,
                    repo_id=repo_id,
                    installation_id=installation_id,
                    pr_number=pr_number,
                    commit_sha=commit_sha,
                    last_reviewed_sha=last_reviewed_sha,
                    status=str(JobStatus.queued),
                    attempts=0,
                    created_at=now,
                    updated_at=now,
                )
            )

        return Job(
            id=job_id,
            repo_id=repo_id,
            installation_id=installation_id,
            pr_number=pr_number,
            commit_sha=commit_sha,
            last_reviewed_sha=last_reviewed_sha,
            status=JobStatus.queued,
            attempts=0,
            created_at=now,
            updated_at=now,
        )

    def _get_last_reviewed_sha(self, repo_id: str, pr_number: int) -> str | None:
        stmt = (
            sa.select(_TABLE.c.commit_sha)
            .where(_TABLE.c.repo_id == repo_id)
            .where(_TABLE.c.pr_number == pr_number)
            .where(_TABLE.c.status == str(JobStatus.complete))
            .order_by(_TABLE.c.updated_at.desc())
            .limit(1)
        )
        with self._engine.connect() as conn:
            row = conn.execute(stmt).fetchone()
        return row[0] if row else None

    def update_status(self, job_id: UUID, status: JobStatus) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                _TABLE.update()
                .where(_TABLE.c.id == job_id)
                .values(status=str(status), updated_at=datetime.now(tz=UTC))
            )

    def update_success(self, job_id: UUID, commit_sha: str, context_tokens: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                _TABLE.update()
                .where(_TABLE.c.id == job_id)
                .values(
                    status=str(JobStatus.complete),
                    commit_sha=commit_sha,
                    context_tokens_used=context_tokens,
                    updated_at=datetime.now(tz=UTC),
                )
            )
