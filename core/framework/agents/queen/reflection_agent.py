"""Reflect agent — background memory extraction after each queen turn.

A lightweight side agent that runs after each queen LLM turn.  It
inspects recent conversation messages (cursor-based incremental
processing) and extracts learnings into individual memory files.

Two reflection types:
  - **Short reflection**: every queen turn. Distills learnings. Nudged
    toward a 2-turn pattern (batch reads → batch writes).
  - **Long reflection**: every 5 short reflections, on CONTEXT_COMPACTED,
    and at session end.  Organises, deduplicates, trims holistically.

The agent has restricted tool access: it can only read/write/delete
memory files in ``~/.hive/queen/memories/`` and list them.

Concurrency: an ``asyncio.Lock`` prevents overlapping runs.  If a
trigger fires while a reflection is already active the event is skipped
(cursor hasn't advanced, so messages will be reconsidered next time).
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from framework.agents.queen.queen_memory_v2 import (
    MAX_FILE_SIZE_BYTES,
    MAX_FILES,
    MEMORY_DIR,
    MEMORY_FRONTMATTER_EXAMPLE,
    MEMORY_TYPES,
    format_memory_manifest,
    read_cursor,
    read_messages_since_cursor,
    scan_memory_files,
    write_cursor,
)
from framework.llm.provider import LLMResponse, Tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reflection tool definitions (internal — not in queen's main registry)
# ---------------------------------------------------------------------------

_REFLECTION_TOOLS: list[Tool] = [
    Tool(
        name="list_memory_files",
        description=(
            "List all memory files with their type, name, age, and description. "
            "Returns a text manifest — one line per file."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    Tool(
        name="read_memory_file",
        description="Read the full content of a memory file by filename.",
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The filename (e.g. 'user-prefers-dark-mode.md').",
                },
            },
            "required": ["filename"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="write_memory_file",
        description=(
            "Create or overwrite a memory file.  Content should include YAML "
            "frontmatter (name, description, type) followed by the memory body.  "
            f"Max file size: {MAX_FILE_SIZE_BYTES} bytes.  Max files: {MAX_FILES}."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Filename ending in .md (e.g. 'user-prefers-dark-mode.md').",
                },
                "content": {
                    "type": "string",
                    "description": "Full file content including frontmatter.",
                },
            },
            "required": ["filename", "content"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="delete_memory_file",
        description=(
            "Delete a memory file by filename.  Use during long "
            "reflection to prune stale or redundant memories."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The filename to delete.",
                },
            },
            "required": ["filename"],
            "additionalProperties": False,
        },
    ),
]


def _safe_memory_path(filename: str, memory_dir: Path) -> Path:
    """Resolve *filename* inside *memory_dir*, raising if it escapes."""
    if not filename or filename.strip() != filename:
        raise ValueError(f"Invalid filename: {filename!r}")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError(f"Invalid filename: path components not allowed: {filename!r}")
    candidate = (memory_dir / filename).resolve()
    root = memory_dir.resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"Path escapes memory directory: {filename!r}")
    return candidate


def _execute_tool(name: str, args: dict[str, Any], memory_dir: Path) -> str:
    """Execute a reflection tool synchronously.  Returns the result string."""
    if name == "list_memory_files":
        files = scan_memory_files(memory_dir)
        logger.debug("reflect: tool list_memory_files → %d files", len(files))
        if not files:
            return "(no memory files yet)"
        return format_memory_manifest(files)

    if name == "read_memory_file":
        filename = args.get("filename", "")
        try:
            path = _safe_memory_path(filename, memory_dir)
        except ValueError as exc:
            return f"ERROR: {exc}"
        if not path.exists() or not path.is_file():
            return f"ERROR: File not found: {filename}"
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            return f"ERROR: {e}"

    if name == "write_memory_file":
        filename = args.get("filename", "")
        content = args.get("content", "")
        if not filename.endswith(".md"):
            return "ERROR: Filename must end with .md"
        # Enforce file size limit.
        if len(content.encode("utf-8")) > MAX_FILE_SIZE_BYTES:
            return f"ERROR: Content exceeds {MAX_FILE_SIZE_BYTES} byte limit."
        # Enforce file cap (only for new files).
        try:
            path = _safe_memory_path(filename, memory_dir)
        except ValueError as exc:
            return f"ERROR: {exc}"
        if not path.exists():
            existing = list(memory_dir.glob("*.md"))
            if len(existing) >= MAX_FILES:
                return f"ERROR: File cap reached ({MAX_FILES}).  Delete a file first."
        memory_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.debug("reflect: tool write_memory_file → %s (%d chars)", filename, len(content))
        return f"Wrote {filename} ({len(content)} chars)."

    if name == "delete_memory_file":
        filename = args.get("filename", "")
        try:
            path = _safe_memory_path(filename, memory_dir)
        except ValueError as exc:
            return f"ERROR: {exc}"
        if not path.exists():
            return f"ERROR: File not found: {filename}"
        path.unlink()
        logger.debug("reflect: tool delete_memory_file → %s", filename)
        return f"Deleted {filename}."

    return f"ERROR: Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Mini event loop
# ---------------------------------------------------------------------------

_MAX_TURNS = 5


async def _reflection_loop(
    llm: Any,
    system: str,
    user_msg: str,
    memory_dir: Path,
    max_turns: int = _MAX_TURNS,
) -> bool:
    """Run a mini tool-use loop: LLM → tool calls → repeat.

    Hard cap of *max_turns* iterations.  Prompt nudges the LLM toward a
    2-turn pattern (batch reads in turn 1, batch writes in turn 2).

    Returns ``True`` if the loop completed without LLM errors, ``False``
    if an LLM call failed (cursor should not advance).
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]
    logger.debug("reflect: starting loop (max %d turns)", max_turns)

    for _turn in range(max_turns):
        try:
            resp: LLMResponse = await llm.acomplete(
                messages=messages,
                system=system,
                tools=_REFLECTION_TOOLS,
                max_tokens=2048,
            )
        except Exception:
            logger.warning("reflect: LLM call failed", exc_info=True)
            return False

        # Build assistant message.
        tool_calls_raw: list[dict[str, Any]] = []
        if resp.raw_response and isinstance(resp.raw_response, dict):
            tool_calls_raw = resp.raw_response.get("tool_calls", [])

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": resp.content or "",
        }
        if tool_calls_raw:
            # Convert to OpenAI format for the conversation.
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("input", {})),
                    },
                }
                for tc in tool_calls_raw
            ]
        messages.append(assistant_msg)

        # No tool calls → agent is done.
        if not tool_calls_raw:
            logger.debug("reflect: loop done after %d turn(s) (no tool calls)", _turn + 1)
            break

        # Execute each tool call and append results.
        logger.debug("reflect: turn %d — executing %d tool call(s): %s", _turn + 1, len(tool_calls_raw), [tc["name"] for tc in tool_calls_raw])
        for tc in tool_calls_raw:
            result = _execute_tool(tc["name"], tc.get("input", {}), memory_dir)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

    return True


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_FRONTMATTER_EXAMPLE = "\n".join(MEMORY_FRONTMATTER_EXAMPLE)

_SHORT_REFLECT_SYSTEM = f"""\
You are a reflection agent that distills learnings from a conversation into
persistent memory files.  You run in the background after each assistant turn.

Your goal: identify anything from the recent messages worth remembering across
future sessions — user preferences, project context, techniques that worked,
goals, environment details, reference pointers.

Memory types: {', '.join(MEMORY_TYPES)}

Expected format for each memory file:
{_FRONTMATTER_EXAMPLE}

Workflow (aim for 2 turns):
  Turn 1 — call list_memory_files to see what already exists, then
            read_memory_file for any that might need updating.
  Turn 2 — call write_memory_file for new/updated memories.

Rules:
- Only persist information that would be useful in a *future* conversation.
  Skip ephemeral task details, routine tool output, and anything obvious
  from the code or git history.
- Keep files concise.  Each file should cover ONE topic.
- If an existing memory already covers the learning, UPDATE it rather than
  creating a duplicate.
- If there is nothing worth remembering from these messages, do nothing
  (just respond with a short note — no tool calls needed).
- File names should be kebab-case slugs ending in .md.
- Include a specific, search-friendly description in the frontmatter.
- Do NOT exceed {MAX_FILE_SIZE_BYTES} bytes per file or {MAX_FILES} total files.
"""

_LONG_REFLECT_SYSTEM = f"""\
You are a reflection agent performing a periodic housekeeping pass over the
memory directory.  Your job is to organise, deduplicate, and trim noise from
the accumulated memory files.

Memory types: {', '.join(MEMORY_TYPES)}

Expected format for each memory file:
{_FRONTMATTER_EXAMPLE}

Workflow:
  1. list_memory_files to get the full manifest.
  2. read_memory_file for files that look redundant, stale, or overlapping.
  3. Merge duplicates, delete stale entries, consolidate related memories.
  4. Ensure descriptions are specific and search-friendly.
  5. Enforce limits: max {MAX_FILES} files, max {MAX_FILE_SIZE_BYTES} bytes each.

Rules:
- Prefer merging over deleting — combine related memories into one file.
- Remove memories that are no longer relevant or are superseded.
- Keep the total collection lean and high-signal.
- Do NOT invent new information — only reorganise what exists.
"""


# ---------------------------------------------------------------------------
# Short & long reflection entry points
# ---------------------------------------------------------------------------


async def run_short_reflection(
    session_dir: Path,
    llm: Any,
    memory_dir: Path | None = None,
) -> None:
    """Run a short reflection: extract learnings from new messages."""
    mem_dir = memory_dir or MEMORY_DIR

    cursor_seq = read_cursor()
    messages, max_seq = read_messages_since_cursor(session_dir, cursor_seq)

    if not messages:
        logger.debug("reflect: short — no new messages since cursor %d", cursor_seq)
        return

    logger.debug("reflect: short — %d new messages (cursor %d → %d)", len(messages), cursor_seq, max_seq)

    # Build a readable transcript of the new messages.
    transcript_lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "")
        content = str(msg.get("content", "")).strip()
        if role == "tool":
            continue  # Skip verbose tool results.
        if not content:
            continue
        label = "user" if role == "user" else "assistant"
        # Truncate very long messages.
        if len(content) > 800:
            content = content[:800] + "…"
        transcript_lines.append(f"[{label}]: {content}")

    if not transcript_lines:
        # Only tool results in the new messages — still advance cursor.
        write_cursor(max_seq)
        return

    transcript = "\n".join(transcript_lines)
    user_msg = (
        f"## Recent conversation (messages {cursor_seq + 1}–{max_seq})\n\n"
        f"{transcript}\n\n"
        f"Timestamp: {datetime.now().isoformat(timespec='minutes')}"
    )

    success = await _reflection_loop(llm, _SHORT_REFLECT_SYSTEM, user_msg, mem_dir)

    # Advance cursor only on success.
    if success:
        write_cursor(max_seq)
        logger.debug("reflect: short reflection done, cursor → %d", max_seq)
    else:
        logger.warning("reflect: short reflection failed, cursor NOT advanced (stays at %d)", cursor_seq)


async def run_long_reflection(
    llm: Any,
    memory_dir: Path | None = None,
) -> None:
    """Run a long reflection: organise and deduplicate all memories."""
    mem_dir = memory_dir or MEMORY_DIR
    files = scan_memory_files(mem_dir)

    if not files:
        logger.debug("reflect: long — no memory files to organise")
        return

    logger.debug("reflect: long — organising %d memory files", len(files))
    manifest = format_memory_manifest(files)
    user_msg = (
        f"## Current memory manifest ({len(files)} files)\n\n"
        f"{manifest}\n\n"
        f"Timestamp: {datetime.now().isoformat(timespec='minutes')}"
    )

    await _reflection_loop(llm, _LONG_REFLECT_SYSTEM, user_msg, mem_dir)
    logger.debug("reflect: long reflection done (%d files)", len(files))


# ---------------------------------------------------------------------------
# Event-bus integration
# ---------------------------------------------------------------------------

# Run a long reflection every N short reflections.
_LONG_REFLECT_INTERVAL = 5


async def subscribe_reflection_triggers(
    event_bus: Any,
    session_dir: Path,
    llm: Any,
    memory_dir: Path | None = None,
    phase_state: Any = None,
) -> list[str]:
    """Subscribe to queen turn events and return subscription IDs.

    Call this once during queen setup.  Returns a list of event-bus
    subscription IDs for cleanup during session teardown.
    """
    from framework.runtime.event_bus import EventType

    mem_dir = memory_dir or MEMORY_DIR
    _lock = asyncio.Lock()
    _short_count = 0

    async def _on_turn_complete(event: Any) -> None:
        nonlocal _short_count

        # Only process queen turns.
        if getattr(event, "stream_id", None) != "queen":
            return

        if _lock.locked():
            logger.debug("reflect: skipping — reflection already in progress")
            return

        async with _lock:
            try:
                _short_count += 1
                logger.debug("reflect: turn complete — short count %d/%d", _short_count, _LONG_REFLECT_INTERVAL)
                if _short_count % _LONG_REFLECT_INTERVAL == 0:
                    await run_short_reflection(session_dir, llm, mem_dir)
                    await run_long_reflection(llm, mem_dir)
                else:
                    await run_short_reflection(session_dir, llm, mem_dir)
            except Exception:
                logger.warning("reflect: reflection failed", exc_info=True)
                _write_error("short/long reflection")

            # Update recall cache after reflection completes, guaranteeing
            # recall sees the current turn's extracted memories.
            if phase_state is not None:
                try:
                    from framework.agents.queen.recall_selector import update_recall_cache
                    await update_recall_cache(session_dir, llm, phase_state)
                except Exception:
                    logger.debug("recall: cache update failed", exc_info=True)

    async def _on_compaction(event: Any) -> None:
        if getattr(event, "stream_id", None) != "queen":
            return

        if _lock.locked():
            return

        async with _lock:
            try:
                await run_long_reflection(llm, mem_dir)
            except Exception:
                logger.warning("reflect: compaction-triggered reflection failed", exc_info=True)
                _write_error("compaction reflection")

    sub_ids: list[str] = []

    sub1 = event_bus.subscribe(
        event_types=[EventType.LLM_TURN_COMPLETE],
        handler=_on_turn_complete,
    )
    sub_ids.append(sub1)

    sub2 = event_bus.subscribe(
        event_types=[EventType.CONTEXT_COMPACTED],
        handler=_on_compaction,
    )
    sub_ids.append(sub2)

    return sub_ids


def _write_error(context: str) -> None:
    """Best-effort write of the last traceback to an error file."""
    try:
        error_path = MEMORY_DIR / ".reflection_error.txt"
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text(
            f"context: {context}\ntime: {datetime.now().isoformat()}\n\n{traceback.format_exc()}",
            encoding="utf-8",
        )
    except OSError:
        pass
