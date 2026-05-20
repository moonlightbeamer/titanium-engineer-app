"""Corpus health monitoring — flags corpora with sustained low retrieval relevance."""

from __future__ import annotations

from typing import Callable


class CorpusHealthMonitor:
    """Rolling-window monitor that flags a corpus when relevance stays below *threshold*.

    *on_flag* is called with the corpus name the first time a flag triggers.
    """

    def __init__(
        self,
        *,
        threshold: float = 0.6,
        window: int = 3,
        on_flag: Callable[[str], None] | None = None,
    ) -> None:
        self._threshold = threshold
        self._window = window
        self._on_flag = on_flag
        self._history: dict[str, list[float]] = {}

    def record_run(self, corpus: str, mean_relevance: float) -> bool:
        """Record one eval run's mean relevance for *corpus*.

        Returns True if the corpus is now flagged (i.e., *window* consecutive
        runs all fell below *threshold*).
        """
        history = list(self._history.get(corpus, []))
        history.append(mean_relevance)
        # Keep only the last *window* entries
        history = history[-self._window :]
        self._history = {**self._history, corpus: history}

        flagged = (
            len(history) >= self._window
            and all(s < self._threshold for s in history)
        )
        if flagged and self._on_flag is not None:
            self._on_flag(corpus)
        return flagged
