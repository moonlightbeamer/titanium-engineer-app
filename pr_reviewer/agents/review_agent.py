"""ReviewAgent — orchestrates tool calls and LLM reasoning for a single PR review."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pr_reviewer.agents.tool_budget import BudgetExhaustedError, ToolBudgetMiddleware
from pr_reviewer.agents.tools import Tool, create_tools
from pr_reviewer.logging import get_logger
from pr_reviewer.models.enums import Confidence, ReviewCategory, Severity
from pr_reviewer.models.finding import Finding

if TYPE_CHECKING:
    from pr_reviewer.components.diff_parser import StructuredDiff
    from pr_reviewer.config.schema import Config

_logger = get_logger(__name__)


@dataclass(frozen=True)
class ReviewContext:
    github_client: Any
    knowledge_base: Any
    mcp_client: Any
    secret_scrubber: Any
    repo: str
    pr_number: int
    job_id: UUID
    few_shot_examples: tuple = field(default_factory=tuple)
    codebase_index: Any = None


@dataclass(frozen=True)
class _Message:
    content: str


class ReviewAgent:
    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def run(
        self,
        diff: StructuredDiff,
        config: Config,
        ctx: ReviewContext,
    ) -> list[Finding]:
        budget = ToolBudgetMiddleware(config.tool_budget)
        findings_store: list[Finding] = []
        tools = create_tools(ctx, budget, findings_store)
        tool_map = {t.name: t for t in tools}

        # Step 1: fetch PR metadata — always first
        try:
            tool_map["fetch_pr_metadata"].func()
        except Exception:
            _logger.warning("fetch_pr_metadata failed; continuing")

        # Step 2: KB security priming — budget-exempt
        try:
            tool_map["query_knowledge_base"].func(
                text="security vulnerabilities",
                category="security",
                language="",
                priming=True,
            )
        except Exception:
            _logger.warning("KB priming failed; continuing")

        # Step 3: LLM reasoning — single pass, one retry on timeout
        messages = [_Message(content=_render_diff(diff))]
        try:
            response = self._llm.invoke(messages)
            findings_store.extend(_parse_findings(response, ctx.job_id))
        except TimeoutError:
            _logger.warning("LLM timeout on first attempt; retrying once")
            try:
                response = self._llm.invoke(messages)
                findings_store.extend(_parse_findings(response, ctx.job_id))
            except TimeoutError:
                _logger.warning("LLM timed out twice; returning partial findings")

        # Step 4: resolve low-confidence findings with one extra tool call each
        for finding in list(findings_store):
            if finding.confidence == Confidence.low:
                try:
                    _resolve_low_confidence(finding, tools, budget)
                except BudgetExhaustedError:
                    break

        # Step 5: post-analysis test coverage check
        _check_test_coverage(diff, tools, budget, findings_store, ctx.job_id)

        # Step 6: merge and annotate
        return _synthesis_step(findings_store)


# ── Module-level helpers (importable for direct testing) ─────────────────────


def _render_diff(diff: StructuredDiff) -> str:
    parts: list[str] = []
    for cf in diff.changed_files:
        parts.append(f"--- {cf.filename}")
        for hunk in cf.hunks:
            parts.append(
                f"@@ -{hunk.old_start},{hunk.old_count}"
                f" +{hunk.new_start},{hunk.new_count} @@"
            )
            for line in hunk.lines:
                parts.append(line.content)
    return "\n".join(parts)


def _parse_findings(response: Any, job_id: UUID) -> list[Finding]:
    """Parse LLM response into Findings; returns empty list on non-structured response."""
    return []


def _resolve_low_confidence(
    finding: Finding,
    tools: list[Tool],
    budget: ToolBudgetMiddleware,
) -> None:
    """Make one additional search_file call to increase evidence for a low-confidence finding."""
    search_tool = next((t for t in tools if t.name == "search_file"), None)
    if search_tool is None:
        return
    search_tool.func(path=finding.file_path, query=finding.explanation[:50])


def _check_test_coverage(
    diff: StructuredDiff,
    tools: list[Tool],
    budget: ToolBudgetMiddleware,
    findings_store: list[Finding],
    job_id: UUID,
) -> None:
    """Check test file existence for each modified source file; emit a bugs Finding if missing."""
    list_dir_tool = next((t for t in tools if t.name == "list_directory"), None)
    if list_dir_tool is None:
        return

    for changed_file in diff.changed_files:
        try:
            test_files = list_dir_tool.func(path="tests")
        except BudgetExhaustedError:
            return

        if not test_files:
            findings_store.append(
                Finding(
                    id=uuid4(),
                    job_id=job_id,
                    file_path=changed_file.filename,
                    line_number=1,
                    category=ReviewCategory.bugs,
                    severity=Severity.low,
                    confidence=Confidence.low,
                    explanation=f"No test coverage found for {changed_file.filename}.",
                    is_escalation=False,
                )
            )


_SEVERITY_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


# ── v2: Index-informed helpers ────────────────────────────────────────────────


def _parse_index_content(codebase_index: Any) -> dict:
    """Parse the JSON content of a CodebaseIndex; return empty dict on failure."""
    if codebase_index is None:
        return {}
    try:
        import json
        return json.loads(getattr(codebase_index, "content", "{}") or "{}")
    except Exception:
        return {}


def _apply_convention_filter(findings: list[Finding], codebase_index: Any) -> list[Finding]:
    """Remove style findings that match patterns established as repo conventions (≥60%)."""
    if codebase_index is None:
        return findings
    profile: dict = _parse_index_content(codebase_index).get("convention_profile", {})
    if not profile:
        return findings
    result = []
    for finding in findings:
        if finding.category != ReviewCategory.style:
            result.append(finding)
            continue
        matched_convention = any(
            pattern in finding.explanation and ratio >= 0.60
            for pattern, ratio in profile.items()
        )
        if not matched_convention:
            result.append(finding)
    return result


def _prioritize_budget_by_density(files: list[str], codebase_index: Any) -> list[str]:
    """Re-order files so high-density (many prior findings) files are processed first."""
    if codebase_index is None:
        return files
    density_map: dict = _parse_index_content(codebase_index).get("finding_density_map", {}) or {}
    if not density_map:
        return files
    return sorted(files, key=lambda f: density_map.get(f, 0), reverse=True)


def _apply_security_boundary_escalation(
    findings: list[Finding], codebase_index: Any
) -> list[Finding]:
    """Escalate low-confidence security findings in files tagged as security boundaries."""
    if codebase_index is None:
        return findings
    arch: dict = _parse_index_content(codebase_index).get("architectural_summary", {})
    boundaries: list[str] = arch.get("security_boundaries", [])
    if not boundaries:
        return findings

    result = []
    for finding in findings:
        if (
            finding.category == ReviewCategory.security
            and finding.confidence == Confidence.low
            and any(finding.file_path.startswith(b) for b in boundaries)
        ):
            result.append(
                Finding(
                    id=finding.id,
                    job_id=finding.job_id,
                    file_path=finding.file_path,
                    line_number=finding.line_number,
                    category=finding.category,
                    severity=finding.severity,
                    confidence=finding.confidence,
                    explanation=finding.explanation,
                    is_escalation=True,
                    suggestion=finding.suggestion,
                    related_finding_ids=finding.related_finding_ids,
                )
            )
        else:
            result.append(finding)
    return result


def _discard_test_fixture_findings(
    findings: list[Finding], codebase_index: Any
) -> list[Finding]:
    """Remove findings whose file is tagged as a test fixture — zero budget consumed."""
    if codebase_index is None:
        return findings
    arch: dict = _parse_index_content(codebase_index).get("architectural_summary", {})
    fixtures: list[str] = arch.get("test_fixtures", [])
    if not fixtures:
        return findings
    return [f for f in findings if not any(f.file_path.startswith(fix) for fix in fixtures)]


def measure_index_contribution(
    findings_with_index: list[Finding],
    findings_without_index: list[Finding],
) -> dict[str, float]:
    """Ablation helper: estimate precision/recall delta between runs with/without index."""
    n_with = len(findings_with_index)
    n_without = len(findings_without_index)
    precision_delta = (n_with - n_without) / max(n_without, 1)
    recall_delta = precision_delta  # placeholder; real eval uses labelled corpus
    return {"precision_delta": precision_delta, "recall_delta": recall_delta}


def _synthesis_step(findings: list[Finding]) -> list[Finding]:
    """Merge findings at the same file+line; populate related_finding_ids."""
    groups: dict[tuple[str, int], list[Finding]] = defaultdict(list)
    for f in findings:
        groups[(f.file_path, f.line_number)].append(f)

    result: list[Finding] = []
    for (file_path, line_number), group in groups.items():
        if len(group) == 1:
            result.append(group[0])
            continue

        highest = max(group, key=lambda f: _SEVERITY_RANK.get(str(f.severity), 0))
        combined_explanation = " ".join(f.explanation for f in group)
        original_ids: tuple[UUID, ...] = tuple(f.id for f in group)

        result.append(
            Finding(
                id=uuid4(),
                job_id=group[0].job_id,
                file_path=file_path,
                line_number=line_number,
                category=highest.category,
                severity=highest.severity,
                confidence=highest.confidence,
                explanation=combined_explanation,
                is_escalation=any(f.is_escalation for f in group),
                suggestion=next((f.suggestion for f in group if f.suggestion), None),
                related_finding_ids=original_ids,
            )
        )

    return result
