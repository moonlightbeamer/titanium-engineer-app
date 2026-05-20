"""Tests for cross-repository fix corpus (task 27)."""

from __future__ import annotations

import uuid
from datetime import datetime, UTC
from unittest.mock import MagicMock, call

import pytest

from pr_reviewer.models.enums import ReviewCategory, SignalType


def _make_signal(
    signal_type: SignalType = SignalType.positive,
    repo_id: str = "org/repo",
) -> object:
    from pr_reviewer.models.feedback_signal import FeedbackSignal

    return FeedbackSignal(
        id=uuid.uuid4(),
        repo_id=repo_id,
        finding_category=ReviewCategory.security,
        file_path_pattern="src/auth/**",
        signal_type=signal_type,
        timestamp=datetime.now(tz=UTC),
    )


def _make_cross_repo(*, chromadb=None, config=None, secret_scrubber=None) -> object:
    from pr_reviewer.kb.cross_repo import CrossRepoLearning
    from pr_reviewer.config.schema import Config

    chromadb = chromadb or MagicMock()
    config = config or Config(cross_repo_sharing=True)
    secret_scrubber = secret_scrubber or MagicMock(
        scrub=lambda content, **kw: (content, [])
    )
    return CrossRepoLearning(
        chromadb_client=chromadb,
        config=config,
        secret_scrubber=secret_scrubber,
    )


# ── Task 27.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_positive_signal_with_cross_repo_enabled_calls_add_cross_repo():
    """positive signal + cross_repo_sharing=True → add_cross_repo_fix invoked."""
    from pr_reviewer.config.schema import Config
    from pr_reviewer.kb.cross_repo import CrossRepoLearning
    from pr_reviewer.store.feedback_store import FeedbackStore
    from pr_reviewer.workers.feedback_processor import FeedbackProcessor

    config = Config(cross_repo_sharing=True)
    cross_repo = MagicMock(spec=CrossRepoLearning)
    feedback_store = MagicMock(spec=FeedbackStore)
    secret_scrubber = MagicMock(scrub=MagicMock(return_value=("abstract fix", [])))

    processor = FeedbackProcessor(
        feedback_store=feedback_store,
        secret_scrubber=secret_scrubber,
        config=config,
        cross_repo_learning=cross_repo,
    )
    payload = {
        "action": "resolved",
        "comment": {
            "body": "applied in commit abc",
            "path": "src/auth/login.py",
        },
        "repository": {"full_name": "org/repo"},
    }
    processor.process("pull_request_review_comment", payload)

    cross_repo.add_cross_repo_fix.assert_called_once()


# ── Task 27.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cross_repo_sharing_false_does_not_call_add_cross_repo():
    """cross_repo_sharing=False → add_cross_repo_fix never called."""
    from pr_reviewer.config.schema import Config
    from pr_reviewer.kb.cross_repo import CrossRepoLearning
    from pr_reviewer.workers.feedback_processor import FeedbackProcessor

    config = Config(cross_repo_sharing=False)
    cross_repo = MagicMock(spec=CrossRepoLearning)
    feedback_store = MagicMock()
    secret_scrubber = MagicMock(scrub=MagicMock(return_value=("body", [])))

    processor = FeedbackProcessor(
        feedback_store=feedback_store,
        secret_scrubber=secret_scrubber,
        config=config,
        cross_repo_learning=cross_repo,
    )
    payload = {
        "action": "resolved",
        "comment": {"body": "applied in commit abc", "path": "src/auth/login.py"},
        "repository": {"full_name": "org/repo"},
    }
    processor.process("pull_request_review_comment", payload)

    cross_repo.add_cross_repo_fix.assert_not_called()


# ── Task 27.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_add_cross_repo_fix_stores_abstract_pattern_not_code():
    """Content with ≤3 code lines is accepted and added to chromadb collection."""
    chromadb = MagicMock()
    collection = MagicMock()
    chromadb.get_or_create_collection.return_value = collection

    cr = _make_cross_repo(chromadb=chromadb)
    signal = _make_signal()
    cr.add_cross_repo_fix(
        signal=signal,
        content="Always validate user input before using it in queries.",
        finding_category="security",
        language="python",
        vulnerability_type="injection",
    )

    collection.add.assert_called_once()


# ── Task 27.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_code_concreteness_classifier_rejects_entry_with_4_code_lines():
    """Content with 4 code-syntax lines → ValueError raised; chromadb not touched."""
    from pr_reviewer.kb.cross_repo import CrossRepoLearning

    chromadb = MagicMock()
    cr = _make_cross_repo(chromadb=chromadb)

    # 4 lines that match Python code-syntax patterns
    content = (
        "def validate(x):\n"   # def keyword
        "    import re\n"       # import keyword
        "    from os import path\n"  # from keyword
        "    class Inner: pass\n"   # class keyword
    )
    with pytest.raises(ValueError, match="abstract description required"):
        cr._check_code_concreteness(content)

    chromadb.get_or_create_collection.return_value.add.assert_not_called()


# ── Task 27.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_code_concreteness_classifier_accepts_entry_with_3_code_lines():
    """Content with exactly 3 code-syntax lines → accepted (no ValueError)."""
    cr = _make_cross_repo()
    # exactly 3 code-like lines (def, import, from)
    content = "def check(x):\n    import os\n    from sys import path"
    cr._check_code_concreteness(content)  # must not raise


# ── Task 27.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cross_repo_entry_tagged_with_language_category_and_type():
    """Stored entry metadata includes language, category, vulnerability_type, installation_id."""
    chromadb = MagicMock()
    collection = MagicMock()
    chromadb.get_or_create_collection.return_value = collection

    cr = _make_cross_repo(chromadb=chromadb)
    signal = _make_signal()
    # Attach installation_id to signal mock-like
    signal_with_install = MagicMock()
    signal_with_install.repo_id = "org/repo"
    signal_with_install.signal_type = SignalType.positive

    cr.add_cross_repo_fix(
        signal=signal_with_install,
        content="Validate inputs at API boundary.",
        finding_category="security",
        language="python",
        vulnerability_type="injection",
        installation_id=42,
    )

    add_call = collection.add.call_args
    metadatas = add_call.kwargs.get("metadatas") or (add_call[1].get("metadatas") if add_call[1] else add_call[0][2] if len(add_call[0]) > 2 else [{}])
    meta = metadatas[0] if metadatas else {}
    assert meta.get("language") == "python"
    assert meta.get("category") == "security"
    assert meta.get("vulnerability_type") == "injection"
    assert meta.get("installation_id") == 42


# ── Task 27.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_rollback_to_previous_version_excludes_newer_entries():
    """After rollback to v2, KnowledgeBase.query filters out entries with version > 2."""
    from pr_reviewer.kb.cross_repo import CrossRepoLearning

    chromadb = MagicMock()
    collection = MagicMock()
    chromadb.get_or_create_collection.return_value = collection

    # Simulate that get() returns entries with versions 1, 2, 3
    collection.get.return_value = {
        "ids": ["id1", "id2", "id3"],
        "metadatas": [
            {"version": 1, "is_active": True},
            {"version": 2, "is_active": True},
            {"version": 3, "is_active": True},
        ],
    }

    cr = _make_cross_repo(chromadb=chromadb)
    cr.rollback(corpus="cross_repo_fixes", target_version=2)

    # id3 (version 3) should be deactivated
    collection.update.assert_called()
    update_call = collection.update.call_args_list
    updated_ids = [c.kwargs.get("ids") or c[1].get("ids") or c[0][0] for c in update_call]
    all_updated = [i for sublist in updated_ids for i in (sublist if isinstance(sublist, list) else [sublist])]
    assert "id3" in all_updated


# ── Task 27.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_corpus_retains_last_5_versions():
    """6 versions → version 1 deactivated, versions 2-6 retained."""
    from pr_reviewer.kb.cross_repo import CrossRepoLearning

    chromadb = MagicMock()
    collection = MagicMock()
    chromadb.get_or_create_collection.return_value = collection

    collection.get.return_value = {
        "ids": [f"id{i}" for i in range(1, 7)],
        "metadatas": [{"version": i, "is_active": True} for i in range(1, 7)],
    }

    cr = _make_cross_repo(chromadb=chromadb)
    cr._prune_old_versions(collection, max_versions=5)

    # Only version 1 should be deactivated
    all_update_ids: list[str] = []
    for c in collection.update.call_args_list:
        ids = c.kwargs.get("ids") or (c[1].get("ids") if c[1] else c[0][0] if c[0] else [])
        if isinstance(ids, list):
            all_update_ids.extend(ids)
        elif isinstance(ids, str):
            all_update_ids.append(ids)
    assert "id1" in all_update_ids
    assert "id2" not in all_update_ids


# ── Task 27.9 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_query_with_weight_produces_different_ranking_than_without():
    """python weight 1.5 vs no weight → ranking differs for Python entries."""
    from pr_reviewer.kb.knowledge_base import KBEntry, _apply_language_weight

    entry_python = KBEntry(
        id="py1",
        content="Use parameterized queries in Python",
        corpus="cross_repo_fixes",
        language_tag="python",
        category="security",
        score=0.8,
        model_version="text-embedding-3-small",
    )
    entry_go = KBEntry(
        id="go1",
        content="Use parameterized queries in Go",
        corpus="cross_repo_fixes",
        language_tag="go",
        category="security",
        score=0.8,
        model_version="text-embedding-3-small",
    )

    weighted = _apply_language_weight(
        [entry_python, entry_go],
        language_corpus_weights={"python": 1.5},
    )

    python_weighted = next(e for e in weighted if e.language_tag == "python")
    go_weighted = next(e for e in weighted if e.language_tag == "go")
    assert python_weighted.score > go_weighted.score
