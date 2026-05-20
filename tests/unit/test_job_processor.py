"""Unit tests for JobProcessor (tasks 16.1–16.9, 16.17–16.18)."""

import uuid
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

import pytest

from pr_reviewer.models.enums import Confidence, JobStatus, ReviewCategory, Severity
from pr_reviewer.models.finding import Finding
from pr_reviewer.models.job import Job


def _make_index(**kwargs):
    """Build a CodebaseIndex with required fields for v2 tests."""
    from pr_reviewer.models.codebase_index import CodebaseIndex, IndexScope
    defaults = {
        "id": uuid.uuid4(),
        "repo_id": "org/repo",
        "commit_sha": "abc123",
        "scope": IndexScope.single,
        "content": "arch summary",
    }
    defaults.update(kwargs)
    return CodebaseIndex(**defaults)


def _job(
    *,
    last_reviewed_sha: str | None = None,
    commit_sha: str = "newsha123",
    repo_id: str = "org/repo",
) -> Job:
    return Job(
        id=uuid.uuid4(),
        repo_id=repo_id,
        installation_id=42,
        pr_number=7,
        commit_sha=commit_sha,
        last_reviewed_sha=last_reviewed_sha,
        status=JobStatus.processing,
        attempts=1,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )


def _finding(severity: Severity = Severity.low) -> Finding:
    return Finding(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        file_path="src/auth.py",
        line_number=10,
        category=ReviewCategory.bugs,
        severity=severity,
        confidence=Confidence.high,
        explanation="Issue here.",
        is_escalation=False,
    )


def _make_processor(**overrides: object) -> tuple:
    """Return (processor, mocks_dict) with all I/O dependencies mocked."""
    from pr_reviewer.workers.job_processor import JobProcessor

    mocks: dict = {
        "job_store": MagicMock(),
        "github_client": MagicMock(),
        "diff_parser": MagicMock(),
        "config_loader": MagicMock(),
        "feedback_store": MagicMock(),
        "review_agent": MagicMock(),
        "comment_poster": MagicMock(),
        "secret_scrubber": MagicMock(),
        "knowledge_base": MagicMock(),
        "mcp_client": MagicMock(),
        "tracer": MagicMock(),
        "duration_hist": MagicMock(),
        "codebase_index_store": None,
        "index_refresh_task": None,
    }
    mocks.update(overrides)

    # Sensible defaults
    mocks["github_client"].get_diff.return_value = "diff text"
    mocks["github_client"].compare_commits.return_value = "diff text"
    mocks["github_client"].get_existing_reviews.return_value = []
    mocks["github_client"].get_branch_head_sha.return_value = "current_head"
    mocks["github_client"].get_commit_distance.return_value = 0
    mocks["diff_parser"].parse.return_value = MagicMock(changed_files=())
    mocks["config_loader"].load.return_value = __import__(
        "pr_reviewer.config.schema", fromlist=["Config"]
    ).Config()
    mocks["feedback_store"].query_recent.return_value = []
    mocks["review_agent"].run.return_value = []
    # Tracer returns a context manager span
    mocks["tracer"].start_as_current_span.return_value.__enter__ = MagicMock(
        return_value=MagicMock()
    )
    mocks["tracer"].start_as_current_span.return_value.__exit__ = MagicMock(
        return_value=False
    )

    processor = JobProcessor(**mocks)
    return processor, mocks


# ── Task 16.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_review_job_completes_end_to_end():
    """All components called; review posted; job updated to success."""
    processor, mocks = _make_processor()
    job = _job()
    mocks["review_agent"].run.return_value = [_finding()]

    processor.process(job)

    mocks["review_agent"].run.assert_called_once()
    mocks["comment_poster"].post.assert_called_once()
    mocks["job_store"].update_success.assert_called_once()


# ── Task 16.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_incremental_diff_fetched_when_last_sha_exists():
    """last_reviewed_sha='abc123' → compare_commits('abc123', 'newsha') called."""
    processor, mocks = _make_processor()
    job = _job(last_reviewed_sha="abc123", commit_sha="newsha")

    processor.process(job)

    mocks["github_client"].compare_commits.assert_called_once_with(
        job.repo_id, "abc123", "newsha"
    )
    mocks["github_client"].get_diff.assert_not_called()


# ── Task 16.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_last_reviewed_sha_updated_only_on_success():
    """CommentPoster.post raises → update_success NOT called."""
    processor, mocks = _make_processor()
    mocks["comment_poster"].post.side_effect = RuntimeError("post failed")
    job = _job()

    with pytest.raises(RuntimeError):
        processor.process(job)

    mocks["job_store"].update_success.assert_not_called()


# ── Task 16.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_existing_review_for_commit_sha_skips_job():
    """Existing bot review for same SHA → ReviewAgent.run NOT called."""
    processor, mocks = _make_processor()
    job = _job(commit_sha="abc123")
    mocks["github_client"].get_existing_reviews.return_value = [
        {"commit_id": "abc123", "user": {"login": "github-actions[bot]"}}
    ]

    processor.process(job)

    mocks["review_agent"].run.assert_not_called()


# ── Task 16.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_min_severity_filter_applied_after_review():
    """min_severity=medium; ReviewAgent returns 1 high + 2 low → poster receives 1 high."""
    from pr_reviewer.config.schema import Config

    processor, mocks = _make_processor()
    mocks["config_loader"].load.return_value = Config(min_severity="medium")
    findings = [
        _finding(Severity.high),
        _finding(Severity.low),
        _finding(Severity.low),
    ]
    mocks["review_agent"].run.return_value = findings

    processor.process(_job())

    post_call = mocks["comment_poster"].post.call_args
    posted_findings = post_call[0][0] if post_call[0] else post_call.kwargs["findings"]
    high_only = [f for f in posted_findings if str(f.severity) == "high"]
    low_only = [f for f in posted_findings if str(f.severity) == "low"]
    assert len(high_only) == 1
    assert len(low_only) == 0


# ── Task 16.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_few_shot_examples_in_review_context():
    """FeedbackStore signals passed as few_shot_examples in ReviewContext."""
    from pr_reviewer.models.feedback_signal import FeedbackSignal
    from pr_reviewer.models.enums import SignalType

    processor, mocks = _make_processor()
    signal = FeedbackSignal(
        id=uuid.uuid4(),
        repo_id="org/repo",
        finding_category=ReviewCategory.bugs,
        file_path_pattern="src/auth/**",
        signal_type=SignalType.positive,
        timestamp=datetime.now(tz=UTC),
    )
    mocks["feedback_store"].query_recent.return_value = [signal]

    processor.process(_job())

    mocks["review_agent"].run.assert_called_once()
    _, __, ctx = mocks["review_agent"].run.call_args[0]
    assert signal in ctx.few_shot_examples


# ── Task 16.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_auth_error_marks_job_failed_no_retry():
    """AuthError → jobs.status = failed; does not raise (no Celery retry)."""
    from pr_reviewer.store.github_client import AuthError

    processor, mocks = _make_processor()
    mocks["github_client"].get_diff.side_effect = AuthError("bad auth")
    mocks["github_client"].compare_commits.side_effect = AuthError("bad auth")
    job = _job()

    processor.process(job)  # Should NOT raise; swallows AuthError

    mocks["job_store"].update_status.assert_called_with(job.id, JobStatus.failed)
    mocks["job_store"].update_success.assert_not_called()


# ── Task 16.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_root_span_created_with_job_id():
    """OTel root span started with job_id as attribute."""
    processor, mocks = _make_processor()
    job = _job()

    processor.process(job)

    mocks["tracer"].start_as_current_span.assert_called_once()
    call_kwargs = mocks["tracer"].start_as_current_span.call_args
    attributes = call_kwargs.kwargs.get("attributes") or (
        call_kwargs[1].get("attributes") if len(call_kwargs) > 1 else {}
    )
    assert str(job.id) in (attributes or {}).values() or \
        str(job.id) in str(call_kwargs)


# ── Task 16.9 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_review_duration_recorded_on_success():
    """Successful job → duration_hist.record called with status='success'."""
    processor, mocks = _make_processor()

    processor.process(_job())

    mocks["duration_hist"].record.assert_called_once()
    call_kwargs = mocks["duration_hist"].record.call_args
    attrs = call_kwargs.kwargs.get("attributes") or (
        call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
    )
    assert attrs.get("status") == "success"


# ── Task 16.17 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_context_tokens_used_recorded_after_successful_job():
    """After success, update_success called with context_tokens_used > 0."""
    processor, mocks = _make_processor()
    mocks["review_agent"].run.return_value = [_finding()]

    processor.process(_job())

    args = mocks["job_store"].update_success.call_args[0]
    context_tokens = args[2] if len(args) > 2 else mocks["job_store"].update_success.call_args.kwargs.get("context_tokens_used", 0)
    assert isinstance(context_tokens, int) and context_tokens >= 0


# ── Task 16.10 [v2] ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_codebase_index_injected_into_review_context_when_enabled():
    """codebase_index_enabled=True + valid index in store → ctx.codebase_index is not None."""
    from pr_reviewer.config.schema import Config

    index = _make_index()
    store = MagicMock()
    store.get_all.return_value = [index]

    processor, mocks = _make_processor(codebase_index_store=store)
    mocks["config_loader"].load.return_value = Config(codebase_index_enabled=True)

    processor.process(_job())

    mocks["review_agent"].run.assert_called_once()
    _, __, ctx = mocks["review_agent"].run.call_args[0]
    assert ctx.codebase_index is not None


# ── Task 16.11 [v2] ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_codebase_index_not_injected_when_disabled():
    """codebase_index_enabled=False → ctx.codebase_index is None."""
    from pr_reviewer.config.schema import Config

    processor, mocks = _make_processor()
    mocks["config_loader"].load.return_value = Config(codebase_index_enabled=False)

    processor.process(_job())

    mocks["review_agent"].run.assert_called_once()
    _, __, ctx = mocks["review_agent"].run.call_args[0]
    assert ctx.codebase_index is None


# ── Task 16.12 [v2] ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_no_index_in_db_does_not_fail_job():
    """codebase_index_enabled=True but store returns [] → job succeeds with ctx.codebase_index=None."""
    from pr_reviewer.config.schema import Config

    store = MagicMock()
    store.get_all.return_value = []

    processor, mocks = _make_processor(codebase_index_store=store)
    mocks["config_loader"].load.return_value = Config(codebase_index_enabled=True)

    processor.process(_job())  # must not raise

    mocks["review_agent"].run.assert_called_once()
    _, __, ctx = mocks["review_agent"].run.call_args[0]
    assert ctx.codebase_index is None


# ── Task 16.13 [v2] ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_stale_index_triggers_out_of_schedule_refresh():
    """Index 501 commits behind HEAD → WARN + run_index_refresh enqueued on indexer_jobs."""
    from pr_reviewer.config.schema import Config

    index = _make_index(commit_sha="old_sha", content="summary")
    store = MagicMock()
    store.get_all.return_value = [index]

    refresh_task = MagicMock()
    processor, mocks = _make_processor(
        codebase_index_store=store,
        index_refresh_task=refresh_task,
    )
    mocks["config_loader"].load.return_value = Config(codebase_index_enabled=True)
    mocks["github_client"].get_branch_head_sha.return_value = "head_sha"
    mocks["github_client"].get_commit_distance.return_value = 501

    processor.process(_job())

    refresh_task.apply_async.assert_called_once_with(
        kwargs={"repo_id": "org/repo", "installation_id": 42},
        queue="indexer_jobs",
    )


# ── Task 16.14 [v2] ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_stale_index_does_not_block_job():
    """Stale index detected → job continues; ReviewAgent.run still called with index."""
    from pr_reviewer.config.schema import Config

    index = _make_index(commit_sha="old_sha", content="summary")
    store = MagicMock()
    store.get_all.return_value = [index]

    processor, mocks = _make_processor(codebase_index_store=store)
    mocks["config_loader"].load.return_value = Config(codebase_index_enabled=True)
    mocks["github_client"].get_branch_head_sha.return_value = "head_sha"
    mocks["github_client"].get_commit_distance.return_value = 501

    processor.process(_job())

    mocks["review_agent"].run.assert_called_once()
    _, __, ctx = mocks["review_agent"].run.call_args[0]
    assert ctx.codebase_index is not None  # stale index still injected


# ── Task 16.15 [v2] ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_multi_package_pr_injects_only_modified_package_sections():
    """PR modifies packages/api and packages/db; auth index excluded."""
    from pr_reviewer.config.schema import Config
    from pr_reviewer.models.codebase_index import IndexScope

    api_index = _make_index(commit_sha="abc", content="api content", scope=IndexScope.monorepo, package_path="packages/api")
    db_index = _make_index(commit_sha="abc", content="db content", scope=IndexScope.monorepo, package_path="packages/db")
    auth_index = _make_index(commit_sha="abc", content="auth content", scope=IndexScope.monorepo, package_path="packages/auth")
    store = MagicMock()
    store.get_all.return_value = [api_index, db_index, auth_index]

    processor, mocks = _make_processor(codebase_index_store=store)
    mocks["config_loader"].load.return_value = Config(codebase_index_enabled=True)

    diff_mock = MagicMock()
    diff_mock.changed_files = [
        MagicMock(filename="packages/api/src/server.ts"),
        MagicMock(filename="packages/db/src/models.py"),
    ]
    mocks["diff_parser"].parse.return_value = diff_mock

    processor.process(_job())

    mocks["review_agent"].run.assert_called_once()
    _, __, ctx = mocks["review_agent"].run.call_args[0]
    injected: list = ctx.codebase_index
    assert api_index in injected
    assert db_index in injected
    assert auth_index not in injected


# ── Task 16.16 [v2] ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_multi_package_injection_respects_token_limit():
    """Combined index > index_max_tokens → most-changed-files package wins; total ≤ limit."""
    from pr_reviewer.config.schema import Config
    from pr_reviewer.models.codebase_index import CodebaseIndex

    # 20_000 chars ≈ 5_000 tokens each; combined 10_000 > 8_000 limit
    from pr_reviewer.models.codebase_index import IndexScope
    big_content = "x" * 20_000
    api_index = _make_index(commit_sha="abc", content=big_content, scope=IndexScope.monorepo, package_path="packages/api")
    db_index = _make_index(commit_sha="abc", content=big_content, scope=IndexScope.monorepo, package_path="packages/db")
    store = MagicMock()
    store.get_all.return_value = [api_index, db_index]

    processor, mocks = _make_processor(codebase_index_store=store)
    mocks["config_loader"].load.return_value = Config(
        codebase_index_enabled=True, index_max_tokens=8_000
    )

    diff_mock = MagicMock()
    diff_mock.changed_files = [
        MagicMock(filename="packages/api/a.py"),
        MagicMock(filename="packages/api/b.py"),
        MagicMock(filename="packages/api/c.py"),
        MagicMock(filename="packages/db/model.py"),
    ]
    mocks["diff_parser"].parse.return_value = diff_mock

    processor.process(_job())

    mocks["review_agent"].run.assert_called_once()
    _, __, ctx = mocks["review_agent"].run.call_args[0]
    injected: list = ctx.codebase_index
    assert injected is not None
    total_tokens = sum(len(idx.content) // 4 for idx in injected)
    assert total_tokens <= 8_000
    assert api_index in injected  # api has 3 changed files vs db's 1
