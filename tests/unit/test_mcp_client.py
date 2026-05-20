"""Unit tests for MCPClient (tasks 11.1–11.7)."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from pr_reviewer.config.schema import Config, MCPServersConfig

# ── Helpers ───────────────────────────────────────────────────────────────────

_W3C_TRACEPARENT_RE = __import__("re").compile(
    r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
)


def _make_http_mock(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """Return a mock httpx.Client context manager with a pre-programmed response."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    if status_code >= 400:
        import httpx

        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=response
        )
    else:
        response.raise_for_status.return_value = None

    http_client = MagicMock()
    http_client.__enter__ = MagicMock(return_value=http_client)
    http_client.__exit__ = MagicMock(return_value=False)
    http_client.get.return_value = response
    http_client.post.return_value = response
    return http_client


def _make_redis_mock(incr_sequence: list[int] | None = None) -> MagicMock:
    """Return a mock Redis client whose incr() returns values from the sequence."""
    redis = MagicMock()
    if incr_sequence is not None:
        redis.incr.side_effect = incr_sequence
    else:
        redis.incr.return_value = 1
    redis.expire.return_value = True
    return redis


def _make_kb_mock(entries: list | None = None) -> MagicMock:
    kb = MagicMock()
    kb.query.return_value = entries or []
    return kb


def _make_client(
    config: Config | None = None,
    redis_mock: MagicMock | None = None,
    kb_mock: MagicMock | None = None,
) -> object:
    from pr_reviewer.kb.mcp_client import MCPClient

    return MCPClient(
        knowledge_base=kb_mock or _make_kb_mock(),
        config=config or Config(),
        redis_client=redis_mock or _make_redis_mock(),
    )


# ── Task 11.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_lookup_cve_calls_default_nvd_endpoint():
    """lookup_cve with default Config sends GET to the NVD base URL."""
    http = _make_http_mock()
    client = _make_client()

    with patch("httpx.Client", return_value=http):
        client.lookup_cve("CVE-2021-44228")

    called_url: str = http.get.call_args[0][0]
    assert called_url.startswith("https://services.nvd.nist.gov")


# ── Task 11.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_lookup_cve_calls_custom_endpoint_from_config():
    """lookup_cve uses custom NVD URL from Config.mcp_servers.nvd."""
    cfg = Config(mcp_servers=MCPServersConfig(nvd="http://proxy:9200"))
    http = _make_http_mock()
    client = _make_client(config=cfg)

    with patch("httpx.Client", return_value=http):
        client.lookup_cve("CVE-2021-44228")

    called_url: str = http.get.call_args[0][0]
    assert called_url.startswith("http://proxy:9200")


# ── Task 11.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_nvd_rate_limit_fallback_to_cve_snapshot(caplog):
    """When NVD token bucket is exhausted, KB is queried; result tagged source=fallback_corpus."""
    from pr_reviewer.kb.knowledge_base import KBEntry

    kb_entry = KBEntry(
        id="kb1",
        content="CVE-2021-44228 is a critical RCE in log4j",
        corpus="cve_snapshot",
        language_tag=None,
        category="security",
        score=0.9,
        model_version="v1",
    )
    kb = _make_kb_mock(entries=[kb_entry])
    redis = _make_redis_mock(incr_sequence=[11])  # bucket exhausted

    client = _make_client(kb_mock=kb, redis_mock=redis)

    with caplog.at_level(logging.WARNING):
        result = client.lookup_cve("CVE-2021-44228")

    kb.query.assert_called_once()
    assert result.source == "fallback_corpus"
    assert any("nvd" in r.message.lower() for r in caplog.records)


# ── Task 11.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_fallback_chain_mcp_unavailable_and_corpus_empty():
    """NVD returns 503 AND KB is empty → EscalationResult with reason field."""
    from pr_reviewer.kb.mcp_client import EscalationResult

    http = _make_http_mock(status_code=503)
    kb = _make_kb_mock(entries=[])
    client = _make_client(kb_mock=kb)

    with patch("httpx.Client", return_value=http):
        result = client.lookup_cve("CVE-2021-44228")

    assert isinstance(result, EscalationResult)
    assert "could not verify" in result.reason.lower()


# ── Task 11.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_traceparent_header_on_every_mcp_call():
    """All outbound MCP calls carry a W3C traceparent header."""
    captured_headers: list[dict] = []

    http = MagicMock()
    http.__enter__ = MagicMock(return_value=http)
    http.__exit__ = MagicMock(return_value=False)

    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {}

    def _capture_get(url: str, **kwargs: object) -> MagicMock:
        captured_headers.append(dict(kwargs.get("headers", {})))
        return response

    def _capture_post(url: str, **kw: object) -> MagicMock:
        captured_headers.append(dict(kw.get("headers", {})))  # type: ignore[arg-type]
        return response

    http.get.side_effect = _capture_get
    http.post.side_effect = _capture_post

    client = _make_client()

    with patch("httpx.Client", return_value=http):
        client.lookup_cve("CVE-2021-44228")

    assert len(captured_headers) >= 1, "No HTTP calls were made"
    for hdrs in captured_headers:
        tp = hdrs.get("traceparent", "")
        assert _W3C_TRACEPARENT_RE.match(tp), f"Invalid traceparent: {tp!r}"


# ── Task 11.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_rate_limit_bucket_per_server_independent():
    """NVD bucket exhausted while OSV bucket available — lookups are independent."""
    from pr_reviewer.kb.knowledge_base import KBEntry
    from pr_reviewer.kb.mcp_client import CVEAdvisory

    kb_entry = KBEntry(
        id="kb1",
        content="description",
        corpus="cve_snapshot",
        language_tag=None,
        category="security",
        score=0.9,
        model_version="v1",
    )
    kb = _make_kb_mock(entries=[kb_entry])

    # Redis returns 11 for first call (NVD exhausted), 1 for second (OSV available)
    redis = _make_redis_mock(incr_sequence=[11, 1])
    http = _make_http_mock()
    client = _make_client(kb_mock=kb, redis_mock=redis)

    with patch("httpx.Client", return_value=http):
        nvd_result = client.lookup_cve("CVE-2021-44228")
        osv_result = client.check_package_advisory("log4j")

    # NVD was rate-limited → fell back to KB
    assert nvd_result.source == "fallback_corpus"
    # OSV was NOT rate-limited → made an HTTP call
    assert isinstance(osv_result, CVEAdvisory)
    assert osv_result.source == "osv"


# ── Task 11.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_nvd_rate_limit_bucket_is_10_per_minute():
    """10th NVD call succeeds; 11th triggers fallback."""
    from pr_reviewer.kb.mcp_client import CVEAdvisory, EscalationResult

    http = _make_http_mock()
    kb = _make_kb_mock(entries=[])  # KB empty so 11th → EscalationResult

    # 10 successful calls then bucket hits 11
    incr_seq = list(range(1, 12))  # 1, 2, ..., 11
    redis = _make_redis_mock(incr_sequence=incr_seq)
    client = _make_client(kb_mock=kb, redis_mock=redis)

    results = []
    with patch("httpx.Client", return_value=http):
        for i in range(11):
            results.append(client.lookup_cve(f"CVE-2021-{i:05d}"))

    http_call_count = http.get.call_count
    assert http_call_count == 10, f"Expected 10 HTTP calls, got {http_call_count}"
    assert isinstance(results[9], CVEAdvisory), "10th should succeed"
    assert isinstance(results[10], EscalationResult), "11th should escalate (KB empty)"
