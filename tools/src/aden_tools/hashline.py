"""Hashline utilities for anchor-based file editing.

Each line gets a short content hash anchor (line_number:hash). Models reference
lines by anchor instead of reproducing text. If the file changed since the model
read it, the hash won't match and the edit is cleanly rejected.
"""

import re
import zlib

# ── Constants ─────────────────────────────────────────────────────────────

# Files beyond this size are skipped/rejected in hashline mode because
# hashline anchors are not practical on files this large (minified
# bundles, logs, data dumps). Shared by read_file, grep_search, and
# hashline_edit.
HASHLINE_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB

# ── Hash computation ──────────────────────────────────────────────────────


def compute_line_hash(line: str) -> str:
    """Compute a 4-char hex hash for a line of text.

    Uses CRC32 mod 65536, formatted as lowercase hex. Only trailing spaces
    and tabs are stripped before hashing. Leading whitespace (indentation)
    is included in the hash so indentation changes invalidate anchors.
    This keeps stale-anchor detection safe for indentation-sensitive files
    while still ignoring common trailing-whitespace noise.

    Collision probability is ~0.0015% per changed line (4-char hex,
    migrated from 2-char hex which had ~0.39% collision rate).
    """
    stripped = line.rstrip(" \t")
    crc = zlib.crc32(stripped.encode("utf-8")) & 0xFFFFFFFF
    return f"{crc % 65536:04x}"


def format_hashlines(lines: list[str], offset: int = 1, limit: int = 0) -> str:
    """Format lines with N:hhhh|content prefixes.

    Args:
        lines: The file content split into lines.
        offset: 1-indexed start line (default 1).
        limit: Maximum lines to return, 0 means all.

    Returns:
        Formatted string with hashline prefixes.
    """
    start = offset - 1  # convert to 0-indexed
    if limit > 0:
        selected = lines[start : start + limit]
    else:
        selected = lines[start:]

    result_parts = []
    for i, line in enumerate(selected):
        line_num = offset + i
        h = compute_line_hash(line)
        result_parts.append(f"{line_num}:{h}|{line}")

    return "\n".join(result_parts)


# ── Anchor parsing & validation ───────────────────────────────────────────


def parse_anchor(anchor: str) -> tuple[int, str]:
    """Parse an anchor string like '2:a3b1' into (line_number, hash).

    Raises:
        ValueError: If the anchor format is invalid.
    """
    if ":" not in anchor:
        raise ValueError(f"Invalid anchor format (no colon): '{anchor}'")

    parts = anchor.split(":", 1)
    try:
        line_num = int(parts[0])
    except ValueError as exc:
        raise ValueError(f"Invalid anchor format (line number not an integer): '{anchor}'") from exc

    hash_str = parts[1]
    if len(hash_str) != 4:
        raise ValueError(f"Invalid anchor format (hash must be 4 chars): '{anchor}'")
    if not all(c in "0123456789abcdef" for c in hash_str):
        raise ValueError(f"Invalid anchor format (hash must be lowercase hex): '{anchor}'")

    return line_num, hash_str


def validate_anchor(anchor: str, lines: list[str]) -> str | None:
    """Validate an anchor against file lines.

    Returns:
        None if valid, error message string if invalid.
    """
    try:
        line_num, expected_hash = parse_anchor(anchor)
    except ValueError as e:
        return str(e)

    if line_num < 1 or line_num > len(lines):
        return f"Line {line_num} out of range (file has {len(lines)} lines)"

    actual_line = lines[line_num - 1]
    actual_hash = compute_line_hash(actual_line)
    if actual_hash != expected_hash:
        preview = actual_line.strip()
        if len(preview) > 80:
            preview = preview[:77] + "..."
        return (
            f"Hash mismatch at line {line_num}: expected '{expected_hash}', "
            f"got '{actual_hash}'. Current content: {preview!r}. "
            f"Re-read the file to get current anchors."
        )

    return None


# ── Auto-cleanup helpers ──────────────────────────────────────────────────
# Shared by both file_ops.hashline_edit and file_system_toolkits.hashline_edit.

HASHLINE_PREFIX_RE = re.compile(r"^\d+:[0-9a-f]{4}\|")


def strip_content_prefixes(lines: list[str]) -> list[str]:
    """Strip hashline prefixes from content lines when all have them.

    LLMs frequently copy hashline-formatted text (e.g. '5:a3b1|content') into
    their content fields. Only strips when 2+ non-empty lines all match the
    exact hashline prefix pattern (N:hhhh|). Single-line content is left alone
    to avoid false positives on literal text that happens to match the pattern.
    """
    if not lines:
        return lines
    non_empty = [ln for ln in lines if ln]
    if len(non_empty) < 2:
        return lines
    prefix_count = sum(1 for ln in non_empty if HASHLINE_PREFIX_RE.match(ln))
    if prefix_count < len(non_empty):
        return lines
    return [HASHLINE_PREFIX_RE.sub("", ln) for ln in lines]


def whitespace_equal(a: str, b: str) -> bool:
    """Compare strings ignoring spaces and tabs."""
    return a.replace(" ", "").replace("\t", "") == b.replace(" ", "").replace("\t", "")


def strip_insert_echo(anchor_line: str, new_lines: list[str], *, position: str = "first") -> list[str]:
    """Strip echoed anchor line from insert content.

    If the model echoes the anchor line in inserted content, remove it to
    avoid duplication. Only applies when content has 2+ lines and both the
    anchor and checked content line are non-blank.

    position="first" (insert_after): check first line, strip from front.
    position="last" (insert_before): check last line, strip from end.
    """
    if len(new_lines) <= 1:
        return new_lines
    if position == "last":
        if not anchor_line.strip() or not new_lines[-1].strip():
            return new_lines
        if whitespace_equal(new_lines[-1], anchor_line):
            return new_lines[:-1]
    else:
        if not anchor_line.strip() or not new_lines[0].strip():
            return new_lines
        if whitespace_equal(new_lines[0], anchor_line):
            return new_lines[1:]
    return new_lines


def strip_boundary_echo(file_lines: list[str], start_1idx: int, end_1idx: int, new_lines: list[str]) -> list[str]:
    """Strip echoed boundary context from replace_lines content.

    If the model includes the line before AND after the replaced range as part
    of the replacement content, strip those echoed boundary lines. Both
    boundaries must echo simultaneously before either is stripped (a single
    boundary match is too likely to be a coincidence with real content).
    Only applies when the replacement has more lines than the range being
    replaced, and both the boundary line and content line are non-blank.
    """
    range_count = end_1idx - start_1idx + 1
    if len(new_lines) <= 1 or len(new_lines) <= range_count:
        return new_lines

    # Check if leading boundary echoes
    before_idx = start_1idx - 2  # 0-indexed line before range
    leading_echoes = (
        before_idx >= 0
        and new_lines[0].strip()
        and file_lines[before_idx].strip()
        and whitespace_equal(new_lines[0], file_lines[before_idx])
    )

    # Check if trailing boundary echoes
    after_idx = end_1idx  # 0-indexed line after range
    trailing_echoes = (
        after_idx < len(file_lines)
        and new_lines[-1].strip()
        and file_lines[after_idx].strip()
        and whitespace_equal(new_lines[-1], file_lines[after_idx])
    )

    # Only strip if BOTH boundaries echo and there is content between them.
    # len < 3 means no real content between the two boundary lines, so
    # stripping would produce an empty list (accidental deletion).
    if not (leading_echoes and trailing_echoes) or len(new_lines) < 3:
        return new_lines

    return new_lines[1:-1]


def maybe_strip(new_lines, strip_fn, action_name, auto_cleanup, cleanup_actions):
    """Apply a strip function if auto_cleanup is enabled, tracking actions."""
    if not auto_cleanup:
        return new_lines
    cleaned = strip_fn(new_lines)
    if cleaned != new_lines:
        if action_name not in cleanup_actions:
            cleanup_actions.append(action_name)
        return cleaned
    return new_lines
