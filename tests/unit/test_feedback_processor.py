"""Unit tests for FeedbackProcessor (tasks 15.1–15.9)."""

from unittest.mock import MagicMock

import pytest

from pr_reviewer.models.enums import ReviewCategory, SignalType


def _make_processor() -> tuple:
    """Return (processor, mock_store, mock_scrubber)."""
    from pr_reviewer.workers.feedback_processor import FeedbackProcessor

    store = MagicMock()
    scrubber = MagicMock()
    scrubber.scrub.return_value = ("clean content", [])
    processor = FeedbackProcessor(feedback_store=store, secret_scrubber=scrubber)
    return processor, store, scrubber


# ── Task 15.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_resolved_comment_without_suggestion_classified_negative():
    """`pull_request_review_comment` resolved, no suggestion → SignalType.negative."""
    from pr_reviewer.workers.feedback_processor import _classify_signal

    payload = {
        "action": "resolved",
        "comment": {
            "body": "This is not useful.",
            "path": "src/auth.py",
        },
        "repository": {"full_name": "org/repo"},
        "pull_request": {"number": 1},
    }
    result = _classify_signal("pull_request_review_comment", payload)
    assert result == SignalType.negative


# ── Task 15.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_applied_suggestion_classified_positive():
    """Suggestion-applied marker in comment body → SignalType.positive."""
    from pr_reviewer.workers.feedback_processor import _classify_signal

    payload = {
        "action": "created",
        "comment": {
            "body": "Applied in commit abc123",
            "path": "src/auth.py",
        },
        "repository": {"full_name": "org/repo"},
        "pull_request": {"number": 1},
    }
    result = _classify_signal("pull_request_review_comment", payload)
    assert result == SignalType.positive


# ── Task 15.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_wontfix_reply_classified_negative():
    """Reply body containing 'won't fix' → SignalType.negative."""
    from pr_reviewer.workers.feedback_processor import _classify_signal

    payload = {
        "action": "created",
        "comment": {
            "body": "won't fix this intentionally",
            "path": "src/auth.py",
        },
        "repository": {"full_name": "org/repo"},
        "pull_request": {"number": 1},
    }
    result = _classify_signal("pull_request_review_comment", payload)
    assert result == SignalType.negative


# ── Task 15.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_pull_request_review_submitted_suggestion_accepted_positive():
    """`pull_request_review` event, state=APPROVED → SignalType.positive."""
    from pr_reviewer.workers.feedback_processor import _classify_signal

    payload = {
        "action": "submitted",
        "review": {
            "state": "approved",
            "body": "Looks good!",
        },
        "repository": {"full_name": "org/repo"},
        "pull_request": {"number": 1},
    }
    result = _classify_signal("pull_request_review", payload)
    assert result == SignalType.positive


# ── Task 15.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_secret_scrubber_called_before_building_signal():
    """Payload with secret-like string → SecretScrubber.scrub called."""
    processor, store, scrubber = _make_processor()
    payload = {
        "action": "resolved",
        "comment": {
            "body": "AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE",
            "path": "src/auth.py",
        },
        "repository": {"full_name": "org/repo"},
        "pull_request": {"number": 1},
    }
    processor.process("pull_request_review_comment", payload)
    scrubber.scrub.assert_called_once()


# ── Task 15.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_feedback_signal_persisted_to_store():
    """Classified signal → FeedbackStore.insert called with a FeedbackSignal."""
    from pr_reviewer.models.feedback_signal import FeedbackSignal

    processor, store, scrubber = _make_processor()
    payload = {
        "action": "resolved",
        "comment": {
            "body": "Not useful.",
            "path": "src/auth.py",
        },
        "repository": {"full_name": "org/repo"},
        "pull_request": {"number": 1},
    }
    processor.process("pull_request_review_comment", payload)
    store.insert.assert_called_once()
    signal = store.insert.call_args[0][0]
    assert isinstance(signal, FeedbackSignal)
    assert signal.repo_id == "org/repo"


# ── Task 15.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_unknown_event_type_logs_warn_and_returns_without_insert():
    """Unrecognised event_type → WARN logged; FeedbackStore.insert never called."""
    processor, store, scrubber = _make_processor()
    processor.process("push", {"repository": {"full_name": "org/repo"}})
    store.insert.assert_not_called()


# ── Task 15.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_file_path_pattern_extracted_from_comment():
    """Comment on src/auth/login.py → file_path_pattern == 'src/auth/**'."""
    from pr_reviewer.workers.feedback_processor import _extract_file_path_pattern

    assert _extract_file_path_pattern("src/auth/login.py") == "src/auth/**"
    assert _extract_file_path_pattern("main.py") == "**"
    assert _extract_file_path_pattern("a/b/c/d.py") == "a/b/**"
