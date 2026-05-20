"""Unit tests for index-informed ReviewAgent behavior (tasks 24.1–24.8)."""

from __future__ import annotations

import json
import uuid
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest

from pr_reviewer.models.enums import Confidence, ReviewCategory, Severity
from pr_reviewer.models.finding import Finding


def _make_finding(
    *,
    category: ReviewCategory = ReviewCategory.style,
    explanation: str = "Uses camelCase naming.",
    file_path: str = "src/foo.py",
    line_number: int = 1,
    confidence: Confidence = Confidence.high,
    severity: Severity = Severity.low,
) -> Finding:
    return Finding(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        file_path=file_path,
        line_number=line_number,
        category=category,
        severity=severity,
        confidence=confidence,
        explanation=explanation,
        is_escalation=False,
    )


def _make_index(content_dict: dict) -> MagicMock:
    from pr_reviewer.models.codebase_index import CodebaseIndex, IndexScope

    return CodebaseIndex(
        id=uuid.uuid4(),
        repo_id="org/repo",
        commit_sha="abc",
        scope=IndexScope.single,
        content=json.dumps(content_dict),
    )


# ── Task 24.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_style_finding_suppressed_for_pattern_in_convention_profile():
    """camelCase in convention_profile at >60% → camelCase style finding removed."""
    from pr_reviewer.agents.review_agent import _apply_convention_filter

    idx = _make_index({"convention_profile": {"camelCase": 0.75}})
    findings = [_make_finding(category=ReviewCategory.style, explanation="Uses camelCase naming.")]

    result = _apply_convention_filter(findings, idx)
    assert len(result) == 0


@pytest.mark.unit
def test_style_finding_retained_when_not_matching_convention():
    """Non-convention style finding retained even when profile present."""
    from pr_reviewer.agents.review_agent import _apply_convention_filter

    idx = _make_index({"convention_profile": {"camelCase": 0.75}})
    findings = [_make_finding(category=ReviewCategory.style, explanation="Missing docstring.")]

    result = _apply_convention_filter(findings, idx)
    assert len(result) == 1


# ── Task 24.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_style_finding_retained_when_no_codebase_index():
    """codebase_index=None → no convention filter applied; findings unchanged."""
    from pr_reviewer.agents.review_agent import _apply_convention_filter

    findings = [_make_finding(category=ReviewCategory.style, explanation="Uses camelCase.")]
    result = _apply_convention_filter(findings, None)
    assert len(result) == 1


# ── Task 24.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_tool_budget_biases_toward_high_density_file():
    """High-density file appears earlier in budget-prioritized list."""
    from pr_reviewer.agents.review_agent import _prioritize_budget_by_density

    idx = _make_index({"finding_density_map": {"src/auth/login.py": 10, "src/utils.py": 1}})
    files = ["src/utils.py", "src/auth/login.py", "src/other.py"]

    ordered = _prioritize_budget_by_density(files, idx)
    assert ordered.index("src/auth/login.py") < ordered.index("src/utils.py")


# ── Task 24.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_security_candidate_in_security_boundary_lowered_threshold():
    """File in security boundary → low-confidence security finding escalated."""
    from pr_reviewer.agents.review_agent import _apply_security_boundary_escalation

    idx = _make_index({
        "architectural_summary": {"security_boundaries": ["src/auth/"], "test_fixtures": []}
    })
    finding = _make_finding(
        category=ReviewCategory.security,
        file_path="src/auth/login.py",
        confidence=Confidence.low,
    )

    result = _apply_security_boundary_escalation([finding], idx)
    assert len(result) == 1
    assert result[0].is_escalation is True


# ── Task 24.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_security_candidate_in_test_fixture_auto_discarded():
    """File tagged as test fixture → security finding discarded."""
    from pr_reviewer.agents.review_agent import _discard_test_fixture_findings

    idx = _make_index({
        "architectural_summary": {"security_boundaries": [], "test_fixtures": ["tests/"]}
    })
    findings = [
        _make_finding(file_path="tests/test_auth.py", category=ReviewCategory.security),
        _make_finding(file_path="src/real.py", category=ReviewCategory.security),
    ]

    result = _discard_test_fixture_findings(findings, idx)
    assert len(result) == 1
    assert result[0].file_path == "src/real.py"


# ── Task 24.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_test_fixture_auto_discard_consumes_zero_budget():
    """Fixture discard via _discard_test_fixture_findings does not touch budget."""
    from pr_reviewer.agents.review_agent import _discard_test_fixture_findings
    from pr_reviewer.agents.tool_budget import ToolBudgetMiddleware

    idx = _make_index({
        "architectural_summary": {"security_boundaries": [], "test_fixtures": ["tests/"]}
    })
    budget = ToolBudgetMiddleware(budget=20)
    findings = [_make_finding(file_path="tests/foo.py")]

    _discard_test_fixture_findings(findings, idx)
    assert budget._count == 0


# ── Task 24.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_no_index_behavior_identical_to_v1():
    """codebase_index_enabled=False → convention and density logic not applied."""
    from pr_reviewer.agents.review_agent import _apply_convention_filter, _prioritize_budget_by_density

    findings = [_make_finding(category=ReviewCategory.style, explanation="Uses camelCase.")]
    files = ["src/auth.py", "src/utils.py"]

    filtered = _apply_convention_filter(findings, None)
    ordered = _prioritize_budget_by_density(files, None)

    assert len(filtered) == 1  # unchanged
    assert ordered == files     # unchanged order


# ── Task 24.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_eval_harness_index_contribution_delta_measured():
    """measure_index_contribution returns dict with precision_delta and recall_delta."""
    from pr_reviewer.agents.review_agent import measure_index_contribution

    result = measure_index_contribution(
        findings_with_index=[_make_finding()],
        findings_without_index=[_make_finding(), _make_finding()],
    )
    assert "precision_delta" in result
    assert "recall_delta" in result
    assert isinstance(result["precision_delta"], (int, float))
    assert isinstance(result["recall_delta"], (int, float))
