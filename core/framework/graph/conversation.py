"""NodeConversation: Message history management for graph nodes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable


@dataclass
class Message:
    """A single message in a conversation.

    Attributes:
        seq: Monotonic sequence number.
        role: One of "user", "assistant", or "tool".
        content: Message text.
        tool_use_id: Internal tool-use identifier (output as ``tool_call_id`` in LLM dicts).
        tool_calls: OpenAI-format tool call list for assistant messages.
        is_error: When True and role is "tool", ``to_llm_dict`` prepends "ERROR: " to content.
    """

    seq: int
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_use_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    is_error: bool = False
    # Phase-aware compaction metadata (continuous mode)
    phase_id: str | None = None
    is_transition_marker: bool = False
    # True when this message is real human input (from /chat), not a system prompt
    is_client_input: bool = False

    def to_llm_dict(self) -> dict[str, Any]:
        """Convert to OpenAI-format message dict."""
        if self.role == "user":
            return {"role": "user", "content": self.content}

        if self.role == "assistant":
            d: dict[str, Any] = {"role": "assistant", "content": self.content}
            if self.tool_calls:
                d["tool_calls"] = self.tool_calls
            return d

        # role == "tool"
        content = f"ERROR: {self.content}" if self.is_error else self.content
        return {
            "role": "tool",
            "tool_call_id": self.tool_use_id,
            "content": content,
        }

    def to_storage_dict(self) -> dict[str, Any]:
        """Serialize all fields for persistence.  Omits None/default-False fields."""
        d: dict[str, Any] = {
            "seq": self.seq,
            "role": self.role,
            "content": self.content,
        }
        if self.tool_use_id is not None:
            d["tool_use_id"] = self.tool_use_id
        if self.tool_calls is not None:
            d["tool_calls"] = self.tool_calls
        if self.is_error:
            d["is_error"] = self.is_error
        if self.phase_id is not None:
            d["phase_id"] = self.phase_id
        if self.is_transition_marker:
            d["is_transition_marker"] = self.is_transition_marker
        if self.is_client_input:
            d["is_client_input"] = self.is_client_input
        return d

    @classmethod
    def from_storage_dict(cls, data: dict[str, Any]) -> Message:
        """Deserialize from a storage dict."""
        return cls(
            seq=data["seq"],
            role=data["role"],
            content=data["content"],
            tool_use_id=data.get("tool_use_id"),
            tool_calls=data.get("tool_calls"),
            is_error=data.get("is_error", False),
            phase_id=data.get("phase_id"),
            is_transition_marker=data.get("is_transition_marker", False),
            is_client_input=data.get("is_client_input", False),
        )


def _extract_spillover_filename(content: str) -> str | None:
    """Extract spillover filename from a tool result annotation.

    Matches patterns produced by EventLoopNode._truncate_tool_result():
        - Large result:  "saved to 'web_search_1.txt'"
        - Small result:  "[Saved to 'web_search_1.txt']"
    """
    match = re.search(r"[Ss]aved to '([^']+)'", content)
    return match.group(1) if match else None


_TC_ARG_LIMIT = 200  # max chars per tool_call argument after compaction


def _compact_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Truncate tool_call arguments to save context tokens during compaction.

    Preserves ``id``, ``type``, and ``function.name`` exactly.  Truncates
    ``function.arguments`` (a JSON string) to at most ``_TC_ARG_LIMIT`` chars
    so that large payloads (e.g. set_output with full findings) don't survive
    compaction and defeat the purpose of context reduction.
    """
    compact = []
    for tc in tool_calls:
        func = tc.get("function", {})
        args = func.get("arguments", "")
        if len(args) > _TC_ARG_LIMIT:
            args = args[:_TC_ARG_LIMIT] + "…[truncated]"
        compact.append(
            {
                "id": tc.get("id", ""),
                "type": tc.get("type", "function"),
                "function": {
                    "name": func.get("name", ""),
                    "arguments": args,
                },
            }
        )
    return compact


# ---------------------------------------------------------------------------
# ConversationStore protocol (Phase 2)
# ---------------------------------------------------------------------------


@runtime_checkable
class ConversationStore(Protocol):
    """Protocol for conversation persistence backends."""

    async def write_part(self, seq: int, data: dict[str, Any]) -> None: ...

    async def read_parts(self) -> list[dict[str, Any]]: ...

    async def write_meta(self, data: dict[str, Any]) -> None: ...

    async def read_meta(self) -> dict[str, Any] | None: ...

    async def write_cursor(self, data: dict[str, Any]) -> None: ...

    async def read_cursor(self) -> dict[str, Any] | None: ...

    async def delete_parts_before(self, seq: int) -> None: ...

    async def close(self) -> None: ...

    async def destroy(self) -> None: ...


# ---------------------------------------------------------------------------
# NodeConversation
# ---------------------------------------------------------------------------


def _try_extract_key(content: str, key: str) -> str | None:
    """Try 4 strategies to extract a *key*'s value from message content.

    Strategies (in order):
    1. Whole message is JSON — ``json.loads``, check for key.
    2. Embedded JSON via ``find_json_object`` helper.
    3. Colon format: ``key: value``.
    4. Equals format: ``key = value``.
    """
    from framework.graph.node import find_json_object

    # 1. Whole message is JSON
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict) and key in parsed:
            val = parsed[key]
            return json.dumps(val) if not isinstance(val, str) else val
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Embedded JSON via find_json_object
    json_str = find_json_object(content)
    if json_str:
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict) and key in parsed:
                val = parsed[key]
                return json.dumps(val) if not isinstance(val, str) else val
        except (json.JSONDecodeError, TypeError):
            pass

    # 3. Colon format: key: value
    match = re.search(rf"\b{re.escape(key)}\s*:\s*(.+)", content)
    if match:
        return match.group(1).strip()

    # 4. Equals format: key = value
    match = re.search(rf"\b{re.escape(key)}\s*=\s*(.+)", content)
    if match:
        return match.group(1).strip()

    return None


class NodeConversation:
    """Message history for a graph node with optional write-through persistence.

    When *store* is ``None`` the conversation works purely in-memory.
    When a :class:`ConversationStore` is supplied every mutation is
    persisted via write-through (meta is lazily written on the first
    ``_persist`` call).
    """

    def __init__(
        self,
        system_prompt: str = "",
        max_history_tokens: int = 32000,
        compaction_threshold: float = 0.8,
        output_keys: list[str] | None = None,
        store: ConversationStore | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._max_history_tokens = max_history_tokens
        self._compaction_threshold = compaction_threshold
        self._output_keys = output_keys
        self._store = store
        self._messages: list[Message] = []
        self._next_seq: int = 0
        self._meta_persisted: bool = False
        self._last_api_input_tokens: int | None = None
        self._current_phase: str | None = None

    # --- Properties --------------------------------------------------------

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    def update_system_prompt(self, new_prompt: str) -> None:
        """Update the system prompt.

        Used in continuous conversation mode at phase transitions to swap
        Layer 3 (focus) while preserving the conversation history.
        """
        self._system_prompt = new_prompt
        self._meta_persisted = False  # re-persist with new prompt

    def set_current_phase(self, phase_id: str) -> None:
        """Set the current phase ID. Subsequent messages will be stamped with it."""
        self._current_phase = phase_id

    @property
    def current_phase(self) -> str | None:
        return self._current_phase

    @property
    def messages(self) -> list[Message]:
        """Return a defensive copy of the message list."""
        return list(self._messages)

    @property
    def turn_count(self) -> int:
        """Number of conversational turns (one turn = one user message)."""
        return sum(1 for m in self._messages if m.role == "user")

    @property
    def message_count(self) -> int:
        """Total number of messages (all roles)."""
        return len(self._messages)

    @property
    def next_seq(self) -> int:
        return self._next_seq

    # --- Add messages ------------------------------------------------------

    async def add_user_message(
        self,
        content: str,
        *,
        is_transition_marker: bool = False,
        is_client_input: bool = False,
    ) -> Message:
        msg = Message(
            seq=self._next_seq,
            role="user",
            content=content,
            phase_id=self._current_phase,
            is_transition_marker=is_transition_marker,
            is_client_input=is_client_input,
        )
        self._messages.append(msg)
        self._next_seq += 1
        await self._persist(msg)
        return msg

    async def add_assistant_message(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> Message:
        msg = Message(
            seq=self._next_seq,
            role="assistant",
            content=content,
            tool_calls=tool_calls,
            phase_id=self._current_phase,
        )
        self._messages.append(msg)
        self._next_seq += 1
        await self._persist(msg)
        return msg

    async def add_tool_result(
        self,
        tool_use_id: str,
        content: str,
        is_error: bool = False,
    ) -> Message:
        msg = Message(
            seq=self._next_seq,
            role="tool",
            content=content,
            tool_use_id=tool_use_id,
            is_error=is_error,
            phase_id=self._current_phase,
        )
        self._messages.append(msg)
        self._next_seq += 1
        await self._persist(msg)
        return msg

    # --- Query -------------------------------------------------------------

    def to_llm_messages(self) -> list[dict[str, Any]]:
        """Return messages as OpenAI-format dicts (system prompt excluded).

        Automatically repairs orphaned tool_use blocks (assistant messages
        with tool_calls that lack corresponding tool-result messages).  This
        can happen when a loop is cancelled mid-tool-execution.
        """
        msgs = [m.to_llm_dict() for m in self._messages]
        return self._repair_orphaned_tool_calls(msgs)

    @staticmethod
    def _repair_orphaned_tool_calls(
        msgs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Ensure every tool_call has a matching tool-result message."""
        repaired: list[dict[str, Any]] = []
        for i, m in enumerate(msgs):
            repaired.append(m)
            tool_calls = m.get("tool_calls")
            if m.get("role") != "assistant" or not tool_calls:
                continue
            # Collect IDs of tool results that follow this assistant message
            answered: set[str] = set()
            for j in range(i + 1, len(msgs)):
                if msgs[j].get("role") == "tool":
                    tid = msgs[j].get("tool_call_id")
                    if tid:
                        answered.add(tid)
                else:
                    break  # stop at first non-tool message
            # Patch any missing results
            for tc in tool_calls:
                tc_id = tc.get("id")
                if tc_id and tc_id not in answered:
                    repaired.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": "ERROR: Tool execution was interrupted.",
                        }
                    )
        return repaired

    def estimate_tokens(self) -> int:
        """Best available token estimate.

        Uses actual API input token count when available (set via
        :meth:`update_token_count`), otherwise falls back to a
        ``total_chars / 4`` heuristic that includes both message content
        AND tool_call argument sizes.
        """
        if self._last_api_input_tokens is not None:
            return self._last_api_input_tokens
        total_chars = 0
        for m in self._messages:
            total_chars += len(m.content)
            if m.tool_calls:
                for tc in m.tool_calls:
                    func = tc.get("function", {})
                    total_chars += len(func.get("arguments", ""))
                    total_chars += len(func.get("name", ""))
        return total_chars // 4

    def update_token_count(self, actual_input_tokens: int) -> None:
        """Store actual API input token count for more accurate compaction.

        Called by EventLoopNode after each LLM call with the ``input_tokens``
        value from the API response.  This value includes system prompt and
        tool definitions, so it may be higher than a message-only estimate.
        """
        self._last_api_input_tokens = actual_input_tokens

    def usage_ratio(self) -> float:
        """Current token usage as a fraction of *max_history_tokens*.

        Returns 0.0 when ``max_history_tokens`` is zero (unlimited).
        """
        if self._max_history_tokens <= 0:
            return 0.0
        return self.estimate_tokens() / self._max_history_tokens

    def needs_compaction(self) -> bool:
        return self.estimate_tokens() >= self._max_history_tokens * self._compaction_threshold

    # --- Output-key extraction ---------------------------------------------

    def _extract_protected_values(self, messages: list[Message]) -> dict[str, str]:
        """Scan assistant messages for output_key values before compaction.

        Iterates most-recent-first. Once a key is found, it's skipped for
        older messages (latest value wins).
        """
        if not self._output_keys:
            return {}

        found: dict[str, str] = {}
        remaining_keys = set(self._output_keys)

        for msg in reversed(messages):
            if msg.role != "assistant" or not remaining_keys:
                continue

            for key in list(remaining_keys):
                value = self._try_extract_key(msg.content, key)
                if value is not None:
                    found[key] = value
                    remaining_keys.discard(key)

        return found

    def _try_extract_key(self, content: str, key: str) -> str | None:
        """Try 4 strategies to extract a key's value from message content."""
        return _try_extract_key(content, key)

    # --- Lifecycle ---------------------------------------------------------

    async def prune_old_tool_results(
        self,
        protect_tokens: int = 5000,
        min_prune_tokens: int = 2000,
    ) -> int:
        """Replace old tool result content with compact placeholders.

        Walks backward through messages. Recent tool results (within
        *protect_tokens*) are kept intact. Older tool results have their
        content replaced with a ~100-char placeholder that preserves the
        spillover filename reference (if any). Message structure (role,
        seq, tool_use_id) stays valid for the LLM API.

        Phase-aware behavior (continuous mode): when messages have ``phase_id``
        metadata, all messages in the current phase are protected regardless of
        token budget. Transition markers are never pruned. Older phases' tool
        results are pruned more aggressively.

        Error tool results are never pruned — they prevent re-calling
        failing tools.

        Returns the number of messages pruned (0 if nothing was pruned).
        """
        if not self._messages:
            return 0

        # Walk backward, classify tool results as protected vs pruneable
        protected_tokens = 0
        pruneable: list[int] = []  # indices into self._messages
        pruneable_tokens = 0

        for i in range(len(self._messages) - 1, -1, -1):
            msg = self._messages[i]

            # Transition markers are never pruned (any role)
            if msg.is_transition_marker:
                continue

            if msg.role != "tool":
                continue
            if msg.is_error:
                continue  # never prune errors
            if msg.content.startswith("[Pruned tool result"):
                continue  # already pruned

            # Phase-aware: protect current phase messages
            if self._current_phase and msg.phase_id == self._current_phase:
                continue

            est = len(msg.content) // 4
            if protected_tokens < protect_tokens:
                protected_tokens += est
            else:
                pruneable.append(i)
                pruneable_tokens += est

        # Only prune if enough to be worthwhile
        if pruneable_tokens < min_prune_tokens:
            return 0

        # Replace content with compact placeholder
        count = 0
        for i in pruneable:
            msg = self._messages[i]
            orig_len = len(msg.content)
            spillover = _extract_spillover_filename(msg.content)

            if spillover:
                placeholder = (
                    f"[Pruned tool result: {orig_len} chars. "
                    f"Full data in '{spillover}'. "
                    f"Use load_data('{spillover}') to retrieve.]"
                )
            else:
                placeholder = f"[Pruned tool result: {orig_len} chars cleared from context.]"

            self._messages[i] = Message(
                seq=msg.seq,
                role=msg.role,
                content=placeholder,
                tool_use_id=msg.tool_use_id,
                tool_calls=msg.tool_calls,
                is_error=msg.is_error,
                phase_id=msg.phase_id,
                is_transition_marker=msg.is_transition_marker,
            )
            count += 1

            if self._store:
                await self._store.write_part(msg.seq, self._messages[i].to_storage_dict())

        # Reset token estimate — content lengths changed
        self._last_api_input_tokens = None
        return count

    async def compact(
        self,
        summary: str,
        keep_recent: int = 2,
        phase_graduated: bool = False,
    ) -> None:
        """Replace old messages with a summary, optionally keeping recent ones.

        Args:
            summary: Caller-provided summary text.
            keep_recent: Number of recent messages to preserve (default 2).
                         Clamped to [0, len(messages) - 1].
            phase_graduated: When True and messages have phase_id metadata,
                split at phase boundaries instead of using keep_recent.
                Keeps current + previous phase intact; compacts older phases.
        """
        if not self._messages:
            return

        total = len(self._messages)

        # Phase-graduated: find the split point based on phase boundaries.
        # Keeps current phase + previous phase intact, compacts older phases.
        if phase_graduated and self._current_phase:
            split = self._find_phase_graduated_split()
        else:
            split = None

        if split is None:
            # Fallback: use keep_recent (non-phase or single-phase conversation)
            keep_recent = max(0, min(keep_recent, total - 1))
            split = total - keep_recent if keep_recent > 0 else total

        # Advance split past orphaned tool results at the boundary.
        # Tool-role messages reference a tool_use from the preceding
        # assistant message; if that assistant message falls into the
        # compacted (old) portion the tool_result becomes invalid.
        while split < total and self._messages[split].role == "tool":
            split += 1

        # Nothing to compact
        if split == 0:
            return

        old_messages = list(self._messages[:split])
        recent_messages = list(self._messages[split:])

        # Extract protected values from messages being discarded
        if self._output_keys:
            protected = self._extract_protected_values(old_messages)
            if protected:
                lines = ["PRESERVED VALUES (do not lose these):"]
                for k, v in protected.items():
                    lines.append(f"- {k}: {v}")
                lines.append("")
                lines.append("CONVERSATION SUMMARY:")
                lines.append(summary)
                summary = "\n".join(lines)

        # Determine summary seq
        if recent_messages:
            summary_seq = recent_messages[0].seq - 1
        else:
            summary_seq = self._next_seq
            self._next_seq += 1

        summary_msg = Message(seq=summary_seq, role="user", content=summary)

        # Persist
        if self._store:
            delete_before = recent_messages[0].seq if recent_messages else self._next_seq
            await self._store.delete_parts_before(delete_before)
            await self._store.write_part(summary_msg.seq, summary_msg.to_storage_dict())
            await self._store.write_cursor({"next_seq": self._next_seq})

        self._messages = [summary_msg] + recent_messages
        self._last_api_input_tokens = None  # reset; next LLM call will recalibrate

    async def compact_preserving_structure(
        self,
        spillover_dir: str,
        keep_recent: int = 4,
        phase_graduated: bool = False,
    ) -> None:
        """Structure-preserving compaction: save freeform text to file, keep tool messages.

        Unlike ``compact()`` which replaces ALL old messages with a single LLM
        summary, this method preserves the tool call structure (assistant
        messages with tool_calls + tool result messages) that are already tiny
        after pruning.  Only freeform text exchanges (user messages,
        text-only assistant messages) are saved to a file and removed.

        The result: the agent retains exact knowledge of what tools it called,
        where each result is stored, and can load the conversation text if
        needed.  No LLM summary call.  No heuristics.  Nothing lost.
        """
        if not self._messages:
            return

        total = len(self._messages)

        # Determine split point (same logic as compact)
        if phase_graduated and self._current_phase:
            split = self._find_phase_graduated_split()
        else:
            split = None

        if split is None:
            keep_recent = max(0, min(keep_recent, total - 1))
            split = total - keep_recent if keep_recent > 0 else total

        # Advance split past orphaned tool results at the boundary
        while split < total and self._messages[split].role == "tool":
            split += 1

        if split == 0:
            return

        old_messages = self._messages[:split]

        # Classify old messages: structural (keep) vs freeform (save to file)
        kept_structural: list[Message] = []
        freeform_lines: list[str] = []

        for msg in old_messages:
            if msg.role == "tool":
                # Tool results — already pruned to ~30 tokens (file reference).
                # Keep in conversation.
                kept_structural.append(msg)
            elif msg.role == "assistant" and msg.tool_calls:
                # Assistant message with tool_calls — keep the tool_calls
                # with truncated arguments, clear the freeform text content.
                compact_tcs = _compact_tool_calls(msg.tool_calls)
                kept_structural.append(
                    Message(
                        seq=msg.seq,
                        role=msg.role,
                        content="",
                        tool_calls=compact_tcs,
                        is_error=msg.is_error,
                        phase_id=msg.phase_id,
                        is_transition_marker=msg.is_transition_marker,
                    )
                )
            else:
                # Freeform text (user messages, text-only assistant messages)
                # — save to file and remove from conversation.
                role_label = msg.role
                text = msg.content
                if len(text) > 2000:
                    text = text[:2000] + "…"
                freeform_lines.append(f"[{role_label}] (seq={msg.seq}): {text}")

        # Write freeform text to a numbered conversation file
        spill_path = Path(spillover_dir)
        spill_path.mkdir(parents=True, exist_ok=True)

        # Find next conversation file number
        existing = sorted(spill_path.glob("conversation_*.md"))
        next_n = len(existing) + 1
        conv_filename = f"conversation_{next_n}.md"

        if freeform_lines:
            header = f"## Compacted conversation (messages 1-{split})\n\n"
            conv_text = header + "\n\n".join(freeform_lines)
            (spill_path / conv_filename).write_text(conv_text, encoding="utf-8")
        else:
            # Nothing to save — skip file creation
            conv_filename = ""

        # Build reference message
        if conv_filename:
            ref_content = (
                f"[Previous conversation saved to '{conv_filename}'. "
                f"Use load_data('{conv_filename}') to review if needed.]"
            )
        else:
            ref_content = "[Previous freeform messages compacted.]"
        # Use a seq just before the first kept message
        recent_messages = list(self._messages[split:])
        if kept_structural:
            ref_seq = kept_structural[0].seq - 1
        elif recent_messages:
            ref_seq = recent_messages[0].seq - 1
        else:
            ref_seq = self._next_seq
            self._next_seq += 1

        ref_msg = Message(seq=ref_seq, role="user", content=ref_content)

        # Persist: delete old messages from store, write reference + kept structural
        if self._store:
            first_kept_seq = (
                kept_structural[0].seq
                if kept_structural
                else (recent_messages[0].seq if recent_messages else self._next_seq)
            )
            # Delete everything before the first structural message we're keeping
            await self._store.delete_parts_before(first_kept_seq)
            # Write the reference message
            await self._store.write_part(ref_msg.seq, ref_msg.to_storage_dict())
            # Write kept structural messages (they may have been modified)
            for msg in kept_structural:
                await self._store.write_part(msg.seq, msg.to_storage_dict())
            await self._store.write_cursor({"next_seq": self._next_seq})

        # Reassemble: reference + kept structural (in original order) + recent
        self._messages = [ref_msg] + kept_structural + recent_messages
        self._last_api_input_tokens = None

    def _find_phase_graduated_split(self) -> int | None:
        """Find split point that preserves current + previous phase.

        Returns the index of the first message in the protected set,
        or None if phase graduation doesn't apply (< 3 phases).
        """
        # Collect distinct phases in order of first appearance
        phases_seen: list[str] = []
        for msg in self._messages:
            if msg.phase_id and msg.phase_id not in phases_seen:
                phases_seen.append(msg.phase_id)

        # Need at least 3 phases for graduation to be meaningful
        # (current + previous are protected, older get compacted)
        if len(phases_seen) < 3:
            return None

        # Protect: current phase + previous phase
        protected_phases = {phases_seen[-1], phases_seen[-2]}

        # Find split: first message belonging to a protected phase
        for i, msg in enumerate(self._messages):
            if msg.phase_id in protected_phases:
                return i

        return None

    async def clear(self) -> None:
        """Remove all messages, keep system prompt, preserve ``_next_seq``."""
        if self._store:
            await self._store.delete_parts_before(self._next_seq)
            await self._store.write_cursor({"next_seq": self._next_seq})
        self._messages.clear()
        self._last_api_input_tokens = None

    def export_summary(self) -> str:
        """Structured summary with [STATS], [CONFIG], [RECENT_MESSAGES] sections."""
        prompt_preview = (
            self._system_prompt[:80] + "..."
            if len(self._system_prompt) > 80
            else self._system_prompt
        )

        lines = [
            "[STATS]",
            f"turns: {self.turn_count}",
            f"messages: {self.message_count}",
            f"estimated_tokens: {self.estimate_tokens()}",
            "",
            "[CONFIG]",
            f"system_prompt: {prompt_preview!r}",
        ]

        if self._output_keys:
            lines.append(f"output_keys: {', '.join(self._output_keys)}")

        lines.append("")
        lines.append("[RECENT_MESSAGES]")
        for m in self._messages[-5:]:
            preview = m.content[:60] + "..." if len(m.content) > 60 else m.content
            lines.append(f"  [{m.role}] {preview}")

        return "\n".join(lines)

    # --- Persistence internals ---------------------------------------------

    async def _persist(self, message: Message) -> None:
        """Write-through a single message.  No-op when store is None."""
        if self._store is None:
            return
        if not self._meta_persisted:
            await self._persist_meta()
        await self._store.write_part(message.seq, message.to_storage_dict())
        await self._store.write_cursor({"next_seq": self._next_seq})

    async def _persist_meta(self) -> None:
        """Lazily write conversation metadata to the store (called once)."""
        if self._store is None:
            return
        await self._store.write_meta(
            {
                "system_prompt": self._system_prompt,
                "max_history_tokens": self._max_history_tokens,
                "compaction_threshold": self._compaction_threshold,
                "output_keys": self._output_keys,
            }
        )
        self._meta_persisted = True

    # --- Restore -----------------------------------------------------------

    @classmethod
    async def restore(
        cls,
        store: ConversationStore,
        phase_id: str | None = None,
    ) -> NodeConversation | None:
        """Reconstruct a NodeConversation from a store.

        Args:
            store: The conversation store to read from.
            phase_id: If set, only load parts matching this phase_id.
                Used in isolated mode so a node only sees its own
                messages in the shared flat store.  In continuous mode
                pass ``None`` to load all parts.

        Returns ``None`` if the store contains no metadata (i.e. the
        conversation was never persisted).
        """
        meta = await store.read_meta()
        if meta is None:
            return None

        conv = cls(
            system_prompt=meta.get("system_prompt", ""),
            max_history_tokens=meta.get("max_history_tokens", 32000),
            compaction_threshold=meta.get("compaction_threshold", 0.8),
            output_keys=meta.get("output_keys"),
            store=store,
        )
        conv._meta_persisted = True

        parts = await store.read_parts()
        if phase_id:
            parts = [p for p in parts if p.get("phase_id") == phase_id]
        conv._messages = [Message.from_storage_dict(p) for p in parts]

        cursor = await store.read_cursor()
        if cursor:
            conv._next_seq = cursor["next_seq"]
        elif conv._messages:
            conv._next_seq = conv._messages[-1].seq + 1

        return conv
