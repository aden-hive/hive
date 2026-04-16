"""Conversation compaction pipeline.

Implements the multi-level compaction strategy:
0. Microcompaction (count-based tool result clearing — cheapest)
1. Prune old tool results (token-budget based)
2. Structure-preserving compaction (spillover)
3. LLM summary compaction (with recursive splitting)
4. Emergency deterministic summary (no LLM)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from framework.agent_loop.conversation import Message, NodeConversation
from framework.agent_loop.internals.event_publishing import publish_context_usage
from framework.agent_loop.internals.types import LoopConfig, OutputAccumulator
from framework.host.event_bus import EventBus
from framework.orchestrator.node import NodeContext

logger = logging.getLogger(__name__)

# Limits for LLM compaction
LLM_COMPACT_CHAR_LIMIT: int = 240_000
LLM_COMPACT_MAX_DEPTH: int = 10

# Microcompaction: tools whose results can be safely cleared
COMPACTABLE_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "run_command",
        "web_search",
        "web_fetch",
        "grep_search",
        "glob_search",
        "write_file",
        "edit_file",
        "browser_screenshot",
        "list_directory",
    }
)

# Keep at most this many compactable tool results; clear older ones
MICROCOMPACT_KEEP_RECENT: int = 8

# Circuit-breaker: stop auto-compacting after this many consecutive failures
MAX_CONSECUTIVE_FAILURES: int = 3

# Track consecutive compaction failures per conversation (module-level)
_failure_counts: dict[int, int] = {}

# Track last compaction time per conversation for recompaction detection
_last_compact_times: dict[int, float] = {}


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
    # Collect indices of compactable tool results (newest first)
    compactable_indices: list[int] = []
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
        if tool_name and tool_name in COMPACTABLE_TOOLS:
            compactable_indices.append(i)

    # Keep the most recent N, clear the rest
    to_clear = compactable_indices[keep_recent:]
    if not to_clear:
        return 0

    cleared = 0
    for i in to_clear:
        msg = messages[i]
        spillover = _extract_spillover_filename_inline(msg.content)
        orig_len = len(msg.content)
        if spillover:
            placeholder = (
                f"Old tool result ({orig_len:,} chars) cleared from context. "
                f"Full data saved at: {spillover}\n"
                f"Read the complete data with read_file(path='{spillover}')."
            )
        else:
            placeholder = f"Old tool result ({orig_len:,} chars) cleared from context."

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

    Matches both the new prose format ("saved at: /path") and the
    legacy bracketed trailer ("saved to '/path'").
    """
    match = re.search(r"saved at:\s*(\S+)", content, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"saved to '([^']+)'", content, re.IGNORECASE)
    return match.group(1) if match else None


async def compact(
    ctx: NodeContext,
    conversation: NodeConversation,
    accumulator: OutputAccumulator | None,
    *,
    config: LoopConfig,
    event_bus: EventBus | None,
    char_limit: int = LLM_COMPACT_CHAR_LIMIT,
    max_depth: int = LLM_COMPACT_MAX_DEPTH,
) -> None:
    """Run the full compaction pipeline if conversation needs compaction.

    Pipeline stages (in order, short-circuits when budget is restored):
    0. Microcompaction (count-based tool result clearing — cheapest)
    1. Prune old tool results (token-budget based)
    2. Structure-preserving compaction (free, no LLM)
    3. LLM summary compaction (recursive split if too large)
    4. Emergency deterministic summary (fallback)
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

    # --- Step 2: Standard structure-preserving compaction (free, no LLM) ---
    spill_dir = config.spillover_dir
    if spill_dir:
        await conversation.compact_preserving_structure(
            spillover_dir=spill_dir,
            keep_recent=4,
            phase_graduated=phase_grad,
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

    # --- Step 3: LLM summary compaction ---
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
            )
        except Exception as e:
            logger.warning("LLM compaction failed: %s", e)
            _failure_counts[conv_id] = _failure_counts.get(conv_id, 0) + 1

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

    # --- Step 4: Emergency deterministic summary (LLM failed/unavailable) ---
    logger.warning(
        "Emergency compaction (%.0f%% usage)",
        conversation.usage_ratio() * 100,
    )
    summary = build_emergency_summary(ctx, accumulator, conversation, config)
    await conversation.compact(
        summary,
        keep_recent=1,
        phase_graduated=phase_grad,
    )
    _record_success(conv_id, now)
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
    char_limit: int = LLM_COMPACT_CHAR_LIMIT,
    max_depth: int = LLM_COMPACT_MAX_DEPTH,
    max_context_tokens: int = 128_000,
) -> str:
    """Summarise *messages* with LLM, splitting recursively if too large.

    If the formatted text exceeds ``LLM_COMPACT_CHAR_LIMIT`` or the LLM
    rejects the call with a context-length error, the messages are split
    in half and each half is summarised independently.  Tool history is
    appended once at the top-level call (``_depth == 0``).
    """
    from framework.agent_loop.conversation import extract_tool_call_history
    from framework.agent_loop.internals.tool_result_handler import is_context_too_large_error

    if _depth > max_depth:
        raise RuntimeError(f"LLM compaction recursion limit ({max_depth})")

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
        )
    else:
        prompt = build_llm_compaction_prompt(
            ctx,
            accumulator,
            formatted,
            max_context_tokens=max_context_tokens,
        )
        summary_budget = max(1024, max_context_tokens // 2)
        try:
            response = await ctx.llm.acomplete(
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "You are a conversation compactor for an AI agent. "
                    "Write a detailed summary that allows the agent to "
                    "continue its work. Preserve user-stated rules, "
                    "constraints, and account/identity preferences verbatim."
                ),
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
    char_limit: int = LLM_COMPACT_CHAR_LIMIT,
    max_depth: int = LLM_COMPACT_MAX_DEPTH,
    max_context_tokens: int = 128_000,
) -> str:
    """Split messages in half and summarise each half independently."""
    mid = max(1, len(messages) // 2)
    s1 = await llm_compact(
        ctx,
        messages[:mid],
        None,
        _depth + 1,
        char_limit=char_limit,
        max_depth=max_depth,
        max_context_tokens=max_context_tokens,
    )
    s2 = await llm_compact(
        ctx,
        messages[mid:],
        accumulator,
        _depth + 1,
        char_limit=char_limit,
        max_depth=max_depth,
        max_context_tokens=max_context_tokens,
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
        "6. **User Messages** — Preserve ALL user-stated rules, constraints, "
        "identity preferences, and account details verbatim.\n"
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
    """Write detailed compaction analysis to ~/.hive/compaction_log/."""
    log_dir = Path.home() / ".hive" / "compaction_log"
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
            lines.append(
                f"| {i} | {entry['seq']} | {entry['role']} | {tool} | {chars:,} | {pct:.1f}% | {', '.join(flags)} |"
            )

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

    # Determine label from what happened
    if after_pct >= before_pct - 1:
        level = "prune_only"
    elif ratio_after <= 0.6:
        level = "llm"
    else:
        level = "structural"

    logger.info(
        "Compaction complete (%s): %d%% -> %d%%",
        level,
        before_pct,
        after_pct,
    )

    if ctx.runtime_logger:
        ctx.runtime_logger.log_step(
            node_id=ctx.agent_id,
            node_type="event_loop",
            step_index=-1,
            llm_text=f"Context compacted ({level}): {before_pct}% \u2192 {after_pct}%",
            verdict="COMPACTION",
            verdict_feedback=f"level={level} before={before_pct}% after={after_pct}%",
        )

    if event_bus:
        from framework.host.event_bus import AgentEvent, EventType

        event_data: dict[str, Any] = {
            "level": level,
            "usage_before": before_pct,
            "usage_after": after_pct,
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


def build_emergency_summary(
    ctx: NodeContext,
    accumulator: OutputAccumulator | None = None,
    conversation: NodeConversation | None = None,
    config: LoopConfig | None = None,
) -> str:
    """Build a structured emergency compaction summary.

    Unlike normal/aggressive compaction which uses an LLM summary,
    emergency compaction cannot afford an LLM call (context is already
    way over budget).  Instead, build a deterministic summary from the
    node's known state so the LLM can continue working after
    compaction without losing track of its task and inputs.
    """
    parts = ["EMERGENCY COMPACTION — previous conversation was too large and has been replaced with this summary.\n"]

    # 1. Node identity
    spec = ctx.agent_spec
    parts.append(f"NODE: {spec.name} (id={spec.id})")
    if spec.description:
        parts.append(f"PURPOSE: {spec.description}")

    # 2. Inputs the node received
    input_lines = []
    for key in spec.input_keys:
        value = ctx.input_data.get(key)
        if value is not None:
            # Truncate long values but keep them recognisable
            v_str = str(value)
            if len(v_str) > 200:
                v_str = v_str[:200] + "…"
            input_lines.append(f"  {key}: {v_str}")
    if input_lines:
        parts.append("INPUTS:\n" + "\n".join(input_lines))

    # 3. Output accumulator state (what's been set so far)
    if accumulator:
        acc_state = accumulator.to_dict()
        set_keys = {k: v for k, v in acc_state.items() if v is not None}
        missing = [k for k, v in acc_state.items() if v is None]
        if set_keys:
            lines = [f"  {k}: {str(v)[:150]}" for k, v in set_keys.items()]
            parts.append("OUTPUTS ALREADY SET:\n" + "\n".join(lines))
        if missing:
            parts.append(f"OUTPUTS STILL NEEDED: {', '.join(missing)}")
    elif spec.output_keys:
        parts.append(f"OUTPUTS STILL NEEDED: {', '.join(spec.output_keys)}")

    # 4. Available tools reminder
    if spec.tools:
        parts.append(f"AVAILABLE TOOLS: {', '.join(spec.tools)}")

    # 5. Spillover files — list actual files so the LLM can load
    # them immediately instead of having to call list_data_files first.
    spillover_dir = config.spillover_dir if config else None
    if spillover_dir:
        try:
            from pathlib import Path

            data_dir = Path(spillover_dir)
            if data_dir.is_dir():
                all_files = sorted(f.name for f in data_dir.iterdir() if f.is_file())
                # Separate conversation history files from regular data files
                conv_files = [f for f in all_files if re.match(r"conversation_\d+\.md$", f)]
                data_files = [f for f in all_files if f not in conv_files]

                if conv_files:
                    conv_list = "\n".join(f"  - {f}  (full path: {data_dir / f})" for f in conv_files)
                    parts.append(
                        "CONVERSATION HISTORY (freeform messages saved during compaction — "
                        "use read_file('<filename>') to review earlier dialogue):\n" + conv_list
                    )
                if data_files:
                    file_list = "\n".join(f"  - {f}  (full path: {data_dir / f})" for f in data_files[:30])
                    parts.append("DATA FILES (use read_file('<filename>') to read):\n" + file_list)
                if not all_files:
                    parts.append(
                        "NOTE: Large tool results may have been saved to files. "
                        "Use list_directory to check the data directory."
                    )
        except Exception:
            parts.append("NOTE: Large tool results were saved to files. Use read_file(path='<path>') to read them.")

    # 6. Tool call history (prevent re-calling tools)
    if conversation is not None:
        tool_history = _extract_tool_call_history(conversation)
        if tool_history:
            parts.append(tool_history)

    parts.append("\nContinue working towards setting the remaining outputs. Use your tools and the inputs above.")
    return "\n\n".join(parts)


def _extract_tool_call_history(conversation: NodeConversation) -> str:
    """Extract tool call history from conversation messages.

    This is the instance-level variant that operates on a NodeConversation
    directly (vs. the module-level extract_tool_call_history in conversation.py
    which works on raw message lists).
    """
    from framework.agent_loop.conversation import extract_tool_call_history

    return extract_tool_call_history(list(conversation.messages))
