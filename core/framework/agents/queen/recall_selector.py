"""Recall selector — pre-turn global memory selection for the queen.

Before each conversation turn the system:
  1. Scans the global memory directory for ``.md`` files (cap: 200).
  2. Reads headers (frontmatter + first 30 lines).
  3. Uses a single LLM call with structured JSON output to pick the ~5
     most relevant memories.
  4. Injects them into the system prompt.

The selector only sees the user's query string — no full conversation
context.  This keeps it cheap and fast.  Errors are caught and return
``[]`` so the main conversation is never blocked.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from framework.agents.queen.queen_memory_v2 import (
    format_memory_manifest,
    global_memory_dir,
    scan_memory_files,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------

RECALL_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "memory_selection",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "selected_memories": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["selected_memories"],
            "additionalProperties": False,
        },
    },
}

# ---------------------------------------------------------------------------
# System prompt
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
    mem_dir = memory_dir or global_memory_dir()
    files = scan_memory_files(mem_dir)
    if not files:
        logger.debug("recall: no memory files found, skipping selection")
        return []

    logger.debug("recall: selecting from %d memories for query: %.100s", len(files), query)
    manifest = format_memory_manifest(files)
    user_msg = f"## User query\n\n{query}\n\n## Available memories\n\n{manifest}"

    try:
        resp = await llm.acomplete(
            messages=[{"role": "user", "content": user_msg}],
            system=SELECT_MEMORIES_SYSTEM_PROMPT,
            max_tokens=512,
            response_format=RECALL_SCHEMA,
        )
        data = json.loads(resp.content)
        selected = data.get("selected_memories", [])
        valid_names = {f.filename for f in files}
        result = [s for s in selected if s in valid_names][:max_results]
        logger.debug("recall: selected %d memories: %s", len(result), result)
        return result
    except Exception:
        logger.debug("recall: memory selection failed, returning []", exc_info=True)
        return []


def format_recall_injection(
    filenames: list[str],
    memory_dir: Path | None = None,
) -> str:
    """Read selected memory files and format for system prompt injection."""
    mem_dir = memory_dir or global_memory_dir()
    if not filenames:
        return ""

    blocks: list[str] = []
    for fname in filenames:
        path = mem_dir / fname
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        blocks.append(f"### {fname}\n\n{content}")

    if not blocks:
        return ""

    body = "\n\n---\n\n".join(blocks)
    return f"--- Global Memories ---\n\n{body}\n\n--- End Global Memories ---"


# ---------------------------------------------------------------------------
# Cache update (called after each queen reflection)
# ---------------------------------------------------------------------------


async def update_recall_cache(
    session_dir: Path,
    llm: Any,
    memory_dir: Path | None = None,
    *,
    cache_setter: Any = None,
) -> None:
    """Update the recall cache for the next turn.

    Reads the latest user message from conversation parts to use as the
    query for memory selection.
    """
    mem_dir = memory_dir or global_memory_dir()

    query = _extract_latest_user_query(session_dir)
    if not query:
        logger.debug("recall: no user query found for cache update")
        return

    logger.debug("recall: updating cache for query: %.100s", query)
    try:
        selected = await select_memories(query, llm, mem_dir)
        injection = format_recall_injection(selected, mem_dir)
        if cache_setter is not None:
            cache_setter(injection)
        logger.debug("recall: cache updated (%d chars injected)", len(injection))
    except Exception:
        logger.debug("recall: cache update failed", exc_info=True)


def _extract_latest_user_query(session_dir: Path) -> str:
    """Read the most recent user message from conversation parts."""
    parts_dir = session_dir / "conversations" / "parts"
    if not parts_dir.is_dir():
        return ""

    part_files = sorted(parts_dir.glob("*.json"), reverse=True)
    for f in part_files[:20]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("role") == "user":
                content = str(data.get("content", "")).strip()
                if content:
                    return content[:1000] if len(content) > 1000 else content
        except (json.JSONDecodeError, OSError):
            continue
    return ""
