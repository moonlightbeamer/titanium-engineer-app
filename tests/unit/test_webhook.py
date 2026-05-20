"""Unit tests for WebhookReceiver (tasks 5.1–5.12)."""

import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ── Helpers ───────────────────────────────────────────────────────────────────

SECRET = "test_webhook_secret_abc123"  # noqa: S105


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _pr_payload(action: str = "opened", draft: bool = False) -> bytes:
    return json.dumps(
        {
            "action": action,
            "installation": {"id": 42},
            "repository": {"full_name": "org/repo"},
            "pull_request": {
                "number": 7,
                "head": {"sha": "abc123"},
                "draft": draft,
            },
        }
    ).encode()


def _review_comment_payload() -> bytes:
    return json.dumps(
        {
            "action": "created",
            "installation": {"id": 42},
            "repository": {"full_name": "org/repo"},
        }
    ).encode()


# ── App fixture ───────────────────────────────────────────────────────────────


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    from pr_reviewer.api.main import build_app

    app = build_app()
    return TestClient(app, raise_server_exceptions=False)


# ── Task 5.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.api.webhook.process_review_job")
def test_valid_hmac_returns_202(mock_task, client):
    body = _pr_payload()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Event": "pull_request",
            "X-Forwarded-For": "10.0.1.1",
        },
    )
    assert resp.status_code == 202


# ── Task 5.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_missing_signature_header_returns_401(client):
    resp = client.post(
        "/webhook/github",
        content=_pr_payload(),
        headers={"X-GitHub-Event": "pull_request", "X-Forwarded-For": "10.0.1.2"},
    )
    assert resp.status_code == 401


# ── Task 5.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_invalid_hmac_returns_401(client):
    body = _pr_payload()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, secret="wrong_secret"),  # noqa: S106
            "X-GitHub-Event": "pull_request",
            "X-Forwarded-For": "10.0.1.3",
        },
    )
    assert resp.status_code == 401


# ── Task 5.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.api.webhook.process_review_job")
def test_rate_limit_100_per_minute_returns_429(mock_task, client):
    body = _pr_payload()
    sig = _sign(body)
    ip = "10.1.0.1"  # unique IP for this test

    responses = [
        client.post(
            "/webhook/github",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "pull_request",
                "X-Forwarded-For": ip,
            },
        )
        for _ in range(101)
    ]
    assert responses[-1].status_code == 429
    assert all(r.status_code == 202 for r in responses[:100])


# ── Task 5.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.api.webhook.process_review_job")
def test_rate_limit_different_ips_have_separate_buckets(mock_task, client):
    body = _pr_payload()
    sig = _sign(body)
    ip_a = "10.2.0.1"
    ip_b = "10.2.0.2"

    # Exhaust IP A's budget
    for _ in range(100):
        client.post(
            "/webhook/github",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "pull_request",
                "X-Forwarded-For": ip_a,
            },
        )
    # 101st from IP A → 429
    over_limit = client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "pull_request",
            "X-Forwarded-For": ip_a,
        },
    )
    assert over_limit.status_code == 429

    # IP B is unaffected
    resp_b = client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "pull_request",
            "X-Forwarded-For": ip_b,
        },
    )
    assert resp_b.status_code == 202


# ── Task 5.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.api.webhook.process_review_job")
def test_pull_request_opened_enqueues_review_job(mock_task, client):
    body = _pr_payload(action="opened")
    client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Event": "pull_request",
            "X-Forwarded-For": "10.3.0.1",
        },
    )
    mock_task.apply_async.assert_called_once()
    call_kwargs = mock_task.apply_async.call_args
    assert call_kwargs.kwargs.get("queue") == "review_jobs" or (
        call_kwargs.args and call_kwargs.args[0].get("queue") == "review_jobs"
    ) or call_kwargs.kwargs.get("queue") == "review_jobs"


# ── Task 5.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.api.webhook.process_feedback_job")
def test_pull_request_review_comment_enqueues_feedback_job(mock_task, client):
    body = _review_comment_payload()
    client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Event": "pull_request_review_comment",
            "X-Forwarded-For": "10.3.0.2",
        },
    )
    mock_task.apply_async.assert_called_once()


# ── Task 5.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.api.webhook.process_feedback_job")
def test_pull_request_review_event_enqueues_feedback_job(mock_task, client):
    body = _review_comment_payload()
    client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Event": "pull_request_review",
            "X-Forwarded-For": "10.3.0.3",
        },
    )
    mock_task.apply_async.assert_called_once()


# ── Task 5.9 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.api.webhook.process_review_job")
def test_draft_pr_not_enqueued_when_review_draft_prs_false(mock_task, monkeypatch, client):
    monkeypatch.setenv("REVIEW_DRAFT_PRS", "false")
    body = _pr_payload(action="opened", draft=True)
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Event": "pull_request",
            "X-Forwarded-For": "10.3.0.4",
        },
    )
    assert resp.status_code == 202
    mock_task.apply_async.assert_not_called()


# ── Task 5.10 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.api.webhook.process_review_job")
def test_ack_time_under_3_seconds(mock_task, client):
    # Celery task is mocked — ACK should be near-instant
    body = _pr_payload()
    start = time.monotonic()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Event": "pull_request",
            "X-Forwarded-For": "10.3.0.5",
        },
    )
    elapsed = time.monotonic() - start
    assert resp.status_code == 202
    assert elapsed < 3.0, f"ACK took {elapsed:.2f}s — must be under 3s"


# ── Task 5.11 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.api.webhook.process_review_job")
@patch("pr_reviewer.api.webhook._queue_depth")
def test_queue_depth_gauge_incremented(mock_gauge, mock_task, client):
    body = _pr_payload()
    client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Event": "pull_request",
            "X-Forwarded-For": "10.3.0.6",
        },
    )
    mock_gauge.add.assert_called_once_with(1, {"queue": "review_jobs"})


# ── Task 5.12 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
@patch("pr_reviewer.api.webhook.process_review_job")
def test_unsupported_event_returns_200_and_not_enqueued(mock_task, client):
    body = json.dumps({"zen": "Keep it logically awesome."}).encode()
    resp = client.post(
        "/webhook/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body),
            "X-GitHub-Event": "ping",
            "X-Forwarded-For": "10.3.0.7",
        },
    )
    assert resp.status_code == 200
    mock_task.apply_async.assert_not_called()
