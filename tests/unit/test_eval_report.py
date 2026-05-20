"""Unit tests for eval trigger modes and summary report (task 20)."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ALEMBIC_VERSIONS = Path(__file__).parent.parent.parent / "alembic" / "versions"


def _make_finding(category: str = "security", label: str = "true_positive") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "job_id": str(uuid.uuid4()),
        "category": category,
        "file_path": "src/auth.py",
        "line_number": 42,
        "explanation": "Issue found.",
        "severity": "high",
        "label": label,
    }


# ── Task 20.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_preshipmode_fails_when_any_security_fp_present():
    """Corpus with 1 security FP → run_pre_ship raises or returns non-zero exit code."""
    from eval.tasks.pre_ship import PreShipFailure, run_pre_ship

    findings = [
        _make_finding("security", "false_positive"),
        _make_finding("bugs", "true_positive"),
    ]
    with pytest.raises(PreShipFailure, match="security false positive"):
        run_pre_ship(findings)


# ── Task 20.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_weekly_mode_samples_exactly_10_findings():
    """50 findings in DB → weekly_vibe samples exactly 10."""
    from eval.tasks.weekly_vibe import sample_findings

    all_findings = [_make_finding() for _ in range(50)]
    sampled = sample_findings(all_findings, n=10)
    assert len(sampled) == 10


# ── Task 20.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_weekly_mode_uses_stored_findings_not_raw_diff():
    """weekly_vibe.sample_findings accepts pre-loaded findings (not raw diff data)."""
    from eval.tasks.weekly_vibe import sample_findings

    # Findings have no 'raw_diff' key — they come from the findings table
    findings = [_make_finding() for _ in range(15)]
    assert all("raw_diff" not in f for f in findings)
    sampled = sample_findings(findings, n=10)
    assert all("raw_diff" not in f for f in sampled)


# ── Task 20.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_summary_report_precision_recall_fp_per_category():
    """Report contains precision, recall, false_positive_count per category."""
    from eval.report import EvalReport, generate_report

    findings = [
        _make_finding("security", "true_positive"),
        _make_finding("security", "false_positive"),
        _make_finding("bugs", "true_positive"),
        _make_finding("style", "false_positive"),
        _make_finding("performance", "true_positive"),
    ]
    report = generate_report(run_id=uuid.uuid4(), run_type="weekly", findings=findings)

    assert isinstance(report, EvalReport)
    for cat in ("bugs", "security", "style", "performance"):
        assert cat in report.precision_by_category
        assert cat in report.recall_by_category
        assert cat in report.fp_by_category


# ── Task 20.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_summary_report_includes_mean_per_dimension_scores():
    """Report has relevance, accuracy, actionability, clarity in mean_scores."""
    from eval.report import generate_report

    findings = [_make_finding() for _ in range(3)]
    report = generate_report(run_id=uuid.uuid4(), run_type="weekly", findings=findings)

    for dim in ("relevance", "accuracy", "actionability", "clarity"):
        assert dim in report.mean_scores, f"Missing dimension '{dim}' in mean_scores"


# ── Task 20.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_summary_report_includes_cost_and_latency_per_review():
    """Report has avg_cost_usd and avg_latency_ms fields."""
    from eval.report import generate_report

    findings = [_make_finding()]
    report = generate_report(run_id=uuid.uuid4(), run_type="weekly", findings=findings)

    assert hasattr(report, "avg_cost_usd")
    assert hasattr(report, "avg_latency_ms")
    assert isinstance(report.avg_cost_usd, float)
    assert isinstance(report.avg_latency_ms, float)


# ── Task 20.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_summary_report_includes_delta_vs_previous_run():
    """Second run report has a delta field comparing to the prior eval_runs record."""
    from eval.report import generate_report

    findings = [_make_finding()]
    previous = {"precision_by_category": {"security": 0.8}, "recall_by_category": {"security": 0.7}}
    report = generate_report(
        run_id=uuid.uuid4(),
        run_type="weekly",
        findings=findings,
        previous_report=previous,
    )
    assert report.delta is not None
    assert isinstance(report.delta, dict)


# ── Task 20.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_summary_report_includes_feedback_signal_counts():
    """Report has feedback_signals_per_category mapping."""
    from eval.report import generate_report

    findings = [_make_finding()]
    feedback = {"security": {"org/repo": 5}, "bugs": {"org/repo": 2}}
    report = generate_report(
        run_id=uuid.uuid4(),
        run_type="weekly",
        findings=findings,
        feedback_signals=feedback,
    )
    assert report.feedback_signals_per_category is not None
    assert "security" in report.feedback_signals_per_category


# ── Task 20.9 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_kb_quality_check_flags_security_finding_with_no_retrieval():
    """Security finding with no KB entries retrieved → flagged in kb_quality."""
    from eval.report import generate_report

    finding = _make_finding("security", "true_positive")
    finding["kb_entries_retrieved"] = 0  # no KB retrieval

    report = generate_report(
        run_id=uuid.uuid4(),
        run_type="weekly",
        findings=[finding],
    )
    assert report.kb_quality is not None
    assert len(report.kb_quality.get("no_retrieval_findings", [])) >= 1


# ── Task 20.10 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_meta_prompt_loop_reports_score_delta_before_applying():
    """Meta-prompt reflector reports delta but does NOT apply changes."""
    from eval.tasks.meta_prompt import run_meta_prompt

    findings = [_make_finding() for _ in range(5)]
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = '{"score": 6, "rationale": "could improve"}'
    mock_resp.model = "gpt-4o"

    with patch("litellm.completion", return_value=mock_resp):
        result = run_meta_prompt(findings)

    assert "delta" in result
    assert "revised_prompt" in result
    assert result.get("applied") is False


# ── Task 20 migration check ────────────────────────────────────────────────────


@pytest.mark.unit
def test_vibe_scores_table_created_by_migration():
    """Migration 005 exists and defines the vibe_scores table."""
    migration_file = ALEMBIC_VERSIONS / "007_vibe_scores.py"
    assert migration_file.exists(), "alembic/versions/007_vibe_scores.py missing"
    content = migration_file.read_text()
    assert "vibe_scores" in content
    assert "human_score" in content
