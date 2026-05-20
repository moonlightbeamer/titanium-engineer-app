"""Unit tests for CodebaseIndex model and migration (tasks 22.1–22.6)."""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa


# ── Task 22.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_codebase_index_model_is_frozen():
    """CodebaseIndex raises FrozenInstanceError on field assignment."""
    from pr_reviewer.models.codebase_index import CodebaseIndex, IndexScope

    idx = CodebaseIndex(
        id=uuid4(),
        repo_id="org/repo",
        commit_sha="abc123",
        scope=IndexScope.single,
        content="{}",
    )
    with pytest.raises(FrozenInstanceError):
        idx.repo_id = "other"  # type: ignore[misc]


# ── Task 22.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_index_scope_enum_values():
    """IndexScope has exactly 'single' and 'monorepo'."""
    from pr_reviewer.models.codebase_index import IndexScope

    values = {e.value for e in IndexScope}
    assert values == {"single", "monorepo"}
    assert len(list(IndexScope)) == 2


# ── Task 22.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_package_path_nullable():
    """CodebaseIndex with package_path=None is valid for single-repo."""
    from pr_reviewer.models.codebase_index import CodebaseIndex, IndexScope

    idx = CodebaseIndex(
        id=uuid4(),
        repo_id="org/repo",
        commit_sha="abc123",
        scope=IndexScope.single,
        content="{}",
        package_path=None,
    )
    assert idx.package_path is None


# ── Task 22.5 / 22.1 ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_codebase_indexes_migration_applies_and_rolls_back():
    """Migration creates codebase_indexes table; downgrade removes it."""
    import importlib

    migration_path = (
        Path(__file__).parent.parent.parent
        / "alembic"
        / "versions"
        / "008_codebase_indexes.py"
    )
    assert migration_path.exists(), "Migration 008_codebase_indexes.py must exist"

    spec = importlib.util.spec_from_file_location("migration_008", migration_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]

    engine = sa.create_engine("sqlite:///:memory:")

    class _FakeOp:
        def __init__(self, conn):
            self._conn = conn
            self._tables: dict = {}

        def create_table(self, name, *cols, **kw):
            # map alembic columns to SQLAlchemy columns for SQLite
            sa_cols = []
            for c in cols:
                if isinstance(c, sa.Column):
                    col = sa.Column(
                        c.name,
                        sa.Text() if isinstance(c.type, sa.UUID) else c.type,
                        nullable=c.nullable,
                    )
                    sa_cols.append(col)
            tbl = sa.Table(name, sa.MetaData(), *sa_cols)
            tbl.create(bind=self._conn)
            self._tables[name] = tbl

        def drop_table(self, name):
            tbl = self._tables.get(name)
            if tbl is not None:
                tbl.drop(bind=self._conn)

        def create_index(self, name, table, cols, **kw):
            pass

        def drop_index(self, name, **kw):
            pass

    with engine.begin() as conn:
        fake_op = _FakeOp(conn)
        import alembic.op as _alembic_op

        # Patch op on the module we're about to load
        import unittest.mock as mock

        with mock.patch.object(_alembic_op, "create_table", fake_op.create_table), \
             mock.patch.object(_alembic_op, "drop_table", fake_op.drop_table), \
             mock.patch.object(_alembic_op, "create_index", fake_op.create_index), \
             mock.patch.object(_alembic_op, "drop_index", fake_op.drop_index):
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            mod.upgrade()

            inspector = sa.inspect(conn)
            assert "codebase_indexes" in inspector.get_table_names()

            mod.downgrade()
            inspector2 = sa.inspect(conn)
            assert "codebase_indexes" not in inspector2.get_table_names()


# ── Task 22.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_codebase_index_has_all_required_fields():
    """CodebaseIndex has id, repo_id, commit_sha, scope, content, package_path, is_valid, version, token_count, created_at."""
    from pr_reviewer.models.codebase_index import CodebaseIndex, IndexScope

    idx = CodebaseIndex(
        id=uuid4(),
        repo_id="org/repo",
        commit_sha="abc123",
        scope=IndexScope.monorepo,
        content='{"convention_profile": {}}',
        package_path="packages/api",
        is_valid=True,
        version=2,
        token_count=500,
    )
    assert idx.version == 2
    assert idx.token_count == 500
    assert idx.package_path == "packages/api"
    assert isinstance(idx.created_at, datetime)
