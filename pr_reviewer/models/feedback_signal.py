"""FeedbackSignal domain model."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pr_reviewer.models.enums import ReviewCategory, SignalType


@dataclass(frozen=True)
class FeedbackSignal:
    id: UUID
    repo_id: str
    finding_category: ReviewCategory
    file_path_pattern: str
    signal_type: SignalType
    timestamp: datetime
    # Intentionally no code/diff/snippet fields — Req 9.7
