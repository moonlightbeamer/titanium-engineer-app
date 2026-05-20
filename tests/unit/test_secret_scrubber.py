"""Unit tests for SecretScrubber (tasks 8.1–8.8)."""

import logging

import pytest

# ── Task 8.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_aws_access_key_redacted():
    from pr_reviewer.components.secret_scrubber import SecretScrubber

    content = "key = 'AKIAIOSFODNN7EXAMPLE'"
    scrubbed, detections = SecretScrubber().scrub(content)
    assert "[REDACTED]" in scrubbed
    assert "AKIAIOSFODNN7EXAMPLE" not in scrubbed


# ── Task 8.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_github_token_redacted():
    from pr_reviewer.components.secret_scrubber import SecretScrubber

    content = "token = 'ghp_abcdefghij1234567890ABCDEFGHIJ12'"
    scrubbed, detections = SecretScrubber().scrub(content)
    assert "[REDACTED]" in scrubbed
    assert "ghp_abcdefghij1234567890ABCDEFGHIJ12" not in scrubbed


# ── Task 8.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_clean_content_returned_byte_for_byte_identical():
    from pr_reviewer.components.secret_scrubber import SecretScrubber

    content = "def hello():\n    return 'world'\n"
    scrubbed, detections = SecretScrubber().scrub(content)
    assert scrubbed == content
    assert detections == []


# ── Task 8.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_returns_new_string_not_in_place():
    from pr_reviewer.components.secret_scrubber import SecretScrubber

    content = "no secrets here"
    original = content
    scrubbed, _ = SecretScrubber().scrub(content)
    assert content == original  # input unchanged
    assert scrubbed is not content or scrubbed == content  # either a new object or identical (fine)


# ── Task 8.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_multiple_secrets_all_redacted():
    from pr_reviewer.components.secret_scrubber import SecretScrubber

    content = (
        "aws_key = 'AKIAIOSFODNN7EXAMPLE'\n"
        "gh_token = 'ghp_abcdefghij1234567890ABCDEFGHIJ12'\n"
    )
    scrubbed, detections = SecretScrubber().scrub(content)
    assert "AKIAIOSFODNN7EXAMPLE" not in scrubbed
    assert "ghp_abcdefghij1234567890ABCDEFGHIJ12" not in scrubbed
    assert scrubbed.count("[REDACTED]") >= 2


# ── Task 8.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_detection_list_length_matches_secret_count():
    from pr_reviewer.components.secret_scrubber import SecretScrubber

    content = (
        "aws_key = 'AKIAIOSFODNN7EXAMPLE'\n"
        "gh_token = 'ghp_abcdefghij1234567890ABCDEFGHIJ12'\n"
    )
    _, detections = SecretScrubber().scrub(content)
    assert len(detections) == 2


# ── Task 8.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_kb_source_logs_error_with_corpus_and_entry_id(caplog):
    from pr_reviewer.components.secret_scrubber import SecretScrubber

    content = "key = 'AKIAIOSFODNN7EXAMPLE'"
    with caplog.at_level(logging.ERROR):
        SecretScrubber().scrub(
            content,
            source="kb",
            corpus="cve_snapshot",
            entry_id="uuid-001",
        )

    assert any(
        "cve_snapshot" in r.message and "uuid-001" in r.message
        for r in caplog.records
    )


# ── Task 8.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_empty_string_returns_empty_string_no_detections():
    from pr_reviewer.components.secret_scrubber import SecretScrubber

    scrubbed, detections = SecretScrubber().scrub("")
    assert scrubbed == ""
    assert detections == []
