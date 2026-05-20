"""Corpus loading and validation for the eval harness.

Standalone module — reads findings directly from the DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class CorpusValidationError(ValueError):
    pass


@dataclass(frozen=True)
class EvalSample:
    id: str
    category: str  # "bugs" | "security" | "style" | "performance" | "safe"
    diff: str
    label: str = ""


def load_corpus(
    *,
    samples: list[dict[str, Any]] | None = None,
    min_prs: int = 20,
    min_safe: int = 10,
    min_security: int = 5,
) -> list[EvalSample]:
    """Load and validate the eval corpus.

    When *samples* is provided (tests), validate that list directly.
    In production, samples would be fetched from the findings table.
    """
    if samples is None:
        samples = _fetch_from_db()

    if len(samples) < min_prs:
        raise CorpusValidationError(
            f"corpus requires ≥{min_prs} PRs; got {len(samples)}"
        )

    safe_count = sum(1 for s in samples if s.get("category") == "safe")
    if safe_count < min_safe:
        raise CorpusValidationError(
            f"corpus requires ≥{min_safe} safe (no-security) PRs; got {safe_count}"
        )

    security_count = sum(1 for s in samples if s.get("category") == "security")
    if security_count < min_security:
        raise CorpusValidationError(
            f"corpus requires ≥{min_security} security PRs; got {security_count}"
        )

    return [
        EvalSample(
            id=s["id"],
            category=s["category"],
            diff=s.get("diff", ""),
            label=s.get("label", s["category"]),
        )
        for s in samples
    ]


def _fetch_from_db() -> list[dict[str, Any]]:
    """Fetch labeled findings from the database."""
    from eval.db import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            "SELECT id, category, label FROM findings WHERE label IS NOT NULL"
        ).fetchall()
    return [{"id": str(r[0]), "category": r[1], "label": r[2], "diff": ""} for r in rows]
