"""Pre-ship eval task — fails if any security false positive is present."""

from __future__ import annotations

from typing import Any


class PreShipFailure(RuntimeError):
    pass


def run_pre_ship(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the pre-ship evaluation.

    Raises PreShipFailure if any security finding is labeled false_positive.
    """
    security_fps = [
        f for f in findings
        if f.get("category") == "security" and f.get("label") == "false_positive"
    ]
    if security_fps:
        raise PreShipFailure(
            f"Found {len(security_fps)} security false positive(s); pre-ship blocked"
        )
    return {"status": "pass", "total_findings": len(findings)}
