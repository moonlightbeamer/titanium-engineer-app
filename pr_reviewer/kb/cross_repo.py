"""Cross-repository fix corpus — learn from positive feedback signals across repos."""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Any

from pr_reviewer.logging import get_logger

if TYPE_CHECKING:
    from pr_reviewer.config.schema import Config

_logger = get_logger(__name__)

# A line is "code-like" if it matches any of these patterns
_CODE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bdef \b|\bclass \b|\bimport \b|\bfrom \b"),        # Python keywords
    re.compile(r"\bfunction \b|\bconst \b|\blet \b|\bvar \b|=>"),    # JS/TS
    re.compile(r"\{|\}|;"),                                           # Braces/semicolons
    re.compile(r"<[A-Za-z].*>"),                                      # Generics/HTML
]

_MAX_RETAINED_VERSIONS = 5


def _count_code_lines(content: str) -> int:
    count = 0
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and any(p.search(stripped) for p in _CODE_PATTERNS):
            count += 1
    return count


class CrossRepoLearning:
    def __init__(
        self,
        chromadb_client: Any,
        config: "Config",
        secret_scrubber: Any,
    ) -> None:
        self._client = chromadb_client
        self._config = config
        self._scrubber = secret_scrubber

    def _get_collection(self) -> Any:
        return self._client.get_or_create_collection("cross_repo_fixes")

    def _check_code_concreteness(self, content: str) -> None:
        """Raise ValueError if content has more than 3 code-like lines."""
        count = _count_code_lines(content)
        if count > 3:
            raise ValueError(
                f"abstract description required: content has {count} code-like lines (max 3)"
            )

    def add_cross_repo_fix(
        self,
        signal: Any,
        content: str,
        finding_category: str,
        language: str,
        vulnerability_type: str,
        installation_id: int = 0,
    ) -> None:
        """Scrub, validate, and persist a cross-repo fix to the ChromaDB collection."""
        # 1. Scrub secrets
        scrubbed, _ = self._scrubber.scrub(content)

        # 2. Validate code concreteness
        self._check_code_concreteness(scrubbed)

        # 3. Embed and store
        collection = self._get_collection()
        entry_id = str(uuid.uuid4())

        collection.add(
            ids=[entry_id],
            documents=[scrubbed],
            metadatas=[{
                "language": language,
                "category": finding_category,
                "vulnerability_type": vulnerability_type,
                "installation_id": installation_id,
                "repo_id": getattr(signal, "repo_id", "unknown"),
                "version": self._next_version(collection),
                "is_active": True,
            }],
        )

        # 4. Prune old versions
        self._prune_old_versions(collection, max_versions=_MAX_RETAINED_VERSIONS)

    def _next_version(self, collection: Any) -> int:
        result = collection.get()
        metadatas = result.get("metadatas") or []
        versions = [m.get("version", 0) for m in metadatas if m]
        return (max(versions) + 1) if versions else 1

    def _prune_old_versions(self, collection: Any, max_versions: int = _MAX_RETAINED_VERSIONS) -> None:
        """Deactivate entries beyond the newest max_versions versions."""
        result = collection.get()
        ids = result.get("ids") or []
        metadatas = result.get("metadatas") or []

        if not ids:
            return

        versioned = sorted(
            zip(ids, metadatas, strict=False),
            key=lambda pair: pair[1].get("version", 0) if pair[1] else 0,
            reverse=True,
        )
        # Keep the newest max_versions entries active; deactivate the rest
        to_deactivate = [id_ for id_, _ in versioned[max_versions:]]
        for entry_id in to_deactivate:
            collection.update(
                ids=[entry_id],
                metadatas=[{"is_active": False}],
            )

    def rollback(self, corpus: str, target_version: int) -> None:  # noqa: ARG002
        """Deactivate entries with version > target_version."""
        collection = self._get_collection()
        result = collection.get()
        ids = result.get("ids") or []
        metadatas = result.get("metadatas") or []

        for entry_id, meta in zip(ids, metadatas, strict=False):
            if meta and meta.get("version", 0) > target_version:
                collection.update(
                    ids=[entry_id],
                    metadatas=[{"is_active": False}],
                )
