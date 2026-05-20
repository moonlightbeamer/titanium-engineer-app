"""Ablation task — runs corpus twice (KB on/off) and reports delta per category."""

from __future__ import annotations

from typing import Any

_CATEGORIES = ("bugs", "security", "style", "performance")


def compute_ablation_delta(
    run_with_kb: dict[str, Any],
    run_without_kb: dict[str, Any],
) -> dict[str, Any]:
    """Compute precision delta between *run_with_kb* and *run_without_kb*.

    Returns a dict with ``delta_precision`` (per category) and
    ``delta_recall`` (per category).
    """
    prec_with = run_with_kb.get("precision_by_category", {})
    prec_without = run_without_kb.get("precision_by_category", {})
    rec_with = run_with_kb.get("recall_by_category", {})
    rec_without = run_without_kb.get("recall_by_category", {})

    categories = set(prec_with) | set(prec_without) | set(_CATEGORIES)

    delta_precision = {
        cat: prec_with.get(cat, 0.0) - prec_without.get(cat, 0.0)
        for cat in categories
    }
    delta_recall = {
        cat: rec_with.get(cat, 0.0) - rec_without.get(cat, 0.0)
        for cat in categories
    }

    return {"delta_precision": delta_precision, "delta_recall": delta_recall}


def run_ablation(corpus: list[dict[str, Any]], eval_runner_fn: Any) -> dict[str, Any]:
    """Run the corpus twice — once with KB enabled, once without.

    *eval_runner_fn(corpus, kb_enabled)* must return an EvalReport-like dict.
    Returns the delta report.
    """
    run_with = eval_runner_fn(corpus, kb_enabled=True)
    run_without = eval_runner_fn(corpus, kb_enabled=False)
    return compute_ablation_delta(run_with, run_without)
