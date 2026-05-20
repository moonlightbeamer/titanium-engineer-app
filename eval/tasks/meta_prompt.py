"""Meta-prompt reflector — proposes an improved prompt without applying it."""

from __future__ import annotations

import json
from typing import Any


def run_meta_prompt(
    findings: list[dict[str, Any]],
    model: str = "gpt-4o",
) -> dict[str, Any]:
    """Select the lowest-scored findings, generate a revised prompt, report delta.

    The revised prompt is NEVER applied automatically.
    """
    import litellm

    finding_texts = "\n".join(
        f"- [{f.get('category', '?')}] {f.get('explanation', '')}"
        for f in findings[:5]
    )
    prompt = (
        "You are a meta-prompt engineer. Given the following low-quality findings, "
        "propose an improved system prompt and estimate the quality score delta.\n\n"
        f"Findings:\n{finding_texts}\n\n"
        'Respond with JSON: {"revised_prompt": "<text>", "delta": <float>}'
    )

    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.choices[0].message.content
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"revised_prompt": raw, "delta": 0.0}

    return {
        "revised_prompt": data.get("revised_prompt", ""),
        "delta": data.get("delta", 0.0),
        "applied": False,
    }
