"""AgentLoop: Multi-turn LLM streaming loop with tool execution and judge evaluation.

Implements AgentProtocol and runs a streaming event loop:
1. Calls LLMProvider.stream() to get streaming events
2. Processes text deltas, tool calls, and finish events
3. Executes tools and feeds results back to the conversation
4. Uses judge evaluation (or implicit stop-reason) to decide loop termination
5. Publishes lifecycle events to EventBus
6. Persists conversation and outputs via write-through to ConversationStore
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from framework.agent_loop.conversation import ConversationStore, NodeConversation
from framework.agent_loop.internals import types as event_loop_types
from framework.agent_loop.internals.compaction import (
    build_llm_compaction_prompt,
    compact,
    format_messages_for_summary,
    llm_compact,
)
from framework.agent_loop.internals.credential_tool import build_credentials_tool
from framework.agent_loop.internals.cursor_persistence import (
    RestoredState,
    check_pause,
    drain_injection_queue,
    drain_trigger_queue,
    restore,
    write_cursor,
)
from framework.agent_loop.internals.event_publishing import (
    log_skip_judge,
    publish_context_usage,
    publish_iteration,
    publish_judge_verdict,
    publish_llm_turn_complete,
    publish_loop_completed,
    publish_loop_started,
    publish_output_key_set,
    publish_stalled,
    publish_text_delta,
    publish_tool_completed,
    publish_tool_started,
    run_hooks,
)
from framework.agent_loop.internals.judge_pipeline import (
    SubagentJudge as SharedSubagentJudge,
    judge_turn,
)
from framework.agent_loop.internals.sentinel_tool import build_sentinel_setup_tool
from framework.agent_loop.internals.stall_detector import (
    fingerprint_tool_calls,
    is_stalled,
    is_tool_doom_loop,
    ngram_similarity,
)
from framework.agent_loop.internals.synthetic_tools import (
    build_ask_user_tool,
    build_collect_result_tool,
    build_escalate_tool,
    build_report_to_parent_tool,
    handle_report_to_parent,
)
from framework.agent_loop.internals.tool_input_coercer import coerce_tool_input
from framework.agent_loop.internals.tool_result_handler import (
    build_json_preview,
    execute_tool,
    extract_json_metadata,
    is_transient_error,
    restore_spill_counter,
    truncate_tool_result,
)
from framework.agent_loop.internals.types import (
    JudgeProtocol,
    JudgeVerdict,
    TriggerEvent,
)
from framework.agent_loop.internals.vision_fallback import (
    caption_tool_image,
    extract_intent_for_tool,
    remap_caption_for_crop,
)
from framework.agent_loop.reminders import (
    InterruptCause,
    LoopActivity,
    LoopSignals,
    ParkReason,
    Reminder,
    ReminderHub,
    ReminderPoint,
    wrap_reminder,
)
from framework.agent_loop.types import AgentContext, AgentProtocol, AgentResult
from framework.config import get_vision_fallback_model
from framework.host.event_bus import EventBus
from framework.llm.capabilities import filter_tools_for_model, supports_image_tool_results
from framework.llm.provider import Tool, ToolResult, ToolUse
from framework.llm.stream_events import (
    FinishEvent,
    ReasoningDeltaEvent,
    StreamErrorEvent,
    TextDeltaEvent,
    ToolCallEvent,
)
from framework.tracker.llm_debug_logger import log_llm_turn

logger = logging.getLogger(__name__)

# Tags that wrap internal reasoning and must be stripped from the
# user-visible stream.  These are the 5-pillar character assessment
# labels, written by the queen as a prefix to every response in either
# closed (<tag>val</tag>) or bare (<tag> val) form.
_INTERNAL_TAGS = frozenset(
    {
        "relationship",
        "context",
        "sentiment",
        "physical_state",
        "tone",
        # Visible-reasoning scaffold: a persona may emit a <think>…</think>
        # block (state calibration, addressee/boundary reasoning) before its
        # spoken line so the grounding tokens exist in-context. It is internal —
        # strip the WHOLE block from the client snapshot (kept in the stored
        # part for history/analysis), never just the markers. Without this the
        # generic pass removes only <think></think> and leaks the reasoning text.
        "think",
    }
)

# Closed-block form: <tag>value</tag>
_STRIP_RE = re.compile(
    r"<(?:" + "|".join(_INTERNAL_TAGS) + r")>"
    r".*?"
    r"</(?:" + "|".join(_INTERNAL_TAGS) + r")>\s*",
    re.DOTALL,
)

# Bare-label form: <tag> value-up-to-next-tag-or-newline.
# The value cannot contain `<` or `\n` — those terminate the label.
# Trailing whitespace (including the terminating newline) is consumed
# so the visible text that follows starts cleanly.
_LABEL_STRIP_RE = re.compile(r"<(?:" + "|".join(_INTERNAL_TAGS) + r")>[^<\n]*\s*")

# An OPEN <think> that hasn't closed yet (a closed block is consumed by
# _STRIP_RE before this runs). Unlike the bare-label pillars — one-line
# prefix labels safely handled by _LABEL_STRIP_RE — <think> wraps MULTI-LINE
# hidden reasoning. Mid-stream, everything from the opening tag to the end
# of the snapshot is reasoning and must be truncated; otherwise the label
# pass strips only the `<think>` marker and the body streams out as visible
# text (the think-leak: the bot's inner monologue sent to the group).
_UNCLOSED_THINK_RE = re.compile(r"<think\b", re.IGNORECASE)

# Matches a trailing `<` that could be the start of an internal tag.
# We build a pattern that matches `<` followed by any prefix of any
# internal tag name (e.g. `<rela`, `<contex`).
_PARTIAL_PREFIXES: set[str] = set()
for _tag in _INTERNAL_TAGS:
    for _i in range(1, len(_tag) + 1):
        _PARTIAL_PREFIXES.add(_tag[:_i])
_PARTIAL_OPEN_RE = re.compile(r"<(?:" + "|".join(re.escape(p) for p in sorted(_PARTIAL_PREFIXES, key=len, reverse=True)) + r")$")

_GENERIC_TAG_RE = re.compile(r"</?[a-zA-Z_][\w-]*\s*/?>")
# `</?\s*$` also eats a bare trailing `<` or `</` — the amputated stump of a
# closing tag (e.g. `</think>`) cut off mid-stream. Without the `/` branch a
# lone `</` at end slipped through (the classic `…line</` leak tail).
_GENERIC_TAG_OR_PARTIAL_RE = re.compile(r"<[a-zA-Z_]|</[a-zA-Z_]|</?\s*$")


def _render_tool_budget_checkpoint(count: int, hard_limit: int) -> str:
    """Body for an escalating soft tool-call budget checkpoint.

    This is a *checkpoint, not a stop* — the turn-loop keeps running.
    Its purpose is to keep a long autonomous run from becoming
    headstrong: pause, confirm the current approach is still working,
    and switch tactics or consult the user rather than grinding the
    same path. The hard stop lands at ``hard_limit``.
    """
    return (
        f"Tool-call checkpoint: you've made {count} tool calls in this stretch "
        f"without yielding the turn (hard stop at {hard_limit}).\n\n"
        "This is a checkpoint, not a stop. If you're deliberately working a "
        "long, multi-step mission and you know where you are, keep going\n\n"
        "But take one honest beat first. If you've been repeating similar "
        "calls, retrying a failing approach, or have lost the thread: "
        "Step back and either (a) try a "
        "genuinely different approach, or (b) if you've hit real difficulty, "
        "pause and escalate instead of grinding on."
    )


# Grace iteration: the set of tools dispatch will still execute once the
# agent has exhausted ``max_iterations`` and is in its single wrap-up turn.
# Everything else gets the neutral ``_GRACE_SKIP_MSG`` placeholder so the
# agent knows the call landed but did not run, and is forced to spend its
# last turn on reporting / persisting state rather than starting new work.
#   - report_to_parent : the terminal channel; without this the queen
#     receives no SUBAGENT_REPORT for the worker.
#   - tracker_upsert   : durable progress channel; rows persist even when
#     the explicit report is thin.
#   - task_update      : worker-local task-list hygiene; cheap to allow
#     and aligned with "wrap up" semantics.
_GRACE_TERMINAL_TOOLS: frozenset[str] = frozenset({"report_to_parent", "tracker_upsert", "task_update"})

_GRACE_SKIP_MSG = (
    "[Skipped — this is your final (grace) iteration. Only "
    "report_to_parent, tracker_upsert, and task_update may execute. "
    "Call report_to_parent now with whatever status you have "
    "(success, partial, or failed) — do not start new work.]"
)

_GRACE_REMINDER_BODY = (
    "[final iteration] Your iteration budget is exhausted. This is your "
    "LAST turn. Call report_to_parent(status=<success|partial|failed>, "
    "summary=<one paragraph>, data=<optional>) NOW to deliver your "
    "results.\n\n"
    "If you still need to persist findings to shared state you may also "
    "call tracker_upsert or task_update. ALL OTHER TOOLS WILL BE SKIPPED "
    "— do not start new work; consolidate what you have and report."
)

# Variant of the grace reminder used when grace is entered early because
# the worker exhausted its cumulative (lifetime) tool-call budget rather
# than its iteration budget. Same wind-down contract — report and stop —
# but framed around the tool-call budget so the model isn't confused about
# why it still has iterations left.
_TOOL_BUDGET_GRACE_REMINDER_BODY = (
    "[tool-call budget reached] You have used your full tool-call budget "
    "for this task. This is your LAST turn. Call report_to_parent("
    "status=<success|partial|failed>, summary=<one paragraph>, "
    "data=<optional>) NOW to deliver your partial results to the queen.\n\n"
    "If you still need to persist findings you may also call tracker_upsert "
    "or task_update. ALL OTHER TOOLS WILL BE SKIPPED — do not start new "
    "work; consolidate what you have and report."
)


def _strip_internal_tags_from_snapshot(snapshot: str) -> str:
    """Remove internal tag blocks and bare labels from accumulated text.

    The 5-pillar character assessment tags appear in two forms:
      1. Closed block: <relationship>neutral</relationship>
      2. Bare label:   <relationship> neutral
    Both are stripped.  Partial tags at the end of a streaming snapshot
    are truncated so reasoning never leaks mid-stream.
    """
    # Pass 1: closed <tag>...</tag> blocks
    cleaned = _STRIP_RE.sub("", snapshot)

    # Pass 1.5: an unclosed <think> mid-stream — truncate from the tag to the
    # end. The visible text stays frozen until the block closes; then Pass 1
    # removes the whole block and the spoken line flows through.
    m_think = _UNCLOSED_THINK_RE.search(cleaned)
    if m_think:
        cleaned = cleaned[: m_think.start()]

    # Pass 2: bare-label <tag> value pairs (value runs to next tag or newline)
    cleaned = _LABEL_STRIP_RE.sub("", cleaned)

    # Pass 3: trailing partial tag (e.g. `<rela`) — mid-stream guard
    m = _PARTIAL_OPEN_RE.search(cleaned)
    if m:
        cleaned = cleaned[: m.start()]

    # Generic pass: strip any remaining XML-like tags the LLM hallucinated
    # (e.g. <professional>, <staging>, </neutral>).  These are never
    # intentional markup — just remove them outright.
    cleaned = _GENERIC_TAG_RE.sub("", cleaned)
    # Truncate at any remaining `<` that looks like it could be a tag
    # start (followed by a letter) or a bare `<` at end of string.
    # During streaming this suppresses partial tags until they resolve.
    m3 = _GENERIC_TAG_OR_PARTIAL_RE.search(cleaned)
    if m3:
        cleaned = cleaned[: m3.start()]

    return cleaned


_THINK_REASONING_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


def _extract_think_reasoning(text: str) -> str:
    """Concatenate the content of every COMPLETE <think>…</think> block in the
    accumulated output. This is the hidden reasoning stripped from the visible
    snapshot; it is surfaced via the CLIENT_REASONING event so monitors can see
    the grounding the agent did before speaking. Returns "" if no closed block yet.
    """
    parts = [m.strip() for m in _THINK_REASONING_RE.findall(text) if m.strip()]
    return "\n".join(parts)


def _vision_fallback_active(model: str | None) -> bool:
    """Return True if tool-result images for *model* should be routed
    through the vision-fallback chain rather than sent to the model.

    Trigger: the model's catalog entry has ``supports_vision: false``
    (resolved via :func:`capabilities.supports_image_tool_results`,
    which reads ``model_catalog.json``). Unknown models default to
    vision-capable, so the fallback only fires when the catalog
    explicitly says the model is text-only.

    The ``vision_fallback`` config block is the *substitution* model —
    it doesn't widen the trigger. To force fallback for a model that
    isn't catalogued yet, add an entry to ``model_catalog.json`` with
    ``supports_vision: false`` rather than relying on a runtime config.
    """
    if not model:
        return False
    return not supports_image_tool_results(model)


async def _captioning_chain(
    intent: str,
    image_content: list[dict[str, Any]],
) -> tuple[str, str] | None:
    """The configured ``vision_fallback`` — and nothing else.

    There used to be a hardcoded ``gemini-3-flash-preview`` retry here
    that reused the configured endpoint's base/auth. Against any custom
    endpoint that base is wrong for Gemini, so the retry could only fail
    confusingly — and its noise masked the real error from the
    configured attempt. The configured slot is the single source of
    truth: it works, or the images are dropped with an honest log line.
    """
    return await caption_tool_image(intent, image_content)


# Pattern for detecting context-window-exceeded errors across LLM providers.
_CONTEXT_TOO_LARGE_RE = re.compile(
    r"context.{0,20}(length|window|limit|size)|"
    r"too.{0,10}(long|large|many.{0,10}tokens)|"
    r"(exceed|exceeds|exceeded).{0,30}(limit|window|context|tokens)|"
    r"maximum.{0,20}token|prompt.{0,20}too.{0,10}long",
    re.IGNORECASE,
)


def _is_context_too_large_error(exc: BaseException) -> bool:
    """Detect whether an exception indicates the LLM input was too large."""
    cls = type(exc).__name__
    if "ContextWindow" in cls:
        return True
    return bool(_CONTEXT_TOO_LARGE_RE.search(str(exc)))


def _queen_account_preflight(tc: Any) -> ToolResult | None:
    """Return an ``account_selection_required`` ToolResult, or None.

    Runs in the parent process before a tool call crosses into the
    stdio MCP subprocess. The subprocess has its own credential
    adapter and never sees the parent's strict-mode ContextVar, so the
    check has to happen here.

    Returns None when:
      - we're not in queen strict mode,
      - the tool isn't tied to an OAuth credential,
      - the LLM already supplied ``account=<alias>``,
      - or zero/one account is authorized (no ambiguity to resolve).
    """
    try:
        from aden_tools.credentials import CredentialStoreAdapter
        from aden_tools.credentials.store_adapter import is_strict_account_mode
    except Exception:
        return None

    if not is_strict_account_mode():
        return None

    tool_input = getattr(tc, "tool_input", None)
    if isinstance(tool_input, dict):
        supplied = str(tool_input.get("account", "") or "").strip()
        if supplied:
            return None
    elif tool_input is not None:
        # Non-dict input (rare) — skip the gate; tool will handle.
        return None

    tool_name = getattr(tc, "tool_name", "") or ""
    if not tool_name:
        return None

    try:
        adapter = CredentialStoreAdapter.default()
    except Exception:
        return None

    cred_name = adapter.get_credential_for_tool(tool_name)
    if cred_name is None:
        return None  # tool isn't credential-bound, no ambiguity to check

    spec = adapter._specs.get(cred_name)  # noqa: SLF001 — read-only
    provider_name = getattr(spec, "aden_provider_name", "") or cred_name if spec is not None else cred_name

    try:
        accounts = adapter._store.list_accounts(provider_name)  # noqa: SLF001
    except Exception:
        return None

    if len(accounts) <= 1:
        return None

    payload = {
        "error": "account_selection_required",
        "credential_id": cred_name,
        "provider": provider_name,
        "available_accounts": [
            {
                "alias": acct.get("alias", ""),
                "identity": acct.get("identity", {}) or {},
            }
            for acct in accounts
        ],
        "message": (f"Multiple {provider_name} accounts are authorized; specify which one to use via account=<alias>."),
        "instructions": (
            "Multiple accounts are authorized for this provider. "
            "Ask the user which one to use, then re-call this tool "
            "with account=<alias> set to one of the listed aliases."
        ),
    }
    return ToolResult(
        tool_use_id=tc.tool_use_id,
        content=json.dumps(payload),
        is_error=True,
    )


def _build_tool_error_result(tc: Any, exc: BaseException) -> ToolResult:
    """Convert a tool exception into a ToolResult for the model.

    Special-cases two credential exceptions so the agent receives a
    structured payload instead of an opaque error string:
      - ``CredentialExpiredError`` → ``credential_expired`` (the agent's
        behavior block prompts the user to reauthorize).
      - ``AccountSelectionRequiredError`` → ``account_selection_required``
        (queens with 2+ accounts on a provider; the LLM should ask the
        user which to use and re-call with ``account=<alias>``).
    """
    try:
        from framework.credentials.models import (
            AccountSelectionRequiredError,
            CredentialExpiredError,
        )
    except ImportError:
        CredentialExpiredError = None  # type: ignore[assignment]
        AccountSelectionRequiredError = None  # type: ignore[assignment]

    if CredentialExpiredError is not None and isinstance(exc, CredentialExpiredError):
        payload: dict[str, Any] = {
            "error": "credential_expired",
            "credential_id": exc.credential_id,
            "message": str(exc),
        }
        if exc.provider:
            payload["provider"] = exc.provider
        if exc.alias:
            payload["alias"] = exc.alias
        if exc.help_url:
            payload["reauth_url"] = exc.help_url
        return ToolResult(
            tool_use_id=tc.tool_use_id,
            content=json.dumps(payload),
            is_error=True,
        )

    if AccountSelectionRequiredError is not None and isinstance(exc, AccountSelectionRequiredError):
        sel_payload: dict[str, Any] = {
            "error": "account_selection_required",
            "credential_id": exc.credential_id,
            "provider": exc.provider,
            "available_accounts": exc.available_accounts,
            "message": str(exc),
            "instructions": (
                "Multiple accounts are authorized for this provider. "
                "Ask the user which one to use, then re-call this tool "
                "with account=<alias> set to one of the listed aliases."
            ),
        }
        return ToolResult(
            tool_use_id=tc.tool_use_id,
            content=json.dumps(sel_payload),
            is_error=True,
        )

    return ToolResult(
        tool_use_id=tc.tool_use_id,
        content=f"Tool '{tc.tool_name}' raised: {exc}",
        is_error=True,
    )


def _publish_attach_file_result(
    result: ToolResult,
    conversation_store: Any,
) -> ToolResult:
    """Post-process an ``attach_file`` ToolResult: copy each source file
    into the session's ``data/attachments/`` directory and inject
    ``hive_attachment_url`` into the summary JSON so the chip pipeline
    (assistant message ``images`` field → renderer's AttachmentChip)
    can surface a clickable chip to the user.

    The framework is the **single** chip publisher — the tool no longer
    self-publishes (its pooled MCP subprocess is queen-agnostic and
    can't see the current session's ``$HIVE_STORAGE_PATH``). So every
    successful attach_file call MUST reach this function for the user
    to see a chip.

    Loud-failure policy: every short-circuit logs a warning, and if we
    can't publish at all the result is rewritten as an error so the
    agent surfaces the failure to the user instead of riding a half-
    success ("the file is attached" with no chip on the screen).
    """
    if conversation_store is None:
        logger.error(
            "attach_file: chip publish skipped — conversation_store is None. User will not see a chip in chat. tool_use_id=%s",
            result.tool_use_id,
        )
        return _attach_file_publish_failure(result, "no conversation store on agent loop")
    # The store's base path is ``{session_dir}/conversations/``; the
    # session dir itself is its parent. Other store implementations
    # may not have ``_base`` — log loudly if so since chip publishing
    # depends on a filesystem-backed session.
    base = getattr(conversation_store, "_base", None)
    if base is None:
        logger.error(
            "attach_file: chip publish skipped — conversation_store=%r has no `_base`. User will not see a chip in chat.",
            type(conversation_store).__name__,
        )
        return _attach_file_publish_failure(result, "conversation store has no filesystem base")
    session_dir = Path(base).parent
    # attach_file emits its summary as the FIRST TextContent block. The
    # MCP executor concatenates every TextContent block in the tool's
    # return list into a single ``result.content`` string, so the JSON
    # summary is followed by whatever inline text content the tool
    # produced (the file body for text-shaped formats; nothing for
    # binary previews / blobs). Use raw_decode to peel off just the
    # leading JSON object and ignore the trailing text.
    content = result.content or ""
    leading_ws_len = len(content) - len(content.lstrip())
    leading = content[leading_ws_len:]
    if not leading.startswith("{"):
        logger.error(
            "attach_file: result.content does not start with a JSON object — cannot publish chip. content[:120]=%r",
            content[:120],
        )
        return _attach_file_publish_failure(result, "tool result is not a JSON summary")
    try:
        payload, json_end = json.JSONDecoder().raw_decode(leading)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error(
            "attach_file: failed to parse summary JSON for chip publish: %s. content[:120]=%r",
            exc,
            content[:120],
        )
        return _attach_file_publish_failure(result, f"tool result JSON parse failed: {exc}")
    if not isinstance(payload, dict):
        logger.error("attach_file: parsed payload is %s, expected dict", type(payload).__name__)
        return _attach_file_publish_failure(result, "tool result top-level is not an object")
    attached = payload.get("attached")
    if not isinstance(attached, list) or not attached:
        # Empty `attached` is the tool's own signal that nothing was
        # successfully attached (every path errored). The tool already
        # populated `errors` for the agent; nothing to publish.
        logger.info(
            "attach_file: nothing to publish (attached=%r, errors=%r)",
            attached,
            payload.get("errors"),
        )
        return result
    # Whatever followed the JSON envelope (the inlined text body for
    # text-shaped attachments) is preserved verbatim — the LLM still
    # needs to read it on the next turn.
    trailing = leading[json_end:]

    import shutil as _shutil

    from aden_tools.utils.attachments import (
        disambiguate_attachment_filename,
        sanitize_attachment_basename,
    )

    attachments_dir = session_dir / "data" / "attachments"
    try:
        attachments_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("attach_file: could not create %s: %s", attachments_dir, exc)
        return _attach_file_publish_failure(result, f"could not create attachments dir: {exc}")

    logger.info(
        "attach_file: publishing %d entr%s into %s",
        len(attached),
        "y" if len(attached) == 1 else "ies",
        attachments_dir,
    )
    published_count = 0
    per_entry_errors: list[str] = []
    for entry in attached:
        if not isinstance(entry, dict):
            per_entry_errors.append(f"non-dict entry: {entry!r}")
            continue
        resolved = entry.get("resolved") or entry.get("path")
        if not isinstance(resolved, str):
            per_entry_errors.append(f"entry missing resolved/path: {entry!r}")
            continue
        source = Path(resolved)
        if not source.is_file():
            logger.warning("attach_file: source vanished before publish: %s", source)
            per_entry_errors.append(f"source vanished: {source}")
            continue
        base_name = sanitize_attachment_basename(source.name, force_ext=source.suffix.lower())
        dest_name = disambiguate_attachment_filename(attachments_dir, base_name)
        dest = attachments_dir / dest_name
        try:
            _shutil.copyfile(source, dest)
        except OSError as exc:
            logger.warning("attach_file: copy %s → %s failed: %s", source, dest, exc)
            per_entry_errors.append(f"copy failed for {source.name}: {exc}")
            continue
        # Point `resolved` at the copy in the session's attachments dir,
        # not the original source path — the source (e.g. the tool's CWD)
        # is queen/colony-agnostic and may not even exist for consumers of
        # this summary. `hive-attachment://` + this absolute path now agree.
        entry["resolved"] = str(dest)
        entry["hive_attachment_url"] = f"hive-attachment://data/attachments/{dest_name}"
        published_count += 1
        logger.info("attach_file: published %s → %s", source.name, dest_name)

    if published_count == 0:
        logger.error(
            "attach_file: could not publish ANY of %d entries; errors=%r",
            len(attached),
            per_entry_errors,
        )
        return _attach_file_publish_failure(
            result,
            "could not publish any attachment: " + "; ".join(per_entry_errors) if per_entry_errors else "could not publish any attachment",
        )

    # Re-serialize the summary; preserve the trailing inlined body
    # (if any) so the LLM still sees the file content on the next turn.
    return ToolResult(
        tool_use_id=result.tool_use_id,
        content=json.dumps(payload) + trailing,
        is_error=result.is_error,
        image_content=getattr(result, "image_content", None),
        is_skill_content=getattr(result, "is_skill_content", False),
    )


def _attach_file_publish_failure(result: ToolResult, reason: str) -> ToolResult:
    """Rewrite an attach_file ToolResult into a hard failure with a
    diagnostic the agent can read.

    Without this, the agent sees a "successful" tool call (it returned
    a summary with paths) and announces the file is delivered — but
    the user never sees a chip because chip publishing silently
    no-op'd. That divergence is exactly the bug we're closing.
    """
    payload = {
        "attached": [],
        "errors": [
            {
                "error": (
                    f"attach_file failed to publish the file as a chip: {reason}. "
                    "The file was NOT delivered to the user. Tell the user the "
                    "delivery failed; do not claim the file was sent."
                ),
            }
        ],
    }
    return ToolResult(
        tool_use_id=result.tool_use_id,
        content=json.dumps(payload),
        is_error=True,
        image_content=None,
        is_skill_content=getattr(result, "is_skill_content", False),
    )


# ---------------------------------------------------------------------------
# Compatibility and control-flow helpers
# ---------------------------------------------------------------------------


class TurnCancelled(Exception):
    """Raised when a turn is cancelled mid-stream."""

    pass


# Public compatibility aliases for older imports from agent_loop.py.
SubagentJudge = SharedSubagentJudge
LoopConfig = event_loop_types.LoopConfig
HookContext = event_loop_types.HookContext
HookResult = event_loop_types.HookResult
OutputAccumulator = event_loop_types.OutputAccumulator


class AgentLoop(AgentProtocol):
    """Multi-turn LLM streaming loop with tool execution and judge evaluation.

    Lifecycle:
    1. Try to restore from durable state (crash recovery)
    2. If no prior state, init from AgentSpec.system_prompt + input_keys
    3. Loop: drain injection queue -> stream LLM -> execute tools
       -> if queen-interactive: block for user input (see below)
       -> judge evaluates (acceptance criteria)
    4. Publish events to EventBus at each stage
    5. Write cursor after each iteration
    6. Terminate when judge returns ACCEPT, shutdown signaled, or max iterations
    7. Build output dict from OutputAccumulator

    Queen interaction blocking:

    - **Text-only turns** (no real tool calls)
      automatically block for user input.  If the LLM is talking to the
      user (not calling tools), it should wait for the user's response
      before the judge runs.
    - **Work turns** (tool calls) flow through without blocking —
      the LLM is making progress, not asking the user.
    - A synthetic ``ask_user`` tool is also injected for explicit
      blocking when the LLM wants to be deliberate about requesting
      input (e.g. mid-tool-call).

    Always returns AgentResult with retryable=False semantics. The executor
    must NOT retry event loop nodes -- retry is handled internally by the
    judge (RETRY action continues the loop). See WP-7 enforcement.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        judge: JudgeProtocol | None = None,
        config: LoopConfig | None = None,
        tool_executor: Callable[[ToolUse], ToolResult | Awaitable[ToolResult]] | None = None,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._judge = judge
        self._config = config or LoopConfig()
        self._tool_executor = tool_executor
        self._conversation_store = conversation_store
        # Tuple: (content, is_client_input, image_content, correlation_id).
        # correlation_id ties a queued message back to the CLIENT_INPUT_RECEIVED
        # event emitted at receive time, so the drain can emit a matching
        # CLIENT_INPUT_COMMITTED carrying the true injection time.
        self._injection_queue: asyncio.Queue[tuple[str, bool, list[dict[str, Any]] | None, str | None]] = asyncio.Queue()
        self._trigger_queue: asyncio.Queue[TriggerEvent] = asyncio.Queue()
        # Queen input blocking state
        self._input_ready = asyncio.Event()
        self._awaiting_input = False
        # Why the loop is parked, when it is — None when not parked. Each
        # _await_user_input call site declares its ParkReason; this carries
        # it to _loop_signals so the idle nudge can tell a legitimate
        # question-park from a broken or normal-idle one.
        self._park_reason: ParkReason | None = None
        # The loop's authoritative top-level state. Owned exclusively by
        # _set_activity, which announces every change via LOOP_STATE_CHANGED.
        self._activity: LoopActivity = LoopActivity.EXECUTING
        self._interrupt_cause: InterruptCause | None = None
        # True after the user explicitly clicked Stop — keeps the idle nudge
        # from auto-resuming a park the user deliberately caused.
        self._user_stopped = False
        self._shutdown = False
        # Set by the ask_user handler to carry the normalized question
        # list into the post-turn blocking emit. Drained on every block.
        self._pending_questions: list[dict] | None = None
        # Sentinel: the questions for the *current* park (the ask_user handler
        # drains _pending_questions before the loop parks, so the escalation
        # source can't read them there). Captured in _await_user_input for the
        # duration of the wait; None when not parked / no questions.
        self._park_questions: list[dict] | None = None
        # Sentinel: live conversation ref, set in execute(). The escalation
        # source's park-context provider reads the conversation tail (last
        # assistant message + recent tool errors) from here.
        self._conversation: Any = None
        # Sentinel: the AgentContext for this run (set in execute()), so the
        # park-context provider can resolve session_id for the task store.
        self._agent_ctx: Any = None
        # Same idea for suggest_colony — carries {colony_id, reason}
        # so the blocking path emits COLONY_SUGGESTION_REQUESTED instead
        # of CLIENT_INPUT_REQUESTED.
        self._pending_colony_suggestion: dict | None = None
        # Colony-pivot variant set by the task_create(new_colony=true)
        # synthetic intercept — carries the rich payload
        # {goal, handoff, tasks, source_phase} so the post-turn block
        # emits a richer COLONY_SUGGESTION_REQUESTED for the popup.
        # Drained on every block, same as _pending_colony_suggestion.
        self._pending_colony_pivot: dict | None = None
        # Set by the credentials(action="collect") handler — carries the
        # no-secret form spec {credential_id, account, title, instructions,
        # fields, correlation_id} so the post-turn block emits
        # CLIENT_CREDENTIAL_FORM_REQUESTED and parks for the form submit.
        self._pending_credential_form: dict | None = None
        self._stream_task: asyncio.Task | None = None
        self._tool_task: asyncio.Task | None = None  # gather task while tools run
        # Background tool calls (see _start_background_tool): handle -> entry.
        # A backgrounded tool returns a handle immediately and runs to
        # completion as a detached task; the agent retrieves it via the
        # synthetic collect_result tool. Persists across iterations/turns for
        # the life of this loop instance, so a call started in one turn can be
        # collected later.
        self._background_calls: dict[str, dict[str, Any]] = {}
        self._bg_counter: int = 0
        # Session-level idle tracking. _session_last_event_at is bumped by
        # _mark_session_progress on every sign of forward progress; the
        # reminder hub's IdleNudgeSource reads the derived idle time via
        # the LoopSignals snapshot from _loop_signals(). _stream_first_event_at
        # is promoted out of _run_turn_loop's local scope so that snapshot
        # can distinguish slow_ttft (stream alive, no first event) from
        # between_turns (no _stream_task at all) without poking at locals.
        self._session_last_event_at: float = 0.0
        self._stream_first_event_at: float | None = None
        # Monotonic counter for spillover file naming (web_search_1.txt, etc.)
        self._spill_counter: int = 0
        # Set to True by the report_to_parent synthetic tool handler so the
        # next loop iteration exits cleanly (parallel worker termination).
        self._report_terminated: bool = False
        # Grace iteration state. ``_in_grace`` is set by the outer loop
        # for the duration of each grace iteration so the dispatch loop
        # in _run_turn_loop can restrict tools to ``_GRACE_TERMINAL_TOOLS``.
        # ``_grace_announced`` makes the one-shot reminder injection
        # idempotent across resumed iterations and inner-loop restarts.
        self._in_grace: bool = False
        self._grace_announced: bool = False
        # Cumulative count of tool calls actually dispatched across the
        # whole execute() run (all turn-loops). Drives the lifetime
        # tool-call budget (LoopConfig.tool_call_lifetime_budget): once it
        # reaches the budget, the loop flips into grace wind-down early.
        # In-memory only — resets to 0 per AgentLoop (each colony worker
        # gets a fresh one); a cursor-resume mid-run restarts the count.
        self._tool_calls_used: int = 0
        # Iteration index at which grace first began, under EITHER trigger
        # (iteration- or budget-exhaustion). Used to cap the wind-down to
        # ``grace_iterations`` turns even when budget triggers grace early
        # while many iterations remain. None until grace starts.
        self._grace_start_iteration: int | None = None
        # Back-reference to the Worker that owns this AgentLoop, if any.
        # Set by the Worker's __init__ so the report_to_parent handler can
        # record the explicit report payload on the owning Worker instance.
        self._owner_worker: Any = None
        # Reliability counters — populated throughout execute() and
        # copied onto AgentResult.reliability_stats at return time.
        # Kept on the instance so ``stats()`` can expose them externally
        # without waiting for execute() to return. Keys are stable so
        # dashboards can build aggregates over many runs.
        self._counters: dict[str, int] = {}

        # Framework-level reminder hub (see framework/agent_loop/reminders.py).
        # Every framework nudge flows through it via one of three trigger
        # models: lifecycle fire() points, the temporal IDLE_TICK ticker,
        # and reactive collect()/post(). Registered sources: task
        # reminders, the idle-nudge watchdog, and the stream-stall
        # continue-nudge. Observe-once-per-turn drives the task source's
        # work-weighted counters.
        from framework.agent_loop.active_workers_reminder import ActiveWorkersReminderSource
        from framework.agent_loop.colony_parallel_nudge import ColonyParallelNudgeSource
        from framework.agent_loop.colony_worker_snapshot_reminder import (
            ColonyWorkerSnapshotReminderSource,
        )
        from framework.agent_loop.idle_nudge import IdleNudgeSource
        from framework.agent_loop.stream_stall import StreamStallSource
        from framework.agent_loop.tool_skill_reminders import (
            SearchableToolsReminderSource,
            SkillsCatalogReminderSource,
        )
        from framework.agent_loop.tracker_snapshot_reminder import (
            TrackerSnapshotReminderSource,
            WorkerTrackerSnapshotReminderSource,
        )
        from framework.tasks.reminders import TaskReminderSource

        self._reminder_hub = ReminderHub()
        self._reminder_hub.register(TaskReminderSource())
        self._reminder_hub.register(ColonyParallelNudgeSource())
        self._reminder_hub.register(ActiveWorkersReminderSource())
        # Queen-only: the searchable-tools manifest + skills catalog ride the
        # conversation as <system-reminder>s Self-skip for non-queen streams.
        self._reminder_hub.register(SearchableToolsReminderSource())
        self._reminder_hub.register(SkillsCatalogReminderSource())
        # Tracker snapshots fire at POST_TOOL_USE on their own cadence
        # (queen: browser-gated; worker: tool-call count) — not the shared
        # tool-budget checkpoint. ColonyWorkerSnapshot still rides the
        # budget checkpoint (soft current-turn tail + hard-stop drain).
        self._reminder_hub.register(TrackerSnapshotReminderSource())
        self._reminder_hub.register(WorkerTrackerSnapshotReminderSource())
        self._reminder_hub.register(ColonyWorkerSnapshotReminderSource())
        # Kept as a direct ref: inject_event re-arms its per-variant nudge
        # caps on a real user message ("per user-response cycle").
        self._idle_nudge_source = IdleNudgeSource(
            budget_seconds=self._config.session_idle_nudge_seconds,
            max_nudges=self._config.session_idle_nudge_max_per_session,
            awaiting_budget_seconds=self._config.session_idle_nudge_awaiting_seconds,
            broken_budget_seconds=self._config.session_idle_nudge_broken_seconds,
        )
        self._reminder_hub.register(self._idle_nudge_source)
        # Sentinel autopilot: for a colony queen whose colony has opted in,
        # this owns the parked-queen decision (nudge / escalate-to-human).
        # Self-skips otherwise (workers, DM queens, opt-out colonies), and the
        # idle-nudge source self-skips when this one is active so they never
        # double-nudge. Kept as a direct ref so inject_event re-arms it.
        from framework.sentinel.escalation_source import EscalationSource

        self._escalation_source = EscalationSource(
            park_context_provider=self._build_sentinel_park_context,
        )
        self._reminder_hub.register(self._escalation_source)
        # Kept as a direct ref too: _run_turn_loop resets its per-turn
        # nudge counter and consults it synchronously when a stream stalls.
        self._stream_stall_source = StreamStallSource(
            max_per_turn=self._config.continue_nudge_max_per_turn,
            enabled=self._config.continue_nudge_enabled,
        )
        self._reminder_hub.register(self._stream_stall_source)

    def _bump(self, key: str, by: int = 1) -> None:
        """Increment a reliability counter (creates the key on first use)."""
        self._counters[key] = self._counters.get(key, 0) + by

    def stats(self) -> dict[str, int]:
        """Return a snapshot of reliability counters for this loop."""
        return dict(self._counters)

    def _mark_session_progress(self) -> None:
        """Bump the session-level idle clock.

        Called from every site that proves the loop is making forward
        progress: stream events, tool completions, iteration boundaries,
        user-input arrival. Kept as a single helper so the idle-nudge
        source's notion of "alive" is auditable from one place.
        """
        self._session_last_event_at = time.monotonic()

    def _loop_signals(self) -> LoopSignals:
        """Snapshot loop runtime state for the reminder hub's ticker.

        Handed to temporal sources (the idle-nudge source) via
        ``ReminderContext.signals`` so they decide without poking at loop
        internals. ``idle_seconds`` is time since the last
        :meth:`_mark_session_progress`.
        """
        now = time.monotonic()
        idle = now - self._session_last_event_at if self._session_last_event_at else 0.0
        stream_active = self._stream_task is not None and not self._stream_task.done()
        return LoopSignals(
            idle_seconds=idle,
            awaiting_input=self._awaiting_input,
            park_reason=self._park_reason,
            activity=self._activity,
            user_stopped=self._user_stopped,
            stream_active=stream_active,
            first_event_seen=self._stream_first_event_at is not None,
        )

    # -------------------------------------------------------------------
    # Sentinel integration (colony-queen autopilot)
    # -------------------------------------------------------------------

    async def _build_sentinel_park_context(self) -> Any:
        """Assemble the park context Sentinel's escalation source classifies.

        Lazy — called only after the source's gates pass (so at most once per
        stalled park-cycle). Reads the goal + open tasks from the task store
        and the conversation tail (last assistant message + recent tool
        errors) from the live conversation. Best-effort throughout.
        """
        from framework.sentinel.classifier import ParkContext

        ctx = self._agent_ctx
        session_id = getattr(ctx, "session_id", None) if ctx is not None else None
        reason = self._park_reason

        goal: str | None = None
        open_tasks: list[str] = []
        if session_id:
            try:
                from framework.tasks import get_task_store
                from framework.tasks.models import TaskStatus

                store_ = get_task_store()
                meta = await store_.get_meta(session_id)
                goal = meta.goal if meta is not None else None
                records = await store_.list_tasks(session_id)
                # Open = active and unfinished; archived tasks are parked in
                # History, not the working plan (and archived != completed),
                # so they must not surface here as open work.
                open_tasks = [
                    (getattr(r, "subject", "") or "").strip() for r in (records or []) if r.status not in (TaskStatus.COMPLETED, TaskStatus.ARCHIVED)
                ]
                open_tasks = [t for t in open_tasks if t]
            except Exception:
                logger.debug("sentinel: task-store lookup failed", exc_info=True)

        last_text = ""
        last_user_text = ""
        recent_errors: list[str] = []
        conv = self._conversation
        if conv is not None:
            try:
                msgs = conv.messages
                last_text, last_user_text = self._pick_park_tail(msgs)
                recent_errors = self._scan_recent_tool_errors(msgs)
            except Exception:
                logger.debug("sentinel: conversation tail read failed", exc_info=True)

        # Snapshot in-flight fan-out so the classifier and nudge can tell a
        # queen that is *waiting on workers* apart from one that has genuinely
        # stalled. Same provider the active-workers reminder uses.
        running_workers: list[dict] = []
        if ctx is not None:
            try:
                provider = getattr(ctx, "active_workers_provider", None)
                if callable(provider):
                    running_workers = [w for w in (provider() or []) if isinstance(w, dict)]
            except Exception:
                logger.debug("sentinel: active-workers snapshot failed", exc_info=True)

        return ParkContext(
            park_reason=reason.value if reason is not None else "unknown",
            goal=goal,
            open_tasks=open_tasks,
            last_assistant_text=last_text,
            recent_user_text=last_user_text,
            pending_questions=self._park_questions,
            recent_errors=recent_errors,
            running_workers=running_workers,
            # Keyword scans are noisy, so don't force-escalate on them; pass
            # the evidence to the classifier and let it judge in context.
            hard_blocker=False,
        )

    @staticmethod
    def _pick_park_tail(msgs: list) -> tuple[str, str]:
        """Return (last_assistant_text, last_human_text) from the conversation.

        A single backward walk capturing the most recent assistant message and
        the most recent *real human* message.

        CRITICAL: only ``is_client_input`` messages are the human's own words.
        User-role messages also carry framework-injected content —
        ``<system-reminder>`` blocks (``is_system_reminder``), ``[External
        event]`` forwards, idle nudges, trigger batches — none of which is user
        intent. Feeding one to the classifier as "the user said" would let a
        reminder masquerade as a steer (e.g. suppress a real escalation, or
        resume a queen the human told to stop). This mirrors the filter
        compaction uses to preserve the user's original words.
        """
        last_text = ""
        last_user_text = ""
        for m in reversed(msgs):
            role = getattr(m, "role", "")
            content = (getattr(m, "content", "") or "").strip()
            if not content:
                continue
            if not last_text and role == "assistant":
                last_text = m.content
            elif not last_user_text and role == "user" and getattr(m, "is_client_input", False):
                last_user_text = m.content
            if last_text and last_user_text:
                break
        return last_text, last_user_text

    @staticmethod
    def _scan_recent_tool_errors(msgs: list) -> list[str]:
        """Short snippets of recent tool results that look like blockers.

        Evidence for the classifier (auth/credential/crash signals), not a
        hard escalate trigger — see the note in _build_sentinel_park_context.
        """
        markers = (
            "log in",
            "login",
            "sign in",
            "authenticat",
            "unauthor",
            "credential",
            "expired",
            "session expired",
            "not logged in",
            "captcha",
            "permission denied",
            "403",
            "401",
            "crashed",
            "disconnected",
            "timed out",
        )
        out: list[str] = []
        tool_msgs = [m for m in msgs if getattr(m, "role", "") == "tool"][-8:]
        for m in tool_msgs:
            content = getattr(m, "content", "") or ""
            if any(k in content.lower() for k in markers):
                out.append(content.strip()[:200])
        return out

    def _notify_sentinel_local_resume(self) -> None:
        """Fire-and-forget: close any open escalation for this session because
        a real reply just arrived (in-app or via a routed messaging reply)."""
        ctx = self._agent_ctx
        session_id = getattr(ctx, "session_id", None) if ctx is not None else None
        if not session_id:
            return
        try:
            from framework.sentinel.manager import get_sentinel_manager

            mgr = get_sentinel_manager()
            if mgr is not None:
                asyncio.create_task(mgr.on_local_resume(session_id))
        except Exception:
            logger.debug("sentinel: local-resume notify failed", exc_info=True)

    async def _set_activity(
        self,
        ctx: AgentContext,
        activity: LoopActivity,
        *,
        park_reason: ParkReason | None = None,
        interrupt_cause: InterruptCause | None = None,
    ) -> None:
        """Set — and announce — the loop's authoritative top-level state.

        The *sole* writer of :attr:`_activity` / :attr:`_interrupt_cause`.
        Idempotent: when nothing changed it neither re-stores nor re-emits,
        so transition points (notably the per-iteration ``EXECUTING``
        re-assert) may call it freely without event spam.

        ``park_reason`` is *not* written here — :meth:`_await_user_input`
        owns it — but is compared and forwarded so the announced state and
        its sub-cause stay consistent. Emits ``LOOP_STATE_CHANGED`` so the
        session snapshot reads the loop's own verdict instead of
        re-deriving activity from scattered events.
        """
        if self._activity == activity and self._park_reason == park_reason and self._interrupt_cause == interrupt_cause:
            return
        self._activity = activity
        self._interrupt_cause = interrupt_cause
        if self._event_bus is None:
            return
        try:
            await self._event_bus.emit_loop_state_changed(
                stream_id=ctx.stream_id or ctx.agent_id,
                node_id=ctx.agent_id,
                activity=activity.value,
                execution_id=ctx.execution_id or "",
                park_reason=park_reason.value if park_reason else None,
                interrupt_cause=interrupt_cause.value if interrupt_cause else None,
            )
        except Exception:
            logger.debug("[_set_activity] emit_loop_state_changed failed", exc_info=True)

    async def _drain_reminder_hub(self, conversation: NodeConversation, ctx: AgentContext) -> int:
        """Inject reminders parked by the hub's temporal ticker.

        Runs on the loop coroutine at the iteration boundary so
        conversation writes never race the loop's own mutations.
        Best-effort — a failed injection is logged and skipped.

        Returns the number of reminders injected. Every reminder is
        energized input: a drained reminder breaks a pending-input wait so
        the agent acts on it instead of re-parking. (A reminder that
        reached a parked agent without waking it would simply rot unread —
        see ``_inject_reminder``.)
        """
        injected = 0
        for reminder in self._reminder_hub.take_pending():
            try:
                await self._inject_reminder(reminder, conversation, ctx)
                injected += 1
            except Exception:  # noqa: BLE001
                logger.debug("failed to inject reminder from %s", reminder.source, exc_info=True)
        return injected

    async def _inject_reminder(
        self,
        reminder: Reminder,
        conversation: NodeConversation,
        ctx: AgentContext,
    ) -> None:
        """Place a single ticker-/post()-produced reminder into the
        conversation.

        Every reminder is injected uniformly: its body is wrapped in a
        ``<system-reminder>`` block and the message is tagged
        ``is_system_reminder`` so the loop, the UI and compaction treat it
        consistently. Each injection emits the ``reminder_injected``
        telemetry event.
        """
        block = wrap_reminder([reminder.body])
        if not block:
            return
        await conversation.add_user_message(block, is_system_reminder=True)
        logger.info(
            "[reminder] injected %s (%d chars)",
            reminder.source,
            len(reminder.body),
        )
        await self._emit_reminder_injected(ctx, reminder)

    async def _emit_reminder_injected(self, ctx: AgentContext, reminder: Reminder) -> None:
        """Bump counters and emit the ``reminder_injected`` event.

        Single telemetry point for every hub injection — drained
        reminders, the synchronous stream-stall nudge, and (via a
        synthetic ``Reminder``) lifecycle blocks.
        """
        self._bump(f"reminder_injected_{reminder.source}")
        # Idle nudges keep their substate-tagged counter for dashboards.
        if reminder.source == "idle_nudge":
            self._bump(f"session_idle_nudge_{reminder.meta.get('substate', '?')}")
        detail = str(reminder.meta.get("substate") or reminder.meta.get("reason") or reminder.meta.get("point") or "")
        if self._event_bus is None:
            return
        try:
            await self._event_bus.emit_reminder_injected(
                stream_id=ctx.stream_id or ctx.agent_id,
                node_id=ctx.agent_id,
                source=reminder.source,
                detail=detail,
                meta=dict(reminder.meta),
                execution_id=ctx.execution_id or None,
            )
        except Exception:  # noqa: BLE001
            logger.debug("failed to emit reminder_injected", exc_info=True)

    def _finalize_result(self, result: AgentResult, reason: str) -> AgentResult:
        """Stamp exit_reason + reliability_stats on an AgentResult before return.

        Central point so every exit path in execute() carries the same
        observability payload, and new counters show up in results
        without touching every return site.
        """
        result.exit_reason = reason
        result.reliability_stats = dict(self._counters)
        result.tool_calls_used = self._tool_calls_used
        return result

    def validate_input(self, ctx: AgentContext) -> list[str]:
        """Validate hard requirements only.

        Event loop nodes are LLM-powered and can reason about flexible input,
        so input_keys are treated as hints — not strict requirements.
        Only the LLM provider is a hard dependency.
        """
        errors = []
        if ctx.llm is None:
            errors.append("LLM provider is required for AgentLoop")
        return errors

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def execute(self, ctx: AgentContext) -> AgentResult:
        """Run the event loop.

        Thin wrapper around :meth:`_execute_impl` that stamps reliability
        counters on whatever AgentResult the implementation returns, and
        fills in a best-effort ``exit_reason`` from the result fields
        when the implementation didn't set one explicitly. This way
        every return path in ``_execute_impl`` automatically carries
        telemetry without having to edit 13+ return sites.

        Also owns the lifecycle of the reminder hub's temporal ticker
        (idle-nudge source): it's started inside ``_execute_impl`` once
        the conversation is ready, and stopped here in ``finally`` so
        every return path in the impl (and every exception) tears down
        the background ticker without leaving an orphaned task.
        """
        try:
            # Resolve which reminder sources apply to this agent before
            # anything consults the hub (see ReminderHub.bind) — this is
            # how one shared loop serves queens, workers, judges, etc.
            self._reminder_hub.bind(ctx)
            result = await self._execute_impl(ctx)
        except Exception:
            # The loop exited via an unhandled exception — announce
            # INTERRUPTED/crashed before it propagates so the session
            # snapshot never shows a dead loop as cleanly idle. Best-effort;
            # CancelledError (deliberate shutdown) is not a crash and is
            # left to propagate untouched.
            try:
                await self._set_activity(
                    ctx,
                    LoopActivity.INTERRUPTED,
                    interrupt_cause=InterruptCause.CRASHED,
                )
            except Exception:
                logger.debug("[execute] crash-state announce failed", exc_info=True)
            raise
        finally:
            # Stop the reminder hub's temporal ticker on every exit path
            # so no background poll task outlives the session.
            await self._reminder_hub.stop()
        # Always refresh counters at the outermost boundary, in case a
        # nested return in _execute_impl used _finalize_result with a
        # stale copy.
        result.reliability_stats = dict(self._counters)
        result.tool_calls_used = self._tool_calls_used
        if result.exit_reason == "?":
            # Best-effort classification from the AgentResult payload.
            # _execute_impl can (and should) set reason explicitly at
            # key sites via _finalize_result — this only handles the
            # returns that weren't updated yet.
            err = (result.error or "").lower()
            if result.success:
                result.exit_reason = "completed"
            elif "max iterations" in err:
                result.exit_reason = "max_iterations"
            elif "input_validation_errors" in err or result.validation_errors:
                result.exit_reason = "validation_error"
            elif "timed out" in err or "timeout" in err:
                result.exit_reason = "timeout"
            elif "cancel" in err or "stopped" in err:
                result.exit_reason = "cancelled"
            else:
                result.exit_reason = "failed"
        return result

    async def _execute_impl(self, ctx: AgentContext) -> AgentResult:
        """Run the event loop."""
        self._last_ctx = ctx
        logger.debug(
            "[AgentLoop.execute] Starting execution for node=%s, stream=%s",
            ctx.agent_id,
            ctx.stream_id,
        )
        start_time = time.time()
        total_input_tokens = 0
        total_output_tokens = 0
        stream_id = ctx.stream_id or ctx.agent_id
        node_id = ctx.agent_id
        execution_id = ctx.execution_id or ""
        # Announce EXECUTING immediately so the SSE snapshot reflects a live
        # loop during conversation restore / tool refresh (which can take
        # 30-60s for large histories). If the loop then parks for pending
        # input (cold resume), _await_user_input will override with
        # AWAITING_USER.
        await self._set_activity(ctx, LoopActivity.EXECUTING)
        # Store skill dirs for AS-9 file-read interception in _execute_tool
        self._skill_dirs: list[str] = ctx.skill_dirs
        logger.debug(
            "[AgentLoop.execute] node_id=%s, execution_id=%s, max_iterations=%d",
            node_id,
            execution_id,
            self._config.max_iterations,
        )

        # Verdict counters for runtime logging
        _accept_count = _retry_count = _escalate_count = _continue_count = 0

        # Queen auto-block grace: consecutive text-only turns without
        # any real tool call or set_output.  Resets on progress.
        _cf_text_only_streak = 0
        # Worker auto-escalation: consecutive text-only turns.
        # After grace, auto-escalate to queen for guidance.
        _worker_text_only_streak = 0
        # Silent worker detection: consecutive turns with tool calls
        # but no user-facing text.  After the threshold, inject a
        # nudge asking the agent to communicate progress.
        _silent_tool_streak = 0

        # 1. Guard: LLM required
        if ctx.llm is None:
            error_msg = "LLM provider not available"
            # Log guard failure
            if ctx.runtime_logger:
                ctx.runtime_logger.log_node_complete(
                    node_id=node_id,
                    node_name=ctx.agent_spec.name,
                    node_type="event_loop",
                    success=False,
                    error=error_msg,
                    exit_status="guard_failure",
                    total_steps=0,
                    tokens_used=0,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0,
                )
            return self._finalize_result(AgentResult(success=False, error=error_msg), "guard_failure")

        # 2. Restore or create new conversation + accumulator
        restored = await self._restore(ctx)
        if restored is not None:
            conversation = restored.conversation
            accumulator = restored.accumulator
            start_iteration = restored.start_iteration
            _restored_recent_responses = restored.recent_responses
            _restored_tool_fingerprints = restored.recent_tool_fingerprints
            _restored_pending_input = restored.pending_input
            _is_cold_resume = True
            # Restore the user-stop flag. __init__ defaulted it to False; if
            # the previous process persisted user_stopped=True (cancel route
            # set the flag and a checkpoint write captured it) the idle-nudge
            # gate must respect that across restart. Cleared by inject_event
            # when a real user message arrives.
            if restored.user_stopped:
                self._user_stopped = True
                logger.info("[%s] restored _user_stopped=True from cursor", ctx.agent_id)

            # Restore the cumulative tool-call count so the lifetime tool-call
            # budget (LoopConfig.tool_call_lifetime_budget) is a TRUE cap
            # across resumes — a resumed worker continues counting toward its
            # budget instead of getting a fresh allotment each time.
            self._tool_calls_used = restored.tool_calls_used
            if restored.tool_calls_used:
                logger.info(
                    "[%s] restored tool_calls_used=%d from cursor",
                    ctx.agent_id,
                    restored.tool_calls_used,
                )

            # Refresh the system prompt. Split into the cache-stable static
            # prefix (identity / accounts / skills / protocols / memory /
            # focus) and the per-turn dynamic suffix (narrative) so the
            # bulk of the prompt stays warm in the provider's prompt
            # cache across iterations.
            from framework.agent_loop.prompting import (
                build_system_prompt_parts_for_context,
            )

            _static, _suffix = build_system_prompt_parts_for_context(ctx)
            if conversation.system_prompt_static != _static or conversation.system_prompt_dynamic_suffix != _suffix:
                conversation.update_system_prompt(_static, dynamic_suffix=_suffix)
                logger.info("Refreshed system prompt for restored conversation")

            # Refresh other meta fields that may differ across runs
            conversation._max_context_tokens = self._config.max_context_tokens
            if ctx.agent_spec.output_keys:
                conversation._output_keys = ctx.agent_spec.output_keys
            conversation._meta_persisted = False
        else:
            _restored_recent_responses = []
            _restored_tool_fingerprints = []
            _restored_pending_input = None
            _is_cold_resume = False

            if self._conversation_store is not None:
                # Log before clearing so data loss is visible in diagnostics.
                existing_parts = await self._conversation_store.read_parts()
                if existing_parts:
                    logger.warning(
                        "[%s] _restore returned None but store has %d parts — clearing (possible data loss)",
                        ctx.agent_id,
                        len(existing_parts),
                    )
                await self._conversation_store.clear()

            from framework.agent_loop.prompting import (
                build_system_prompt_parts_for_context,
            )

            # Split into static prefix (cache-stable) and dynamic suffix
            # (narrative + timestamp). Both legs are recombined for the
            # initial NodeConversation construction, then re-set via
            # update_system_prompt so the conversation tracks them
            # separately and the LLM wrapper can emit two cache-aware
            # system content blocks.
            system_prompt_static, system_prompt_suffix = build_system_prompt_parts_for_context(ctx)

            if ctx.skills_catalog_prompt:
                logger.info(
                    "[%s] Injected skills catalog (%d chars)",
                    node_id,
                    len(ctx.skills_catalog_prompt),
                )
            if ctx.protocols_prompt:
                logger.info(
                    "[%s] Injected operational protocols (%d chars)",
                    node_id,
                    len(ctx.protocols_prompt),
                )

            conversation = NodeConversation(
                system_prompt=system_prompt_static,
                max_context_tokens=self._config.max_context_tokens,
                output_keys=ctx.agent_spec.output_keys or None,
                store=self._conversation_store,
                run_id=ctx.effective_run_id,
                compaction_buffer_tokens=self._config.compaction_buffer_tokens,
                compaction_buffer_ratio=self._config.compaction_buffer_ratio,
                compaction_warning_buffer_tokens=(self._config.compaction_warning_buffer_tokens),
            )
            # Promote the static/suffix split into the conversation so the
            # LLM wrapper sends them as two cache-aware blocks.
            if system_prompt_suffix:
                conversation.update_system_prompt(system_prompt_static, dynamic_suffix=system_prompt_suffix)
            accumulator = OutputAccumulator(
                store=self._conversation_store,
                spillover_dir=self._config.spillover_dir,
                max_value_chars=self._config.max_output_value_chars,
                run_id=ctx.effective_run_id,
            )
            start_iteration = 0

            initial_message = self._build_initial_message(ctx)
            # Fire SESSION_START hooks + reminders BEFORE seeding the user's
            # first message so the situational frame (tools/skills manifest,
            # task list, ...) precedes the user's request rather than trailing
            # it. This mirrors the USER_PROMPT_SUBMIT ordering on every
            # subsequent turn (see the drain block below, where the reminder
            # fires before the injection queue is drained) — "cowork style":
            # the queen reads the frame first, then the user's latest message.
            await self._run_hooks("session_start", conversation, trigger=initial_message)
            await self._fire_reminder(ReminderPoint.SESSION_START, ctx, conversation)

            if initial_message:
                # Stamp with arrival time so the conversation has a
                # temporal anchor for the first turn, matching the
                # stamping done by drain_injection_queue for every
                # subsequent event.
                _stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
                await conversation.add_user_message(f"[{_stamp}] {initial_message}")

        # 2a. Guard: ensure at least one non-system message exists.
        # A restored conversation may have 0 messages if phase_id filtering
        # removes them all, or if a prior run stored metadata without messages
        # (e.g. node that failed before the first LLM call).
        if conversation.message_count == 0:
            initial_message = self._build_initial_message(ctx)
            if not initial_message:
                initial_message = "Hello"
            _stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
            await conversation.add_user_message(f"[{_stamp}] {initial_message}")

        # 2b. Restore spill counter from existing files (resume safety)
        self._restore_spill_counter()

        # 3. Build tool list: node tools + synthetic framework tools + delegate tools
        tools = list(ctx.available_tools)
        # collect_result lets the agent retrieve results of backgrounded tools
        # (LoopConfig.background_tools). Added whenever any background tool is
        # configured, independent of user-IO support, since the caller — not an
        # MCP server — handles it.
        if getattr(self._config, "background_tools", None):
            tools.append(build_collect_result_tool())
        if ctx.supports_direct_user_io:
            tools.append(self._build_ask_user_tool())
            # Single CLI-style credentials tool — browse/collect/attach/reveal.
            # Queen-facing: it parks the loop for the secure collect form and
            # writes session attachments, both of which need loop internals.
            tools.append(build_credentials_tool())
            # Sentinel setup — store channel tokens + configure/test per-colony
            # notifications (the desktop Sentinel connector's API), so the queen
            # can finish a browser-driven Slack/Telegram setup without bouncing
            # the user back to the form.
            tools.append(build_sentinel_setup_tool())
            # ``suggest_colony`` is queen-only AND independent-phase-only.
            # It is sourced via the queen's dynamic_tools_provider —
            # ``QueenPhaseState.independent_tools`` carries it, so it
            # disappears automatically when the queen switches to colony
            # phase. The dispatch site (search for ``suggest_colony`` in
            # this file) enforces the same gate as defense in depth.
        # Parallel fan-out workers (stream_id="worker:{uuid}") have NO
        # escalation channel — per BRD they fail-fast via report_to_parent
        # and the queen re-dispatches with different parameters or takes
        # over. Escalate stays available to the legacy primary worker
        # (stream_id="worker", no colon — run_agent_with_input style),
        # which still uses it for credential / ambiguity handoffs back
        # to the queen.
        is_parallel_worker = isinstance(stream_id, str) and stream_id.startswith("worker:")
        if stream_id not in ("queen", "judge", "overseer") and not is_parallel_worker:
            tools.append(self._build_escalate_tool())
        # Only parallel workers (stream_id="worker:{uuid}") get report_to_parent.
        # report_schema is optional and not present on every spec type
        # (NodeSpec etc.), so read it defensively — absent means no schema.
        if is_parallel_worker:
            tools.append(build_report_to_parent_tool(getattr(ctx.agent_spec, "report_schema", None) or None))
            # Worker-side searchable tiering: when the spawn wired a
            # ToolTierState (keep-set configured), expose ``search_tools`` so
            # the worker can load deferred schemas on demand — same UX as the
            # queen's, but executed in-loop against this worker's own tier
            # (the registry-registered search_tools closes over the QUEEN's
            # phase_state and must not serve workers).
            if getattr(ctx, "tool_tier_state", None) is not None:
                from framework.tools.tool_tiers import build_search_tools

                _tier_tool, self._worker_search_tools_handler = build_search_tools(ctx.tool_tier_state)
                tools.append(_tier_tool)

        # Hide image-producing tools from text-only models so they never try
        # to call them. Avoids wasted turns + "screenshot failed" lessons
        # getting saved to memory. See framework.llm.capabilities.
        # EXCEPTION: when the model IS on the text-only deny list AND
        # a vision_fallback subagent is configured, leave image tools
        # visible. The post-execution hook in the inner tool loop
        # will route each image_content through the fallback VLM and
        # replace it with a text caption before the main agent sees
        # the result — so the main agent gets captions instead of
        # raw images, rather than losing the tool entirely. We DON'T
        # bypass the filter for vision-capable models (that would be
        # a no-op anyway — the filter doesn't fire for them) and we
        # DON'T bypass it without a configured fallback (the agent
        # would just see raw stripped tool results with no caption).
        _llm_model = ctx.llm.model if ctx.llm else ""
        _text_only_main = _llm_model and not supports_image_tool_results(_llm_model)
        if _text_only_main and get_vision_fallback_model() is not None:
            _hidden_image_tools: list[str] = []
        else:
            tools, _hidden_image_tools = filter_tools_for_model(tools, _llm_model)

        logger.info(
            "[%s] Tools available (%d): %s | direct_user_io=%s | judge=%s | hidden_image_tools=%s",
            node_id,
            len(tools),
            [t.name for t in tools],
            ctx.supports_direct_user_io,
            type(self._judge).__name__ if self._judge else "None",
            _hidden_image_tools,
        )

        # 4. Publish loop started
        await self._publish_loop_started(stream_id, node_id, execution_id)

        # 4a. Start the reminder hub's temporal ticker. Its IdleNudgeSource
        # catches idle gaps the stream-level watchdog can't see — between
        # turns (no _stream_task) and slow TTFT under the 600s ceiling.
        # Stopped in execute()'s finally so cleanup isn't threaded through
        # every return site. The ticker only parks reminders; the loop
        # drains them via _drain_reminder_hub at each iteration boundary.
        self._stream_first_event_at = None
        self._mark_session_progress()
        # Expose the live conversation + context to Sentinel's park-context provider.
        self._conversation = conversation
        self._agent_ctx = ctx
        await self._reminder_hub.start(
            ctx,
            signals_provider=self._loop_signals,
            wake=self._input_ready.set,
        )

        # 5. Stall / doom loop detection state (restored from cursor if resuming)
        recent_responses: list[str] = _restored_recent_responses
        recent_tool_fingerprints: list[list[tuple[str, str]]] = _restored_tool_fingerprints
        pending_input_state: dict[str, Any] | None = _restored_pending_input
        _consecutive_empty_turns: int = 0

        # 6. Main loop
        # The loop ceiling is ``max_iterations + grace_iterations``. The
        # grace iterations (typically 1, only set for workers) are a
        # guaranteed wrap-up phase: dispatch is restricted to
        # ``_GRACE_TERMINAL_TOOLS`` so the agent reports back instead of
        # dying silently when its work budget is exhausted. Queens set
        # grace_iterations=0 → no behavioural change.
        _total_iterations = self._config.max_iterations + self._config.grace_iterations
        logger.debug(
            "[AgentLoop.execute] Entering main loop, start_iteration=%d, max_iterations=%d, grace_iterations=%d",
            start_iteration,
            self._config.max_iterations,
            self._config.grace_iterations,
        )
        for iteration in range(start_iteration, _total_iterations):
            iter_start = time.time()
            # Flip into grace mode once the work budget is spent — by EITHER
            # the iteration budget OR the cumulative (lifetime) tool-call
            # budget (LoopConfig.tool_call_lifetime_budget; 0 disables). The
            # dispatch loop in _run_turn_loop reads ``self._in_grace`` to gate
            # non-terminal tools; the boundary-time reminder below tells the
            # model what's about to happen (and which budget tripped).
            _lifetime_budget = self._config.tool_call_lifetime_budget
            budget_exhausted = _lifetime_budget > 0 and self._tool_calls_used >= _lifetime_budget
            self._in_grace = iteration >= self._config.max_iterations or budget_exhausted
            if self._in_grace and self._grace_start_iteration is None:
                self._grace_start_iteration = iteration
            # Cap the wind-down to ``grace_iterations`` turn(s) from whenever
            # grace began, under either trigger. For iteration-triggered grace
            # this is a no-op: grace_start == max_iterations, so the bound is
            # max_iterations + grace_iterations == _total_iterations (the
            # existing range ceiling). For budget-triggered (early) grace it
            # stops the loop from spinning the remaining — possibly hundreds
            # of — iterations in tool-restricted mode. Falls through to the
            # "max iterations exhausted" exit below.
            # ``not self._report_terminated``: if the worker already called
            # report_to_parent during its grace turn, let the report-terminated
            # early-exit below own the exit (success + the explicit report)
            # rather than preempting it with the max-iterations failure path.
            if (
                self._grace_start_iteration is not None
                and not self._report_terminated
                and iteration - self._grace_start_iteration >= max(1, self._config.grace_iterations)
            ):
                logger.info(
                    "[AgentLoop.execute] grace wind-down complete at iteration=%d (grace_start=%d, grace_iterations=%d); exiting",
                    iteration,
                    self._grace_start_iteration,
                    self._config.grace_iterations,
                )
                break
            logger.debug(
                "[AgentLoop.execute] iteration=%d starting (in_grace=%s, tool_calls_used=%d)",
                iteration,
                self._in_grace,
                self._tool_calls_used,
            )
            # Inject any reminders the hub's temporal ticker parked while
            # the previous turn ran (idle nudges, …) — done here, on the
            # loop coroutine, so conversation writes don't race the loop.
            # A drained reminder counts as fresh input below (it breaks a
            # pending-input wait), so the agent acts on it.
            drained_reminders = await self._drain_reminder_hub(conversation, ctx)
            # On the first grace iteration, inject the one-shot reminder
            # explaining the restriction. Idempotent: ``_grace_announced``
            # guards against duplicate injections if the loop ever revisits
            # the same iteration index (resume / inner-loop restart paths).
            # ``not self._report_terminated``: a worker whose FINAL counted
            # call was its report (landing used == budget) is a clean
            # self-terminated success — announcing grace here would bump
            # tool_lifetime_budget_grace and falsely mark the result
            # budget_limited (excluding a legitimate sample from colony
            # budget adaptation and baiting a pointless resume). The
            # report-terminated early-exit below owns that path.
            if self._in_grace and not self._grace_announced and not self._report_terminated:
                self._grace_announced = True
                self._bump("grace_iteration_entered")
                # Distinguish the trigger so the reminder body matches reality:
                # a tool-call-budget wind-down (the worker still has iterations
                # left) reads differently from an iteration-budget wind-down.
                if budget_exhausted:
                    self._bump("tool_lifetime_budget_grace")
                _grace_body = _TOOL_BUDGET_GRACE_REMINDER_BODY if budget_exhausted else _GRACE_REMINDER_BODY
                await self._inject_reminder(
                    Reminder(
                        source="grace_iteration",
                        body=_grace_body,
                        meta={
                            "iteration": iteration,
                            "max_iterations": self._config.max_iterations,
                            "grace_iterations": self._config.grace_iterations,
                            "tool_call_lifetime_budget": _lifetime_budget,
                            "tool_calls_used": self._tool_calls_used,
                            "trigger": "tool_call_budget" if budget_exhausted else "iterations",
                        },
                    ),
                    conversation,
                    ctx,
                )
            # Crossing an iteration boundary counts as progress — judge
            # work, setup, etc. between turns shouldn't accrue idle time.
            self._mark_session_progress()
            # The loop is making forward progress — re-assert EXECUTING.
            # Idempotent: only emits when transitioning back from a park or
            # a stream stall, so this covers between-turn / judge / compaction
            # work without spamming events.
            await self._set_activity(ctx, LoopActivity.EXECUTING)

            # 6a-pre. Early exit for workers that called report_to_parent on
            # the previous turn. The report_to_parent handler sets this
            # flag; the loop finishes the current turn (so the LLM sees
            # the acknowledgement tool result) and exits at the top of the
            # next iteration. Parallel workers terminate here.
            if self._report_terminated:
                latency_ms = int((time.time() - start_time) * 1000)
                logger.info(
                    "[%s] iter=%d: worker terminated via report_to_parent",
                    node_id,
                    iteration,
                )
                await self._publish_loop_completed(stream_id, node_id, iteration, execution_id)
                return AgentResult(
                    success=True,
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=None,
                )

            # 6a. Check pause (no current-iteration data yet — only log_node_complete needed)
            if await self._check_pause(ctx, conversation, iteration):
                latency_ms = int((time.time() - start_time) * 1000)
                if ctx.runtime_logger:
                    ctx.runtime_logger.log_node_complete(
                        node_id=node_id,
                        node_name=ctx.agent_spec.name,
                        node_type="event_loop",
                        success=True,
                        total_steps=iteration,
                        tokens_used=total_input_tokens + total_output_tokens,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        latency_ms=latency_ms,
                        exit_status="paused",
                        accept_count=_accept_count,
                        retry_count=_retry_count,
                        escalate_count=_escalate_count,
                        continue_count=_continue_count,
                    )
                return AgentResult(
                    success=True,
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=None,
                )

            # 6b. Drain injection queue
            # Fire USER_PROMPT_SUBMIT reminders BEFORE draining so any
            # reminder body (active workers, task snapshot, ...) lands in
            # the conversation as context preceding the user's message —
            # the queen reads the situational frame first, then the user's
            # latest request. Peek via queue.empty() instead of acting on
            # drained_injections after the fact; the peek-then-drain
            # ordering is async-single-loop so there is no real race.
            will_drain = not self._injection_queue.empty()
            if will_drain:
                await self._fire_reminder(ReminderPoint.USER_PROMPT_SUBMIT, ctx, conversation)
            logger.debug("[AgentLoop.execute] iteration=%d: draining injection queue...", iteration)
            drained_injections = await self._drain_injection_queue(conversation, ctx)
            logger.debug(
                "[AgentLoop.execute] iteration=%d: drained %d injections",
                iteration,
                drained_injections,
            )
            # 6b1. Drain trigger queue (framework-level signals)
            drained_triggers = await self._drain_trigger_queue(conversation)
            logger.debug(
                "[AgentLoop.execute] iteration=%d: drained %d triggers",
                iteration,
                drained_triggers,
            )

            # Resume blocked ask_user/auto-block waits durably across restarts.
            # If the node was parked for input and no new message has been
            # injected yet, re-enter the wait instead of continuing the last
            # assistant turn with a synthetic prompt.
            if pending_input_state is not None:
                _is_cold_resume = False
                # A reminder drained this iteration is respected like fresh
                # user input — it breaks the pending-input wait so the agent
                # acts on the reminder instead of silently re-parking.
                if drained_injections > 0 or drained_triggers > 0 or drained_reminders > 0:
                    pending_input_state = None
                    await self._write_cursor(
                        ctx,
                        conversation,
                        accumulator,
                        iteration,
                        recent_responses=recent_responses,
                        recent_tool_fingerprints=recent_tool_fingerprints,
                        pending_input=None,
                    )
                else:
                    logger.info(
                        "[%s] iter=%d: restored pending input wait (emit_client_request=%s)",
                        node_id,
                        iteration,
                        pending_input_state.get("emit_client_request", True),
                    )
                    got_input = await self._await_user_input(
                        ctx,
                        reason=self._park_reason_from_cursor(pending_input_state),
                        questions=pending_input_state.get("questions"),
                        credential_form=pending_input_state.get("credential_form"),
                        emit_client_request=bool(pending_input_state.get("emit_client_request", True)),
                    )
                    logger.info(
                        "[%s] iter=%d: restored wait unblocked, got_input=%s",
                        node_id,
                        iteration,
                        got_input,
                    )
                    if not got_input:
                        await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                        latency_ms = int((time.time() - start_time) * 1000)
                        return AgentResult(
                            success=True,
                            output=accumulator.to_dict(),
                            tokens_used=total_input_tokens + total_output_tokens,
                            latency_ms=latency_ms,
                            conversation=None,
                        )
                    if self._injection_queue.empty() and self._trigger_queue.empty():
                        logger.info(
                            "[%s] iter=%d: pending-input wait woke without queued input; re-waiting",
                            node_id,
                            iteration,
                        )
                        # The request was already published on the wait we
                        # just woke from — re-wait silently so we don't spam
                        # duplicate CLIENT_INPUT_REQUESTED events for the one
                        # still-open question.
                        pending_input_state["emit_client_request"] = False
                        continue
                    # Input arrived — clear the persisted pending-input
                    # marker NOW. Deferring to the next iteration's 6g
                    # checkpoint risks an early `continue` (compaction /
                    # empty-response guard / stall handling) skipping it,
                    # leaving a stale pending_input on disk that re-pops
                    # the already-answered question on the next cold resume.
                    pending_input_state = None
                    await self._write_cursor(
                        ctx,
                        conversation,
                        accumulator,
                        iteration,
                        recent_responses=recent_responses,
                        recent_tool_fingerprints=recent_tool_fingerprints,
                        pending_input=None,
                    )
                    continue

            # 6b1½. Cold-resume mid-turn guard.
            # If the queen was mid-LLM-turn when the runtime died (no
            # pending_input persisted), don't silently resume the in-flight
            # work — inject a note and park until the user sends a message.
            # Workers are excluded: they should resume autonomously.
            if _is_cold_resume and ctx.supports_direct_user_io:
                _is_cold_resume = False
                if drained_injections == 0 and drained_triggers == 0:
                    logger.info(
                        "[%s] iter=%d: cold resume mid-turn — parking until user input",
                        node_id,
                        iteration,
                    )
                    await conversation.add_user_message(
                        "[System] The session was interrupted (app closed or runtime "
                        "restarted while work was in progress). Waiting for your "
                        "next message before resuming."
                    )
                    pending_input_state = {
                        "reason": ParkReason.COLD_INTERRUPTED.value,
                        "emit_client_request": True,
                    }
                    await self._write_cursor(
                        ctx,
                        conversation,
                        accumulator,
                        iteration,
                        recent_responses=recent_responses,
                        recent_tool_fingerprints=recent_tool_fingerprints,
                        pending_input=pending_input_state,
                    )
                    got_input = await self._await_user_input(
                        ctx,
                        reason=ParkReason.COLD_INTERRUPTED,
                    )
                    if not got_input:
                        await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                        latency_ms = int((time.time() - start_time) * 1000)
                        return AgentResult(
                            success=True,
                            output=accumulator.to_dict(),
                            tokens_used=total_input_tokens + total_output_tokens,
                            latency_ms=latency_ms,
                            conversation=None,
                        )
                    pending_input_state = None
                    await self._write_cursor(
                        ctx,
                        conversation,
                        accumulator,
                        iteration,
                        recent_responses=recent_responses,
                        recent_tool_fingerprints=recent_tool_fingerprints,
                        pending_input=None,
                    )
                    continue

            # 6b2. Dynamic tool refresh (mode switching + mid-session loads).
            # Mirrored inside _run_turn_loop's inner stream loop so a tool
            # loaded via search_tools mid-turn becomes callable immediately.
            self._refresh_dynamic_tools(ctx, tools)

            # 6b3. Dynamic prompt refresh (phase switching / memory refresh)
            if ctx.dynamic_prompt_provider is not None or ctx.dynamic_memory_provider is not None or ctx.dynamic_skills_catalog_provider is not None:
                from framework.agent_loop.prompting import (
                    build_system_prompt_parts_for_context,
                )

                if ctx.dynamic_prompt_provider is not None:
                    _new_prompt = ctx.dynamic_prompt_provider()
                    # When a suffix provider is also wired (Queen's
                    # static/dynamic split), keep the two pieces separate
                    # so the LLM wrapper can emit them as two system
                    # content blocks with a cache breakpoint between them.
                    # An empty suffix is fine — the LLM wrapper falls back
                    # to the single-block system message, which is the
                    # byte-stable shape now that nothing per-turn (recall,
                    # timestamps) lives in the suffix anymore. A CHANGING
                    # suffix here would invalidate the cached history
                    # prefix on every change, so never stamp wall-clock
                    # time into it.
                    _new_suffix = ""
                    if ctx.dynamic_prompt_suffix_provider is not None:
                        try:
                            _new_suffix = ctx.dynamic_prompt_suffix_provider() or ""
                        except Exception:
                            logger.debug(
                                "[%s] dynamic_prompt_suffix_provider raised — treating suffix as empty",
                                node_id,
                                exc_info=True,
                            )
                            _new_suffix = ""
                else:
                    # No dynamic_prompt_provider — rebuild from context.
                    # Use the split builder so the narrative stays outside
                    # the cached prefix.
                    _new_prompt, _new_suffix = build_system_prompt_parts_for_context(ctx)
                _combined_for_compare = f"{_new_prompt}\n\n{_new_suffix}" if _new_suffix else _new_prompt
                if _combined_for_compare != conversation.system_prompt or _new_suffix != conversation.system_prompt_dynamic_suffix:
                    conversation.update_system_prompt(_new_prompt, dynamic_suffix=_new_suffix)
                    logger.info("[%s] Dynamic prompt updated (split)", node_id)

            # 6c. Publish iteration event (with per-iteration metadata when available)
            _iter_meta = None
            if ctx.iteration_metadata_provider is not None:
                try:
                    _iter_meta = ctx.iteration_metadata_provider()
                except Exception:
                    pass
            await self._publish_iteration(
                stream_id,
                node_id,
                iteration,
                execution_id,
                extra_data=_iter_meta,
            )
            # Sync max_context_tokens from live config so mid-session model
            # switches are reflected in compaction decisions and the UI bar.
            # Fallback = this loop's own budget, NOT the global 32k default:
            # when config/catalog don't resolve (local/proxy models), the
            # compaction trigger must agree with the LoopConfig-driven
            # prune/summary budgets instead of collapsing to 32k under them.
            from framework.config import get_max_context_tokens as _live_mct

            conversation._max_context_tokens = _live_mct(fallback=self._config.max_context_tokens)

            await self._publish_context_usage(ctx, conversation, "iteration_start", tools=tools)

            # 6d. Pre-turn compaction check (tiered)
            _compacted_this_iter = False
            if conversation.needs_compaction():
                await self._compact(ctx, conversation, accumulator)
                _compacted_this_iter = True

            # 6e. Run single LLM turn (with transient error retry)
            logger.info(
                "[%s] iter=%d: running LLM turn (msgs=%d)",
                node_id,
                iteration,
                len(conversation.messages),
            )
            logger.debug("[AgentLoop.execute] iteration=%d: entering _run_turn_loop loop", iteration)
            _stream_retry_count = 0
            _capacity_retry_started_at: float | None = None
            _capacity_retry_attempt = 0
            _turn_cancelled = False
            _llm_turn_failed_waiting_input = False
            # Set by the STOP reminder fire below when an energizing source
            # contributed; suppresses this iteration's queen auto-block so the
            # agent gets a turn to act on it. Reset per iteration so it can
            # never hold the loop open across turns.
            _stop_reminder_energized = False
            _turn_t0 = time.monotonic()
            while True:
                try:
                    logger.debug(
                        "[AgentLoop.execute] iteration=%d: calling _run_turn_loop (retry=%d)",
                        iteration,
                        _stream_retry_count,
                    )
                    (
                        assistant_text,
                        real_tool_results,
                        outputs_set,
                        turn_tokens,
                        logged_tool_calls,
                        user_input_requested,
                        queen_input_requested,
                        request_system_prompt,
                        request_messages,
                        _,
                    ) = await self._run_turn_loop(ctx, conversation, tools, iteration, accumulator)
                    logger.debug(
                        "[AgentLoop.execute] iteration=%d: _run_turn_loop completed successfully",
                        iteration,
                    )
                    try:
                        from framework.host.runtime_health import mark_upstream_healthy

                        mark_upstream_healthy()
                    except Exception:
                        pass
                    _turn_ms = int((time.monotonic() - _turn_t0) * 1000)
                    logger.info(
                        "[%s] iter=%d: LLM done (%dms) — text=%d chars, real_tools=%d, outputs_set=%s, tokens=%s, accumulator=%s",
                        node_id,
                        iteration,
                        _turn_ms,
                        len(assistant_text),
                        len(real_tool_results),
                        outputs_set or "[]",
                        turn_tokens,
                        {k: ("set" if v is not None else "None") for k, v in accumulator.to_dict().items()},
                    )
                    total_input_tokens += turn_tokens.get("input", 0)
                    total_output_tokens += turn_tokens.get("output", 0)

                    # Reminder STOP point: the turn loop just ended on a
                    # text-only turn (no tool result to ride a tail on),
                    # so fire STOP as an injected message. Per-turn drift
                    # counting happens inside _run_turn_loop, once per
                    # inner turn. Best-effort — never raises.
                    try:
                        if not real_tool_results:
                            _stop_reminder_energized = await self._fire_reminder(ReminderPoint.STOP, ctx, conversation)
                    except Exception:
                        logger.debug("reminder STOP fire failed", exc_info=True)
                    # Cache-instrumentation hook: hash the system prefix /
                    # suffix and record the rolling-breakpoint anchor index
                    # so post-hoc analysis of events.jsonl can pinpoint
                    # cache anomalies without re-running the session under
                    # DEBUG. ``request_messages`` is the exact list the
                    # provider sent (including system prepended); strip the
                    # system message and feed the rest to the index helper
                    # so the index matches the live request shape.
                    _diag = self._compute_turn_diagnostics(
                        conversation_static=conversation.system_prompt_static,
                        conversation_suffix=conversation.system_prompt_dynamic_suffix,
                        request_messages=request_messages,
                        model=turn_tokens.get("model", ""),
                    )
                    await self._publish_llm_turn_complete(
                        stream_id,
                        node_id,
                        stop_reason=turn_tokens.get("stop_reason", ""),
                        model=turn_tokens.get("model", ""),
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        cached_tokens=turn_tokens.get("cached", 0),
                        cache_creation_tokens=turn_tokens.get("cache_creation", 0),
                        cost_usd=float(turn_tokens.get("cost", 0.0) or 0.0),
                        credits=turn_tokens.get("credits"),
                        execution_id=execution_id,
                        iteration=iteration,
                        system_prefix_sha=_diag["system_prefix_sha"],
                        system_suffix_sha=_diag["system_suffix_sha"],
                        history_anchor_idx=_diag["history_anchor_idx"],
                        message_count=_diag["message_count"],
                    )
                    log_llm_turn(
                        node_id=node_id,
                        stream_id=stream_id,
                        execution_id=execution_id,
                        iteration=iteration,
                        system_prompt=request_system_prompt,
                        messages=request_messages,
                        assistant_text=assistant_text,
                        tool_calls=logged_tool_calls,
                        tool_results=real_tool_results,
                        token_counts=turn_tokens,
                        tools=tools,
                    )

                    break  # success — exit retry loop

                except TurnCancelled:
                    logger.debug("[AgentLoop.execute] iteration=%d: TurnCancelled", iteration)
                    _turn_cancelled = True
                    break

                except Exception as e:
                    logger.debug(
                        "[AgentLoop.execute] iteration=%d: Exception in _run_turn_loop: %s (%s)",
                        iteration,
                        type(e).__name__,
                        str(e)[:200],
                    )
                    # Persistent retry for capacity errors (429/529/overloaded).
                    # Unlike the bounded branch below, this one keeps trying
                    # within a wall-clock budget instead of burning through
                    # five attempts in ~1 minute and giving up. Each attempt
                    # still publishes a retry event so the UI can see us
                    # waiting (the "heartbeat" — no silent stalls).
                    self._bump("llm_turn_exception")
                    if self._is_capacity_error(e) and self._config.capacity_retry_max_seconds > 0:
                        self._bump("capacity_error")
                        now = time.monotonic()
                        if _capacity_retry_started_at is None:
                            _capacity_retry_started_at = now
                        elapsed = now - _capacity_retry_started_at
                        if elapsed < self._config.capacity_retry_max_seconds:
                            _capacity_retry_attempt += 1
                            delay = min(
                                self._config.stream_retry_backoff_base * (2 ** min(_capacity_retry_attempt - 1, 6)),
                                self._config.capacity_retry_max_delay,
                            )
                            logger.warning(
                                "[%s] iter=%d: capacity error (%s), persistent retry #%d after %.1fs (elapsed %.0fs / %.0fs budget): %s",
                                node_id,
                                iteration,
                                type(e).__name__,
                                _capacity_retry_attempt,
                                delay,
                                elapsed,
                                self._config.capacity_retry_max_seconds,
                                str(e)[:200],
                            )
                            if self._event_bus:
                                await self._event_bus.emit_node_retry(
                                    stream_id=stream_id,
                                    node_id=node_id,
                                    retry_count=_capacity_retry_attempt,
                                    max_retries=-1,  # -1 == persistent / unbounded
                                    error=str(e)[:500],
                                    execution_id=execution_id,
                                )
                            await asyncio.sleep(delay)
                            continue  # retry same iteration

                    # Retry transient errors with exponential backoff
                    if self._is_transient_error(e) and _stream_retry_count < self._config.max_stream_retries:
                        self._bump("llm_transient_retry")
                        try:
                            from framework.host.runtime_health import (
                                is_upstream_network_error,
                                mark_upstream_degraded,
                            )

                            if is_upstream_network_error(e):
                                mark_upstream_degraded(f"{type(e).__name__}: {str(e)[:200]}")
                        except Exception:
                            pass
                        _stream_retry_count += 1
                        delay = min(
                            self._config.stream_retry_backoff_base * (2 ** (_stream_retry_count - 1)),
                            self._config.stream_retry_max_delay,
                        )
                        logger.warning(
                            "[%s] iter=%d: transient error (%s), retrying in %.1fs (%d/%d): %s",
                            node_id,
                            iteration,
                            type(e).__name__,
                            delay,
                            _stream_retry_count,
                            self._config.max_stream_retries,
                            str(e)[:200],
                        )
                        if self._event_bus:
                            await self._event_bus.emit_node_retry(
                                stream_id=stream_id,
                                node_id=node_id,
                                retry_count=_stream_retry_count,
                                max_retries=self._config.max_stream_retries,
                                error=str(e)[:500],
                                execution_id=execution_id,
                            )

                        # For malformed tool call errors, inject feedback into
                        # the conversation before retrying.  Retrying with the
                        # same messages is futile — the LLM will reproduce the
                        # same truncated JSON.  The nudge tells it to shorten
                        # its arguments.
                        error_str = str(e).lower()
                        if "failed to parse tool call" in error_str:
                            await conversation.add_user_message(
                                "[System: Your previous tool call had malformed "
                                "JSON arguments (likely truncated). Keep your "
                                "tool call arguments shorter and simpler. Do NOT "
                                "repeat the same long argument — summarize or "
                                "split into multiple calls.]"
                            )

                        await asyncio.sleep(delay)
                        continue  # retry same iteration

                    # Non-transient or retries exhausted.
                    # For queen turns, surface the error and wait
                    # for user input instead of killing the loop.  The user
                    # can retry or adjust the request.
                    if ctx.supports_direct_user_io:
                        error_msg = f"LLM call failed: {e}"
                        _guardrail_phrase = "no endpoints available matching your guardrail restrictions and data policy"
                        if _guardrail_phrase in str(e).lower():
                            error_msg += (
                                " OpenRouter blocked this model under current privacy settings. "
                                "Update https://openrouter.ai/settings/privacy or choose another "
                                "OpenRouter model."
                            )
                        logger.error(
                            "[%s] iter=%d: %s — waiting for user input",
                            node_id,
                            iteration,
                            error_msg,
                        )
                        if self._event_bus:
                            await self._event_bus.emit_node_retry(
                                stream_id=stream_id,
                                node_id=node_id,
                                retry_count=_stream_retry_count,
                                max_retries=self._config.max_stream_retries,
                                error=str(e)[:500],
                                execution_id=execution_id,
                            )
                        # Emit the error via SSE so the frontend renders
                        # it in the chat, then persist it in the conversation.
                        visible_error = f"[Error: {error_msg}. Please try again.]"
                        if self._event_bus and ctx.emits_client_io:
                            await self._event_bus.emit_client_output_delta(
                                stream_id=stream_id,
                                node_id=node_id,
                                content=visible_error,
                                snapshot=visible_error,
                                execution_id=execution_id,
                                iteration=iteration,
                                inner_turn=0,
                            )
                        await conversation.add_assistant_message(visible_error)
                        await self._await_user_input(ctx, reason=ParkReason.LLM_ERROR)
                        _llm_turn_failed_waiting_input = True
                        break  # exit retry loop, continue outer iteration

                    # Non-interactive nodes: crash as before
                    import traceback

                    iter_latency_ms = int((time.time() - iter_start) * 1000)
                    latency_ms = int((time.time() - start_time) * 1000)
                    error_msg = f"LLM call failed: {e}"
                    stack_trace = traceback.format_exc()

                    if ctx.runtime_logger:
                        ctx.runtime_logger.log_step(
                            node_id=node_id,
                            node_type="event_loop",
                            step_index=iteration,
                            error=error_msg,
                            stacktrace=stack_trace,
                            is_partial=True,
                            input_tokens=0,
                            output_tokens=0,
                            latency_ms=iter_latency_ms,
                        )
                        ctx.runtime_logger.log_node_complete(
                            node_id=node_id,
                            node_name=ctx.agent_spec.name,
                            node_type="event_loop",
                            success=False,
                            error=error_msg,
                            stacktrace=stack_trace,
                            total_steps=iteration + 1,
                            tokens_used=total_input_tokens + total_output_tokens,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            latency_ms=latency_ms,
                            exit_status="failure",
                            accept_count=_accept_count,
                            retry_count=_retry_count,
                            escalate_count=_escalate_count,
                            continue_count=_continue_count,
                        )

                    # Re-raise to maintain existing error handling
                    raise

            if _turn_cancelled:
                logger.info("[%s] iter=%d: turn cancelled by user", node_id, iteration)
                if ctx.supports_direct_user_io:
                    # Persist the user-stop park BEFORE we block. Without
                    # this, killing the runtime mid-wait loses both the
                    # park reason and ``_user_stopped`` (they only live in
                    # memory), and the queen would silently auto-resume on
                    # reload. The persisted ``pending_input`` mirrors the
                    # other park sites (line 2498) and replays through the
                    # restored-wait branch at line 1442 on restart.
                    await self._write_cursor(
                        ctx,
                        conversation,
                        accumulator,
                        iteration,
                        recent_responses=recent_responses,
                        recent_tool_fingerprints=recent_tool_fingerprints,
                        pending_input={
                            "reason": ParkReason.USER_STOPPED.value,
                            "emit_client_request": True,
                        },
                    )
                    await self._await_user_input(ctx, reason=ParkReason.USER_STOPPED)
                continue  # back to top of for-iteration loop

            # Queen non-transient LLM failures wait for user input and then
            # continue the outer loop without touching per-turn token vars.
            if _llm_turn_failed_waiting_input:
                continue

            # 6e'. (Removed: feeding turn_tokens["input"] — the cumulative
            # billing sum across all inner LLM calls — into the conversation
            # was the source of fictional 1000%+ usage ratios. The single-
            # prompt size is now reported by the FinishEvent handler inside
            # _run_turn_loop, per LLM call, which is the unit
            # ``max_context_tokens`` and ``usage_ratio()`` actually mean.)

            # 6e''. Post-turn compaction check (catches tool-result bloat).
            # Skip if pre-turn already compacted this iteration — two compactions
            # in one iteration produce back-to-back spillover files and leave the
            # agent disoriented on the very next turn.
            #
            # Also skip when the turn requested user/queen input. Otherwise a
            # large LLM compaction (multi-minute on heavily over-budget
            # conversations) sits between ask_user and the
            # CLIENT_INPUT_REQUESTED emit, so the UI shows nothing for the
            # whole compaction window — looks frozen, the human types
            # something to "wake it up", and that input is then consumed as
            # an answer to a question that was never displayed. The next
            # iteration's pre-turn compaction handles the bloat once the
            # user has actually responded.
            if not _compacted_this_iter and not user_input_requested and not queen_input_requested and conversation.needs_compaction():
                await self._compact(ctx, conversation, accumulator)

            # Reset auto-block grace streak when real work happens
            if real_tool_results or outputs_set:
                _cf_text_only_streak = 0
                _worker_text_only_streak = 0

            # 6e'''. Empty response guard — if the LLM returned nothing
            # (no text, no real tools, no set_output) and all required
            # outputs are already set, accept immediately.  This prevents
            # wasted iterations when the LLM has genuinely finished its
            # work (e.g. after calling set_output in a previous turn).
            truly_empty = not assistant_text and not real_tool_results and not outputs_set and not user_input_requested and not queen_input_requested
            if truly_empty and accumulator is not None:
                missing = self._get_missing_output_keys(accumulator, ctx.agent_spec.output_keys, ctx.agent_spec.nullable_output_keys)
                # Only accept on empty response if the node actually has
                # output_keys that are all satisfied.  Nodes with NO
                # output_keys (e.g. the forever-alive queen) should never
                # be terminated by a ghost empty stream — "missing" is
                # trivially empty when there are no required outputs.
                has_real_outputs = bool(ctx.agent_spec.output_keys)
                if not missing and has_real_outputs:
                    logger.info(
                        "[%s] iter=%d: empty response but all outputs set — accepting",
                        node_id,
                        iteration,
                    )
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                    latency_ms = int((time.time() - start_time) * 1000)
                    return AgentResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                        conversation=None,
                    )
                elif missing:
                    # Ghost empty stream: LLM returned nothing and outputs
                    # are still missing.  The conversation hasn't changed, so
                    # repeating the same call will produce the same empty
                    # result.  Inject a nudge to break the cycle.
                    _consecutive_empty_turns += 1
                    logger.warning(
                        "[%s] iter=%d: empty response with missing outputs %s (consecutive=%d)",
                        node_id,
                        iteration,
                        missing,
                        _consecutive_empty_turns,
                    )
                    if _consecutive_empty_turns >= self._config.stall_detection_threshold:
                        # Persistent ghost stream — fail the node.
                        error_msg = f"Ghost empty stream: {_consecutive_empty_turns} consecutive empty responses with missing outputs {missing}"
                        latency_ms = int((time.time() - start_time) * 1000)
                        if ctx.runtime_logger:
                            ctx.runtime_logger.log_node_complete(
                                node_id=node_id,
                                node_name=ctx.agent_spec.name,
                                node_type="event_loop",
                                success=False,
                                error=error_msg,
                                total_steps=iteration + 1,
                                tokens_used=total_input_tokens + total_output_tokens,
                                input_tokens=total_input_tokens,
                                output_tokens=total_output_tokens,
                                latency_ms=latency_ms,
                                exit_status="ghost_stream",
                                accept_count=_accept_count,
                                retry_count=_retry_count,
                                escalate_count=_escalate_count,
                                continue_count=_continue_count,
                            )
                        raise RuntimeError(error_msg)
                    # First nudge — inject a system message to break the
                    # empty-response cycle.
                    await conversation.add_user_message(
                        "[System: Your response was empty. You have required "
                        f"outputs that are not yet set: {missing}. Review "
                        "your task and call the appropriate tools to make "
                        "progress.]"
                    )
                    continue
                else:
                    # No output_keys and empty response — forever-alive node
                    # got a ghost empty stream.  Nudge like the missing-outputs
                    # path but without failing (no outputs to demand).
                    _consecutive_empty_turns += 1
                    logger.warning(
                        "[%s] iter=%d: empty response on node with no output_keys (consecutive=%d)",
                        node_id,
                        iteration,
                        _consecutive_empty_turns,
                    )
                    if _consecutive_empty_turns >= self._config.stall_detection_threshold:
                        # Persistent ghost — but since this is a forever-alive
                        # node, block for user input instead of crashing.
                        logger.warning(
                            "[%s] iter=%d: %d consecutive empty responses, blocking for user input",
                            node_id,
                            iteration,
                            _consecutive_empty_turns,
                        )
                        await self._await_user_input(ctx, reason=ParkReason.EMPTY_RESPONSES)
                        _consecutive_empty_turns = 0
                    else:
                        await conversation.add_user_message(
                            "[System: Your response was empty. Review the conversation and respond to the user or take action with your tools.]"
                        )
                    continue
            else:
                _consecutive_empty_turns = 0

            # 6f. Stall detection
            recent_responses.append(assistant_text)
            if len(recent_responses) > self._config.stall_detection_threshold:
                recent_responses.pop(0)
            if self._is_stalled(recent_responses):
                await self._publish_stalled(stream_id, node_id, execution_id)
                latency_ms = int((time.time() - start_time) * 1000)
                _continue_count += 1
                if ctx.runtime_logger:
                    iter_latency_ms = int((time.time() - iter_start) * 1000)
                    ctx.runtime_logger.log_step(
                        node_id=node_id,
                        node_type="event_loop",
                        step_index=iteration,
                        verdict="CONTINUE",
                        verdict_feedback="Stall detected before judge evaluation",
                        tool_calls=logged_tool_calls,
                        llm_text=assistant_text,
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        latency_ms=iter_latency_ms,
                    )
                    ctx.runtime_logger.log_node_complete(
                        node_id=node_id,
                        node_name=ctx.agent_spec.name,
                        node_type="event_loop",
                        success=False,
                        error="Node stalled",
                        total_steps=iteration + 1,
                        tokens_used=total_input_tokens + total_output_tokens,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        latency_ms=latency_ms,
                        exit_status="stalled",
                        accept_count=_accept_count,
                        retry_count=_retry_count,
                        escalate_count=_escalate_count,
                        continue_count=_continue_count,
                    )
                return AgentResult(
                    success=False,
                    error=(
                        f"Node stalled: {self._config.stall_detection_threshold} similar "
                        f"responses ({self._config.stall_similarity_threshold * 100:.0f}+"
                        " threshold)"
                    ),
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=None,
                )

            # 6f'. Tool doom loop detection
            # Use logged_tool_calls (persists across inner iterations) and
            # filter to real MCP tools (exclude set_output, ask_user).
            # NOTE: errored tool calls ARE included — a tool that keeps
            # failing with the same args is the canonical doom loop case
            # (e.g. a tool repeatedly hitting the same error).
            mcp_tool_calls = [
                tc
                for tc in logged_tool_calls
                # Exempt tools that legitimately repeat identical calls (polls,
                # idempotent reads, synthetics) — single source of truth in
                # LoopConfig.replay_exempt_tools, shared with the replay breaker.
                if tc.get("tool_name") not in self._config.replay_exempt_tools
            ]
            if mcp_tool_calls:
                fps = self._fingerprint_tool_calls(mcp_tool_calls)
                recent_tool_fingerprints.append(fps)
                threshold = self._config.tool_doom_loop_threshold
                if len(recent_tool_fingerprints) > threshold:
                    recent_tool_fingerprints.pop(0)
                is_doom, doom_desc = self._is_tool_doom_loop(
                    recent_tool_fingerprints,
                )
                if is_doom:
                    logger.warning("[%s] %s", node_id, doom_desc)
                    if self._event_bus:
                        await self._event_bus.emit_tool_doom_loop(
                            stream_id=stream_id,
                            node_id=node_id,
                            description=doom_desc,
                            execution_id=execution_id,
                        )
                    warning_msg = (
                        f"[SYSTEM] {doom_desc}. You are repeating the "
                        "same tool calls with identical arguments. "
                        "Try a different approach or different arguments."
                    )
                    if (
                        not ctx.supports_direct_user_io
                        and not ctx.event_triggered
                        and stream_id not in ("queen", "judge")
                        and self._event_bus is not None
                    ):
                        await self._event_bus.emit_escalation_requested(
                            stream_id=stream_id,
                            node_id=node_id,
                            reason="Tool doom loop detected",
                            context=doom_desc,
                            execution_id=execution_id,
                            request_id=uuid.uuid4().hex,
                        )
                        await conversation.add_user_message("[SYSTEM] Escalated tool doom loop to queen for intervention.")
                        recent_tool_fingerprints.clear()
                        recent_responses.clear()
                    elif ctx.supports_direct_user_io:
                        await conversation.add_user_message(warning_msg)
                        await self._await_user_input(ctx, reason=ParkReason.DOOM_LOOP)
                        recent_tool_fingerprints.clear()
                        recent_responses.clear()
                    else:
                        await conversation.add_user_message(warning_msg)
                        recent_tool_fingerprints.clear()
            else:
                # Text-only turn breaks the doom loop chain
                recent_tool_fingerprints.clear()

            # 6f'. Silent worker detection — tool calls without user-facing text.
            #
            # When the agent makes tool calls but produces no text for the
            # user, it feels like a runaway process.  After a configurable
            # number of consecutive silent turns, inject a nudge asking it
            # to communicate what it's doing and why.
            _has_tools_no_text = bool(real_tool_results) and not assistant_text
            if _has_tools_no_text:
                _silent_tool_streak += 1
                if _silent_tool_streak > 0 and _silent_tool_streak % self._config.silent_tool_streak_threshold == 0:
                    nudge = (
                        "[SYSTEM] You have been calling tools for "
                        f"{_silent_tool_streak} consecutive turns without "
                        "any text output. Continue working, but include a "
                        "brief explanation alongside your next tool calls "
                        "so the user can see what you are doing."
                    )
                    await conversation.add_user_message(nudge)
                    logger.info(
                        "[%s] iter=%d: silent tool streak %d, injected communication nudge",
                        node_id,
                        iteration,
                        _silent_tool_streak,
                    )
            else:
                _silent_tool_streak = 0

            # 6g. Write cursor checkpoint (includes stall/doom state for resume)
            await self._write_cursor(
                ctx,
                conversation,
                accumulator,
                iteration,
                recent_responses=recent_responses,
                recent_tool_fingerprints=recent_tool_fingerprints,
                pending_input=None,
            )

            # 6h. Worker stall detection on text-only turns
            #
            # Workers that produce text without tool calls or set_output
            # get a grace period to plan/think, then are auto-failed.
            # Two paths diverge after grace:
            #   (a) Parallel workers (stream_id="worker:*"): synthesize
            #       report_to_parent(status='failed', summary=…) and
            #       exit cleanly. Per BRD fail-fast model — queen reads
            #       the failure as a [WORKER_REPORT] and re-dispatches.
            #       NO escalation event, NO synchronous wait.
            #   (b) Legacy primary worker (stream_id="worker", no colon):
            #       fall back to the pre-BRD escalation behavior — emit
            #       ESCALATION_REQUESTED and pause for queen guidance.
            #       Kept so existing run_agent_with_input flows that
            #       depend on credential/ambiguity handoffs don't break.
            _is_worker = stream_id not in ("queen", "judge") and not False and not ctx.supports_direct_user_io and self._event_bus is not None
            _is_parallel_worker = isinstance(stream_id, str) and stream_id.startswith("worker:")
            _worker_no_tool_turn = not real_tool_results and not outputs_set and not queen_input_requested and not user_input_requested
            if _is_worker and _worker_no_tool_turn:
                _worker_text_only_streak += 1
                # INFO on each grace turn so observability sees the
                # streak climbing before any auto-fail fires. Useful
                # for tuning worker_escalation_grace_turns (if these
                # land for healthy workers, grace is too tight).
                logger.info(
                    "[%s] stall-grace iter=%d streak=%d/%d stream=%s text_preview=%r",
                    node_id,
                    iteration,
                    _worker_text_only_streak,
                    self._config.worker_escalation_grace_turns,
                    stream_id,
                    (assistant_text or "")[:120],
                )
                if _worker_text_only_streak <= self._config.worker_escalation_grace_turns:
                    _continue_count += 1
                    if ctx.runtime_logger:
                        iter_latency_ms = int((time.time() - iter_start) * 1000)
                        ctx.runtime_logger.log_step(
                            node_id=node_id,
                            node_type="event_loop",
                            step_index=iteration,
                            verdict="CONTINUE",
                            verdict_feedback=(f"Worker stall grace ({_worker_text_only_streak}/{self._config.worker_escalation_grace_turns})"),
                            tool_calls=logged_tool_calls,
                            llm_text=assistant_text,
                            input_tokens=turn_tokens.get("input", 0),
                            output_tokens=turn_tokens.get("output", 0),
                            latency_ms=iter_latency_ms,
                        )
                    continue

                # Grace exhausted.
                if _is_parallel_worker:
                    # Path (a): fail-fast via synthetic report_to_parent.
                    # Build the same payload the LLM would have built,
                    # run it through the same handler, record on the
                    # owning Worker, set _report_terminated. The next
                    # iteration's 6a-pre exits cleanly with success=True
                    # (the worker terminated cleanly — its REPORT just
                    # says status='failed').
                    _preview = (assistant_text or "").strip()
                    if len(_preview) > 1500:
                        _preview = _preview[:1500] + "…"
                    _summary = (
                        f"Auto-failed: {_worker_text_only_streak} consecutive "
                        "text-only turns (no tool calls, no set_output, no "
                        "ask_user). Worker stalled — re-dispatch with "
                        "different parameters or take over." + (f" Last text excerpt: {_preview}" if _preview else "")
                    )
                    # WARNING: a parallel worker is being terminated for
                    # stalling. Loud enough to surface in default
                    # production logs since this is real worker failure
                    # (the queen will need to re-dispatch).
                    logger.warning(
                        "[%s] AUTO-FAIL iter=%d stream=%s exec=%s — parallel worker stalled %d/%d "
                        "consecutive text-only turns; synthesizing report_to_parent(status='failed') "
                        "and terminating. text_preview=%r",
                        node_id,
                        iteration,
                        stream_id,
                        execution_id,
                        _worker_text_only_streak,
                        self._config.worker_escalation_grace_turns,
                        _preview[:240] if _preview else "",
                    )
                    _synthetic_input: dict[str, Any] = {
                        "status": "failed",
                        "summary": _summary,
                        "data": {"auto_fail_reason": "stall_text_only"},
                        "tool_use_id": f"auto_fail_{uuid.uuid4().hex[:12]}",
                    }
                    handle_report_to_parent(_synthetic_input)
                    _normalised = _synthetic_input.get("_normalised", {})
                    _owner = getattr(self, "_owner_worker", None)
                    if _owner is not None:
                        _owner.record_explicit_report(
                            status=_normalised.get("status", "failed"),
                            summary=_normalised.get("summary", _summary),
                            data=_normalised.get("data", {}),
                        )
                    self._report_terminated = True
                    if ctx.runtime_logger:
                        iter_latency_ms = int((time.time() - iter_start) * 1000)
                        ctx.runtime_logger.log_step(
                            node_id=node_id,
                            node_type="event_loop",
                            step_index=iteration,
                            verdict="FAIL",
                            verdict_feedback=(f"Auto-failed: stall {_worker_text_only_streak}/{self._config.worker_escalation_grace_turns}"),
                            tool_calls=logged_tool_calls,
                            llm_text=assistant_text,
                            input_tokens=turn_tokens.get("input", 0),
                            output_tokens=turn_tokens.get("output", 0),
                            latency_ms=iter_latency_ms,
                        )
                    continue

                # Path (b): legacy primary worker — keep escalation.
                # WARNING for symmetry with the parallel-worker path:
                # this is a real intervention (worker is being paused
                # waiting for the queen) and should be visible.
                logger.warning(
                    "[%s] AUTO-ESCALATE iter=%d stream=%s exec=%s — legacy worker stalled %d/%d "
                    "consecutive text-only turns; emitting ESCALATION_REQUESTED and pausing for "
                    "queen guidance. text_preview=%r",
                    node_id,
                    iteration,
                    stream_id,
                    execution_id,
                    _worker_text_only_streak,
                    self._config.worker_escalation_grace_turns,
                    (assistant_text or "")[:240],
                )
                await self._event_bus.emit_escalation_requested(
                    stream_id=stream_id,
                    node_id=node_id,
                    reason="Worker produced text-only turns without progress; auto-escalating",
                    context=assistant_text[:2000] if assistant_text else "",
                    execution_id=execution_id,
                    request_id=uuid.uuid4().hex,
                )
                queen_input_requested = True

            # 6h'. Queen input blocking
            #
            # Two triggers:
            # (a) Explicit ask_user() — blocks, then skips judge (6i).
            #     The LLM intentionally asked a question; judging before the
            #     user answers would inject confusing "missing outputs"
            #     feedback. Works for the queen's interactive turns.
            # (b) Auto-block (queen only) — a text-only turn (no real
            #     tools, no set_output) from the queen node.  Blocks for
            #     the user's response, then falls through to judge so
            #     models stuck in a clarification loop get RETRY feedback.
            #     Workers are autonomous and don't auto-block — they use
            #     ask_user() explicitly when they need input.
            #
            # Turns that include tool calls or set_output are *work*, not
            # conversation — they flow through without blocking.
            _cf_block = False
            _cf_auto = False
            if ctx.supports_direct_user_io:
                if user_input_requested:
                    _cf_block = True
                elif stream_id == "queen" and not real_tool_results and not outputs_set and not _stop_reminder_energized:
                    # Auto-block: only for the queen (conversational node).
                    # Workers are autonomous — they block only on explicit
                    # ask_user().  Turns without tool calls or set_output
                    # (including empty ghost streams) are not work — block
                    # and wait for user input.
                    #
                    # Unless the STOP reminder just injected an energizing
                    # body: parking would leave it unread until the user next
                    # speaks, which for a reminder about something only the
                    # AGENT can do means it never gets read at all. Give the
                    # turn back instead. Bounded — the source's own rate limit
                    # means the next STOP won't re-energize, so this can add
                    # one turn, not a loop.
                    _cf_block = True
                    _cf_auto = True

            if _cf_block:
                # Auto-block grace: when required outputs are still
                # missing and we're within the grace period, skip
                # blocking and continue to the next LLM turn so the
                # judge can apply RETRY pressure on lazy models.
                # Without this, _await_user_input() would block
                # forever since no inject_event is coming.
                #
                # When no outputs are missing (e.g. queen monitoring
                # with output_keys=[]), text-only is legitimate
                # conversation and should always block.
                if _cf_auto:
                    _auto_missing = (
                        self._get_missing_output_keys(
                            accumulator,
                            ctx.agent_spec.output_keys,
                            ctx.agent_spec.nullable_output_keys,
                        )
                        if accumulator is not None
                        else True
                    )
                    if _auto_missing:
                        _cf_text_only_streak += 1
                        if _cf_text_only_streak <= self._config.cf_grace_turns:
                            _continue_count += 1
                            if ctx.runtime_logger:
                                iter_latency_ms = int((time.time() - iter_start) * 1000)
                                ctx.runtime_logger.log_step(
                                    node_id=node_id,
                                    node_type="event_loop",
                                    step_index=iteration,
                                    verdict="CONTINUE",
                                    verdict_feedback=(f"Auto-block grace ({_cf_text_only_streak}/{self._config.cf_grace_turns})"),
                                    tool_calls=logged_tool_calls,
                                    llm_text=assistant_text,
                                    input_tokens=turn_tokens.get("input", 0),
                                    output_tokens=turn_tokens.get("output", 0),
                                    latency_ms=iter_latency_ms,
                                )
                            continue
                        # Beyond grace — block below, then fall
                        # through to judge

                if self._shutdown:
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                    latency_ms = int((time.time() - start_time) * 1000)
                    _continue_count += 1
                    if ctx.runtime_logger:
                        iter_latency_ms = int((time.time() - iter_start) * 1000)
                        ctx.runtime_logger.log_step(
                            node_id=node_id,
                            node_type="event_loop",
                            step_index=iteration,
                            verdict="CONTINUE",
                            verdict_feedback="Shutdown signaled (queen interaction)",
                            tool_calls=logged_tool_calls,
                            llm_text=assistant_text,
                            input_tokens=turn_tokens.get("input", 0),
                            output_tokens=turn_tokens.get("output", 0),
                            latency_ms=iter_latency_ms,
                        )
                        ctx.runtime_logger.log_node_complete(
                            node_id=node_id,
                            node_name=ctx.agent_spec.name,
                            node_type="event_loop",
                            success=True,
                            total_steps=iteration + 1,
                            tokens_used=total_input_tokens + total_output_tokens,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            latency_ms=latency_ms,
                            exit_status="success",
                            accept_count=_accept_count,
                            retry_count=_retry_count,
                            escalate_count=_escalate_count,
                            continue_count=_continue_count,
                        )
                    return AgentResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                        conversation=None,
                    )

                logger.info(
                    "[%s] iter=%d: blocking for user input (auto=%s)...",
                    node_id,
                    iteration,
                    _cf_auto,
                )
                # Pull the pending questions array set by the ask_user
                # handler (a 1-item list for a single question, 2-8 for a
                # batch). None for auto-block turns with no explicit ask.
                pending_qs = getattr(self, "_pending_questions", None)
                pending_colony = getattr(self, "_pending_colony_suggestion", None)
                pending_pivot = getattr(self, "_pending_colony_pivot", None)
                pending_credential_form = getattr(self, "_pending_credential_form", None)
                self._pending_questions = None
                self._pending_colony_suggestion = None
                self._pending_colony_pivot = None
                self._pending_credential_form = None
                # _cf_auto marks an auto-block: a clean text-only queen turn
                # with no explicit ask — a *successful end of turn*, parked
                # for the next user message. An explicit ask_user turn
                # (_cf_auto False) carries a real pending question.
                if pending_colony or pending_pivot:
                    _ask_reason = ParkReason.COLONY_SUGGESTION
                elif pending_credential_form:
                    _ask_reason = ParkReason.CREDENTIAL_FORM
                elif _cf_auto:
                    _ask_reason = ParkReason.TURN_DONE
                else:
                    _ask_reason = ParkReason.ASK_USER
                pending_input_state = {
                    "questions": pending_qs,
                    "colony_suggestion": pending_colony,
                    "colony_pivot": pending_pivot,
                    "credential_form": pending_credential_form,
                    "emit_client_request": True,
                    "reason": _ask_reason.value,
                }
                await self._write_cursor(
                    ctx,
                    conversation,
                    accumulator,
                    iteration,
                    recent_responses=recent_responses,
                    recent_tool_fingerprints=recent_tool_fingerprints,
                    pending_input=pending_input_state,
                )
                got_input = await self._await_user_input(
                    ctx,
                    reason=_ask_reason,
                    questions=pending_qs,
                    colony_suggestion=pending_colony,
                    colony_pivot=pending_pivot,
                    credential_form=pending_credential_form,
                )
                logger.info("[%s] iter=%d: unblocked, got_input=%s", node_id, iteration, got_input)
                if not got_input:
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                    latency_ms = int((time.time() - start_time) * 1000)
                    _continue_count += 1
                    if ctx.runtime_logger:
                        iter_latency_ms = int((time.time() - iter_start) * 1000)
                        ctx.runtime_logger.log_step(
                            node_id=node_id,
                            node_type="event_loop",
                            step_index=iteration,
                            verdict="CONTINUE",
                            verdict_feedback="No input received (shutdown during wait)",
                            tool_calls=logged_tool_calls,
                            llm_text=assistant_text,
                            input_tokens=turn_tokens.get("input", 0),
                            output_tokens=turn_tokens.get("output", 0),
                            latency_ms=iter_latency_ms,
                        )
                        ctx.runtime_logger.log_node_complete(
                            node_id=node_id,
                            node_name=ctx.agent_spec.name,
                            node_type="event_loop",
                            success=True,
                            total_steps=iteration + 1,
                            tokens_used=total_input_tokens + total_output_tokens,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            latency_ms=latency_ms,
                            exit_status="success",
                            accept_count=_accept_count,
                            retry_count=_retry_count,
                            escalate_count=_escalate_count,
                            continue_count=_continue_count,
                        )
                    return AgentResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                        conversation=None,
                    )

                if self._injection_queue.empty() and self._trigger_queue.empty():
                    logger.info(
                        "[%s] iter=%d: input wait woke without queued input; continuing to wait",
                        node_id,
                        iteration,
                    )
                    # Request already published — the next iteration re-enters
                    # the restored-wait path above, which must re-wait silently
                    # rather than re-emit a duplicate for the same question.
                    pending_input_state["emit_client_request"] = False
                    continue

                pending_input_state = None

                recent_responses.clear()

                # Input arrived — clear the persisted pending-input marker
                # NOW rather than deferring to this iteration's 6g cursor
                # checkpoint, which an early `continue` (post-turn
                # compaction / empty-response guard / stall handling) can
                # skip. A stale pending_input on disk re-pops the
                # already-answered question on the next cold resume.
                await self._write_cursor(
                    ctx,
                    conversation,
                    accumulator,
                    iteration,
                    recent_responses=recent_responses,
                    recent_tool_fingerprints=recent_tool_fingerprints,
                    pending_input=None,
                )

                # -- Judge-skip decision after queen blocking --
                #
                # Explicit ask_user: skip judge while the queen is
                # still gathering information from the user.  BUT if
                # all required outputs have already been set, don't
                # skip -- fall through to the judge so it can accept.
                if not _cf_auto:
                    _missing = (
                        self._get_missing_output_keys(
                            accumulator,
                            ctx.agent_spec.output_keys,
                            ctx.agent_spec.nullable_output_keys,
                        )
                        if accumulator is not None
                        else True
                    )
                    _outputs_complete = not _missing
                    if not _outputs_complete:
                        _cf_text_only_streak = 0
                        _continue_count += 1
                        self._log_skip_judge(
                            ctx,
                            node_id,
                            iteration,
                            "Blocked for ask_user input (skip judge)",
                            logged_tool_calls,
                            assistant_text,
                            turn_tokens,
                            iter_start,
                        )
                        continue
                    # All outputs set -- fall through to judge

                # Auto-block beyond grace -- fall through to judge (6i).
                # The queen's runtime AgentSpec sets skip_judge=True in
                # queen_orchestrator.py, so the judge short-circuits to
                # RETRY (no feedback) and the loop continues cleanly.

            # 6h''. Worker wait for queen guidance
            # When a worker escalates, pause here and skip judge evaluation
            # until the queen injects guidance.
            if queen_input_requested:
                if self._shutdown:
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                    latency_ms = int((time.time() - start_time) * 1000)
                    _continue_count += 1
                    self._log_skip_judge(
                        ctx,
                        node_id,
                        iteration,
                        "Shutdown signaled (waiting for queen input)",
                        logged_tool_calls,
                        assistant_text,
                        turn_tokens,
                        iter_start,
                    )
                    if ctx.runtime_logger:
                        ctx.runtime_logger.log_node_complete(
                            node_id=node_id,
                            node_name=ctx.agent_spec.name,
                            node_type="event_loop",
                            success=True,
                            total_steps=iteration + 1,
                            tokens_used=total_input_tokens + total_output_tokens,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            latency_ms=latency_ms,
                            exit_status="success",
                            accept_count=_accept_count,
                            retry_count=_retry_count,
                            escalate_count=_escalate_count,
                            continue_count=_continue_count,
                        )
                    return AgentResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                        conversation=None,
                    )

                logger.info("[%s] iter=%d: waiting for queen input...", node_id, iteration)
                pending_input_state = {
                    "prompt": "",
                    "options": None,
                    "questions": None,
                    "emit_client_request": False,
                    "reason": ParkReason.AWAITING_QUEEN.value,
                }
                await self._write_cursor(
                    ctx,
                    conversation,
                    accumulator,
                    iteration,
                    recent_responses=recent_responses,
                    recent_tool_fingerprints=recent_tool_fingerprints,
                    pending_input=pending_input_state,
                )
                got_input = await self._await_user_input(ctx, reason=ParkReason.AWAITING_QUEEN, emit_client_request=False)
                logger.info(
                    "[%s] iter=%d: queen wait unblocked, got_input=%s",
                    node_id,
                    iteration,
                    got_input,
                )
                if not got_input:
                    # Blocked by missing user input - emit escalation before returning
                    if self._event_bus:
                        await self._event_bus.emit_escalation_requested(
                            stream_id=stream_id,
                            node_id=node_id,
                            reason="Blocked waiting for queen guidance - no input received",
                            context=("Worker escalated but received no queen guidance before shutdown"),
                            execution_id=execution_id,
                            request_id=uuid.uuid4().hex,
                        )
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                    latency_ms = int((time.time() - start_time) * 1000)
                    _continue_count += 1
                    self._log_skip_judge(
                        ctx,
                        node_id,
                        iteration,
                        "No queen input received (shutdown during wait)",
                        logged_tool_calls,
                        assistant_text,
                        turn_tokens,
                        iter_start,
                    )
                    if ctx.runtime_logger:
                        ctx.runtime_logger.log_node_complete(
                            node_id=node_id,
                            node_name=ctx.agent_spec.name,
                            node_type="event_loop",
                            success=True,
                            total_steps=iteration + 1,
                            tokens_used=total_input_tokens + total_output_tokens,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            latency_ms=latency_ms,
                            exit_status="success",
                            accept_count=_accept_count,
                            retry_count=_retry_count,
                            escalate_count=_escalate_count,
                            continue_count=_continue_count,
                        )
                    return AgentResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                        conversation=None,
                    )

                if self._injection_queue.empty() and self._trigger_queue.empty():
                    logger.info(
                        "[%s] iter=%d: queen-input wait woke without queued guidance; re-waiting",
                        node_id,
                        iteration,
                    )
                    continue

                pending_input_state = None

                recent_responses.clear()
                _cf_text_only_streak = 0
                _worker_text_only_streak = 0
                _continue_count += 1
                self._log_skip_judge(
                    ctx,
                    node_id,
                    iteration,
                    "Blocked for queen input (skip judge)",
                    logged_tool_calls,
                    assistant_text,
                    turn_tokens,
                    iter_start,
                )
                continue

            # 6i. Judge evaluation
            should_judge = (
                False or (iteration + 1) % self._config.judge_every_n_turns == 0 or not real_tool_results  # no real tool calls = natural stop
            )

            logger.info("[%s] iter=%d: 6i should_judge=%s", node_id, iteration, should_judge)
            if not should_judge:
                # Gap C: unjudged iteration — log as CONTINUE
                _continue_count += 1
                self._log_skip_judge(
                    ctx,
                    node_id,
                    iteration,
                    "Unjudged (judge_every_n_turns skip)",
                    logged_tool_calls,
                    assistant_text,
                    turn_tokens,
                    iter_start,
                )
                continue

            # Judge evaluation (should_judge is always True here)
            verdict = await self._judge_turn(
                ctx,
                conversation,
                accumulator,
                assistant_text,
                real_tool_results,
                iteration,
            )
            fb_preview = (verdict.feedback or "")[:200]
            logger.info(
                "[%s] iter=%d: judge verdict=%s feedback=%r",
                node_id,
                iteration,
                verdict.action,
                fb_preview,
            )

            # Publish judge verdict event
            judge_type = "custom" if self._judge is not None else "implicit"
            await self._publish_judge_verdict(
                stream_id,
                node_id,
                action=verdict.action,
                feedback=fb_preview,
                judge_type=judge_type,
                iteration=iteration,
                execution_id=execution_id,
            )

            if verdict.action == "ACCEPT":
                # Check for missing output keys
                missing = self._get_missing_output_keys(accumulator, ctx.agent_spec.output_keys, ctx.agent_spec.nullable_output_keys)
                if missing and self._judge is not None:
                    hint = (
                        f"Task incomplete. Required outputs not yet produced: {missing}. Follow your system prompt instructions to complete the work."
                    )
                    logger.info(
                        "[%s] iter=%d: ACCEPT but missing keys %s",
                        node_id,
                        iteration,
                        missing,
                    )
                    await conversation.add_user_message(hint)
                    # Gap D: log ACCEPT-with-missing-keys as RETRY
                    _retry_count += 1
                    if ctx.runtime_logger:
                        iter_latency_ms = int((time.time() - iter_start) * 1000)
                        ctx.runtime_logger.log_step(
                            node_id=node_id,
                            node_type="event_loop",
                            step_index=iteration,
                            verdict="RETRY",
                            verdict_feedback=(f"Judge accepted but missing output keys: {missing}"),
                            tool_calls=logged_tool_calls,
                            llm_text=assistant_text,
                            input_tokens=turn_tokens.get("input", 0),
                            output_tokens=turn_tokens.get("output", 0),
                            latency_ms=iter_latency_ms,
                        )
                    continue

                # Exit point 5: Judge ACCEPT — log step + log_node_complete
                # Write outputs to data buffer
                for key, value in accumulator.to_dict().items():
                    ctx.input_data[key] = value

                await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                latency_ms = int((time.time() - start_time) * 1000)
                _accept_count += 1
                if ctx.runtime_logger:
                    iter_latency_ms = int((time.time() - iter_start) * 1000)
                    ctx.runtime_logger.log_step(
                        node_id=node_id,
                        node_type="event_loop",
                        step_index=iteration,
                        verdict="ACCEPT",
                        verdict_feedback=verdict.feedback or "",
                        tool_calls=logged_tool_calls,
                        llm_text=assistant_text,
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        latency_ms=iter_latency_ms,
                    )
                    ctx.runtime_logger.log_node_complete(
                        node_id=node_id,
                        node_name=ctx.agent_spec.name,
                        node_type="event_loop",
                        success=True,
                        total_steps=iteration + 1,
                        tokens_used=total_input_tokens + total_output_tokens,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        latency_ms=latency_ms,
                        exit_status="success",
                        accept_count=_accept_count,
                        retry_count=_retry_count,
                        escalate_count=_escalate_count,
                        continue_count=_continue_count,
                    )
                return AgentResult(
                    success=True,
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=None,
                )

            elif verdict.action == "ESCALATE":
                # Exit point 6: Judge ESCALATE — log step + log_node_complete
                await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                latency_ms = int((time.time() - start_time) * 1000)
                _escalate_count += 1
                if ctx.runtime_logger:
                    iter_latency_ms = int((time.time() - iter_start) * 1000)
                    ctx.runtime_logger.log_step(
                        node_id=node_id,
                        node_type="event_loop",
                        step_index=iteration,
                        verdict="ESCALATE",
                        verdict_feedback=verdict.feedback or "",
                        tool_calls=logged_tool_calls,
                        llm_text=assistant_text,
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        latency_ms=iter_latency_ms,
                    )
                    ctx.runtime_logger.log_node_complete(
                        node_id=node_id,
                        node_name=ctx.agent_spec.name,
                        node_type="event_loop",
                        success=False,
                        error=f"Judge escalated: {verdict.feedback or 'no feedback'}",
                        total_steps=iteration + 1,
                        tokens_used=total_input_tokens + total_output_tokens,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        latency_ms=latency_ms,
                        exit_status="escalated",
                        accept_count=_accept_count,
                        retry_count=_retry_count,
                        escalate_count=_escalate_count,
                        continue_count=_continue_count,
                    )
                return AgentResult(
                    success=False,
                    error=f"Judge escalated: {verdict.feedback or 'no feedback'}",
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=None,
                )

            elif verdict.action == "RETRY":
                _retry_count += 1
                if ctx.runtime_logger:
                    iter_latency_ms = int((time.time() - iter_start) * 1000)
                    ctx.runtime_logger.log_step(
                        node_id=node_id,
                        node_type="event_loop",
                        step_index=iteration,
                        verdict="RETRY",
                        verdict_feedback=verdict.feedback or "",
                        tool_calls=logged_tool_calls,
                        llm_text=assistant_text,
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        latency_ms=iter_latency_ms,
                    )
                if verdict.feedback is not None:
                    fb = verdict.feedback or "[Judge returned RETRY without feedback]"
                    await conversation.add_user_message(f"[Judge feedback]: {fb}")
                continue

        # 7. Max iterations exhausted
        await self._publish_loop_completed(stream_id, node_id, self._config.max_iterations, execution_id)
        latency_ms = int((time.time() - start_time) * 1000)
        if ctx.runtime_logger:
            ctx.runtime_logger.log_node_complete(
                node_id=node_id,
                node_name=ctx.agent_spec.name,
                node_type="event_loop",
                success=False,
                error=f"Max iterations ({self._config.max_iterations}) reached without acceptance",
                total_steps=self._config.max_iterations,
                tokens_used=total_input_tokens + total_output_tokens,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                latency_ms=latency_ms,
                exit_status="failure",
                accept_count=_accept_count,
                retry_count=_retry_count,
                escalate_count=_escalate_count,
                continue_count=_continue_count,
            )
        return self._finalize_result(
            AgentResult(
                success=False,
                error=(f"Max iterations ({self._config.max_iterations}) reached without acceptance"),
                output=accumulator.to_dict(),
                tokens_used=total_input_tokens + total_output_tokens,
                latency_ms=latency_ms,
                conversation=None,
            ),
            "max_iterations",
        )

    async def inject_event(
        self,
        content: str,
        *,
        is_client_input: bool = False,
        image_content: list[dict[str, Any]] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Inject an external event or user input into the running loop.

        The content becomes a user message prepended to the next iteration.
        Thread-safe via asyncio.Queue.
        Always unblocks _await_user_input() so the node processes the
        message promptly — both real user input and external events
        (e.g. worker ask_user forwarded via queenContext) need to wake
        the node.

        Args:
            content: The message text.
            is_client_input: True when the message originates from a real
                human user (e.g. /chat endpoint), False for external events
                (e.g. worker question forwarded by the frontend).  Controls
                message formatting in _drain_injection_queue, not wake behavior.
            image_content: Optional list of OpenAI-style image blocks to attach.
            correlation_id: Optional id linking this message to the
                CLIENT_INPUT_RECEIVED event already emitted for it, so the
                drain can emit a matching CLIENT_INPUT_COMMITTED (true
                injection time) the UI can reconcile against.
        """
        logger.debug(
            "[AgentLoop.inject_event] content_len=%d, is_client_input=%s, has_images=%s, queue_size_before=%d",
            len(content) if content else 0,
            is_client_input,
            bool(image_content),
            self._injection_queue.qsize() if hasattr(self._injection_queue, "qsize") else -1,
        )
        # Real input arriving lifts an explicit user-stop — the loop is about
        # to run a turn on this message, so it is no longer "stopped".
        self._user_stopped = False
        # A real user message starts a fresh response cycle: re-arm the
        # idle-nudge per-variant caps so each may nudge again.
        if is_client_input:
            self._idle_nudge_source.reset()
            # Sentinel: re-arm the escalation source's per-park de-dup, and
            # close any open escalation for this session — the user just
            # answered (in-app or via a routed messaging reply).
            self._escalation_source.reset()
            self._notify_sentinel_local_resume()
        try:
            await self._injection_queue.put((content, is_client_input, image_content, correlation_id))
            logger.debug("[AgentLoop.inject_event] Message queued successfully")
        except Exception as e:
            logger.exception("[AgentLoop.inject_event] Failed to queue message: %s", e)
            raise
        try:
            self._input_ready.set()
            logger.debug("[AgentLoop.inject_event] _input_ready.set() called")
        except Exception as e:
            logger.exception("[AgentLoop.inject_event] Failed to set _input_ready: %s", e)
            raise

    async def inject_trigger(self, trigger: TriggerEvent) -> None:
        """Inject a framework-level trigger into the running queen loop.

        Triggers are queued separately from user messages and drained
        atomically via _drain_trigger_queue().
        """
        await self._trigger_queue.put(trigger)
        self._input_ready.set()

    def signal_shutdown(self) -> None:
        """Signal the node to exit its loop cleanly.

        Unblocks any pending _await_user_input() call and causes
        the loop to exit on the next check.
        """
        self._shutdown = True
        self._input_ready.set()

    @property
    def activity(self) -> LoopActivity:
        """The loop's current top-level activity state.

        Public read surface so callers (e.g. the queen orchestrator's
        background recall injection) can tell whether the loop is mid-turn
        without reaching into ``_activity`` directly.
        """
        return self._activity

    @property
    def tool_calls_used(self) -> int:
        """Cumulative tool calls dispatched across this execute() run.

        Public read surface for the run-level counter so callers
        (Worker's cancel/crash result paths, colony budget adaptation)
        never reach into ``_tool_calls_used`` directly.
        """
        return self._tool_calls_used

    def apply_lifetime_budget_cap(self, new_budget: int) -> bool:
        """Shrink this loop's lifetime tool-call budget mid-run.

        The ONE sanctioned post-spawn LoopConfig mutation, and deliberately
        narrow: shrink-only, single field. The grace-flip check re-reads
        ``self._config.tool_call_lifetime_budget`` at every iteration
        boundary (see execute()'s main loop), so the clamp takes effect on
        the next turn and rides the existing budget-grace wind-down
        (one-shot reminder → report_to_parent). Do NOT extend this pattern
        to LoopConfig fields that are cached at spawn (e.g. the
        orchestrator node-worker path caches its budget) — those are not
        boundary-safe.

        Note: the dispatch loop captures the budget into a local at the
        start of each tool batch, so a clamp landing mid-batch takes
        effect one batch late. That staleness is intended — do not "fix"
        it into a mid-batch race.

        No-ops (returns False) when:
        - ``new_budget <= 0`` (0 means "disabled"; never disable via cap),
        - the current budget is 0 (an unlimited loop stays unlimited),
        - ``new_budget`` would not shrink the current budget,
        - ``grace_iterations == 0`` (a capped worker without a declared
          wind-down phase is not a colony worker — don't clamp it).
        """
        current = self._config.tool_call_lifetime_budget
        if new_budget <= 0 or current <= 0 or new_budget >= current:
            return False
        if self._config.grace_iterations <= 0:
            return False
        self._config.tool_call_lifetime_budget = new_budget
        logger.info(
            "[AgentLoop] lifetime tool-call budget capped %d -> %d (used so far: %d)",
            current,
            new_budget,
            self._tool_calls_used,
        )
        return True

    def cancel_current_turn(self) -> list[asyncio.Task]:
        """Cancel the current LLM streaming turn or in-progress tool calls instantly.

        Unlike signal_shutdown() which permanently stops the event loop,
        this only kills the in-progress HTTP stream or tool gather task.
        The queen stays alive for the next user message.

        Returns the cancelled tasks so callers can `await` them and confirm
        the cancellation actually took effect before responding to the user.
        """
        cancelled: list[asyncio.Task] = []
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            cancelled.append(self._stream_task)
        if self._tool_task and not self._tool_task.done():
            self._tool_task.cancel()
            cancelled.append(self._tool_task)
        return cancelled

    def mark_user_stopped(self) -> None:
        """Record that the user explicitly stopped the agent.

        Set by the cancel-queen route before ``cancel_current_turn()`` so
        the idle-nudge gate sees the flag from the very first tick after
        the cancelled turn parks the loop. Cleared *only* by
        ``inject_event`` (a real user message). Chat re-entry no longer
        lifts this flag — the user must send a message to resume.
        """
        self._user_stopped = True

    @staticmethod
    def _park_reason_from_cursor(pending: dict[str, Any]) -> ParkReason:
        """Recover the :class:`ParkReason` for a restored pending-input wait.

        Cursors written before park reasons existed carry no ``reason`` —
        fall back to the question/questionless split they did record.
        """
        raw = pending.get("reason")
        if raw:
            try:
                return ParkReason(raw)
            except ValueError:
                pass
        return ParkReason.ASK_USER if pending.get("questions") else ParkReason.TURN_DONE

    async def _await_user_input(
        self,
        ctx: AgentContext,
        *,
        reason: ParkReason = ParkReason.UNKNOWN,
        questions: list[dict] | None = None,
        colony_suggestion: dict | None = None,
        colony_pivot: dict | None = None,
        credential_form: dict | None = None,
        emit_client_request: bool = True,
    ) -> bool:
        """Block until user input arrives or shutdown is signaled.

        Called in two situations:
        - The LLM explicitly calls ask_user() or suggest_colony().
        - Auto-block: any text-only turn (no real tools, no set_output)
          from the queen node — ensures the user sees and responds
          before the judge runs.

        Args:
            reason: Why the loop is parking — see :class:`ParkReason`.
                Recorded in ``self._park_reason`` for the duration of the
                wait so the idle nudge can tell a legitimate question-park
                from a broken or normal-idle one. Each call site declares
                its own; ``UNKNOWN`` flags a site that forgot to.
            questions: Optional list of question dicts from ask_user. Each
                dict has id, prompt, and optional options. Passed through to
                the CLIENT_INPUT_REQUESTED event so the frontend can render
                the appropriate widget (QuestionWidget for one, else
                MultiQuestionWidget).
            colony_suggestion: Optional payload from suggest_colony with
                ``colony_id`` and optional ``reason``. When set, the
                COLONY_SUGGESTION_REQUESTED event is emitted in place of
                CLIENT_INPUT_REQUESTED so the frontend opens the
                "Create Colony" popup pre-filled. Mutually exclusive with
                ``questions`` (the queen calls one or the other per turn).
            emit_client_request: When False, wait silently without publishing
                CLIENT_INPUT_REQUESTED. Used for worker waits where input is
                expected from the queen via inject_message().

        Returns True if input arrived, False if shutdown was signaled.
        """
        # If messages or triggers arrived while the LLM was processing, skip
        # blocking — the next drain pass will pick them up.
        if not self._injection_queue.empty() or not self._trigger_queue.empty():
            return True

        # Clear BEFORE emitting so that synchronous handlers (e.g. the
        # headless stdin handler) can call inject_event() during the emit
        # and the signal won't be lost.  TUI handlers return immediately
        # without injecting, so the wait still blocks until the user types.
        self._input_ready.clear()

        # Close the lost-wakeup window: a message can arrive between the
        # pre-check above and the clear() we just did. Re-check the queues
        # after clearing; if anything snuck in, skip the wait entirely.
        # Same after emit (sync handlers may inject during the emit).
        if not self._injection_queue.empty() or not self._trigger_queue.empty():
            return True

        if emit_client_request and self._event_bus:
            if colony_pivot is not None:
                # The colony-pivot popup variant — slug field starts
                # blank for the user to fill in, and the popup shows the
                # queen-authored goal + handoff so the user can review
                # what's being handed over before confirming.
                tasks_in = colony_pivot.get("tasks") or []
                await self._event_bus.emit_colony_suggestion_requested(
                    stream_id=ctx.stream_id or ctx.agent_id,
                    node_id=ctx.agent_id,
                    execution_id=ctx.execution_id or "",
                    colony_id="",
                    source_session_id=ctx.session_id,
                    source_phase=colony_pivot.get("source_phase", "colony"),
                    goal=colony_pivot.get("goal"),
                    handoff=colony_pivot.get("handoff"),
                    task_count=len(tasks_in) if isinstance(tasks_in, list) else 0,
                )
            elif colony_suggestion is not None:
                await self._event_bus.emit_colony_suggestion_requested(
                    stream_id=ctx.stream_id or ctx.agent_id,
                    node_id=ctx.agent_id,
                    execution_id=ctx.execution_id or "",
                    colony_id=colony_suggestion.get("colony_id", ""),
                    reason=colony_suggestion.get("reason"),
                )
            elif credential_form is not None:
                await self._event_bus.emit_credential_form_requested(
                    stream_id=ctx.stream_id or ctx.agent_id,
                    node_id=ctx.agent_id,
                    execution_id=ctx.execution_id or "",
                    form=credential_form,
                )
            else:
                await self._event_bus.emit_client_input_requested(
                    stream_id=ctx.stream_id or ctx.agent_id,
                    node_id=ctx.agent_id,
                    execution_id=ctx.execution_id or "",
                    questions=questions,
                    park_reason=reason.value,
                )

        if not self._injection_queue.empty() or not self._trigger_queue.empty():
            return True

        self._awaiting_input = True
        # Record why the loop is parked for the duration of the wait. A
        # question-park (ask_user / colony suggestion) is legitimate; a
        # broken or questionless park is what the idle nudge re-engages.
        self._park_reason = reason
        # Sentinel: stash this park's questions so the escalation source can
        # render them (the ask_user handler already drained _pending_questions).
        self._park_questions = questions
        # Announce the park's authoritative state — AWAITING_USER for a
        # deliberate end-of-turn park, INTERRUPTED for a broken / stopped /
        # unknown one. ParkReason.activity is the single classifier.
        await self._set_activity(ctx, reason.activity, park_reason=reason)
        try:
            await self._input_ready.wait()
        finally:
            self._awaiting_input = False
            self._park_reason = None
            self._park_questions = None
            # User input just arrived (or wait was cancelled) — count it
            # as progress so the session-idle watchdog's clock starts
            # fresh from this moment instead of inheriting whatever the
            # pre-wait timestamp was.
            self._mark_session_progress()
            # Back to EXECUTING — unless the loop is shutting down, in which
            # case leave the last announced state alone.
            if not self._shutdown:
                await self._set_activity(ctx, LoopActivity.EXECUTING)
        return not self._shutdown

    # Synthetic framework tools that are appended directly to the loop's
    # ``tools`` list (not sourced from ``dynamic_tools_provider``). They must
    # survive a dynamic refresh, so the refresh preserves them by name.
    _DYNAMIC_REFRESH_SYNTHETIC_NAMES = frozenset(
        {
            "ask_user",
            "credentials",
            "sentinel_setup",
            "escalate",
            "collect_result",
            # Worker synthetics: report_to_parent and the worker-side
            # search_tools are appended directly to the loop's list, so a
            # dynamic refresh (now wired for tiered workers too) must
            # preserve them or the worker loses its report channel mid-turn.
            "report_to_parent",
            "search_tools",
        }
    )

    def _refresh_dynamic_tools(self, ctx: AgentContext, tools: list[Tool]) -> None:
        """Re-pull the phase-aware dynamic tool list into ``tools`` in place.

        For the queen, ``ctx.dynamic_tools_provider`` is
        ``QueenPhaseState.get_current_tools`` — the set of tools currently
        callable for the active phase, which GROWS when ``search_tools`` loads
        a searchable tool mid-session. Mutating ``tools`` in place (rather than
        rebinding) is required: ``_run_turn_loop``'s inner-stream closure holds
        this exact list object by reference.

        Called from TWO sites that must stay in lockstep:
          * step 6b2 in :meth:`execute` (once per outer iteration), and
          * the top of the inner stream loop in :meth:`_run_turn_loop`.
        The inner-loop call is the load-bearing one: a tool loaded by a
        ``search_tools`` call earlier in the SAME turn-loop would otherwise not
        reach the model until the inner loop yields on a tool-free response —
        which never happens while the model keeps emitting tool calls trying to
        use the tool it cannot yet see (a deadlock). Refreshing here makes the
        freshly-loaded tool callable on the very next step, exactly as the
        ``search_tools`` "callable from your next step" note promises.

        No-op when no provider is wired (non-queen nodes), so those paths keep
        their static tool list untouched.
        """
        if ctx.dynamic_tools_provider is None:
            return
        provided = list(ctx.dynamic_tools_provider())
        # Dedupe by name: the queen's provider includes the registry-registered
        # search_tools, which is ALSO in the synthetic-preserve set (for the
        # worker path, where it is loop-appended) — without the check it would
        # appear twice in the wire list.
        provided_names = {t.name for t in provided}
        synthetic = [t for t in tools if t.name in self._DYNAMIC_REFRESH_SYNTHETIC_NAMES and t.name not in provided_names]
        tools[:] = provided + synthetic

    # -------------------------------------------------------------------
    # Single LLM turn with caller-managed tool orchestration
    # -------------------------------------------------------------------

    async def _run_turn_loop(
        self,
        ctx: AgentContext,
        conversation: NodeConversation,
        tools: list[Tool],
        iteration: int,
        accumulator: OutputAccumulator,
    ) -> tuple[
        str,
        list[dict],
        list[str],
        dict[str, int],
        list[dict],
        bool,
        bool,
        str,
        list[dict[str, Any]],
        bool,
    ]:
        """Run the agent's turn loop: stream the model, execute its tool
        calls, re-stream — repeating until the model produces a tool-free
        response. One pass of the inner loop is a single turn; this runs
        as many turns as the model needs before yielding control back.

        Returns (assistant_text, real_tool_results, outputs_set, token_counts, logged_tool_calls,
        user_input_requested, queen_input_requested, system_prompt, messages, reported_to_parent).

        ``real_tool_results`` contains only results from actual tools (web_search,
        etc.), NOT from synthetic framework tools such as ``set_output``,
        ``ask_user``, or ``escalate``.
        ``outputs_set`` lists the output keys written via ``set_output`` during
        this turn.  ``user_input_requested`` is True if the LLM called
        ``ask_user`` during this turn.  This separation lets the caller treat
        synthetic tools as framework concerns rather than tool-execution concerns.
        ``queen_input_requested`` is True when the worker called
        ``escalate`` and should wait for queen guidance before judge
        evaluation.

        ``logged_tool_calls`` accumulates ALL tool calls across the loop's
        inner turns (real tools, set_output, and discarded calls) for L3
        logging.  Unlike ``real_tool_results`` which resets each inner turn,
        this list grows across the whole loop.
        """
        stream_id = ctx.stream_id or ctx.agent_id
        node_id = ctx.agent_id
        execution_id = ctx.execution_id or ""
        # Mixed-type dict: int token counts + str stop_reason/model + float cost.
        # ``credits`` stays ``None`` until at least one FinishEvent in this turn
        # carries an upstream ``usage.credits`` (Hive-aliased models only).
        # Typed loosely to avoid churn in the many call sites that read from it.
        token_counts: dict[str, Any] = {
            "input": 0,
            "output": 0,
            "cached": 0,
            "cache_creation": 0,
            "cost": 0.0,
            "credits": None,
        }
        # Running tool-call count for this turn-loop (one judge
        # iteration). Drives both the soft checkpoint reminders and the
        # hard stop; resets here, per turn-loop. `soft_budget_reminders`
        # tracks how many soft checkpoints have already been emitted so
        # each budget multiple fires its reminder at most once.
        tool_call_count = 0
        soft_budget_reminders = 0
        final_text = ""
        final_system_prompt = conversation.system_prompt
        final_messages: list[dict[str, Any]] = []
        # Track output keys set via set_output across all inner iterations
        outputs_set_this_turn: list[str] = []
        user_input_requested = False
        queen_input_requested = False
        # Accumulate ALL tool calls across inner iterations for L3 logging.
        # Unlike real_tool_results (reset each inner iteration), this persists.
        logged_tool_calls: list[dict] = []
        # Counter for LLM calls within a single iteration.  Each pass through
        # the inner tool loop starts a fresh LLM stream whose snapshot resets
        # to "".  Without this, all calls share the same message ID on the
        # frontend and the second call's text silently replaces the first.
        inner_turn = 0
        logger.debug(
            "[_run_turn_loop] node_id=%s, tools_count=%d, execution_id=%s",
            node_id,
            len(tools),
            execution_id,
        )

        # Reset the stream-stall source's per-turn nudge counter. It caps
        # how many times we re-stream within this _run_turn_loop when the
        # idle/TTFT watchdog fires, so a genuinely dead endpoint eventually
        # surfaces as an error instead of nudging forever.
        self._stream_stall_source.reset_turn()

        # Inner tool loop: stream may produce tool calls requiring re-invocation
        while True:
            # Mid-turn dynamic tool refresh. The outer loop's 6b2 refresh runs
            # only once per iteration, BEFORE this inner loop — but a
            # search_tools call here loads a tool into the phase state mid-loop.
            # Re-pull before each stream so the freshly-loaded tool reaches the
            # model on its very next step; without this the inner loop (which
            # only exits on a tool-free response) deadlocks: the model keeps
            # emitting tool calls trying to use a tool that is never injected
            # into the request's tool schema. In-place mutation keeps the
            # _do_stream closure's `tools` reference valid. No-op (skipped)
            # for nodes without a dynamic_tools_provider.
            self._refresh_dynamic_tools(ctx, tools)

            # Pre-send guard: if context is at or over budget, compact before
            # calling the LLM — prevents API context-length errors.
            if conversation.usage_ratio() >= 1.0:
                logger.warning(
                    "Pre-send guard: context at %.0f%% of budget, compacting",
                    conversation.usage_ratio() * 100,
                )
                await self._compact(ctx, conversation, accumulator)

            messages = conversation.to_llm_messages()

            # Defensive guard: ensure messages don't end with an assistant
            # message.  The Anthropic API rejects "assistant message prefill"
            # (conversations must end with a user or tool message).  This can
            # happen after compaction trims messages leaving an assistant tail,
            # or when a conversation is inherited without a transition marker
            # (e.g. parallel-branch execution).
            if messages and messages[-1].get("role") == "assistant":
                logger.info(
                    "[%s] Messages end with assistant — injecting continuation prompt",
                    node_id,
                )
                await conversation.add_user_message("[Continue working on your current task.]")
                messages = conversation.to_llm_messages()
            final_system_prompt = conversation.system_prompt
            final_messages = messages

            accumulated_text = ""
            tool_calls: list[ToolCallEvent] = []
            _stream_error: StreamErrorEvent | None = None
            # Reasoning/`thinking` blocks for this turn — captured from the
            # FinishEvent and stored on the assistant message so they are
            # echoed back on every follow-up request (reasoning models 400
            # otherwise). See Message.thinking_blocks.
            _thinking_blocks: list[dict[str, Any]] = []

            # Gap 1 - Streaming tool execution. Any tool flagged as
            # concurrency_safe is kicked off the moment its ToolCallEvent
            # arrives in the stream, instead of waiting for the full
            # assistant message stop event. The dispatch phase below
            # reuses these already-running tasks so terminal_rg / terminal_glob
            # reads overlap with whatever text the model is still
            # generating. Unsafe tools (bash, edits, browser actions)
            # still wait for FinishEvent so we don't race a write
            # against a decision the model hasn't finished making.
            _early_safe_names = {t.name for t in tools if getattr(t, "concurrency_safe", False)}
            _early_tasks: dict[str, asyncio.Task] = {}

            async def _timed_execute(
                _tc: ToolCallEvent,
            ) -> tuple[ToolResult | BaseException, str, float]:
                """Execute a tool and return (result, start_iso, duration_s)."""
                _s = time.time()
                _iso = datetime.now(UTC).isoformat()
                try:
                    _r = await self._execute_tool(_tc)
                except BaseException as _exc:
                    _r = _exc
                _dur = round(time.time() - _s, 3)
                return _r, _iso, _dur

            logger.debug(
                "[_run_turn_loop] inner_turn=%d: Starting LLM stream with %d messages, %d tools",
                inner_turn,
                len(messages),
                len(tools),
            )
            logger.debug(
                "[_run_turn_loop] inner_turn=%d: request context node=%s roles=%s system_chars=%d max_tokens=%d",
                inner_turn,
                node_id,
                [m.get("role") for m in messages],
                len(conversation.system_prompt or ""),
                ctx.max_tokens,
            )
            if not messages:
                logger.warning(
                    "[_run_turn_loop] inner_turn=%d: no non-system conversation messages "
                    "before LLM call for node=%s model=%s api_base=%s. "
                    "This will produce a system-only payload, which some providers reject.",
                    inner_turn,
                    node_id,
                    getattr(ctx.llm, "model", type(ctx.llm).__name__),
                    getattr(ctx.llm, "api_base", None),
                )

            # Stream LLM response in a child task so cancel_current_turn()
            # can kill it instantly without terminating the queen's main loop.
            # Capture loop-scoped variables as defaults to satisfy B023.
            # _stream_last_event_at is bumped on every event; the watchdog
            # below uses it to detect silently hung HTTP connections.
            _stream_start_at = time.monotonic()
            _stream_last_event_at = _stream_start_at
            # None until the first event arrives. Before first event, the
            # watchdog uses the (much looser) TTFT budget — large-context
            # local models legitimately take minutes to first token. Once
            # any event has been observed, tight inter-event idle applies.
            _first_event_at: float | None = None
            # Reset the instance-level mirror so the session-idle watchdog
            # sees this stream as freshly-opened (substate=slow_ttft until
            # the first event arrives, then no double-fire while it's
            # producing).
            self._stream_first_event_at = None
            # Partial tool_calls accumulated so far, as OpenAI-format dicts
            # ready for persistence if the stream is cut short.
            _partial_tc_dicts: list[dict[str, Any]] = []

            async def _do_stream(
                _msgs: list = messages,  # noqa: B006
                _tc: list[ToolCallEvent] = tool_calls,  # noqa: B006
                inner_turn: int = inner_turn,
                _safe_names: set = _early_safe_names,  # noqa: B006,B008
                _tasks: dict = _early_tasks,  # noqa: B006,B008
                _exec_fn=_timed_execute,
                _partial_dicts: list[dict[str, Any]] = _partial_tc_dicts,  # noqa: B006,B008
            ) -> None:
                nonlocal accumulated_text, _stream_error, _stream_last_event_at
                nonlocal _first_event_at, _thinking_blocks
                _clean_snapshot = ""  # visible-only text for the frontend
                _reasoning_emitted = ""  # last reasoning emitted via CLIENT_REASONING (dedup)
                _reasoning_native = ""  # accumulated native reasoning-delta text (thinking models)
                _reasoning_streamed_len = 0  # chars of _reasoning_native already published live
                _reasoning_last_pub = 0.0

                async def _stream_reasoning_delta() -> None:
                    """Live-stream native reasoning to the UI, throttled to ~1/s.

                    A thinking model can reason for minutes before its first
                    visible character; without these events the session looks
                    dead the whole time. Snapshot is tail-capped — the full
                    text still arrives via CLIENT_REASONING at flush.
                    """
                    nonlocal _reasoning_streamed_len, _reasoning_last_pub
                    if not (self._event_bus and ctx.emits_client_io):
                        return
                    if len(_reasoning_native) <= _reasoning_streamed_len:
                        return
                    now = time.monotonic()
                    if now - _reasoning_last_pub < 1.0:
                        return
                    tail = _reasoning_native[_reasoning_streamed_len:]
                    _reasoning_streamed_len = len(_reasoning_native)
                    _reasoning_last_pub = now
                    await self._event_bus.emit_llm_reasoning_delta(
                        stream_id=stream_id,
                        node_id=node_id,
                        content=tail,
                        execution_id=execution_id,
                        iteration=iteration,
                        inner_turn=inner_turn,
                        snapshot=_reasoning_native[-4000:],
                    )

                async def _flush_reasoning() -> None:
                    """Surface reasoning to monitors once per turn (deduped).

                    Prefers the model's native reasoning stream (glm/deepseek
                    reasoning_content, Anthropic thinking blocks) captured via
                    ReasoningDeltaEvent; falls back to an inline <think> block
                    when a non-thinking model uses the persona scaffold.
                    """
                    nonlocal _reasoning_emitted
                    if not (self._event_bus and ctx.emits_client_io):
                        return
                    _reason = _reasoning_native or _extract_think_reasoning(accumulated_text)
                    if _reason and _reason != _reasoning_emitted:
                        _reasoning_emitted = _reason
                        await self._event_bus.emit_client_reasoning(
                            stream_id=stream_id,
                            node_id=node_id,
                            reasoning=_reason,
                            execution_id=execution_id,
                            iteration=iteration,
                            inner_turn=inner_turn,
                        )

                # Split-prompt path: pass STATIC and DYNAMIC tail separately
                # so the LLM wrapper can emit them as two Anthropic system
                # content blocks with a cache breakpoint between them. When
                # no split is in use, ``system_prompt_static`` equals the
                # full prompt and the suffix is empty — identical to the
                # legacy single-block request.
                async for event in ctx.llm.stream(
                    messages=_msgs,
                    system=conversation.system_prompt_static,
                    system_dynamic_suffix=(conversation.system_prompt_dynamic_suffix or None),
                    tools=tools if tools else None,
                    max_tokens=ctx.max_tokens,
                ):
                    _stream_last_event_at = time.monotonic()
                    if _first_event_at is None:
                        _first_event_at = _stream_last_event_at
                        self._stream_first_event_at = _first_event_at
                    # Mirror progress to the session-level clock so the
                    # outer watchdog stays quiet during a productive stream.
                    self._mark_session_progress()
                    if isinstance(event, ReasoningDeltaEvent):
                        # Native reasoning stream from a thinking model
                        # (glm/deepseek reasoning_content, Anthropic thinking).
                        # Accumulate; flushed to monitors when the first visible
                        # text arrives (or at FinishEvent for tool-only turns).
                        _reasoning_native += event.content
                        await _stream_reasoning_delta()

                    elif isinstance(event, TextDeltaEvent):
                        accumulated_text = event.snapshot
                        # Surface reasoning (native stream or inline <think>)
                        # just before the first visible text, so monitors see
                        # the grounding that precedes the spoken line.
                        await _flush_reasoning()
                        # Strip internal reasoning tags from the full
                        # snapshot, then diff against what we already
                        # emitted to get the new visible delta.
                        _new_clean = _strip_internal_tags_from_snapshot(event.snapshot)
                        if len(_new_clean) > len(_clean_snapshot):
                            _delta = _new_clean[len(_clean_snapshot) :]
                            _clean_snapshot = _new_clean
                            await self._publish_text_delta(
                                stream_id,
                                node_id,
                                _delta,
                                _clean_snapshot,
                                ctx,
                                execution_id,
                                iteration=iteration,
                                inner_turn=inner_turn,
                            )
                        # Checkpoint partial state so a watchdog cancel or
                        # crash doesn't discard whatever the model has
                        # produced so far. Cheap — one atomic file write.
                        try:
                            await conversation.checkpoint_partial_assistant(
                                accumulated_text,
                                _partial_dicts or None,
                            )
                        except Exception as _cp_err:  # noqa: BLE001
                            logger.debug(
                                "[_run_turn_loop] partial checkpoint failed: %s",
                                _cp_err,
                            )

                    elif isinstance(event, ToolCallEvent):
                        _tc.append(event)
                        _partial_dicts.append(
                            {
                                "id": event.tool_use_id,
                                "type": "function",
                                "function": {
                                    "name": event.tool_name,
                                    "arguments": json.dumps(event.tool_input),
                                },
                            }
                        )
                        # Checkpoint now that a tool call has landed —
                        # this is the important one: if the stream dies
                        # right after a tool call but before FinishEvent,
                        # we still have the intent recorded.
                        try:
                            await conversation.checkpoint_partial_assistant(
                                accumulated_text,
                                _partial_dicts or None,
                            )
                        except Exception as _cp_err:  # noqa: BLE001
                            logger.debug(
                                "[_run_turn_loop] partial checkpoint failed: %s",
                                _cp_err,
                            )
                        # Gap 1: start concurrency-safe tools immediately
                        # while the rest of the stream is still arriving,
                        # so read-heavy turns don't stall after the last
                        # text delta. Unsafe tools wait for FinishEvent.
                        if event.tool_name in _safe_names and "_raw" not in event.tool_input and event.tool_use_id not in _tasks:
                            _tasks[event.tool_use_id] = asyncio.create_task(_exec_fn(event))

                    elif isinstance(event, FinishEvent):
                        # Reasoning-only or tool-only turns produce no text
                        # delta; flush any accumulated reasoning here so it
                        # still reaches monitors.
                        await _flush_reasoning()
                        token_counts["input"] += event.input_tokens
                        token_counts["output"] += event.output_tokens
                        token_counts["cached"] += event.cached_tokens
                        token_counts["cache_creation"] += event.cache_creation_tokens
                        token_counts["cost"] = token_counts.get("cost", 0.0) + event.cost_usd
                        # Credits are cumulative-per-request from the proxy.
                        # Each FinishEvent represents one request, so sum
                        # across them. Skip events with no credits (direct
                        # provider models) so we don't false-zero a turn that
                        # had at least one Hive-aliased call.
                        logger.info(
                            "[credits] agent_loop FinishEvent: credits=%r model=%s",
                            event.credits,
                            event.model,
                        )
                        if event.credits is not None:
                            token_counts["credits"] = (token_counts.get("credits") or 0.0) + event.credits
                        token_counts["stop_reason"] = event.stop_reason
                        token_counts["model"] = event.model

                        # Capture reasoning blocks so the assistant turn can
                        # echo them back next request. Each FinishEvent is one
                        # LLM call; the last call's blocks belong to the turn
                        # being persisted, so overwrite rather than extend.
                        if event.thinking_blocks:
                            _thinking_blocks = list(event.thinking_blocks)

                        # Tell the conversation the size of THIS request's
                        # prompt. ``max_context_tokens`` is a single-prompt
                        # budget; ``usage_ratio()`` compares this field
                        # against it. ``token_counts["input"]`` above is a
                        # billing sum across all inner LLM calls in this
                        # turn — feeding the sum into the conversation
                        # would make usage_ratio compare billing to a
                        # request budget and report fictional 1000%+
                        # ratios. Stay strictly per-call here.
                        if event.input_tokens > 0:
                            conversation.update_token_count(event.input_tokens)

                    elif isinstance(event, StreamErrorEvent):
                        if not event.recoverable:
                            # Surface billing-gate errors as a dedicated
                            # SSE so the desktop client can reopen the
                            # upgrade popup without parsing the failure
                            # string. The execution_failed event still
                            # fires downstream as usual.
                            if event.error_type == "payment_required" and self._event_bus is not None:
                                try:
                                    await self._event_bus.emit_payment_required(
                                        stream_id=stream_id,
                                        execution_id=execution_id or None,
                                        message=event.error,
                                        upstream_status=event.upstream_status,
                                    )
                                except Exception:
                                    logger.exception("Failed to emit payment_required event")
                            raise RuntimeError(f"Stream error: {event.error}")
                        _stream_error = event
                        logger.warning("Recoverable stream error: %s", event.error)

            # About to stream — the loop is executing. Idempotent; this is
            # also the recovery point after a stream-stall nudge re-streams,
            # flipping the loop back out of INTERRUPTED.
            await self._set_activity(ctx, LoopActivity.EXECUTING)
            _llm_stream_t0 = time.monotonic()
            self._stream_task = asyncio.create_task(_do_stream())
            logger.debug("[_run_turn_loop] inner_turn=%d: Stream task created, waiting...", inner_turn)

            # Watchdog budgets — see LoopConfig docstring for rationale.
            _ttft_limit = self._config.llm_stream_ttft_timeout_seconds
            _inter_event_limit = self._config.llm_stream_inter_event_idle_seconds
            # Back-compat: if the legacy inactivity knob was overridden to
            # a value below the new default, respect it as the inter-event
            # budget (historic behaviour) so existing configs don't regress.
            _legacy = self._config.llm_stream_inactivity_timeout_seconds
            if _legacy and _legacy > 0 and _legacy < _inter_event_limit:
                _inter_event_limit = _legacy
            _watchdog_active = (_ttft_limit and _ttft_limit > 0) or (_inter_event_limit and _inter_event_limit > 0)
            # Result of the watchdog: "ok" (stream finished), "ttft" (no first
            # event in budget), "inactive" (silence after first event).
            _watchdog_verdict: str = "ok"
            _watchdog_elapsed: float = 0.0
            _watchdog_limit: float = 0.0

            try:
                if _watchdog_active:
                    # Poll cheapest-valid interval: at most every 5s, at least
                    # half the tighter budget. Must use asyncio.wait (not
                    # wait_for) so "poll interval elapsed" and "task raised
                    # TimeoutError of its own" stay distinguishable.
                    _tight = min(
                        _ttft_limit or float("inf"),
                        _inter_event_limit or float("inf"),
                    )
                    _check_interval = max(1.0, min(5.0, _tight / 2))
                    while True:
                        done, _pending = await asyncio.wait({self._stream_task}, timeout=_check_interval)
                        if self._stream_task in done:
                            break
                        now = time.monotonic()
                        if _first_event_at is None:
                            # TTFT phase — stream open but silent. Use the
                            # looser budget; don't confuse slow models with
                            # dead connections.
                            elapsed = now - _stream_start_at
                            if _ttft_limit and _ttft_limit > 0 and elapsed >= _ttft_limit:
                                _watchdog_verdict = "ttft"
                                _watchdog_elapsed = elapsed
                                _watchdog_limit = _ttft_limit
                                break
                        else:
                            # Post-first-event silence. A stream that produced
                            # events and then went quiet is a real stall.
                            idle = now - _stream_last_event_at
                            if _inter_event_limit and _inter_event_limit > 0 and idle >= _inter_event_limit:
                                _watchdog_verdict = "inactive"
                                _watchdog_elapsed = idle
                                _watchdog_limit = _inter_event_limit
                                break
                        # Still active — keep polling.

                if _watchdog_verdict != "ok":
                    logger.warning(
                        "[_run_turn_loop] inner_turn=%d: watchdog=%s %.0fs >= %.0fs — cancelling stream",
                        inner_turn,
                        _watchdog_verdict,
                        _watchdog_elapsed,
                        _watchdog_limit,
                    )
                    self._bump(f"stream_watchdog_{_watchdog_verdict}")
                    # The stream stalled — announce INTERRUPTED. A nudge
                    # re-stream (or the next iteration) flips it back to
                    # EXECUTING; an unrecoverable stall raises and parks.
                    await self._set_activity(
                        ctx,
                        LoopActivity.INTERRUPTED,
                        interrupt_cause=InterruptCause.STREAM_STALL,
                    )
                    self._stream_task.cancel()
                    try:
                        await self._stream_task
                    except BaseException:
                        pass
                else:
                    # Re-raise any exception the stream task stored. When the
                    # watchdog loop exited via ``break`` the task is done, and
                    # ``await`` is the cheapest way to surface its exception.
                    await self._stream_task
                    logger.debug(
                        "[_run_turn_loop] inner_turn=%d: Stream task completed normally",
                        inner_turn,
                    )
            except asyncio.CancelledError:
                logger.debug("[_run_turn_loop] inner_turn=%d: Stream task cancelled", inner_turn)
                if accumulated_text or _partial_tc_dicts:
                    await conversation.add_assistant_message(
                        content=accumulated_text,
                        tool_calls=_partial_tc_dicts or None,
                        truncated=True,
                    )
                # Persist the cancelled turn so events.jsonl and the LLM
                # debug log show what was in flight when the user hit
                # stop. Mirrors the success-path emit + log at 1141/1159
                # but stamps stop_reason="cancelled" so subscribers can
                # filter (e.g. the frontend skips the pending-queue
                # flush — handleCancelQueen already drained one).
                # Also flushes accumulated client_output_delta snapshots
                # for this stream via the LLM_TURN_COMPLETE handler in
                # the event bus.
                try:
                    _cancelled_counts = {**token_counts, "stop_reason": "cancelled"}
                    _cancel_diag = self._compute_turn_diagnostics(
                        conversation_static=conversation.system_prompt_static,
                        conversation_suffix=conversation.system_prompt_dynamic_suffix,
                        request_messages=final_messages,
                        model=_cancelled_counts.get("model", ""),
                    )
                    await self._publish_llm_turn_complete(
                        stream_id,
                        node_id,
                        stop_reason="cancelled",
                        model=_cancelled_counts.get("model", ""),
                        input_tokens=_cancelled_counts.get("input", 0),
                        output_tokens=_cancelled_counts.get("output", 0),
                        cached_tokens=_cancelled_counts.get("cached", 0),
                        cache_creation_tokens=_cancelled_counts.get("cache_creation", 0),
                        cost_usd=float(_cancelled_counts.get("cost", 0.0) or 0.0),
                        credits=_cancelled_counts.get("credits"),
                        execution_id=execution_id,
                        iteration=iteration,
                        system_prefix_sha=_cancel_diag["system_prefix_sha"],
                        system_suffix_sha=_cancel_diag["system_suffix_sha"],
                        history_anchor_idx=_cancel_diag["history_anchor_idx"],
                        message_count=_cancel_diag["message_count"],
                    )
                    log_llm_turn(
                        node_id=node_id,
                        stream_id=stream_id,
                        execution_id=execution_id,
                        iteration=iteration,
                        system_prompt=final_system_prompt,
                        messages=final_messages,
                        assistant_text=accumulated_text,
                        tool_calls=logged_tool_calls + list(_partial_tc_dicts or []),
                        tool_results=[],
                        token_counts=_cancelled_counts,
                        tools=tools,
                    )
                except Exception:
                    logger.debug("cancel-turn telemetry failed", exc_info=True)
                # Gap 1: kill any early-dispatched tool tasks too.
                # Without this, a safe tool started during streaming
                # would leak past cancellation and keep running.
                for _early in _early_tasks.values():
                    if not _early.done():
                        _early.cancel()
                # Distinguish cancel_current_turn() (cancels the child
                # _stream_task) from stop_worker (cancels the parent
                # execution task).  When the parent itself is cancelled,
                # cancelling() > 0 — propagate so the executor can save
                # state.  When only the child was cancelled, convert to
                # TurnCancelled so the event loop continues.
                task = asyncio.current_task()
                if task and task.cancelling() > 0:
                    raise
                raise TurnCancelled() from None
            except Exception as e:
                logger.exception("[_run_turn_loop] inner_turn=%d: Stream task failed: %s", inner_turn, e)
                # Don't orphan early tool tasks on a stream failure
                # either - the outer retry loop will re-emit the tool
                # calls on the next attempt.
                for _early in _early_tasks.values():
                    if not _early.done():
                        _early.cancel()
                raise
            finally:
                self._stream_task = None

            # Continue-nudge recovery path. Runs AFTER the stream task is
            # cleaned up so all state is consistent. We persist whatever
            # partial text + tool-calls the model produced (as a truncated
            # message so the model can see its own in-flight work on the
            # next turn), cancel early tool tasks, append a terse
            # continuation hint, and restart the stream.
            if _watchdog_verdict != "ok":
                # Kill any safe-tool tasks the stream dispatched early —
                # their results would have had nowhere to land anyway
                # because the assistant message was incomplete.
                for _early in _early_tasks.values():
                    if not _early.done():
                        _early.cancel()
                # Promote whatever we captured into a real truncated
                # message. The partial checkpoint for this seq is cleared
                # automatically when add_assistant_message persists.
                if accumulated_text or _partial_tc_dicts:
                    await conversation.add_assistant_message(
                        content=accumulated_text,
                        tool_calls=_partial_tc_dicts or None,
                        truncated=True,
                    )

                if self._event_bus:
                    if _watchdog_verdict == "ttft":
                        await self._event_bus.emit_stream_ttft_exceeded(
                            stream_id=stream_id,
                            node_id=node_id,
                            ttft_seconds=_watchdog_elapsed,
                            limit_seconds=_watchdog_limit,
                            execution_id=execution_id,
                        )
                    else:
                        await self._event_bus.emit_stream_inactive(
                            stream_id=stream_id,
                            node_id=node_id,
                            idle_seconds=_watchdog_elapsed,
                            limit_seconds=_watchdog_limit,
                            execution_id=execution_id,
                        )

                # Consult the stream-stall reminder source synchronously —
                # it owns the nudge text and the per-turn cap. A returned
                # reminder is injected inline: we re-stream this same turn,
                # so it cannot be deferred to the iteration-boundary drain.
                stall_reminders = await self._reminder_hub.collect(
                    ReminderPoint.STREAM_STALLED,
                    ctx,
                    signals=LoopSignals(
                        stall_reason=_watchdog_verdict,
                        stall_elapsed=_watchdog_elapsed,
                    ),
                )
                if stall_reminders:
                    nudge = stall_reminders[0]
                    await conversation.add_user_message(
                        wrap_reminder([nudge.body]) or nudge.body,
                        is_system_reminder=True,
                    )
                    await self._emit_reminder_injected(ctx, nudge)
                    if self._event_bus:
                        # Diagnostic counterpart, kept alongside the generic
                        # reminder_injected event.
                        await self._event_bus.emit_stream_nudge_sent(
                            stream_id=stream_id,
                            node_id=node_id,
                            reason=_watchdog_verdict,
                            nudge_count=int(nudge.meta.get("nudge_count", 0)),
                            execution_id=execution_id,
                        )
                    logger.info(
                        "[%s] continue-nudge sent (count=%s/%s, reason=%s)",
                        node_id,
                        nudge.meta.get("nudge_count"),
                        nudge.meta.get("cap"),
                        _watchdog_verdict,
                    )
                    # Reset the outer _turn_t0 timer so the "LLM done in
                    # Xms" log line reflects real work not the nudge cycle.
                    _llm_stream_ms = int((time.monotonic() - _llm_stream_t0) * 1000)
                    logger.debug(
                        "[_run_turn_loop] inner_turn=%d: nudge restart after %dms",
                        inner_turn,
                        _llm_stream_ms,
                    )
                    continue  # restart the inner loop, re-fetches messages
                # Nudge disabled or cap exhausted — fall back to the
                # existing retry path so a truly dead endpoint eventually
                # surfaces as an error.
                raise ConnectionError(
                    f"LLM stream {_watchdog_verdict} for {_watchdog_elapsed:.0f}s (limit {_watchdog_limit:.0f}s) — nudge cap reached"
                )

            _llm_stream_ms = int((time.monotonic() - _llm_stream_t0) * 1000)

            # If a recoverable stream error produced an empty response,
            # raise so the outer transient-error retry can handle it
            # with proper backoff instead of burning judge iterations.
            if _stream_error and not accumulated_text and not tool_calls:
                for _early in _early_tasks.values():
                    if not _early.done():
                        _early.cancel()
                raise ConnectionError(f"Stream failed with recoverable error: {_stream_error.error}")

            final_text = accumulated_text
            logger.info(
                "[%s] LLM response (%dms): text=%r tool_calls=%s stop=%s model=%s",
                node_id,
                _llm_stream_ms,
                accumulated_text[:300] if accumulated_text else "(empty)",
                [tc.tool_name for tc in tool_calls] if tool_calls else "[]",
                token_counts.get("stop_reason", "?"),
                token_counts.get("model", "?"),
            )

            # Record assistant message (write-through via conversation store)
            tc_dicts = None
            if tool_calls:
                tc_dicts = [
                    {
                        "id": tc.tool_use_id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": json.dumps(tc.tool_input),
                        },
                    }
                    for tc in tool_calls
                ]
            # Skip storing empty turns — no content, no tool calls.
            # An empty assistant message (e.g. Codex returning nothing after
            # a tool result) confuses some models on the next turn and causes
            # cascading empty-stream failures.
            if accumulated_text or tc_dicts:
                await conversation.add_assistant_message(
                    content=accumulated_text,
                    tool_calls=tc_dicts,
                    thinking_blocks=_thinking_blocks or None,
                )

            # Reminder bookkeeping: one inner turn = one model stream +
            # its tool batch — the standard "turn". Counted here, per
            # inner turn, so the drift counter tracks real model activity
            # rather than the coarse outer judge-cycle iteration. The hub
            # swallows source errors internally.
            self._reminder_hub.observe_turn([tc.tool_name for tc in tool_calls])

            # If no tool calls, turn is complete
            if not tool_calls:
                return (
                    final_text,
                    [],
                    outputs_set_this_turn,
                    token_counts,
                    logged_tool_calls,
                    user_input_requested,
                    queen_input_requested,
                    final_system_prompt,
                    final_messages,
                    False,
                )

            # Priority drain: if user sent a message while the LLM was
            # streaming, inject it into the conversation NOW -- before tool
            # execution.  The LLM will see it on the next inner turn.
            # Mirrors drain_injection_queue() in cursor_persistence.py:
            # same timestamp prefix, is_client_input, and image_content
            # so steered messages enter the conversation identically to
            # messages drained at the outer-loop boundary.
            if not self._injection_queue.empty():
                while not self._injection_queue.empty():
                    _inj_content, _inj_client, _inj_images, _inj_corr = self._injection_queue.get_nowait()
                    _inj_stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
                    if _inj_client:
                        _inj_stamped = f"[{_inj_stamp}] {_inj_content}" if _inj_content else f"[{_inj_stamp}]"
                    else:
                        _inj_stamped = f"[{_inj_stamp}] [External event] {_inj_content}"
                    _inj_msg = await conversation.add_user_message(
                        _inj_stamped,
                        is_client_input=_inj_client,
                        image_content=_inj_images if _inj_images else None,
                    )
                    if _inj_client:
                        logger.info(
                            "[%s] Priority-injected user message mid-turn (%d chars)",
                            node_id,
                            len(_inj_content),
                        )
                        # The message truly enters the conversation HERE (mid-turn,
                        # before tool execution), not at receive time. Announce the
                        # real injection moment + seq so the UI can place the bubble
                        # after the in-flight turn's deltas. See emit docstring.
                        if self._event_bus and ctx.emits_client_io:
                            await self._event_bus.emit_client_input_committed(
                                stream_id=stream_id,
                                node_id=node_id,
                                execution_id=execution_id,
                                seq=_inj_msg.seq,
                                correlation_id=_inj_corr,
                            )

            # Execute tool calls -- framework tools (set_output, ask_user)
            # run inline; real MCP tools run in parallel.
            real_tool_results: list[dict] = []
            limit_hit = False
            # True when the deferral was caused by the cumulative (lifetime)
            # budget rather than the per-turn hard stop — so the advisory can
            # name the right cause (and point at the grace wind-down).
            lifetime_limit_hit = False
            executed_in_batch = 0
            # Calls skipped because we're in the grace iteration and they
            # weren't in ``_GRACE_TERMINAL_TOOLS``. Handled symmetrically
            # with ``limit_hit`` after Phase 3: each gets a neutral
            # placeholder so the conversation stays consistent and the
            # judge sees the attempt.
            grace_skipped: list[ToolCallEvent] = []
            # Tool-call pacing budget. `soft_interval` is the cadence at
            # which we ride an escalating *checkpoint* reminder on the
            # tool-result tail (a nudge to reassess, never a stop);
            # `hard_limit` is where the turn-loop actually stops and
            # defers remaining calls. soft_interval <= 0 disables both.
            soft_interval = self._config.tool_call_budget
            if soft_interval > 0:
                hard_limit = soft_interval * max(1, self._config.tool_call_hard_multiple)
            else:
                hard_limit = 0  # disabled
            # Cumulative (lifetime) tool-call budget across the whole run.
            # Unlike `hard_limit` (per turn-loop), this reads the run-level
            # `self._tool_calls_used`. Hitting it mid-batch defers the rest;
            # the next iteration boundary flips into grace wind-down. 0 = off.
            lifetime_budget = self._config.tool_call_lifetime_budget

            # Phase 1: triage — handle framework tools immediately,
            # queue real tools for parallel execution.
            results_by_id: dict[str, ToolResult] = {}
            timing_by_id: dict[str, dict[str, Any]] = {}  # tool_use_id -> {start_timestamp, duration_s}
            pending_real: list[ToolCallEvent] = []
            # Replay detector: per-turn map from tool_use_id -> steer prefix.
            # Populated below when we detect that the model is re-emitting a
            # tool call whose (name + canonical args) matches a prior success.
            # Applied to the stored tool result content so the model sees the
            # nudge on its next turn without losing the real execution output.
            replay_prefixes_by_id: dict[str, str] = {}

            # Schema-driven coercion of tool arguments. Heals the small
            # handful of drift patterns that non-frontier models emit
            # (numbers-as-strings, array-of-{label} wrappers, arrays
            # sent as JSON strings, singleton scalars). Runs once per
            # tool call before dispatch; see tool_input_coercer module.
            _tool_by_name = {t.name: t for t in tools}

            # Pre-batch duplicate scan for the hard-breaker variant of the
            # replay detector. Counts (name, canonical-args) within this
            # LLM response so an in-batch loop (e.g. 25 identical parallel
            # tool calls in one response) trips the breaker even though
            # each call has no completed prior in the conversation yet.
            def _canonical_args(_inp: Any) -> str:
                try:
                    return json.dumps(_inp, sort_keys=True, default=str)
                except (TypeError, ValueError):
                    return str(_inp)

            batch_dup_count: Counter[tuple[str, str]] = Counter((tc.tool_name, _canonical_args(tc.tool_input)) for tc in tool_calls)

            for tc in tool_calls:
                _tool_schema = _tool_by_name.get(tc.tool_name)
                if _tool_schema is not None:
                    coerce_tool_input(_tool_schema, tc.tool_input)
                # Grace iteration: skip dispatch for non-terminal tools.
                # The skipped call gets a neutral placeholder appended
                # alongside the limit_hit handling below (same shape:
                # is_error=False, tool result in conversation, entry in
                # real_tool_results / logged_tool_calls). Does not count
                # against the per-turn tool-call budget — these calls
                # never actually executed.
                if self._in_grace and tc.tool_name not in _GRACE_TERMINAL_TOOLS:
                    grace_skipped.append(tc)
                    continue
                tool_call_count += 1
                if hard_limit > 0 and tool_call_count > hard_limit:
                    limit_hit = True
                    break
                # Lifetime (cumulative) budget hard stop — mirrors the
                # per-turn hard stop above, but on the run-level counter.
                # Reads the pre-increment total so the worker executes
                # exactly `lifetime_budget` calls then defers the rest; the
                # next iteration boundary flips into grace wind-down.
                #
                # Skip this once we're already in grace: grace dispatch is
                # restricted to _GRACE_TERMINAL_TOOLS (everything else was
                # grace-skipped above), and those terminal tools
                # (report_to_parent / tracker_upsert / task_update) are the
                # wind-down channel itself — deferring them here would trap
                # the worker, unable to report or persist, so it could only
                # die silently at max_iterations. Grace's own restriction +
                # the grace_iterations ceiling bound the work instead.
                if lifetime_budget > 0 and not self._in_grace and self._tool_calls_used >= lifetime_budget:
                    limit_hit = True
                    lifetime_limit_hit = True
                    break
                executed_in_batch += 1
                # Count only calls that pass both gates and proceed to
                # execution — grace-skipped (continue above) and
                # limit-deferred (break above) calls are excluded, so the
                # lifetime budget reflects work actually done.
                self._tool_calls_used += 1

                await self._publish_tool_started(
                    stream_id,
                    node_id,
                    tc.tool_use_id,
                    tc.tool_name,
                    tc.tool_input,
                    execution_id,
                )
                logger.info(
                    "[%s] tool_call: %s(%s)",
                    node_id,
                    tc.tool_name,
                    json.dumps(tc.tool_input)[:200],
                )

                if tc.tool_name == "set_output":
                    # set_output is no longer supported — inform the agent
                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content="set_output is no longer available. Report your results via conversation instead.",
                        is_error=True,
                    )
                    results_by_id[tc.tool_use_id] = result

                elif tc.tool_name == "ask_user":
                    # --- Framework-level ask_user handling ---
                    # The consolidated tool always takes a `questions`
                    # array (1-8 entries). A single-entry array is the
                    # common case; longer arrays batch several questions
                    # into one turn so the user answers them all at once.
                    from framework.agent_loop.internals.synthetic_tools import (
                        sanitize_ask_user_inputs,
                    )

                    raw_questions = tc.tool_input.get("questions", None)
                    if not isinstance(raw_questions, list) or not raw_questions:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: ask_user requires a non-empty "
                                "'questions' array. Each entry must have "
                                "{id, prompt, options?}. Example: "
                                '{"questions": [{"id": "q1", "prompt": '
                                '"What now?", "options": ["A", "B"]}]}'
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    # Normalize + self-heal each question entry. The
                    # generic tool_input_coercer has already handled
                    # schema-shape drift (array-of-string options, JSON
                    # strings, etc.), so here we only deal with
                    # prompt-style drift: some model families cram
                    # options inside the prompt as a pseudo-XML blob
                    # like "What now?</question>\n_OPTIONS: [\"A\", \"B\"]".
                    # sanitize_ask_user_inputs strips the tag and
                    # recovers the inline options as a fallback.
                    questions: list[dict] = []
                    for i, q in enumerate(raw_questions):
                        if not isinstance(q, dict):
                            continue
                        qid = str(q.get("id", f"q{i + 1}"))
                        raw_prompt = q.get("prompt", q.get("question", ""))
                        raw_opts = q.get("options", None)
                        cleaned_prompt, recovered_opts = sanitize_ask_user_inputs(raw_prompt, raw_opts)

                        opts: list[str] | None = None
                        if isinstance(raw_opts, list) and raw_opts:
                            opts = [str(o) for o in raw_opts if o]
                        elif recovered_opts is not None:
                            opts = recovered_opts
                        if opts is not None and len(opts) < 2:
                            opts = None  # fall back to free-text

                        questions.append(
                            {
                                "id": qid,
                                "prompt": cleaned_prompt,
                                **({"options": opts} if opts else {}),
                            }
                        )

                    if not questions:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=("ERROR: no valid question objects in 'questions'. Each entry must be an object with 'id' and 'prompt'."),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    # Workers MUST provide options on every question —
                    # free-text asks are queen-only.
                    if stream_id != "queen" and any("options" not in q for q in questions):
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: options are required on every "
                                "question for worker nodes. Provide at "
                                "least 2 predefined choices in the "
                                "'options' array of each question."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    user_input_requested = True

                    # Single free-form question: stream the prompt as a
                    # chat message so the user sees it. Widget-rendered
                    # cases (single-with-options, multi) draw their own
                    # question text, so no text delta is needed.
                    if len(questions) == 1 and "options" not in questions[0] and questions[0]["prompt"] and ctx.emits_client_io:
                        _q_text = questions[0]["prompt"]
                        await self._publish_text_delta(
                            stream_id,
                            node_id,
                            content=_q_text,
                            snapshot=_q_text,
                            ctx=ctx,
                            execution_id=execution_id,
                            iteration=iteration,
                            inner_turn=inner_turn,
                        )

                    # Stash the normalized questions list for the
                    # blocking path (§1612) + event emission.
                    self._pending_questions = questions

                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content="Waiting for user input...",
                        is_error=False,
                    )
                    results_by_id[tc.tool_use_id] = result

                elif tc.tool_name == "credentials":
                    # --- Single CLI-style credentials tool ---
                    # All actions except `collect` are non-blocking and
                    # resolve synchronously via credential_tool helpers.
                    # `collect` stashes a no-secret form spec and parks the
                    # loop (mirrors ask_user) so the user can submit secrets
                    # that go straight to the encrypted store.
                    from framework.agent_loop.internals import (
                        credential_tool as _credtool,
                    )

                    _ci = tc.tool_input if isinstance(tc.tool_input, dict) else {}
                    _action = str(_ci.get("action", "") or "help").strip().lower()
                    _cred_id = str(_ci.get("credential_id", "") or "")
                    _cred_account = str(_ci.get("account", "") or "")

                    if _action == "collect":
                        _payload, _err = _credtool.validate_collect_input(_ci)
                        if _err:
                            results_by_id[tc.tool_use_id] = ToolResult(
                                tool_use_id=tc.tool_use_id,
                                content=f"ERROR: {_err}",
                                is_error=True,
                            )
                            continue
                        _payload["correlation_id"] = uuid.uuid4().hex
                        self._pending_credential_form = _payload
                        user_input_requested = True
                        _field_names = ", ".join(f["name"] for f in _payload["fields"])
                        results_by_id[tc.tool_use_id] = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                f"Showing the user a secure form for "
                                f"'{_payload['credential_id']}' (account "
                                f"'{_payload['account']}', fields: {_field_names}). "
                                "Waiting for them to submit — the values are "
                                "stored securely and are not shown to you."
                            ),
                            is_error=False,
                        )
                    else:
                        if _action in ("", "help"):
                            _content = _credtool.render_help()
                        elif _action == "browse":
                            _content = _credtool.browse(_ci.get("query"))
                        elif _action == "inspect":
                            _content = _credtool.inspect(_cred_id, _cred_account)
                        elif _action == "reveal":
                            _content = _credtool.reveal(
                                _cred_id,
                                _cred_account,
                                str(_ci.get("key", "") or ""),
                            )
                        elif _action == "attach":
                            _content = _credtool.add_attachment(ctx.session_id, _cred_id, _cred_account)
                        elif _action == "detach":
                            _content = _credtool.remove_attachment(ctx.session_id, _cred_id, _cred_account)
                        else:
                            _content = f"ERROR: unknown credentials action '{_action}'. Call credentials() with no arguments for usage."
                        results_by_id[tc.tool_use_id] = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=_content,
                            is_error=_content.startswith("ERROR:"),
                        )

                elif tc.tool_name == "sentinel_setup":
                    # --- Sentinel (Slack/Telegram) setup tool ---
                    # Stores channel tokens + writes per-colony notifications
                    # config in-process (same store/config the desktop UI uses).
                    # configure/test default to the colony bound to this session.
                    from framework.agent_loop.internals import (
                        sentinel_tool as _sentineltool,
                    )

                    _binding = None
                    _prov = getattr(ctx, "colony_binding_provider", None)
                    if callable(_prov):
                        try:
                            _binding = _prov()
                        except Exception:
                            _binding = None
                    _content = await _sentineltool.handle(
                        tc.tool_input if isinstance(tc.tool_input, dict) else {},
                        default_colony_id=getattr(_binding, "name", None),
                    )
                    results_by_id[tc.tool_use_id] = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content=_content,
                        is_error=_content.startswith("ERROR:"),
                    )

                elif tc.tool_name == "suggest_colony":
                    # --- Framework-level suggest_colony handling ---
                    # Mirrors ask_user: stash a payload, set
                    # user_input_requested=True, and rely on the
                    # post-turn block to emit the
                    # COLONY_SUGGESTION_REQUESTED event and wait for the
                    # frontend to either drive the colony fork (POST
                    # /api/sessions with colony_id + source_session_id)
                    # or inject a dismissal message back into this
                    # session.
                    import re as _re

                    _COLONY_NAME_RE = _re.compile(r"^[a-z0-9_]+$")

                    if stream_id != "queen":
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=("ERROR: suggest_colony is queen-only. Workers fan out via run_worker inside an existing colony."),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    # Phase gate (defense in depth). Mirrors the
                    # tool-list partition: ``suggest_colony`` is wired
                    # into the queen's INDEPENDENT-phase tool list only
                    # (see queen_orchestrator._phase_tools), so a
                    # colony-mode queen shouldn't see it. Defense in
                    # depth: re-check the same precondition (phase ==
                    # "independent") at dispatch, the way ``escalate``
                    # re-checks ``stream_id`` even though the tool is
                    # already filtered out for queen/judge streams. The
                    # phase reads through ``iteration_metadata_provider``
                    # — the same callback the loop already uses for the
                    # per-iteration event payload — so this stays
                    # decoupled from QueenPhaseState's API.
                    _phase: str | None = None
                    if ctx.iteration_metadata_provider is not None:
                        try:
                            _phase = (ctx.iteration_metadata_provider() or {}).get("phase")
                        except Exception:
                            _phase = None
                    if _phase is not None and _phase != "independent":
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: suggest_colony is only available "
                                "in the independent (DM) phase. You are "
                                "already inside a colony — fan out with "
                                "run_worker, schedule recurring "
                                "runs with set_trigger, or share protocol "
                                "with workers via write_skill."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    raw_name = tc.tool_input.get("colony_id", "")
                    cn = str(raw_name or "").strip()
                    if not _COLONY_NAME_RE.match(cn):
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: colony_id must be lowercase "
                                "alphanumeric with underscores (e.g. "
                                "'morning_hn_digest'). The popup is "
                                "pre-filled with this slug, so make it "
                                "user-friendly."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    raw_reason = tc.tool_input.get("reason", "")
                    reason = str(raw_reason or "").strip() or None

                    user_input_requested = True
                    self._pending_colony_suggestion = {
                        "colony_id": cn,
                        "reason": reason,
                    }

                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content=(
                            "Colony creation popup opened with "
                            f"colony_id='{cn}'. Waiting for the user "
                            "to confirm or dismiss. If they confirm, "
                            "this session will lock and you'll be "
                            "compacted into the new colony's queen "
                            "seed. If they dismiss, you'll receive a "
                            "follow-up message and can continue."
                        ),
                        is_error=False,
                    )
                    results_by_id[tc.tool_use_id] = result

                elif tc.tool_name == "task_create" and tc.tool_input.get("new_colony") is True:
                    # --- Framework-level task_create(new_colony=true) intercept ---
                    # The colony-pivot path needs to BLOCK until the user
                    # confirms or dismisses the popup, which can take many
                    # minutes — far longer than ``tool_call_timeout_seconds``
                    # (60s). Doing the wait inside the registered task_create
                    # executor causes ``asyncio.wait_for`` in
                    # tool_result_handler.execute_tool to cancel the call and
                    # surface a "tool timed out" error to the queen (observed
                    # in linkedin_4 session 20260519: queen called the pivot
                    # correctly, framework cancelled at 60s, queen fell back
                    # to doing the off-goal work inline). The fix: intercept
                    # here BEFORE execute_tool runs, mirror the suggest_colony
                    # pattern — stash the rich payload, set user_input_requested,
                    # return a synthetic "popup opened" result, and let the
                    # post-turn block park on _input_ready. Accept/dismiss
                    # routes wake the loop via inject_event.

                    if stream_id != "queen":
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=("ERROR: task_create(new_colony=true) is queen-only. Workers don't spawn colonies."),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    # Phase gate — defense in depth; the schema only
                    # exposes new_colony to colony-phase queens, but a
                    # mid-session switch_to_independent could leave a
                    # stale field reachable.
                    _phase: str | None = None
                    if ctx.iteration_metadata_provider is not None:
                        try:
                            _phase = (ctx.iteration_metadata_provider() or {}).get("phase")
                        except Exception:
                            _phase = None
                    if _phase is not None and _phase != "colony":
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                f"ERROR: task_create(new_colony=true) is colony-only (currently '{_phase}'). "
                                "In DM, use new_session for unrelated work, or suggest_colony to spawn the first colony."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    goal_in = tc.tool_input.get("goal")
                    handoff_in = tc.tool_input.get("handoff")
                    tasks_in = tc.tool_input.get("tasks")
                    goal = (goal_in or "").strip() if isinstance(goal_in, str) else ""
                    handoff = (handoff_in or "").strip() if isinstance(handoff_in, str) else ""
                    if not goal:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: task_create(new_colony=true) requires a `goal` — state the new colony's "
                                "purpose in one sentence, in the user's terms. The new colony anchors on this."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue
                    if not handoff:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: task_create(new_colony=true) requires a `handoff`. The new colony inherits "
                                "NOTHING from this conversation; without a handoff its queen starts blind. Write a "
                                "complete, objective brief: user goal in their terms, concrete data (names, URLs, "
                                "IDs, file paths, account to use, exact requirements), decisions made and options "
                                "ruled out, constraints, what 'done' looks like."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue
                    if not isinstance(tasks_in, list) or not tasks_in:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: task_create(new_colony=true) requires a non-empty `tasks` array"
                                " — the plan that gets seeded into the new colony."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    pivot_payload = {
                        "goal": goal,
                        "handoff": handoff,
                        "tasks": list(tasks_in),
                        "source_phase": "colony",
                    }

                    # Sink runs FIRST so the orchestrator can veto on
                    # state agent_loop doesn't know about (e.g. a freshly
                    # forked colony whose kickoff turn must not re-pivot,
                    # signalled via session.fork_kickoff_pending). The
                    # sink returns None to accept, or an error string to
                    # reject; we propagate the string as an is_error
                    # tool result and skip the popup entirely.
                    sink = getattr(ctx, "pivot_payload_sink", None)
                    sink_error: str | None = None
                    if callable(sink):
                        try:
                            sink_result = sink(pivot_payload)
                            if isinstance(sink_result, str) and sink_result.strip():
                                sink_error = sink_result.strip()
                        except Exception:
                            logger.warning(
                                "[%s] pivot_payload_sink raised — popup may render without rich payload",
                                node_id,
                                exc_info=True,
                            )
                    if sink_error:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=f"ERROR: {sink_error}",
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    # Stash the rich payload on self so the post-turn
                    # block emits a rich COLONY_SUGGESTION_REQUESTED.
                    # The popup renders goal + handoff + task_count
                    # inline so the user can review what's being handed
                    # over before confirming.
                    self._pending_colony_pivot = pivot_payload
                    user_input_requested = True

                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content=(
                            "Colony pivot popup opened (goal: "
                            f"{goal[:80]}). Waiting for the user to "
                            "confirm a slug and create the new colony, "
                            "or dismiss. If they confirm, the new colony "
                            "is spawned with this handoff + task plan "
                            "and they navigate there; you stay here "
                            "idle on this colony's existing plan. If "
                            "they dismiss, you'll receive a follow-up "
                            "message instructing you to call ask_user "
                            "for explicit direction. End your turn now "
                            "and wait for the user."
                        ),
                        is_error=False,
                    )
                    results_by_id[tc.tool_use_id] = result

                elif tc.tool_name == "escalate":
                    # --- Framework-level escalate handling ---
                    reason = str(tc.tool_input.get("reason", "")).strip()
                    context = str(tc.tool_input.get("context", "")).strip()

                    if stream_id in ("queen", "judge"):
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=("ERROR: escalate is only available to worker nodes/sub-agents, not queen/judge streams."),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        continue

                    if self._event_bus is None:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=("ERROR: EventBus unavailable. Could not emit escalation request."),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        continue

                    await self._event_bus.emit_escalation_requested(
                        stream_id=stream_id,
                        node_id=node_id,
                        reason=reason,
                        context=context,
                        execution_id=execution_id,
                        request_id=uuid.uuid4().hex,
                    )
                    queen_input_requested = True

                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content="Escalation requested to queen; waiting for guidance.",
                        is_error=False,
                    )
                    results_by_id[tc.tool_use_id] = result

                elif tc.tool_name == "report_to_parent":
                    # --- Framework-level report_to_parent handling ---
                    # Parallel workers call this to emit a structured
                    # SUBAGENT_REPORT and terminate cleanly. The worker
                    # owner (Worker instance) records the explicit report
                    # via ``record_explicit_report`` so Worker.run()'s
                    # terminal event emission picks it up.
                    if not (isinstance(stream_id, str) and stream_id.startswith("worker:")):
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: report_to_parent is only available to "
                                "parallel workers (stream_id='worker:*'). "
                                "The overseer talks to the user directly."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        continue

                    report_tc_input = dict(tc.tool_input)
                    report_tc_input["tool_use_id"] = tc.tool_use_id
                    result = handle_report_to_parent(report_tc_input)
                    results_by_id[tc.tool_use_id] = result

                    # Record on the owning Worker so its terminal event
                    # emission picks up the explicit report.
                    owner_worker = getattr(self, "_owner_worker", None)
                    if owner_worker is not None:
                        normalised = report_tc_input.get("_normalised", {})
                        owner_worker.record_explicit_report(
                            status=normalised.get("status", "success"),
                            summary=normalised.get("summary", ""),
                            data=normalised.get("data", {}),
                        )

                    # Terminate the loop cleanly after this turn. Set the
                    # same completion flag path that set_output used so
                    # the next iteration exits with success.
                    self._report_terminated = True

                else:
                    # --- Real tool: check for truncated args, else queue ---
                    if "_raw" in tc.tool_input:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                f"Tool call to '{tc.tool_name}' failed: your arguments "
                                "were truncated (hit output token limit). "
                                "Simplify or shorten your arguments and try again."
                            ),
                            is_error=True,
                        )
                        logger.warning(
                            "[%s] Blocked truncated _raw tool call: %s",
                            node_id,
                            tc.tool_name,
                        )
                        results_by_id[tc.tool_use_id] = result
                    else:
                        # Replay detector — two-tier:
                        #   * Below ``tool_doom_loop_threshold`` consecutive
                        #     identical occurrences: soft-prepend a steer
                        #     onto the stored result and still execute
                        #     (back-compat with screenshots/evaluates that
                        #     are legitimately repeated).
                        #   * At/above the threshold: trip the breaker —
                        #     refuse to execute, stub the offending and
                        #     sibling calls, park the loop as
                        #     ParkReason.DOOM_LOOP. The streak counts both
                        #     duplicates **within this batch** (catches a
                        #     single LLM response with N identical
                        #     parallel calls) and across **recent
                        #     completed assistant turns**.
                        # Skip the replay breaker for tools that legitimately
                        # repeat identical calls — polls (collect_result,
                        # terminal_job_logs), idempotent reads/observers
                        # (a hive-browser screenshot, …), and synthetics. Single source
                        # of truth: LoopConfig.replay_exempt_tools (shared with
                        # the doom-loop fingerprint above). Without this, e.g. a
                        # 3-minute image poll trips the breaker at 3 polls.
                        if self._config.replay_detector_enabled and tc.tool_name not in self._config.replay_exempt_tools:
                            canonical = _canonical_args(tc.tool_input)
                            in_batch_dup = batch_dup_count[(tc.tool_name, canonical)]
                            prior_streak = conversation.count_consecutive_completed_tool_calls(
                                tc.tool_name,
                                tc.tool_input,
                                within_last_turns=self._config.replay_detector_within_last_turns,
                                skip_most_recent_assistant=True,
                            )
                            streak = prior_streak + in_batch_dup
                            threshold = self._config.tool_doom_loop_threshold

                            if streak >= threshold:
                                await self._trip_tool_breaker(
                                    ctx=ctx,
                                    conversation=conversation,
                                    stream_id=stream_id,
                                    node_id=node_id,
                                    execution_id=execution_id,
                                    offending_tc=tc,
                                    pending_real=pending_real,
                                    tool_calls=tool_calls,
                                    results_by_id=results_by_id,
                                    streak=streak,
                                    prior_streak=prior_streak,
                                    in_batch_dup=in_batch_dup,
                                )
                                # _trip_tool_breaker raises TurnCancelled.

                            prior = (
                                conversation.find_completed_tool_call(
                                    tc.tool_name,
                                    tc.tool_input,
                                    within_last_turns=self._config.replay_detector_within_last_turns,
                                )
                                if prior_streak > 0
                                else None
                            )
                            if prior is not None or in_batch_dup > 1:
                                logger.warning(
                                    "[%s] replay detected: %s prior_streak=%d in_batch_dup=%d — executing anyway",
                                    node_id,
                                    tc.tool_name,
                                    prior_streak,
                                    in_batch_dup,
                                )
                                self._bump("tool_call_replay_detected")
                                if self._event_bus and prior is not None:
                                    await self._event_bus.emit_tool_call_replay_detected(
                                        stream_id=stream_id,
                                        node_id=node_id,
                                        tool_name=tc.tool_name,
                                        prior_seq=prior.seq,
                                        execution_id=execution_id,
                                    )
                                replay_prefixes_by_id[tc.tool_use_id] = (
                                    f"[Replay detected: {tc.tool_name} matches "
                                    f"{prior_streak} prior consecutive turn(s) + "
                                    f"{max(0, in_batch_dup - 1)} duplicate(s) in this batch. "
                                    "Result still produced below — consider whether the "
                                    "retry was necessary.]\n"
                                )
                        pending_real.append(tc)

            # Phase 2a: partition real tools by concurrency safety.
            # Read-only tools flagged concurrency_safe run in one parallel
            # batch (bounded by a semaphore). Everything else - shell, file
            # writes, browser actions, unknown MCP tools - runs serially
            # afterwards so we can't race an edit against a bash command
            # that touches the same path. Result ordering is preserved via
            # results_by_id below; the split only affects scheduling.
            # Reuses the same _early_safe_names set the stream used for
            # Gap 1 early dispatch, so "safe" means exactly the same
            # thing in both places.
            parallel_batch: list[ToolCallEvent] = []
            serial_batch: list[ToolCallEvent] = []
            for tc in pending_real:
                if tc.tool_name in _early_safe_names:
                    parallel_batch.append(tc)
                else:
                    serial_batch.append(tc)

            if pending_real:
                # Cap on concurrent read-only tool executions. Ten matches
                # Claude Code's StreamingToolExecutor default and keeps MCP
                # server load bounded on turns where the model issues a
                # big fan-out of reads.
                _PARALLEL_CAP = 10
                _parallel_sem = asyncio.Semaphore(_PARALLEL_CAP)

                async def _capped(
                    _tc: ToolCallEvent,
                    _sem: asyncio.Semaphore = _parallel_sem,  # noqa: B008,B023
                ) -> tuple[ToolResult | BaseException, str, float]:
                    async with _sem:
                        return await _timed_execute(_tc)

                timed_results_by_id: dict[str, tuple[ToolResult | BaseException, str, float] | BaseException] = {}

                async def _cancel_turn_with_stubs(
                    _pending: list[ToolCallEvent] = pending_real,  # noqa: B006,B008
                ) -> None:
                    """Populate [Tool call cancelled by user] stubs for
                    every pending tool so the conversation doesn't end
                    up with dangling tool_use blocks, then raise
                    TurnCancelled so the queen event loop continues
                    cleanly. Shared between the parallel and serial
                    phases because either can observe CancelledError.
                    """
                    for _tc in _pending:
                        await conversation.add_tool_result(
                            tool_use_id=_tc.tool_use_id,
                            content="[Tool call cancelled by user]",
                            is_error=True,
                        )
                        await self._publish_tool_completed(
                            stream_id,
                            node_id,
                            _tc.tool_use_id,
                            _tc.tool_name,
                            "[Tool call cancelled by user]",
                            is_error=True,
                            execution_id=execution_id,
                        )
                    raise TurnCancelled() from None

                # Phase 2b: resolve the concurrency-safe batch. Prefer
                # any early task already started during streaming (Gap
                # 1) so we don't accidentally execute the same tool
                # twice; for everything else, schedule via the semaphore-
                # capped wrapper as before.
                if parallel_batch:
                    _awaitables: list = []
                    for tc in parallel_batch:
                        early = _early_tasks.get(tc.tool_use_id)
                        if early is not None:
                            _awaitables.append(early)
                        else:
                            _awaitables.append(_capped(tc))
                    self._tool_task = asyncio.ensure_future(asyncio.gather(*_awaitables, return_exceptions=True))
                    try:
                        parallel_timed = await self._tool_task
                    finally:
                        self._tool_task = None
                    # gather(return_exceptions=True) captures CancelledError
                    # as a return value instead of propagating it.
                    # Distinguish cancel_current_turn() (cancels only
                    # _tool_task) from stop_worker (cancels the parent
                    # execution task). When the parent itself is
                    # cancelled, cancelling() > 0 — propagate so the
                    # executor can save state. Otherwise convert to
                    # TurnCancelled so the queen event loop continues,
                    # writing cancellation stubs for every pending tool
                    # first so the conversation has no dangling
                    # tool_use blocks.
                    for entry in parallel_timed:
                        if isinstance(entry, asyncio.CancelledError):
                            task = asyncio.current_task()
                            if task and task.cancelling() > 0:
                                raise entry
                            await _cancel_turn_with_stubs()
                    for tc, entry in zip(parallel_batch, parallel_timed, strict=True):
                        timed_results_by_id[tc.tool_use_id] = entry

                # Phase 2c: run unsafe tools sequentially. On a raised
                # exception, cancel the remaining siblings with a clear
                # error so the model sees the cascade instead of a silent
                # drop. A ToolResult with is_error=True is a normal return
                # (e.g. "file not found") and does NOT trip the cascade -
                # the model should see subsequent errors too.
                # CancelledError is handled separately via the shared
                # user-cancel helper above.
                _serial_cascade_broken = False
                for tc in serial_batch:
                    if _serial_cascade_broken:
                        timed_results_by_id[tc.tool_use_id] = (
                            ToolResult(
                                tool_use_id=tc.tool_use_id,
                                content=(
                                    "Cancelled: an earlier non-concurrent tool "
                                    "in this turn raised an exception. Re-issue "
                                    "this call once the previous error is resolved."
                                ),
                                is_error=True,
                            ),
                            datetime.now(UTC).isoformat(),
                            0.0,
                        )
                        continue

                    self._tool_task = asyncio.ensure_future(_timed_execute(tc))
                    try:
                        entry = await self._tool_task
                    finally:
                        self._tool_task = None

                    timed_results_by_id[tc.tool_use_id] = entry
                    raw_check = entry[0] if isinstance(entry, tuple) else entry
                    if isinstance(raw_check, asyncio.CancelledError):
                        task = asyncio.current_task()
                        if task and task.cancelling() > 0:
                            raise raw_check
                        await _cancel_turn_with_stubs()
                    elif isinstance(raw_check, BaseException):
                        _serial_cascade_broken = True

                # Phase 2d: reassemble results in original call order so
                # the rest of the loop sees no difference from the
                # pre-partition world.
                for tc in pending_real:
                    entry = timed_results_by_id[tc.tool_use_id]
                    if isinstance(entry, BaseException):
                        raw = entry
                        _start_iso = datetime.now(UTC).isoformat()
                        _dur_s = 0
                    else:
                        raw, _start_iso, _dur_s = entry
                    timing_by_id[tc.tool_use_id] = {
                        "start_timestamp": _start_iso,
                        "duration_s": _dur_s,
                    }
                    if isinstance(raw, BaseException):
                        result = _build_tool_error_result(tc, raw)
                    else:
                        result = raw
                    results_by_id[tc.tool_use_id] = await self._truncate_tool_result(result, tc.tool_name)

            # Phase 3: record results into conversation in original order,
            # build logged/real lists, and publish completed events.
            #
            # Vision-fallback prefetch: a single turn may fire several
            # image-producing tools in parallel (e.g. one screenshot
            # per tab). Captioning each one takes a vision LLM round
            # trip (1–30 s). Doing them sequentially in this loop
            # would serialise that latency per image. Instead, kick
            # off all caption tasks concurrently NOW, and await each
            # one just-in-time inside the per-tc body. If only a
            # single image needs captioning, this collapses to a
            # single await with no overhead.
            _model_text_only = ctx.llm and _vision_fallback_active(ctx.llm.model)
            caption_tasks: dict[str, asyncio.Task[tuple[str, str] | None]] = {}
            if _model_text_only:
                for tc in tool_calls[:executed_in_batch]:
                    res = results_by_id.get(tc.tool_use_id)
                    if not res or not res.image_content:
                        continue
                    intent = extract_intent_for_tool(
                        conversation,
                        tc.tool_name,
                        tc.tool_input or {},
                    )
                    caption_tasks[tc.tool_use_id] = asyncio.create_task(_captioning_chain(intent, res.image_content))

            # Reminder POST_TOOL_USE point: ride the tail of this batch's
            # last real tool result so the model sees fresh state right
            # where it's working (see framework.agent_loop.reminders).
            # Best-effort — a reminder failure must never break the turn.
            _task_tail: str | None = None
            _tail_target_id: str | None = None
            try:
                _batch_tool_names = [tc.tool_name for tc in tool_calls[:executed_in_batch]]
                _task_tail = await self._reminder_hub.fire(ReminderPoint.POST_TOOL_USE, ctx, tool_names=_batch_tool_names)
            except Exception:
                logger.debug("reminder POST_TOOL_USE failed", exc_info=True)

            # Soft tool-call budget checkpoint. Each time the running
            # count crosses a new budget multiple (below the hard stop)
            # we ride one escalating checkpoint reminder on the tail.
            # `crossed` is capped at hard_multiple - 1 so the soft
            # checkpoint never doubles up with the hard-stop advisory.
            #
            # Additional sources fire at TOOL_BUDGET_CHECKPOINT (tracker
            # snapshot, colony fleet snapshot, …); their bodies are merged
            # into the same <system-reminder> block so the model sees one
            # consolidated checkpoint, not a wall of sibling blocks.
            _budget_tail: str | None = None
            if soft_interval > 0 and hard_limit > 0:
                crossed = min(
                    tool_call_count // soft_interval,
                    max(1, self._config.tool_call_hard_multiple) - 1,
                )
                if crossed > soft_budget_reminders:
                    soft_budget_reminders = crossed
                    self._bump("tool_budget_soft_reminder")
                    _checkpoint_bodies = [_render_tool_budget_checkpoint(tool_call_count, hard_limit)]
                    try:
                        _extra_items = await self._reminder_hub.collect(ReminderPoint.TOOL_BUDGET_CHECKPOINT, ctx)
                    except Exception:
                        logger.debug(
                            "reminder TOOL_BUDGET_CHECKPOINT (soft) failed",
                            exc_info=True,
                        )
                        _extra_items = []
                    _checkpoint_bodies.extend(r.body for r in _extra_items)
                    _budget_tail = wrap_reminder(_checkpoint_bodies)

            # One combined tail block — task reminders and the budget
            # checkpoint both ride the last real tool result.
            _combined_tail = "\n\n".join(t for t in (_task_tail, _budget_tail) if t) or None
            if _combined_tail:
                for _tc in reversed(tool_calls[:executed_in_batch]):
                    if _tc.tool_name not in ("ask_user", "escalate"):
                        _tail_target_id = _tc.tool_use_id
                        break

            for tc in tool_calls[:executed_in_batch]:
                result = results_by_id.get(tc.tool_use_id)
                if result is None:
                    continue  # shouldn't happen

                # Build log entries for real tools (exclude synthetic tools)
                if tc.tool_name not in (
                    "ask_user",
                    "escalate",
                ):
                    tool_entry = {
                        "tool_use_id": tc.tool_use_id,
                        "tool_name": tc.tool_name,
                        "tool_input": tc.tool_input,
                        "content": result.content,
                        "is_error": result.is_error,
                        **timing_by_id.get(tc.tool_use_id, {}),
                    }
                    real_tool_results.append(tool_entry)
                    logged_tool_calls.append(tool_entry)

                image_content = result.image_content
                # Vision-fallback marker spliced into the persisted text
                # below. None when no captioning ran (vision-capable
                # main model, no images, or no fallback chain reached
                # this tool).
                vision_fallback_marker: str | None = None
                if image_content and tc.tool_use_id in caption_tasks:
                    caption_result = await caption_tasks.pop(tc.tool_use_id)
                    if caption_result:
                        caption, vision_model = caption_result
                        # If the captioned image was a crop (zoom / clipped
                        # screenshot), the subagent's (fx,fy) labels are
                        # crop-relative — remap them to viewport fractions
                        # so a coordinate click off this caption lands right.
                        caption = remap_caption_for_crop(caption, result.content)
                        vision_fallback_marker = f"[vision-fallback caption]\n{caption}"
                        logger.info(
                            "vision_fallback: captioned %d image(s) for tool '%s' (main model '%s' routed through fallback model '%s')",
                            len(image_content),
                            tc.tool_name,
                            ctx.llm.model if ctx.llm else "?",
                            vision_model,
                        )
                    else:
                        vision_fallback_marker = "[image stripped — vision fallback exhausted]"
                        logger.info(
                            "vision_fallback: exhausted; stripping %d image(s) from tool '%s' result without caption (model '%s')",
                            len(image_content),
                            tc.tool_name,
                            ctx.llm.model if ctx.llm else "?",
                        )
                    image_content = None

                # Apply replay-detector steer prefix if this call matched a
                # recent successful invocation. Only applies to non-error
                # results — an error already breaks the replay chain.
                stored_content = result.content
                if not result.is_error:
                    _prefix = replay_prefixes_by_id.get(tc.tool_use_id)
                    if _prefix:
                        stored_content = f"{_prefix}{stored_content or ''}"

                # Splice the vision-fallback caption / placeholder into
                # the persisted text after any prefix has been applied.
                if vision_fallback_marker:
                    stored_content = f"{stored_content or ''}\n\n{vision_fallback_marker}"

                # Append the task / budget reminder tail to this
                # batch's last real tool result.
                if _combined_tail and tc.tool_use_id == _tail_target_id:
                    stored_content = f"{stored_content or ''}\n\n{_combined_tail}"

                await conversation.add_tool_result(
                    tool_use_id=tc.tool_use_id,
                    content=stored_content,
                    is_error=result.is_error,
                    image_content=image_content,
                    is_skill_content=result.is_skill_content,
                    # Out-of-band recovery pointer so microcompaction/prune can
                    # cite where this result's full content lives on disk even
                    # when it was small enough to be inlined without a header.
                    spillover_path=getattr(result, "spillover_path", None),
                )
                # Publish tool_call_completed immediately for every tool,
                # including ask_user. ask_user returns synchronously
                # ("Waiting for user input...") — its completion event
                # carries that same content whether emitted now or after
                # the user answers, so deferring it only left the tool
                # pill spinning indefinitely (and orphaned on restart).
                # The "awaiting input" UX is driven separately by the
                # CLIENT_INPUT_REQUESTED event / question widget.
                await self._publish_tool_completed(
                    stream_id,
                    node_id,
                    tc.tool_use_id,
                    tc.tool_name,
                    result.content,
                    result.is_error,
                    execution_id,
                )

                # Real-time context-usage update after this individual tool
                # result lands in the conversation. The debug panel reads
                # this stream to show "size of the prompt that will go out
                # next" — granularity is per-tool-call, including content
                # for the just-added result, all tool args, system prompt,
                # and tool definitions.
                await self._publish_context_usage(ctx, conversation, "post_tool_call", tools=tools)

            # Grace iteration: append placeholders for every non-terminal
            # call that was skipped above. Same shape as the limit_hit
            # branch — keeps the conversation's tool_use/tool_result pairs
            # balanced so the next model turn doesn't repeat them, and
            # puts the entries into real_tool_results / logged_tool_calls
            # so the implicit judge sees them as attempted (RETRY path).
            # We deliberately do NOT short-circuit return here: terminal
            # tools (e.g. report_to_parent) that *did* dispatch in this
            # same batch still need their handlers to run normally so
            # _report_terminated can be set.
            if grace_skipped:
                logger.info(
                    "Grace iteration: skipped %d non-terminal call(s) (whitelist=%s): %s",
                    len(grace_skipped),
                    sorted(_GRACE_TERMINAL_TOOLS),
                    ", ".join(tc.tool_name for tc in grace_skipped),
                )
                self._bump("grace_iteration_skipped", len(grace_skipped))
                for tc in grace_skipped:
                    await conversation.add_tool_result(
                        tool_use_id=tc.tool_use_id,
                        content=_GRACE_SKIP_MSG,
                        is_error=False,
                    )
                    skip_entry = {
                        "tool_use_id": tc.tool_use_id,
                        "tool_name": tc.tool_name,
                        "tool_input": tc.tool_input,
                        "content": _GRACE_SKIP_MSG,
                        "is_error": False,
                    }
                    real_tool_results.append(skip_entry)
                    logged_tool_calls.append(skip_entry)

            # If the limit was hit, add a result for every remaining tool
            # call so the conversation stays consistent. Without this, the
            # assistant message contains tool_calls that have no matching
            # tool results, causing the LLM to repeat them in the next
            # turn (infinite loop). The deferred calls are NOT errors —
            # nothing was attempted and nothing failed — so each result
            # is a neutral advisory (is_error=False) and the overflow is
            # surfaced once as a <system-reminder>, not as N tool errors.
            if limit_hit:
                skipped = tool_calls[executed_in_batch:]
                logger.info(
                    "Tool-call budget hard stop (%d) reached — deferring %d remaining call(s) with an advisory (not an error): %s",
                    hard_limit,
                    len(skipped),
                    ", ".join(tc.tool_name for tc in skipped),
                )
                self._bump("tool_budget_deferred", len(skipped))
                if lifetime_limit_hit:
                    defer_msg = (
                        "[Not executed — you reached your cumulative tool-call "
                        "budget for this task. This is not an error and the call "
                        "did not fail. You are out of work budget: next turn winds "
                        "down — report_to_parent now (tracker_upsert / task_update "
                        "also allowed) instead of re-issuing this call.]"
                    )
                else:
                    defer_msg = (
                        "[Not executed — the tool-call budget hard stop was reached "
                        "before this call. This is not an error and the call did "
                        "not fail; re-issue it on the next turn if still needed.]"
                    )
                for tc in skipped:
                    await conversation.add_tool_result(
                        tool_use_id=tc.tool_use_id,
                        content=defer_msg,
                        is_error=False,
                    )
                    # Deferred calls go into real_tool_results so the judge
                    # sees they were attempted — as non-errors.
                    defer_entry = {
                        "tool_use_id": tc.tool_use_id,
                        "tool_name": tc.tool_name,
                        "tool_input": tc.tool_input,
                        "content": defer_msg,
                        "is_error": False,
                    }
                    real_tool_results.append(defer_entry)
                    logged_tool_calls.append(defer_entry)
                # One consolidated advisory for the whole overflow, posted
                # to the reminder hub as a reactive reminder — drained
                # (and <system-reminder>-wrapped) at the next iteration
                # boundary like every other hub reminder.
                #
                # TOOL_BUDGET_CHECKPOINT sources (tracker snapshot, fleet
                # snapshot) also fire here. Unlike the soft path — which
                # rides the *current* turn's tool_result tail — the hard
                # stop is forcibly ending the turn, and its advisory is
                # already next-turn (via ``post()``). We merge the source
                # bodies into the SAME posted reminder so the model sees
                # one consolidated "you hit the wall, here's what was
                # deferred, here's the state of the world" block on its
                # next turn — not the advisory in one block and the
                # snapshot in another.
                if lifetime_limit_hit:
                    _hard_stop_bodies = [
                        f"{len(skipped)} tool call(s) were deferred: you reached "
                        f"your cumulative tool-call budget of {lifetime_budget} "
                        "for this whole task (not a per-turn cap). Nothing failed "
                        "— the deferred calls are listed above with a neutral "
                        "result.\n\n"
                        "You are out of work budget. Next turn is a wind-down: "
                        "dispatch is restricted to report_to_parent / "
                        "tracker_upsert / task_update. Consolidate what you have "
                        "and call report_to_parent now — do not start new work."
                    ]
                else:
                    _hard_stop_bodies = [
                        f"{len(skipped)} tool call(s) were deferred: you hit the "
                        f"tool-call budget hard stop of {hard_limit} calls for this "
                        "turn-loop. Nothing failed — the deferred calls are listed "
                        "above with a neutral result.\n\n"
                        "Hitting the hard stop is a strong signal to step back, not "
                        "to plough on. Next turn: consolidate (batch related work, "
                        "drop redundant calls), and if the current approach isn't "
                        "converging, switch to a different approach or consult the "
                        "user rather than re-issuing the same calls."
                    ]
                try:
                    _hard_extra = await self._reminder_hub.collect(ReminderPoint.TOOL_BUDGET_CHECKPOINT, ctx)
                except Exception:
                    logger.debug(
                        "reminder TOOL_BUDGET_CHECKPOINT (hard) failed",
                        exc_info=True,
                    )
                    _hard_extra = []
                _hard_stop_bodies.extend(r.body for r in _hard_extra)
                self._reminder_hub.post(
                    Reminder(
                        source="tool_budget",
                        body="\n\n".join(_hard_stop_bodies),
                        meta={
                            "deferred": len(skipped),
                            "cause": "lifetime_budget" if lifetime_limit_hit else "per_turn_hard_stop",
                            "limit": lifetime_budget if lifetime_limit_hit else hard_limit,
                        },
                    )
                )
                # Prune old tool results NOW to prevent context bloat on the
                # next turn.  The char-based token estimator underestimates
                # actual API tokens, so the standard compaction check in the
                # outer loop may not trigger in time.
                protect = max(2000, self._config.max_context_tokens // 12)
                pruned = await conversation.prune_old_tool_results(
                    protect_tokens=protect,
                    min_prune_tokens=max(1000, protect // 3),
                )
                if pruned > 0:
                    logger.info(
                        "Post-limit pruning: cleared %d old tool results (budget: %d)",
                        pruned,
                        self._config.max_context_tokens,
                    )
                # Limit hit — return from this turn so the judge can
                # evaluate instead of looping back for another stream.
                return (
                    final_text,
                    real_tool_results,
                    outputs_set_this_turn,
                    token_counts,
                    logged_tool_calls,
                    user_input_requested,
                    queen_input_requested,
                    final_system_prompt,
                    final_messages,
                    False,
                )

            # --- Image eviction: strip old screenshot image_content ---
            # Screenshots from hive-browser screenshot are inlined as base64
            # data URLs in message.image_content. Each screenshot costs
            # ~250k tokens when the provider counts base64 as text
            # (gemini, most non-Anthropic providers). Four screenshots
            # in one conversation blew through gemini's 1M context in
            # session_20260415_104727_5c4ed7ff and caused garbage
            # output ("协日" as the final assistant text). We evict
            # aggressively after every tool batch — independent of the
            # char-based usage_ratio, which severely underestimates
            # image cost (counts each image as ~2000 tokens vs the
            # ~250k actually billed). Text metadata stays on the
            # evicted messages so the agent can still reason about
            # "I took a screenshot at step N".
            _max_imgs = self._config.max_retained_screenshots
            if _max_imgs >= 0:
                await conversation.evict_old_images(keep_latest=_max_imgs)

            # --- Mid-turn pruning: prevent context blowup within a single turn ---
            if conversation.usage_ratio() >= 0.6:
                protect = max(2000, self._config.max_context_tokens // 12)
                pruned = await conversation.prune_old_tool_results(
                    protect_tokens=protect,
                    min_prune_tokens=max(1000, protect // 3),
                )
                if pruned > 0:
                    logger.info(
                        "Mid-turn pruning: cleared %d old tool results (usage now %.0f%%)",
                        pruned,
                        conversation.usage_ratio() * 100,
                    )

            await self._publish_context_usage(ctx, conversation, "post_tool_results", tools=tools)

            # If the turn requested external input (ask_user or queen handoff),
            # return immediately so the outer loop can block before judge eval.
            if user_input_requested or queen_input_requested:
                return (
                    final_text,
                    real_tool_results,
                    outputs_set_this_turn,
                    token_counts,
                    logged_tool_calls,
                    user_input_requested,
                    queen_input_requested,
                    final_system_prompt,
                    final_messages,
                    False,
                )

            # Worker called report_to_parent — bail out of the inner loop now
            # so we don't burn an extra LLM call before the outer for-loop's
            # _report_terminated check at the top of the next iteration fires.
            if self._report_terminated:
                return (
                    final_text,
                    real_tool_results,
                    outputs_set_this_turn,
                    token_counts,
                    logged_tool_calls,
                    user_input_requested,
                    queen_input_requested,
                    final_system_prompt,
                    final_messages,
                    False,
                )

            # Tool calls processed -- loop back to stream with updated conversation
            inner_turn += 1

    # -------------------------------------------------------------------
    # Synthetic tools: set_output, ask_user, escalate
    # ask_user is used by queen
    # escalate is used by worker
    # -------------------------------------------------------------------

    def _build_ask_user_tool(self) -> Tool:
        """Build the synthetic ask_user tool. Delegates to synthetic_tools module."""
        return build_ask_user_tool()

    def _build_escalate_tool(self) -> Tool:
        """Build the synthetic escalate tool. Delegates to synthetic_tools module."""
        return build_escalate_tool()

    # -------------------------------------------------------------------
    # Judge evaluation
    # -------------------------------------------------------------------

    async def _judge_turn(
        self,
        ctx: AgentContext,
        conversation: NodeConversation,
        accumulator: OutputAccumulator,
        assistant_text: str,
        tool_results: list[dict],
        iteration: int,
    ) -> JudgeVerdict:
        """Evaluate the current state, with retry + fallback.

        The judge makes its own LLM call, which can fail transiently
        (network blip, 429/529, stream stall). Without a safety net here
        a single hiccup in the judge would crash the whole loop — even
        though the work under evaluation was perfectly fine. We retry
        transient failures a few times, then fall back to ACCEPT so the
        loop keeps moving instead of dying on a judge outage.
        """
        max_attempts = max(1, self._config.max_stream_retries)
        for attempt in range(max_attempts):
            try:
                return await judge_turn(
                    mark_complete_flag=False,
                    judge=self._judge,
                    ctx=ctx,
                    conversation=conversation,
                    accumulator=accumulator,
                    assistant_text=assistant_text,
                    tool_results=tool_results,
                    iteration=iteration,
                    get_missing_output_keys_fn=self._get_missing_output_keys,
                    max_context_tokens=self._config.max_context_tokens,
                )
            except Exception as e:
                is_last = attempt == max_attempts - 1
                if not self._is_transient_error(e) or is_last:
                    if is_last and self._is_transient_error(e):
                        self._bump("judge_fallback_accept")
                        logger.error(
                            "[judge] iter=%d: transient failure persisted across %d attempts "
                            "(%s) — skipping judgment and accepting the turn to keep moving: %s",
                            iteration,
                            max_attempts,
                            type(e).__name__,
                            str(e)[:200],
                        )
                        return JudgeVerdict(
                            action="ACCEPT",
                            feedback=(f"[judge unavailable after {max_attempts} attempts: {type(e).__name__}; accepting to avoid stalling the loop]"),
                        )
                    # Non-transient — re-raise so the caller sees it.
                    raise
                self._bump("judge_transient_retry")
                delay = min(
                    self._config.stream_retry_backoff_base * (2**attempt),
                    self._config.stream_retry_max_delay,
                )
                logger.warning(
                    "[judge] iter=%d: transient error (%s), retrying in %.1fs (%d/%d): %s",
                    iteration,
                    type(e).__name__,
                    delay,
                    attempt + 1,
                    max_attempts,
                    str(e)[:200],
                )
                await asyncio.sleep(delay)
        # Unreachable — the loop above always returns or raises.
        raise RuntimeError("_judge_turn retry loop exited unexpectedly")

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _extract_tool_call_history(
        conversation: NodeConversation,
        max_entries: int = 30,
    ) -> str:
        """Build a compact tool call history from the conversation.

        Delegates to :func:`extract_tool_call_history` in conversation.py.
        """
        from framework.agent_loop.conversation import extract_tool_call_history

        return extract_tool_call_history(conversation.messages, max_entries=max_entries)

    def _build_initial_message(self, ctx: AgentContext) -> str:
        """Build the initial user message from input data and buffer.

        Includes ALL input_data (not just declared input_keys) so that
        upstream handoff data flows through regardless of key naming.
        Declared input_keys are also checked in data buffer as fallback.
        """
        parts = []
        seen: set[str] = set()
        # Include everything from input_data (flexible handoff)
        for key, value in ctx.input_data.items():
            if value is not None:
                parts.append(f"{key}: {value}")
                seen.add(key)
        # Fallback: check data buffer for declared input_keys not already covered
        for key in ctx.agent_spec.input_keys:
            if key not in seen:
                value = ctx.input_data.get(key)
                if value is not None:
                    parts.append(f"{key}: {value}")
        if ctx.goal_context:
            parts.append(f"\nGoal: {ctx.goal_context}")
        return "\n".join(parts) if parts else ""

    def _get_missing_output_keys(
        self,
        accumulator: OutputAccumulator,
        output_keys: list[str] | None,
        nullable_keys: list[str] | None = None,
    ) -> list[str]:
        """Return output keys that have not been set yet."""
        if not output_keys:
            return []
        return [k for k in output_keys if accumulator.get(k) is None]

    @staticmethod
    def _ngram_similarity(s1: str, s2: str, n: int = 2) -> float:
        """Jaccard similarity of n-gram sets. Delegates to stall_detector module."""
        return ngram_similarity(s1, s2, n)

    def _is_stalled(self, recent_responses: list[str]) -> bool:
        """Detect stall using n-gram similarity. Delegates to stall_detector module."""
        return is_stalled(
            recent_responses,
            self._config.stall_detection_threshold,
            self._config.stall_similarity_threshold,
        )

    @staticmethod
    def _is_transient_error(exc: BaseException) -> bool:
        """Classify whether an exception is transient. Delegates to tool_result_handler module."""
        return is_transient_error(exc)

    @staticmethod
    def _is_capacity_error(exc: BaseException) -> bool:
        """Detect provider-side capacity / rate-limit errors.

        These are the errors that typically resolve on their own if we
        just wait long enough — 429 rate limit, 529 overloaded, and the
        equivalent provider-specific flavours. We treat these differently
        from generic transient errors (network blips) and retry them
        persistently within a wall-clock budget instead of giving up
        after a fixed attempt count.
        """
        cls_name = type(exc).__name__.lower()
        if "ratelimit" in cls_name or "overloaded" in cls_name:
            return True
        try:
            from litellm.exceptions import RateLimitError, ServiceUnavailableError

            if isinstance(exc, (RateLimitError, ServiceUnavailableError)):
                return True
        except ImportError:
            pass
        error_str = str(exc).lower()
        keywords = (
            "429",
            "529",
            "rate limit",
            "rate_limit",
            "overloaded",
            "capacity",
            "too many requests",
            "service unavailable",
        )
        return any(kw in error_str for kw in keywords)

    @staticmethod
    def _fingerprint_tool_calls(
        tool_results: list[dict],
    ) -> list[tuple[str, str]]:
        """Create deterministic fingerprints. Delegates to stall_detector module."""
        return fingerprint_tool_calls(tool_results)

    def _is_tool_doom_loop(
        self,
        recent_tool_fingerprints: list[list[tuple[str, str]]],
    ) -> tuple[bool, str]:
        """Detect doom loop. Delegates to stall_detector module."""
        return is_tool_doom_loop(
            recent_tool_fingerprints=recent_tool_fingerprints,
            threshold=self._config.tool_doom_loop_threshold,
            enabled=self._config.tool_doom_loop_enabled,
        )

    async def _trip_tool_breaker(
        self,
        *,
        ctx: AgentContext,
        conversation: NodeConversation,
        stream_id: str,
        node_id: str,
        execution_id: str,
        offending_tc: ToolCallEvent,
        pending_real: list[ToolCallEvent],
        tool_calls: list[ToolCallEvent],
        results_by_id: dict[str, ToolResult],
        streak: int,
        prior_streak: int,
        in_batch_dup: int,
    ) -> None:
        """Hard-breaker variant of the replay detector.

        Refuses the offending tool call, stubs every sibling pending-or-
        already-queued call in the same batch (so the conversation has no
        dangling ``tool_use`` blocks), emits the doom-loop event, injects a
        ``[SYSTEM]`` user message, and parks the loop as
        ``ParkReason.DOOM_LOOP`` — which maps to
        ``LoopActivity.INTERRUPTED``. Always raises :class:`TurnCancelled`
        so the outer execute loop continues cleanly.

        Called *before* ``pending_real.append(tc)``, so the offending tool
        never executes. Callers should not assume control returns.
        """
        description = (
            f"Tool breaker tripped: {offending_tc.tool_name} reached "
            f"{streak} consecutive identical call(s) "
            f"(prior_streak={prior_streak}, in_batch_dup={in_batch_dup}, "
            f"threshold={self._config.tool_doom_loop_threshold})"
        )
        logger.warning("[%s] %s", node_id, description)
        self._bump("tool_call_breaker_tripped")

        # Stub the offending call.
        offending_stub = (
            f"[Breaker tripped: {offending_tc.tool_name} has been called "
            f"{streak} times in a row with identical arguments. This call "
            "was NOT executed. Take a different action or produce a "
            "text-only turn to clear the streak.]"
        )
        await conversation.add_tool_result(
            tool_use_id=offending_tc.tool_use_id,
            content=offending_stub,
            is_error=True,
        )
        await self._publish_tool_completed(
            stream_id,
            node_id,
            offending_tc.tool_use_id,
            offending_tc.tool_name,
            offending_stub,
            is_error=True,
            execution_id=execution_id,
        )

        # Stub every sibling tool in this batch that doesn't already have
        # a result (framework-tools like ask_user have already populated
        # results_by_id; pending_real entries are queued real tools that
        # haven't run yet; later-in-list entries haven't been visited).
        sibling_stub = (
            "[Tool call cancelled — breaker tripped on a sibling tool call "
            "in the same response. Re-issue with a different argument or "
            "a different approach.]"
        )
        offending_id = offending_tc.tool_use_id
        # Track which tool_use_ids already have a result in the conversation
        # so we don't double-stub framework tools that wrote their result
        # earlier in the dispatch loop. add_tool_result has its own dedup
        # guard as a backstop.
        already_resulted: set[str] = set()
        for m in conversation.messages:
            if m.role == "tool" and m.tool_use_id is not None:
                already_resulted.add(m.tool_use_id)
        for sibling in tool_calls:
            if sibling.tool_use_id == offending_id:
                continue
            if sibling.tool_use_id in results_by_id:
                continue
            if sibling.tool_use_id in already_resulted:
                continue
            await conversation.add_tool_result(
                tool_use_id=sibling.tool_use_id,
                content=sibling_stub,
                is_error=True,
            )
            await self._publish_tool_completed(
                stream_id,
                node_id,
                sibling.tool_use_id,
                sibling.tool_name,
                sibling_stub,
                is_error=True,
                execution_id=execution_id,
            )
        pending_real.clear()

        # Telemetry — reuse the existing doom-loop event so the UI banner
        # is identical to the turn-level detector's.
        if self._event_bus:
            await self._event_bus.emit_tool_doom_loop(
                stream_id=stream_id,
                node_id=node_id,
                description=description,
                execution_id=execution_id,
            )

        # System message so the model sees the reason on resume.
        await conversation.add_user_message(
            f"[SYSTEM] {description}. You are repeating the same tool "
            "calls with identical arguments. Try a different approach or "
            "different arguments."
        )

        # Park the loop as INTERRUPTED via ParkReason.DOOM_LOOP, then
        # raise TurnCancelled so the outer execute loop continues.
        await self._await_user_input(ctx, reason=ParkReason.DOOM_LOOP)
        raise TurnCancelled()

    def _resolve_tool_timeout(self, tool_name: str) -> float:
        """Effective per-call timeout: longest matching prefix override wins.

        ``tool_timeout_overrides`` exists because the flat 60s default is
        wrong for browser tools — heavy-page evaluates legitimately run
        long, and on the shared per-server MCP client a call queued behind
        a slow one needs the same headroom (a false timeout used to
        force-disconnect the shared transport for every worker).
        """
        overrides = getattr(self._config, "tool_timeout_overrides", None) or {}
        best = ""
        for prefix in overrides:
            if tool_name.startswith(prefix) and len(prefix) > len(best):
                best = prefix
        return overrides[best] if best else self._config.tool_call_timeout_seconds

    async def _execute_tool(self, tc: ToolCallEvent) -> ToolResult:
        """Execute a tool call. Three paths:

        * ``collect_result`` — the synthetic poll tool for backgrounded calls;
          handled here, never dispatched to an MCP server.
        * a tool in ``LoopConfig.background_tools`` — dispatched as a detached
          task; a handle is returned IMMEDIATELY so a call that can run for
          minutes (e.g. image generation) never blocks the loop or trips the
          per-call timeout. The agent retrieves it via ``collect_result``.
        * everything else — runs inline via ``_execute_tool_inner`` with the
          resolved per-tool timeout.
        """
        if tc.tool_name == "collect_result":
            return await self._collect_background_result(tc)

        # Worker-side tool tiering. Two branches, both scoped to streams that
        # carry a ToolTierState (queens keep theirs in QueenPhaseState and hit
        # neither):
        #   * ``search_tools`` executes in-loop against THIS worker's tier —
        #     the registry-registered handler closes over the queen's state.
        #   * a searchable-but-not-loaded name is refused with an instructive
        #     error instead of executing. Dispatch is registry-membership only,
        #     so without this gate a deferred tool would silently run even
        #     though its schema was never advertised. The log line doubles as
        #     the telemetry counter for wrongly-deferred tools.
        _tier = getattr(getattr(self, "_agent_ctx", None), "tool_tier_state", None)
        if _tier is not None:
            if tc.tool_name == "search_tools":
                _handler = getattr(self, "_worker_search_tools_handler", None)
                if _handler is not None:
                    try:
                        _payload = await _handler(**(tc.tool_input or {}))
                    except TypeError as e:
                        _payload = json.dumps({"error": f"search_tools: {e}"})
                    return ToolResult(tool_use_id=tc.tool_use_id, content=_payload)
            elif tc.tool_name in _tier.searchable_names():
                logger.info(
                    "[tool-tier] blocked not-loaded tool call: %s (stream=%s)",
                    tc.tool_name,
                    getattr(getattr(self, "_agent_ctx", None), "stream_id", "?"),
                )
                return ToolResult(
                    tool_use_id=tc.tool_use_id,
                    content=json.dumps(
                        {
                            "error": (
                                f"Tool '{tc.tool_name}' is available but its schema is not loaded yet. "
                                f'Call search_tools(query="select:{tc.tool_name}") first, then retry — '
                                "it stays loaded for the rest of the session."
                            )
                        }
                    ),
                    is_error=True,
                )

        # Bridge multi-tenant routing: for AstrBot-proxied tools (astrbot__*),
        # inject the current run's session_id so the AstrBot side can route the
        # tool's side effects (e.g. a generated image) back to the correct QQ chat.
        if tc.tool_name.startswith("astrbot__"):
            try:
                _sid = getattr(getattr(self, "_agent_ctx", None), "session_id", None)
                if _sid and isinstance(tc.tool_input, dict):
                    tc.tool_input["_hive_session"] = _sid
            except Exception:
                pass

        # Queen strict-account preflight. The MCP tools run in a stdio
        # subprocess with its own CredentialStoreAdapter that can't see the
        # parent's ``_strict_account_mode`` ContextVar, so the check happens
        # here: block OAuth calls that omit ``account=`` when >1 account is
        # authorized, returning the ``account_selection_required`` payload.
        preflight = _queen_account_preflight(tc)
        if preflight is not None:
            return preflight

        if tc.tool_name in (getattr(self._config, "background_tools", None) or set()):
            return await self._start_background_tool(tc)

        return await self._execute_tool_inner(tc, self._resolve_tool_timeout(tc.tool_name))

    async def _execute_tool_inner(self, tc: ToolCallEvent, timeout: float) -> ToolResult:
        """Run a tool to completion with ``timeout`` (the non-background path).

        The initial executor call is offloaded to a thread pool so that sync
        executors (MCP STDIO tools that block on ``future.result()``) don't
        freeze the event loop. Also runs the attach_file chip-publish post-step.
        """
        result = await execute_tool(
            tool_executor=self._tool_executor,
            tc=tc,
            timeout=timeout,
            skill_dirs=getattr(self, "_skill_dirs", []),
        )
        # Cheap post-hoc classification: the timeout handler in
        # execute_tool builds a canned error message we can recognise
        # here without threading a callback through. Good enough for
        # telemetry; the content format is stable framework-internal.
        if result.is_error and "timed out after" in (result.content or ""):
            self._bump("tool_call_timeout")
        elif result.is_error:
            self._bump("tool_error")
        # attach_file post-process: the tool runs in a queen-agnostic
        # pooled MCP subprocess and can't see HIVE_STORAGE_PATH, so the
        # tool returns plain entries with `resolved` paths. The framework
        # is the SINGLE chip-publishing path — copy the bytes here and
        # inject `hive_attachment_url` into the result summary so the
        # chip pipeline (add_assistant_message → msg.images → renderer's
        # AttachmentChip) can surface it. If publish fails for any reason
        # `_publish_attach_file_result` rewrites the result into an
        # is_error so the agent surfaces failure instead of fake success.
        if tc.tool_name == "attach_file" and not result.is_error:
            try:
                result = _publish_attach_file_result(result, self._conversation_store)
            except Exception as exc:  # noqa: BLE001
                logger.exception("attach_file chip publish raised: %s", exc)
                result = _attach_file_publish_failure(result, f"unexpected error: {exc}")
        return result

    async def _start_background_tool(self, tc: ToolCallEvent) -> ToolResult:
        """Run a background tool's real call, returning a handle only if it's slow.

        Backgrounding is not free: the handle costs the agent a whole extra
        model turn to spend on ``collect_result``, and that turn is inference
        latency, not tool time. So we wait ``background_tool_grace_seconds``
        first: work that lands inside the window returns its real result on
        the original call and never mints a handle; only genuinely slow work
        (image generation, a long command) pays for the deferred path.
        (Ported from the desktop runtime's async-job logic — without it,
        terminal_exec ran foreground and slammed into the shared 60s tool
        timeout, resetting the MCP connection.)
        """
        timeout = float(getattr(self._config, "background_tool_timeout_seconds", 235.0))

        def _retrieve(t: asyncio.Task) -> None:
            # Retrieve any exception so a never-collected task doesn't log
            # "exception was never retrieved"; the awaited path in
            # collect_result surfaces real failures to the agent.
            if not t.cancelled():
                t.exception()

        # Register BEFORE the grace await, not after. CancelledError derives
        # from BaseException, so a user stop landing inside the grace window
        # propagates straight out of this coroutine — and anything not yet in
        # ``_background_calls`` at that moment is a live subprocess nobody can
        # reach or collect. Claiming the handle up front costs only a gap in
        # handle numbering on the fast path, which the agent never sees.
        self._bg_counter += 1
        handle = f"bg_{self._bg_counter}"
        task = asyncio.create_task(self._execute_tool_inner(tc, timeout))
        task.add_done_callback(_retrieve)
        self._background_calls[handle] = {
            "task": task,
            "tool": tc.tool_name,
            "started": time.time(),
        }

        grace = float(getattr(self._config, "background_tool_grace_seconds", 5.0))
        if grace > 0:
            try:
                # shield: a grace-window timeout must not cancel the in-flight
                # work — it still has the full `timeout` budget to finish in.
                result = await asyncio.wait_for(asyncio.shield(task), timeout=grace)
            except TimeoutError:
                pass  # genuinely slow — fall through and hand back the handle
            except Exception:
                # Failed fast. Let collect_result surface it rather than
                # duplicating the error shaping here.
                pass
            else:
                # Beat the window: hand back the real result and retire the
                # handle, since there is nothing left to collect.
                self._background_calls.pop(handle, None)
                return result

        logger.info("[AgentLoop] backgrounded tool '%s' as %s", tc.tool_name, handle)
        payload = {
            "status": "started",
            "handle": handle,
            "tool": tc.tool_name,
            "note": (
                f"'{tc.tool_name}' is running in the background (can take a few "
                f'minutes). Call collect_result(handle="{handle}") to fetch it; '
                'it returns {"status":"pending"} until done, then the real result.'
            ),
        }
        return ToolResult(tool_use_id=tc.tool_use_id, content=json.dumps(payload), is_error=False)

    async def _collect_background_result(self, tc: ToolCallEvent) -> ToolResult:
        """Handle the synthetic ``collect_result`` poll for a backgrounded tool."""
        tool_input = tc.tool_input or {}
        handle = tool_input.get("handle")
        entry = self._background_calls.get(handle) if isinstance(handle, str) else None
        if entry is None:
            return ToolResult(
                tool_use_id=tc.tool_use_id,
                content=json.dumps(
                    {"error": (f"Unknown or already-collected handle: {handle!r}. It may have been collected already, or never started.")}
                ),
                is_error=True,
            )
        try:
            wait_seconds = int(tool_input.get("wait_seconds", 30))
        except (TypeError, ValueError):
            wait_seconds = 30
        wait_seconds = max(1, min(wait_seconds, 45))
        task: asyncio.Task = entry["task"]
        try:
            # shield: a poll-wait timeout must not cancel the in-flight work.
            result = await asyncio.wait_for(asyncio.shield(task), timeout=wait_seconds)
        except TimeoutError:
            return ToolResult(
                tool_use_id=tc.tool_use_id,
                content=json.dumps(
                    {
                        "status": "pending",
                        "handle": handle,
                        "elapsed_seconds": int(time.time() - entry["started"]),
                    }
                ),
                is_error=False,
            )
        except Exception as exc:  # noqa: BLE001
            self._background_calls.pop(handle, None)
            return ToolResult(
                tool_use_id=tc.tool_use_id,
                content=json.dumps({"error": f"Background tool '{entry['tool']}' failed: {exc}"}),
                is_error=True,
            )
        # Done — hand back the tool's real result, re-attached to THIS
        # collect_result call so the conversation pairs request/result correctly.
        self._background_calls.pop(handle, None)
        return ToolResult(
            tool_use_id=tc.tool_use_id,
            content=result.content,
            is_error=result.is_error,
            image_content=getattr(result, "image_content", None),
            is_skill_content=getattr(result, "is_skill_content", False),
        )

    def _next_spill_filename(self, tool_name: str) -> str:
        """Return a short, monotonic filename for a tool result spill."""
        self._spill_counter += 1
        # Shorten common tool name prefixes to save tokens
        short = tool_name.removeprefix("tool_").removeprefix("mcp_")
        return f"{short}_{self._spill_counter}.txt"

    def _restore_spill_counter(self) -> None:
        """Scan spillover_dir for existing spill files and restore the counter."""
        self._spill_counter = restore_spill_counter(
            spillover_dir=self._config.spillover_dir,
        )

    # ------------------------------------------------------------------
    # JSON metadata / smart preview helpers for truncation
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json_metadata(parsed: Any, *, _depth: int = 0, _max_depth: int = 3) -> str:
        """Return a concise structural summary of parsed JSON.

        Reports key names, value types, and — crucially — array lengths so
        the LLM knows how much data exists beyond the preview.

        Returns an empty string for simple scalars.
        """
        return extract_json_metadata(
            parsed=parsed,
        )

    @staticmethod
    def _build_json_preview(parsed: Any, *, max_chars: int = 5000) -> str | None:
        """Build a smart preview of parsed JSON, truncating large arrays.

        Shows first 3 + last 1 items of large arrays with explicit count
        markers so the LLM cannot mistake the preview for the full dataset.

        Returns ``None`` if no truncation was needed (no large arrays).
        """
        return build_json_preview(
            parsed=parsed,
            max_chars=max_chars,
        )

    async def _truncate_tool_result(
        self,
        result: ToolResult,
        tool_name: str,
    ) -> ToolResult:
        """Persist tool result to file and optionally truncate for context.

        When *spillover_dir* is configured, EVERY non-error tool result is
        saved to a file (short filename like ``web_search_1.txt``).  A
        ``[Saved to '...']`` annotation is appended so the reference
        survives pruning and compaction.

        - Small results (≤ limit): full content kept + file annotation
        - Large results (> limit): preview + file reference
        - Errors: pass through unchanged

        For large results this does a synchronous JSON round-trip
        (``json.loads`` + pretty-print ``json.dumps(indent=2)``) plus a
        file write. On big payloads — web_search, web_fetch, full-page
        extractions — this can block the event loop for hundreds of ms
        per call. We offload to a worker thread so concurrent tool
        executions keep running while one large result is being
        pretty-printed and spilled to disk.
        """
        # Fast path: small results don't need thread offload. The
        # function only touches disk / does heavy JSON work when the
        # result exceeds either the truncation or spillover threshold,
        # so cheap pass-throughs stay on the main loop.
        needs_offload = len(result.content) > 10_000 and not result.is_error
        if not needs_offload:
            return truncate_tool_result(
                result=result,
                tool_name=tool_name,
                max_tool_result_chars=self._config.max_tool_result_chars,
                spillover_dir=self._config.spillover_dir,
                next_spill_filename_fn=self._next_spill_filename,
            )
        return await asyncio.to_thread(
            truncate_tool_result,
            result=result,
            tool_name=tool_name,
            max_tool_result_chars=self._config.max_tool_result_chars,
            spillover_dir=self._config.spillover_dir,
            next_spill_filename_fn=self._next_spill_filename,
        )

    # --- Compaction -----------------------------------------------------------

    # Optional override for the window-derived split threshold (tests
    # shrink it); None -> llm_compact_char_limit(max_context_tokens).
    _LLM_COMPACT_CHAR_LIMIT: int | None = None
    # Max recursion depth for binary-search splitting.
    _LLM_COMPACT_MAX_DEPTH = 10

    def _compact_char_limit(self) -> int:
        if self._LLM_COMPACT_CHAR_LIMIT is not None:
            return self._LLM_COMPACT_CHAR_LIMIT
        from framework.agent_loop.internals.compaction import llm_compact_char_limit

        return llm_compact_char_limit(self._config.max_context_tokens)

    async def _compact(
        self,
        ctx: AgentContext,
        conversation: NodeConversation,
        accumulator: OutputAccumulator | None = None,
    ) -> None:
        """Compact conversation history to stay within token budget.

        0. Microcompaction — count-based clearing of old compactable tool results.
        1. Prune old tool results (always, free).
        2. LLM summary compaction — generates a summary and places it as the first
           message, replacing old messages. Used whenever pruning alone does not
           fully resolve the budget.
        3. Emergency deterministic summary only if LLM failed or unavailable.
        """
        # Reminder hook: let sources re-assert context that compaction
        # would otherwise summarize away (e.g. the open task list).
        await self._fire_reminder(ReminderPoint.PRE_COMPACT, ctx, conversation)
        result = await compact(
            ctx=ctx,
            conversation=conversation,
            accumulator=accumulator,
            config=self._config,
            event_bus=self._event_bus,
            char_limit=self._compact_char_limit(),
            max_depth=self._LLM_COMPACT_MAX_DEPTH,
        )
        # After compaction: re-announce surfaces the model can't see unless
        # told (deferred-tool manifest, skills catalog). Placed into the fresh
        # post-summary context so the first post-compact turn has them — the
        # summary itself does not faithfully reproduce a tool/skill listing.
        await self._fire_reminder(ReminderPoint.POST_COMPACT, ctx, conversation)
        return result

    # --- LLM compaction with binary-search splitting ----------------------

    async def _llm_compact(
        self,
        ctx: AgentContext,
        messages: list,
        accumulator: OutputAccumulator | None = None,
        _depth: int = 0,
    ) -> str:
        """Summarise *messages* with LLM, splitting recursively if too large.

        If the formatted text exceeds the window-derived char limit or the LLM
        rejects the call with a context-length error, the messages are split
        in half and each half is summarised independently.  Tool history is
        appended once at the top-level call (``_depth == 0``).
        """
        return await llm_compact(
            ctx=ctx,
            messages=messages,
            accumulator=accumulator,
            _depth=_depth,
            char_limit=self._compact_char_limit(),
            max_depth=self._LLM_COMPACT_MAX_DEPTH,
            max_context_tokens=self._config.max_context_tokens,
        )

    # --- Compaction helpers ------------------------------------------------

    @staticmethod
    def _format_messages_for_summary(messages: list) -> str:
        """Format messages as text for LLM summarisation."""
        return format_messages_for_summary(messages)

    def _build_llm_compaction_prompt(
        self,
        ctx: AgentContext,
        accumulator: OutputAccumulator | None,
        formatted_messages: str,
    ) -> str:
        """Build prompt for LLM compaction targeting 50% of token budget."""
        return build_llm_compaction_prompt(
            ctx,
            accumulator,
            formatted_messages,
            max_context_tokens=self._config.max_context_tokens,
        )

    # -------------------------------------------------------------------
    # Persistence: restore, cursor, injection, pause
    # -------------------------------------------------------------------

    async def _restore(
        self,
        ctx: AgentContext,
    ) -> RestoredState | None:
        """Attempt to restore from a previous checkpoint.

        Returns a ``RestoredState`` with conversation, accumulator, iteration
        counter, and stall/doom-loop detection state — everything needed to
        resume exactly where execution stopped.
        """
        return await restore(
            conversation_store=self._conversation_store,
            ctx=ctx,
            config=self._config,
        )

    async def _write_cursor(
        self,
        ctx: AgentContext,
        conversation: NodeConversation,
        accumulator: OutputAccumulator,
        iteration: int,
        *,
        recent_responses: list[str] | None = None,
        recent_tool_fingerprints: list[list[tuple[str, str]]] | None = None,
        pending_input: dict[str, Any] | None = None,
    ) -> None:
        """Write checkpoint cursor for crash recovery.

        Persists iteration counter, accumulator outputs, and stall/doom-loop
        detection state so that resume picks up exactly where execution stopped.
        Always includes ``self._user_stopped`` so an explicit user-stop
        survives runtime restart — without this, killing the app would let
        a cancelled queen auto-resume on reload.
        """
        return await write_cursor(
            conversation_store=self._conversation_store,
            ctx=ctx,
            conversation=conversation,
            accumulator=accumulator,
            iteration=iteration,
            recent_responses=recent_responses,
            recent_tool_fingerprints=recent_tool_fingerprints,
            pending_input=pending_input,
            user_stopped=self._user_stopped,
            tool_calls_used=self._tool_calls_used,
        )

    async def _drain_injection_queue(self, conversation: NodeConversation, ctx: AgentContext) -> int:
        """Drain all pending injected events as user messages. Returns count."""
        on_committed = None
        if self._event_bus is not None and ctx.emits_client_io:
            stream_id = ctx.stream_id or ctx.agent_id
            node_id = ctx.agent_id
            execution_id = ctx.execution_id or ""

            async def on_committed(seq: int, correlation_id: str | None) -> None:
                # Emit the true injection time + seq for this boundary drain so
                # the UI places the user bubble where the conversation has it.
                await self._event_bus.emit_client_input_committed(
                    stream_id=stream_id,
                    node_id=node_id,
                    execution_id=execution_id,
                    seq=seq,
                    correlation_id=correlation_id,
                )

        return await drain_injection_queue(
            queue=self._injection_queue,
            conversation=conversation,
            ctx=ctx,
            caption_image_fn=_captioning_chain,
            on_client_input_committed=on_committed,
        )

    async def _drain_trigger_queue(self, conversation: NodeConversation) -> int:
        """Drain all pending trigger events as a single batched user message.

        Multiple triggers are merged so the LLM sees them atomically and can
        reason about all pending triggers before acting.
        """
        return await drain_trigger_queue(
            queue=self._trigger_queue,
            conversation=conversation,
        )

    async def _check_pause(
        self,
        ctx: AgentContext,
        conversation: NodeConversation,
        iteration: int,
    ) -> bool:
        """
        Check if pause has been requested. Returns True if paused.

        Note: This check happens BEFORE starting iteration N, after completing N-1.
        If paused, the node exits having completed {iteration} iterations (0 to iteration-1).
        """
        return await check_pause(
            ctx=ctx,
            conversation=conversation,
            iteration=iteration,
        )

    # -------------------------------------------------------------------
    # EventBus publishing helpers
    # -------------------------------------------------------------------

    async def _publish_loop_started(self, stream_id: str, node_id: str, execution_id: str = "") -> None:
        return await publish_loop_started(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            max_iterations=self._config.max_iterations,
            execution_id=execution_id,
        )

    async def _fire_reminder(
        self,
        point: ReminderPoint,
        ctx: AgentContext,
        conversation: NodeConversation,
    ) -> bool:
        """Fire a reminder lifecycle point that injects as a user message.

        Used for SESSION_START / USER_PROMPT_SUBMIT / PRE_COMPACT / STOP —
        the points with no tool result to ride. POST_TOOL_USE is handled
        separately (it appends to a tool result's tail). Best-effort —
        never raises.

        Returns True when an injected source declared itself *energizing*
        (:attr:`ReminderSource.energizes`) — the STOP call site reads this to
        keep the loop awake for one more turn instead of parking on a
        reminder the agent would not read until the user next speaks.
        """
        try:
            block, energized = await self._reminder_hub.fire_energized(point, ctx)
            if block:
                await conversation.add_user_message(block)
                self._bump("reminders_injected")
                logger.info("[reminder] injected %s block (%d chars)", point, len(block))
                # Surface lifecycle reminders on the same telemetry event
                # as the rest of the hub. fire() merges sources into one
                # block, so the producer is the point, not a named source.
                await self._emit_reminder_injected(
                    ctx,
                    Reminder(
                        body=block,
                        source=f"point:{point}",
                        meta={"point": str(point)},
                    ),
                )
                return energized
        except Exception:
            logger.debug("reminder fire failed at %s", point, exc_info=True)
        return False

    async def _run_hooks(
        self,
        event: str,
        conversation: NodeConversation,
        trigger: str | None = None,
    ) -> None:
        """Run all registered hooks for *event*, applying their results.

        Each hook receives a HookContext and may return a HookResult that:
        - replaces the system prompt (result.system_prompt)
        - injects an extra user message (result.inject)
        Hooks run in registration order; each sees the prompt as left by the
        previous hook.
        """
        return await run_hooks(
            hooks_config=self._config.hooks,
            event=event,
            conversation=conversation,
            trigger=trigger,
        )

    async def _publish_context_usage(
        self,
        ctx: AgentContext,
        conversation: NodeConversation,
        trigger: str,
        *,
        tools: list | None = None,
    ) -> None:
        """Emit a CONTEXT_USAGE_UPDATED event with current context window state.

        Pass ``tools`` when available so the estimate includes the JSON
        tool-definitions size — for queens with many tools registered this
        is a non-trivial component of the actual prompt sent to the LLM.
        """
        return await publish_context_usage(
            event_bus=self._event_bus,
            ctx=ctx,
            conversation=conversation,
            trigger=trigger,
            tools=tools,
        )

    async def _publish_iteration(
        self,
        stream_id: str,
        node_id: str,
        iteration: int,
        execution_id: str = "",
        extra_data: dict | None = None,
    ) -> None:
        return await publish_iteration(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            iteration=iteration,
            execution_id=execution_id,
            extra_data=extra_data,
        )

    def _compute_turn_diagnostics(
        self,
        *,
        conversation_static: str,
        conversation_suffix: str,
        request_messages: list[dict] | None,
        model: str,
    ) -> dict:
        """Compute per-turn cache-diagnostic fingerprints for events.jsonl.

        Cheap (sha256 of ~15KB is microseconds). Always on — the diagnostic
        value of having post-mortem-debuggable fingerprints on every
        production turn outweighs the negligible overhead, and the fields
        are omitted from the event payload when None so legacy consumers
        see no schema change.

        Returns a dict with four keys:
        * ``system_prefix_sha``: 12-char hex sha256 of the static system
          prefix that carries ``cache_control: ephemeral``. Drives
          cross-turn cache-stability analysis.
        * ``system_suffix_sha``: 12-char hex sha256 of the dynamic
          suffix (narrative, when present; empty for most agents now that
          timestamps and recall ride the conversation instead). Useful to
          confirm the split is being emitted at all.
        * ``history_anchor_idx``: index in ``request_messages`` where
          the rolling history breakpoint was placed, or ``-1`` if none.
        * ``message_count``: length of ``request_messages`` (system
          included), or ``None`` when the request wasn't captured.
        """
        import hashlib

        def _sha(s: str) -> str:
            return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]

        prefix_sha = _sha(conversation_static or "")
        suffix_sha = _sha(conversation_suffix or "")

        anchor_idx: int = -1
        msg_count: int | None = None
        if request_messages is not None:
            msg_count = len(request_messages)
            # request_messages includes the system message at index 0
            # when one was prepended. Strip it before asking the helper
            # so the returned index matches the OUTGOING messages list
            # the provider actually sent (caller-friendly indexing).
            try:
                from framework.llm.litellm import _history_cache_breakpoint_index

                anchor_idx = _history_cache_breakpoint_index(request_messages, model)
            except Exception:
                anchor_idx = -1

        return {
            "system_prefix_sha": prefix_sha,
            "system_suffix_sha": suffix_sha,
            "history_anchor_idx": anchor_idx,
            "message_count": msg_count,
        }

    async def _publish_llm_turn_complete(
        self,
        stream_id: str,
        node_id: str,
        stop_reason: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cost_usd: float = 0.0,
        credits: float | None = None,
        execution_id: str = "",
        iteration: int | None = None,
        system_prefix_sha: str | None = None,
        system_suffix_sha: str | None = None,
        history_anchor_idx: int | None = None,
        message_count: int | None = None,
    ) -> None:
        return await publish_llm_turn_complete(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            stop_reason=stop_reason,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cost_usd=cost_usd,
            credits=credits,
            execution_id=execution_id,
            iteration=iteration,
            system_prefix_sha=system_prefix_sha,
            system_suffix_sha=system_suffix_sha,
            history_anchor_idx=history_anchor_idx,
            message_count=message_count,
        )

    def _log_skip_judge(
        self,
        ctx: AgentContext,
        node_id: str,
        iteration: int,
        feedback: str,
        tool_calls: list[dict],
        llm_text: str,
        turn_tokens: dict[str, int],
        iter_start: float,
    ) -> None:
        """Log a CONTINUE step that skips judge evaluation (e.g., waiting for input)."""
        return log_skip_judge(
            ctx=ctx,
            node_id=node_id,
            iteration=iteration,
            feedback=feedback,
            tool_calls=tool_calls,
            llm_text=llm_text,
            turn_tokens=turn_tokens,
            iter_start=iter_start,
        )

    async def _publish_loop_completed(self, stream_id: str, node_id: str, iterations: int, execution_id: str = "") -> None:
        return await publish_loop_completed(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            iterations=iterations,
            execution_id=execution_id,
        )

    async def _publish_stalled(self, stream_id: str, node_id: str, execution_id: str = "") -> None:
        return await publish_stalled(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            execution_id=execution_id,
        )

    async def _publish_text_delta(
        self,
        stream_id: str,
        node_id: str,
        content: str,
        snapshot: str,
        ctx: AgentContext,
        execution_id: str = "",
        iteration: int | None = None,
        inner_turn: int = 0,
    ) -> None:
        # Strip leading whitespace from first output chunk for client_facing nodes
        # (some LLMs like Kimi output leading whitespace before text)
        if ctx.agent_spec.client_facing and not snapshot and content:
            content = content.lstrip()
            if not content:  # Content was all whitespace
                return

        return await publish_text_delta(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            content=content,
            snapshot=snapshot,
            ctx=ctx,
            execution_id=execution_id,
            iteration=iteration,
            inner_turn=inner_turn,
        )

    async def _publish_tool_started(
        self,
        stream_id: str,
        node_id: str,
        tool_use_id: str,
        tool_name: str,
        tool_input: dict,
        execution_id: str = "",
    ) -> None:
        return await publish_tool_started(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            tool_input=tool_input,
            execution_id=execution_id,
        )

    async def _publish_tool_completed(
        self,
        stream_id: str,
        node_id: str,
        tool_use_id: str,
        tool_name: str,
        result: str,
        is_error: bool,
        execution_id: str = "",
    ) -> None:
        # A tool result landed — the loop is making progress. Reset the
        # session-idle clock here so a long-running tool doesn't trip
        # the watchdog the instant it returns.
        self._mark_session_progress()
        return await publish_tool_completed(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            result=result,
            is_error=is_error,
            execution_id=execution_id,
        )

    async def _publish_judge_verdict(
        self,
        stream_id: str,
        node_id: str,
        action: str,
        feedback: str = "",
        judge_type: str = "implicit",
        iteration: int = 0,
        execution_id: str = "",
    ) -> None:
        return await publish_judge_verdict(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            action=action,
            feedback=feedback,
            judge_type=judge_type,
            iteration=iteration,
            execution_id=execution_id,
        )

    async def _publish_output_key_set(
        self,
        stream_id: str,
        node_id: str,
        key: str,
        execution_id: str = "",
    ) -> None:
        return await publish_output_key_set(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            key=key,
            execution_id=execution_id,
        )

    # -------------------------------------------------------------------
    # Subagent Execution
    # -------------------------------------------------------------------
