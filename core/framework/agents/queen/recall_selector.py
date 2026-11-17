"""Recall selector — memory selection for the queen.

For each user message the system:
  1. Scans one or more memory directories for ``.md`` files (cap: 200 each).
  2. Reads headers (frontmatter + first 30 lines).
  3. Uses an LLM call with structured JSON output to pick the most relevant
     memories for each scope.
  4. Injects them into the conversation as a reminder.

``memory_recall.mode`` decides when (``framework.config.MemoryRecallConfig``);
in "index" mode there is no pick, and :func:`memory_index` lists every note.

The selector only sees the user's query string — no full conversation
context.  This keeps it cheap and fast.  Errors are caught and return
``[]`` so the main conversation is never blocked.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from framework.agents.queen import memory_log
from framework.agents.queen.queen_memory_v2 import (
    format_memory_manifest,
    global_memory_dir as _default_global_memory_dir,
    scan_memory_files,
)
from framework.config import get_aux_max_tokens

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------

SELECT_MEMORIES_SYSTEM_PROMPT = """\
You are selecting memories that will be useful to the Queen agent as it \
processes a user's query.

You will be given the user's query and a list of available memory files \
with their filenames and descriptions.

Return a JSON object with a single key "selected_memories" containing a \
list of filenames for the memories that will clearly be useful as the \
Queen processes the user's query (up to 5).

Only include memories that you are certain will be helpful based on their \
name and description.
- If you are unsure if a memory will be useful in processing the user's \
query, then do not include it in your list.  Be selective and discerning.
- If there are no memories in the list that would clearly be useful, \
return an empty list.
"""

# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


async def select_memories(
    query: str,
    llm: Any,
    memory_dir: Path | None = None,
    *,
    max_results: int = 5,
) -> list[str]:
    """Select up to 5 relevant memory filenames for *query*.

    Returns a list of filenames.  Best-effort: on any error returns ``[]``.
    """
    mem_dir = memory_dir or _default_global_memory_dir()
    files = scan_memory_files(mem_dir)
    if not files:
        logger.debug("recall: no memory files found, skipping selection")
        return []

    # Profile memories are user-identity baseline. The description rarely
    # enumerates every entity inside the body (e.g. user-profile.md will say
    # "personal life" but not name every person), so an LLM-only selector
    # misses queries like "who is <partner-name>". They back-fill whatever
    # slots the relevance picks leave (see below), so they still answer those
    # queries when the selector finds nothing better.
    pinned = [f.filename for f in files if (f.type or "").lower() == "profile"][:max_results]

    logger.debug("recall: selecting from %d memories for query: %.100s", len(files), query)
    manifest = format_memory_manifest(files)
    user_msg = f"## User query\n\n{query}\n\n## Available memories\n\n{manifest}"

    try:
        resp = await llm.acomplete(
            messages=[{"role": "user", "content": user_msg}],
            system=SELECT_MEMORIES_SYSTEM_PROMPT,
            max_tokens=get_aux_max_tokens(),
            response_format={"type": "json_object"},
        )
        raw = (resp.content or "").strip()
        if not raw:
            logger.warning(
                "recall: LLM returned empty response (model=%s, stop=%s)",
                resp.model,
                resp.stop_reason,
            )
            return pinned
        # Some models wrap JSON in markdown fences or add preamble text.
        # Try to extract the JSON object if raw parse fails.
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            import re

            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                data = json.loads(m.group())
            else:
                logger.warning("recall: LLM returned non-JSON: %.200s", raw)
                return pinned
        selected = data.get("selected_memories", [])
        valid_names = {f.filename for f in files}
        # Some models return filenames without the .md extension or as a
        # bare slug; tolerate both so we don't silently drop valid picks.
        name_aliases: dict[str, str] = {}
        for f in files:
            name_aliases[f.filename] = f.filename
            stem = f.filename.removesuffix(".md")
            name_aliases.setdefault(stem, f.filename)
        normalized: list[str] = []
        dropped: list[Any] = []
        for s in selected:
            if not isinstance(s, str):
                dropped.append(s)
                continue
            if s in valid_names:
                normalized.append(s)
            elif s in name_aliases:
                normalized.append(name_aliases[s])
            else:
                dropped.append(s)
        # Relevance first, profiles fill the rest. Pins-first let a scope with
        # max_results profile memories (one queen had 10 character sheets
        # typed "profile") return the same pins every turn and never a single
        # memory the selector judged relevant.
        result = list(dict.fromkeys([*normalized, *pinned]))[:max_results]
        if not normalized:
            # LLM picked nothing. Log the raw response so the next bug
            # report is diagnosable; we still return pinned memories.
            logger.debug(
                "recall: LLM selected 0 memories (model=%s, raw=%.300s, dropped=%s, pinned=%s)",
                resp.model,
                raw,
                dropped,
                pinned,
            )
        else:
            logger.debug(
                "recall: selected %d memories: %s (pinned=%s)",
                len(result),
                result,
                pinned,
            )
        return result
    except Exception as exc:
        logger.warning(
            "recall: memory selection failed (%s), returning pinned=%s",
            exc,
            pinned,
        )
        return pinned


def _format_relative_age(content: str, mtime: float) -> str | None:
    """How long since a conversation last supported the memory, once that is more than two days.

    Counted from its ``confirmed`` day (:mod:`memory_log`); a file from before those were recorded
    counts from when it was last written.
    """
    today = datetime.now().date()
    confirmed = memory_log.confirmed_on(content) or datetime.fromtimestamp(mtime).date()
    days = (today - confirmed).days
    if days <= 2:
        return None
    return f"last confirmed {days} days ago"


def format_recall_injection(
    filenames: list[str],
    memory_dir: Path | None = None,
    *,
    label: str = "Global Memories",
) -> str:
    """Read selected memory files and format for system prompt injection.

    Says how long ago a memory was last confirmed, once that is more than two days.
    """

    mem_dir = memory_dir or _default_global_memory_dir()
    if not filenames:
        return ""

    blocks: list[str] = []
    for fname in filenames:
        path = mem_dir / fname
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8").strip()
            # Get file modification time for age calculation
            mtime = path.stat().st_mtime
            age_note = _format_relative_age(content, mtime)
        except OSError:
            continue

        # Build header with optional age note
        if age_note:
            header = f"### {fname} ({age_note})"
        else:
            header = f"### {fname}"
        blocks.append(f"{header}\n\n{content}")

    if not blocks:
        return ""

    body = "\n\n---\n\n".join(blocks)
    return f"--- {label} ---\n\n{body}\n\n--- End {label} ---"


async def build_scoped_recall_blocks(
    query: str,
    llm: Any,
    *,
    global_memory_dir: Path | None = None,
    queen_memory_dir: Path | None = None,
    queen_id: str | None = None,
    global_max_results: int = 3,
    queen_max_results: int = 3,
) -> tuple[str, str]:
    """Build separate recall blocks for global and queen-scoped memory.

    The two scopes are picked at once: each pick is a model call, and a turn may be waiting on both.
    """
    global_dir = global_memory_dir or _default_global_memory_dir()
    picks = [select_memories(query, llm, memory_dir=global_dir, max_results=global_max_results)]
    if queen_memory_dir is not None:
        picks.append(select_memories(query, llm, memory_dir=queen_memory_dir, max_results=queen_max_results))
    selected = await asyncio.gather(*picks)

    global_block = format_recall_injection(selected[0], memory_dir=global_dir, label="Global Memories")
    queen_block = ""
    if queen_memory_dir is not None:
        queen_label = f"Queen Memories: {queen_id}" if queen_id else "Queen Memories"
        queen_block = format_recall_injection(selected[1], memory_dir=queen_memory_dir, label=queen_label)
    return global_block, queen_block


def memory_index(scopes: Sequence[tuple[str, Path | None]]) -> list[tuple[str, Path, dict[str, str]]]:
    """Every note in each ``(label, directory)`` scope as one manifest line, keyed by filename.

    What :class:`~framework.agent_loop.memory_reminders.MemoryIndexReminderSource` shows her in
    place of a model's pick. Scopes without a directory or a note are left out.
    """
    out: list[tuple[str, Path, dict[str, str]]] = []
    for label, directory in scopes:
        if directory is None:
            continue
        entries = {mf.filename: format_memory_manifest([mf]) for mf in scan_memory_files(directory)}
        if entries:
            out.append((label, directory, entries))
    return out
