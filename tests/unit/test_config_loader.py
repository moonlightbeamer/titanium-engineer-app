"""Unit tests for ConfigLoader (tasks 9.1–9.9)."""

import logging
from unittest.mock import MagicMock, patch

import pytest


def _make_loader(yaml_content: str | None = None, status_code: int = 200) -> "ConfigLoader":  # noqa: F821
    """Return a ConfigLoader with a mocked GitHubAPIClient."""
    from pr_reviewer.config.loader import ConfigLoader

    mock_client = MagicMock()
    if yaml_content is None or status_code != 200:
        mock_client.get_file_content.side_effect = Exception(f"HTTP {status_code}")
    else:
        mock_client.get_file_content.return_value = yaml_content
    return ConfigLoader(github_client=mock_client)


# ── Task 9.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_valid_yaml_parsed_into_config():
    yaml = (
        "tool_budget: 30\n"
        "min_severity: medium\n"
        "auto_approve_on_no_findings: true\n"
        "review_draft_prs: true\n"
        "ignore_patterns_override:\n"
        "  - '*.lock'\n"
        "max_linter_files: 10\n"
    )
    loader = _make_loader(yaml)
    config = loader.load(repo_id="org/repo", installation_id=42)

    assert config.tool_budget == 30
    assert config.min_severity == "medium"
    assert config.auto_approve_on_no_findings is True
    assert config.review_draft_prs is True
    assert config.ignore_patterns_override == ["*.lock"]
    assert config.max_linter_files == 10


# ── Task 9.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_missing_config_file_returns_defaults():
    loader = _make_loader(status_code=404)
    config = loader.load(repo_id="org/repo", installation_id=42)

    assert config.tool_budget == 20
    assert config.max_linter_files == 5
    assert config.ignore_patterns_override is None
    assert config.ignore_patterns_extend is None


# ── Task 9.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_invalid_yaml_returns_defaults_and_logs_warn(caplog):
    loader = _make_loader(yaml_content="tool_budget: not_an_int\n")
    with caplog.at_level(logging.WARNING):
        config = loader.load(repo_id="org/repo", installation_id=42)

    assert config.tool_budget == 20  # defaults
    assert any("invalid config" in r.message.lower() for r in caplog.records)


# ── Task 9.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_config_is_frozen_instance():
    from pydantic import ValidationError

    loader = _make_loader(yaml_content="tool_budget: 25\n")
    config = loader.load(repo_id="org/repo", installation_id=42)

    with pytest.raises((ValidationError, TypeError)):
        config.tool_budget = 99  # type: ignore[misc]


# ── Task 9.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_max_linter_files_defaults_to_5():
    loader = _make_loader(yaml_content="tool_budget: 15\n")  # no max_linter_files
    config = loader.load(repo_id="org/repo", installation_id=42)
    assert config.max_linter_files == 5


# ── Task 9.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_mcp_servers_custom_nvd_endpoint_parsed():
    yaml = "mcp_servers:\n  nvd: 'http://proxy:9200'\n"
    loader = _make_loader(yaml_content=yaml)
    config = loader.load(repo_id="org/repo", installation_id=42)
    assert config.mcp_servers.nvd == "http://proxy:9200"


# ── Task 9.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_mcp_servers_defaults_to_standard_endpoints_when_absent():
    loader = _make_loader(yaml_content="tool_budget: 20\n")
    config = loader.load(repo_id="org/repo", installation_id=42)
    assert config.mcp_servers.nvd == "https://services.nvd.nist.gov"


# ── Task 9.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_language_corpus_weights_parsed():
    yaml = "knowledge_base:\n  language_corpus_weights:\n    python: 1.5\n"
    loader = _make_loader(yaml_content=yaml)
    config = loader.load(repo_id="org/repo", installation_id=42)
    assert config.knowledge_base.language_corpus_weights == {"python": 1.5}


# ── Task 9.9 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_language_corpus_weights_defaults_to_empty_dict():
    loader = _make_loader(yaml_content="tool_budget: 20\n")
    config = loader.load(repo_id="org/repo", installation_id=42)
    assert config.knowledge_base.language_corpus_weights == {}
