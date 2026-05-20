"""Shared types and helper for all judge implementations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JudgeResult:
    score: int
    rationale: str
    model_used: str


def call_judge(
    model: str,
    prompt: str,
) -> JudgeResult:
    """Call LiteLLM with *prompt* and parse a JSON {score, rationale} response."""
    import litellm

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.choices[0].message.content
    try:
        data = json.loads(raw)
        score = int(data.get("score", 0))
        rationale = str(data.get("rationale", ""))
    except (json.JSONDecodeError, ValueError):
        score = 0
        rationale = raw or ""

    return JudgeResult(score=max(0, min(10, score)), rationale=rationale, model_used=model)
