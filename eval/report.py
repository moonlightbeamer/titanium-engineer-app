"""Eval report generation — computes metrics and persists to eval_runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

_CATEGORIES = ("bugs", "security", "style", "performance")
_DIMENSIONS = ("relevance", "accuracy", "actionability", "clarity")


@dataclass(frozen=True)
class EvalReport:
    run_id: UUID
    run_type: str
    precision_by_category: dict[str, float]
    recall_by_category: dict[str, float]
    fp_by_category: dict[str, int]
    mean_scores: dict[str, float]
    avg_cost_usd: float
    avg_latency_ms: float
    delta: dict[str, Any] | None
    feedback_signals_per_category: dict[str, Any] | None
    kb_quality: dict[str, Any] | None
    corpus_version: str = "unknown"


def generate_report(
    *,
    run_id: UUID,
    run_type: str,
    findings: list[dict[str, Any]],
    judge_scores: dict[str, list[float]] | None = None,
    previous_report: dict[str, Any] | None = None,
    feedback_signals: dict[str, Any] | None = None,
    avg_cost_usd: float = 0.0,
    avg_latency_ms: float = 0.0,
    corpus_version: str = "unknown",
) -> EvalReport:
    precision = _compute_precision(findings)
    recall = _compute_recall(findings)
    fp = _compute_fp_count(findings)
    mean_scores = _compute_mean_scores(judge_scores)
    delta = _compute_delta(precision, recall, previous_report) if previous_report else None
    kb_quality = _compute_kb_quality(findings)

    return EvalReport(
        run_id=run_id,
        run_type=run_type,
        precision_by_category=precision,
        recall_by_category=recall,
        fp_by_category=fp,
        mean_scores=mean_scores,
        avg_cost_usd=avg_cost_usd,
        avg_latency_ms=avg_latency_ms,
        delta=delta,
        feedback_signals_per_category=feedback_signals,
        kb_quality=kb_quality,
        corpus_version=corpus_version,
    )


def _compute_precision(findings: list[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for cat in _CATEGORIES:
        cat_findings = [f for f in findings if f.get("category") == cat]
        if not cat_findings:
            result[cat] = 0.0
            continue
        tp = sum(1 for f in cat_findings if f.get("label") == "true_positive")
        result[cat] = tp / len(cat_findings)
    return result


def _compute_recall(findings: list[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for cat in _CATEGORIES:
        cat_findings = [f for f in findings if f.get("category") == cat]
        tp = sum(1 for f in cat_findings if f.get("label") == "true_positive")
        # Without ground truth total, recall = tp / (tp + fn); use tp / cat_count as proxy
        total = len(cat_findings) if cat_findings else 1
        result[cat] = tp / total
    return result


def _compute_fp_count(findings: list[dict[str, Any]]) -> dict[str, int]:
    return {
        cat: sum(
            1 for f in findings
            if f.get("category") == cat and f.get("label") == "false_positive"
        )
        for cat in _CATEGORIES
    }


def _compute_mean_scores(
    judge_scores: dict[str, list[float]] | None,
) -> dict[str, float]:
    if not judge_scores:
        return {dim: 0.0 for dim in _DIMENSIONS}
    return {
        dim: (sum(judge_scores[dim]) / len(judge_scores[dim]) if judge_scores.get(dim) else 0.0)
        for dim in _DIMENSIONS
    }


def _compute_delta(
    precision: dict[str, float],
    recall: dict[str, float],
    previous: dict[str, Any],
) -> dict[str, Any]:
    prev_prec = previous.get("precision_by_category", {})
    prev_rec = previous.get("recall_by_category", {})
    delta: dict[str, Any] = {}
    for cat in _CATEGORIES:
        delta[cat] = {
            "precision_delta": precision.get(cat, 0.0) - prev_prec.get(cat, 0.0),
            "recall_delta": recall.get(cat, 0.0) - prev_rec.get(cat, 0.0),
        }
    return delta


def _compute_kb_quality(findings: list[dict[str, Any]]) -> dict[str, Any]:
    no_retrieval = [
        f.get("id", "?")
        for f in findings
        if f.get("category") == "security"
        and f.get("kb_entries_retrieved", 1) == 0
    ]
    return {"no_retrieval_findings": no_retrieval}
