"""DiffParser — parses unified diff text into structured, immutable data."""

import fnmatch
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pr_reviewer.logging import get_logger

if TYPE_CHECKING:
    from pr_reviewer.config.schema import Config

_logger = get_logger(__name__)

_MAX_CHANGED_LINES = 3000

DEFAULT_IGNORE_PATTERNS: list[str] = [
    "*.lock",
    "*.min.js",
    "*.min.css",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "go.sum",
    "*.pb.go",
    "*.generated.*",
]

_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".swift": "swift",
    ".scala": "scala",
    ".sh": "shell",
    ".bash": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
}

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
_BINARY_RE = re.compile(r"^Binary files ")


class ChangeType(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CONTEXT = "context"


@dataclass(frozen=True)
class DiffLine:
    line_number: int | None
    content: str
    change_type: ChangeType


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[DiffLine, ...]


@dataclass(frozen=True)
class ChangedFile:
    filename: str
    language: str
    hunks: tuple[Hunk, ...]
    github_position_map: dict[int, int]


@dataclass(frozen=True)
class StructuredDiff:
    changed_files: tuple[ChangedFile, ...]
    skipped_files: tuple[str, ...]
    truncated: bool
    truncation_notice: str


def _detect_language(filename: str) -> str:
    dot = filename.rfind(".")
    if dot == -1:
        return "unknown"
    return _LANGUAGE_MAP.get(filename[dot:].lower(), "unknown")


def _matches_any(filename: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(filename, pat):
            return True
        # Also check basename-only match
        basename = filename.rsplit("/", 1)[-1]
        if fnmatch.fnmatch(basename, pat):
            return True
    return False


def _resolve_patterns(config: "Config") -> list[str]:
    if config.ignore_patterns_override is not None and config.ignore_patterns_extend is not None:
        _logger.error("conflicting ignore fields; override applied — extend list ignored")
        return list(config.ignore_patterns_override)
    if config.ignore_patterns_override is not None:
        return list(config.ignore_patterns_override)
    if config.ignore_patterns_extend is not None:
        return DEFAULT_IGNORE_PATTERNS + list(config.ignore_patterns_extend)
    return DEFAULT_IGNORE_PATTERNS


class DiffParser:
    def parse(self, raw_diff: str, config: "Config") -> StructuredDiff:
        patterns = _resolve_patterns(config)
        changed_files: list[ChangedFile] = []
        skipped_files: list[str] = []
        total_changed = 0
        truncated = False

        file_blocks = self._split_file_blocks(raw_diff)

        for filename, block_lines in file_blocks:
            if _matches_any(filename, patterns):
                skipped_files.append(filename)
                continue

            if self._is_binary(block_lines):
                skipped_files.append(filename)
                continue

            hunks, file_changed, file_position_map, hit_limit = self._parse_hunks(
                block_lines, total_changed
            )
            total_changed += file_changed
            if hit_limit:
                truncated = True

            changed_files.append(
                ChangedFile(
                    filename=filename,
                    language=_detect_language(filename),
                    hunks=tuple(hunks),
                    github_position_map=file_position_map,
                )
            )

            if truncated:
                break

        return StructuredDiff(
            changed_files=tuple(changed_files),
            skipped_files=tuple(skipped_files),
            truncated=truncated,
            truncation_notice=(
                f"Diff truncated: showing first {_MAX_CHANGED_LINES} changed lines."
                if truncated
                else ""
            ),
        )

    def _split_file_blocks(self, raw: str) -> list[tuple[str, list[str]]]:
        blocks: list[tuple[str, list[str]]] = []
        current_filename: str | None = None
        current_lines: list[str] = []

        for line in raw.splitlines():
            m = _DIFF_FILE_RE.match(line)
            if m:
                if current_filename is not None:
                    blocks.append((current_filename, current_lines))
                current_filename = m.group(2)
                current_lines = [line]
            elif current_filename is not None:
                current_lines.append(line)

        if current_filename is not None:
            blocks.append((current_filename, current_lines))

        return blocks

    def _is_binary(self, lines: list[str]) -> bool:
        return any(_BINARY_RE.match(line) for line in lines)

    def _parse_hunks(
        self, lines: list[str], already_changed: int
    ) -> tuple[list[Hunk], int, dict[int, int], bool]:
        hunks: list[Hunk] = []
        position_map: dict[int, int] = {}
        file_changed = 0
        hit_limit = False

        position = 0  # github diff position (1-indexed, reset per file)
        current_hunk_lines: list[DiffLine] = []
        # (old_start, old_count, new_start, new_count)
        current_hunk: tuple[int, int, int, int] | None = None
        new_line_no = 0

        for line in lines:
            m = _HUNK_HEADER_RE.match(line)
            if m:
                if current_hunk is not None and current_hunk_lines:
                    os, oc, ns, nc = current_hunk
                    hunks.append(Hunk(os, oc, ns, nc, tuple(current_hunk_lines)))
                    current_hunk_lines = []

                os = int(m.group(1))
                oc = int(m.group(2)) if m.group(2) is not None else 1
                ns = int(m.group(3))
                nc = int(m.group(4)) if m.group(4) is not None else 1
                current_hunk = (os, oc, ns, nc)
                new_line_no = ns
                position += 1  # hunk header counts as position
                continue

            if current_hunk is None:
                continue

            if line.startswith("+"):
                if already_changed + file_changed >= _MAX_CHANGED_LINES:
                    hit_limit = True
                    break
                dl = DiffLine(
                    line_number=new_line_no,
                    content=line[1:],
                    change_type=ChangeType.ADDED,
                )
                position += 1
                position_map[new_line_no] = position
                new_line_no += 1
                file_changed += 1
                current_hunk_lines.append(dl)

            elif line.startswith("-"):
                if already_changed + file_changed >= _MAX_CHANGED_LINES:
                    hit_limit = True
                    break
                dl = DiffLine(
                    line_number=None,
                    content=line[1:],
                    change_type=ChangeType.REMOVED,
                )
                position += 1
                file_changed += 1
                current_hunk_lines.append(dl)

            elif line.startswith(" ") or line == "":
                dl = DiffLine(
                    line_number=new_line_no,
                    content=line[1:] if line.startswith(" ") else "",
                    change_type=ChangeType.CONTEXT,
                )
                position += 1
                position_map[new_line_no] = position
                new_line_no += 1
                current_hunk_lines.append(dl)

        if current_hunk is not None and current_hunk_lines:
            os, oc, ns, nc = current_hunk
            hunks.append(Hunk(os, oc, ns, nc, tuple(current_hunk_lines)))

        return hunks, file_changed, position_map, hit_limit
