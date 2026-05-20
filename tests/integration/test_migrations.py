"""Integration tests for Alembic migrations (tasks 3.1–3.6).

Requires:  DATABASE_URL pointing to a live PostgreSQL instance
           (set by CI via environment, or locally via services-up + env).
"""

import os
import subprocess

import pytest
from sqlalchemy import create_engine, inspect

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/pr_reviewer"
)


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(DATABASE_URL, pool_pre_ping=True)
    yield eng
    eng.dispose()


def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        ["uv", "run", "alembic", *args],  # noqa: S607
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": DATABASE_URL},
    )


# ── Task 3.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_v1_migrations_apply_to_blank_db(engine):
    """alembic upgrade head → exits 0, all v1 tables present."""
    # Reset to empty state first
    _run_alembic("downgrade", "base")

    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, result.stderr

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "jobs" in tables
    assert "findings" in tables
    assert "feedback_signals" in tables


# ── Task 3.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_v1_migrations_are_reversible():
    """alembic downgrade -1 from each migration → exits 0."""
    _run_alembic("upgrade", "head")

    for _ in range(3):
        result = _run_alembic("downgrade", "-1")
        assert result.returncode == 0, result.stderr


# ── Task 3.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_jobs_table_columns_match_model(engine):
    """jobs table has all fields from Job dataclass."""
    _run_alembic("upgrade", "head")
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("jobs")}
    expected = {
        "id",
        "repo_id",
        "installation_id",
        "pr_number",
        "commit_sha",
        "last_reviewed_sha",
        "status",
        "attempts",
        "created_at",
        "updated_at",
        "context_tokens_used",
    }
    assert expected <= cols, f"Missing columns: {expected - cols}"


# ── Task 3.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_findings_table_columns_match_model(engine):
    """findings table has all fields from Finding dataclass."""
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("findings")}
    expected = {
        "id",
        "job_id",
        "file_path",
        "line_number",
        "start_line",
        "category",
        "severity",
        "confidence",
        "explanation",
        "suggestion",
        "is_escalation",
        "related_finding_ids",
    }
    assert expected <= cols, f"Missing columns: {expected - cols}"


# ── Task 3.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_feedback_signals_table_columns_match_model(engine):
    """feedback_signals table has all fields from FeedbackSignal dataclass."""
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("feedback_signals")}
    expected = {
        "id",
        "repo_id",
        "finding_category",
        "file_path_pattern",
        "signal_type",
        "timestamp",
    }
    assert expected <= cols, f"Missing columns: {expected - cols}"


# ── Task 3.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_indexes_created(engine):
    """Expected indexes exist on jobs and findings tables."""
    inspector = inspect(engine)

    job_indexes = {idx["name"] for idx in inspector.get_indexes("jobs")}
    assert "ix_jobs_repo_pr" in job_indexes
    assert "ix_jobs_commit_sha" in job_indexes

    finding_indexes = {idx["name"] for idx in inspector.get_indexes("findings")}
    assert "ix_findings_job_id" in finding_indexes
