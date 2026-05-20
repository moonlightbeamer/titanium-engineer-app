"""Create codebase_indexes table

Revision ID: 008
Revises: 007
Create Date: 2025-01-01 00:04:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "codebase_indexes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("commit_sha", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("package_path", sa.String(), nullable=True),
        sa.Column("is_valid", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_codebase_indexes_lookup",
        "codebase_indexes",
        ["repo_id", "package_path", "is_valid", sa.text("version DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_codebase_indexes_lookup", table_name="codebase_indexes")
    op.drop_table("codebase_indexes")
