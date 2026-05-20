"""Unit tests for evaluation harness scaffold (task 18)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).parent.parent.parent / "eval"
ALEMBIC_VERSIONS = Path(__file__).parent.parent.parent / "alembic" / "versions"


# ── Task 18.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_eval_package_has_zero_pr_reviewer_imports():
    """eval/ directory contains no 'from pr_reviewer' imports."""
    result = subprocess.run(
        ["grep", "-r", "--include=*.py", "from pr_reviewer", str(EVAL_DIR)],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "", (
        f"Found pr_reviewer imports in eval/:\n{result.stdout}"
    )


# ── Task 18.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_inspect_task_suite_dry_runs_without_error():
    """eval/tasks/ exists and its modules are importable without error."""
    tasks_dir = EVAL_DIR / "tasks"
    assert tasks_dir.is_dir(), "eval/tasks/ directory missing"
    for py_file in tasks_dir.glob("*.py"):
        if py_file.stem.startswith("_"):
            continue
        result = subprocess.run(
            [".venv/bin/python", "-c", f"import importlib; importlib.import_module('eval.tasks.{py_file.stem}')"],
            capture_output=True,
            text=True,
            cwd=str(EVAL_DIR.parent),
        )
        assert result.returncode == 0, (
            f"eval/tasks/{py_file.name} failed to import:\n{result.stderr}"
        )


# ── Task 18.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_eval_runs_table_created_by_migration():
    """Migration 004 exists and defines the eval_runs table with required columns."""
    migration_file = ALEMBIC_VERSIONS / "004_eval_runs.py"
    assert migration_file.exists(), "alembic/versions/004_eval_runs.py missing"
    content = migration_file.read_text()
    for col in ("eval_runs", "run_type", "started_at", "completed_at", "report", "corpus_version"):
        assert col in content, f"Column/table '{col}' missing from migration 004"


# ── Task 18.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_corpus_raises_if_fewer_than_20_prs():
    """19 labeled samples → CorpusValidationError('corpus requires ≥20 PRs')."""
    from eval.corpus import CorpusValidationError, load_corpus

    samples = _make_samples(total=19, safe=10, security=5)
    with pytest.raises(CorpusValidationError, match="≥20 PRs"):
        load_corpus(samples=samples)


# ── Task 18.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_corpus_raises_if_fewer_than_10_safe_prs():
    """20 total, 9 safe → CorpusValidationError."""
    from eval.corpus import CorpusValidationError, load_corpus

    samples = _make_samples(total=20, safe=9, security=5)
    with pytest.raises(CorpusValidationError, match="safe"):
        load_corpus(samples=samples)


# ── Task 18.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_corpus_raises_if_fewer_than_5_security_prs():
    """20 total, 10 safe, 4 security → CorpusValidationError."""
    from eval.corpus import CorpusValidationError, load_corpus

    samples = _make_samples(total=20, safe=10, security=4)
    with pytest.raises(CorpusValidationError, match="security"):
        load_corpus(samples=samples)


# ── Task 18.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_corpus_valid_with_minimum_required_prs():
    """20 PRs, 10 safe, 5 security → load_corpus() succeeds and returns list."""
    from eval.corpus import load_corpus

    samples = _make_samples(total=20, safe=10, security=5)
    result = load_corpus(samples=samples)
    assert isinstance(result, list)
    assert len(result) == 20


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_samples(*, total: int, safe: int, security: int) -> list[dict]:
    """Build a list of raw sample dicts for corpus validation tests."""
    samples: list[dict] = []
    for i in range(total):
        if i < security:
            label = "security"
        elif i < security + safe:
            label = "safe"
        else:
            label = "bugs"
        samples.append({"id": str(i), "category": label, "diff": f"diff_{i}"})
    return samples
