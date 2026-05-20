"""JobProcessor — orchestrates the full PR review pipeline for a single job."""

from __future__ import annotations

import time
from typing import Any

from pr_reviewer.logging import get_logger
from pr_reviewer.models.enums import JobStatus
from pr_reviewer.models.finding import Finding
from pr_reviewer.models.job import Job

_logger = get_logger(__name__)

_SEVERITY_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}

_BOT_LOGINS = frozenset({"github-actions[bot]", "pr-reviewer[bot]", "github-actions"})


_STALE_COMMIT_THRESHOLD = 500


class JobProcessor:
    def __init__(
        self,
        job_store: Any,
        github_client: Any,
        diff_parser: Any,
        config_loader: Any,
        feedback_store: Any,
        review_agent: Any,
        comment_poster: Any,
        secret_scrubber: Any,
        knowledge_base: Any,
        mcp_client: Any,
        tracer: Any = None,
        duration_hist: Any = None,
        codebase_index_store: Any = None,
        index_refresh_task: Any = None,
    ) -> None:
        self._job_store = job_store
        self._github_client = github_client
        self._diff_parser = diff_parser
        self._config_loader = config_loader
        self._feedback_store = feedback_store
        self._review_agent = review_agent
        self._comment_poster = comment_poster
        self._secret_scrubber = secret_scrubber
        self._knowledge_base = knowledge_base
        self._mcp_client = mcp_client
        self._tracer = tracer or _noop_tracer()
        self._duration_hist = duration_hist or _noop_histogram()
        self._codebase_index_store = codebase_index_store
        self._index_refresh_task = index_refresh_task

    def process(self, job: Job) -> None:
        with self._tracer.start_as_current_span(
            "review.job",
            attributes={"job_id": str(job.id)},
        ):
            start = time.monotonic()
            try:
                self._run(job)
                elapsed_ms = (time.monotonic() - start) * 1000
                self._duration_hist.record(elapsed_ms, {"status": "success"})
            except _AuthErrorBase:
                elapsed_ms = (time.monotonic() - start) * 1000
                self._duration_hist.record(elapsed_ms, {"status": "auth_error"})
                self._job_store.update_status(job.id, JobStatus.failed)
                _logger.warning(f"Auth error on job {job.id}; marked failed")

    def _run(self, job: Job) -> None:
        # Load config
        config = self._config_loader.load(job.repo_id, job.installation_id)

        # Check for existing review on this commit
        existing = self._github_client.get_existing_reviews(job.repo_id, job.pr_number)
        if _already_reviewed(existing, job.commit_sha):
            _logger.info(f"Job {job.id}: already reviewed SHA {job.commit_sha}; skipping")
            return

        # Fetch diff
        raw_diff = self._fetch_diff(job)

        # Parse diff
        diff = self._diff_parser.parse(raw_diff, config)

        # Fetch few-shot feedback signals
        signals = self._feedback_store.query_recent(
            job.repo_id, file_path_patterns=[], limit=5
        )

        # Load codebase index (v2 feature)
        codebase_index = self._load_codebase_index(job, diff, config)

        # Build review context
        from pr_reviewer.agents.review_agent import ReviewContext

        ctx = ReviewContext(
            github_client=self._github_client,
            knowledge_base=self._knowledge_base,
            mcp_client=self._mcp_client,
            secret_scrubber=self._secret_scrubber,
            repo=job.repo_id,
            pr_number=job.pr_number,
            job_id=job.id,
            few_shot_examples=tuple(signals),
            codebase_index=codebase_index,
        )

        # Run agent
        findings = self._review_agent.run(diff, config, ctx)

        # Apply min_severity filter
        filtered = _filter_severity(findings, config.min_severity)

        # Post comments
        self._comment_poster.post(filtered, job.repo_id, job.pr_number, config)

        # Persist success state
        context_tokens = len(findings) * 100  # placeholder until token counting implemented
        self._job_store.update_success(job.id, job.commit_sha, context_tokens)

    def _load_codebase_index(self, job: Job, diff: Any, config: Any) -> list | None:
        if not (config.codebase_index_enabled and self._codebase_index_store):
            return None
        indexes = self._codebase_index_store.get_all(job.repo_id)
        if not indexes:
            return None
        if self._is_stale(indexes[0], job):
            _logger.warning(
                f"Codebase index for {job.repo_id} is stale (>{_STALE_COMMIT_THRESHOLD} commits behind HEAD); "
                "triggering out-of-schedule refresh"
            )
            if self._index_refresh_task:
                self._index_refresh_task.apply_async(
                    kwargs={"repo_id": job.repo_id, "installation_id": job.installation_id},
                    queue="indexer_jobs",
                )
        return self._select_indexes(diff, indexes, config) or None

    def _is_stale(self, index: Any, job: Job) -> bool:
        try:
            head_sha = self._github_client.get_branch_head_sha(job.repo_id)
            if head_sha == index.commit_sha:
                return False
            distance = self._github_client.get_commit_distance(
                job.repo_id, index.commit_sha, head_sha
            )
            return isinstance(distance, int) and distance > _STALE_COMMIT_THRESHOLD
        except Exception:
            return False

    def _select_indexes(self, diff: Any, indexes: list, config: Any) -> list:
        has_package_paths = any(getattr(idx, "package_path", None) for idx in indexes)
        if not has_package_paths:
            return self._apply_token_limit(indexes, diff, config.index_max_tokens)

        try:
            changed_names = [f.filename for f in diff.changed_files]
        except (TypeError, AttributeError):
            changed_names = []

        matching = [
            idx for idx in indexes
            if idx.package_path and any(
                name.startswith(idx.package_path + "/") or name == idx.package_path
                for name in changed_names
            )
        ]
        return self._apply_token_limit(matching, diff, config.index_max_tokens)

    def _apply_token_limit(self, indexes: list, diff: Any, max_tokens: int) -> list:
        try:
            changed_names = [f.filename for f in diff.changed_files]
        except (TypeError, AttributeError):
            changed_names = []

        def _changed_count(idx: Any) -> int:
            pkg = getattr(idx, "package_path", None)
            if pkg:
                return sum(
                    1 for name in changed_names
                    if name.startswith(pkg + "/") or name == pkg
                )
            return len(changed_names)

        sorted_indexes = sorted(indexes, key=_changed_count, reverse=True)
        result: list = []
        total_tokens = 0
        skipped = False
        for idx in sorted_indexes:
            idx_tokens = len(getattr(idx, "content", "")) // 4
            if total_tokens + idx_tokens > max_tokens:
                skipped = True
            else:
                result.append(idx)
                total_tokens += idx_tokens
        if skipped:
            _logger.warning(
                f"Codebase index token budget ({max_tokens}) exceeded; "
                f"{len(sorted_indexes) - len(result)} package(s) omitted"
            )
        return result

    def _fetch_diff(self, job: Job) -> str:
        if job.last_reviewed_sha:
            return self._github_client.compare_commits(
                job.repo_id, job.last_reviewed_sha, job.commit_sha
            )
        return self._github_client.get_diff(job.repo_id, job.pr_number)


def _already_reviewed(existing_reviews: list[dict], commit_sha: str) -> bool:
    for review in existing_reviews:
        reviewer = review.get("user", {}).get("login", "")
        if reviewer in _BOT_LOGINS and review.get("commit_id") == commit_sha:
            return True
    return False


def _filter_severity(findings: list[Finding], min_severity: str) -> list[Finding]:
    min_rank = _SEVERITY_RANK.get(min_severity, 0)
    return [f for f in findings if _SEVERITY_RANK.get(str(f.severity), 0) >= min_rank]


# ── Auth error detection ──────────────────────────────────────────────────────

try:
    from pr_reviewer.store.github_client import (
        AuthError as _AuthErrorBase,  # type: ignore[assignment]
    )
except ImportError:
    _AuthErrorBase = Exception  # type: ignore[assignment,misc]


# ── No-op fallbacks for uninstrumented environments ──────────────────────────

class _NoopSpan:
    def __enter__(self) -> _NoopSpan:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class _NoopTracer:
    def start_as_current_span(self, name: str, **kwargs: Any) -> _NoopSpan:
        return _NoopSpan()


class _NoopHistogram:
    def record(self, value: float, attributes: dict | None = None) -> None:
        pass


def _noop_tracer() -> _NoopTracer:
    return _NoopTracer()


def _noop_histogram() -> _NoopHistogram:
    return _NoopHistogram()
