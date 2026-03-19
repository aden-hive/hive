"""Tools for the queen to read and write episodic memory.

The queen can consciously record significant moments during a session — like
writing in a diary — and recall past diary entries when needed. Semantic
memory (MEMORY.md) is updated automatically at session end and is never
written by the queen directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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


def recall_diary(query: str = "", days_back: int = 7) -> str:
    """Search recent diary entries (episodic memory).

    Use this when the user asks about what happened in the past — "what did we
    do yesterday?", "what happened last week?", "remind me about the pipeline
    issue", etc. Also use it proactively when you need context from recent
    sessions to answer a question or make a decision.

    Args:
        query: Optional keyword or phrase to filter entries. If empty, all
            recent entries are returned.
        days_back: How many days to look back (1–30). Defaults to 7.
    """
    from datetime import date, timedelta

    from framework.agents.queen.queen_memory import read_episodic_memory

    days_back = max(1, min(days_back, 30))
    today = date.today()
    results: list[str] = []
    total_chars = 0
    char_budget = 12_000

    for offset in range(days_back):
        d = today - timedelta(days=offset)
        content = read_episodic_memory(d)
        if not content:
            continue
        # If a query is given, only include entries that mention it
        if query:
            # Check each section (split by ###) for relevance
            sections = content.split("### ")
            matched = [s for s in sections if query.lower() in s.lower()]
            if not matched:
                continue
            content = "### ".join(matched)
        label = d.strftime("%B %-d, %Y")
        if d == today:
            label = f"Today — {label}"
        entry = f"## {label}\n\n{content}"
        if total_chars + len(entry) > char_budget:
            remaining = char_budget - total_chars
            if remaining > 200:
                # Fit a partial entry within budget
                trimmed = content[: remaining - 100] + "\n\n…(truncated)"
                results.append(f"## {label}\n\n{trimmed}")
            else:
                results.append(f"## {label}\n\n(truncated — hit size limit)")
            break
        results.append(entry)
        total_chars += len(entry)

    if not results:
        if query:
            return f"No diary entries matching '{query}' in the last {days_back} days."
        return f"No diary entries found in the last {days_back} days."

    return "\n\n---\n\n".join(results)


def register_queen_memory_tools(registry: ToolRegistry) -> None:
    """Register the episodic memory tools into the queen's tool registry."""
    registry.register_function(write_to_diary)
    registry.register_function(recall_diary)
