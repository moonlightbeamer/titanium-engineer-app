"""Tests for v2 MCP ecosystem tools (task 26)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_mcp(*, snyk_bucket_exhausted: bool = False) -> object:
    from pr_reviewer.config.schema import Config
    from pr_reviewer.kb.mcp_client import MCPClient

    kb = MagicMock()
    kb.query.return_value = []

    redis = MagicMock()
    # By default all buckets have capacity
    redis.incr.return_value = 1
    redis.expire.return_value = True

    if snyk_bucket_exhausted:
        def _incr(key: str) -> int:
            if "snyk" in key:
                return 99  # over any limit
            return 1
        redis.incr.side_effect = _incr

    config = Config()
    return MCPClient(knowledge_base=kb, config=config, redis_client=redis)


# ── Task 26.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_ghsa_lookup_calls_github_advisory_endpoint():
    """ghsa_lookup makes GET to api.github.com/advisories with correct params."""
    mcp = _make_mcp()
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = []

    with patch("httpx.get", return_value=mock_response) as mock_get:
        mcp.ghsa_lookup(package="requests", version="2.28.0", ecosystem="pip")

    mock_get.assert_called_once()
    call_url = mock_get.call_args[0][0]
    assert "api.github.com" in call_url
    assert "advisories" in call_url
    params = mock_get.call_args[1].get("params", {})
    assert params.get("ecosystem") == "pip"
    assert params.get("package") == "requests"


# ── Task 26.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_snyk_lookup_falls_back_on_rate_limit_bucket_exhausted():
    """Snyk bucket exhausted → fallback to cve_snapshot; source tagged 'fallback_corpus'."""
    from pr_reviewer.config.schema import Config
    from pr_reviewer.kb.mcp_client import CVEAdvisory, MCPClient

    kb = MagicMock()
    kb.query.return_value = [
        MagicMock(content="known vuln in lodash", id="kb-1")
    ]
    redis = MagicMock()
    redis.incr.return_value = 99  # every bucket exhausted
    redis.expire.return_value = True

    mcp = MCPClient(knowledge_base=kb, config=Config(), redis_client=redis)
    results = mcp.snyk_lookup(package="lodash", version="4.17.20", ecosystem="npm")

    assert len(results) > 0
    assert all(
        isinstance(r, CVEAdvisory) and r.source == "fallback_corpus"
        for r in results
    )


# ── Task 26.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_owasp_check_matches_sql_injection_pattern():
    """SQL string concatenation in Python → OWASPMatch with A03:2021."""
    from pr_reviewer.kb.mcp_client import OWASPMatch

    mcp = _make_mcp()
    code = 'query = "SELECT * FROM users WHERE id = " + user_id'
    results = mcp.owasp_check(code_snippet=code, language="python")

    assert len(results) > 0
    categories = [r.category for r in results]
    assert any("A03" in c for c in categories)
    assert all(isinstance(r, OWASPMatch) for r in results)


# ── Task 26.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_owasp_check_no_match_returns_empty():
    """Safe parameterized query → empty result list."""
    mcp = _make_mcp()
    code = 'cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))'
    results = mcp.owasp_check(code_snippet=code, language="python")

    assert results == []


# ── Task 26.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_v2_mcp_tools_count_against_tool_budget():
    """ghsa_lookup, snyk_lookup, owasp_check each increment ToolBudgetMiddleware."""
    from pr_reviewer.agents.tool_budget import ToolBudgetMiddleware
    from pr_reviewer.agents.review_agent import ReviewContext

    budget = ToolBudgetMiddleware(budget=50)

    ctx = ReviewContext(
        github_client=MagicMock(),
        knowledge_base=MagicMock(),
        mcp_client=_make_mcp(),
        secret_scrubber=MagicMock(),
        repo="org/repo",
        pr_number=1,
        job_id=__import__("uuid").uuid4(),
    )

    from pr_reviewer.agents.tools import create_tools
    from pr_reviewer.models.finding import Finding

    tools_list = create_tools(ctx, budget, [])
    tool_map = {t.name: t for t in tools_list}

    before = budget.calls_used

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = []

    with patch("httpx.get", return_value=mock_resp):
        tool_map["ghsa_lookup"].func(package="requests", version="2.28.0", ecosystem="pip")
    tool_map["snyk_lookup"].func(package="lodash", version="4.0.0", ecosystem="npm")
    tool_map["owasp_check"].func(code_snippet="x = 1", language="python")

    assert budget.calls_used == before + 3
