"""Domain enums for the PR review service."""

from enum import StrEnum


class JobStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    complete = "complete"
    failed = "failed"
    dead_letter = "dead_letter"


class ReviewCategory(StrEnum):
    bugs = "bugs"
    security = "security"
    style = "style"
    performance = "performance"


class Severity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class Confidence(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class SignalType(StrEnum):
    positive = "positive"
    negative = "negative"
