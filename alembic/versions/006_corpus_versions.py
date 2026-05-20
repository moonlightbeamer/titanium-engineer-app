"""Create corpus_versions table

Revision ID: 006
Revises: 005
Create Date: 2025-01-01 00:04:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "corpus_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("corpus", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("corpus", "version", name="uq_corpus_versions_corpus_version"),
    )


def downgrade() -> None:
    op.drop_table("corpus_versions")
