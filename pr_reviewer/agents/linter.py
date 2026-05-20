"""Linter and license tools for v2 agent — subprocess-based linting and license checks."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pr_reviewer.logging import get_logger
from pr_reviewer.models.enums import Confidence, ReviewCategory, Severity
from pr_reviewer.models.finding import Finding

_logger = get_logger(__name__)

_LANGUAGE_BINARY: dict[str, str] = {
    "python": "pylint",
    "javascript": "eslint",
    "typescript": "eslint",
    "go": "golangci-lint",
}

_COPYLEFT_LICENSES = frozenset({
    "AGPL-3.0", "AGPL-3.0-only", "AGPL-3.0-or-later",
    "GPL-3.0", "GPL-3.0-only", "GPL-3.0-or-later",
    "GPL-2.0", "GPL-2.0-only", "GPL-2.0-or-later",
    "LGPL-3.0", "LGPL-3.0-only",
})

_PERMISSIVE_POLICIES = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"})


@dataclass(frozen=True)
class LintTarget:
    filename: str
    language: str
    changed_line_count: int


@dataclass(frozen=True)
class LinterFinding:
    file_path: str
    line_number: int
    message: str
    rule_id: str


@dataclass(frozen=True)
class LicenseResult:
    package_name: str
    license: str
    is_violation: bool
    policy: str


def run_linter(targets: list[LintTarget], max_files: int) -> list[LinterFinding]:
    """Run the appropriate linter per file; return aggregated findings."""
    sorted_targets = sorted(targets, key=lambda t: t.changed_line_count, reverse=True)

    if len(sorted_targets) > max_files:
        skipped = sorted_targets[max_files:]
        _logger.warning(
            f"Linter file cap ({max_files}) reached; skipping "
            f"{len(skipped)} file(s): {[t.filename for t in skipped]}"
        )
        sorted_targets = sorted_targets[:max_files]

    findings: list[LinterFinding] = []
    for target in sorted_targets:
        findings.extend(_lint_one(target))
    return findings


def _lint_one(target: LintTarget) -> list[LinterFinding]:
    binary = _LANGUAGE_BINARY.get(target.language)
    if binary is None:
        return []

    try:
        result = subprocess.run(
            [binary, target.filename],
            capture_output=True,
            timeout=30,
            text=True,
        )
        return _parse_output(result.stdout or result.stderr, target.filename)
    except FileNotFoundError:
        _logger.warning(f"linter unavailable for {target.language}: {binary} not found on PATH")
        return []
    except subprocess.TimeoutExpired:
        _logger.warning(f"linter timed out (30s) for {target.filename}")
        return []


def _parse_output(output: str, filename: str) -> list[LinterFinding]:
    findings: list[LinterFinding] = []
    for line in output.splitlines():
        m = re.match(r"(?:[^:]+:)?(\d+):\d*:?\s*([EWC]\w+)?\s*(.*)", line)
        if m and m.group(3).strip():
            findings.append(LinterFinding(
                file_path=filename,
                line_number=int(m.group(1)),
                message=m.group(3).strip(),
                rule_id=m.group(2) or "unknown",
            ))
    return findings


def check_license(
    package_name: str,
    version: str,
    policy: str,
    *,
    license_fetcher: Any = None,
) -> LicenseResult:
    """Check whether a package's license violates the given policy."""
    if license_fetcher is not None:
        license_id = license_fetcher(package_name, version)
    else:
        license_id = _fetch_license_stub(package_name)

    is_violation = _is_license_violation(license_id, policy)
    return LicenseResult(
        package_name=package_name,
        license=license_id,
        is_violation=is_violation,
        policy=policy,
    )


def _fetch_license_stub(package_name: str) -> str:  # noqa: ARG001
    return "unknown"


def _is_license_violation(license_id: str, policy: str) -> bool:
    if policy in _PERMISSIVE_POLICIES:
        return license_id in _COPYLEFT_LICENSES
    return False


def detect_new_package_json_deps(diff_content: str) -> list[tuple[str, str]]:
    """Extract newly-added (package, version) pairs from a package.json diff."""
    deps: list[tuple[str, str]] = []
    in_deps_block = False

    for line in diff_content.splitlines():
        if '"dependencies"' in line or '"devDependencies"' in line:
            in_deps_block = True
        if in_deps_block and line.startswith("+") and not line.startswith("+++"):
            m = re.search(r'"([^"]+)"\s*:\s*"([^"]+)"', line[1:])
            if m:
                deps.append((m.group(1), m.group(2)))
    return deps


def license_violation_to_finding(
    result: LicenseResult,
    *,
    file_path: str = "package.json",
    job_id: Any = None,
) -> Finding | None:
    """Convert a LicenseResult with is_violation=True into a high-severity Finding."""
    if not result.is_violation:
        return None
    return Finding(
        id=uuid4(),
        job_id=job_id or uuid4(),
        file_path=file_path,
        line_number=1,
        category=ReviewCategory.bugs,
        severity=Severity.high,
        confidence=Confidence.high,
        explanation=(
            f"Package '{result.package_name}' uses the {result.license} license "
            f"which is incompatible with this project's {result.policy} policy."
        ),
        is_escalation=False,
    )
