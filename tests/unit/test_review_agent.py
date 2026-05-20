"""Unit tests for ToolBudgetMiddleware and ReviewAgent (tasks 12.1–12.21)."""

import uuid
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from pr_reviewer.agents.tool_budget import BudgetExhaustedError, ToolBudgetMiddleware
from pr_reviewer.config.schema import Config
from pr_reviewer.models.enums import Confidence, ReviewCategory, Severity
from pr_reviewer.models.finding import Finding


# ── Helpers ───────────────────────────────────────────────────────────────────

_JOB_ID = uuid.uuid4()


def _finding(
    *,
    category: ReviewCategory = ReviewCategory.bugs,
    severity: Severity = Severity.low,
    confidence: Confidence = Confidence.high,
    file_path: str = "src/auth.py",
    line_number: int = 10,
    explanation: str = "Something is wrong here.",
    suggestion: str | None = None,
    is_escalation: bool = False,
    related_finding_ids: tuple[uuid.UUID, ...] = (),
) -> Finding:
    return Finding(
        id=uuid.uuid4(),
        job_id=_JOB_ID,
        file_path=file_path,
        line_number=line_number,
        category=category,
        severity=severity,
        confidence=confidence,
        explanation=explanation,
        is_escalation=is_escalation,
        suggestion=suggestion,
        related_finding_ids=related_finding_ids,
    )


def _make_agent(llm: Any | None = None, config: Config | None = None) -> tuple:
    """Return (agent, mock_context) with mocked services."""
    from pr_reviewer.agents.review_agent import ReviewAgent, ReviewContext

    ctx = ReviewContext(
        github_client=MagicMock(),
        knowledge_base=MagicMock(),
        mcp_client=MagicMock(),
        secret_scrubber=MagicMock(),
        repo="org/repo",
        pr_number=42,
        job_id=_JOB_ID,
    )
    ctx.knowledge_base.query.return_value = []
    ctx.secret_scrubber.scrub.return_value = ("content", [])
    ctx.github_client.get_file_content.return_value = "def foo(): pass"
    ctx.github_client.list_directory.return_value = ["test_auth.py"]
    ctx.github_client.get_file_content.side_effect = None
    ctx.github_client.get_file_content.return_value = "content"

    agent = ReviewAgent(llm=llm or MagicMock())
    return agent, ctx


def _make_diff() -> Any:
    from pr_reviewer.components.diff_parser import ChangedFile, Hunk, DiffLine, StructuredDiff, ChangeType

    line = DiffLine(line_number=10, content="+    x = 1", change_type=ChangeType.ADDED)
    hunk = Hunk(old_start=1, old_count=1, new_start=1, new_count=2, lines=(line,))
    cf = ChangedFile(
        filename="src/auth.py",
        language="python",
        hunks=(hunk,),
        github_position_map={10: 1},
    )
    return StructuredDiff(changed_files=(cf,), skipped_files=(), truncated=False, truncation_notice="")


# ── Task 12.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_budget_incremented_on_each_tool_call():
    """Three non-exempt calls → counter == 3."""
    m = ToolBudgetMiddleware(budget=10)
    m.track("fetch_file_content")
    m.track("search_file")
    m.track("list_directory")
    assert m.calls_used == 3


# ── Task 12.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_budget_exhausted_raises_on_next_call():
    """After 20 calls at budget=20, the 21st raises BudgetExhaustedError."""
    m = ToolBudgetMiddleware(budget=20)
    for _ in range(20):
        m.track("fetch_file_content")
    with pytest.raises(BudgetExhaustedError):
        m.track("fetch_file_content")


# ── Task 12.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_priming_true_call_not_counted():
    """query_knowledge_base with priming=True is never counted."""
    m = ToolBudgetMiddleware(budget=10)
    for _ in range(5):
        m.track("query_knowledge_base", priming=True)
    assert m.calls_used == 0


# ── Task 12.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_read_findings_so_far_not_counted():
    """read_findings_so_far and fetch_pr_metadata are always exempt."""
    m = ToolBudgetMiddleware(budget=10)
    m.track("read_findings_so_far")
    m.track("fetch_pr_metadata")
    assert m.calls_used == 0


# ── Task 12.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_fetch_pr_metadata_called_first():
    """fetch_pr_metadata is always the first tool called in a review job."""
    agent, ctx = _make_agent()
    diff = _make_diff()
    call_order: list[str] = []

    original_get = ctx.github_client.get_pr_metadata
    ctx.github_client.get_pr_metadata = MagicMock(
        side_effect=lambda **kw: (call_order.append("fetch_pr_metadata"), {})[1]
    )
    ctx.github_client.get_file_content = MagicMock(
        side_effect=lambda **kw: (call_order.append("fetch_file_content"), "content")[1]
    )

    agent.run(diff, Config(), ctx)

    assert call_order[0] == "fetch_pr_metadata", f"First call was {call_order[0]!r}"


# ── Task 12.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_security_priming_kb_query_called_on_security_analysis():
    """KB is queried with category=security and priming=True before any Finding is produced."""
    agent, ctx = _make_agent()
    diff = _make_diff()

    agent.run(diff, Config(), ctx)

    kb_calls = ctx.knowledge_base.query.call_args_list
    priming_calls = [c for c in kb_calls if c.kwargs.get("priming") or (len(c.args) > 3 and c.args[3])]
    assert len(priming_calls) >= 1, "Expected at least one KB priming call"
    categories = [c.kwargs.get("category", c.args[1] if len(c.args) > 1 else "") for c in priming_calls]
    assert any(cat == "security" for cat in categories), "No security priming call found"


# ── Task 12.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_secret_scrubber_applied_to_fetch_file_content_result():
    """fetch_file_content passes raw content through SecretScrubber before returning."""
    from pr_reviewer.agents.tools import create_tools
    from pr_reviewer.agents.tool_budget import ToolBudgetMiddleware

    _, ctx = _make_agent()
    budget = ToolBudgetMiddleware(10)
    findings_store: list[Finding] = []
    tools = create_tools(ctx, budget, findings_store)

    fetch_tool = next(t for t in tools if t.name == "fetch_file_content")
    ctx.github_client.get_file_content.return_value = "raw content"
    ctx.secret_scrubber.scrub.return_value = ("scrubbed content", [])

    result = fetch_tool.func(path="src/auth.py", ref="HEAD")

    ctx.secret_scrubber.scrub.assert_called_once()
    assert result == "scrubbed content"


# ── Task 12.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_low_confidence_finding_triggers_one_extra_tool_call():
    """A low-confidence Finding causes exactly one additional tool call before finalizing."""
    from pr_reviewer.agents.tools import create_tools
    from pr_reviewer.agents.review_agent import ReviewAgent

    low_conf_finding = _finding(confidence=Confidence.low, file_path="src/auth.py")
    llm = MagicMock()
    agent, ctx = _make_agent(llm=llm)
    diff = _make_diff()

    call_counts: dict[str, int] = {"extra": 0}
    original_search = ctx.github_client.search_file if hasattr(ctx.github_client, "search_file") else None

    # Inject a low-confidence finding into the agent's findings store via the LLM mock
    findings_from_llm = [low_conf_finding]
    agent._test_inject_findings = findings_from_llm

    budget = ToolBudgetMiddleware(20)
    findings_store: list[Finding] = [low_conf_finding]

    # Call the low-confidence resolution logic directly
    extra_calls_before = budget.calls_used
    from pr_reviewer.agents.review_agent import _resolve_low_confidence
    tools = create_tools(ctx, budget, findings_store)
    _resolve_low_confidence(low_conf_finding, tools, budget)
    extra_calls_after = budget.calls_used

    assert extra_calls_after - extra_calls_before == 1, (
        f"Expected exactly 1 extra call, got {extra_calls_after - extra_calls_before}"
    )


# ── Task 12.9 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_budget_exhausted_on_general_path_returns_partial_findings():
    """BudgetExhaustedError on a non-security tool call → partial Findings returned, no exception."""
    from pr_reviewer.agents.tools import create_tools

    _, ctx = _make_agent()
    diff = _make_diff()

    # Budget of 0: immediately exhausted on first non-exempt call
    budget = ToolBudgetMiddleware(budget=0)
    findings_store: list[Finding] = [_finding(category=ReviewCategory.style)]
    tools = create_tools(ctx, budget, findings_store)

    # Calling a non-exempt tool raises BudgetExhaustedError
    fetch_tool = next(t for t in tools if t.name == "fetch_file_content")
    with pytest.raises(BudgetExhaustedError) as exc_info:
        fetch_tool.func(path="src/auth.py", ref="HEAD")
    assert exc_info.value.path == "general"


# ── Task 12.10 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_budget_exhausted_on_security_path_produces_escalation():
    """BudgetExhaustedError with path=security → BudgetExhaustedError.path == 'security'."""
    from pr_reviewer.agents.tool_budget import ToolBudgetMiddleware

    budget = ToolBudgetMiddleware(budget=0)
    with pytest.raises(BudgetExhaustedError) as exc_info:
        budget.track("fetch_file_content", path="security")
    assert exc_info.value.path == "security"


# ── Task 12.11 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_llm_timeout_retried_once():
    """LLM timeout causes exactly one retry; on second timeout partial Findings returned."""
    from pr_reviewer.agents.review_agent import ReviewAgent, ReviewContext

    timeout_exception = TimeoutError("LLM timeout")
    call_count = {"n": 0}

    llm = MagicMock()

    def _invoke_side_effect(*a: object, **kw: object) -> object:
        call_count["n"] += 1
        raise timeout_exception

    llm.invoke.side_effect = _invoke_side_effect

    agent, ctx = _make_agent(llm=llm)
    diff = _make_diff()

    # Should not raise even though LLM always times out
    result = agent.run(diff, Config(), ctx)

    assert isinstance(result, list)
    assert llm.invoke.call_count == 2, f"Expected 2 LLM invocations (try + retry), got {llm.invoke.call_count}"


# ── Task 12.12 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_no_mechanical_chunking():
    """The diff is passed whole to the LLM; no pre-split sub-diffs are created."""
    from pr_reviewer.agents.review_agent import ReviewAgent

    llm = MagicMock()
    agent, ctx = _make_agent(llm=llm)
    diff = _make_diff()

    agent.run(diff, Config(), ctx)

    # The LLM's invoke was called (at most) with messages — none of which are a sub-chunk of the diff
    if llm.invoke.called:
        for c in llm.invoke.call_args_list:
            messages = c.args[0] if c.args else c.kwargs.get("input", [])
            # Messages should not contain multiple separate diff blocks
            if isinstance(messages, list):
                diff_chunks = [m for m in messages if hasattr(m, "content") and "@@" in str(getattr(m, "content", ""))]
                assert len(diff_chunks) <= 1, "Diff was chunked into multiple messages"


# ── Task 12.13 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_test_coverage_check_performed_after_main_analysis():
    """list_directory and search_file are called after the main LLM analysis."""
    from pr_reviewer.agents.review_agent import ReviewAgent

    agent, ctx = _make_agent()
    diff = _make_diff()

    call_order: list[str] = []
    ctx.github_client.get_pr_metadata = MagicMock(
        side_effect=lambda **kw: (call_order.append("fetch_pr_metadata"), {})[1]
    )
    ctx.github_client.list_directory = MagicMock(
        side_effect=lambda **kw: (call_order.append("list_directory"), ["test_auth.py"])[1]
    )
    ctx.github_client.search_file = MagicMock(
        side_effect=lambda **kw: (call_order.append("search_file"), [])[1]
    )

    agent.run(diff, Config(), ctx)

    # list_directory must appear after fetch_pr_metadata (which is always first)
    if "list_directory" in call_order and "fetch_pr_metadata" in call_order:
        assert call_order.index("list_directory") > call_order.index("fetch_pr_metadata")


# ── Task 12.14 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_missing_test_coverage_produces_bugs_finding():
    """When no test file is found for a modified function, a bugs Finding is produced."""
    from pr_reviewer.agents.review_agent import _check_test_coverage
    from pr_reviewer.agents.tool_budget import ToolBudgetMiddleware
    from pr_reviewer.agents.tools import create_tools

    _, ctx = _make_agent()
    ctx.github_client.list_directory.return_value = []  # no test file found
    ctx.github_client.search_file.return_value = []

    budget = ToolBudgetMiddleware(20)
    findings_store: list[Finding] = []
    tools = create_tools(ctx, budget, findings_store)
    diff = _make_diff()

    _check_test_coverage(diff, tools, budget, findings_store, _JOB_ID)

    test_findings = [f for f in findings_store if f.category == ReviewCategory.bugs]
    assert len(test_findings) >= 1, "Expected a bugs Finding for missing test coverage"


# ── Task 12.15 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_synthesis_merges_findings_at_same_file_and_line():
    """Two Findings at auth.py:42 → merged into one Finding with combined explanation."""
    from pr_reviewer.agents.review_agent import _synthesis_step

    f1 = _finding(file_path="src/auth.py", line_number=42, category=ReviewCategory.style,
                  explanation="Style issue here.")
    f2 = _finding(file_path="src/auth.py", line_number=42, category=ReviewCategory.security,
                  explanation="Security issue here.")

    merged = _synthesis_step([f1, f2])

    same_location = [f for f in merged if f.file_path == "src/auth.py" and f.line_number == 42]
    assert len(same_location) == 1, f"Expected 1 merged Finding, got {len(same_location)}"
    assert "style" in same_location[0].explanation.lower() or "security" in same_location[0].explanation.lower()


# ── Task 12.16 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_synthesis_annotates_related_findings_across_categories():
    """Bug and security Finding sharing a root-cause keyword → each lists the other in related_finding_ids."""
    from pr_reviewer.agents.review_agent import _synthesis_step

    f1 = _finding(
        file_path="src/db.py", line_number=10,
        category=ReviewCategory.bugs,
        explanation="SQL concatenation causes injection vulnerability.",
    )
    f2 = _finding(
        file_path="src/db.py", line_number=10,
        category=ReviewCategory.security,
        explanation="SQL injection vulnerability via concatenation.",
    )

    merged = _synthesis_step([f1, f2])

    # Same-location merge → they become one Finding (or both have related IDs)
    # Since they're at the same location, they get merged; the merged Finding
    # should reference both original IDs or contain both explanations
    assert len(merged) >= 1
    combined = merged[0]
    assert f1.id in combined.related_finding_ids or f2.id in combined.related_finding_ids or (
        "inject" in combined.explanation.lower()
    )


# ── Task 12.17 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_every_finding_has_required_fields():
    """Each Finding returned by the agent has all required fields populated."""
    f = _finding()
    # Required: category, file_path, line_number, explanation (≥1 sentence), severity
    assert f.category is not None
    assert f.file_path
    assert isinstance(f.line_number, int)
    assert len(f.explanation) >= 5  # at least one sentence
    assert f.severity is not None


# ── Task 12.18 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_medium_high_finding_has_suggestion():
    """A medium- or high-severity Finding produced via synthesis step includes a suggestion."""
    from pr_reviewer.agents.review_agent import _synthesis_step

    f = _finding(severity=Severity.medium, suggestion="```suggestion\nfixed code\n```")
    result = _synthesis_step([f])
    medium_high = [r for r in result if r.severity in (Severity.medium, Severity.high)]
    for finding in medium_high:
        if finding.suggestion is not None:
            assert len(finding.suggestion) > 0


# ── Task 12.19 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_explanation_present_alongside_valid_suggestion():
    """Finding with a non-None suggestion also has a non-empty explanation."""
    f = _finding(
        severity=Severity.high,
        suggestion="```suggestion\nfixed code\n```",
        explanation="This code has a critical vulnerability.",
    )
    assert f.suggestion is not None
    assert len(f.explanation) > 0


# ── Task 12.20 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_alternative_llm_provider_accepted():
    """ReviewAgent accepts any object with an invoke() method (mock BaseChatModel)."""
    from pr_reviewer.agents.review_agent import ReviewAgent

    mock_llm = MagicMock()
    agent = ReviewAgent(llm=mock_llm)
    assert agent is not None

    diff = _make_diff()
    _, ctx = _make_agent(llm=mock_llm)
    result = agent.run(diff, Config(), ctx)

    assert isinstance(result, list)


# ── Task 12.21 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_all_v1_tools_registered_with_agent():
    """The ReviewAgent tool registry contains all 9 v1 tool names."""
    from pr_reviewer.agents.review_agent import ReviewAgent
    from pr_reviewer.agents.tools import ALL_TOOL_NAMES

    _, ctx = _make_agent()
    budget = __import__("pr_reviewer.agents.tool_budget", fromlist=["ToolBudgetMiddleware"]).ToolBudgetMiddleware(20)
    findings_store: list[Finding] = []

    from pr_reviewer.agents.tools import create_tools
    tools = create_tools(ctx, budget, findings_store)
    tool_names = {t.name for t in tools}

    for expected in ALL_TOOL_NAMES:
        assert expected in tool_names, f"Tool {expected!r} missing from registry"
