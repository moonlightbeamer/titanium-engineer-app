"""Unit tests for config completeness — task 29 (KB corpus toggles, indexer scope/schedule)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pr_reviewer.config.schema import Config, KnowledgeBaseConfig


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_kb(kb_config: KnowledgeBaseConfig | None = None) -> object:
    from pr_reviewer.kb.knowledge_base import KnowledgeBase

    chroma = MagicMock()
    col = MagicMock()
    chroma.get_or_create_collection.return_value = col
    cfg = Config(knowledge_base=kb_config or KnowledgeBaseConfig())
    return KnowledgeBase(chroma_client=chroma, config=cfg)


def _make_ctx(config: Config) -> MagicMock:
    from pr_reviewer.agents.review_agent import ReviewContext
    from uuid import uuid4

    return ReviewContext(
        github_client=MagicMock(),
        knowledge_base=MagicMock(),
        mcp_client=MagicMock(),
        secret_scrubber=MagicMock(),
        repo="org/repo",
        pr_number=1,
        job_id=uuid4(),
    )


def _make_indexer(config: Config) -> object:
    from pr_reviewer.workers.indexer import Indexer

    gh = MagicMock()
    gh.get_branch_head_sha.return_value = "abc123"
    db = MagicMock()
    conn = MagicMock()
    db.connect.return_value.__enter__ = MagicMock(return_value=conn)
    db.connect.return_value.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.scalar.return_value = 1  # has successful job
    store = MagicMock()
    store.list_versions.return_value = []
    return Indexer(
        github_client=gh, db_engine=db, index_store=store, config=config
    ), gh, store


# ── Task 29.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_corpus_toggle_coding_guidelines_disables_org_guidelines():
    from pr_reviewer.kb.knowledge_base import _CORPUS_CONFIG_ATTR, KnowledgeBase

    kb_cfg = KnowledgeBaseConfig(coding_guidelines=False)
    kb = _make_kb(kb_cfg)
    assert not kb._corpus_enabled("org_guidelines")


# ── Task 29.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_corpus_toggle_fix_knowledge_base_disables_collection():
    kb_cfg = KnowledgeBaseConfig(fix_knowledge_base=False)
    kb = _make_kb(kb_cfg)
    assert not kb._corpus_enabled("fix_knowledge_base")


# ── Task 29.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_corpus_toggle_lessons_learned_disables_collection():
    kb_cfg = KnowledgeBaseConfig(lessons_learned=False)
    kb = _make_kb(kb_cfg)
    assert not kb._corpus_enabled("lessons_learned")


# ── Task 29.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_lookup_cve_skipped_when_live_cve_lookup_false():
    from pr_reviewer.agents.tool_budget import ToolBudgetMiddleware
    from pr_reviewer.agents.tools import create_tools

    cfg = Config(knowledge_base=KnowledgeBaseConfig(live_cve_lookup=False))
    ctx = _make_ctx(cfg)
    budget = ToolBudgetMiddleware(20)
    tools_list = create_tools(ctx, budget, [], config=cfg)
    tool_map = {t.name: t for t in tools_list}

    result = tool_map["lookup_cve"].func(cve_id="CVE-2024-1234")
    assert result == []
    ctx.mcp_client.lookup_cve.assert_not_called()


# ── Task 29.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_check_package_advisory_skipped_when_live_package_advisory_false():
    from pr_reviewer.agents.tool_budget import ToolBudgetMiddleware
    from pr_reviewer.agents.tools import create_tools

    cfg = Config(knowledge_base=KnowledgeBaseConfig(live_package_advisory=False))
    ctx = _make_ctx(cfg)
    budget = ToolBudgetMiddleware(20)
    tools_list = create_tools(ctx, budget, [], config=cfg)
    tool_map = {t.name: t for t in tools_list}

    result = tool_map["check_package_advisory"].func(package="requests")
    assert result == []
    ctx.mcp_client.check_package_advisory.assert_not_called()


# ── Task 29.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_index_scope_single_skips_monorepo_detection():
    from pr_reviewer.workers.indexer import _detect_monorepo

    cfg = Config(index_scope="single")
    indexer, gh, store = _make_indexer(cfg)

    with patch(
        "pr_reviewer.workers.indexer._detect_monorepo", return_value=[]
    ) as mock_detect:
        indexer.refresh("org/repo", installation_id=1)
        mock_detect.assert_not_called()

    store.save.assert_called_once()
    saved_index = store.save.call_args[0][0]
    from pr_reviewer.models.codebase_index import IndexScope
    assert saved_index.scope == IndexScope.single


# ── Task 29.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_index_scope_monorepo_forces_monorepo_path():
    """index_scope=monorepo uses the monorepo code path even when _detect_monorepo returns []."""
    cfg = Config(index_scope="monorepo")
    indexer, gh, store = _make_indexer(cfg)
    gh.list_directory.return_value = []

    with patch(
        "pr_reviewer.workers.indexer._detect_monorepo", return_value=[]
    ):
        indexer.refresh("org/repo", installation_id=1)

    store.save.assert_called_once()
    saved_index = store.save.call_args[0][0]
    from pr_reviewer.models.codebase_index import IndexScope
    assert saved_index.scope == IndexScope.monorepo


# ── Task 29.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_index_refresh_schedule_on_merge_skips_beat_triggered_run():
    from pr_reviewer.workers.indexer import _run_index_refresh

    cfg = Config(index_refresh_schedule="on_merge")
    redis_mock = MagicMock()

    with patch(
        "pr_reviewer.workers.indexer._store_last_refresh"
    ) as mock_store:
        _run_index_refresh("org/repo", 1, config=cfg, redis_client=redis_mock)
        mock_store.assert_not_called()


# ── Task 29.9 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_index_refresh_schedule_weekly_skips_if_refreshed_within_7_days():
    from pr_reviewer.workers.indexer import _run_index_refresh

    cfg = Config(index_refresh_schedule="weekly")
    redis_mock = MagicMock()

    with patch(
        "pr_reviewer.workers.indexer._get_last_refresh_days", return_value=5
    ), patch(
        "pr_reviewer.workers.indexer._store_last_refresh"
    ) as mock_store:
        _run_index_refresh("org/repo", 1, config=cfg, redis_client=redis_mock)
        mock_store.assert_not_called()


# ── Task 29.10 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_index_refresh_schedule_weekly_runs_if_refreshed_8_days_ago():
    from pr_reviewer.workers.indexer import _run_index_refresh

    cfg = Config(index_refresh_schedule="weekly")
    redis_mock = MagicMock()

    with patch(
        "pr_reviewer.workers.indexer._get_last_refresh_days", return_value=8
    ), patch(
        "pr_reviewer.workers.indexer._store_last_refresh"
    ) as mock_store:
        _run_index_refresh("org/repo", 1, config=cfg, redis_client=redis_mock)
        mock_store.assert_called_once_with(redis_mock, "org/repo")
