"""Reflection agent — background global memory extraction for the queen.

A lightweight side agent that runs after each queen LLM turn.  It inspects
recent conversation messages and extracts durable user knowledge into
individual memory files in ``~/.hive/queen/global_memory/``.

Two reflection types:
  - **Short reflection**: after conversational queen turns.  Distills
    learnings about the user (profile, preferences, environment, feedback).
  - **Long reflection**: every 5 short reflections and on CONTEXT_COMPACTED.
    Organises, deduplicates, trims the global memory directory.

Concurrency: an ``asyncio.Lock`` prevents overlapping runs.  If a trigger
fires while a reflection is already active the event is skipped.

All reflections are fire-and-forget (spawned via ``asyncio.create_task``)
so they never block the queen's event loop.
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
    GLOBAL_MEMORY_CATEGORIES,
    MAX_FILE_SIZE_BYTES,
    MAX_FILES,
    format_memory_manifest,
    global_memory_dir,
    parse_frontmatter,
    scan_memory_files,
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
            "List all memory files with their type, name, and description. "
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
        # Enforce global memory type restrictions.
        fm = parse_frontmatter(content)
        mem_type = (fm.get("type") or "").strip().lower()
        if mem_type and mem_type not in GLOBAL_MEMORY_CATEGORIES:
            return (
                f"ERROR: Invalid memory type '{mem_type}'. "
                f"Allowed types: {', '.join(GLOBAL_MEMORY_CATEGORIES)}."
            )
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
) -> tuple[bool, list[str], str]:
    """Run a mini tool-use loop: LLM → tool calls → repeat.

    Returns (success, changed_files, last_text).
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]
    changed_files: list[str] = []
    last_text: str = ""

    for _turn in range(max_turns):
        logger.info("reflect: loop turn %d/%d (msgs=%d)", _turn + 1, max_turns, len(messages))
        try:
            resp: LLMResponse = await llm.acomplete(
                messages=messages,
                system=system,
                tools=_REFLECTION_TOOLS,
                max_tokens=2048,
            )
        except asyncio.CancelledError:
            logger.warning("reflect: LLM call cancelled (task cancelled)")
            return False, changed_files, last_text
        except Exception:
            logger.warning("reflect: LLM call failed", exc_info=True)
            return False, changed_files, last_text

        # Extract tool calls from litellm/OpenAI response object.
        tool_calls_raw: list[dict[str, Any]] = []
        raw = resp.raw_response
        if raw is not None:
            # litellm returns a ModelResponse object; tool calls live on
            # choices[0].message.tool_calls as a list of ChatCompletionMessageToolCall.
            try:
                msg_obj = raw.choices[0].message
                if hasattr(msg_obj, "tool_calls") and msg_obj.tool_calls:
                    for tc in msg_obj.tool_calls:
                        fn = tc.function
                        try:
                            args = json.loads(fn.arguments) if fn.arguments else {}
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                        tool_calls_raw.append(
                            {
                                "id": tc.id,
                                "name": fn.name,
                                "input": args,
                            }
                        )
            except (AttributeError, IndexError):
                pass

        logger.info(
            "reflect: LLM responded, text=%d chars, tool_calls=%d",
            len(resp.content or ""),
            len(tool_calls_raw),
        )

        turn_text = resp.content or ""
        if turn_text:
            last_text = turn_text
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": turn_text}
        if tool_calls_raw:
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

        if not tool_calls_raw:
            break

        for tc in tool_calls_raw:
            result = _execute_tool(tc["name"], tc.get("input", {}), memory_dir)
            if tc["name"] in ("write_memory_file", "delete_memory_file"):
                fname = tc.get("input", {}).get("filename", "")
                if fname and not result.startswith("ERROR"):
                    changed_files.append(fname)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

    return True, changed_files, last_text


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_CATEGORIES_STR = ", ".join(GLOBAL_MEMORY_CATEGORIES)

_SHORT_REFLECT_SYSTEM = f"""\
You are a reflection agent that distills durable knowledge about the USER
into persistent global memory files.  You run in the background after each
assistant turn.

Your goal: identify anything from the recent messages worth remembering
about the user across ALL future sessions — their profile, preferences,
environment setup, or feedback on assistant behavior.

Memory categories: {_CATEGORIES_STR}

Expected format for each memory file:
```markdown
---
name: {{{{memory name}}}}
description: {{{{one-line description — specific and search-friendly}}}}
type: {{{{{_CATEGORIES_STR}}}}}
---

{{{{memory content}}}}
```

Workflow (aim for 2 turns):
  Turn 1 — call list_memory_files to see what exists, then read_memory_file
            for any that might need updating.
  Turn 2 — call write_memory_file for new/updated memories.

Rules:
- ONLY persist durable knowledge about the USER — who they are, how they
  like to work, their tech environment, their feedback on your behavior.
- Do NOT store task-specific details, code patterns, file paths, or
  ephemeral session state.
- Keep files concise.  Each file should cover ONE topic.
- If an existing memory already covers the learning, UPDATE it rather than
  creating a duplicate.
- If there is nothing worth remembering, do nothing (respond with a brief
  reason — no tool calls needed).
- File names should be kebab-case slugs ending in .md.
- Do NOT exceed {MAX_FILE_SIZE_BYTES} bytes per file or {MAX_FILES} total files.
"""

_LONG_REFLECT_SYSTEM = f"""\
You are a reflection agent performing a periodic housekeeping pass over the
global memory directory.  Your job is to organise, deduplicate, and trim
noise from the accumulated memory files.

Memory categories: {_CATEGORIES_STR}

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


async def _read_conversation_parts(session_dir: Path) -> list[dict[str, Any]]:
    """Read conversation parts from the queen session directory."""
    from framework.storage.conversation_store import FileConversationStore

    store = FileConversationStore(session_dir / "conversations")
    return await store.read_parts()


async def run_short_reflection(
    session_dir: Path,
    llm: Any,
    memory_dir: Path | None = None,
) -> None:
    """Run a short reflection: extract user knowledge from conversation."""
    logger.info("reflect: starting short reflection for %s", session_dir)
    mem_dir = memory_dir or global_memory_dir()

    messages = await _read_conversation_parts(session_dir)
    if not messages:
        logger.info("reflect: no conversation parts found in %s, skipping", session_dir)
        return

    transcript_lines: list[str] = []
    for msg in messages[-50:]:
        role = msg.get("role", "")
        content = str(msg.get("content", "")).strip()
        if role == "tool" or not content:
            continue
        label = "user" if role == "user" else "assistant"
        if len(content) > 800:
            content = content[:800] + "…"
        transcript_lines.append(f"[{label}]: {content}")

    if not transcript_lines:
        logger.info("reflect: no transcript lines after filtering, skipping")
        return

    transcript = "\n".join(transcript_lines)
    user_msg = (
        f"## Recent conversation ({len(messages)} messages total)\n\n"
        f"{transcript}\n\n"
        f"Timestamp: {datetime.now().isoformat(timespec='minutes')}"
    )

    _, changed, reason = await _reflection_loop(llm, _SHORT_REFLECT_SYSTEM, user_msg, mem_dir)
    if changed:
        logger.info("reflect: short reflection done, changed files: %s", changed)
    else:
        logger.info("reflect: short reflection done, no changes — %s", reason or "no reason")


async def run_long_reflection(
    llm: Any,
    memory_dir: Path | None = None,
) -> None:
    """Run a long reflection: organise and deduplicate all global memories."""
    logger.debug("reflect: starting long reflection")
    mem_dir = memory_dir or global_memory_dir()
    files = scan_memory_files(mem_dir)

    if not files:
        logger.debug("reflect: no memory files, skipping long reflection")
        return

    manifest = format_memory_manifest(files)
    user_msg = (
        f"## Current memory manifest ({len(files)} files)\n\n"
        f"{manifest}\n\n"
        f"Timestamp: {datetime.now().isoformat(timespec='minutes')}"
    )

    _, changed, reason = await _reflection_loop(llm, _LONG_REFLECT_SYSTEM, user_msg, mem_dir)
    if changed:
        logger.debug("reflect: long reflection done (%d files), changed: %s", len(files), changed)
    else:
        logger.debug(
            "reflect: long reflection done (%d files), no changes — %s",
            len(files),
            reason or "no reason",
        )


async def run_shutdown_reflection(
    session_dir: Path,
    llm: Any,
    memory_dir: Path | None = None,
) -> None:
    """Run a final short reflection on session shutdown.

    Called during session teardown so recent conversation insights are
    persisted before the session is destroyed.
    """
    logger.info("reflect: running shutdown reflection for %s", session_dir)
    mem_dir = memory_dir or global_memory_dir()
    try:
        await run_short_reflection(session_dir, llm, mem_dir)
        logger.info("reflect: shutdown reflection completed for %s", session_dir)
    except asyncio.CancelledError:
        logger.warning("reflect: shutdown reflection cancelled for %s", session_dir)
    except Exception:
        logger.warning("reflect: shutdown reflection failed", exc_info=True)
        _write_error("shutdown reflection")


# ---------------------------------------------------------------------------
# Event-bus integration
# ---------------------------------------------------------------------------

_LONG_REFLECT_INTERVAL = 5


async def subscribe_reflection_triggers(
    event_bus: Any,
    session_dir: Path,
    llm: Any,
    memory_dir: Path | None = None,
) -> list[str]:
    """Subscribe to queen turn events and return subscription IDs.

    Call this once during queen setup.  Returns a list of event-bus
    subscription IDs for cleanup during session teardown.
    """
    from framework.runtime.event_bus import EventType

    mem_dir = memory_dir or global_memory_dir()
    _lock = asyncio.Lock()
    _short_count = 0
    _background_tasks: set[asyncio.Task] = set()

    async def _do_turn_reflect(is_interval: bool, count: int) -> None:
        async with _lock:
            try:
                if is_interval:
                    await run_short_reflection(session_dir, llm, mem_dir)
                    await run_long_reflection(llm, mem_dir)
                else:
                    await run_short_reflection(session_dir, llm, mem_dir)
            except Exception:
                logger.warning("reflect: reflection failed", exc_info=True)
                _write_error("short/long reflection")

    async def _do_compaction_reflect() -> None:
        async with _lock:
            try:
                await run_long_reflection(llm, mem_dir)
            except Exception:
                logger.warning("reflect: compaction-triggered reflection failed", exc_info=True)
                _write_error("compaction reflection")

    def _fire_and_forget(coro: Any) -> None:
        """Spawn a background task and prevent GC before it finishes."""
        task = asyncio.create_task(coro)
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    async def _on_turn_complete(event: Any) -> None:
        nonlocal _short_count

        if getattr(event, "stream_id", None) != "queen":
            return

        _short_count += 1

        event_data = getattr(event, "data", {}) or {}
        stop_reason = event_data.get("stop_reason", "")
        is_tool_turn = stop_reason in ("tool_use", "tool_calls")
        is_interval = _short_count % _LONG_REFLECT_INTERVAL == 0

        if is_tool_turn and not is_interval:
            logger.debug("reflect: skipping tool turn (count=%d)", _short_count)
            return

        if _lock.locked():
            logger.debug("reflect: skipping, already running (count=%d)", _short_count)
            return

        logger.debug(
            "reflect: triggered (count=%d, interval=%s, stop_reason=%s)",
            _short_count,
            is_interval,
            stop_reason,
        )
        _fire_and_forget(_do_turn_reflect(is_interval, _short_count))

    async def _on_compaction(event: Any) -> None:
        if getattr(event, "stream_id", None) != "queen":
            return
        if _lock.locked():
            logger.debug("reflect: skipping compaction trigger, already running")
            return
        logger.debug("reflect: compaction triggered long reflection")
        _fire_and_forget(_do_compaction_reflect())

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
        error_path = global_memory_dir() / ".reflection_error.txt"
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text(
            f"context: {context}\ntime: {datetime.now().isoformat()}\n\n{traceback.format_exc()}",
            encoding="utf-8",
        )
    except OSError:
        pass
