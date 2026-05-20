"""Accuracy judge — scores how accurate a finding's diagnosis is."""

from __future__ import annotations

from eval.judges._base import JudgeResult, call_judge

_MODEL = "gpt-4o"

_PROMPT_TMPL = """
You are a code review quality evaluator.

Rate the ACCURACY of the following finding on a scale of 0-10.
Respond with JSON: {{"score": <int>, "rationale": "<one sentence>"}}

Finding: {finding}
Diff excerpt: {diff}
Ground truth label: {label}
""".strip()


def judge(*, finding: str, diff: str, label: str = "", model: str = _MODEL) -> JudgeResult:
    prompt = _PROMPT_TMPL.format(finding=finding, diff=diff, label=label)
    return call_judge(model=model, prompt=prompt)


__all__ = ["JudgeResult", "judge"]
