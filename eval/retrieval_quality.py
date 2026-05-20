"""Retrieval quality scoring for the v2 eval harness."""

from __future__ import annotations

from typing import Any, Callable


def score_retrieval_calls(
    trace: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    judge_fn: Callable[..., Any] | None = None,
) -> dict[str, float]:
    """Score each query_knowledge_base call in *trace* using *judge_fn*.

    Returns mean relevance score per corpus name.
    judge_fn signature: (finding, query, corpus) -> object with .score attribute.
    """
    if judge_fn is None:
        from eval.judges.relevance_judge import judge as judge_fn  # type: ignore[assignment]

    kb_calls = [t for t in trace if t.get("tool_name") == "query_knowledge_base"]

    # Representative finding text for context
    finding_text = findings[0].get("explanation", "") if findings else ""

    corpus_scores: dict[str, list[float]] = {}
    for call in kb_calls:
        corpus = call.get("corpus", "unknown")
        query = call.get("query", "")
        result = judge_fn(finding=finding_text, query=query, corpus=corpus)
        score = float(result.score)
        corpus_scores.setdefault(corpus, []).append(score)

    return {
        corpus: sum(scores) / len(scores)
        for corpus, scores in corpus_scores.items()
    }


def emit_retrieval_relevance_metric(
    scores: dict[str, float],
    record_fn: Callable[[str, float], None] | None = None,
) -> None:
    """Emit kb.retrieval_relevance OTel gauge per corpus.

    *record_fn* is injectable for testing; defaults to a real OTel gauge.
    """
    if record_fn is None:
        record_fn = _make_otel_record_fn()

    for corpus, value in scores.items():
        record_fn(corpus, value)


def _make_otel_record_fn() -> Callable[[str, float], None]:
    from opentelemetry import metrics

    meter = metrics.get_meter("eval")
    gauge = meter.create_gauge("kb.retrieval_relevance")

    def _record(corpus: str, value: float) -> None:
        gauge.set(value, {"corpus": corpus})

    return _record
