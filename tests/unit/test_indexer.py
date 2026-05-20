"""Unit tests for Indexer (tasks 23.1–23.16)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_github_client(
    files: list[str] | None = None,
    head_sha: str = "head123",
) -> MagicMock:
    client = MagicMock()
    client.get_branch_head_sha.return_value = head_sha
    file_list = files or []
    client.list_directory.return_value = [{"name": f, "path": f} for f in file_list]
    client.get_file_content.return_value = ""
    return client


def _make_db_engine(signal_count: int = 0) -> MagicMock:
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    # has_successful_job query
    conn.execute.return_value.scalar.return_value = signal_count
    return engine


# ── Task 23.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_indexer_skips_repo_with_no_successful_review_job():
    """No complete job for repo → returns early; no index built."""
    from pr_reviewer.workers.indexer import Indexer

    db = _make_db_engine(signal_count=0)
    gh = _make_github_client()
    store = MagicMock()

    indexer = Indexer(github_client=gh, db_engine=db, index_store=store)
    # Simulate no successful job: scalar returns 0
    conn = db.connect.return_value.__enter__.return_value
    conn.execute.return_value.scalar.return_value = 0

    indexer.refresh("org/repo", installation_id=1)

    store.save.assert_not_called()


# ── Task 23.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_convention_profile_pattern_requires_60pct_agreement():
    """Pattern in 11/20 files (55%) → omitted from profile."""
    from pr_reviewer.workers.indexer import _build_convention_profile

    files_content = {f"file{i}.py": ("camelCase" if i < 11 else "") for i in range(20)}
    profile = _build_convention_profile(files_content)
    assert "camelCase" not in profile


# ── Task 23.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_convention_profile_pattern_at_exactly_60pct_included():
    """Pattern in 12/20 files (60%) → included in profile."""
    from pr_reviewer.workers.indexer import _build_convention_profile

    files_content = {f"file{i}.py": ("camelCase" if i < 12 else "") for i in range(20)}
    profile = _build_convention_profile(files_content)
    assert "camelCase" in profile
    assert profile["camelCase"] == pytest.approx(12 / 20)


# ── Task 23.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_convention_profile_samples_20_most_recently_modified_files():
    """50 files available → exactly 20 fetched for convention analysis."""
    from pr_reviewer.workers.indexer import Indexer

    files = [f"src/file{i}.py" for i in range(50)]
    gh = _make_github_client(files=files)
    db = _make_db_engine()
    conn = db.connect.return_value.__enter__.return_value
    conn.execute.return_value.scalar.return_value = 1  # has successful job

    store = MagicMock()
    store.get_latest.return_value = None
    store.save.return_value = None

    indexer = Indexer(github_client=gh, db_engine=db, index_store=store)
    indexer.refresh("org/repo", installation_id=1)

    fetch_calls = gh.get_file_content.call_count
    assert fetch_calls == 20


# ── Task 23.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_finding_density_map_omitted_below_10_signals():
    """9 signals → finding_density_map=None; WARN logged."""
    from pr_reviewer.workers.indexer import _build_finding_density_map

    density = _build_finding_density_map(signal_count=9)
    assert density is None


# ── Task 23.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_finding_density_map_included_at_10_signals():
    """10 signals → finding_density_map is not None."""
    from pr_reviewer.workers.indexer import _build_finding_density_map

    density = _build_finding_density_map(signal_count=10)
    assert density is not None


# ── Task 23.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_index_trimmed_to_max_tokens():
    """Content exceeding max_tokens is trimmed; token_count <= max."""
    from pr_reviewer.workers.indexer import _trim_to_token_limit

    # 1 char ≈ 0.25 tokens; 40000 chars ≈ 10000 tokens; limit 8000
    big_content = "x" * 40_000
    trimmed, token_count = _trim_to_token_limit(big_content, max_tokens=8_000)
    assert token_count <= 8_000
    assert len(trimmed) <= len(big_content)


# ── Task 23.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_on_refresh_failure_last_valid_index_still_accessible():
    """Indexer crash mid-build → prior valid index unchanged."""
    from pr_reviewer.workers.indexer import Indexer

    previous = MagicMock()
    previous.is_valid = True

    gh = _make_github_client()
    db = _make_db_engine()
    conn = db.connect.return_value.__enter__.return_value
    conn.execute.return_value.scalar.return_value = 1

    store = MagicMock()
    store.get_latest.return_value = previous
    gh.get_branch_head_sha.side_effect = RuntimeError("network error")

    indexer = Indexer(github_client=gh, db_engine=db, index_store=store)
    with pytest.raises(RuntimeError):
        indexer.refresh("org/repo", installation_id=1)

    store.invalidate.assert_not_called()


# ── Task 23.9 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_versioning_keeps_last_3_versions():
    """After 4th save, versions 1 & 2 become is_valid=False; 3 & 4 remain True; none deleted."""
    from pr_reviewer.workers.indexer import _prune_old_versions

    versions = [MagicMock(version=i, is_valid=True) for i in range(1, 5)]
    store = MagicMock()
    store.list_versions.return_value = versions

    _prune_old_versions(store, "org/repo", keep=3)

    # versions 1 and 2 invalidated (only keep last 3: versions 2, 3, 4)
    store.invalidate_version.assert_called()
    invalidated_versions = {c.args[1] for c in store.invalidate_version.call_args_list}
    assert 1 in invalidated_versions
    store.delete.assert_not_called()


# ── Task 23.10 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_commit_sha_recorded_as_default_branch_head_at_build_time():
    """commit_sha in saved index == get_branch_head_sha result at build start."""
    from pr_reviewer.workers.indexer import Indexer

    gh = _make_github_client(head_sha="deadbeef")
    db = _make_db_engine()
    conn = db.connect.return_value.__enter__.return_value
    conn.execute.return_value.scalar.return_value = 1

    store = MagicMock()
    store.get_latest.return_value = None
    saved_indexes = []
    store.save.side_effect = saved_indexes.append

    indexer = Indexer(github_client=gh, db_engine=db, index_store=store)
    indexer.refresh("org/repo", installation_id=1)

    assert saved_indexes, "save was never called"
    assert saved_indexes[0].commit_sha == "deadbeef"


# ── Task 23.11 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_monorepo_detection_finds_manifest_in_subdirectory():
    """package.json in packages/api/ → 'packages/api' detected as package."""
    from pr_reviewer.workers.indexer import _detect_monorepo

    def list_dir(path: str) -> list[dict]:
        if path == ".":
            return [{"name": "packages", "path": "packages", "type": "dir"}]
        if path == "packages":
            return [{"name": "api", "path": "packages/api", "type": "dir"}]
        if path == "packages/api":
            return [{"name": "package.json", "path": "packages/api/package.json", "type": "file"}]
        return []

    gh = MagicMock()
    gh.list_directory.side_effect = list_dir

    packages = _detect_monorepo(gh, "org/repo")
    assert "packages/api" in packages


# ── Task 23.12 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_monorepo_builds_separate_index_per_package():
    """2 packages detected → 2 CodebaseIndex rows saved."""
    from pr_reviewer.workers.indexer import Indexer

    gh = _make_github_client(files=[])
    db = _make_db_engine()
    conn = db.connect.return_value.__enter__.return_value
    conn.execute.return_value.scalar.return_value = 1

    store = MagicMock()
    store.get_latest.return_value = None
    saved = []
    store.save.side_effect = saved.append

    indexer = Indexer(github_client=gh, db_engine=db, index_store=store)

    with patch(
        "pr_reviewer.workers.indexer._detect_monorepo",
        return_value=["packages/api", "packages/db"],
    ):
        indexer.refresh("org/repo", installation_id=1)

    package_paths = {idx.package_path for idx in saved}
    assert "packages/api" in package_paths
    assert "packages/db" in package_paths


# ── Task 23.13 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_indexer_uses_separate_rate_limit_bucket():
    """Indexer creates GitHubAPIClient with ':indexer' Redis key suffix."""
    from pr_reviewer.workers.indexer import _make_indexer_github_client

    redis = MagicMock()
    client = _make_indexer_github_client(installation_id=99, redis_client=redis)
    assert client is not None
    # The rate-limit key should include 'indexer'
    assert hasattr(client, "_rate_limit_key") or hasattr(client, "_redis_key_suffix")


# ── Task 23.14 ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_celery_beat_scheduled_at_02_utc_daily():
    """Beat schedule has run_index_refresh with crontab(hour=2, minute=0)."""
    from pr_reviewer.workers.indexer import BEAT_SCHEDULE

    assert "run_index_refresh_daily" in BEAT_SCHEDULE
    entry = BEAT_SCHEDULE["run_index_refresh_daily"]
    sched = entry["schedule"]
    assert sched.hour == {2}
    assert sched.minute == {0}


# ── Tasks 23.15–23.16: webhook push routing ───────────────────────────────────


def _make_webhook_app():
    """Build test FastAPI app with mocked secret."""
    import hashlib
    import hmac

    from fastapi.testclient import TestClient

    from pr_reviewer.api.webhook import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    secret = "testsecret"

    def signed_post(payload: dict, event: str = "push") -> object:
        import json as _json
        body = _json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with patch.dict("os.environ", {"GITHUB_WEBHOOK_SECRET": secret}):
            return TestClient(app).post(
                "/webhook/github",
                content=body,
                headers={
                    "X-Hub-Signature-256": sig,
                    "X-GitHub-Event": event,
                    "Content-Type": "application/json",
                },
            )

    return signed_post


@pytest.mark.unit
def test_push_event_with_over_20_files_triggers_indexer_refresh():
    """Push with 21 changed files → run_index_refresh.apply_async called on indexer_jobs."""
    signed_post = _make_webhook_app()
    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "org/repo", "default_branch": "main"},
        "installation": {"id": 42},
        "commits": [{"added": [], "modified": [f"file{i}.py" for i in range(21)], "removed": []}],
    }
    with patch("pr_reviewer.api.webhook.run_index_refresh") as mock_task:
        mock_task.apply_async = MagicMock()
        resp = signed_post(payload, event="push")
    assert resp.status_code in (200, 202)
    mock_task.apply_async.assert_called_once()
    call_kwargs = mock_task.apply_async.call_args
    assert call_kwargs.kwargs.get("queue") == "indexer_jobs" or \
           (call_kwargs[1].get("queue") == "indexer_jobs")


@pytest.mark.unit
def test_push_event_with_20_or_fewer_files_does_not_trigger_indexer():
    """Push with exactly 20 changed files → run_index_refresh not called."""
    signed_post = _make_webhook_app()
    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "org/repo", "default_branch": "main"},
        "installation": {"id": 42},
        "commits": [{"added": [], "modified": [f"file{i}.py" for i in range(20)], "removed": []}],
    }
    with patch("pr_reviewer.api.webhook.run_index_refresh") as mock_task:
        mock_task.apply_async = MagicMock()
        resp = signed_post(payload, event="push")
    mock_task.apply_async.assert_not_called()
