"""CodebaseIndex model — stub for v2 codebase indexing feature (task 22)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CodebaseIndex:
    repo_id: str
    commit_sha: str
    content: str = ""
    package_path: str | None = None
    is_valid: bool = True
