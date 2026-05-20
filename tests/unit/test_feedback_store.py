"""Unit tests for FeedbackStore (tasks 14.1–14.7)."""

import uuid
from datetime import datetime, UTC

import pytest
import sqlalchemy as sa

from pr_reviewer.models.enums import ReviewCategory, SignalType
from pr_reviewer.models.feedback_signal import FeedbackSignal

_REPO = "org/repo"


def _engine() -> sa.Engine:
    """Return an in-memory SQLite engine for unit testing."""
    return sa.create_engine("sqlite:///:memory:", echo=False)


def _signal(
    *,
    repo_id: str = _REPO,
    category: ReviewCategory = ReviewCategory.bugs,
    file_path_pattern: str = "src/auth/**",
    signal_type: SignalType = SignalType.positive,
    timestamp: datetime | None = None,
) -> FeedbackSignal:
    return FeedbackSignal(
        id=uuid.uuid4(),
        repo_id=repo_id,
        finding_category=category,
        file_path_pattern=file_path_pattern,
        signal_type=signal_type,
        timestamp=timestamp or datetime.now(tz=UTC),
    )


# ── Task 14.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_insert_then_query_returns_inserted_signal():
    """Insert a signal; query by repo_id → signal is present."""
    from pr_reviewer.store.feedback_store import FeedbackStore

    engine = _engine()
    store = FeedbackStore(engine)
    sig = _signal()
    store.insert(sig)
    results = store.query_recent(_REPO, file_path_patterns=[], limit=10)
    ids = [r.id for r in results]
    assert sig.id in ids


# ── Task 14.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_query_recent_respects_limit():
    """10 signals → query with limit=5 returns exactly 5."""
    from pr_reviewer.store.feedback_store import FeedbackStore

    engine = _engine()
    store = FeedbackStore(engine)
    for _ in range(10):
        store.insert(_signal())
    results = store.query_recent(_REPO, file_path_patterns=[], limit=5)
    assert len(results) == 5


# ── Task 14.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_query_recent_returns_most_recent_first():
    """3 signals at t1 < t2 < t3 → t3 is first in results."""
    from pr_reviewer.store.feedback_store import FeedbackStore

    engine = _engine()
    store = FeedbackStore(engine)
    t1 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)
    t3 = datetime(2026, 1, 3, 0, 0, 0, tzinfo=UTC)
    s1 = _signal(timestamp=t1)
    s2 = _signal(timestamp=t2)
    s3 = _signal(timestamp=t3)
    for s in [s1, s2, s3]:
        store.insert(s)
    results = store.query_recent(_REPO, file_path_patterns=[], limit=10)
    assert results[0].id == s3.id


# ── Task 14.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_query_filters_by_file_path_pattern():
    """Only signals matching the given file_path_patterns are returned."""
    from pr_reviewer.store.feedback_store import FeedbackStore

    engine = _engine()
    store = FeedbackStore(engine)
    auth_sig = _signal(file_path_pattern="src/auth/**")
    db_sig = _signal(file_path_pattern="src/db/**")
    other_sig = _signal(file_path_pattern="src/utils/**")
    for s in [auth_sig, db_sig, other_sig]:
        store.insert(s)
    results = store.query_recent(
        _REPO, file_path_patterns=["src/auth/**"], limit=10
    )
    result_ids = {r.id for r in results}
    assert auth_sig.id in result_ids
    assert db_sig.id not in result_ids
    assert other_sig.id not in result_ids


# ── Task 14.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_feedback_signal_has_no_code_fields():
    """FeedbackSignal has no code, diff, content, or snippet field."""
    sig = _signal()
    for forbidden in ("code", "diff", "content", "snippet"):
        assert not hasattr(sig, forbidden), f"FeedbackSignal must not have field: {forbidden}"


# ── Task 14.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_query_uses_parameterized_sql():
    """SQL injection-like repo_id returns empty results rather than an error."""
    from pr_reviewer.store.feedback_store import FeedbackStore

    engine = _engine()
    store = FeedbackStore(engine)
    # If f-string SQL is used, this could raise or cause a logic error.
    # With parameterized SQL, it simply returns no results.
    malicious = "'; DROP TABLE feedback_signals; --"
    results = store.query_recent(malicious, file_path_patterns=[], limit=10)
    assert results == []
    # Confirm the table still exists
    store.insert(_signal())
    legit = store.query_recent(_REPO, file_path_patterns=[], limit=10)
    assert len(legit) == 1
