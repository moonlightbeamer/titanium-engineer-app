"""Quality-with-CoT judge — holistic score using chain-of-thought reasoning."""

from __future__ import annotations

from typing import Any

from eval.judges._base import JudgeResult, call_judge

_MODEL = "gpt-4o"

_PROMPT_TMPL = """
You are a senior engineer evaluating code review quality.

Think step by step (chain of thought), then rate the overall quality of this finding
on a scale of 0-10.
Respond with JSON: {{"score": <int>, "rationale": "<two to three sentences of reasoning>"}}

Finding: {finding}
Diff: {diff}
""".strip()


def judge(
    *,
    finding: dict[str, Any] | str,
    diff: str = "",
    model: str = _MODEL,
) -> JudgeResult:
    prompt = _PROMPT_TMPL.format(finding=str(finding), diff=diff)
    return call_judge(model=model, prompt=prompt)


__all__ = ["JudgeResult", "judge"]
