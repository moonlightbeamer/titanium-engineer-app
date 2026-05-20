"""Unit tests for GitHubAPIClient (tasks 4.1–4.11)."""

import json
import re
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from pr_reviewer.store.github_client import AuthError, GitHubAPIClient, RateLimitError
from pr_reviewer.telemetry import setup_telemetry

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def rsa_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


@pytest.fixture(autouse=True)
def telemetry_setup():
    setup_telemetry("test")


class _MockTransport(httpx.BaseTransport):
    """Captures requests; serves pre-programmed httpx.Response objects."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            raise RuntimeError("No more mock responses queued")
        return self._responses.pop(0)


def _redis_miss() -> MagicMock:
    r = MagicMock()
    r.get.return_value = None
    return r


def _token_response(token: str = "ghs_test", expires_in: int = 3600) -> httpx.Response:  # noqa: S107
    expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()
    return httpx.Response(
        200,
        json={"token": token, "expires_at": expires_at},
        request=httpx.Request("POST", "https://api.github.com/"),
    )


def _make_client(
    rsa_key: str,
    transport: _MockTransport,
    redis: MagicMock | None = None,
    installation_id: int = 42,
    app_id: str = "99999",
) -> GitHubAPIClient:
    return GitHubAPIClient(
        installation_id=installation_id,
        redis_client=redis or _redis_miss(),
        app_id=app_id,
        private_key=rsa_key,
        http_client=httpx.Client(
            base_url="https://api.github.com",
            transport=transport,
        ),
    )


# ── Task 4.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_jwt_has_correct_claims(rsa_key_pem):
    client = GitHubAPIClient(
        installation_id=1,
        redis_client=_redis_miss(),
        app_id="99999",
        private_key=rsa_key_pem,
        http_client=httpx.Client(transport=_MockTransport([])),
    )
    token = client._generate_jwt()
    # Decode without verification to inspect claims
    claims = jwt.decode(token, options={"verify_signature": False})

    now = int(time.time())
    assert claims["iss"] == "99999"
    assert "iat" in claims
    assert "exp" in claims
    assert 50 <= claims["exp"] - now <= 70, "exp should be ~60s from now"


# ── Task 4.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_token_exchange_sends_jwt_as_bearer(rsa_key_pem):
    transport = _MockTransport([_token_response()])
    client = _make_client(rsa_key_pem, transport)

    client.get_access_token()

    req = transport.requests[0]
    auth = req.headers.get("authorization", "")
    assert auth.startswith("Bearer "), f"Expected Bearer token, got: {auth}"
    bearer_token = auth.removeprefix("Bearer ")
    claims = jwt.decode(bearer_token, options={"verify_signature": False})
    assert claims["iss"] == "99999"


# ── Task 4.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_token_cached_in_redis(rsa_key_pem):
    transport = _MockTransport([_token_response()])
    expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    redis = MagicMock()
    redis.get.return_value = json.dumps({"token": "cached_tok", "expires_at": expires_at}).encode()

    client = _make_client(rsa_key_pem, transport, redis=redis)
    token = client.get_access_token()

    assert token == "cached_tok"  # noqa: S105
    assert len(transport.requests) == 0, "Should not have made an HTTP call on cache hit"


# ── Task 4.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_token_refreshed_4_min_before_expiry(rsa_key_pem):
    # Token expiring in 3 minutes — below the 4-minute refresh threshold
    transport = _MockTransport([_token_response(token="fresh_tok")])  # noqa: S106
    expires_at = (datetime.now(UTC) + timedelta(minutes=3)).isoformat()
    redis = MagicMock()
    redis.get.return_value = json.dumps({"token": "old_tok", "expires_at": expires_at}).encode()

    client = _make_client(rsa_key_pem, transport, redis=redis)
    token = client.get_access_token()

    assert token == "fresh_tok", "Should have proactively refreshed"  # noqa: S105
    assert len(transport.requests) == 1


# ── Task 4.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_401_raises_auth_error_no_retry(rsa_key_pem):
    transport = _MockTransport(
        [
            httpx.Response(
                401,
                json={"message": "Bad credentials"},
                request=httpx.Request("GET", "https://api.github.com/"),
            )
        ]
    )
    client = _make_client(rsa_key_pem, transport)

    with pytest.raises(AuthError):
        client._request("GET", "/repos/org/repo/pulls/1")

    assert len(transport.requests) == 1, "Must not retry on 401"


# ── Task 4.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.store.github_client.time.sleep")
def test_403_rate_limit_retries_with_retry_after_header(mock_sleep, rsa_key_pem):
    transport = _MockTransport(
        [
            httpx.Response(
                403,
                headers={"Retry-After": "2"},
                json={},
                request=httpx.Request("GET", "https://api.github.com/"),
            ),
            httpx.Response(
                403,
                headers={"Retry-After": "2"},
                json={},
                request=httpx.Request("GET", "https://api.github.com/"),
            ),
            httpx.Response(
                403,
                headers={"Retry-After": "2"},
                json={},
                request=httpx.Request("GET", "https://api.github.com/"),
            ),
        ]
    )
    client = _make_client(rsa_key_pem, transport)

    with pytest.raises(RateLimitError):
        client._request("GET", "/repos/org/repo/pulls/1")

    assert mock_sleep.call_count == 2  # sleeps between attempts 1→2 and 2→3
    mock_sleep.assert_called_with(2)


# ── Task 4.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.store.github_client.time.sleep")
def test_429_rate_limit_same_behavior_as_403(mock_sleep, rsa_key_pem):
    transport = _MockTransport(
        [
            httpx.Response(
                429,
                headers={"Retry-After": "1"},
                json={},
                request=httpx.Request("GET", "https://api.github.com/"),
            )
            for _ in range(3)
        ]
    )
    client = _make_client(rsa_key_pem, transport)

    with pytest.raises(RateLimitError):
        client._request("GET", "/repos/org/repo/pulls/1")

    assert mock_sleep.call_count == 2


# ── Task 4.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_compare_commits_calls_correct_endpoint(rsa_key_pem):
    transport = _MockTransport(
        [
            _token_response(),
            httpx.Response(
                200,
                json={"files": []},
                request=httpx.Request("GET", "https://api.github.com/"),
            ),
        ]
    )
    client = _make_client(rsa_key_pem, transport)
    client.compare_commits("org/repo", "sha1", "sha2")

    compare_req = transport.requests[-1]
    assert "/compare/sha1...sha2" in str(compare_req.url)


# ── Task 4.9 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_post_review_sends_correct_payload(rsa_key_pem):
    transport = _MockTransport(
        [
            _token_response(),
            httpx.Response(
                200,
                json={"id": 1},
                request=httpx.Request("POST", "https://api.github.com/"),
            ),
        ]
    )
    client = _make_client(rsa_key_pem, transport)
    client.post_review(
        repo="org/repo",
        pr_number=7,
        body="LGTM",
        event="COMMENT",
        comments=[{"path": "foo.py", "line": 10, "body": "fix this"}],
    )

    review_req = transport.requests[-1]
    body = json.loads(review_req.content)
    assert body["event"] == "COMMENT"
    assert body["body"] == "LGTM"
    assert len(body["comments"]) == 1
    assert "/pulls/7/reviews" in str(review_req.url)


# ── Task 4.10 ────────────────────────────────────────────────────────────────

_TRACEPARENT_RE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


@pytest.mark.unit
def test_traceparent_header_on_every_outbound_call(rsa_key_pem):
    setup_telemetry("test")
    tracer = trace.get_tracer("test")
    transport = _MockTransport(
        [
            _token_response(),
            httpx.Response(
                200,
                json={"files": []},
                request=httpx.Request("GET", "https://api.github.com/"),
            ),
        ]
    )
    client = _make_client(rsa_key_pem, transport)

    with tracer.start_as_current_span("parent"):
        client.compare_commits("org/repo", "sha1", "sha2")

    for req in transport.requests:
        tp = req.headers.get("traceparent", "")
        assert _TRACEPARENT_RE.match(tp), f"Missing/invalid traceparent on {req.url}: {tp!r}"


# ── Task 4.11 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_otel_span_created_per_api_call(rsa_key_pem):
    setup_telemetry("test")
    # Add in-memory exporter to the existing provider (can't replace it after first set)
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.add_span_processor(SimpleSpanProcessor(exporter))

    transport = _MockTransport(
        [
            _token_response(),
            httpx.Response(
                200,
                json={"files": []},
                request=httpx.Request("GET", "https://api.github.com/"),
            ),
        ]
    )
    client = _make_client(rsa_key_pem, transport)
    client.compare_commits("org/repo", "sha1", "sha2")

    spans = exporter.get_finished_spans()
    span_names = [s.name for s in spans]
    assert any("github" in n for n in span_names), f"No github span found in: {span_names}"

    api_spans = [s for s in spans if "github" in s.name]
    for s in api_spans:
        assert "endpoint" in s.attributes or "status_code" in s.attributes
