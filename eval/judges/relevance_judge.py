"""Relevance judge — scores how relevant a finding is to the changed diff."""

from __future__ import annotations

from eval.judges._base import JudgeResult, call_judge

_MODEL = "gpt-4o"

_PROMPT_TMPL = """
You are a code review quality evaluator.

Rate the RELEVANCE of the following finding to the diff on a scale of 0-10.
Respond with JSON: {{"score": <int>, "rationale": "<one sentence>"}}

Finding: {finding}
Diff excerpt: {diff}
""".strip()


def judge(*, finding: str, diff: str, model: str = _MODEL) -> JudgeResult:
    prompt = _PROMPT_TMPL.format(finding=finding, diff=diff)
    return call_judge(model=model, prompt=prompt)


__all__ = ["JudgeResult", "judge"]
