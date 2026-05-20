"""ToolBudgetMiddleware — per-job tool call accounting."""

_EXEMPT_TOOLS = frozenset({"fetch_pr_metadata", "read_findings_so_far"})


class BudgetExhaustedError(Exception):
    """Raised when the tool budget is exceeded."""

    def __init__(self, message: str, path: str = "general") -> None:
        super().__init__(message)
        self.path = path


class ToolBudgetMiddleware:
    """Tracks non-exempt tool calls; raises BudgetExhaustedError at the limit."""

    def __init__(self, budget: int) -> None:
        self._budget = budget
        self._count = 0

    @property
    def calls_used(self) -> int:
        return self._count

    @property
    def budget(self) -> int:
        return self._budget

    def track(self, tool_name: str, priming: bool = False, path: str = "general") -> None:
        """Increment counter for non-exempt calls; raise when budget exceeded.

        Args:
            tool_name: Name of the tool being called.
            priming: When True and tool is ``query_knowledge_base``, the call is exempt.
            path: Passed through to ``BudgetExhaustedError`` so callers can tell
                  whether exhaustion happened on the security or general analysis path.
        """
        if tool_name in _EXEMPT_TOOLS:
            return
        if tool_name == "query_knowledge_base" and priming:
            return
        self._count += 1
        if self._count > self._budget:
            raise BudgetExhaustedError(
                f"Tool budget of {self._budget} exhausted on call {self._count}",
                path=path,
            )
