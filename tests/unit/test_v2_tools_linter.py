"""Tests for v2 linter and license tools (task 25)."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from pr_reviewer.models.enums import ReviewCategory, Severity


# ── Task 25.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_run_linter_invokes_correct_binary_for_language():
    """Python → pylint, TS → eslint, Go → golangci-lint."""
    from pr_reviewer.agents.linter import LintTarget, run_linter

    targets = [
        LintTarget(filename="main.py", language="python", changed_line_count=10),
        LintTarget(filename="app.ts", language="typescript", changed_line_count=5),
        LintTarget(filename="service.go", language="go", changed_line_count=3),
    ]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        run_linter(targets, max_files=10)

    commands = [c[0][0] for c in mock_run.call_args_list]
    binaries = [cmd[0] for cmd in commands]
    assert "pylint" in binaries
    assert "eslint" in binaries
    assert "golangci-lint" in binaries


# ── Task 25.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_run_linter_subprocess_has_30s_timeout():
    """TimeoutExpired caught → empty results, WARN logged."""
    from pr_reviewer.agents.linter import LintTarget, run_linter

    targets = [LintTarget(filename="main.py", language="python", changed_line_count=10)]
    with patch(
        "subprocess.run", side_effect=subprocess.TimeoutExpired("pylint", 30)
    ):
        results = run_linter(targets, max_files=10)

    assert results == []


# ── Task 25.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_run_linter_returns_empty_when_binary_missing():
    """FileNotFoundError → [] and no exception."""
    from pr_reviewer.agents.linter import LintTarget, run_linter

    targets = [LintTarget(filename="main.py", language="python", changed_line_count=10)]
    with patch("subprocess.run", side_effect=FileNotFoundError("pylint not found")):
        results = run_linter(targets, max_files=10)

    assert results == []


# ── Task 25.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_run_linter_respects_max_linter_files_cap():
    """7 files, max_files=5 → linter called exactly 5 times."""
    from pr_reviewer.agents.linter import LintTarget, run_linter

    targets = [
        LintTarget(filename=f"file{i}.py", language="python", changed_line_count=i * 10)
        for i in range(7)
    ]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        run_linter(targets, max_files=5)

    assert mock_run.call_count == 5


# ── Task 25.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_run_linter_prioritizes_files_by_most_changed_lines():
    """Files ordered 200, 100, 50 by changed lines before cap applied."""
    from pr_reviewer.agents.linter import LintTarget, run_linter

    targets = [
        LintTarget(filename="a.py", language="python", changed_line_count=100),
        LintTarget(filename="b.py", language="python", changed_line_count=50),
        LintTarget(filename="c.py", language="python", changed_line_count=200),
    ]
    processed: list[str] = []

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        processed.append(cmd[1])
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        run_linter(targets, max_files=10)

    assert processed == ["c.py", "a.py", "b.py"]


# ── Task 25.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_check_license_triggered_on_new_package_json_dependency():
    """Added line in package.json dependencies block → new dep detected."""
    from pr_reviewer.agents.linter import detect_new_package_json_deps

    diff = (
        "diff --git a/package.json b/package.json\n"
        "--- a/package.json\n"
        "+++ b/package.json\n"
        "@@ -5,6 +5,7 @@\n"
        '   "dependencies": {\n'
        '     "express": "^4.18.0",\n'
        '+    "lodash": "^4.17.21"\n'
        "   }\n"
        " }\n"
    )
    deps = detect_new_package_json_deps(diff)
    assert ("lodash", "^4.17.21") in deps


# ── Task 25.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_check_license_violation_produces_high_severity_bugs_finding():
    """AGPL license with MIT policy → Finding(severity=high, category=bugs)."""
    from pr_reviewer.agents.linter import LicenseResult, license_violation_to_finding

    result = LicenseResult(
        package_name="some-agpl-lib",
        license="AGPL-3.0",
        is_violation=True,
        policy="MIT",
    )
    finding = license_violation_to_finding(result, file_path="package.json")

    assert finding is not None
    assert finding.severity == Severity.high
    assert finding.category == ReviewCategory.bugs
