"""Weekly vibe-check eval task — samples stored findings for human review."""

from __future__ import annotations

import random
from typing import Any


def sample_findings(
    findings: list[dict[str, Any]],
    n: int = 10,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Sample *n* findings from *findings* for human vibe scoring.

    Reads from pre-loaded findings (stored in the findings table), not raw diffs.
    """
    if len(findings) <= n:
        return list(findings)
    rng = random.Random(seed)
    return rng.sample(findings, n)
