"""Job domain model."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pr_reviewer.models.enums import JobStatus


@dataclass(frozen=True)
class Job:
    id: UUID
    repo_id: str
    installation_id: int
    pr_number: int
    commit_sha: str
    last_reviewed_sha: str | None
    status: JobStatus
    attempts: int
    created_at: datetime
    updated_at: datetime
    context_tokens_used: int | None = None
