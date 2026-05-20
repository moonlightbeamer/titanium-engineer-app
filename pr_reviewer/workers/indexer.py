"""Indexer — builds and refreshes CodebaseIndex for a repository."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from celery.schedules import crontab

from pr_reviewer.logging import get_logger
from pr_reviewer.models.codebase_index import CodebaseIndex, IndexScope
from pr_reviewer.workers.celery_app import celery_app

if TYPE_CHECKING:
    from pr_reviewer.config.schema import Config

_logger = get_logger(__name__)

_MANIFEST_FILES = frozenset({"package.json", "pyproject.toml", "go.mod", "Cargo.toml"})
_LAST_REFRESH_KEY_PREFIX = "index_last_refresh:"
_WEEKLY_REFRESH_DAYS = 7
_SAMPLE_FILE_COUNT = 20
_MIN_SIGNALS_FOR_DENSITY = 10
_DEFAULT_MAX_TOKENS = 8_000
_KEEP_VERSIONS = 3

# Celery Beat schedule
BEAT_SCHEDULE: dict = {
    "run_index_refresh_daily": {
        "task": "pr_reviewer.workers.indexer.run_index_refresh_task",
        "schedule": crontab(hour=2, minute=0),
        "kwargs": {},
    }
}

celery_app.conf.beat_schedule = BEAT_SCHEDULE


# ── Public helpers (importable for unit tests) ────────────────────────────────


def _build_convention_profile(files_content: dict[str, str]) -> dict[str, float]:
    """Return patterns present in ≥60% of files."""
    total = len(files_content)
    if total == 0:
        return {}

    candidate_patterns = ["camelCase", "snake_case", "PascalCase", "kebab-case"]
    profile: dict[str, float] = {}
    for pattern in candidate_patterns:
        count = sum(1 for content in files_content.values() if pattern in content)
        ratio = count / total
        if ratio >= 0.60:
            profile[pattern] = ratio
    return profile


def _build_finding_density_map(
    signal_count: int,
    raw_signals: list[dict] | None = None,
) -> dict | None:
    """Return density map if signal_count >= 10, else None."""
    if signal_count < _MIN_SIGNALS_FOR_DENSITY:
        _logger.warning(
            f"insufficient signal: {signal_count}, need {_MIN_SIGNALS_FOR_DENSITY}"
        )
        return None
    # Build simple density map from raw signals if provided
    if raw_signals:
        density: dict[str, int] = {}
        for sig in raw_signals:
            path = sig.get("file_path_pattern", "")
            density[path] = density.get(path, 0) + 1
        return density
    return {}


def _trim_to_token_limit(content: str, max_tokens: int) -> tuple[str, int]:
    """Trim content so token_count (≈ len/4) <= max_tokens."""
    max_chars = max_tokens * 4
    trimmed = content[:max_chars]
    token_count = len(trimmed) // 4
    return trimmed, token_count


def _detect_monorepo(github_client: Any, repo: str, depth: int = 2) -> list[str]:
    """Detect package roots by looking for manifest files in subdirectories."""
    packages: list[str] = []

    def _scan(path: str, current_depth: int) -> None:
        if current_depth < 0:
            return
        try:
            entries = github_client.list_directory(path=path)
        except Exception:
            return
        for entry in entries:
            if entry.get("type") == "file" and entry.get("name") in _MANIFEST_FILES:
                parent = "/".join(entry["path"].split("/")[:-1])
                if parent and parent != ".":
                    packages.append(parent)
                return
            if entry.get("type") == "dir":
                _scan(entry["path"], current_depth - 1)

    _scan(".", depth)
    return list(dict.fromkeys(packages))  # deduplicate preserving order


def _prune_old_versions(store: Any, repo_id: str, keep: int = _KEEP_VERSIONS) -> None:
    """Invalidate all but the last `keep` versions; never delete rows."""
    versions = store.list_versions(repo_id)
    if not versions:
        return
    sorted_versions = sorted(versions, key=lambda v: v.version, reverse=True)
    for old in sorted_versions[keep:]:
        store.invalidate_version(repo_id, old.version)


def _make_indexer_github_client(
    installation_id: int,
    redis_client: Any,
    app_id: str = "",
    private_key: str = "",
) -> Any:
    """Create a GitHubAPIClient with a dedicated ':indexer' rate-limit key."""
    import os

    from pr_reviewer.store.github_client import GitHubAPIClient

    client = GitHubAPIClient(
        installation_id=installation_id,
        redis_client=redis_client,
        app_id=app_id or os.getenv("GITHUB_APP_ID", ""),
        private_key=private_key or os.getenv("GITHUB_APP_PRIVATE_KEY", ""),
    )
    client._rate_limit_key = f"{installation_id}:indexer"
    client._redis_key_suffix = "indexer"
    return client


# ── Indexer class ─────────────────────────────────────────────────────────────


class Indexer:
    def __init__(
        self,
        github_client: Any,
        db_engine: Any,
        index_store: Any,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        config: "Config | None" = None,
    ) -> None:
        self._github_client = github_client
        self._db_engine = db_engine
        self._index_store = index_store
        self._max_tokens = max_tokens
        self._config = config

    def refresh(self, repo_id: str, installation_id: int) -> None:
        if not self._has_successful_job(repo_id):
            _logger.info(f"{repo_id}: no successful review yet; skipping index refresh")
            return

        # May raise — do NOT catch here to preserve previous valid index
        head_sha = self._github_client.get_branch_head_sha(repo_id)

        index_scope = self._config.index_scope if self._config else "auto"

        if index_scope == "single":
            packages: list[str] = []
        elif index_scope == "monorepo":
            packages = _detect_monorepo(self._github_client, repo_id)
            if not packages:
                packages = ["."]
        else:
            packages = _detect_monorepo(self._github_client, repo_id)

        if packages:
            scope = IndexScope.monorepo
            for pkg in packages:
                idx = self._build_index(
                    repo_id, head_sha, scope, package_path=pkg if pkg != "." else None
                )
                self._index_store.save(idx)
                _prune_old_versions(self._index_store, repo_id)
        else:
            scope = IndexScope.single
            idx = self._build_index(repo_id, head_sha, scope, package_path=None)
            self._index_store.save(idx)
            _prune_old_versions(self._index_store, repo_id)

    def _has_successful_job(self, repo_id: str) -> bool:
        from sqlalchemy import text

        with self._db_engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT COUNT(*) FROM jobs WHERE repo_id = :repo AND status = 'complete'"
                ),
                {"repo": repo_id},
            )
            count = result.scalar()
            return bool(count and count > 0)

    def _build_index(
        self,
        repo_id: str,
        head_sha: str,
        scope: IndexScope,
        package_path: str | None,
    ) -> CodebaseIndex:
        # Sample up to 20 files
        all_files_raw = self._github_client.list_directory(path=package_path or ".")
        all_files = [e["path"] for e in all_files_raw if e.get("type") != "dir"]
        sample = all_files[:_SAMPLE_FILE_COUNT]
        files_content = {
            path: self._github_client.get_file_content(repo_id, path)
            for path in sample
        }

        convention_profile = _build_convention_profile(files_content)
        content_obj = {
            "convention_profile": convention_profile,
            "architectural_summary": {"security_boundaries": [], "test_fixtures": []},
            "finding_density_map": None,
        }
        raw_content = json.dumps(content_obj)
        trimmed, token_count = _trim_to_token_limit(raw_content, self._max_tokens)

        return CodebaseIndex(
            id=uuid4(),
            repo_id=repo_id,
            commit_sha=head_sha,
            scope=scope,
            content=trimmed,
            package_path=package_path,
            is_valid=True,
            version=1,
            token_count=token_count,
        )


# ── Schedule helpers ──────────────────────────────────────────────────────────


def _get_last_refresh_days(redis_client: Any, repo_id: str) -> int | None:
    """Return age in days of last index refresh, or None if never refreshed."""
    key = f"{_LAST_REFRESH_KEY_PREFIX}{repo_id}"
    try:
        value = redis_client.get(key)
        if value is None:
            return None
        raw = value.decode() if isinstance(value, bytes) else value
        last_ts = datetime.fromisoformat(raw)
        return (datetime.now(tz=UTC) - last_ts).days
    except Exception:
        return None


def _store_last_refresh(redis_client: Any, repo_id: str) -> None:
    key = f"{_LAST_REFRESH_KEY_PREFIX}{repo_id}"
    redis_client.set(key, datetime.now(tz=UTC).isoformat())


def _run_index_refresh(
    repo_id: str,
    installation_id: int,
    config: "Config | None" = None,
    redis_client: Any = None,
) -> None:
    """Core index refresh logic — extracted for testability."""
    import os

    if redis_client is None:
        import redis as _redis
        redis_client = _redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    if config is None:
        from pr_reviewer.config.loader import ConfigLoader
        from pr_reviewer.store.github_client import GitHubAPIClient

        gh = GitHubAPIClient(installation_id=installation_id)
        config = ConfigLoader(gh).load(repo_id, installation_id)

    schedule = config.index_refresh_schedule

    if schedule == "on_merge":
        _logger.info(
            f"{repo_id}: index_refresh_schedule=on_merge; skipping Beat-triggered run"
        )
        return

    if schedule == "weekly":
        age_days = _get_last_refresh_days(redis_client, repo_id)
        if age_days is not None and age_days < _WEEKLY_REFRESH_DAYS:
            _logger.info(
                f"{repo_id}: weekly refresh; last refresh was {age_days} days ago; skipping"
            )
            return

    _logger.info(f"Index refresh proceeding for {repo_id}")
    _store_last_refresh(redis_client, repo_id)


# ── Celery task ───────────────────────────────────────────────────────────────


@celery_app.task(
    name="pr_reviewer.workers.indexer.run_index_refresh_task",
    queue="indexer_jobs",
    max_retries=3,
)
def run_index_refresh_task(repo_id: str = "", installation_id: int = 0) -> None:
    _run_index_refresh(repo_id, installation_id)


# Module-level alias used by webhook and job_processor
run_index_refresh = run_index_refresh_task
