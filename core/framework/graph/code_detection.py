"""Heuristics for detecting code-like content in text payloads."""

from __future__ import annotations

import re

_FULL_SCAN_MAX_CHARS = 10_000
_SAMPLE_CHUNK_SIZE = 2_000

_STRONG_SUBSTRINGS = (
    "```",
    "<script",
    "<?php",
    "<%",
    "if __name__",
    "=> {",
    "require(",
)

_STRONG_PATTERNS = (
    re.compile(r"^\s*async\s+def\s+[A-Za-z_][\w]*\s*\(", re.MULTILINE),
    re.compile(r"^\s*def\s+[A-Za-z_][\w]*\s*\(", re.MULTILINE),
    re.compile(r"^\s*class\s+[A-Za-z_][\w]*\s*[:(]", re.MULTILINE),
    re.compile(r"^\s*from\s+[A-Za-z_][\w.]*\s+import\s+[\w.*,\s]+$", re.MULTILINE),
    re.compile(
        r"^\s*import\s+[A-Za-z_][\w.]*(\s*,\s*[A-Za-z_][\w.]*)*(\s+as\s+[A-Za-z_][\w]*)?\s*$",
        re.MULTILINE,
    ),
    re.compile(r"^\s*try\s*:\s*$", re.MULTILINE),
    re.compile(r"^\s*except\b.*:\s*$", re.MULTILINE),
    re.compile(r"^\s*function\s+[A-Za-z_$][\w$]*\s*\(", re.MULTILINE),
    re.compile(r"^\s*(const|let|var)\s+[A-Za-z_$][\w$]*\s*=", re.MULTILINE),
    re.compile(r"^\s*export\s+(default\s+)?(function|class|const|let|var|\{)", re.MULTILINE),
    re.compile(
        r"^\s*(SELECT|INSERT|UPDATE|DELETE|DROP)\b.+\b(FROM|INTO|TABLE|SET)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
)

_WEAK_PATTERNS = (
    re.compile(r"^\s*(import|from|class|const|let|var|function|export)\b", re.MULTILINE),
    re.compile(r"^\s*(select|insert|update|delete|drop)\b", re.IGNORECASE | re.MULTILINE),
)


def _iter_chunks(value: str) -> list[str]:
    if len(value) < _FULL_SCAN_MAX_CHARS:
        return [value]

    positions = [
        0,  # Start
        len(value) // 4,  # 25%
        len(value) // 2,  # 50%
        (3 * len(value)) // 4,  # 75%
        max(0, len(value) - _SAMPLE_CHUNK_SIZE),  # Near end
    ]
    return [value[pos : pos + _SAMPLE_CHUNK_SIZE] for pos in positions]


def contains_code_indicators(value: str) -> bool:
    """Return True when a text chunk is likely code, not plain prose.

    Two-tier strategy:
    - Strong indicators (code fences/syntax) trigger immediately.
    - Weak keyword indicators must appear at least twice on line anchors.
    """
    if not value:
        return False

    for chunk in _iter_chunks(value):
        chunk_lower = chunk.lower()

        if any(indicator in chunk_lower for indicator in _STRONG_SUBSTRINGS):
            return True

        if any(pattern.search(chunk) for pattern in _STRONG_PATTERNS):
            return True

        weak_hits = 0
        for pattern in _WEAK_PATTERNS:
            weak_hits += len(pattern.findall(chunk))
            if weak_hits >= 2:
                return True

    return False
