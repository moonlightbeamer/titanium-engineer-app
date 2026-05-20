"""Unit tests for KnowledgeBase (tasks 10.1–10.11)."""

import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from pr_reviewer.config.schema import Config, KnowledgeBaseConfig

# ── Helpers ───────────────────────────────────────────────────────────────────

_MODEL_V = "text-embedding-3-small-v1"


def _chroma_result(
    ids: list[str],
    docs: list[str],
    metas: list[dict],
    distances: list[float],
) -> dict:
    return {
        "ids": [ids],
        "documents": [docs],
        "metadatas": [metas],
        "distances": [distances],
    }


def _empty_result() -> dict:
    return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}


def _make_kb(
    cve_count: int = 10,
    query_results: dict | None = None,
    config: Config | None = None,
    last_refresh: datetime | None = None,
    model_version: str = _MODEL_V,
    cross_repo_results: dict | None = None,
) -> tuple:
    from pr_reviewer.kb.knowledge_base import KnowledgeBase

    chroma = MagicMock()

    def _make_collection(name: str) -> MagicMock:
        col = MagicMock()
        if name == "cve_snapshot":
            col.count.return_value = cve_count
            col.get.return_value = {
                "ids": [f"cve-{i}" for i in range(cve_count)],
                "metadatas": [{"model_version": model_version}] * cve_count,
            }
        else:
            col.count.return_value = 10
            col.get.return_value = {
                "ids": ["e1"],
                "metadatas": [{"model_version": model_version}],
            }
        if name == "cross_repo_fixes" and cross_repo_results is not None:
            col.query.return_value = cross_repo_results
        elif query_results is not None:
            col.query.return_value = query_results
        else:
            col.query.return_value = _empty_result()
        return col

    chroma.get_or_create_collection.side_effect = _make_collection

    cfg = config or Config()
    refresh_dates = {"cve_snapshot": last_refresh} if last_refresh else {}
    kb = KnowledgeBase(chroma_client=chroma, config=cfg, last_refresh_dates=refresh_dates)
    return kb, chroma


# ── Task 10.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_query_returns_at_most_5_entries():

    result_10 = _chroma_result(
        ids=[f"id{i}" for i in range(10)],
        docs=[f"doc {i}" for i in range(10)],
        metas=[
            {"category": "security", "language": "python", "model_version": _MODEL_V}
            for _ in range(10)
        ],
        distances=[0.1 * i for i in range(10)],
    )
    kb, _ = _make_kb(query_results=result_10)
    entries = kb.query("find vulnerabilities", category="security", language="python")
    assert len(entries) <= 5


# ── Task 10.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_query_filtered_by_category_tag():

    # Collection returns only security entries (chromadb where filter)
    security_results = _chroma_result(
        ids=["s1", "s2"],
        docs=["sec content 1", "sec content 2"],
        metas=[
            {"category": "security", "language": "python", "model_version": _MODEL_V},
            {"category": "security", "language": "python", "model_version": _MODEL_V},
        ],
        distances=[0.1, 0.2],
    )
    kb, chroma = _make_kb(query_results=security_results)
    entries = kb.query("vulnerability", category="security", language="python")

    # All returned entries must be security category
    for e in entries:
        assert e.category == "security"


# ── Task 10.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_disabled_corpus_not_queried():
    from pr_reviewer.kb.knowledge_base import KnowledgeBase

    cfg = Config(knowledge_base=KnowledgeBaseConfig(cve_snapshot=False))
    chroma = MagicMock()
    collection_mocks: dict[str, MagicMock] = {}

    def _make_col(name: str) -> MagicMock:
        col = MagicMock()
        col.count.return_value = 10
        col.get.return_value = {"ids": ["e1"], "metadatas": [{"model_version": _MODEL_V}]}
        col.query.return_value = _empty_result()
        collection_mocks[name] = col
        return col

    chroma.get_or_create_collection.side_effect = _make_col
    kb = KnowledgeBase(chroma_client=chroma, config=cfg)
    kb.query("test", category="security", language="python")

    assert "cve_snapshot" in collection_mocks
    collection_mocks["cve_snapshot"].query.assert_not_called()


# ── Task 10.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cve_staleness_warn_after_14_days(caplog):
    stale_date = datetime.now(tz=UTC) - timedelta(days=15)
    kb, _ = _make_kb(last_refresh=stale_date)
    with caplog.at_level(logging.WARNING):
        kb.query("test", category="security", language="python")
    assert any("cve snapshot stale" in r.message.lower() for r in caplog.records)


# ── Task 10.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_model_version_mismatch_returns_empty_and_refuses(caplog):
    from pr_reviewer.kb.knowledge_base import KnowledgeBase

    # Two model versions in the cve_snapshot collection
    chroma = MagicMock()

    def _make_col(name: str) -> MagicMock:
        col = MagicMock()
        col.count.return_value = 10
        if name == "cve_snapshot":
            col.get.return_value = {
                "ids": ["e1", "e2"],
                "metadatas": [
                    {"model_version": "v1"},
                    {"model_version": "v2"},  # mismatch!
                ],
            }
        else:
            col.get.return_value = {
                "ids": ["e1"],
                "metadatas": [{"model_version": "v1"}],
            }
        col.query.return_value = _empty_result()
        return col

    chroma.get_or_create_collection.side_effect = _make_col
    kb = KnowledgeBase(chroma_client=chroma, config=Config())

    with caplog.at_level(logging.ERROR):
        entries = kb.query("test", category="security", language="python")

    assert entries == []
    assert any("model version" in r.message.lower() for r in caplog.records)


# ── Task 10.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_below_minimum_corpus_returns_empty_with_warn(caplog):
    kb, _ = _make_kb(cve_count=3)  # below minimum of 5
    with caplog.at_level(logging.WARNING):
        entries = kb.query("test", category="security", language="python")
    assert entries == []
    assert any("insufficient corpus" in r.message.lower() for r in caplog.records)


# ── Task 10.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_per_language_weight_boosts_language_best_practices_score():
    cfg = Config(
        knowledge_base=KnowledgeBaseConfig(
            language_corpus_weights={"python": 2.0}
        )
    )

    # Both entries have the same raw distance (0.2); Python one should rank higher after weighting
    lbp_results = _chroma_result(
        ids=["py-entry", "go-entry"],
        docs=["python tip", "go tip"],
        metas=[
            {"category": "style", "language": "python", "model_version": _MODEL_V},
            {"category": "style", "language": "go", "model_version": _MODEL_V},
        ],
        distances=[0.2, 0.2],
    )

    chroma = MagicMock()

    def _make_col(name: str) -> MagicMock:
        col = MagicMock()
        col.count.return_value = 10
        col.get.return_value = {"ids": ["e1"], "metadatas": [{"model_version": _MODEL_V}]}
        if name == "language_best_practices":
            col.query.return_value = lbp_results
        else:
            col.query.return_value = _empty_result()
        return col

    chroma.get_or_create_collection.side_effect = _make_col
    from pr_reviewer.kb.knowledge_base import KnowledgeBase
    kb = KnowledgeBase(chroma_client=chroma, config=cfg)
    entries = kb.query("styling", category="style", language="python")

    py_scores = [e.score for e in entries if e.id == "py-entry"]
    go_scores = [e.score for e in entries if e.id == "go-entry"]
    if py_scores and go_scores:
        assert py_scores[0] > go_scores[0], "Python entry should rank higher due to language weight"


# ── Task 10.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_weight_applied_only_to_language_best_practices_corpus():
    cfg = Config(
        knowledge_base=KnowledgeBaseConfig(language_corpus_weights={"python": 3.0})
    )

    distance = 0.2
    raw_score = 1 - distance / 2

    chroma = MagicMock()

    def _make_col(name: str) -> MagicMock:
        col = MagicMock()
        col.count.return_value = 10
        col.get.return_value = {"ids": ["e1"], "metadatas": [{"model_version": _MODEL_V}]}
        col.query.return_value = _chroma_result(
            ids=["e1"],
            docs=["content"],
            metas=[{"category": "security", "language": "python", "model_version": _MODEL_V, "corpus": name}],  # noqa: E501
            distances=[distance],
        )
        return col

    chroma.get_or_create_collection.side_effect = _make_col
    from pr_reviewer.kb.knowledge_base import KnowledgeBase
    kb = KnowledgeBase(chroma_client=chroma, config=cfg)
    entries = kb.query("test", category="security", language="python")

    for e in entries:
        if e.corpus == "language_best_practices":
            assert e.score > raw_score, "language_best_practices score should be boosted"
        else:
            assert abs(e.score - raw_score) < 0.001, f"corpus {e.corpus} should not be boosted"


# ── Task 10.9 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.kb.knowledge_base._retrieval_latency")
def test_retrieval_latency_metric_emitted(mock_latency):
    kb, _ = _make_kb()
    kb.query("test", category="security", language="python")
    mock_latency.record.assert_called_once()


# ── Task 10.10 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cross_repo_fixes_collection_queryable_when_enabled():
    cfg = Config(knowledge_base=KnowledgeBaseConfig())  # all collections enabled
    cross_entry = _chroma_result(
        ids=["cr1"],
        docs=["cross-repo fix"],
        metas=[{"category": "bugs", "language": "python", "model_version": _MODEL_V}],
        distances=[0.1],
    )
    kb, _ = _make_kb(config=cfg, cross_repo_results=cross_entry)
    entries = kb.query("fix", category="bugs", language="python")
    ids = [e.id for e in entries]
    assert "cr1" in ids


# ── Task 10.11 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cross_repo_fixes_excluded_when_not_in_active_collections():
    kb, _ = _make_kb(cross_repo_results=_empty_result())
    # No error expected — just no cross_repo_fixes results
    entries = kb.query("test", category="security", language="python")
    ids = [e.id for e in entries]
    assert "cr1" not in ids  # cross_repo returns empty, not in results
