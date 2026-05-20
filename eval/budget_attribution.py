"""Tool budget attribution — separates KB calls from codebase calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_KB_TOOLS = frozenset({
    "query_knowledge_base",
    "lookup_cve",
    "check_package_advisory",
    "ghsa_lookup",
    "snyk_lookup",
    "owasp_check",
})

_CODEBASE_TOOLS = frozenset({
    "fetch_file_content",
    "search_file",
    "list_directory",
    "get_symbol_usages",
})


@dataclass(frozen=True)
class BudgetAttribution:
    kb_calls: int
    codebase_calls: int
    total: int


def attribute_budget(tool_calls: list[dict[str, Any]]) -> BudgetAttribution:
    """Partition *tool_calls* into KB vs codebase categories."""
    kb = sum(1 for t in tool_calls if t.get("tool_name") in _KB_TOOLS)
    codebase = sum(1 for t in tool_calls if t.get("tool_name") in _CODEBASE_TOOLS)
    return BudgetAttribution(kb_calls=kb, codebase_calls=codebase, total=len(tool_calls))
