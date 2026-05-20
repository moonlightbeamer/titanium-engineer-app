"""Create findings table

Revision ID: 002
Revises: 001
Create Date: 2025-01-01 00:01:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "findings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("confidence", sa.String(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("is_escalation", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("related_finding_ids", sa.ARRAY(sa.UUID()), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_findings_job_id", "findings", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_findings_job_id", table_name="findings")
    op.drop_table("findings")
