"""Reflection agent — background memory extraction for the queen.

A lightweight side agent that runs after each queen LLM turn.  It inspects
recent conversation messages and extracts durable user knowledge into
individual memory files in the configured memory directories.

Two reflection types:
  - **Short reflection**: after conversational queen turns.  Distills
    learnings into either global or queen-scoped memory.
  - **Long reflection**: every 5 short reflections and on CONTEXT_COMPACTED.
    Organises, deduplicates, and trims a memory directory.

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
    global_memory_dir as _default_global_memory_dir,
    parse_frontmatter,
    scan_memory_files,
)
from framework.llm.provider import LLMResponse, Tool
from framework.tracker.llm_debug_logger import log_llm_turn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reflection tool definitions (internal — not in queen's main registry)
# ---------------------------------------------------------------------------

_REFLECTION_TOOLS: list[Tool] = [
    Tool(
        name="list_memory_files",
        description=(
            "List memory files with their type, name, and description. "
            "When scope is omitted, returns all scopes grouped by scope."
        ),
        parameters={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "Optional scope to inspect: 'global' or 'queen'.",
                },
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="read_memory_file",
        description="Read the full content of a memory file by filename from a scope.",
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The filename (e.g. 'user-prefers-dark-mode.md').",
                },
                "scope": {
                    "type": "string",
                    "description": "Memory scope: 'global' or 'queen'. Defaults to 'global'.",
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
                "scope": {
                    "type": "string",
                    "description": "Memory scope: 'global' or 'queen'. Defaults to 'global'.",
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
                "scope": {
                    "type": "string",
                    "description": "Memory scope: 'global' or 'queen'. Defaults to 'global'.",
                },
            },
            "required": ["filename"],
            "additionalProperties": False,
        },
    ),
]


def _normalize_memory_dirs(
    memory_dir: Path | dict[str, Path],
    *,
    queen_memory_dir: Path | None = None,
) -> dict[str, Path]:
    """Normalize memory directory input into a scope -> path mapping."""
    if isinstance(memory_dir, dict):
        return {scope: path for scope, path in memory_dir.items() if path is not None}

    dirs: dict[str, Path] = {"global": memory_dir}
    if queen_memory_dir is not None:
        dirs["queen"] = queen_memory_dir
    return dirs


def _scope_label(scope: str, queen_id: str | None = None) -> str:
    """Human-readable label for a memory scope."""
    if scope == "queen":
        return f"queen ({queen_id})" if queen_id else "queen"
    return scope


def _resolve_memory_scope(args: dict[str, Any], memory_dirs: dict[str, Path]) -> str:
    """Resolve and validate the requested memory scope."""
    raw_scope = args.get("scope")
    if raw_scope is None:
        if len(memory_dirs) == 1:
            return next(iter(memory_dirs))
        scope = "global"
    else:
        scope = str(raw_scope).strip().lower() or "global"
    if scope not in memory_dirs:
        available = ", ".join(sorted(memory_dirs))
        raise ValueError(f"Invalid scope '{scope}'. Available scopes: {available}.")
    return scope


def _format_multi_scope_manifest(
    memory_dirs: dict[str, Path],
    *,
    queen_id: str | None = None,
) -> str:
    """Format a manifest that groups memory files by scope."""
    blocks: list[str] = []
    for scope, memory_dir in memory_dirs.items():
        files = scan_memory_files(memory_dir)
        label = _scope_label(scope, queen_id)
        body = format_memory_manifest(files) if files else "(no memory files yet)"
        blocks.append(f"## Scope: {label}\n\n{body}")
    return "\n\n".join(blocks)


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


def _execute_tool(
    name: str,
    args: dict[str, Any],
    memory_dir: Path | dict[str, Path],
    *,
    queen_id: str | None = None,
) -> str:
    """Execute a reflection tool synchronously.  Returns the result string."""
    memory_dirs = _normalize_memory_dirs(memory_dir)
    if name == "list_memory_files":
        requested_scope = args.get("scope")
        if requested_scope is not None:
            try:
                scope = _resolve_memory_scope(args, memory_dirs)
            except ValueError as exc:
                return f"ERROR: {exc}"
            files = scan_memory_files(memory_dirs[scope])
            logger.debug("reflect: tool list_memory_files[%s] → %d files", scope, len(files))
            if not files:
                return f"(no {scope} memory files yet)"
            return format_memory_manifest(files)
        return _format_multi_scope_manifest(memory_dirs, queen_id=queen_id)

    if name == "read_memory_file":
        filename = args.get("filename", "")
        try:
            scope = _resolve_memory_scope(args, memory_dirs)
        except ValueError as exc:
            return f"ERROR: {exc}"
        try:
            path = _safe_memory_path(filename, memory_dirs[scope])
        except ValueError as exc:
            return f"ERROR: {exc}"
        if not path.exists() or not path.is_file():
            return f"ERROR: File not found in {scope}: {filename}"
        try:
            return path.read_text(encoding="utf-8")
        except OSError as e:
            return f"ERROR: {e}"

    if name == "write_memory_file":
        filename = args.get("filename", "")
        content = args.get("content", "")
        try:
            scope = _resolve_memory_scope(args, memory_dirs)
        except ValueError as exc:
            return f"ERROR: {exc}"
        scope_dir = memory_dirs[scope]
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
            path = _safe_memory_path(filename, scope_dir)
        except ValueError as exc:
            return f"ERROR: {exc}"
        if not path.exists():
            existing = list(scope_dir.glob("*.md"))
            if len(existing) >= MAX_FILES:
                return f"ERROR: File cap reached in {scope} ({MAX_FILES}). Delete a file first."
        scope_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.debug(
            "reflect: tool write_memory_file[%s] → %s (%d chars)",
            scope,
            filename,
            len(content),
        )
        return f"Wrote {scope}:{filename} ({len(content)} chars)."

    if name == "delete_memory_file":
        filename = args.get("filename", "")
        try:
            scope = _resolve_memory_scope(args, memory_dirs)
        except ValueError as exc:
            return f"ERROR: {exc}"
        try:
            path = _safe_memory_path(filename, memory_dirs[scope])
        except ValueError as exc:
            return f"ERROR: {exc}"
        if not path.exists():
            return f"ERROR: File not found in {scope}: {filename}"
        path.unlink()
        logger.debug("reflect: tool delete_memory_file[%s] → %s", scope, filename)
        return f"Deleted {scope}:{filename}."

    return f"ERROR: Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Reflection logging helper
# ---------------------------------------------------------------------------


def _log_reflection_turn(
    *,
    reflection_id: str,
    iteration: int,
    system_prompt: str,
    messages: list[dict[str, Any]],
    assistant_text: str,
    tool_calls: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
    token_counts: dict[str, Any],
) -> None:
    """Log a reflection turn using the same JSONL format as the main agent loop."""
    log_llm_turn(
        node_id="reflection",
        stream_id=reflection_id,
        execution_id=reflection_id,
        iteration=iteration,
        system_prompt=system_prompt,
        messages=messages,
        assistant_text=assistant_text,
        tool_calls=tool_calls,
        tool_results=tool_results,
        token_counts=token_counts,
    )


# ---------------------------------------------------------------------------
# Mini event loop
# ---------------------------------------------------------------------------

_MAX_TURNS = 5


async def _reflection_loop(
    llm: Any,
    system: str,
    user_msg: str,
    memory_dir: Path | dict[str, Path],
    max_turns: int = _MAX_TURNS,
    *,
    queen_id: str | None = None,
) -> tuple[bool, list[str], str]:
    """Run a mini tool-use loop: LLM → tool calls → repeat.

    Returns (success, changed_files, last_text).
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]
    changed_files: list[str] = []
    last_text: str = ""
    reflection_id = f"reflection_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    token_counts: dict[str, Any] = {}
    memory_dirs = _normalize_memory_dirs(memory_dir)

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

        # Capture token counts from the LLM response.
        try:
            raw_usage = getattr(raw, "usage", None) if raw else None
            if raw_usage:
                token_counts = {
                    "model": getattr(raw, "model", ""),
                    "input": getattr(raw_usage, "prompt_tokens", 0) or 0,
                    "output": getattr(raw_usage, "completion_tokens", 0) or 0,
                    "cached": getattr(raw_usage, "prompt_tokens_details", None)
                    and getattr(raw_usage.prompt_tokens_details, "cached_tokens", 0),
                    "stop_reason": getattr(raw.choices[0], "finish_reason", "") if raw else "",
                }
        except Exception:
            token_counts = {}

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

        tool_results: list[dict[str, Any]] = []
        for tc in tool_calls_raw:
            tc_input = tc.get("input", {})
            result = _execute_tool(tc["name"], tc_input, memory_dirs, queen_id=queen_id)
            if tc["name"] in ("write_memory_file", "delete_memory_file"):
                fname = tc_input.get("filename", "")
                try:
                    scope = _resolve_memory_scope(tc_input, memory_dirs)
                except ValueError:
                    scope = str(tc_input.get("scope", "global")).strip().lower() or "global"
                if fname and not result.startswith("ERROR"):
                    changed_files.append(f"{scope}:{fname}")
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            tool_results.append({"tool_call_id": tc["id"], "name": tc["name"], "result": result})

        # Log the reflection turn in the same JSONL format as the main agent loop.
        _log_reflection_turn(
            reflection_id=reflection_id,
            iteration=_turn,
            system_prompt=system,
            messages=messages,
            assistant_text=turn_text,
            tool_calls=tool_calls_raw,
            tool_results=tool_results,
            token_counts=token_counts,
        )

    return True, changed_files, last_text


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_CATEGORIES_STR = ", ".join(GLOBAL_MEMORY_CATEGORIES)


def _build_unified_short_reflect_system(queen_id: str | None = None) -> str:
    """Build the unified short reflection prompt across memory scopes."""
    queen_scope = (
        f"- `queen`: durable learnings specific to how queen '{queen_id}' should work with this user\n"
        if queen_id
        else ""
    )
    return f"""\
You are a reflection agent that distills durable knowledge about the USER
into persistent memory files. You run in the background after each
assistant turn.

Memory categories: {_CATEGORIES_STR}

Available memory scopes:
- `global`: durable user facts that should help every queen in future sessions
{queen_scope}

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
  Turn 1 — call list_memory_files without a scope to inspect all scopes, then
            read_memory_file for any files that might need updating.
  Turn 2 — call write_memory_file / delete_memory_file with an explicit scope.

Rules:
- Make ONE coordinated storage decision per learning.
- Prefer `global` for broad user facts: identity, general preferences, environment,
  and feedback that should help all queens.
- Prefer `queen` only for stable domain-specific learnings about how this queen
  should reason, prioritize, communicate, or make tradeoffs for this user.
- Avoid storing the same fact in both scopes unless the scoped version adds
  genuinely distinct queen-specific nuance. When in doubt, keep only one copy.
- Update existing files instead of creating duplicates when possible.
- If the same learning already exists in the wrong scope or both scopes,
  you may update one file and delete the redundant one.
- Do NOT store task-specific details, code patterns, file paths, or ephemeral
  session state.
- Keep files concise. Each file should cover ONE topic.
- If there is nothing worth remembering, do nothing (respond with a brief
  reason — no tool calls needed).
- File names should be kebab-case slugs ending in .md.
- For user identity/profile information about the human user (name, role,
  background), ALWAYS use the canonical filename 'user-profile.md' in the
  `global` scope. This is the single source of truth for user profile data,
  shared with the settings UI.
- When updating `global:user-profile.md`, preserve the '## User Identity'
  section — it is managed by the settings UI. Never describe the assistant,
  queen, or agent as the identity in this file. Add/update other sections
  below it.
- Do NOT exceed {MAX_FILE_SIZE_BYTES} bytes per file or {MAX_FILES} total files per scope.
"""


def _build_unified_long_reflect_system(queen_id: str | None = None) -> str:
    """Build the unified housekeeping prompt across memory scopes."""
    queen_scope = (
        f"- `queen`: memories specific to how queen '{queen_id}' should work with this user\n"
        if queen_id
        else ""
    )
    return f"""\
You are a reflection agent performing a periodic housekeeping pass over the
memory system for this user.

Memory categories: {_CATEGORIES_STR}

Available memory scopes:
- `global`: facts useful to every queen
{queen_scope}

Workflow:
  1. Call list_memory_files without a scope to inspect all scopes together.
  2. Read files that look redundant, stale, overlapping, or misplaced.
  3. Merge duplicates, move memories to the correct scope, and delete
     redundant copies when appropriate.
  4. Ensure descriptions are specific and search-friendly.
  5. Enforce limits: max {MAX_FILES} files and {MAX_FILE_SIZE_BYTES} bytes per file in each scope.

Rules:
- Treat deduplication across scopes as part of the job, not just within a scope.
- Prefer `global` for broad durable user facts and `queen` for queen-specific nuance.
- If two files store materially the same fact, keep the best one and delete or
  rewrite the redundant one.
- Prefer merging over deleting when the memories contain complementary signal.
- Remove memories that are stale, superseded, or misplaced.
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
    """Run a global-only short reflection (compatibility wrapper)."""
    logger.info("reflect: starting global short reflection for %s", session_dir)
    mem_dir = memory_dir or _default_global_memory_dir()
    await _run_short_reflection_with_prompt(
        session_dir,
        llm,
        mem_dir,
        system_prompt=_build_unified_short_reflect_system(),
        log_label="global",
        queen_id=None,
    )


async def run_queen_short_reflection(
    session_dir: Path,
    llm: Any,
    queen_id: str,
    memory_dir: Path,
) -> None:
    """Run a queen-only short reflection (compatibility wrapper)."""
    logger.info("reflect: starting queen short reflection for %s (%s)", session_dir, queen_id)
    await _run_short_reflection_with_prompt(
        session_dir,
        llm,
        {"queen": memory_dir},
        system_prompt=_build_unified_short_reflect_system(queen_id),
        log_label=f"queen:{queen_id}",
        queen_id=queen_id,
    )


async def run_unified_short_reflection(
    session_dir: Path,
    llm: Any,
    *,
    global_memory_dir: Path | None = None,
    queen_memory_dir: Path | None = None,
    queen_id: str | None = None,
) -> None:
    """Run one short reflection loop over all active memory scopes."""
    global_dir = global_memory_dir or _default_global_memory_dir()
    memory_dirs = {"global": global_dir}
    if queen_memory_dir is not None and queen_id:
        memory_dirs["queen"] = queen_memory_dir

    logger.info(
        "reflect: starting unified short reflection for %s (scopes=%s)",
        session_dir,
        sorted(memory_dirs),
    )
    await _run_short_reflection_with_prompt(
        session_dir,
        llm,
        memory_dirs,
        system_prompt=_build_unified_short_reflect_system(
            queen_id if "queen" in memory_dirs else None
        ),
        log_label="unified",
        queen_id=queen_id if "queen" in memory_dirs else None,
    )


async def _run_short_reflection_with_prompt(
    session_dir: Path,
    llm: Any,
    memory_dir: Path | dict[str, Path],
    *,
    system_prompt: str,
    log_label: str,
    queen_id: str | None,
) -> None:
    """Run a short reflection with a scope-specific system prompt."""
    mem_dir = memory_dir

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

    _, changed, reason = await _reflection_loop(
        llm,
        system_prompt,
        user_msg,
        mem_dir,
        queen_id=queen_id,
    )
    if changed:
        logger.info("reflect: %s short reflection done, changed files: %s", log_label, changed)
    else:
        logger.info(
            "reflect: %s short reflection done, no changes — %s",
            log_label,
            reason or "no reason",
        )


async def run_long_reflection(
    llm: Any,
    memory_dir: Path | None = None,
    *,
    scope_label: str = "global",
) -> None:
    """Run a single-scope long reflection (compatibility wrapper)."""
    logger.debug("reflect: starting long reflection for %s", scope_label)
    mem_dir = memory_dir or _default_global_memory_dir()
    files = scan_memory_files(mem_dir)

    if not files:
        logger.debug("reflect: no %s memory files, skipping long reflection", scope_label)
        return

    manifest = format_memory_manifest(files)
    user_msg = (
        f"## Current memory manifest ({len(files)} files)\n\n"
        f"{manifest}\n\n"
        f"Timestamp: {datetime.now().isoformat(timespec='minutes')}"
    )

    _, changed, reason = await _reflection_loop(
        llm,
        _build_unified_long_reflect_system(),
        user_msg,
        mem_dir,
        queen_id=None,
    )
    if changed:
        logger.debug(
            "reflect: long reflection done for %s (%d files), changed: %s",
            scope_label,
            len(files),
            changed,
        )
    else:
        logger.debug(
            "reflect: long reflection done for %s (%d files), no changes — %s",
            scope_label,
            len(files),
            reason or "no reason",
        )


async def run_unified_long_reflection(
    llm: Any,
    *,
    global_memory_dir: Path | None = None,
    queen_memory_dir: Path | None = None,
    queen_id: str | None = None,
) -> None:
    """Run one housekeeping loop across all active memory scopes."""
    global_dir = global_memory_dir or _default_global_memory_dir()
    memory_dirs = {"global": global_dir}
    if queen_memory_dir is not None and queen_id:
        memory_dirs["queen"] = queen_memory_dir

    manifest = _format_multi_scope_manifest(
        memory_dirs, queen_id=queen_id if "queen" in memory_dirs else None
    )
    user_msg = (
        "## Current memory manifest across scopes\n\n"
        f"{manifest}\n\n"
        f"Timestamp: {datetime.now().isoformat(timespec='minutes')}"
    )

    _, changed, reason = await _reflection_loop(
        llm,
        _build_unified_long_reflect_system(queen_id if "queen" in memory_dirs else None),
        user_msg,
        memory_dirs,
        queen_id=queen_id if "queen" in memory_dirs else None,
    )
    if changed:
        logger.debug("reflect: unified long reflection changed: %s", changed)
    else:
        logger.debug("reflect: unified long reflection no changes — %s", reason or "no reason")


async def run_shutdown_reflection(
    session_dir: Path,
    llm: Any,
    memory_dir: Path | None = None,
    *,
    global_memory_dir_override: Path | None = None,
    queen_memory_dir: Path | None = None,
    queen_id: str | None = None,
) -> None:
    """Run a final short reflection on session shutdown.

    Called during session teardown so recent conversation insights are
    persisted before the session is destroyed.
    """
    logger.info("reflect: running shutdown reflection for %s", session_dir)
    try:
        global_dir = global_memory_dir_override or memory_dir or _default_global_memory_dir()
        await run_unified_short_reflection(
            session_dir,
            llm,
            global_memory_dir=global_dir,
            queen_memory_dir=queen_memory_dir,
            queen_id=queen_id,
        )
        logger.info("reflect: shutdown reflection completed for %s", session_dir)
    except asyncio.CancelledError:
        logger.warning("reflect: shutdown reflection cancelled for %s", session_dir)
    except Exception:
        logger.warning("reflect: shutdown reflection failed", exc_info=True)
        _write_error(
            "shutdown reflection",
            global_memory_dir_override or memory_dir or _default_global_memory_dir(),
        )


# ---------------------------------------------------------------------------
# Event-bus integration
# ---------------------------------------------------------------------------

_LONG_REFLECT_INTERVAL = 5


async def subscribe_reflection_triggers(
    event_bus: Any,
    session_dir: Path,
    llm: Any,
    global_memory_dir: Path | None = None,
    queen_memory_dir: Path | None = None,
    queen_id: str | None = None,
) -> list[str]:
    """Subscribe to queen turn events and return subscription IDs.

    Call this once during queen setup.  Returns a list of event-bus
    subscription IDs for cleanup during session teardown.
    """
    from framework.host.event_bus import EventType

    global_mem_dir = global_memory_dir or _default_global_memory_dir()
    queen_mem_dir = queen_memory_dir
    _lock = asyncio.Lock()
    _short_count = 0
    _background_tasks: set[asyncio.Task] = set()

    async def _run_with_error_capture(coro: Any, *, context: str, memory_dir: Path) -> None:
        try:
            await coro
        except Exception:
            logger.warning("reflect: %s failed", context, exc_info=True)
            _write_error(context, memory_dir)

    async def _do_turn_reflect(is_interval: bool, count: int) -> None:
        async with _lock:
            await _run_with_error_capture(
                run_unified_short_reflection(
                    session_dir,
                    llm,
                    global_memory_dir=global_mem_dir,
                    queen_memory_dir=queen_mem_dir,
                    queen_id=queen_id,
                ),
                context="unified short reflection",
                memory_dir=global_mem_dir,
            )
            if is_interval:
                await _run_with_error_capture(
                    run_unified_long_reflection(
                        llm,
                        global_memory_dir=global_mem_dir,
                        queen_memory_dir=queen_mem_dir,
                        queen_id=queen_id,
                    ),
                    context="unified long reflection",
                    memory_dir=global_mem_dir,
                )

    async def _do_compaction_reflect() -> None:
        async with _lock:
            await _run_with_error_capture(
                run_unified_long_reflection(
                    llm,
                    global_memory_dir=global_mem_dir,
                    queen_memory_dir=queen_mem_dir,
                    queen_id=queen_id,
                ),
                context="unified compaction reflection",
                memory_dir=global_mem_dir,
            )

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


def _write_error(context: str, memory_dir: Path) -> None:
    """Best-effort write of the last traceback to an error file."""
    try:
        error_path = memory_dir / ".reflection_error.txt"
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text(
            f"context: {context}\ntime: {datetime.now().isoformat()}\n\n{traceback.format_exc()}",
            encoding="utf-8",
        )
    except OSError:
        pass
