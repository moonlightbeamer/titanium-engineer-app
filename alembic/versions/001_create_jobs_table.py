"""Create jobs table

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("commit_sha", sa.String(), nullable=False),
        sa.Column("last_reviewed_sha", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("context_tokens_used", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_repo_pr", "jobs", ["repo_id", "pr_number"])
    op.create_index("ix_jobs_commit_sha", "jobs", ["commit_sha"])


def downgrade() -> None:
    op.drop_index("ix_jobs_commit_sha", table_name="jobs")
    op.drop_index("ix_jobs_repo_pr", table_name="jobs")
    op.drop_table("jobs")
