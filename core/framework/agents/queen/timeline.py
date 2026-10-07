"""Dated timeline of what the user has told a queen.

``search_messages`` finds what was *said*; it can't answer "how many
weddings did I go to this year" or "what did I do last week" without the
model re-deriving every date and de-duplicating every repeat mention from raw
turns. This module extracts, once, a dated item for each event, fact and plan
the user states — with relative dates ("yesterday", "last week") resolved
against the session date and a few alias phrasings for keyword search — and
stores them next to the session's ``events.jsonl``:

    <session_dir>/timeline.jsonl       one item per line
    <session_dir>/timeline_meta.json   {"user_turns": n, ...} extraction cursor

``memory_tools.timeline`` serves them to the queen as ``search_timeline``.

Extraction runs on the queen's own LLM: after turns while a session is live
(:func:`subscribe_timeline_triggers`), at session stop, and for earlier
sessions that predate it (:func:`backfill_timelines`). Only user messages
are read — they are where the user's facts live, and about a tenth of the
text.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TIMELINE_FILE = "timeline.jsonl"
META_FILE = "timeline_meta.json"
SCHEMA_VERSION = 1
KINDS = ("event", "fact", "plan")

# One extraction call carries at most this much user text.
BATCH_CHARS = 12_000
MESSAGE_CHARS = 2_000
# While a session is live, extract once this many new user messages piled
# up, or after the cooldown if fewer did; session stop flushes the rest.
LIVE_BATCH_MESSAGES = int(os.environ.get("HIVE_TIMELINE_BATCH", "3"))
LIVE_COOLDOWN_S = float(os.environ.get("HIVE_TIMELINE_COOLDOWN", "300"))

_SYSTEM = """You build a dated timeline of what a user has told an assistant about their life.

The input is one or more conversation sessions. Each has a label, the date it took place, and the user's messages, numbered.

Extract every concrete event, fact and plan the user states about themselves or the people and things in
their life: what they did, bought, sold, attended, visited, made, fixed, learned, received, spent, counted or
measured; facts about their situation (work, home, possessions, routines, health, relationships, pets,
preferences, quantities); and plans. One item per distinct occurrence: two separate weddings are two items.
Skip requests, questions and chit-chat that state nothing about the user.

For each item give:
- "session": the session label, e.g. "S2"
- "turn": the number of the message it came from
- "kind": "event" (it happened), "fact" (a state or preference as of that date) or "plan" (intended, future)
- "text": one self-contained sentence about "the user" (never "I") naming what, where, with whom, and any
  number, amount, price or duration exactly as stated
- "start", "end": the dates (YYYY-MM-DD) it happened or holds, resolved against the session date.
  "yesterday" is the day before; "last week" is the previous Monday to Sunday; "two weeks ago" is that week;
  "this month" is the 1st through the session date; "recently" or "just" is the 7 days up to the session date.
  With no time given, use the session date for both. For plans, use the intended date if stated, otherwise
  the session date.
- "aliases": 2 to 4 short rephrasings in different words (synonyms, the category it belongs to) so a keyword
  search finds it

Reply with JSON only: {"items": [...]}, or {"items": []} when there is nothing."""


@dataclass
class SessionText:
    """User messages of one session, numbered from 1 within the session."""

    session_id: str
    started_at: datetime
    messages: list[tuple[int, str]]


# ---------------------------------------------------------------------------
# Reading sessions
# ---------------------------------------------------------------------------


def session_started_at(session_id: str) -> datetime | None:
    from memory_tools.paths import parse_session_started_at

    return parse_session_started_at(session_id)


def user_messages(session_dir: Path) -> list[str]:
    """The user's messages in a session, in order, from ``events.jsonl``."""
    path = session_dir / "events.jsonl"
    if not path.is_file():
        return []
    out: list[str] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"client_input_received"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            content = (event.get("data") or {}).get("content")
            if event.get("type") == "client_input_received" and isinstance(content, str) and content.strip():
                out.append(content)
    return out


def _read_meta(session_dir: Path) -> dict[str, Any]:
    try:
        return json.loads((session_dir / META_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _append_items(session_dir: Path, items: list[dict[str, Any]], user_turns: int, model: str) -> None:
    if items:
        with (session_dir / TIMELINE_FILE).open("a", encoding="utf-8") as fh:
            for item in items:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    meta = {"version": SCHEMA_VERSION, "user_turns": user_turns, "model": model, "updated_at": datetime.now().isoformat(timespec="seconds")}
    tmp = session_dir / (META_FILE + ".tmp")
    tmp.write_text(json.dumps(meta), encoding="utf-8")
    tmp.replace(session_dir / META_FILE)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _batches(sessions: list[SessionText]) -> list[list[SessionText]]:
    """Pack sessions into calls of at most :data:`BATCH_CHARS` user text.

    A session too big for one call is split across calls; each part keeps
    its session id and date, so items still land where they belong.
    """
    batches: list[list[SessionText]] = []
    current: list[SessionText] = []
    size = 0
    for s in sessions:
        part: list[tuple[int, str]] = []
        part_size = 0
        for turn, text in s.messages:
            text = text[:MESSAGE_CHARS]
            if part and size + part_size + len(text) > BATCH_CHARS:
                current.append(SessionText(s.session_id, s.started_at, part))
                batches.append(current)
                current, size, part, part_size = [], 0, [], 0
            part.append((turn, text))
            part_size += len(text)
        if part:
            current.append(SessionText(s.session_id, s.started_at, part))
            size += part_size
        if size >= BATCH_CHARS:
            batches.append(current)
            current, size = [], 0
    if current:
        batches.append(current)
    return batches


def _prompt(batch: list[SessionText]) -> tuple[str, dict[str, SessionText]]:
    labels: dict[str, SessionText] = {}
    blocks = []
    for i, s in enumerate(batch, 1):
        label = f"S{i}"
        labels[label] = s
        lines = [f"Session {label}, {s.started_at:%Y-%m-%d (%A)}"]
        lines += [f"[{turn}] {' '.join(text.split())}" for turn, text in s.messages]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks), labels


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _as_date(value: Any, fallback: date) -> date:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            pass
    return fallback


def _clean(raw: Any, labels: dict[str, SessionText]) -> tuple[str, dict[str, Any]] | None:
    """Validate one model item → (session id, stored item), or None."""
    if not isinstance(raw, dict):
        return None
    session = labels.get(str(raw.get("session", "")).strip())
    text = str(raw.get("text") or "").strip()
    if session is None or not text:
        return None
    said_on = session.started_at.date()
    start = _as_date(raw.get("start"), said_on)
    end = _as_date(raw.get("end"), start)
    if end < start:
        start, end = end, start
    kind = str(raw.get("kind") or "event").strip().lower()
    turns = {t for t, _ in session.messages}
    try:
        turn = int(raw.get("turn"))
    except (TypeError, ValueError):
        turn = min(turns)
    aliases = [str(a).strip() for a in raw.get("aliases") or [] if str(a).strip()][:4]
    return session.session_id, {
        "turn": turn if turn in turns else min(turns),
        "kind": kind if kind in KINDS else "event",
        "text": text,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "aliases": aliases,
    }


async def _extract_batch(llm: Any, batch: list[SessionText]) -> dict[str, list[dict[str, Any]]]:
    prompt, labels = _prompt(batch)
    response = await llm.acomplete(
        messages=[{"role": "user", "content": prompt}],
        system=_SYSTEM,
        json_mode=True,
        max_tokens=8000,
    )
    data = _parse_json(getattr(response, "content", "") or "")
    out: dict[str, list[dict[str, Any]]] = {s.session_id: [] for s in batch}
    for raw in data.get("items") or []:
        cleaned = _clean(raw, labels)
        if cleaned:
            out[cleaned[0]].append(cleaned[1])
    return out


async def extract(llm: Any, sessions: list[SessionText], *, concurrency: int = 4) -> dict[str, list[dict[str, Any]]]:
    """Timeline items for each session (by id), batching calls by size."""
    out: dict[str, list[dict[str, Any]]] = {s.session_id: [] for s in sessions}
    gate = asyncio.Semaphore(concurrency)

    async def run(batch: list[SessionText]) -> None:
        async with gate:
            for session_id, items in (await _extract_batch(llm, batch)).items():
                out[session_id].extend(items)

    await asyncio.gather(*(run(b) for b in _batches([s for s in sessions if s.messages])))
    return out


# ---------------------------------------------------------------------------
# Keeping session timelines current
# ---------------------------------------------------------------------------

_session_locks: dict[str, asyncio.Lock] = {}


def _pending(session_dir: Path) -> tuple[SessionText | None, int]:
    """Messages not yet extracted, and the session's total user turns."""
    started = session_started_at(session_dir.name)
    messages = user_messages(session_dir)
    done = int(_read_meta(session_dir).get("user_turns") or 0)
    if started is None or len(messages) <= done:
        return None, len(messages)
    numbered = list(enumerate(messages, 1))[done:]
    return SessionText(session_dir.name, started, numbered), len(messages)


async def update_session_timeline(llm: Any, session_dir: Path) -> int:
    """Extract the session's user messages added since the last run. Returns items written."""
    lock = _session_locks.setdefault(str(session_dir), asyncio.Lock())
    async with lock:
        pending, total = _pending(session_dir)
        if pending is None:
            return 0
        items = (await extract(llm, [pending]))[session_dir.name]
        _append_items(session_dir, items, total, getattr(llm, "model", ""))
        return len(items)


def cache_key(session: SessionText, model: str) -> str:
    """Content key for a session's extraction: same messages + date + model → same items."""
    h = hashlib.sha256()
    h.update(f"{SCHEMA_VERSION}|{model}|{session.started_at.isoformat()}".encode())
    for turn, text in session.messages:
        h.update(f"\n{turn}\x00{text}".encode())
    return h.hexdigest()[:32]


async def backfill_timelines(
    llm: Any,
    sessions_dir: Path,
    *,
    limit: int | None = None,
    exclude: set[str] | None = None,
    cache_dir: Path | None = None,
    concurrency: int = 4,
) -> int:
    """Extract timelines for sessions under *sessions_dir* that are behind.

    Newest sessions first, at most *limit* of them. *cache_dir* stores
    extractions by content (:func:`cache_key`), so re-running over the same
    sessions — the benchmark does, many times — costs nothing. Returns the
    number of sessions brought up to date.
    """
    if not sessions_dir.is_dir():
        return 0
    todo: list[tuple[Path, SessionText, int]] = []
    for session_dir in sorted((p for p in sessions_dir.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        if exclude and session_dir.name in exclude:
            continue
        pending, total = _pending(session_dir)
        if pending is not None:
            todo.append((session_dir, pending, total))
        if limit is not None and len(todo) >= limit:
            break
    if not todo:
        return 0

    model = getattr(llm, "model", "")
    results: dict[str, list[dict[str, Any]]] = {}
    uncached: list[SessionText] = []
    for _dir, pending, _total in todo:
        cached = cache_dir / f"{cache_key(pending, model)}.json" if cache_dir else None
        if cached is not None and cached.is_file():
            results[pending.session_id] = json.loads(cached.read_text(encoding="utf-8"))
        else:
            uncached.append(pending)
    if uncached:
        fresh = await extract(llm, uncached, concurrency=concurrency)
        for pending in uncached:
            results[pending.session_id] = fresh[pending.session_id]
            if cache_dir is not None:
                cache_dir.mkdir(parents=True, exist_ok=True)
                (cache_dir / f"{cache_key(pending, model)}.json").write_text(json.dumps(fresh[pending.session_id]), encoding="utf-8")

    for session_dir, pending, total in todo:
        _append_items(session_dir, results[pending.session_id], total, model)
    return len(todo)


async def subscribe_timeline_triggers(event_bus: Any, session_dir: Path, llm: Any, *, backfill_sessions: int = 10) -> list[str]:
    """Keep the live session's timeline current; backfill recent earlier sessions.

    Extraction runs in the background after a completed queen turn once
    :data:`LIVE_BATCH_MESSAGES` new user messages are waiting, or after
    :data:`LIVE_COOLDOWN_S` if fewer are. Session stop flushes the rest
    (:func:`update_session_timeline`, called by the session manager).
    At subscribe time, up to *backfill_sessions* earlier sessions of this
    queen that predate timelines are extracted, newest first.
    """
    from framework.host.event_bus import EventType

    tasks: set[asyncio.Task] = set()
    last_run = 0.0

    def spawn(coro: Any, what: str) -> None:
        async def guarded() -> None:
            try:
                await coro
            except Exception:
                logger.warning("timeline: %s failed", what, exc_info=True)

        task = asyncio.create_task(guarded())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def on_turn_complete(event: Any) -> None:
        nonlocal last_run
        if getattr(event, "stream_id", None) != "queen":
            return
        if (getattr(event, "data", None) or {}).get("stop_reason") in ("tool_use", "tool_calls"):
            return
        pending, _total = _pending(session_dir)
        if pending is None:
            return
        waited = time.monotonic() - last_run
        if len(pending.messages) < LIVE_BATCH_MESSAGES and waited < LIVE_COOLDOWN_S:
            return
        last_run = time.monotonic()
        spawn(update_session_timeline(llm, session_dir), "live update")

    if backfill_sessions > 0:
        spawn(
            backfill_timelines(llm, session_dir.parent, limit=backfill_sessions, exclude={session_dir.name}, concurrency=2),
            "backfill",
        )
    return [event_bus.subscribe(event_types=[EventType.LLM_TURN_COMPLETE], handler=on_turn_complete)]


__all__ = [
    "SessionText",
    "backfill_timelines",
    "cache_key",
    "extract",
    "subscribe_timeline_triggers",
    "update_session_timeline",
    "user_messages",
]
