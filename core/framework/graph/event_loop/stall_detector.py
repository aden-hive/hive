"""Stall and doom-loop detection for the event loop.

Pure functions with no class dependencies — safe to call from any context.
"""

from __future__ import annotations

import json


def ngram_similarity(s1: str, s2: str, n: int = 2) -> float:
    """Jaccard similarity of n-gram sets.

    Returns 0.0-1.0, where 1.0 is exact match.
    Fast: O(len(s) + len(s2)) using set operations.
    """

    def _ngrams(s: str) -> set[str]:
        return {s[i : i + n] for i in range(len(s) - n + 1) if s.strip()}

    if not s1 or not s2:
        return 0.0

    ngrams1, ngrams2 = _ngrams(s1.lower()), _ngrams(s2.lower())
    if not ngrams1 or not ngrams2:
        return 0.0

    intersection = len(ngrams1 & ngrams2)
    union = len(ngrams1 | ngrams2)
    return intersection / union if union else 0.0


def is_stalled(
    recent_responses: list[str],
    threshold: int,
    similarity_threshold: float,
) -> bool:
    """Detect stall using n-gram similarity.

    Detects when ALL N consecutive responses are mutually similar
    (>= threshold).  A single dissimilar response resets the signal.
    This catches phrases like "I'm still stuck" vs "I'm stuck"
    without false-positives on "attempt 1" vs "attempt 2".
    """
    if len(recent_responses) < threshold:
        return False
    if not recent_responses[0]:
        return False

    # Every consecutive pair must be similar
    for i in range(1, len(recent_responses)):
        if ngram_similarity(recent_responses[i], recent_responses[i - 1]) < similarity_threshold:
            return False
    return True


def fingerprint_tool_calls(
    tool_results: list[dict],
) -> list[tuple[str, str]]:
    """Create deterministic fingerprints for a turn's tool calls.

    Each fingerprint is (tool_name, canonical_args_json).  Order-sensitive
    so [search("a"), fetch("b")] != [fetch("b"), search("a")].
    """
    fingerprints = []
    for tr in tool_results:
        name = tr.get("tool_name", "")
        args = tr.get("tool_input", {})
        try:
            canonical = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            canonical = str(args)
        fingerprints.append((name, canonical))
    return fingerprints


def is_tool_doom_loop(
    recent_tool_fingerprints: list[list[tuple[str, str]]],
    threshold: int,
    enabled: bool = True,
) -> tuple[bool, str]:
    """Detect doom loop via exact fingerprint match.

    Detects when N consecutive turns invoke the same tools with
    identical (canonicalized) arguments.  Different arguments mean
    different work, so only exact matches count.

    Returns (is_doom_loop, description).
    """
    if not enabled:
        return False, ""
    if len(recent_tool_fingerprints) < threshold:
        return False, ""
    first = recent_tool_fingerprints[0]
    if not first:
        return False, ""

    # All turns in the window must match the first exactly
    if all(fp == first for fp in recent_tool_fingerprints[1:]):
        tool_names = [name for name, _ in first]
        desc = (
            f"Doom loop detected: {len(recent_tool_fingerprints)} "
            f"identical consecutive tool calls ({', '.join(tool_names)})"
        )
        return True, desc
    return False, ""
