"""Tools for the queen to read and write episodic memory.

The queen can consciously record significant moments during a session — like
writing in a diary — and recall past diary entries when needed. Semantic
memory (MEMORY.md) is updated automatically at session end and is never
written by the queen directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from framework.runner.tool_registry import ToolRegistry


def write_to_diary(entry: str) -> str:
    """Write a prose entry to today's episodic memory.

    Use this when something significant just happened: a pipeline went live, the
    user shared an important preference, a goal was achieved or abandoned, or
    you want to record something that should be remembered across sessions.

    Write in first person, as you would in a private diary. Be specific — what
    happened, how the user responded, what it means going forward. One or two
    paragraphs is enough.

    You do not need to include a timestamp or date heading; those are added
    automatically.
    """
    from framework.agents.queen.queen_memory import append_episodic_entry

    append_episodic_entry(entry)
    return "Diary entry recorded."


async def recall_diary(query: str = "", days_back: int = 7) -> str:
    """Search recent diary entries (episodic memory).

    Use this when the user asks about what happened in the past — "what did we
    do yesterday?", "what happened last week?", "remind me about the pipeline
    issue", etc. Also use it proactively when you need context from recent
    sessions to answer a question or make a decision.

    Args:
        query: Optional keyword or phrase to filter entries. If empty, all
            recent entries are returned.
        days_back: How many days to look back (1-30). Defaults to 7.
    """
    from datetime import date, timedelta

    from framework.agents.queen.queen_memory import read_episodic_memory
    from framework.agents.queen.queen_memory_index import (
        embeddings_enabled,
        hybrid_search,
        load_index,
        record_retrieval,
        resolve_prose,
        semantic_search,
    )

    days_back = max(1, min(days_back, 30))
    today = date.today()
    char_budget = 12_000

    # ------------------------------------------------------------------
    # Semantic path — used when embedding model is configured and query given
    # ------------------------------------------------------------------
    if query and embeddings_enabled():
        logger.info("queen_memory: semantic recall — query=%r days_back=%d", query, days_back)
        oldest = (today - timedelta(days=days_back - 1)).strftime("%Y-%m-%d")
        newest = today.strftime("%Y-%m-%d")

        index = load_index()
        sem_results = await semantic_search(
            query, index, k=30, date_range=(oldest, newest)
        )

        if sem_results:
            sem_scores = dict(sem_results)
            candidate_ids = [eid for eid, _ in sem_results]
            ranked = hybrid_search(query, index, candidate_ids, sem_scores)

            results: list[str] = []
            total_chars = 0
            returned_ids: list[str] = []

            for entry_id, _score in ranked:
                date_str, ts = entry_id.split(":", 1)
                prose = resolve_prose(entry_id)
                if not prose:
                    continue

                # Format label from date_str
                try:
                    y, m, d_int = map(int, date_str.split("-"))
                    d = date(y, m, d_int)
                    label = d.strftime("%B %-d, %Y")
                    if d == today:
                        label = f"Today — {label}"
                except ValueError:
                    label = date_str

                section = f"## {label} ({ts})\n\n{prose}"

                # Also include linked neighbours (Phase 3 expansion)
                raw = index.get("entries", {}).get(entry_id, {})
                related_prose_parts: list[str] = []
                for related_id in raw.get("related", [])[:2]:
                    if related_id in (eid for eid, _ in ranked):
                        continue  # will appear in main results
                    rp = resolve_prose(related_id)
                    if rp:
                        r_date_str, r_ts = related_id.split(":", 1)
                        try:
                            ry, rm, rd = map(int, r_date_str.split("-"))
                            r_label = date(ry, rm, rd).strftime("%B %-d, %Y")
                        except ValueError:
                            r_label = r_date_str
                        related_prose_parts.append(
                            f"_Related ({r_label} {r_ts}):_ {rp[:300]}"
                        )
                if related_prose_parts:
                    section += "\n\n" + "\n\n".join(related_prose_parts)

                if total_chars + len(section) > char_budget:
                    remaining = char_budget - total_chars
                    if remaining > 200:
                        section = section[: remaining - 100] + "\n\n…(truncated)"
                        results.append(section)
                        returned_ids.append(entry_id)
                    break
                results.append(section)
                returned_ids.append(entry_id)
                total_chars += len(section)

            if results:
                record_retrieval(index, returned_ids)
                return "\n\n---\n\n".join(results)
            # Fall through to substring if semantic found nothing useful

    # ------------------------------------------------------------------
    # Substring fallback — original behaviour, unchanged
    # ------------------------------------------------------------------
    results_fb: list[str] = []
    total_chars_fb = 0

    for offset in range(days_back):
        d = today - timedelta(days=offset)
        content = read_episodic_memory(d)
        if not content:
            continue
        if query:
            sections = content.split("### ")
            matched = [s for s in sections if query.lower() in s.lower()]
            if not matched:
                continue
            content = "### ".join(matched)
        label = d.strftime("%B %-d, %Y")
        if d == today:
            label = f"Today — {label}"
        entry = f"## {label}\n\n{content}"
        if total_chars_fb + len(entry) > char_budget:
            remaining = char_budget - total_chars_fb
            if remaining > 200:
                trimmed = content[: remaining - 100] + "\n\n…(truncated)"
                results_fb.append(f"## {label}\n\n{trimmed}")
            else:
                results_fb.append(f"## {label}\n\n(truncated — hit size limit)")
            break
        results_fb.append(entry)
        total_chars_fb += len(entry)

    if not results_fb:
        if query:
            return f"No diary entries matching '{query}' in the last {days_back} days."
        return f"No diary entries found in the last {days_back} days."

    return "\n\n---\n\n".join(results_fb)


def register_queen_memory_tools(registry: ToolRegistry) -> None:
    """Register the episodic memory tools into the queen's tool registry."""
    registry.register_function(write_to_diary)
    registry.register_function(recall_diary)
