"""Phase 3 of search_messages: enrich hits with turn-window context.

A "turn" here is the natural conversational unit, bounded by user
messages:

    [user] → [assistant] → [tool]* → [assistant] → [tool]* → ... → next [user]

For each hit at ordinal N, the enricher returns the messages in the
turn that contains N: every message from the most recent user message
at or before N, up to (but not including) the next user message.

Trimming rules (applied in this order so the matched substring is
preserved verbatim):

    1. Per-message cap: middle-truncate any single message longer than
       ``per_message_char_cap``, but never trim across the matched
       span. The hit message gets a window centered on the match.
    2. Total turn cap: if the assembled turn exceeds ``turn_char_cap``,
       further trim non-hit messages first (front and back of window),
       only encroaching on the hit message's surrounding text last.
    3. ``match_offsets`` are re-anchored to the *trimmed* hit message
       content the agent actually receives.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from memory_tools import paths as P
from memory_tools.locate import Hit

logger = logging.getLogger(__name__)


_OMITTED_MARKER = "…[{n} chars omitted]…"


@dataclass
class TurnMessage:
    ordinal: int
    role: str
    content: str
    is_hit: bool = False


@dataclass
class EnrichedHit:
    session: str
    ordinal: int
    role: str
    match_offsets: tuple[int, int]
    sources: list[str]
    turn: list[TurnMessage] | None  # None when context == "none"


# ── Session-level helpers ─────────────────────────────────────────────


def _list_session_messages(events_dir: Path) -> list[tuple[int, str, Path]]:
    """Return [(ordinal, role, path), …] sorted by ordinal."""
    if not events_dir.exists():
        return []
    out: list[tuple[int, str, Path]] = []
    for entry in events_dir.iterdir():
        if not entry.is_file():
            continue
        name = entry.name
        if not name.endswith(".txt"):
            continue
        # 000087.tool.txt → ordinal 87, role "tool"
        try:
            ordinal_str, role, _ext = name.split(".", 2)
            ordinal = int(ordinal_str)
        except (ValueError, IndexError):
            continue
        if role not in {"user", "assistant", "tool"}:
            continue
        out.append((ordinal, role, entry))
    out.sort(key=lambda t: t[0])
    return out


def _turn_bounds(
    messages: list[tuple[int, str, Path]],
    hit_ordinal: int,
) -> tuple[int, int]:
    """Return [start_index, end_index) into ``messages`` for the hit's turn."""
    # Find the index of the hit message.
    hit_index = None
    for i, (ord_, _role, _path) in enumerate(messages):
        if ord_ == hit_ordinal:
            hit_index = i
            break
    if hit_index is None:
        return (0, 0)

    # Walk backward to the most recent user message at or before hit.
    start = hit_index
    while start > 0 and messages[start][1] != "user":
        start -= 1

    # Walk forward to (but excluding) the next user message after hit.
    end = hit_index + 1
    while end < len(messages) and messages[end][1] != "user":
        end += 1

    return (start, end)


# ── Trimming primitives ──────────────────────────────────────────────


def _middle_trim(text: str, cap: int) -> str:
    """Middle-truncate text to ``cap`` chars with an omitted-chars marker."""
    if len(text) <= cap:
        return text
    marker_template = _OMITTED_MARKER
    omitted_count = len(text) - cap
    marker = marker_template.format(n=omitted_count)
    keep = max(cap - len(marker), 0)
    head = keep // 2
    tail = keep - head
    return text[:head] + marker + text[-tail:] if tail else text[:head] + marker


def _trim_around_match(
    text: str,
    span: tuple[int, int],
    cap: int,
) -> tuple[str, tuple[int, int]]:
    """Trim ``text`` to ``cap`` while preserving ``[span[0]:span[1]]``.

    Returns (trimmed_text, new_offsets_into_trimmed_text).
    """
    start, end = span
    match_len = end - start
    if len(text) <= cap or match_len >= cap:
        # Either small enough already, or the match itself exceeds the cap;
        # in the latter case we keep the match plus a head marker.
        if match_len >= cap:
            return text[start:end], (0, match_len)
        return text, span

    budget = cap - match_len
    # Aim for equal context before and after; clamp at boundaries.
    want_before = budget // 2
    want_after = budget - want_before

    avail_before = start
    avail_after = len(text) - end

    take_before = min(want_before, avail_before)
    take_after = min(want_after, avail_after)
    # Reallocate any leftover budget to the other side.
    leftover = budget - take_before - take_after
    if leftover > 0:
        if avail_before > take_before:
            extra = min(leftover, avail_before - take_before)
            take_before += extra
            leftover -= extra
        if leftover > 0 and avail_after > take_after:
            extra = min(leftover, avail_after - take_after)
            take_after += extra

    head_omitted = start - take_before
    tail_omitted = avail_after - take_after

    parts: list[str] = []
    new_start = 0
    if head_omitted > 0:
        marker = _OMITTED_MARKER.format(n=head_omitted)
        parts.append(marker)
        new_start += len(marker)
    parts.append(text[start - take_before : start])
    new_start += take_before
    new_end = new_start + match_len
    parts.append(text[start:end])
    parts.append(text[end : end + take_after])
    if tail_omitted > 0:
        parts.append(_OMITTED_MARKER.format(n=tail_omitted))
    return "".join(parts), (new_start, new_end)


# ── Per-hit enrichment ───────────────────────────────────────────────


def _read_message(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _re_anchor_via_pattern(text: str, pattern: str, *, ignore_case: bool, multiline: bool, dotall: bool) -> tuple[int, int] | None:
    """When the locate phase didn't supply byte offsets (data-only hit),
    re-search the message body with the same regex to find the span."""
    flags = 0
    if ignore_case:
        flags |= re.IGNORECASE
    if multiline:
        flags |= re.MULTILINE
    if dotall:
        flags |= re.DOTALL
    try:
        compiled = re.compile(pattern, flags)
    except re.error:
        return None
    m = compiled.search(text)
    if not m:
        return None
    # Convert char offsets → byte offsets to match locate's convention.
    prefix = text[: m.start()].encode("utf-8", errors="replace")
    matched = text[m.start() : m.end()].encode("utf-8", errors="replace")
    start_b = len(prefix)
    return (start_b, start_b + len(matched))


def _byte_to_char_span(text: str, span_bytes: tuple[int, int]) -> tuple[int, int]:
    """Convert byte offsets (rg's unit) to character offsets (Python's unit)."""
    if span_bytes == (0, 0):
        return (0, 0)
    raw = text.encode("utf-8", errors="replace")
    sb, eb = span_bytes
    sb = max(0, min(sb, len(raw)))
    eb = max(sb, min(eb, len(raw)))
    head = raw[:sb].decode("utf-8", errors="replace")
    body = raw[sb:eb].decode("utf-8", errors="replace")
    return (len(head), len(head) + len(body))


def _enrich_one(
    hit: Hit,
    *,
    pattern: str,
    ignore_case: bool,
    multiline: bool,
    dotall: bool,
    context: Literal["none", "narrow", "turn"],
    turn_char_cap: int,
    per_message_char_cap: int,
) -> EnrichedHit:
    if context == "none":
        return EnrichedHit(
            session=hit.session,
            ordinal=hit.ordinal,
            role=hit.role,
            match_offsets=(0, 0),
            sources=sorted(hit.sources),
            turn=None,
        )

    events_dir = P.events_index_dir(hit.scope, hit.owner, hit.session)
    messages = _list_session_messages(events_dir)
    if not messages:
        return EnrichedHit(
            session=hit.session,
            ordinal=hit.ordinal,
            role=hit.role,
            match_offsets=(0, 0),
            sources=sorted(hit.sources),
            turn=[],
        )

    # Locate the hit message's path.
    hit_path = None
    for ord_, _role, path in messages:
        if ord_ == hit.ordinal:
            hit_path = path
            break

    hit_text = _read_message(hit_path) if hit_path is not None else ""

    # Resolve the match span in *character* units. If locate didn't give
    # us one (data-only hit), re-search the body.
    if hit.match_offsets == (0, 0):
        span = _re_anchor_via_pattern(
            hit_text,
            pattern,
            ignore_case=ignore_case,
            multiline=multiline,
            dotall=dotall,
        ) or (0, 0)
        char_span = _byte_to_char_span(hit_text, span) if span != (0, 0) else (0, 0)
    else:
        char_span = _byte_to_char_span(hit_text, hit.match_offsets)

    # Trim the hit message around the match.
    trimmed_hit, new_span = _trim_around_match(hit_text, char_span, per_message_char_cap)

    if context == "narrow":
        return EnrichedHit(
            session=hit.session,
            ordinal=hit.ordinal,
            role=hit.role,
            match_offsets=new_span,
            sources=sorted(hit.sources),
            turn=[
                TurnMessage(
                    ordinal=hit.ordinal,
                    role=hit.role,
                    content=trimmed_hit,
                    is_hit=True,
                )
            ],
        )

    # context == "turn": assemble the full turn window.
    start_idx, end_idx = _turn_bounds(messages, hit.ordinal)
    window: list[TurnMessage] = []
    for i in range(start_idx, end_idx):
        ord_, role_, path_ = messages[i]
        if ord_ == hit.ordinal:
            window.append(
                TurnMessage(
                    ordinal=ord_,
                    role=role_,
                    content=trimmed_hit,
                    is_hit=True,
                )
            )
        else:
            body = _read_message(path_)
            if len(body) > per_message_char_cap:
                body = _middle_trim(body, per_message_char_cap)
            window.append(TurnMessage(ordinal=ord_, role=role_, content=body))

    # Apply turn_char_cap: trim non-hit messages first, hit last.
    total = sum(len(m.content) for m in window)
    if total > turn_char_cap:
        # First pass: shrink each non-hit message by its proportional share
        # of the overflow, preserving at least 80 chars head + tail.
        overflow = total - turn_char_cap
        non_hit = [m for m in window if not m.is_hit]
        non_hit_total = sum(len(m.content) for m in non_hit) or 1
        for m in non_hit:
            share = int(round(overflow * (len(m.content) / non_hit_total)))
            new_cap = max(160, len(m.content) - share)
            if len(m.content) > new_cap:
                m.content = _middle_trim(m.content, new_cap)
        total = sum(len(m.content) for m in window)

    if total > turn_char_cap:
        # Final pass: trim hit message tighter, but never across the match.
        for m in window:
            if not m.is_hit:
                continue
            new_cap = max(len(m.content) - (total - turn_char_cap), new_span[1] - new_span[0] + 64)
            tighter, new_span = _trim_around_match(trimmed_hit, new_span, new_cap)
            m.content = tighter

    return EnrichedHit(
        session=hit.session,
        ordinal=hit.ordinal,
        role=hit.role,
        match_offsets=new_span,
        sources=sorted(hit.sources),
        turn=window,
    )


def enrich(
    hits: list[Hit],
    *,
    pattern: str,
    ignore_case: bool,
    multiline: bool,
    dotall: bool,
    context: Literal["none", "narrow", "turn"],
    turn_char_cap: int,
    per_message_char_cap: int,
    max_workers: int = 8,
) -> list[EnrichedHit]:
    """Enrich every hit in parallel; preserves input order on output."""
    if not hits:
        return []
    if context == "none" or len(hits) == 1 or max_workers <= 1:
        return [
            _enrich_one(
                h,
                pattern=pattern,
                ignore_case=ignore_case,
                multiline=multiline,
                dotall=dotall,
                context=context,
                turn_char_cap=turn_char_cap,
                per_message_char_cap=per_message_char_cap,
            )
            for h in hits
        ]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        # Submit in order; collect results by index to preserve ordering.
        futures = [
            pool.submit(
                _enrich_one,
                h,
                pattern=pattern,
                ignore_case=ignore_case,
                multiline=multiline,
                dotall=dotall,
                context=context,
                turn_char_cap=turn_char_cap,
                per_message_char_cap=per_message_char_cap,
            )
            for h in hits
        ]
        return [f.result() for f in futures]


__all__ = ["EnrichedHit", "TurnMessage", "enrich"]
