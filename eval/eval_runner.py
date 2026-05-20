"""Eval runner — orchestrates judge calls for a single finding."""

from __future__ import annotations

from typing import Any, NamedTuple

from eval.judges.accuracy_judge import judge as accuracy_judge
from eval.judges.actionability_judge import judge as actionability_judge
from eval.judges.clarity_judge import judge as clarity_judge
from eval.judges.relevance_judge import judge as relevance_judge


class ScoreVector(NamedTuple):
    relevance: int
    accuracy: int
    actionability: int
    clarity: int


def evaluate_finding(
    finding: dict[str, Any],
    diff: str,
    label: str,
    model: str = "gpt-4o",
) -> ScoreVector:
    """Run all four dimension judges and return a ScoreVector."""
    finding_str = str(finding)
    return ScoreVector(
        relevance=relevance_judge(finding=finding_str, diff=diff, model=model).score,
        accuracy=accuracy_judge(finding=finding_str, diff=diff, label=label, model=model).score,
        actionability=actionability_judge(finding=finding_str, model=model).score,
        clarity=clarity_judge(finding=finding_str, model=model).score,
    )
