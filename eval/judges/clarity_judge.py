"""Clarity judge — scores how clearly the finding is communicated."""

from __future__ import annotations

from eval.judges._base import JudgeResult, call_judge

_MODEL = "gpt-4o"

_PROMPT_TMPL = """
You are a code review quality evaluator.

Rate the CLARITY of the following finding on a scale of 0-10.
Respond with JSON: {{"score": <int>, "rationale": "<one sentence>"}}

Finding: {finding}
""".strip()


def judge(*, finding: str, model: str = _MODEL) -> JudgeResult:
    prompt = _PROMPT_TMPL.format(finding=finding)
    return call_judge(model=model, prompt=prompt)


__all__ = ["JudgeResult", "judge"]
