"""Finding domain model."""

from dataclasses import dataclass, field
from uuid import UUID

from pr_reviewer.models.enums import Confidence, ReviewCategory, Severity


@dataclass(frozen=True)
class Finding:
    id: UUID
    job_id: UUID
    file_path: str
    line_number: int
    category: ReviewCategory
    severity: Severity
    confidence: Confidence
    explanation: str
    is_escalation: bool
    start_line: int | None = None
    suggestion: str | None = None
    related_finding_ids: tuple[UUID, ...] = field(default_factory=tuple)
