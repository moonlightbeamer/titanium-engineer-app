"""Create eval_corpus_health table

Revision ID: 009
Revises: 008
Create Date: 2025-01-01 00:05:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "eval_corpus_health",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("corpus", sa.Text(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("mean_relevance", sa.Float(), nullable=False),
        sa.Column("is_flagged", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_eval_corpus_health_corpus",
        "eval_corpus_health",
        ["corpus", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_eval_corpus_health_corpus", table_name="eval_corpus_health")
    op.drop_table("eval_corpus_health")
