"""Bias detection — checks for same-family model bias in judge scores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eval.judges._base import JudgeResult, call_judge

_MODELS = ["gpt-4o", "claude-3-sonnet-20240229"]


@dataclass(frozen=True)
class BiasResult:
    scores: tuple[JudgeResult, ...]
    models_used: tuple[str, ...]
    max_delta: float


def detect_same_family_bias(
    finding: dict[str, Any] | str,
    diff: str,
    models: list[str] | None = None,
) -> BiasResult:
    """Run the relevance judge with multiple model families and compare scores."""
    from eval.judges.relevance_judge import _PROMPT_TMPL

    models_to_use = models or _MODELS
    finding_str = str(finding)
    prompt = _PROMPT_TMPL.format(finding=finding_str, diff=diff)

    results: list[JudgeResult] = [
        call_judge(model=m, prompt=prompt) for m in models_to_use
    ]

    scores = [r.score for r in results]
    max_delta = float(max(scores) - min(scores)) if len(scores) > 1 else 0.0

    return BiasResult(
        scores=tuple(results),
        models_used=tuple(models_to_use),
        max_delta=max_delta,
    )
