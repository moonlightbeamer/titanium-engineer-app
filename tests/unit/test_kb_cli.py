"""Unit tests for Knowledge Base CLI (task 21)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from click.testing import CliRunner
from sqlalchemy import text


@pytest.fixture
def engine():
    """In-memory SQLite engine with KB tables created."""
    from pr_reviewer.kb.cli import _create_tables

    eng = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    _create_tables(eng)
    return eng


def _invoke(engine, args, input_data=None):
    from pr_reviewer.kb.cli import kb

    runner = CliRunner()
    input_str = json.dumps(input_data) if input_data is not None else None
    return runner.invoke(kb, args, obj={"engine": engine}, input=input_str, catch_exceptions=False)


def _valid_entry_json(**overrides):
    base = {
        "corpus": "cve_snapshot",
        "category": "security",
        "content": "This is a detailed description of the vulnerability and its context.",
        "problem_description": "A fifty-character-or-longer problem description here is valid.",
        "resolution": "Update the affected dependency to a patched version immediately.",
    }
    base.update(overrides)
    return base


def _insert_entry(engine, **kwargs):
    """Insert an entry directly for test setup."""
    row = {
        "id": str(uuid.uuid4()),
        "corpus": "cve_snapshot",
        "category": "security",
        "content": "test content",
        "problem_description": "problem description that is at least fifty characters.",
        "resolution": "Fix this vulnerability by applying the recommended mitigation steps.",
        "code_pattern": None,
        "language": None,
        "model_version": "text-embedding-3-small",
        "is_draft": False,
        "is_active": True,
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
    }
    row.update(kwargs)
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO knowledge_base_entries "
                "(id,corpus,category,content,problem_description,resolution,"
                "code_pattern,language,model_version,is_draft,is_active,version,created_at) "
                "VALUES (:id,:corpus,:category,:content,:problem_description,:resolution,"
                ":code_pattern,:language,:model_version,:is_draft,:is_active,:version,:created_at)"
            ),
            row,
        )
        conn.commit()
    return row["id"]


# ── Task 21.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_add_lessons_learned_requires_four_fields(engine):
    """JSON missing 'resolution' → validation error; not inserted."""
    data = _valid_entry_json()
    del data["resolution"]

    result = _invoke(engine, ["add"], input_data=data)

    assert result.exit_code != 0 or "resolution" in result.output.lower() or "required" in result.output.lower()
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM knowledge_base_entries")).scalar()
    assert count == 0


# ── Task 21.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_add_lessons_learned_rejects_field_below_50_chars(engine):
    """problem_description shorter than 50 chars → error mentioning '50 characters'."""
    data = _valid_entry_json(problem_description="Too short.")  # 10 chars

    result = _invoke(engine, ["add"], input_data=data)

    assert result.exit_code != 0 or "50" in result.output
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM knowledge_base_entries")).scalar()
    assert count == 0


# ── Task 21.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_add_lessons_learned_rejects_raw_code_in_code_pattern(engine):
    """code_pattern with >3 code-like lines → error 'abstract description required'."""
    # Four lines matching the code-detection regex (def/class/import/function)
    code_pattern = "\n".join(
        [
            "def authenticate(user):",
            "class AuthManager:",
            "    import hashlib",
            "    def generate_token():",
            "        pass",
        ]
    )
    data = _valid_entry_json(code_pattern=code_pattern)

    result = _invoke(engine, ["add"], input_data=data)

    assert result.exit_code != 0 or "abstract" in result.output.lower()
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM knowledge_base_entries")).scalar()
    assert count == 0


# ── Task 21.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_add_with_draft_flag_requires_approval(engine):
    """kb add --draft → is_draft=True in DB; kb list does not return it."""
    data = _valid_entry_json()

    result = _invoke(engine, ["add", "--draft"], input_data=data)

    assert result.exit_code == 0
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT is_draft FROM knowledge_base_entries LIMIT 1")
        ).fetchone()
    assert row is not None
    assert bool(row[0]) is True  # is_draft=True

    list_result = _invoke(engine, ["list"])
    assert list_result.exit_code == 0
    assert "cve_snapshot" not in list_result.output or "draft" in list_result.output.lower()


# ── Task 21.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_approve_sets_is_draft_false(engine):
    """kb approve {id} → is_draft=False; entry returned by kb list."""
    entry_id = _insert_entry(engine, is_draft=True)

    result = _invoke(engine, ["approve", entry_id])

    assert result.exit_code == 0
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT is_draft FROM knowledge_base_entries WHERE id=:id"),
            {"id": entry_id},
        ).fetchone()
    assert bool(row[0]) is False


# ── Task 21.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_deprecate_sets_is_active_false_entry_remains_in_db(engine):
    """kb deprecate {id} → is_active=False; row still in DB."""
    entry_id = _insert_entry(engine, is_active=True)

    result = _invoke(engine, ["deprecate", entry_id])

    assert result.exit_code == 0
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT is_active FROM knowledge_base_entries WHERE id=:id"),
            {"id": entry_id},
        ).fetchone()
    assert row is not None
    assert bool(row[0]) is False


# ── Task 21.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_deprecated_entry_not_returned_by_kb_query(engine):
    """Deprecated entry excluded from kb list output."""
    entry_id = _insert_entry(engine, is_active=False, content="DEPRECATED_UNIQUE_CONTENT")

    list_result = _invoke(engine, ["list"])

    assert list_result.exit_code == 0
    assert "DEPRECATED_UNIQUE_CONTENT" not in list_result.output


# ── Task 21.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_rollback_activates_target_version(engine):
    """kb rollback --corpus cve_snapshot --version 2 → v2 active, v3 inactive."""
    _insert_entry(engine, version=2, is_active=False, id=str(uuid.uuid4()))
    _insert_entry(engine, version=3, is_active=True, id=str(uuid.uuid4()))

    result = _invoke(engine, ["rollback", "--corpus", "cve_snapshot", "--version", "2"])

    assert result.exit_code == 0
    with engine.connect() as conn:
        v2 = conn.execute(
            text("SELECT is_active FROM knowledge_base_entries WHERE corpus='cve_snapshot' AND version=2")
        ).fetchall()
        v3 = conn.execute(
            text("SELECT is_active FROM knowledge_base_entries WHERE corpus='cve_snapshot' AND version=3")
        ).fetchall()
    assert all(bool(r[0]) for r in v2), "version 2 should be active"
    assert not any(bool(r[0]) for r in v3), "version 3 should be inactive"


# ── Task 21.9 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_rollback_retains_last_5_versions(engine):
    """6 versions exist → versions 2–6 all retained in DB (rows not deleted)."""
    for v in range(1, 7):
        _insert_entry(engine, version=v, is_active=(v == 6), id=str(uuid.uuid4()))

    result = _invoke(engine, ["rollback", "--corpus", "cve_snapshot", "--version", "5"])

    assert result.exit_code == 0
    with engine.connect() as conn:
        for v in range(2, 7):
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM knowledge_base_entries WHERE corpus='cve_snapshot' AND version={v}")
            ).scalar()
            assert count > 0, f"Version {v} should still have rows in DB"


# ── Task 21.10 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_reembed_updates_model_version_on_all_active_entries(engine):
    """kb reembed --corpus all → all is_active=True entries get new model_version."""
    _insert_entry(engine, is_active=True, model_version="old-model", id=str(uuid.uuid4()))
    _insert_entry(engine, is_active=True, model_version="old-model", id=str(uuid.uuid4()))
    _insert_entry(engine, is_active=False, model_version="old-model", id=str(uuid.uuid4()))

    result = _invoke(engine, ["reembed", "--corpus", "all", "--model-version", "text-embedding-3-large"])

    assert result.exit_code == 0
    with engine.connect() as conn:
        active_old = conn.execute(
            text("SELECT COUNT(*) FROM knowledge_base_entries WHERE is_active=1 AND model_version='old-model'")
        ).scalar()
        inactive_old = conn.execute(
            text("SELECT COUNT(*) FROM knowledge_base_entries WHERE is_active=0 AND model_version='old-model'")
        ).scalar()
    assert active_old == 0, "all active entries should have new model_version"
    assert inactive_old == 1, "inactive entry should remain unchanged"


# ── Task 21.11 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_bootstrap_seeds_min_cve_and_guidelines(engine):
    """kb bootstrap on empty DB → cve_snapshot ≥5 entries; org_guidelines ≥1."""
    result = _invoke(engine, ["bootstrap"])

    assert result.exit_code == 0
    with engine.connect() as conn:
        cve_count = conn.execute(
            text("SELECT COUNT(*) FROM knowledge_base_entries WHERE corpus='cve_snapshot'")
        ).scalar()
        guidelines_count = conn.execute(
            text("SELECT COUNT(*) FROM knowledge_base_entries WHERE corpus='org_guidelines'")
        ).scalar()
    assert cve_count >= 5
    assert guidelines_count >= 1
