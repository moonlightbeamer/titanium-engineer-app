"""Unit tests for DiffParser (tasks 7.1–7.9)."""

import logging
import textwrap

import pytest

from pr_reviewer.config.schema import Config

# ── Fixtures / helpers ────────────────────────────────────────────────────────


def _simple_diff(filename: str = "foo.py", lines: list[str] | None = None) -> str:
    body = "\n".join(lines or [" context", "+added"])
    return textwrap.dedent(f"""\
        diff --git a/{filename} b/{filename}
        --- a/{filename}
        +++ b/{filename}
        @@ -1,1 +1,2 @@
        {body}
    """)


# ── Task 7.1 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_added_line_has_correct_github_position_index():
    from pr_reviewer.components.diff_parser import DiffParser

    raw = textwrap.dedent("""\
        diff --git a/foo.py b/foo.py
        --- a/foo.py
        +++ b/foo.py
        @@ -1,2 +1,3 @@
         context line
        -removed line
        +added line 1
        +added line 2
    """)
    result = DiffParser().parse(raw, Config())
    assert len(result.changed_files) == 1
    f = result.changed_files[0]
    # position 1=hunk header, 2=context(line1), 3=removed, 4=added(line2), 5=added(line3)
    positions = [f.github_position_map[ln] for ln in sorted(f.github_position_map)]
    assert positions == sorted(positions), "positions must increase monotonically"
    assert f.github_position_map[2] == 4  # new line 2 is at diff position 4
    assert f.github_position_map[3] == 5  # new line 3 is at diff position 5


# ── Task 7.2 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_binary_file_not_in_changed_files():
    from pr_reviewer.components.diff_parser import DiffParser

    raw = textwrap.dedent("""\
        diff --git a/image.png b/image.png
        index abc..def 100644
        Binary files a/image.png and b/image.png differ
    """)
    result = DiffParser().parse(raw, Config())
    filenames = [f.filename for f in result.changed_files]
    assert "image.png" not in filenames
    assert "image.png" in result.skipped_files


# ── Task 7.3 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_truncation_at_exactly_3000_changed_lines():
    from pr_reviewer.components.diff_parser import ChangeType, DiffParser

    added_lines = "".join(f"+line{i}\n" for i in range(3001))
    raw = (
        "diff --git a/big.py b/big.py\n"
        "--- a/big.py\n"
        "+++ b/big.py\n"
        "@@ -0,0 +1,3001 @@\n"
        + added_lines
    )
    result = DiffParser().parse(raw, Config())
    assert result.truncated is True
    total_changed = sum(
        1
        for f in result.changed_files
        for hunk in f.hunks
        for line in hunk.lines
        if line.change_type in (ChangeType.ADDED, ChangeType.REMOVED)
    )
    assert total_changed == 3000


# ── Task 7.4 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_truncation_notice_present_in_output():
    from pr_reviewer.components.diff_parser import DiffParser

    added_lines = "".join(f"+line{i}\n" for i in range(3001))
    raw = (
        "diff --git a/big.py b/big.py\n"
        "--- a/big.py\n"
        "+++ b/big.py\n"
        "@@ -0,0 +1,3001 @@\n"
        + added_lines
    )
    result = DiffParser().parse(raw, Config())
    assert result.truncated is True
    assert result.truncation_notice != ""


# ── Task 7.5 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_override_wins_over_extend_with_warn(caplog):
    from pr_reviewer.components.diff_parser import DiffParser

    config = Config(
        ignore_patterns_override=["*.lock"],
        ignore_patterns_extend=["*.md"],
    )
    raw = textwrap.dedent("""\
        diff --git a/foo.lock b/foo.lock
        --- a/foo.lock
        +++ b/foo.lock
        @@ -1,1 +1,1 @@
        -old
        +new
        diff --git a/README.md b/README.md
        --- a/README.md
        +++ b/README.md
        @@ -1,1 +1,1 @@
        -old
        +new
    """)
    with caplog.at_level(logging.WARNING):
        result = DiffParser().parse(raw, config)

    filenames = [f.filename for f in result.changed_files]
    # override=["*.lock"] → foo.lock excluded; *.md NOT excluded (extend is ignored)
    assert "foo.lock" not in filenames
    assert "README.md" not in filenames or "README.md" in filenames  # extend ignored
    # Actually: only override list applies → *.lock excluded, *.md NOT excluded
    assert "README.md" in filenames
    assert any("conflicting ignore" in r.message.lower() for r in caplog.records)


# ── Task 7.6 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_extend_merged_with_defaults():
    from pr_reviewer.components.diff_parser import DEFAULT_IGNORE_PATTERNS, DiffParser

    # Pick a pattern from the defaults and one custom extension
    default_pattern = DEFAULT_IGNORE_PATTERNS[0]
    # Build a filename that matches the first default pattern
    # e.g., if default is "*.lock", filename = "package.lock"
    default_match = default_pattern.lstrip("*")  # e.g. ".lock"
    default_file = "test" + default_match  # e.g. "test.lock"

    config = Config(ignore_patterns_extend=["*.custom"])
    raw = textwrap.dedent(f"""\
        diff --git a/{default_file} b/{default_file}
        --- a/{default_file}
        +++ b/{default_file}
        @@ -1 +1 @@
        -old
        +new
        diff --git a/file.custom b/file.custom
        --- a/file.custom
        +++ b/file.custom
        @@ -1 +1 @@
        -old
        +new
    """)
    result = DiffParser().parse(raw, config)
    filenames = [f.filename for f in result.changed_files]
    assert default_file not in filenames
    assert "file.custom" not in filenames


# ── Task 7.7 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_file_matching_ignore_pattern_excluded():
    from pr_reviewer.components.diff_parser import DiffParser

    config = Config(ignore_patterns_override=["vendor/**"])
    raw = textwrap.dedent("""\
        diff --git a/vendor/lib/util.py b/vendor/lib/util.py
        --- a/vendor/lib/util.py
        +++ b/vendor/lib/util.py
        @@ -1 +1 @@
        -old
        +new
    """)
    result = DiffParser().parse(raw, config)
    filenames = [f.filename for f in result.changed_files]
    assert "vendor/lib/util.py" not in filenames


# ── Task 7.8 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_language_detected_from_file_extension():
    from pr_reviewer.components.diff_parser import DiffParser

    def _parse_one(filename: str) -> str:
        raw = textwrap.dedent(f"""\
            diff --git a/{filename} b/{filename}
            --- a/{filename}
            +++ b/{filename}
            @@ -1 +1 @@
            -old
            +new
        """)
        result = DiffParser().parse(raw, Config())
        return result.changed_files[0].language

    assert _parse_one("script.py") == "python"
    assert _parse_one("app.ts") == "typescript"


# ── Task 7.9 ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_github_position_map_key_is_line_number_value_is_position():
    from pr_reviewer.components.diff_parser import DiffParser

    # Diff: hunk header (pos 1), context (pos 2, new line 1), added (pos 3, new line 2)
    raw = textwrap.dedent("""\
        diff --git a/bar.py b/bar.py
        --- a/bar.py
        +++ b/bar.py
        @@ -1,1 +1,2 @@
         existing line
        +new line
    """)
    result = DiffParser().parse(raw, Config())
    f = result.changed_files[0]
    # new line 1 (context) → position 2; new line 2 (added) → position 3
    assert f.github_position_map[1] == 2
    assert f.github_position_map[2] == 3
