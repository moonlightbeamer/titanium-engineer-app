"""FeedbackProcessor — classifies and persists feedback signals from GitHub events."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pr_reviewer.logging import get_logger
from pr_reviewer.models.enums import ReviewCategory, SignalType
from pr_reviewer.models.feedback_signal import FeedbackSignal

if TYPE_CHECKING:
    from pr_reviewer.store.feedback_store import FeedbackStore

_logger = get_logger(__name__)

_SUPPORTED_EVENTS = frozenset({"pull_request_review_comment", "pull_request_review"})

_POSITIVE_MARKERS = ("applied in commit", "suggestion accepted", "suggestion applied")
_NEGATIVE_MARKERS = ("won't fix", "wontfix", "not applicable", "by design")


class FeedbackProcessor:
    def __init__(self, feedback_store: "FeedbackStore", secret_scrubber: Any) -> None:
        self._store = feedback_store
        self._scrubber = secret_scrubber

    def process(self, event_type: str, payload: dict) -> None:
        if event_type not in _SUPPORTED_EVENTS:
            _logger.warning(f"Unsupported feedback event type: {event_type!r}; skipping")
            return

        body = _extract_comment_body(event_type, payload)
        scrubbed_body, _ = self._scrubber.scrub(body, source="feedback")

        signal_type = _classify_signal(event_type, payload)
        path = _extract_path(event_type, payload)
        pattern = _extract_file_path_pattern(path)
        category = _extract_finding_category(scrubbed_body)
        repo_id = payload.get("repository", {}).get("full_name", "unknown")

        signal = FeedbackSignal(
            id=uuid.uuid4(),
            repo_id=repo_id,
            finding_category=category,
            file_path_pattern=pattern,
            signal_type=signal_type,
            timestamp=datetime.now(tz=UTC),
        )
        self._store.insert(signal)


# ── Module-level helpers (importable for direct testing) ─────────────────────


def _classify_signal(event_type: str, payload: dict) -> SignalType:
    if event_type == "pull_request_review":
        state = payload.get("review", {}).get("state", "").lower()
        if state == "approved":
            return SignalType.positive
        return SignalType.negative

    # pull_request_review_comment
    action = payload.get("action", "")
    body = (payload.get("comment", {}).get("body", "") or "").lower()

    for marker in _POSITIVE_MARKERS:
        if marker in body:
            return SignalType.positive

    for marker in _NEGATIVE_MARKERS:
        if marker in body:
            return SignalType.negative

    if action == "resolved":
        return SignalType.negative

    return SignalType.positive


def _extract_file_path_pattern(path: str) -> str:
    parts = path.rsplit("/", maxsplit=1)
    if len(parts) == 1:
        return "**"
    directory = parts[0]
    dir_parts = directory.split("/")
    anchor = "/".join(dir_parts[:2])
    return anchor + "/**"


def _extract_finding_category(body: str) -> ReviewCategory:
    lower = body.lower()
    if "security" in lower or "injection" in lower or "xss" in lower:
        return ReviewCategory.security
    if "performance" in lower or "slow" in lower or "latency" in lower:
        return ReviewCategory.performance
    if "style" in lower or "format" in lower or "naming" in lower:
        return ReviewCategory.style
    return ReviewCategory.bugs


def _extract_comment_body(event_type: str, payload: dict) -> str:
    if event_type == "pull_request_review":
        return payload.get("review", {}).get("body", "") or ""
    return payload.get("comment", {}).get("body", "") or ""


def _extract_path(event_type: str, payload: dict) -> str:
    if event_type == "pull_request_review_comment":
        return payload.get("comment", {}).get("path", "unknown") or "unknown"
    return "unknown"
