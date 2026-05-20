"""Create feedback_signals table

Revision ID: 003
Revises: 002
Create Date: 2025-01-01 00:02:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback_signals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("finding_category", sa.String(), nullable=False),
        sa.Column("file_path_pattern", sa.String(), nullable=False),
        sa.Column("signal_type", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_signals_repo_id", "feedback_signals", ["repo_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_signals_repo_id", table_name="feedback_signals")
    op.drop_table("feedback_signals")
