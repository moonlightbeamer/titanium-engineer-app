"""CommentPoster — formats and posts PR review comments via GitHubAPIClient."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from pr_reviewer.logging import get_logger
from pr_reviewer.models.enums import Severity
from pr_reviewer.models.finding import Finding

if TYPE_CHECKING:
    from pr_reviewer.config.schema import Config

_logger = get_logger(__name__)

_SEVERITY_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


class CommentPoster:
    def __init__(self, github_client: Any) -> None:
        self._github_client = github_client

    def post(
        self,
        findings: list[Finding],
        repo: str,
        pr_number: int,
        config: Config,
    ) -> None:
        existing = self._github_client.get_existing_reviews(repo, pr_number)
        filtered = _filter_by_severity(findings, config.min_severity)
        filtered = _dedup(filtered, existing)

        event = _determine_review_status(filtered, config)
        body = _build_summary_body(filtered)
        comments = [_format_comment(f) for f in filtered]

        try:
            self._github_client.post_review(repo, pr_number, body, event, comments)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 422:
                _logger.warning("Batch review 422'd; falling back to per-comment posting")
                for comment in comments:
                    try:
                        self._github_client.post_review(
                            repo, pr_number, body, event, [comment]
                        )
                    except httpx.HTTPStatusError:
                        _logger.warning(
                            f"Skipping invalid comment on {comment.get('path')}"
                        )
            else:
                raise


def _filter_by_severity(findings: list[Finding], min_severity: str) -> list[Finding]:
    min_rank = _SEVERITY_RANK.get(min_severity, 0)
    return [f for f in findings if _SEVERITY_RANK.get(str(f.severity), 0) >= min_rank]


def _dedup(findings: list[Finding], existing_reviews: list[dict]) -> list[Finding]:
    existing: set[tuple[str, int]] = set()
    for review in existing_reviews:
        for comment in review.get("comments", []):
            existing.add((comment.get("path", ""), comment.get("line", -1)))
    return [f for f in findings if (f.file_path, f.line_number) not in existing]


def _format_comment(finding: Finding) -> dict:
    body = finding.explanation
    if finding.suggestion is not None:
        body += f"\n\n```suggestion\n{finding.suggestion}\n```"
    return {
        "path": finding.file_path,
        "line": finding.line_number,
        "body": body,
    }


def _determine_review_status(findings: list[Finding], config: Config) -> str:
    if not findings:
        return "APPROVE" if config.auto_approve_on_no_findings else "COMMENT"
    if any(str(f.severity) == str(Severity.high) and not f.is_escalation for f in findings):
        return "REQUEST_CHANGES"
    return "COMMENT"


def _build_summary_body(findings: list[Finding]) -> str:
    if not findings:
        return "No issues found."
    n = len(findings)
    categories = len({f.category for f in findings})
    return f"Found {n} issue(s) across {categories} category/categories."
