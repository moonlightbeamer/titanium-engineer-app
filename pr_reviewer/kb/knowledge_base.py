"""KnowledgeBase — ChromaDB-backed retrieval for review context."""

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from opentelemetry import metrics

from pr_reviewer.logging import get_logger
from pr_reviewer.telemetry import METRIC_KB_RETRIEVAL_LATENCY, METRIC_KB_RETRIEVAL_RELEVANCE

if TYPE_CHECKING:
    from pr_reviewer.config.schema import Config

_logger = get_logger(__name__)
_meter = metrics.get_meter(__name__)
_retrieval_latency = _meter.create_histogram(METRIC_KB_RETRIEVAL_LATENCY)
_retrieval_relevance = _meter.create_histogram(METRIC_KB_RETRIEVAL_RELEVANCE)

TOP_K = 5
MIN_CVE_ENTRIES = 5
STALENESS_DAYS = 14

COLLECTIONS = [
    "org_guidelines",
    "language_best_practices",
    "cve_snapshot",
    "fix_knowledge_base",
    "lessons_learned",
    "cross_repo_fixes",
]

# Config attribute name per corpus (matches KnowledgeBaseConfig fields)
_CORPUS_CONFIG_ATTR: dict[str, str] = {
    "cve_snapshot": "cve_snapshot",
    "language_best_practices": "language_best_practices",
}


@dataclass(frozen=True)
class KBEntry:
    id: str
    content: str
    corpus: str
    language_tag: str | None
    category: str | None
    score: float
    model_version: str
    source: str = "corpus"


class KnowledgeBase:
    def __init__(
        self,
        chroma_client: Any,
        config: "Config",
        last_refresh_dates: dict[str, datetime] | None = None,
    ) -> None:
        self._client = chroma_client
        self._config = config
        self._last_refresh = last_refresh_dates or {}
        self._collections: dict[str, Any] = {
            name: chroma_client.get_or_create_collection(name) for name in COLLECTIONS
        }

    def _corpus_enabled(self, corpus: str) -> bool:
        attr = _CORPUS_CONFIG_ATTR.get(corpus)
        if attr is not None:
            return bool(getattr(self._config.knowledge_base, attr, True))
        return True

    def _validate_model_versions(self) -> bool:
        versions: set[str] = set()
        for name, col in self._collections.items():
            if not self._corpus_enabled(name):
                continue
            result = col.get()
            for meta in result.get("metadatas", []):
                if meta and "model_version" in meta:
                    versions.add(meta["model_version"])

        if len(versions) > 1:
            _logger.error(
                f"Embedding model version mismatch detected: {versions}. "
                "Refusing to serve retrievals. Run kb reembed --corpus all."
            )
            return False
        return True

    def _check_cve_staleness(self) -> None:
        if not self._corpus_enabled("cve_snapshot"):
            return
        last = self._last_refresh.get("cve_snapshot")
        if last is None:
            return
        age_days = (datetime.now(tz=UTC) - last).days
        if age_days > STALENESS_DAYS:
            _logger.warning(
                f"CVE snapshot stale: last refresh was {age_days} days ago"
                f" (threshold: {STALENESS_DAYS} days)"
            )

    def _check_cve_minimum(self) -> bool:
        if not self._corpus_enabled("cve_snapshot"):
            return True
        count = self._collections["cve_snapshot"].count()
        if count < MIN_CVE_ENTRIES:
            _logger.warning(
                f"Insufficient corpus: cve_snapshot has {count} entries"
                f" (minimum: {MIN_CVE_ENTRIES})"
            )
            return False
        return True

    def _language_weight(self, corpus: str, language: str) -> float:
        if corpus != "language_best_practices":
            return 1.0
        weights = self._config.knowledge_base.language_corpus_weights
        return weights.get(language, 1.0)

    def query(
        self,
        query: str,
        category: str,
        language: str,
        priming: bool = False,
    ) -> list[KBEntry]:
        start = time.monotonic()

        if not self._validate_model_versions():
            return []

        self._check_cve_staleness()

        if not self._check_cve_minimum():
            return []

        all_entries: list[KBEntry] = []

        for corpus, col in self._collections.items():
            if not self._corpus_enabled(corpus):
                continue

            result = col.query(
                query_texts=[query],
                n_results=TOP_K,
                where={"category": category} if category else None,
            )

            ids = result["ids"][0] if result["ids"] else []
            docs = result["documents"][0] if result["documents"] else []
            metas = result["metadatas"][0] if result["metadatas"] else []
            distances = result["distances"][0] if result["distances"] else []

            for id_, doc, meta, dist in zip(ids, docs, metas, distances, strict=False):
                raw_score = 1.0 - dist / 2.0
                weight = self._language_weight(corpus, meta.get("language", ""))
                weighted_score = raw_score * weight

                all_entries.append(
                    KBEntry(
                        id=id_,
                        content=doc,
                        corpus=corpus,
                        language_tag=meta.get("language"),
                        category=meta.get("category"),
                        score=weighted_score,
                        model_version=meta.get("model_version", ""),
                    )
                )

        all_entries.sort(key=lambda e: e.score, reverse=True)
        top = all_entries[:TOP_K]

        elapsed_ms = (time.monotonic() - start) * 1000
        _retrieval_latency.record(elapsed_ms, {"category": category, "language": language})

        return top

    def validate_model_versions(self) -> bool:
        return self._validate_model_versions()


# ── Module-level helpers ──────────────────────────────────────────────────────

_WEIGHTED_CORPORA = frozenset({"language_best_practices", "cross_repo_fixes"})


def _apply_language_weight(
    entries: list[KBEntry],
    language_corpus_weights: dict[str, float],
    weighted_corpora: frozenset[str] | None = None,
) -> list[KBEntry]:
    """Return a new list with scores boosted by per-language weights for eligible corpora."""
    if weighted_corpora is None:
        weighted_corpora = _WEIGHTED_CORPORA
    result: list[KBEntry] = []
    for entry in entries:
        if entry.corpus in weighted_corpora:
            lang = entry.language_tag or ""
            weight = language_corpus_weights.get(lang, 1.0)
            result.append(KBEntry(
                id=entry.id,
                content=entry.content,
                corpus=entry.corpus,
                language_tag=entry.language_tag,
                category=entry.category,
                score=entry.score * weight,
                model_version=entry.model_version,
                source=entry.source,
            ))
        else:
            result.append(entry)
    result.sort(key=lambda e: e.score, reverse=True)
    return result
