"""Database connection and metadata for the eval harness.

Standalone module — no application package imports.
Connects directly to the shared PostgreSQL database via DATABASE_URL.
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy import MetaData

metadata = MetaData()

eval_runs = sa.Table(
    "eval_runs",
    metadata,
    sa.Column("id", sa.UUID(), primary_key=True),
    sa.Column("run_type", sa.Text(), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("report", sa.JSON(), nullable=True),
    sa.Column("corpus_version", sa.Text(), nullable=True),
)

vibe_scores = sa.Table(
    "vibe_scores",
    metadata,
    sa.Column("id", sa.UUID(), primary_key=True),
    sa.Column("eval_run_id", sa.UUID(), nullable=False),
    sa.Column("finding_id", sa.UUID(), nullable=False),
    sa.Column("human_score", sa.Integer(), nullable=False),
    sa.Column("cot_score", sa.Float(), nullable=True),
    sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
)


def get_engine() -> sa.Engine:
    url = os.environ.get("DATABASE_URL", "sqlite:///:memory:")
    return sa.create_engine(url)
