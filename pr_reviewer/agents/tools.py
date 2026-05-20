"""Agent tools — one callable per named function; wired to ReviewContext services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pr_reviewer.agents.tool_budget import ToolBudgetMiddleware
from pr_reviewer.models.finding import Finding

if TYPE_CHECKING:
    from pr_reviewer.agents.review_agent import ReviewContext

ALL_TOOL_NAMES: list[str] = [
    "fetch_pr_metadata",
    "read_findings_so_far",
    "query_knowledge_base",
    "fetch_file_content",
    "search_file",
    "list_directory",
    "get_symbol_usages",
    "lookup_cve",
    "check_package_advisory",
]


@dataclass(frozen=True)
class Tool:
    name: str
    func: Callable


def create_tools(
    ctx: ReviewContext,
    budget: ToolBudgetMiddleware,
    findings_store: list[Finding],
) -> list[Tool]:
    """Build the full v1 tool list wired to ctx services and the shared budget."""

    def fetch_pr_metadata(**kwargs: Any) -> Any:
        budget.track("fetch_pr_metadata")
        return ctx.github_client.get_pr_metadata(**kwargs)

    def read_findings_so_far(**kwargs: Any) -> list[Finding]:
        budget.track("read_findings_so_far")
        return list(findings_store)

    def query_knowledge_base(
        text: str = "",
        category: str = "general",
        language: str = "",
        priming: bool = False,
        **kwargs: Any,
    ) -> Any:
        budget.track("query_knowledge_base", priming=priming)
        return ctx.knowledge_base.query(
            text=text,
            category=category,
            language=language,
            priming=priming,
            **kwargs,
        )

    def fetch_file_content(path: str, ref: str = "HEAD", **kwargs: Any) -> str:
        budget.track("fetch_file_content", path="general")
        raw = ctx.github_client.get_file_content(path=path, ref=ref, **kwargs)
        scrubbed, _ = ctx.secret_scrubber.scrub(raw, source="diff")
        return scrubbed

    def search_file(path: str = "", query: str = "", **kwargs: Any) -> Any:
        budget.track("search_file")
        return ctx.github_client.search_file(path=path, query=query, **kwargs)

    def list_directory(path: str = "", **kwargs: Any) -> Any:
        budget.track("list_directory")
        return ctx.github_client.list_directory(path=path, **kwargs)

    def get_symbol_usages(symbol: str = "", **kwargs: Any) -> Any:
        budget.track("get_symbol_usages")
        return ctx.github_client.get_symbol_usages(symbol=symbol, **kwargs)

    def lookup_cve(cve_id: str = "", **kwargs: Any) -> Any:
        budget.track("lookup_cve")
        return ctx.mcp_client.lookup_cve(cve_id=cve_id)

    def check_package_advisory(package: str = "", **kwargs: Any) -> Any:
        budget.track("check_package_advisory")
        return ctx.mcp_client.check_package_advisory(package=package)

    return [
        Tool(name="fetch_pr_metadata", func=fetch_pr_metadata),
        Tool(name="read_findings_so_far", func=read_findings_so_far),
        Tool(name="query_knowledge_base", func=query_knowledge_base),
        Tool(name="fetch_file_content", func=fetch_file_content),
        Tool(name="search_file", func=search_file),
        Tool(name="list_directory", func=list_directory),
        Tool(name="get_symbol_usages", func=get_symbol_usages),
        Tool(name="lookup_cve", func=lookup_cve),
        Tool(name="check_package_advisory", func=check_package_advisory),
    ]
