"""Hashline utilities for anchor-based file editing.

Each line gets a short content hash anchor (line_number:hash). Models reference
lines by anchor instead of reproducing text. If the file changed since the model
read it, the hash won't match and the edit is cleanly rejected.
"""

import zlib


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
