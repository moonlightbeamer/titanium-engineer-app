"""FeedbackStore — persists and retrieves FeedbackSignal rows via SQLAlchemy Core."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from pr_reviewer.models.enums import ReviewCategory, SignalType
from pr_reviewer.models.feedback_signal import FeedbackSignal

_TABLE = sa.Table(
    "feedback_signals",
    sa.MetaData(),
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("repo_id", sa.String, nullable=False),
    sa.Column("finding_category", sa.String, nullable=False),
    sa.Column("file_path_pattern", sa.String, nullable=False),
    sa.Column("signal_type", sa.String, nullable=False),
    sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
)


class FeedbackStore:
    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine
        _TABLE.metadata.create_all(engine)

    def insert(self, signal: FeedbackSignal) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                _TABLE.insert().values(
                    id=str(signal.id),
                    repo_id=signal.repo_id,
                    finding_category=str(signal.finding_category),
                    file_path_pattern=signal.file_path_pattern,
                    signal_type=str(signal.signal_type),
                    timestamp=signal.timestamp,
                )
            )

    def query_recent(
        self,
        repo_id: str,
        file_path_patterns: list[str],
        limit: int = 5,
    ) -> list[FeedbackSignal]:
        stmt = (
            sa.select(_TABLE)
            .where(_TABLE.c.repo_id == sa.bindparam("repo_id"))
            .order_by(_TABLE.c.timestamp.desc())
            .limit(limit)
        )
        if file_path_patterns:
            stmt = stmt.where(
                _TABLE.c.file_path_pattern.in_(file_path_patterns)
            )

        with self._engine.connect() as conn:
            rows = conn.execute(stmt, {"repo_id": repo_id}).fetchall()

        return [_row_to_signal(row) for row in rows]


def _row_to_signal(row: sa.Row) -> FeedbackSignal:
    return FeedbackSignal(
        id=uuid.UUID(row.id),
        repo_id=row.repo_id,
        finding_category=ReviewCategory(row.finding_category),
        file_path_pattern=row.file_path_pattern,
        signal_type=SignalType(row.signal_type),
        timestamp=_ensure_utc(row.timestamp),
    )


def _ensure_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts
