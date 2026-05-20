"""Unit tests for v2 eval harness — knowledge retrieval quality (task 28)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch


# ── Task 28.1 ─────────────────────────────────────────────────────────────────


def test_ablation_run_computes_delta_precision_per_category():
    """Two run results (KB enabled vs disabled) → delta_precision per category."""
    from eval.tasks.ablation import compute_ablation_delta

    run_with_kb = {
        "precision_by_category": {"bugs": 0.8, "security": 0.9, "style": 0.7, "performance": 0.6},
    }
    run_without_kb = {
        "precision_by_category": {"bugs": 0.6, "security": 0.7, "style": 0.65, "performance": 0.55},
    }

    result = compute_ablation_delta(run_with_kb, run_without_kb)

    assert "delta_precision" in result
    assert "security" in result["delta_precision"]
    assert abs(result["delta_precision"]["security"] - 0.2) < 1e-6
    assert abs(result["delta_precision"]["bugs"] - 0.2) < 1e-6


# ── Task 28.2 ─────────────────────────────────────────────────────────────────


def test_retrieval_relevance_scored_per_kb_call():
    """Eval trace with 3 query_knowledge_base calls → 3 relevance scores produced."""
    from eval.retrieval_quality import score_retrieval_calls

    trace = [
        {"tool_name": "query_knowledge_base", "corpus": "cve_snapshot", "query": "SQL injection"},
        {"tool_name": "query_knowledge_base", "corpus": "cve_snapshot", "query": "XSS"},
        {"tool_name": "query_knowledge_base", "corpus": "org_guidelines", "query": "auth"},
        {"tool_name": "fetch_file_content", "path": "src/auth.py"},  # not a KB call
    ]
    findings = [{"category": "security", "explanation": "SQL injection risk"}]

    mock_judge = MagicMock(return_value=MagicMock(score=7))
    scores = score_retrieval_calls(trace, findings, judge_fn=mock_judge)

    assert mock_judge.call_count == 3
    assert "cve_snapshot" in scores
    assert "org_guidelines" in scores


# ── Task 28.3 ─────────────────────────────────────────────────────────────────


def test_mean_relevance_computed_per_corpus():
    """5 cve_snapshot calls + 3 org_guidelines → separate mean scores per corpus."""
    from eval.retrieval_quality import score_retrieval_calls

    call_scores = {"cve_snapshot": [8, 7, 9, 6, 8], "org_guidelines": [5, 6, 7]}
    call_idx = {"cve_snapshot": 0, "org_guidelines": 0}

    def fake_judge(*, finding, query, corpus, **kwargs):
        idx = call_idx[corpus]
        call_idx[corpus] += 1
        return MagicMock(score=call_scores[corpus][idx])

    trace = (
        [{"tool_name": "query_knowledge_base", "corpus": "cve_snapshot", "query": f"q{i}"} for i in range(5)]
        + [{"tool_name": "query_knowledge_base", "corpus": "org_guidelines", "query": f"q{i}"} for i in range(3)]
    )
    findings: list[dict] = []

    scores = score_retrieval_calls(trace, findings, judge_fn=fake_judge)

    assert abs(scores["cve_snapshot"] - (8 + 7 + 9 + 6 + 8) / 5) < 1e-6
    assert abs(scores["org_guidelines"] - (5 + 6 + 7) / 3) < 1e-6


# ── Task 28.4 ─────────────────────────────────────────────────────────────────


def test_tool_budget_attribution_separates_kb_from_codebase_calls():
    """Attribution result has kb_calls and codebase_calls summing to total budget used."""
    from eval.budget_attribution import BudgetAttribution, attribute_budget

    tool_calls = [
        {"tool_name": "query_knowledge_base"},
        {"tool_name": "lookup_cve"},
        {"tool_name": "fetch_file_content"},
        {"tool_name": "search_file"},
        {"tool_name": "list_directory"},
        {"tool_name": "ghsa_lookup"},
    ]

    result = attribute_budget(tool_calls)

    assert isinstance(result, BudgetAttribution)
    assert result.kb_calls == 3   # query_knowledge_base, lookup_cve, ghsa_lookup
    assert result.codebase_calls == 3  # fetch_file_content, search_file, list_directory
    assert result.total == 6


def test_budget_attribution_is_frozen():
    """BudgetAttribution raises FrozenInstanceError on mutation."""
    from eval.budget_attribution import BudgetAttribution

    attr = BudgetAttribution(kb_calls=2, codebase_calls=3, total=5)
    try:
        attr.kb_calls = 99  # type: ignore[misc]
        raise AssertionError("Expected FrozenInstanceError")
    except FrozenInstanceError:
        pass


# ── Task 28.5 ─────────────────────────────────────────────────────────────────


def test_corpus_flagged_when_mean_relevance_below_0_6_for_3_runs():
    """3 consecutive runs with cve_snapshot mean relevance 0.4 → corpus flagged."""
    from eval.corpus_health import CorpusHealthMonitor

    flagged: list[str] = []
    monitor = CorpusHealthMonitor(threshold=0.6, window=3, on_flag=flagged.append)

    monitor.record_run("cve_snapshot", 0.4)
    monitor.record_run("cve_snapshot", 0.35)
    was_flagged = monitor.record_run("cve_snapshot", 0.45)

    assert was_flagged is True
    assert "cve_snapshot" in flagged


# ── Task 28.6 ─────────────────────────────────────────────────────────────────


def test_corpus_not_flagged_on_only_2_consecutive_low_runs():
    """2 runs below threshold then 1 above → not flagged."""
    from eval.corpus_health import CorpusHealthMonitor

    flagged: list[str] = []
    monitor = CorpusHealthMonitor(threshold=0.6, window=3, on_flag=flagged.append)

    monitor.record_run("cve_snapshot", 0.4)
    monitor.record_run("cve_snapshot", 0.5)
    was_flagged = monitor.record_run("cve_snapshot", 0.7)  # above threshold

    assert was_flagged is False
    assert "cve_snapshot" not in flagged


# ── Task 28.7 ─────────────────────────────────────────────────────────────────


def test_index_contribution_delta_reported():
    """Eval with CodebaseIndex vs without → precision/recall/FP delta in IndexContributionReport."""
    from eval.tasks.index_contribution import IndexContributionReport, compute_index_contribution

    run_with_index = {
        "precision_by_category": {"security": 0.85, "bugs": 0.7},
        "recall_by_category": {"security": 0.8, "bugs": 0.65},
        "fp_by_category": {"security": 2, "bugs": 3},
    }
    run_without_index = {
        "precision_by_category": {"security": 0.7, "bugs": 0.6},
        "recall_by_category": {"security": 0.65, "bugs": 0.55},
        "fp_by_category": {"security": 5, "bugs": 7},
    }

    report = compute_index_contribution(run_with_index, run_without_index)

    assert isinstance(report, IndexContributionReport)
    assert "security" in report.precision_delta
    assert abs(report.precision_delta["security"] - 0.15) < 1e-6
    assert "security" in report.recall_delta
    assert "security" in report.fp_delta
    assert report.fp_delta["security"] == -3  # fewer FPs with index


def test_index_contribution_report_is_frozen():
    """IndexContributionReport raises FrozenInstanceError on mutation."""
    from eval.tasks.index_contribution import IndexContributionReport

    report = IndexContributionReport(
        precision_delta={"security": 0.1},
        recall_delta={"security": 0.05},
        fp_delta={"security": -2},
    )
    try:
        report.precision_delta = {}  # type: ignore[misc]
        raise AssertionError("Expected FrozenInstanceError")
    except FrozenInstanceError:
        pass


# ── Task 28.8 ─────────────────────────────────────────────────────────────────


def test_retrieval_relevance_written_to_kb_retrieval_relevance_metric():
    """After eval run, kb.retrieval_relevance OTel gauge updated per corpus."""
    from eval.retrieval_quality import emit_retrieval_relevance_metric

    recorded: list[tuple] = []

    def fake_gauge_record(corpus, value):
        recorded.append((corpus, value))

    scores = {"cve_snapshot": 0.75, "org_guidelines": 0.82}
    emit_retrieval_relevance_metric(scores, record_fn=fake_gauge_record)

    assert len(recorded) == 2
    corpora = {r[0] for r in recorded}
    assert "cve_snapshot" in corpora
    assert "org_guidelines" in corpora
    values = {r[0]: r[1] for r in recorded}
    assert abs(values["cve_snapshot"] - 0.75) < 1e-9
