"""Verification trace judge — scores whether the agent used the right tools."""

from __future__ import annotations

from typing import Any

from eval.judges._base import JudgeResult, call_judge

_MODEL = "gpt-4o"

_PROMPT_TMPL = """
You are a code review quality evaluator.

The following security finding was produced after these tool calls: {tool_calls}

Rate whether the agent used an appropriate verification trace on a scale of 0-10.
A score of 10 means the agent correctly looked up CVEs, checked the KB, etc.
Respond with JSON: {{"score": <int>, "rationale": "<one sentence>"}}

Finding: {finding}
""".strip()


def judge(
    *,
    finding: dict[str, Any] | str,
    tool_calls: list[str],
    model: str = _MODEL,
) -> JudgeResult:
    finding_str = str(finding)
    tool_calls_str = ", ".join(tool_calls)
    prompt = _PROMPT_TMPL.format(tool_calls=tool_calls_str, finding=finding_str)
    return call_judge(model=model, prompt=prompt)


__all__ = ["JudgeResult", "judge"]
