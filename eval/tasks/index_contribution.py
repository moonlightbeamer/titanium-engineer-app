"""Index contribution task — ablation toggling codebase_index_enabled."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IndexContributionReport:
    precision_delta: dict[str, float]
    recall_delta: dict[str, float]
    fp_delta: dict[str, int]


def compute_index_contribution(
    run_with_index: dict[str, Any],
    run_without_index: dict[str, Any],
) -> IndexContributionReport:
    """Compute precision/recall/FP delta between two runs (index on vs off)."""
    prec_with = run_with_index.get("precision_by_category", {})
    prec_without = run_without_index.get("precision_by_category", {})
    rec_with = run_with_index.get("recall_by_category", {})
    rec_without = run_without_index.get("recall_by_category", {})
    fp_with = run_with_index.get("fp_by_category", {})
    fp_without = run_without_index.get("fp_by_category", {})

    categories = set(prec_with) | set(prec_without)

    precision_delta = {
        cat: prec_with.get(cat, 0.0) - prec_without.get(cat, 0.0)
        for cat in categories
    }
    recall_delta = {
        cat: rec_with.get(cat, 0.0) - rec_without.get(cat, 0.0)
        for cat in categories
    }
    fp_delta = {
        cat: fp_with.get(cat, 0) - fp_without.get(cat, 0)
        for cat in categories
    }

    return IndexContributionReport(
        precision_delta=precision_delta,
        recall_delta=recall_delta,
        fp_delta=fp_delta,
    )


def run_index_contribution(corpus: list[dict[str, Any]], eval_runner_fn: Any) -> IndexContributionReport:
    """Run corpus twice — once with codebase_index_enabled=True, once False."""
    run_with = eval_runner_fn(corpus, codebase_index_enabled=True)
    run_without = eval_runner_fn(corpus, codebase_index_enabled=False)
    return compute_index_contribution(run_with, run_without)
