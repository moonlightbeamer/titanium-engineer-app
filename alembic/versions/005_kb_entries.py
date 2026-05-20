"""Create knowledge_base_entries table

Revision ID: 005
Revises: 004
Create Date: 2025-01-01 00:03:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_base_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("corpus", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("problem_description", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("code_pattern", sa.Text(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column(
            "model_version",
            sa.String(),
            nullable=False,
            server_default="text-embedding-3-small",
        ),
        sa.Column("is_draft", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Partial unique index: only one is_active=TRUE per (corpus, version)
    op.execute(
        """
        CREATE UNIQUE INDEX ix_kb_entries_one_active_per_version
        ON knowledge_base_entries (corpus, version)
        WHERE is_active = TRUE
        """
    )


def downgrade() -> None:
    op.drop_index("ix_kb_entries_one_active_per_version", table_name="knowledge_base_entries")
    op.drop_table("knowledge_base_entries")
