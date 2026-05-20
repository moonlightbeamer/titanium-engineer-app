"""CodebaseIndex model — v2 codebase indexing feature (task 22)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from uuid import UUID, uuid4


class IndexScope(str, Enum):
    single = "single"
    monorepo = "monorepo"


@dataclass(frozen=True)
class CodebaseIndex:
    repo_id: str
    commit_sha: str
    content: str
    id: UUID = field(default_factory=uuid4)
    scope: IndexScope = IndexScope.single
    package_path: str | None = None
    is_valid: bool = True
    version: int = 1
    token_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
