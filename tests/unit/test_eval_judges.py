"""Unit tests for eval judge suite and classical metrics (task 19)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest


def _mock_litellm_response(score: int = 8, rationale: str = "looks relevant") -> MagicMock:
    """Return a mock litellm completion resembling the real API response."""
    choice = MagicMock()
    choice.message.content = f'{{"score": {score}, "rationale": "{rationale}"}}'
    resp = MagicMock()
    resp.choices = [choice]
    resp.model = "gpt-4o"
    resp.usage.total_tokens = 200
    return resp


# ── Task 19.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_relevance_judge_returns_score_and_rationale():
    """Mocked LiteLLM → JudgeResult with 0 ≤ score ≤ 10 and non-empty rationale."""
    from eval.judges.relevance_judge import JudgeResult, judge

    with patch("litellm.completion", return_value=_mock_litellm_response(8, "very relevant")):
        result = judge(finding="auth bypass", diff="diff text")

    assert isinstance(result, JudgeResult)
    assert 0 <= result.score <= 10
    assert len(result.rationale) > 0
    assert len(result.model_used) > 0


# ── Task 19.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_scores_returned_as_4_vector_not_mean():
    """evaluate_finding returns ScoreVector(relevance, accuracy, actionability, clarity)."""
    from eval.eval_runner import ScoreVector, evaluate_finding

    finding_dict = {"category": "security", "explanation": "sql injection", "line_number": 10}
    diff = "some diff"
    label = "true_positive"

    mock_resp = _mock_litellm_response(7)
    with patch("litellm.completion", return_value=mock_resp):
        result = evaluate_finding(finding_dict, diff, label)

    assert isinstance(result, ScoreVector)
    assert hasattr(result, "relevance")
    assert hasattr(result, "accuracy")
    assert hasattr(result, "actionability")
    assert hasattr(result, "clarity")
    # Must not be a single float
    assert not isinstance(result, float)


# ── Task 19.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_schema_validity_check_passes_for_complete_finding():
    """Finding dict with all required fields → validate_schema returns True."""
    from eval.classical_metrics import validate_schema

    finding = {
        "category": "security",
        "file_path": "src/auth.py",
        "line_number": 42,
        "explanation": "SQL injection vulnerability detected.",
        "severity": "high",
    }
    assert validate_schema(finding) is True


# ── Task 19.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_regex_check_requires_line_number_for_security():
    """Security finding without line_number → check_regex returns False."""
    from eval.classical_metrics import check_regex

    finding = {
        "category": "security",
        "explanation": "potential XSS",
        "line_number": None,
    }
    assert check_regex(finding) is False


# ── Task 19.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_token_f1_computed_against_reference_fix():
    """Reference contains 'x > 0', prediction includes it → F1 > 0."""
    from eval.classical_metrics import token_f1

    reference = "def validate(x): return x > 0"
    prediction = "the value must satisfy x > 0 to pass validation"
    f1 = token_f1(reference, prediction)
    assert f1 > 0


# ── Task 19.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_bias_detection_runs_security_judge_with_two_model_families():
    """detect_same_family_bias calls the judge with ≥2 different model families."""
    from eval.bias_detection import detect_same_family_bias

    finding = {"category": "security", "explanation": "SQL injection"}
    diff = "some diff"
    models_used: list[str] = []

    def fake_completion(**kwargs: object) -> MagicMock:
        models_used.append(kwargs.get("model", ""))
        return _mock_litellm_response(7)

    with patch("litellm.completion", side_effect=fake_completion):
        result = detect_same_family_bias(finding, diff)

    assert result is not None
    families = {_model_family(m) for m in models_used}
    assert len(families) >= 2, f"Only one model family used: {models_used}"


# ── Task 19.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_verification_trace_judge_receives_tool_call_chain():
    """verification_trace_judge receives the list of tool calls used before the finding."""
    from eval.judges.verification_trace_judge import JudgeResult, judge

    tool_calls = ["fetch_pr_metadata", "query_knowledge_base", "lookup_cve"]
    finding = {"category": "security", "explanation": "CVE-2024-1234 affected"}

    captured: list = []

    def fake_completion(**kwargs: object) -> MagicMock:
        captured.append(kwargs)
        return _mock_litellm_response(9)

    with patch("litellm.completion", side_effect=fake_completion):
        result = judge(finding=finding, tool_calls=tool_calls)

    assert isinstance(result, JudgeResult)
    assert len(captured) > 0
    # Verify tool call chain reached the LLM prompt
    prompt_text = str(captured[0])
    assert any(tc in prompt_text for tc in tool_calls)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _model_family(model: str) -> str:
    if "gpt" in model or "openai" in model:
        return "openai"
    if "claude" in model or "anthropic" in model:
        return "anthropic"
    if "gemini" in model or "google" in model:
        return "google"
    return model
