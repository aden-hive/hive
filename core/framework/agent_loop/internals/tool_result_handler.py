"""Tool result handling: truncation, spillover, JSON preview, and execution.

Manages tool result size limits, file spillover for large results, and
smart JSON previews.  Also includes transient error classification and
the context-window-exceeded error detector.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
from pathlib import Path
from typing import Any

from framework.llm.provider import ToolResult, ToolUse
from framework.llm.stream_events import ToolCallEvent

logger = logging.getLogger(__name__)

# Pattern for detecting context-window-exceeded errors across LLM providers.
_CONTEXT_TOO_LARGE_RE = re.compile(
    r"context.{0,20}(length|window|limit|size)|"
    r"too.{0,10}(long|large|many.{0,10}tokens)|"
    r"(exceed|exceeds|exceeded).{0,30}(limit|window|context|tokens)|"
    r"maximum.{0,20}token|prompt.{0,20}too.{0,10}long",
    re.IGNORECASE,
)


def is_context_too_large_error(exc: BaseException) -> bool:
    """Detect whether an exception indicates the LLM input was too large."""
    cls = type(exc).__name__
    if "ContextWindow" in cls:
        return True
    return bool(_CONTEXT_TOO_LARGE_RE.search(str(exc)))


def is_transient_error(exc: BaseException) -> bool:
    """Classify whether an exception is transient (retryable) vs permanent.

    Transient: network errors, rate limits, server errors, timeouts.
    Permanent: auth errors, bad requests, context window exceeded.
    """
    try:
        from litellm.exceptions import (
            APIConnectionError,
            BadGatewayError,
            InternalServerError,
            RateLimitError,
            ServiceUnavailableError,
        )

        transient_types: tuple[type[BaseException], ...] = (
            RateLimitError,
            APIConnectionError,
            InternalServerError,
            BadGatewayError,
            ServiceUnavailableError,
            TimeoutError,
            ConnectionError,
            OSError,
        )
    except ImportError:
        transient_types = (TimeoutError, ConnectionError, OSError)

    if isinstance(exc, transient_types):
        return True

    # RuntimeError from StreamErrorEvent with "Stream error:" prefix
    if isinstance(exc, RuntimeError):
        error_str = str(exc).lower()
        transient_keywords = [
            "rate limit",
            "429",
            "timeout",
            "connection",
            "internal server",
            "502",
            "503",
            "504",
            "service unavailable",
            "bad gateway",
            "overloaded",
            "failed to parse tool call",
        ]
        return any(kw in error_str for kw in transient_keywords)

    return False


def extract_json_metadata(parsed: Any, *, _depth: int = 0, _max_depth: int = 3) -> str:
    """Return a concise structural summary of parsed JSON.

    Reports key names, value types, and — crucially — array lengths so
    the LLM knows how much data exists beyond the preview.

    Returns an empty string for simple scalars.
    """
    if _depth >= _max_depth:
        if isinstance(parsed, dict):
            return f"dict with {len(parsed)} keys"
        if isinstance(parsed, list):
            return f"list of {len(parsed)} items"
        return type(parsed).__name__

    if isinstance(parsed, dict):
        if not parsed:
            return "empty dict"
        lines: list[str] = []
        indent = "  " * (_depth + 1)
        for key, value in list(parsed.items())[:20]:
            if isinstance(value, list):
                line = f'{indent}"{key}": list of {len(value)} items'
                if value:
                    first = value[0]
                    if isinstance(first, dict):
                        sample_keys = list(first.keys())[:10]
                        line += f" (each item: dict with keys {sample_keys})"
                    elif isinstance(first, list):
                        line += f" (each item: list of {len(first)} elements)"
                lines.append(line)
            elif isinstance(value, dict):
                child = extract_json_metadata(value, _depth=_depth + 1, _max_depth=_max_depth)
                lines.append(f'{indent}"{key}": {child}')
            else:
                lines.append(f'{indent}"{key}": {type(value).__name__}')
        if len(parsed) > 20:
            lines.append(f"{indent}... and {len(parsed) - 20} more keys")
        return "\n".join(lines)

    if isinstance(parsed, list):
        if not parsed:
            return "empty list"
        desc = f"list of {len(parsed)} items"
        first = parsed[0]
        if isinstance(first, dict):
            sample_keys = list(first.keys())[:10]
            desc += f" (each item: dict with keys {sample_keys})"
        elif isinstance(first, list):
            desc += f" (each item: list of {len(first)} elements)"
        return desc

    return ""


def build_json_preview(parsed: Any, *, max_chars: int = 5000) -> str | None:
    """Build a smart preview of parsed JSON, truncating large arrays.

    Shows first 3 + last 1 items of large arrays with explicit count
    markers so the LLM cannot mistake the preview for the full dataset.

    Returns ``None`` if no truncation was needed (no large arrays).
    """
    _LARGE_ARRAY_THRESHOLD = 10

    def _truncate_arrays(obj: Any) -> tuple[Any, bool]:
        """Return (truncated_copy, was_truncated)."""
        if isinstance(obj, list) and len(obj) > _LARGE_ARRAY_THRESHOLD:
            n = len(obj)
            head = obj[:3]
            tail = obj[-1:]
            marker = f"... ({n - 4} more items omitted, {n} total) ..."
            return head + [marker] + tail, True
        if isinstance(obj, dict):
            changed = False
            out: dict[str, Any] = {}
            for k, v in obj.items():
                new_v, did = _truncate_arrays(v)
                out[k] = new_v
                changed = changed or did
            return (out, True) if changed else (obj, False)
        return obj, False

    preview_obj, was_truncated = _truncate_arrays(parsed)
    if not was_truncated:
        return None  # No large arrays — caller should use raw slicing

    try:
        result = json.dumps(preview_obj, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return None

    if len(result) > max_chars:
        # Even 3+1 items too big — try just 1 item
        def _minimal_arrays(obj: Any) -> Any:
            if isinstance(obj, list) and len(obj) > _LARGE_ARRAY_THRESHOLD:
                n = len(obj)
                return obj[:1] + [f"... ({n - 1} more items omitted, {n} total) ..."]
            if isinstance(obj, dict):
                return {k: _minimal_arrays(v) for k, v in obj.items()}
            return obj

        preview_obj = _minimal_arrays(parsed)
        try:
            result = json.dumps(preview_obj, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            return None
        if len(result) > max_chars:
            result = result[:max_chars] + "…"

    return result


def truncate_tool_result(
    result: ToolResult,
    tool_name: str,
    *,
    max_tool_result_chars: int,
    spillover_dir: str | None,
    next_spill_filename_fn: Any,  # Callable[[str], str]
) -> ToolResult:
    """Persist tool result to file and optionally truncate for context.

    When *spillover_dir* is configured, EVERY non-error tool result is
    written to disk for debugging. The LLM-visible content is then
    shaped to avoid a **poison pattern** that we traced on 2026-04-15
    through a gemini-3.1-pro-preview-customtools queen session: the prior format
    appended ``\\n\\n[Saved to '/abs/path/file.txt']`` after every
    small result, and frontier pattern-matching models (gemini 3.x in
    particular) learned to autocomplete the `[Saved to '...']` trailer
    in their own assistant turns, eventually degenerating into echoing
    the whole tool result instead of deciding what to do next. See
    ``session_20260415_100751_d49f4c28/conversations/parts/0000000056.json``
    for the terminal case where the model's "text" output was the full
    tool_result JSON.

    Rules after the fix:
    - **Small results (≤ limit):** pass content through unchanged. No
      trailer. No annotation. The full content is already in the
      message; the disk copy is for debugging only.
    - **Large results (> limit):** preview + file reference, but
      formatted as plain prose instead of a bracketed ``[...]``
      pattern. Structured JSON metadata ("_saved_to") is embedded
      inside the JSON body when the preview is JSON-shaped so the
      model can locate the full file without seeing a mimicry-prone
      bracket token outside the body.
    - **Errors:** pass through unchanged.
    - **read_file results:** truncate with pagination hint (no re-spill).
    """
    limit = max_tool_result_chars

    # Errors always pass through unchanged
    if result.is_error:
        return result

    # read_file reads FROM spilled files — never re-spill (circular).
    # Just truncate with a pagination hint if the result is too large.
    if tool_name == "read_file":
        if limit <= 0 or len(result.content) <= limit:
            return result  # Small result — pass through as-is
        # Large result — truncate with smart preview
        PREVIEW_CAP = min(5000, max(limit - 500, limit // 2))

        metadata_str = ""
        smart_preview: str | None = None
        try:
            parsed_ld = json.loads(result.content)
            metadata_str = extract_json_metadata(parsed_ld)
            smart_preview = build_json_preview(parsed_ld, max_chars=PREVIEW_CAP)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        if smart_preview is not None:
            preview_block = smart_preview
        else:
            preview_block = result.content[:PREVIEW_CAP] + "…"

        # Prose header (no brackets).
        header = (
            f"Tool `{tool_name}` returned {len(result.content):,} characters "
            f"(too large for context). Use offset_bytes / limit_bytes "
            f"parameters to paginate smaller chunks."
        )
        if metadata_str:
            header += f"\n\nData structure:\n{metadata_str}"
        header += (
            "\n\nWARNING: the preview below is a SAMPLE only — do NOT draw counts, totals, or conclusions from it."
        )

        truncated = f"{header}\n\nPreview (truncated):\n{preview_block}"
        logger.info(
            "%s result truncated: %d → %d chars (use offset/limit to paginate)",
            tool_name,
            len(result.content),
            len(truncated),
        )
        return ToolResult(
            tool_use_id=result.tool_use_id,
            content=truncated,
            is_error=False,
            image_content=result.image_content,
            is_skill_content=result.is_skill_content,
        )

    spill_dir = spillover_dir
    if spill_dir:
        spill_path = Path(spill_dir)
        spill_path.mkdir(parents=True, exist_ok=True)
        filename = next_spill_filename_fn(tool_name)

        # Pretty-print JSON content so read_file's line-based
        # pagination works correctly.
        write_content = result.content
        parsed_json: Any = None  # track for metadata extraction
        try:
            parsed_json = json.loads(result.content)
            write_content = json.dumps(parsed_json, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass  # Not JSON — write as-is

        file_path = spill_path / filename
        file_path.write_text(write_content, encoding="utf-8")
        # Use absolute path so parent agents can find files from subagents
        abs_path = str(file_path.resolve())

        if limit > 0 and len(result.content) > limit:
            # Large result: build a small, metadata-rich preview so the
            # LLM cannot mistake it for the complete dataset. The
            # preview is introduced as plain prose (no bracketed
            # ``[Result from …]`` token) so it doesn't prime the model
            # to autocomplete the same pattern in its next turn.
            PREVIEW_CAP = 5000

            # Extract structural metadata (array lengths, key names)
            metadata_str = ""
            smart_preview: str | None = None
            if parsed_json is not None:
                metadata_str = extract_json_metadata(parsed_json)
                smart_preview = build_json_preview(parsed_json, max_chars=PREVIEW_CAP)

            if smart_preview is not None:
                preview_block = smart_preview
            else:
                preview_block = result.content[:PREVIEW_CAP] + "…"

            # Prose header (no brackets). Absolute path still surfaced
            # so the agent can read the full file, but it's framed as
            # a sentence, not a bracketed trailer.
            header = (
                f"Tool `{tool_name}` returned {len(result.content):,} characters "
                f"(too large for context). Full result saved at: {abs_path}\n"
                f"Read the complete data with read_file(path='{abs_path}').\n"
            )
            if metadata_str:
                header += f"\nData structure:\n{metadata_str}\n"
            header += (
                "\nWARNING: the preview below is a SAMPLE only — do NOT draw counts, totals, or conclusions from it."
            )

            content = f"{header}\n\nPreview (truncated):\n{preview_block}"
            logger.info(
                "Tool result spilled to file: %s (%d chars → %s)",
                tool_name,
                len(result.content),
                abs_path,
            )
        else:
            # Small result: pass content through UNCHANGED.
            #
            # The prior design appended `\n\n[Saved to '/abs/path']`
            # after every small result so the agent could re-read the
            # file later. But (a) the full content is already in the
            # message, so there's nothing to re-read; (b) the
            # `[Saved to '…']` trailer is a repeating token pattern
            # that frontier pattern-matching models autocomplete into
            # their own assistant turns, eventually echoing whole tool
            # results as "text" instead of making decisions. Dropping
            # the trailer entirely kills the poison pattern. Spilled
            # files on disk still exist for debugging — they just
            # aren't advertised in the LLM-visible message.
            content = result.content
            logger.info(
                "Tool result saved to file: %s (%d chars → %s, no trailer)",
                tool_name,
                len(result.content),
                filename,
            )

        return ToolResult(
            tool_use_id=result.tool_use_id,
            content=content,
            is_error=False,
            image_content=result.image_content,
            is_skill_content=result.is_skill_content,
        )

    # No spillover_dir — truncate in-place if needed
    if limit > 0 and len(result.content) > limit:
        PREVIEW_CAP = min(5000, max(limit - 500, limit // 2))

        metadata_str = ""
        smart_preview: str | None = None
        try:
            parsed_inline = json.loads(result.content)
            metadata_str = extract_json_metadata(parsed_inline)
            smart_preview = build_json_preview(parsed_inline, max_chars=PREVIEW_CAP)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        if smart_preview is not None:
            preview_block = smart_preview
        else:
            preview_block = result.content[:PREVIEW_CAP] + "…"

        # Prose header (no brackets) — see docstring for the poison
        # pattern that the bracket format triggered.
        header = (
            f"Tool `{tool_name}` returned {len(result.content):,} characters "
            f"(truncated to fit context budget — no spillover dir configured)."
        )
        if metadata_str:
            header += f"\n\nData structure:\n{metadata_str}"
        header += (
            "\n\nWARNING: the preview below is a SAMPLE only — do NOT draw counts, totals, or conclusions from it."
        )

        truncated = f"{header}\n\n{preview_block}"
        logger.info(
            "Tool result truncated in-place: %s (%d → %d chars)",
            tool_name,
            len(result.content),
            len(truncated),
        )
        return ToolResult(
            tool_use_id=result.tool_use_id,
            content=truncated,
            is_error=False,
            image_content=result.image_content,
            is_skill_content=result.is_skill_content,
        )

    return result


async def execute_tool(
    tool_executor: Any,  # Callable[[ToolUse], ToolResult | Awaitable[ToolResult]] | None
    tc: ToolCallEvent,
    timeout: float,
    skill_dirs: list[str] | None = None,
) -> ToolResult:
    """Execute a tool call, handling both sync and async executors.

    Applies ``tool_call_timeout_seconds`` to prevent hung MCP servers
    from blocking the event loop indefinitely.  The initial executor
    call is offloaded to a thread pool so that sync executors don't
    freeze the event loop.
    """
    if tool_executor is None:
        return ToolResult(
            tool_use_id=tc.tool_use_id,
            content=f"No tool executor configured for '{tc.tool_name}'",
            is_error=True,
        )

    skill_dirs = skill_dirs or []
    skill_read_tools = {"view_file", "read_file"}
    if tc.tool_name in skill_read_tools and skill_dirs:
        raw_path = tc.tool_input.get("path", "")
        if raw_path:
            resolved = Path(raw_path).resolve(strict=False)
            resolved_roots = [Path(skill_dir).resolve(strict=False) for skill_dir in skill_dirs]
            if any(resolved.is_relative_to(root) for root in resolved_roots):
                try:
                    content = resolved.read_text(encoding="utf-8")
                except Exception as exc:
                    return ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content=f"Could not read skill resource '{raw_path}': {exc}",
                        is_error=True,
                    )
                return ToolResult(
                    tool_use_id=tc.tool_use_id,
                    content=content,
                    is_skill_content=resolved.name == "SKILL.md",
                )

    tool_use = ToolUse(id=tc.tool_use_id, name=tc.tool_name, input=tc.tool_input)

    async def _run() -> ToolResult:
        # Offload the executor call to a thread.  Sync MCP executors
        # block on future.result() — running in a thread keeps the
        # event loop free so asyncio.wait_for can fire the timeout.
        # Copy the current context so contextvars (e.g. data_dir from
        # execution context) propagate into the worker thread.
        loop = asyncio.get_running_loop()
        ctx = contextvars.copy_context()
        result = await loop.run_in_executor(None, ctx.run, tool_executor, tool_use)
        # Async executors return a coroutine — await it on the loop
        if asyncio.iscoroutine(result) or asyncio.isfuture(result):
            result = await result
        return result

    try:
        if timeout > 0:
            result = await asyncio.wait_for(_run(), timeout=timeout)
        else:
            result = await _run()
    except TimeoutError:
        logger.warning("Tool '%s' timed out after %.0fs", tc.tool_name, timeout)
        # asyncio.wait_for cancels the awaiting coroutine, but the sync
        # executor running inside run_in_executor keeps going — and so
        # does any MCP subprocess it is blocked on. Reach through to the
        # owning MCPClient and force-disconnect it so the subprocess is
        # torn down. Next call_tool triggers a reconnect. Without this
        # the executor thread and MCP child leak on every timeout.
        kill_for_tool = getattr(tool_executor, "kill_for_tool", None)
        if callable(kill_for_tool):
            try:
                await asyncio.to_thread(kill_for_tool, tc.tool_name)
            except Exception as exc:  # defensive — never let cleanup crash the loop
                logger.warning(
                    "kill_for_tool('%s') raised during timeout handling: %s",
                    tc.tool_name,
                    exc,
                )
        return ToolResult(
            tool_use_id=tc.tool_use_id,
            content=(
                f"Tool '{tc.tool_name}' timed out after {timeout:.0f}s. "
                "The operation took too long and was cancelled. "
                "Try a simpler request or a different approach."
            ),
            is_error=True,
        )
    return result


def restore_spill_counter(spillover_dir: str | None) -> int:
    """Scan spillover_dir for existing spill files and return the max counter.

    Returns the highest spill number found (or 0 if none).
    """
    if not spillover_dir:
        return 0
    spill_path = Path(spillover_dir)
    if not spill_path.is_dir():
        return 0
    max_n = 0
    for f in spill_path.iterdir():
        if not f.is_file():
            continue
        m = re.search(r"_(\d+)\.txt$", f.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n
