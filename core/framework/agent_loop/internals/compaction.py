"""Conversation compaction pipeline.

Implements the multi-level compaction strategy:
0. Microcompaction (count-based tool result clearing — cheapest)
1. Prune old tool results (token-budget based)
2. Structure-preserving compaction (spillover)
3. LLM summary compaction (with recursive splitting)
4. Emergency deterministic summary (no LLM)
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from typing import Any

from framework.agent_loop.conversation import Message, NodeConversation
from framework.agent_loop.internals.event_publishing import publish_context_usage
from framework.agent_loop.internals.types import LoopConfig, OutputAccumulator
from framework.host.event_bus import EventBus
from framework.orchestrator.node import NodeContext

logger = logging.getLogger(__name__)

# Limits for LLM compaction
LLM_COMPACT_MAX_DEPTH: int = 10


def llm_compact_char_limit(max_context_tokens: int) -> int:
    """Input-size ceiling (chars) for one compaction-summary call.

    Derived from the model window instead of a constant: the historic
    240_000 literal was 180k * 4/3 — ~45% of the window at the chars/3
    token estimate — and silently overflowed smaller windows (and CJK
    text, where chars/token is closer to 1). Ratio preserved; the floor
    keeps tiny windows from splitting into confetti.
    """
    return max(20_000, (max_context_tokens * 4) // 3)


# Max output tokens for a single compaction summary call. A summary must be a
# small fraction of the window — using ``max_context_tokens // 2`` (e.g. 90k on a
# 180k window) lets the model emit a "summary" nearly as large as the input, which
# both barely reduces usage and is extremely slow (a far-over-window context splits
# into several chunks, each a slow ~90k-token generation → multi-minute hangs).
# A few thousand tokens is plenty for a detailed continue-the-work summary.
LLM_COMPACT_SUMMARY_MAX_TOKENS: int = 8_192

# Microcompaction: tools whose results can be safely cleared from context
# because the agent can re-derive them on demand. The bar for inclusion is
# "old result has no irreversible value": file content can be re-read, a
# search can be re-run, a screenshot can be re-captured, terminal output can
# be re-fetched, etc. Write / edit results are short confirmations whose
# value is in the side effect, not the message — also fair game.
COMPACTABLE_TOOLS: frozenset[str] = frozenset(
    {
        # Document reads — content lives on disk, re-readable.
        "pdf_read",
        # Terminal — re-runnable; advanced job/output tools produce verbose
        # logs whose recent state is what matters.
        "terminal_exec",
        "terminal_rg",
        "terminal_glob",
        "terminal_output_get",
        "terminal_job_logs",
        # Web / research — pages and queries can be re-fetched.
        "web_scrape",
        "search_papers",
        "download_paper",
        "search_wikipedia",
        # Browser reads now run via the hive-browser CLI under terminal_exec
        # (already covered above): page snapshot/html/text return a small
        # saved_to pointer (not a large compactable payload), and screenshots
        # are re-inlined images on the terminal result. NOTE: evicting stale
        # inlined CLI screenshots on compaction is a follow-up — they ride on a
        # terminal_exec result, so they aren't matched by a browser_* tool name.
    }
)

# Keep at most this many compactable tool results; clear older ones.
# Tuned 8 → 4 → 2 → 6:
# - First drop (8 → 4) was based on the observation that real sessions
#   carry many large compactable results (terminal_exec, terminal_rg,
#   web_scrape) before any compaction trigger fires.
# - Second drop (4 → 2) reduced per-turn density further, on the assumption
#   that older results survive via the spillover path the placeholder cites.
# - Raised 2 → 6: at 2, a single batch of ~5 read queries lost 3 the instant
#   it finished — mid-reasoning — so the agent re-issued them to "confirm the
#   numbers", re-firing microcompaction (a re-read loop). 6 lets a normal batch
#   survive intact. Recoverability is now an invariant enforced in microcompact
#   (only results with a citable spill path are ever cleared), so a higher keep
#   count is purely about batch ergonomics, not safety.
# Env-overridable for tuning without a code edit (0/negative → falls back to 6).
_MICROCOMPACT_KEEP_RECENT_RAW = int(os.environ.get("HIVE_MICROCOMPACT_KEEP_RECENT", "6") or 6)
MICROCOMPACT_KEEP_RECENT: int = _MICROCOMPACT_KEEP_RECENT_RAW if _MICROCOMPACT_KEEP_RECENT_RAW > 0 else 6

# Group-chat compaction guard. The LLM-summary path preserves every
# ``is_client_input`` message verbatim so a 1:1 agent never loses the
# operator's exact words. In a group room EVERY member's line is client
# input, so that rule pins the whole group backlog in-context forever and
# compaction can never bring usage under budget (observed: 97% of a 50K-token
# window was 188 preserved group messages). Cap the verbatim tail; older group
# messages survive in the summary. Override via env for tuning without a code
# edit. 0/negative disables the cap (legacy unbounded behaviour).
_MAX_VERBATIM_CLIENT_RAW = int(os.environ.get("HIVE_MAX_VERBATIM_CLIENT_MSGS", "40") or 40)
MAX_VERBATIM_CLIENT_MESSAGES: int | None = _MAX_VERBATIM_CLIENT_RAW if _MAX_VERBATIM_CLIENT_RAW > 0 else None

# Circuit-breaker: stop auto-compacting after this many consecutive failures
MAX_CONSECUTIVE_FAILURES: int = 3

# Track consecutive compaction failures per conversation (module-level)
_failure_counts: dict[int, int] = {}

# Track last compaction time per conversation for recompaction detection
_last_compact_times: dict[int, float] = {}


# ---------------------------------------------------------------------------
# Defensive guard against oversized user messages.
#
# The upload-path size gate (Layer E) prevents huge PDFs from landing as full
# text in a user message going forward. But older sessions persisted before
# that gate shipped — and any future bug that re-introduces a bloated message
# — could leave a 2 MB+ user message sitting in the conversation. LLM
# compaction would try to summarize it, blow the model's own context window
# building the compaction prompt, and the loop would get stuck in a
# recompaction chain.
#
# Threshold: 100 K chars (~25 K tokens at 4 chars/token). Normal user
# messages — even long pastes — sit well under this; the bloated calculus
# textbook case was 2.4 M chars per message, 24× over the threshold.
USER_MESSAGE_MAX_CHARS: int = 100_000
USER_MESSAGE_HEAD_CHARS: int = 4_000
USER_MESSAGE_TAIL_CHARS: int = 4_000


def truncate_oversized_user_messages(conversation: NodeConversation) -> int:
    """Clip user messages that exceed :data:`USER_MESSAGE_MAX_CHARS` so the
    compaction pipeline survives historical or future bloat.

    Keeps the head + tail of the message so the agent still sees what kind
    of message the user sent. The tail is preserved deliberately: the
    upload path appends an ``[Attachments saved to disk]`` block at the
    end with the on-disk path the agent can re-read selectively via
    ``pdf_read``. A ``<system-reminder>`` block explains the truncation
    so the LLM doesn't think the user's message just stops mid-sentence.

    Skips messages already marked ``is_system_reminder`` — those are
    framework injections, not real user input. ``is_skill_content`` is
    similarly off-limits.

    Returns the number of messages clipped.
    """
    messages = conversation.messages
    truncated = 0
    for i, msg in enumerate(messages):
        if msg.role != "user":
            continue
        if msg.is_system_reminder or msg.is_skill_content:
            continue
        content = msg.content or ""
        if len(content) <= USER_MESSAGE_MAX_CHARS:
            continue

        orig_len = len(content)
        head = content[:USER_MESSAGE_HEAD_CHARS]
        tail = content[-USER_MESSAGE_TAIL_CHARS:]
        cut = orig_len - USER_MESSAGE_HEAD_CHARS - USER_MESSAGE_TAIL_CHARS
        notice = (
            "\n\n<system-reminder>\n"
            f"[{cut:,} chars truncated to keep compaction safe; "
            f"original message was {orig_len:,} chars. If an attachment "
            "path appears in the tail below, read it selectively via "
            "pdf_read.]\n"
            "</system-reminder>\n\n"
        )
        new_content = head + notice + tail

        conversation._messages[i] = dataclasses.replace(msg, content=new_content)
        truncated += 1

    if truncated > 0:
        conversation._last_api_input_tokens = None
        logger.info(
            "[compaction] truncated %d oversized user message(s) — defensive guard",
            truncated,
        )

    return truncated


def microcompact(
    conversation: NodeConversation,
    *,
    keep_recent: int = MICROCOMPACT_KEEP_RECENT,
) -> int:
    """Clear old compactable tool results by count, keeping only the most recent.

    This is the cheapest possible compaction — no LLM call, no structural
    changes, just replaces old tool result content with a short placeholder.
    Inspired by Claude Code's cached-microcompact strategy.

    Returns the number of tool results cleared.
    """
    # Collect compactable tool results (newest first) as (index, recovery_path).
    compactable: list[tuple[int, str]] = []
    messages = conversation.messages
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.role != "tool" or msg.is_error or msg.is_skill_content:
            continue
        if msg.content.startswith(("Pruned tool result", "[Pruned tool result", "[Old tool result")):
            continue
        if len(msg.content) < 100:
            continue

        # Check if the tool that produced this result is compactable
        tool_name = _find_tool_name_for_result(messages, msg)
        if not (tool_name and tool_name in COMPACTABLE_TOOLS):
            continue

        # Recoverability invariant: only clear a result we can point back to.
        # Prefer the out-of-band spill path recorded when the result landed
        # (present for small inline results too); fall back to a path embedded
        # in the message text (large-preview results). A result with no
        # recovery path is left INTACT rather than replaced by an unrecoverable
        # "cleared from context" placeholder — that stranding was the cause of
        # the re-read loop (agent re-runs the query to recover vanished output,
        # which re-fires microcompaction).
        spillover = msg.spillover_path or _extract_spillover_filename_inline(msg.content)
        if not spillover:
            continue
        compactable.append((i, spillover))

    # Keep the most recent N, clear the rest
    to_clear = compactable[keep_recent:]
    if not to_clear:
        return 0

    cleared = 0
    for i, spillover in to_clear:
        msg = messages[i]
        orig_len = len(msg.content)
        # Recovery hint points at terminal_rg, not a whole-file cat: re-reading
        # the whole file would only get truncated again at max_tool_result_chars
        # and force a pagination dance, whereas ripgrep returns just the matching
        # lines and keeps per-turn density low.
        placeholder = f"Old tool result ({orig_len:,} chars) at {spillover}. Use terminal_rg with a pattern against this path to recover specifics."

        # Mutate in-place (microcompact is synchronous, no store writes)
        conversation._messages[i] = Message(
            seq=msg.seq,
            role=msg.role,
            content=placeholder,
            tool_use_id=msg.tool_use_id,
            tool_calls=msg.tool_calls,
            is_error=msg.is_error,
            phase_id=msg.phase_id,
            is_transition_marker=msg.is_transition_marker,
            spillover_path=msg.spillover_path,
        )
        cleared += 1

    if cleared > 0:
        # Invalidate cached token count
        conversation._last_api_input_tokens = None

    return cleared


def _find_tool_name_for_result(messages: list[Message], tool_msg: Message) -> str | None:
    """Find the tool name from the assistant message that triggered this tool result."""
    if not tool_msg.tool_use_id:
        return None
    for msg in messages:
        if msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.get("id") == tool_msg.tool_use_id:
                    return tc.get("function", {}).get("name")
    return None


def _extract_spillover_filename_inline(content: str) -> str | None:
    """Quick inline check for spillover filename in tool result content.

    Accepts the new "chars) at /path" form emitted by microcompact and
    truncate_tool_result, plus the legacy "saved at:" / "saved to '...'"
    forms still present in older conversation snapshots. The new form is
    parsed by ``\\bat\\s+(/[^\\s]+)``; the legacy ones keep their original
    patterns so a long-lived conversation that started before this
    change still resolves spillover paths correctly.

    Matches the new "chars) at /path" form, the previous "saved at: /path"
    prose, and the legacy bracketed "saved to '/path'" trailer.

    Trailing sentence punctuation (``.,;:``) on a captured path is
    stripped — filenames don't end in those chars in practice, but
    sentences do.
    """
    # Current truncate_tool_result header: "... Full result at: /path"
    match = re.search(r"full result at:\s*(\S+)", content, re.IGNORECASE)
    if match:
        return match.group(1).rstrip(".,;:")
    # New form: "Old tool result (44,754 chars) at /tmp/.../file.txt. ..."
    match = re.search(r"\)\s+at\s+(/\S+)", content)
    if match:
        return match.group(1).rstrip(".,;:")
    match = re.search(r"saved at:\s*(\S+)", content, re.IGNORECASE)
    if match:
        return match.group(1).rstrip(".,;:")
    match = re.search(r"saved to '([^']+)'", content, re.IGNORECASE)
    return match.group(1) if match else None


async def compact(
    ctx: NodeContext,
    conversation: NodeConversation,
    accumulator: OutputAccumulator | None,
    *,
    config: LoopConfig,
    event_bus: EventBus | None,
    char_limit: int | None = None,
    max_depth: int = LLM_COMPACT_MAX_DEPTH,
) -> None:
    """Run the full compaction pipeline if conversation needs compaction.

    Pipeline stages (in order, short-circuits when budget is restored):
    0. Microcompaction (count-based tool result clearing — cheapest)
    1. Prune old tool results (token-budget based)
    2. LLM summary compaction (recursive split if too large)
    3. Emergency deterministic summary (fallback)
    """
    conv_id = id(conversation)

    # Circuit breaker: stop LLM-based compaction after repeated failures,
    # but still fall through to the emergency deterministic summary so
    # the conversation doesn't silently grow past the context window.
    # Without this, a persistent LLM outage during compaction would
    # leave the agent stuck sending oversized prompts until the API 400s.
    _llm_compaction_skipped = _failure_counts.get(conv_id, 0) >= MAX_CONSECUTIVE_FAILURES
    if _llm_compaction_skipped:
        logger.warning(
            "Circuit breaker: LLM compaction disabled after %d failures — skipping straight to emergency summary",
            _failure_counts[conv_id],
        )

    # Recompaction detection
    now = time.monotonic()
    last_time = _last_compact_times.get(conv_id)
    if last_time is not None and (now - last_time) < 30:
        logger.warning(
            "Recompaction chain detected: only %.1fs since last compaction",
            now - last_time,
        )

    ratio_before = conversation.usage_ratio()
    phase_grad = getattr(ctx, "continuous_mode", False)
    pre_inventory: list[dict[str, Any]] | None = None

    if ratio_before >= 1.0:
        pre_inventory = build_message_inventory(conversation)

    # Tell the UI a compaction pass has begun. Without this the debug
    # panel (and any "agent is busy" indicator) sees nothing for the
    # entire compaction window — multi-minute on heavily over-budget
    # conversations — and the human assumes the agent has frozen.
    if event_bus is not None:
        from framework.host.event_bus import AgentEvent, EventType

        await event_bus.publish(
            AgentEvent(
                type=EventType.CONTEXT_COMPACTION_STARTED,
                stream_id=ctx.stream_id or ctx.agent_id,
                node_id=ctx.agent_id,
                execution_id=getattr(ctx, "execution_id", None) or None,
                data={
                    "usage_before": round(ratio_before * 100),
                    "message_count": len(conversation.messages),
                    "llm_compaction_skipped": _llm_compaction_skipped,
                },
            )
        )

    # --- Step 0a: Defensive truncation of oversized user messages ---
    # Runs before everything else so the LLM-compaction prompt is never
    # built around a 2 MB user message that would itself exceed the
    # model's context window. Cheap (O(n) scan + small splice), idempotent
    # (re-running on already-truncated messages is a no-op since the head
    # + reminder + tail fit under the threshold).
    oversized_clipped = truncate_oversized_user_messages(conversation)
    if oversized_clipped > 0:
        logger.warning(
            "[compaction] clipped %d oversized user message(s) before microcompact; usage %.0f%% -> %.0f%%",
            oversized_clipped,
            ratio_before * 100,
            conversation.usage_ratio() * 100,
        )

    # --- Step 0: Microcompaction (count-based, cheapest) ---
    mc_cleared = microcompact(conversation)
    if mc_cleared > 0:
        logger.info(
            "Microcompact cleared %d old tool results: %.0f%% -> %.0f%%",
            mc_cleared,
            ratio_before * 100,
            conversation.usage_ratio() * 100,
        )
    if not conversation.needs_compaction():
        _record_success(conv_id, now)
        await log_compaction(
            ctx,
            conversation,
            ratio_before,
            event_bus,
            pre_inventory=pre_inventory,
        )
        return

    # --- Step 1: Prune old tool results (free, fast) ---
    protect = max(2000, config.max_context_tokens // 12)
    pruned = await conversation.prune_old_tool_results(
        protect_tokens=protect,
        min_prune_tokens=max(1000, protect // 3),
    )
    if pruned > 0:
        logger.info(
            "Pruned %d old tool results: %.0f%% -> %.0f%%",
            pruned,
            ratio_before * 100,
            conversation.usage_ratio() * 100,
        )
    if not conversation.needs_compaction():
        _record_success(conv_id, now)
        await log_compaction(
            ctx,
            conversation,
            ratio_before,
            event_bus,
            pre_inventory=pre_inventory,
        )
        return

    # --- Step 2: LLM summary compaction ---
    if ctx.llm is not None and not _llm_compaction_skipped:
        logger.info(
            "LLM summary compaction triggered (%.0f%% usage)",
            conversation.usage_ratio() * 100,
        )
        try:
            summary = await llm_compact(
                ctx,
                list(conversation.messages),
                accumulator,
                char_limit=char_limit,
                max_depth=max_depth,
                max_context_tokens=config.max_context_tokens,
            )
            await conversation.compact(
                summary,
                keep_recent=2,
                phase_graduated=phase_grad,
                max_verbatim_client=MAX_VERBATIM_CLIENT_MESSAGES,
            )
        except Exception as e:
            logger.warning("LLM compaction failed: %s", e)
            _failure_counts[conv_id] = _failure_counts.get(conv_id, 0) + 1

    # The LLM summary is the ONLY (non-destructive) compaction. We never fall
    # back to a deterministic "emergency" summary — that crude-summarizes and
    # deletes the conversation, destroying the user's data. If the LLM summary
    # could not run (provider down / circuit breaker) or did not fully reduce
    # usage, leave the conversation intact and let the next LLM call's
    # context-too-large handling surface/retry. Better a loud over-budget state
    # than silent data loss.
    if not conversation.needs_compaction():
        _record_success(conv_id, now)
    else:
        logger.warning(
            "Compaction did not bring usage under budget (%.0f%%); leaving "
            "conversation intact (LLM summary unavailable or insufficient) — "
            "not crude-summarizing.",
            conversation.usage_ratio() * 100,
        )
    await log_compaction(
        ctx,
        conversation,
        ratio_before,
        event_bus,
        pre_inventory=pre_inventory,
    )


def _record_success(conv_id: int, timestamp: float) -> None:
    """Reset failure counter and record compaction time on success."""
    _failure_counts.pop(conv_id, None)
    _last_compact_times[conv_id] = timestamp


# --- LLM compaction with binary-search splitting ----------------------


def strip_images_from_messages(messages: list[Message]) -> list[Message]:
    """Strip image_content from messages before LLM summarisation.

    Images/documents are replaced with ``[image]`` markers so the summary
    notes they existed without wasting tokens sending binary data to the
    compaction LLM.  Returns a new list (original messages are not mutated).
    """
    stripped: list[Message] = []
    for msg in messages:
        if msg.image_content:
            n_images = len(msg.image_content)
            marker = " ".join("[image]" for _ in range(n_images))
            content = f"{msg.content}\n{marker}" if msg.content else marker
            stripped.append(
                Message(
                    seq=msg.seq,
                    role=msg.role,
                    content=content,
                    tool_use_id=msg.tool_use_id,
                    tool_calls=msg.tool_calls,
                    is_error=msg.is_error,
                    phase_id=msg.phase_id,
                    is_transition_marker=msg.is_transition_marker,
                    image_content=None,  # stripped
                )
            )
        else:
            stripped.append(msg)
    return stripped


async def llm_compact(
    ctx: NodeContext,
    messages: list,
    accumulator: OutputAccumulator | None = None,
    _depth: int = 0,
    *,
    char_limit: int | None = None,
    max_depth: int = LLM_COMPACT_MAX_DEPTH,
    max_context_tokens: int = 128_000,
    preserve_user_messages: bool = False,
) -> str:
    """Summarise *messages* with LLM, splitting recursively if too large.

    If the formatted text exceeds the window-derived char limit or the LLM
    rejects the call with a context-length error, the messages are split
    in half and each half is summarised independently.  Tool history is
    appended once at the top-level call (``_depth == 0``).

    When ``preserve_user_messages`` is True, the prompt and system message
    are amplified to instruct the LLM to keep every user message verbatim
    and in full — used by the manual /compact-and-fork endpoint where the
    user wants their voice carried into the new session intact.
    """
    from framework.agent_loop.conversation import extract_tool_call_history
    from framework.agent_loop.internals.tool_result_handler import is_context_too_large_error

    if _depth > max_depth:
        raise RuntimeError(f"LLM compaction recursion limit ({max_depth})")
    if char_limit is None:
        char_limit = llm_compact_char_limit(max_context_tokens)

    # Strip images before summarisation to avoid wasting tokens
    if _depth == 0:
        messages = strip_images_from_messages(messages)

    formatted = format_messages_for_summary(messages)

    # Proactive split: avoid wasting an API call on oversized input
    if len(formatted) > char_limit and len(messages) > 1:
        summary = await _llm_compact_split(
            ctx,
            messages,
            accumulator,
            _depth,
            char_limit=char_limit,
            max_depth=max_depth,
            max_context_tokens=max_context_tokens,
            preserve_user_messages=preserve_user_messages,
        )
    else:
        prompt = build_llm_compaction_prompt(
            ctx,
            accumulator,
            formatted,
            max_context_tokens=max_context_tokens,
            preserve_user_messages=preserve_user_messages,
        )
        if preserve_user_messages:
            system_msg = (
                "You are a conversation compactor for an AI agent. "
                "Write a detailed summary that allows the agent to "
                "continue its work. CRITICAL: reproduce every user "
                "message verbatim and in full inside the 'User Messages' "
                "section — do not paraphrase, truncate, or merge them. "
                "Assistant turns and tool results may be summarised, but "
                "user input is sacred."
            )
        else:
            system_msg = (
                "You are a conversation compactor for an AI agent. "
                "Write a detailed summary that allows the agent to "
                "continue its work. Preserve user-stated rules, "
                "constraints, and account/identity preferences verbatim."
            )
        if preserve_user_messages:
            # /compact-and-fork reproduces every user message verbatim, so it
            # needs room — keep the large budget for that path only.
            summary_budget = max(1024, max_context_tokens // 2)
        else:
            # Normal compaction: a summary should be small. Cap to an absolute
            # ceiling AND scale with the window (~1/8) so that even when a far-
            # over-window context splits into several chunks, the COMBINED
            # summary stays well under the window — keeping each call fast and
            # guaranteeing real reduction on small and large windows alike.
            summary_budget = min(LLM_COMPACT_SUMMARY_MAX_TOKENS, max(1024, max_context_tokens // 8))
        try:
            response = await ctx.llm.acomplete(
                messages=[{"role": "user", "content": prompt}],
                system=system_msg,
                max_tokens=summary_budget,
            )
            summary = response.content
        except Exception as e:
            if is_context_too_large_error(e) and len(messages) > 1:
                logger.info(
                    "LLM context too large (depth=%d, msgs=%d) — splitting",
                    _depth,
                    len(messages),
                )
                summary = await _llm_compact_split(
                    ctx,
                    messages,
                    accumulator,
                    _depth,
                    char_limit=char_limit,
                    max_depth=max_depth,
                    max_context_tokens=max_context_tokens,
                    preserve_user_messages=preserve_user_messages,
                )
            else:
                raise

    # Append tool history at top level only
    if _depth == 0:
        tool_history = extract_tool_call_history(messages)
        if tool_history and "TOOLS ALREADY CALLED" not in summary:
            summary += "\n\n" + tool_history

    return summary


async def _llm_compact_split(
    ctx: NodeContext,
    messages: list,
    accumulator: OutputAccumulator | None,
    _depth: int,
    *,
    char_limit: int | None = None,
    max_depth: int = LLM_COMPACT_MAX_DEPTH,
    max_context_tokens: int = 128_000,
    preserve_user_messages: bool = False,
) -> str:
    """Split messages in half and summarise each half independently."""
    if char_limit is None:
        char_limit = llm_compact_char_limit(max_context_tokens)
    mid = max(1, len(messages) // 2)
    s1 = await llm_compact(
        ctx,
        messages[:mid],
        None,
        _depth + 1,
        char_limit=char_limit,
        max_depth=max_depth,
        max_context_tokens=max_context_tokens,
        preserve_user_messages=preserve_user_messages,
    )
    s2 = await llm_compact(
        ctx,
        messages[mid:],
        accumulator,
        _depth + 1,
        char_limit=char_limit,
        max_depth=max_depth,
        max_context_tokens=max_context_tokens,
        preserve_user_messages=preserve_user_messages,
    )
    return s1 + "\n\n" + s2


# --- Compaction helpers ------------------------------------------------


def format_messages_for_summary(messages: list) -> str:
    """Format messages as text for LLM summarisation."""
    lines: list[str] = []
    for m in messages:
        if m.role == "tool":
            content = m.content[:500]
            if len(m.content) > 500:
                content += "..."
            lines.append(f"[tool result]: {content}")
        elif m.role == "assistant" and m.tool_calls:
            names = [tc.get("function", {}).get("name", "?") for tc in m.tool_calls]
            text = m.content[:200] if m.content else ""
            lines.append(f"[assistant (calls: {', '.join(names)})]: {text}")
        else:
            lines.append(f"[{m.role}]: {m.content}")
    return "\n\n".join(lines)


def build_llm_compaction_prompt(
    ctx: NodeContext,
    accumulator: OutputAccumulator | None,
    formatted_messages: str,
    *,
    max_context_tokens: int = 128_000,
    preserve_user_messages: bool = False,
) -> str:
    """Build prompt for LLM compaction targeting 50% of token budget.

    Uses a structured section format inspired by Claude Code's compact
    service.  Each section focuses on a different aspect of the conversation
    so the summariser produces consistently useful, well-organised output.
    """
    spec = ctx.agent_spec
    ctx_lines = [f"NODE: {spec.name} (id={spec.id})"]
    if spec.description:
        ctx_lines.append(f"PURPOSE: {spec.description}")
    if spec.success_criteria:
        ctx_lines.append(f"SUCCESS CRITERIA: {spec.success_criteria}")

    if accumulator:
        acc = accumulator.to_dict()
        done = {k: v for k, v in acc.items() if v is not None}
        todo = [k for k, v in acc.items() if v is None]
        if done:
            ctx_lines.append("OUTPUTS ALREADY SET:\n" + "\n".join(f"  {k}: {str(v)[:150]}" for k, v in done.items()))
        if todo:
            ctx_lines.append(f"OUTPUTS STILL NEEDED: {', '.join(todo)}")
    elif spec.output_keys:
        ctx_lines.append(f"OUTPUTS STILL NEEDED: {', '.join(spec.output_keys)}")

    target_tokens = max_context_tokens // 2
    target_chars = target_tokens * 4
    node_ctx = "\n".join(ctx_lines)

    user_messages_section = (
        "6. **User Messages** — Reproduce EVERY user message verbatim and "
        "in full, in chronological order, each on its own line prefixed "
        'with the message index (e.g. "[U1] ..."). Do NOT paraphrase, '
        "summarise, merge, or omit any user message. Preserve markdown, "
        "code fences, whitespace, and punctuation exactly as the user "
        "wrote them.\n"
        if preserve_user_messages
        else "6. **User Messages** — Preserve ALL user-stated rules, constraints, identity preferences, and account details verbatim.\n"
    )

    return (
        "You are compacting an AI agent's conversation history. "
        "The agent is still working and needs to continue.\n\n"
        f"AGENT CONTEXT:\n{node_ctx}\n\n"
        f"CONVERSATION MESSAGES:\n{formatted_messages}\n\n"
        "INSTRUCTIONS:\n"
        f"Write a summary of approximately {target_chars} characters "
        f"(~{target_tokens} tokens).\n\n"
        "Organise the summary into these sections (omit empty ones):\n\n"
        "1. **Primary Request and Intent** — What the user originally asked "
        "for and the high-level goal the agent is working toward.\n"
        "2. **Key Technical Concepts** — Important domain-specific terms, "
        "patterns, or architectural decisions established in the conversation.\n"
        "3. **Files and Code Sections** — Specific files read/written/edited "
        "with brief descriptions of changes. Include short code snippets only "
        "when they capture critical logic.\n"
        "4. **Errors and Fixes** — Problems encountered and how they were "
        "resolved. Include root causes so the agent doesn't repeat them.\n"
        "5. **Problem Solving Efforts** — Approaches tried, dead ends hit, "
        "and reasoning behind the current strategy.\n"
        f"{user_messages_section}"
        "7. **Pending Tasks** — Work remaining, outputs still needed, and "
        "any blockers.\n"
        "8. **Current Work** — The most recent action taken and the immediate "
        "next step the agent should perform. This section is the most important "
        "for seamless resumption.\n\n"
        "Additional rules:\n"
        "- Be detailed enough that the agent can resume without re-doing work.\n"
        "- Preserve key decisions made and results obtained.\n"
        "- When in doubt, keep information rather than discard it.\n"
    )


def build_message_inventory(conversation: NodeConversation) -> list[dict[str, Any]]:
    """Build a per-message size inventory for debug logging."""
    inventory: list[dict[str, Any]] = []
    for message in conversation.messages:
        content_chars = len(message.content)
        tool_call_args_chars = 0
        tool_name = None
        if message.tool_calls:
            for tool_call in message.tool_calls:
                args = tool_call.get("function", {}).get("arguments", "")
                tool_call_args_chars += len(args) if isinstance(args, str) else len(json.dumps(args))
            names = [tool_call.get("function", {}).get("name", "?") for tool_call in message.tool_calls]
            tool_name = ", ".join(names)
        elif message.role == "tool" and message.tool_use_id:
            for previous in conversation.messages:
                if previous.tool_calls:
                    for tool_call in previous.tool_calls:
                        if tool_call.get("id") == message.tool_use_id:
                            tool_name = tool_call.get("function", {}).get("name", "?")
                            break
                if tool_name:
                    break
        entry: dict[str, Any] = {
            "seq": message.seq,
            "role": message.role,
            "content_chars": content_chars,
        }
        if tool_call_args_chars:
            entry["tool_call_args_chars"] = tool_call_args_chars
        if tool_name:
            entry["tool"] = tool_name
        if message.is_error:
            entry["is_error"] = True
        if message.phase_id:
            entry["phase"] = message.phase_id
        if content_chars > 2000:
            entry["preview"] = message.content[:200] + "…"
        inventory.append(entry)
    return inventory


def write_compaction_debug_log(
    ctx: NodeContext,
    before_pct: int,
    after_pct: int,
    level: str,
    inventory: list[dict[str, Any]] | None,
) -> None:
    """Write detailed compaction analysis to $HIVE_HOME/compaction_log/."""
    from framework.config import HIVE_HOME

    log_dir = HIVE_HOME / "compaction_log"
    log_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%f")
    node_label = ctx.agent_id.replace("/", "_")
    log_path = log_dir / f"{ts}_{node_label}.md"

    lines: list[str] = [
        f"# Compaction Debug — {ctx.agent_id}",
        f"**Time:** {datetime.now(UTC).isoformat()}",
        f"**Node:** {ctx.agent_spec.name} (`{ctx.agent_id}`)",
    ]
    if ctx.stream_id:
        lines.append(f"**Stream:** {ctx.stream_id}")
    lines.append(f"**Level:** {level}")
    lines.append(f"**Usage:** {before_pct}% → {after_pct}%")
    lines.append("")

    if inventory:
        total_chars = sum(entry.get("content_chars", 0) + entry.get("tool_call_args_chars", 0) for entry in inventory)
        lines.append(f"## Pre-Compaction Message Inventory ({len(inventory)} messages, {total_chars:,} total chars)")
        lines.append("")
        ranked = sorted(
            inventory,
            key=lambda entry: entry.get("content_chars", 0) + entry.get("tool_call_args_chars", 0),
            reverse=True,
        )
        lines.append("| # | seq | role | tool | chars | % of total | flags |")
        lines.append("|---|-----|------|------|------:|------------|-------|")
        for i, entry in enumerate(ranked, 1):
            chars = entry.get("content_chars", 0) + entry.get("tool_call_args_chars", 0)
            pct = (chars / total_chars * 100) if total_chars else 0
            tool = entry.get("tool", "")
            flags: list[str] = []
            if entry.get("is_error"):
                flags.append("error")
            if entry.get("phase"):
                flags.append(f"phase={entry['phase']}")
            lines.append(f"| {i} | {entry['seq']} | {entry['role']} | {tool} | {chars:,} | {pct:.1f}% | {', '.join(flags)} |")

        large = [entry for entry in ranked if entry.get("preview")]
        if large:
            lines.append("")
            lines.append("### Large message previews")
            for entry in large:
                lines.append(f"\n**seq={entry['seq']}** ({entry['role']}, {entry.get('tool', '')}):")
                lines.append(f"```\n{entry['preview']}\n```")
    lines.append("")

    try:
        log_path.write_text("\n".join(lines), encoding="utf-8")
        logger.debug("Compaction debug log written to %s", log_path)
    except OSError:
        logger.debug("Failed to write compaction debug log to %s", log_path)


async def log_compaction(
    ctx: NodeContext,
    conversation: NodeConversation,
    ratio_before: float,
    event_bus: EventBus | None,
    *,
    pre_inventory: list[dict[str, Any]] | None = None,
) -> None:
    """Log compaction result to runtime logger and event bus."""
    ratio_after = conversation.usage_ratio()
    before_pct = round(ratio_before * 100)
    after_pct = round(ratio_after * 100)
    # Absolute token counts in K (1K = 1000). ratio_before is a fraction of
    # max_context_tokens captured pre-compaction; multiply back to recover
    # the absolute token count without re-estimating the pre-state.
    max_ctx = conversation._max_context_tokens
    before_k = round((ratio_before * max_ctx) / 1000) if max_ctx > 0 else 0
    after_k = round(conversation.estimate_tokens() / 1000)

    # Determine label from what happened
    if after_pct >= before_pct - 1:
        level = "prune_only"
    elif ratio_after <= 0.6:
        level = "llm"
    else:
        level = "structural"

    logger.info(
        "Compaction complete (%s): %d%% (%dK) -> %d%% (%dK)",
        level,
        before_pct,
        before_k,
        after_pct,
        after_k,
    )

    if ctx.runtime_logger:
        ctx.runtime_logger.log_step(
            node_id=ctx.agent_id,
            node_type="event_loop",
            step_index=-1,
            llm_text=f"Context compacted ({level}): {before_pct}% ({before_k}K) \u2192 {after_pct}% ({after_k}K)",
            verdict="COMPACTION",
            verdict_feedback=f"level={level} before={before_pct}%/{before_k}K after={after_pct}%/{after_k}K",
        )

    if event_bus:
        from framework.host.event_bus import AgentEvent, EventType

        event_data: dict[str, Any] = {
            "level": level,
            "usage_before": before_pct,
            "usage_after": after_pct,
            "tokens_before_k": before_k,
            "tokens_after_k": after_k,
        }
        if pre_inventory is not None:
            event_data["message_inventory"] = pre_inventory
        await event_bus.publish(
            AgentEvent(
                type=EventType.CONTEXT_COMPACTED,
                stream_id=ctx.stream_id or ctx.agent_id,
                node_id=ctx.agent_id,
                data=event_data,
            )
        )

    await publish_context_usage(event_bus, ctx, conversation, "post_compaction")

    if os.environ.get("HIVE_COMPACTION_DEBUG"):
        write_compaction_debug_log(ctx, before_pct, after_pct, level, pre_inventory)


# NOTE: the deterministic "emergency" compaction summary (build_emergency_summary)
# was removed — it crude-summarized and deleted the conversation, destroying user
# data. Compaction is now always the non-destructive LLM summary; if that cannot
# run, the conversation is left intact (see compact()).
