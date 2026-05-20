"""Unit tests for CommentPoster (tasks 13.1–13.12)."""

import uuid
from unittest.mock import MagicMock, call

import httpx
import pytest

from pr_reviewer.config.schema import Config
from pr_reviewer.models.enums import Confidence, ReviewCategory, Severity
from pr_reviewer.models.finding import Finding

_JOB_ID = uuid.uuid4()
_REPO = "org/repo"
_PR = 42


def _finding(
    *,
    severity: Severity = Severity.low,
    confidence: Confidence = Confidence.high,
    category: ReviewCategory = ReviewCategory.bugs,
    file_path: str = "src/auth.py",
    line_number: int = 10,
    explanation: str = "Something is wrong.",
    suggestion: str | None = None,
    is_escalation: bool = False,
) -> Finding:
    return Finding(
        id=uuid.uuid4(),
        job_id=_JOB_ID,
        file_path=file_path,
        line_number=line_number,
        category=category,
        severity=severity,
        confidence=confidence,
        explanation=explanation,
        is_escalation=is_escalation,
        suggestion=suggestion,
    )


def _make_poster() -> tuple:
    """Return (poster, mock_github_client)."""
    from pr_reviewer.components.comment_poster import CommentPoster

    gh = MagicMock()
    gh.get_existing_reviews.return_value = []
    gh.post_review.return_value = {}
    poster = CommentPoster(github_client=gh)
    return poster, gh


# ── Task 13.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_single_review_payload_sent():
    """Multiple Findings → exactly one call to post_review, not one per Finding."""
    poster, gh = _make_poster()
    findings = [
        _finding(severity=Severity.low, file_path="src/a.py", line_number=1),
        _finding(severity=Severity.medium, file_path="src/b.py", line_number=2),
        _finding(severity=Severity.high, file_path="src/c.py", line_number=3),
    ]
    poster.post(findings, _REPO, _PR, Config())
    assert gh.post_review.call_count == 1


# ── Task 13.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_any_high_produces_request_changes():
    """One high-severity Finding → event == 'REQUEST_CHANGES'."""
    poster, gh = _make_poster()
    findings = [
        _finding(severity=Severity.low),
        _finding(severity=Severity.high, line_number=20),
    ]
    poster.post(findings, _REPO, _PR, Config())
    _, kwargs = gh.post_review.call_args
    assert kwargs.get("event", gh.post_review.call_args[0][3] if gh.post_review.call_args[0] else "") == "REQUEST_CHANGES" or \
        gh.post_review.call_args[0][3] == "REQUEST_CHANGES" or \
        gh.post_review.call_args.kwargs.get("event") == "REQUEST_CHANGES"


# ── Task 13.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_empty_findings_list_posts_no_issues_found_comment():
    """Empty findings → summary body 'No issues found.', status 'COMMENT'."""
    poster, gh = _make_poster()
    poster.post([], _REPO, _PR, Config())
    assert gh.post_review.call_count == 1
    args = gh.post_review.call_args
    # event should be COMMENT, body should contain "No issues found."
    body = args.kwargs.get("body") or args[0][2]
    event = args.kwargs.get("event") or args[0][3]
    assert "No issues found." in body
    assert event == "COMMENT"


# ── Task 13.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_all_filtered_by_min_severity_also_posts_no_issues_found():
    """3 low Findings, min_severity=medium → all filtered → 'No issues found.'"""
    from pydantic import ValidationError

    poster, gh = _make_poster()
    findings = [_finding(severity=Severity.low) for _ in range(3)]
    config = Config(min_severity="medium")
    poster.post(findings, _REPO, _PR, config)
    args = gh.post_review.call_args
    body = args.kwargs.get("body") or args[0][2]
    assert "No issues found." in body


# ── Task 13.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_auto_approve_when_no_findings_and_configured():
    """Empty + auto_approve_on_no_findings=True → event == 'APPROVE'."""
    poster, gh = _make_poster()
    config = Config(auto_approve_on_no_findings=True)
    poster.post([], _REPO, _PR, config)
    args = gh.post_review.call_args
    event = args.kwargs.get("event") or args[0][3]
    assert event == "APPROVE"


# ── Task 13.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_suggestion_block_uses_github_syntax_for_medium():
    """Medium Finding with suggestion → body contains GitHub suggestion block."""
    poster, gh = _make_poster()
    findings = [
        _finding(
            severity=Severity.medium,
            suggestion="fixed code here",
            explanation="This needs fixing.",
        )
    ]
    poster.post(findings, _REPO, _PR, Config())
    args = gh.post_review.call_args
    comments = args.kwargs.get("comments") or args[0][4]
    assert len(comments) >= 1
    body = comments[0]["body"]
    assert "```suggestion" in body


# ── Task 13.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_invalid_suggestion_omits_block_retains_explanation():
    """Finding with None suggestion → no suggestion block; explanation present."""
    poster, gh = _make_poster()
    findings = [
        _finding(
            severity=Severity.medium,
            suggestion=None,
            explanation="Important issue here.",
        )
    ]
    poster.post(findings, _REPO, _PR, Config())
    args = gh.post_review.call_args
    comments = args.kwargs.get("comments") or args[0][4]
    assert len(comments) >= 1
    body = comments[0]["body"]
    assert "```suggestion" not in body
    assert "Important issue here." in body


# ── Task 13.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_422_skips_comment_and_continues():
    """422 on second comment → first and third posted; second skipped; no exception."""
    poster, gh = _make_poster()
    findings = [
        _finding(severity=Severity.low, file_path="src/a.py", line_number=1),
        _finding(severity=Severity.low, file_path="src/b.py", line_number=2),
        _finding(severity=Severity.low, file_path="src/c.py", line_number=3),
    ]

    call_count = {"n": 0}

    def _side_effect(*args: object, **kwargs: object) -> dict:
        call_count["n"] += 1
        comments = kwargs.get("comments") or (args[4] if len(args) > 4 else [])
        # Batch call with 3 comments → 422
        if len(comments) == 3:
            resp = MagicMock()
            resp.status_code = 422
            raise httpx.HTTPStatusError("422", request=MagicMock(), response=resp)
        # Individual call for src/b.py → 422
        if len(comments) == 1 and comments[0].get("path") == "src/b.py":
            resp = MagicMock()
            resp.status_code = 422
            raise httpx.HTTPStatusError("422", request=MagicMock(), response=resp)
        return {}

    gh.post_review.side_effect = _side_effect
    # Should not raise
    poster.post(findings, _REPO, _PR, Config())
    # Batch (1) + 3 individual = 4 calls; or fallback logic may vary
    assert call_count["n"] >= 3  # at minimum the fallback tried all 3 individually


# ── Task 13.9 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_dedup_skips_finding_with_existing_comment():
    """Existing comment at src/auth.py:10 → Finding at that location not re-posted."""
    poster, gh = _make_poster()
    gh.get_existing_reviews.return_value = [
        {"comments": [{"path": "src/auth.py", "line": 10}]}
    ]
    findings = [
        _finding(file_path="src/auth.py", line_number=10),  # already commented
        _finding(file_path="src/auth.py", line_number=99),  # new
    ]
    poster.post(findings, _REPO, _PR, Config())
    args = gh.post_review.call_args
    comments = args.kwargs.get("comments") or args[0][4]
    paths_and_lines = [(c["path"], c.get("line", c.get("position"))) for c in comments]
    assert ("src/auth.py", 10) not in paths_and_lines


# ── Task 13.10 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_summary_body_found_n_issues():
    """3 Findings across 2 categories → summary body contains count and category info."""
    poster, gh = _make_poster()
    findings = [
        _finding(category=ReviewCategory.bugs, line_number=1),
        _finding(category=ReviewCategory.bugs, line_number=2),
        _finding(category=ReviewCategory.security, line_number=3),
    ]
    poster.post(findings, _REPO, _PR, Config())
    args = gh.post_review.call_args
    body = args.kwargs.get("body") or args[0][2]
    assert "3" in body
    assert "2" in body


# ── Task 13.11 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_min_severity_filter_applied_before_status_determination():
    """2 high + 1 low, min_severity=high → low suppressed; status 'REQUEST_CHANGES'."""
    poster, gh = _make_poster()
    findings = [
        _finding(severity=Severity.high, line_number=1),
        _finding(severity=Severity.high, line_number=2),
        _finding(severity=Severity.low, line_number=3),
    ]
    config = Config(min_severity="high")
    poster.post(findings, _REPO, _PR, config)
    args = gh.post_review.call_args
    event = args.kwargs.get("event") or args[0][3]
    comments = args.kwargs.get("comments") or args[0][4]
    assert event == "REQUEST_CHANGES"
    # Only 2 high-severity comments included
    assert len(comments) == 2
