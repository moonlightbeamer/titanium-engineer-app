"""Unit tests for domain models (tasks 3.7–3.8)."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from pr_reviewer.models import (
    Confidence,
    FeedbackSignal,
    Finding,
    Job,
    JobStatus,
    ReviewCategory,
    Severity,
    SignalType,
)


def _make_job(**overrides) -> Job:
    now = datetime.now(UTC)
    defaults = dict(
        id=uuid4(),
        repo_id="org/repo",
        installation_id=123,
        pr_number=42,
        commit_sha="abc123",
        last_reviewed_sha=None,
        status=JobStatus.queued,
        attempts=0,
        created_at=now,
        updated_at=now,
    )
    return Job(**{**defaults, **overrides})


def _make_finding(**overrides) -> Finding:
    defaults = dict(
        id=uuid4(),
        job_id=uuid4(),
        file_path="src/foo.py",
        line_number=10,
        category=ReviewCategory.bugs,
        severity=Severity.medium,
        confidence=Confidence.high,
        explanation="Off-by-one error",
        is_escalation=False,
    )
    return Finding(**{**defaults, **overrides})


# ── Task 3.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_job_model_is_frozen():
    job = _make_job()
    with pytest.raises(FrozenInstanceError):
        job.status = JobStatus.complete  # type: ignore[misc]


# ── Task 3.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_finding_model_is_frozen():
    finding = _make_finding()
    with pytest.raises(FrozenInstanceError):
        finding.severity = Severity.high  # type: ignore[misc]


# ── Enum completeness checks ──────────────────────────────────────────────────


@pytest.mark.unit
def test_job_status_values():
    values = {s.value for s in JobStatus}
    assert values == {"queued", "processing", "complete", "failed", "dead_letter"}


@pytest.mark.unit
def test_review_category_values():
    values = {c.value for c in ReviewCategory}
    assert values == {"bugs", "security", "style", "performance"}


@pytest.mark.unit
def test_severity_values():
    values = {s.value for s in Severity}
    assert values == {"low", "medium", "high"}


@pytest.mark.unit
def test_confidence_values():
    values = {c.value for c in Confidence}
    assert values == {"low", "medium", "high"}


@pytest.mark.unit
def test_signal_type_values():
    values = {s.value for s in SignalType}
    assert values == {"positive", "negative"}


# ── FeedbackSignal has no raw code fields ─────────────────────────────────────


@pytest.mark.unit
def test_feedback_signal_has_no_code_fields():
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(FeedbackSignal)}
    forbidden = {"code", "diff", "content", "snippet"}
    overlap = field_names & forbidden
    assert not overlap, f"FeedbackSignal must not have raw code fields: {overlap}"
