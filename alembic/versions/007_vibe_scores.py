"""Create vibe_scores table

Revision ID: 007
Revises: 006
Create Date: 2025-01-01 00:04:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vibe_scores",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("eval_run_id", sa.UUID(), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("human_score", sa.Integer(), nullable=False),
        sa.Column("cot_score", sa.Float(), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vibe_scores_eval_run_id", "vibe_scores", ["eval_run_id"])


def downgrade() -> None:
    op.drop_index("ix_vibe_scores_eval_run_id", table_name="vibe_scores")
    op.drop_table("vibe_scores")
