"""NodeConversation: Message history management for graph nodes."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

LEGACY_RUN_ID = "__legacy_run__"
logger = logging.getLogger(__name__)


def is_legacy_run_id(run_id: str | None) -> bool:
    """True when run_id represents pre-migration (no run boundary) data."""
    return run_id is None or run_id == LEGACY_RUN_ID


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
    # Optional image content blocks (e.g. from browser_screenshot)
    image_content: list[dict[str, Any]] | None = None
    # True when message contains an activated skill body (AS-10: never prune)
    is_skill_content: bool = False
    # Logical worker run identifier for shared-session persistence
    run_id: str | None = None
    # True when this is a framework-injected continuation hint (continue-nudge
    # on stream stall). Stored as a user message for API compatibility, but
    # the UI should render it as a compact system notice, not user speech.
    is_system_nudge: bool = False
    # True when this message is a partial/truncated assistant turn reconstructed
    # from a crashed or watchdog-cancelled stream. Signals that the original
    # turn never finished — the model may or may not choose to redo it.
    truncated: bool = False
    # When non-None, identifies the parent session id this message was
    # carried over from — used by fork_session_into_colony on the single
    # compacted-summary message it writes when a colony is born from a
    # queen DM. Presence of the field IS the "inherited" signal.
    inherited_from: str | None = None
    # True when this user message was synthesized from one or more
    # fired triggers (timer/webhook), not typed by a human. The LLM still
    # sees the message as a regular user turn; the UI uses this flag to
    # render it as a trigger banner instead of a speech bubble.
    is_trigger: bool = False

    def to_llm_dict(self) -> dict[str, Any]:
        """Convert to OpenAI-format message dict."""
        if self.role == "user":
            if self.image_content:
                blocks: list[dict[str, Any]] = []
                if self.content:
                    blocks.append({"type": "text", "text": self.content})
                blocks.extend(self.image_content)
                return {"role": "user", "content": blocks}
            return {"role": "user", "content": self.content}

        if self.role == "assistant":
            d: dict[str, Any] = {"role": "assistant"}
            if self.tool_calls:
                d["tool_calls"] = self.tool_calls
                d["content"] = self.content if self.content else None
            else:
                d["content"] = self.content or ""
            return d

        # role == "tool"
        content = f"ERROR: {self.content}" if self.is_error else self.content
        if self.image_content:
            # Multimodal tool result: text + image content blocks
            blocks: list[dict[str, Any]] = [{"type": "text", "text": content}]
            blocks.extend(self.image_content)
            return {
                "role": "tool",
                "tool_call_id": self.tool_use_id,
                "content": blocks,
            }
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
        if self.image_content is not None:
            d["image_content"] = self.image_content
        if self.run_id is not None:
            d["run_id"] = self.run_id
        if self.is_system_nudge:
            d["is_system_nudge"] = self.is_system_nudge
        if self.truncated:
            d["truncated"] = self.truncated
        if self.inherited_from is not None:
            d["inherited_from"] = self.inherited_from
        if self.is_trigger:
            d["is_trigger"] = self.is_trigger
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
            image_content=data.get("image_content"),
            run_id=data.get("run_id"),
            is_system_nudge=data.get("is_system_nudge", False),
            truncated=data.get("truncated", False),
            inherited_from=data.get("inherited_from"),
            is_trigger=data.get("is_trigger", False),
        )


def _normalize_cursor(cursor: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize legacy and run-scoped cursor formats into one flat shape."""
    return dict(cursor) if cursor else {}


def get_cursor_next_seq(cursor: dict[str, Any] | None) -> int | None:
    next_seq = (cursor or {}).get("next_seq")
    return next_seq if isinstance(next_seq, int) else None


def update_cursor_next_seq(cursor: dict[str, Any] | None, next_seq: int) -> dict[str, Any]:
    updated = dict(cursor or {})
    updated["next_seq"] = next_seq
    return updated


def get_run_cursor(cursor: dict[str, Any] | None, run_id: str | None) -> dict[str, Any] | None:
    return dict(cursor) if cursor else None


def update_run_cursor(
    cursor: dict[str, Any] | None,
    run_id: str | None,
    values: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(cursor or {})
    updated.update(values)
    return updated


def _extract_spillover_filename(content: str) -> str | None:
    """Extract spillover filename from a tool result annotation.

    Matches patterns produced by ``truncate_tool_result``:
        - New large-result header: "Full result saved at: /abs/path/file.txt"
        - Legacy bracketed trailer: "[Saved to 'file.txt']"  (pre-2026-04-15,
          retained here so cold conversations still resolve)
    """
    # New prose format — ``saved at: <absolute path>``, terminated by
    # newline or end-of-string.
    match = re.search(r"[Ss]aved at:\s*(\S+)", content)
    if match:
        return match.group(1)
    # Legacy format.
    match = re.search(r"[Ss]aved to '([^']+)'", content)
    return match.group(1) if match else None


_TC_ARG_LIMIT = 200  # max chars per tool_call argument after compaction


def _compact_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Truncate tool_call arguments to save context tokens during compaction.

    Preserves ``id``, ``type``, and ``function.name`` exactly.  When arguments
    exceed ``_TC_ARG_LIMIT``, replaces the full JSON string with a compact
    **valid** JSON summary.  The Anthropic API parses tool_call arguments and
    rejects requests with malformed JSON (e.g. unterminated strings), so we
    must never produce broken JSON here.
    """
    compact = []
    for tc in tool_calls:
        func = tc.get("function", {})
        args = func.get("arguments", "")
        if len(args) > _TC_ARG_LIMIT:
            # Build a valid JSON summary instead of slicing mid-string.
            # Try to extract top-level keys for a meaningful preview.
            try:
                parsed = json.loads(args)
                if isinstance(parsed, dict):
                    # Preserve key names, truncate values
                    summary_parts = []
                    for k, v in parsed.items():
                        v_str = str(v)
                        if len(v_str) > 60:
                            v_str = v_str[:60] + "..."
                        summary_parts.append(f"{k}={v_str}")
                    summary = ", ".join(summary_parts)
                    if len(summary) > _TC_ARG_LIMIT:
                        summary = summary[:_TC_ARG_LIMIT] + "..."
                    args = json.dumps({"_compacted": summary})
                else:
                    args = json.dumps({"_compacted": str(parsed)[:_TC_ARG_LIMIT]})
            except (json.JSONDecodeError, TypeError):
                # Args were already invalid JSON — wrap the preview safely
                args = json.dumps({"_compacted": args[:_TC_ARG_LIMIT]})
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


def extract_tool_call_history(messages: list[Message], max_entries: int = 30) -> str:
    """Build a compact tool call history from a list of messages.

    Used in compaction summaries to prevent the LLM from re-calling
    tools it already called.  Extracts tool call details, files saved,
    outputs set, and errors encountered.
    """
    tool_calls_detail: dict[str, list[str]] = {}
    files_saved: list[str] = []
    outputs_set: list[str] = []
    errors: list[str] = []

    def _summarize_input(name: str, args: dict) -> str:
        if name == "web_search":
            return args.get("query", "")
        if name == "web_scrape":
            return args.get("url", "")
        if name == "read_file":
            return args.get("path", "")
        return ""

    for msg in messages:
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "unknown")
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    args = {}

                summary = _summarize_input(name, args)
                tool_calls_detail.setdefault(name, []).append(summary)

                if name == "read_file" and args.get("path"):
                    files_saved.append(args["path"])
                if name == "set_output" and args.get("key"):
                    outputs_set.append(args["key"])

        if msg.role == "tool" and msg.is_error:
            preview = msg.content[:120].replace("\n", " ")
            errors.append(preview)

    parts: list[str] = []
    if tool_calls_detail:
        lines: list[str] = []
        for name, inputs in list(tool_calls_detail.items())[:max_entries]:
            count = len(inputs)
            non_empty = [s for s in inputs if s]
            if non_empty:
                detail_lines = [f"    - {s[:120]}" for s in non_empty[:8]]
                lines.append(f"  {name} ({count}x):\n" + "\n".join(detail_lines))
            else:
                lines.append(f"  {name} ({count}x)")
        parts.append("TOOLS ALREADY CALLED:\n" + "\n".join(lines))
    if files_saved:
        unique = list(dict.fromkeys(files_saved))
        parts.append("FILES SAVED: " + ", ".join(unique))
    if outputs_set:
        unique = list(dict.fromkeys(outputs_set))
        parts.append("OUTPUTS SET: " + ", ".join(unique))
    if errors:
        parts.append("ERRORS (do NOT retry these):\n" + "\n".join(f"  - {e}" for e in errors[:10]))
    return "\n\n".join(parts)


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

    async def delete_parts_before(self, seq: int, run_id: str | None = None) -> None: ...

    async def write_partial(self, seq: int, data: dict[str, Any]) -> None: ...

    async def read_partial(self, seq: int) -> dict[str, Any] | None: ...

    async def read_all_partials(self) -> list[dict[str, Any]]: ...

    async def clear_partial(self, seq: int) -> None: ...

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
    from framework.orchestrator.node import find_json_object

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
        max_context_tokens: int = 32000,
        compaction_threshold: float = 0.8,
        output_keys: list[str] | None = None,
        store: ConversationStore | None = None,
        run_id: str | None = None,
        compaction_buffer_tokens: int | None = None,
        compaction_warning_buffer_tokens: int | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._max_context_tokens = max_context_tokens
        self._compaction_threshold = compaction_threshold
        # Buffer-based compaction trigger (Gap 7). When set, takes
        # precedence over the multiplicative compaction_threshold so the
        # loop reserves a fixed headroom for the next turn's input+output
        # instead of trying to get exactly X% of the way to the hard
        # limit. If left as None the legacy threshold-based rule is
        # used, keeping old call sites behaving identically.
        self._compaction_buffer_tokens = compaction_buffer_tokens
        self._compaction_warning_buffer_tokens = compaction_warning_buffer_tokens
        self._output_keys = output_keys
        self._store = store
        self._messages: list[Message] = []
        self._next_seq: int = 0
        self._meta_persisted: bool = False
        self._last_api_input_tokens: int | None = None
        self._current_phase: str | None = None
        self._run_id: str | None = run_id

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
        image_content: list[dict[str, Any]] | None = None,
        is_system_nudge: bool = False,
        is_trigger: bool = False,
    ) -> Message:
        msg = Message(
            seq=self._next_seq,
            role="user",
            content=content,
            phase_id=self._current_phase,
            run_id=self._run_id,
            is_transition_marker=is_transition_marker,
            is_client_input=is_client_input,
            image_content=image_content,
            is_system_nudge=is_system_nudge,
            is_trigger=is_trigger,
        )
        self._messages.append(msg)
        self._next_seq += 1
        # Invalidate stale API token count so estimate_tokens() uses
        # the char-based heuristic which reflects the new message.
        self._last_api_input_tokens = None
        await self._persist(msg)
        return msg

    async def add_assistant_message(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        *,
        truncated: bool = False,
    ) -> Message:
        msg = Message(
            seq=self._next_seq,
            role="assistant",
            content=content,
            tool_calls=tool_calls,
            phase_id=self._current_phase,
            run_id=self._run_id,
            truncated=truncated,
        )
        self._messages.append(msg)
        self._next_seq += 1
        self._last_api_input_tokens = None
        await self._persist(msg)
        return msg

    async def add_tool_result(
        self,
        tool_use_id: str,
        content: str,
        is_error: bool = False,
        image_content: list[dict[str, Any]] | None = None,
        is_skill_content: bool = False,
    ) -> Message:
        # Dedup guard: reject a second tool_result for the same tool_use_id.
        # Anthropic's API only accepts one result per tool_call, and a duplicate
        # causes a hard 400 two turns later ("messages with role 'tool' must
        # be a response to a preceding message with 'tool_calls'"). Duplicates
        # can arise when a tool_call_timeout fires and records a placeholder
        # error, then the real executor thread eventually delivers the actual
        # result (the thread kept running inside run_in_executor — see
        # tool_result_handler.execute_tool).  We keep the FIRST result to
        # preserve whatever state the agent already reasoned about.
        for existing in reversed(self._messages):
            if existing.role == "tool" and existing.tool_use_id == tool_use_id:
                import logging as _logging

                _logging.getLogger(__name__).warning(
                    "add_tool_result: dropping duplicate result for tool_use_id=%s "
                    "(first result preserved, %d chars; new result ignored, %d chars)",
                    tool_use_id,
                    len(existing.content),
                    len(content),
                )
                return existing
        msg = Message(
            seq=self._next_seq,
            role="tool",
            content=content,
            tool_use_id=tool_use_id,
            is_error=is_error,
            phase_id=self._current_phase,
            image_content=image_content,
            is_skill_content=is_skill_content,
            run_id=self._run_id,
        )
        self._messages.append(msg)
        self._next_seq += 1
        self._last_api_input_tokens = None
        await self._persist(msg)
        return msg

    # --- Query -------------------------------------------------------------

    def find_completed_tool_call(
        self,
        name: str,
        tool_input: dict[str, Any],
        within_last_turns: int = 3,
    ) -> Message | None:
        """Return the most recent assistant message that issued a tool call
        with the same (name + canonical-json args) AND received a non-error
        tool result, within the last ``within_last_turns`` assistant turns.

        Used by the replay detector to flag when the model is about to redo
        a successful call — we prepend a steer onto the upcoming result but
        still execute, so tools like browser_screenshot that are legitimately
        repeated are not silently skipped.
        """
        try:
            target_canonical = json.dumps(tool_input, sort_keys=True, default=str)
        except (TypeError, ValueError):
            target_canonical = str(tool_input)

        # Walk backwards over recent assistant messages
        assistant_turns_seen = 0
        for idx in range(len(self._messages) - 1, -1, -1):
            m = self._messages[idx]
            if m.role != "assistant":
                continue
            assistant_turns_seen += 1
            if assistant_turns_seen > within_last_turns:
                break
            if not m.tool_calls:
                continue
            for tc in m.tool_calls:
                func = tc.get("function", {}) if isinstance(tc, dict) else {}
                tc_name = func.get("name")
                if tc_name != name:
                    continue
                args_str = func.get("arguments", "")
                try:
                    parsed = json.loads(args_str) if isinstance(args_str, str) else args_str
                    canonical = json.dumps(parsed, sort_keys=True, default=str)
                except (TypeError, ValueError):
                    canonical = str(args_str)
                if canonical != target_canonical:
                    continue
                # Found a match — now verify its result was not an error.
                tc_id = tc.get("id")
                for later in self._messages[idx + 1 :]:
                    if later.role == "tool" and later.tool_use_id == tc_id:
                        if not later.is_error:
                            return m
                        break
        return None

    def to_llm_messages(self) -> list[dict[str, Any]]:
        """Return messages as OpenAI-format dicts (system prompt excluded).

        Automatically repairs orphaned tool_use blocks (assistant messages
        with tool_calls that lack corresponding tool-result messages).  This
        can happen when a loop is cancelled mid-tool-execution.
        """
        msgs = [m.to_llm_dict() for m in self._messages]
        msgs = self._repair_orphaned_tool_calls(msgs)
        msgs = self._sanitize_for_api(msgs)
        return msgs

    @staticmethod
    def _sanitize_for_api(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Final pass: ensure message sequence is valid for strict APIs.

        Rules:
        1. No two consecutive messages with the same role (merge or drop)
        2. Tool messages must have a tool_call_id
        3. Assistant messages with tool_calls must have content=null, not ""
        4. First message must not be 'tool' or 'assistant' (without prior context)
        """
        cleaned: list[dict[str, Any]] = []
        for m in msgs:
            role = m.get("role")

            # Fix assistant content when tool_calls present
            if role == "assistant" and m.get("tool_calls"):
                if m.get("content") == "":
                    m["content"] = None

            # Drop tool messages without tool_call_id
            if role == "tool" and not m.get("tool_call_id"):
                continue

            # Drop consecutive duplicate roles (merge user messages)
            if cleaned and cleaned[-1].get("role") == role == "user":
                prev_content = cleaned[-1].get("content", "")
                curr_content = m.get("content", "")
                if isinstance(prev_content, str) and isinstance(curr_content, str):
                    cleaned[-1]["content"] = f"{prev_content}\n{curr_content}"
                    continue

            cleaned.append(m)

        # Drop leading assistant/tool messages (no prior context)
        while cleaned and cleaned[0].get("role") in ("assistant", "tool"):
            cleaned.pop(0)

        return cleaned

    @staticmethod
    def _repair_orphaned_tool_calls(
        msgs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Ensure tool_call / tool_result pairs are consistent.

        1. **Orphaned tool results** (tool_result with no matching tool_use
           anywhere) are dropped.  Happens after compaction removes the
           parent assistant message.
        2. **Positionally orphaned tool results** (tool_result separated
           from its parent by a non-tool message, e.g. a user injection)
           are dropped.  The Anthropic API requires tool messages to
           follow immediately after the assistant message that issued
           the matching tool_call.
        3. **Duplicate tool results** (same tool_call_id appearing more
           than once) are dropped; only the first is kept.
        4. **Orphaned tool calls** (tool_use with no following tool_result)
           get a synthetic error result appended.  Happens when the loop
           is cancelled mid-tool-execution.
        """
        # Pass 1: collect all tool_call IDs from assistant messages so we
        # can identify orphaned tool-result messages.
        all_tool_call_ids: set[str] = set()
        for m in msgs:
            if m.get("role") == "assistant":
                for tc in m.get("tool_calls") or []:
                    tc_id = tc.get("id")
                    if tc_id:
                        all_tool_call_ids.add(tc_id)

        # Pass 2: build repaired list — drop orphaned tool results, drop
        # positional orphans and duplicates, patch missing tool results.
        #
        # ``open_tool_calls`` holds the tool_call IDs we're still expecting
        # results for: it's populated when we emit an assistant-with-tool_calls
        # and drained as matching tool messages follow. Any tool message
        # whose id is not currently open is positionally invalid and gets
        # dropped — that closes the gap that caused the tool-after-user
        # 400 errors.
        repaired: list[dict[str, Any]] = []
        open_tool_calls: set[str] = set()
        seen_tool_ids: set[str] = set()
        for m in msgs:
            role = m.get("role")

            if role == "tool":
                tid = m.get("tool_call_id")
                # Drop tool results with no matching tool_use anywhere.
                if not tid or tid not in all_tool_call_ids:
                    continue
                # Drop duplicates (same id appearing twice) — keep first.
                if tid in seen_tool_ids:
                    continue
                # Drop positional orphans — tool messages whose parent
                # assistant isn't the still-open assistant block.
                if tid not in open_tool_calls:
                    continue
                open_tool_calls.discard(tid)
                seen_tool_ids.add(tid)
                repaired.append(m)
                continue

            # Any non-tool message closes the current assistant tool block.
            # If the previous assistant left tool_calls unanswered, patch
            # synthetic error results before emitting this message so the
            # API sees a complete pairing.
            if open_tool_calls:
                for stale_id in list(open_tool_calls):
                    repaired.append(
                        {
                            "role": "tool",
                            "tool_call_id": stale_id,
                            "content": "ERROR: Tool execution was interrupted.",
                        }
                    )
                    seen_tool_ids.add(stale_id)
                open_tool_calls.clear()

            repaired.append(m)

            if role == "assistant":
                for tc in m.get("tool_calls") or []:
                    tc_id = tc.get("id")
                    if tc_id and tc_id not in seen_tool_ids:
                        open_tool_calls.add(tc_id)

        # Tail: if the conversation ends with an assistant that issued
        # tool_calls and no results followed, patch them so the next
        # turn's first message can be a valid assistant/user response.
        if open_tool_calls:
            for stale_id in list(open_tool_calls):
                repaired.append(
                    {
                        "role": "tool",
                        "tool_call_id": stale_id,
                        "content": "ERROR: Tool execution was interrupted.",
                    }
                )

        return repaired

    def estimate_tokens(self) -> int:
        """Best available token estimate.

        Uses actual API input token count when available (set via
        :meth:`update_token_count`), otherwise falls back to a
        character-based heuristic that includes message content, tool_call
        arguments, and image blocks.  The heuristic applies a 4/3 safety
        margin to avoid under-counting (inspired by Claude Code's compact
        service).
        """
        if self._last_api_input_tokens is not None:
            return self._last_api_input_tokens
        total_chars = 0
        image_tokens = 0
        for m in self._messages:
            total_chars += len(m.content)
            if m.tool_calls:
                for tc in m.tool_calls:
                    func = tc.get("function", {})
                    total_chars += len(func.get("arguments", ""))
                    total_chars += len(func.get("name", ""))
            if m.image_content:
                # Images/documents have a fixed token cost per block
                image_tokens += len(m.image_content) * 2000
        # Apply 4/3 safety margin to character-based estimate
        return (total_chars * 4) // (3 * 4) + image_tokens

    def update_token_count(self, actual_input_tokens: int) -> None:
        """Store actual API input token count for more accurate compaction.

        Called by EventLoopNode after each LLM call with the ``input_tokens``
        value from the API response.  This value includes system prompt and
        tool definitions, so it may be higher than a message-only estimate.
        """
        self._last_api_input_tokens = actual_input_tokens

    def usage_ratio(self) -> float:
        """Current token usage as a fraction of *max_context_tokens*.

        Returns 0.0 when ``max_context_tokens`` is zero (unlimited).
        """
        if self._max_context_tokens <= 0:
            return 0.0
        return self.estimate_tokens() / self._max_context_tokens

    def needs_compaction(self) -> bool:
        """True when the conversation should be compacted before the
        next LLM call.

        Buffer-based rule (Gap 7): trigger when the current estimate
        plus the configured buffer would exceed the hard context limit.
        Prevents compaction from firing only AFTER we're already over
        the wire and forced into a reactive binary-split pass.

        When no buffer is configured, falls back to the multiplicative
        threshold the old callers were built around.
        """
        if self._max_context_tokens <= 0:
            return False
        if self._compaction_buffer_tokens is not None:
            budget = self._max_context_tokens - self._compaction_buffer_tokens
            return self.estimate_tokens() >= max(0, budget)
        return self.estimate_tokens() >= self._max_context_tokens * self._compaction_threshold

    def compaction_warning(self) -> bool:
        """True when the conversation has crossed the warning threshold
        but not yet the hard compaction trigger.

        Used by telemetry / UI to show a "context getting tight" hint
        before a compaction pass actually runs. Returns False when no
        warning buffer is configured (legacy behaviour).
        """
        if self._max_context_tokens <= 0 or self._compaction_warning_buffer_tokens is None:
            return False
        warn_at = self._max_context_tokens - self._compaction_warning_buffer_tokens
        return self.estimate_tokens() >= max(0, warn_at)

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
            if msg.is_skill_content:
                continue  # never prune activated skill instructions (AS-10)
            if msg.content.startswith(("Pruned tool result", "[Pruned tool result")):
                continue  # already pruned
            # Tiny results (set_output acks, confirmations) — pruning
            # saves negligible space but makes the LLM think the call
            # failed, causing costly retries.
            if len(msg.content) < 100:
                continue

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
                    f"Pruned tool result ({orig_len:,} chars) cleared from context. "
                    f"Full data saved at: {spillover}\n"
                    f"Read the complete data with read_file(path='{spillover}')."
                )
            else:
                placeholder = f"Pruned tool result ({orig_len:,} chars) cleared from context."

            self._messages[i] = Message(
                seq=msg.seq,
                role=msg.role,
                content=placeholder,
                tool_use_id=msg.tool_use_id,
                tool_calls=msg.tool_calls,
                is_error=msg.is_error,
                phase_id=msg.phase_id,
                is_transition_marker=msg.is_transition_marker,
                run_id=msg.run_id,
            )
            count += 1

            if self._store:
                await self._store.write_part(msg.seq, self._messages[i].to_storage_dict())

        # Reset token estimate — content lengths changed
        self._last_api_input_tokens = None
        return count

    async def evict_old_images(self, keep_latest: int = 2) -> int:
        """Strip ``image_content`` from older messages, keeping the most recent.

        Screenshots from ``browser_screenshot`` are inlined into the
        message's ``image_content`` as base64 data URLs. Each screenshot
        costs ~250k tokens when the provider counts the base64 as
        text — four screenshots push a conversation over gemini's 1M
        context limit and trigger out-of-context garbage output (see
        ``session_20260415_104727_5c4ed7ff`` for the terminal case
        where the model emitted ``协日`` as its final text then stopped).

        This method walks backward through messages and keeps
        ``image_content`` intact on the most recent ``keep_latest``
        messages that have images. Older messages get their
        ``image_content`` nulled out — the text content (metadata
        like url, dimensions, scale hints) stays, but the raw bytes
        are dropped. Storage is updated too so cold-restore sees the
        same evicted state.

        Run this right after every tool result is recorded so image
        context stays bounded even within a single iteration (the
        compaction pipeline only fires at iteration boundaries, too
        late for a single turn that takes 4 screenshots).

        Returns the number of messages whose image_content was evicted.
        """
        if not self._messages or keep_latest < 0:
            return 0

        # Find messages carrying images, walking newest → oldest.
        image_indices: list[int] = []
        for i in range(len(self._messages) - 1, -1, -1):
            if self._messages[i].image_content:
                image_indices.append(i)

        # Nothing to evict if we have ≤ keep_latest images total.
        if len(image_indices) <= keep_latest:
            return 0

        # Evict everything past the first keep_latest (newest) entries.
        to_evict = image_indices[keep_latest:]
        evicted = 0
        for idx in to_evict:
            msg = self._messages[idx]
            self._messages[idx] = Message(
                seq=msg.seq,
                role=msg.role,
                content=msg.content,
                tool_use_id=msg.tool_use_id,
                tool_calls=msg.tool_calls,
                is_error=msg.is_error,
                phase_id=msg.phase_id,
                is_transition_marker=msg.is_transition_marker,
                is_client_input=msg.is_client_input,
                image_content=None,  # ← dropped
                is_skill_content=msg.is_skill_content,
                run_id=msg.run_id,
            )
            evicted += 1
            if self._store:
                await self._store.write_part(msg.seq, self._messages[idx].to_storage_dict())

        if evicted:
            # Reset token estimate — image blocks no longer contribute.
            self._last_api_input_tokens = None
            logger.info(
                "evict_old_images: dropped image_content from %d message(s), kept %d most recent",
                evicted,
                keep_latest,
            )
        return evicted

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

        summary_msg = Message(seq=summary_seq, role="user", content=summary, run_id=self._run_id)

        # Persist
        if self._store:
            delete_before = recent_messages[0].seq if recent_messages else self._next_seq
            await self._store.delete_parts_before(delete_before)
            await self._store.write_part(summary_msg.seq, summary_msg.to_storage_dict())
            await self._write_next_seq()

        self._messages = [summary_msg] + recent_messages
        self._last_api_input_tokens = None  # reset; next LLM call will recalibrate

    async def compact_preserving_structure(
        self,
        spillover_dir: str,
        keep_recent: int = 4,
        phase_graduated: bool = False,
        aggressive: bool = False,
    ) -> None:
        """Structure-preserving compaction: save freeform text to file, keep tool messages.

        Unlike ``compact()`` which replaces ALL old messages with a single LLM
        summary, this method preserves the tool call structure (assistant
        messages with tool_calls + tool result messages) that are already tiny
        after pruning.  Only freeform text exchanges (user messages,
        text-only assistant messages) are saved to a file and removed.

        When *aggressive* is True, non-essential tool call pairs are also
        collapsed into a compact summary instead of being kept individually.
        Only ``set_output`` calls and error results are preserved; all other
        old tool pairs are replaced by a tool-call history summary.

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
        collapsed_msgs: list[Message] = []

        # Collect all tool_use IDs present in old messages so we can detect
        # orphaned tool results whose parent assistant message was already
        # compacted away (API invariant protection).
        old_tc_ids: set[str] = set()
        for msg in old_messages:
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    old_tc_ids.add(tc.get("id", ""))

        if aggressive:
            # Aggressive: only keep set_output tool pairs and error results.
            # Everything else is collapsed into a tool-call history summary.
            # We need to track tool_call IDs to pair assistant messages with
            # their tool results.
            protected_tc_ids: set[str] = set()
            collapsible_tc_ids: set[str] = set()

            # First pass: classify assistant messages
            for msg in old_messages:
                if msg.role != "assistant" or not msg.tool_calls:
                    continue
                has_protected = any(tc.get("function", {}).get("name") == "set_output" for tc in msg.tool_calls)
                tc_ids = {tc.get("id", "") for tc in msg.tool_calls}
                if has_protected:
                    protected_tc_ids |= tc_ids
                else:
                    collapsible_tc_ids |= tc_ids

            # Skill content and transition markers are always protected
            for msg in old_messages:
                if msg.role == "tool" and msg.is_skill_content and msg.tool_use_id:
                    protected_tc_ids.add(msg.tool_use_id)

            # Second pass: classify all messages
            for msg in old_messages:
                if msg.is_transition_marker:
                    # Transition markers are always kept (phase boundaries)
                    kept_structural.append(msg)
                elif msg.role == "tool":
                    tc_id = msg.tool_use_id or ""
                    if tc_id in protected_tc_ids:
                        kept_structural.append(msg)
                    elif msg.is_error:
                        # Error results are always protected
                        kept_structural.append(msg)
                        # Protect the parent assistant message too
                        protected_tc_ids.add(tc_id)
                    elif msg.is_skill_content:
                        kept_structural.append(msg)
                    elif tc_id and tc_id not in old_tc_ids:
                        # Orphaned tool result — parent tool_use not in old msgs.
                        # Keep it to maintain API invariants.
                        kept_structural.append(msg)
                    else:
                        collapsed_msgs.append(msg)
                elif msg.role == "assistant" and msg.tool_calls:
                    tc_ids = {tc.get("id", "") for tc in msg.tool_calls}
                    if tc_ids & protected_tc_ids:
                        # Has at least one protected tool call — keep entire msg
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
                                run_id=msg.run_id,
                            )
                        )
                    else:
                        collapsed_msgs.append(msg)
                else:
                    # Freeform text — save to file
                    role_label = msg.role
                    text = msg.content
                    if len(text) > 2000:
                        text = text[:2000] + "…"
                    freeform_lines.append(f"[{role_label}] (seq={msg.seq}): {text}")
        else:
            # Standard mode: keep all tool call pairs as structural
            for msg in old_messages:
                if msg.is_transition_marker:
                    # Transition markers are always kept (phase boundaries)
                    kept_structural.append(msg)
                elif msg.role == "tool":
                    kept_structural.append(msg)
                elif msg.role == "assistant" and msg.tool_calls:
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
                            run_id=msg.run_id,
                        )
                    )
                else:
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

        # Build reference message. Prose format (no brackets) — see the
        # poison-pattern note on truncate_tool_result. Frontier models
        # autocomplete `[...']` trailers into their own text turns.
        ref_parts: list[str] = []
        if conv_filename:
            full_path = str((spill_path / conv_filename).resolve())
            ref_parts.append(
                f"Previous conversation saved at: {full_path}\n"
                f"Read the full transcript with read_file('{conv_filename}')."
            )
        elif not collapsed_msgs:
            ref_parts.append("(Previous freeform messages compacted.)")

        # Aggressive: add collapsed tool-call history to the reference
        if collapsed_msgs:
            tool_history = extract_tool_call_history(collapsed_msgs)
            if tool_history:
                ref_parts.append(tool_history)
            elif not ref_parts:
                ref_parts.append("[Previous tool calls compacted.]")

        ref_content = "\n\n".join(ref_parts)

        # Use a seq just before the first kept message
        recent_messages = list(self._messages[split:])
        if kept_structural:
            ref_seq = kept_structural[0].seq - 1
        elif recent_messages:
            ref_seq = recent_messages[0].seq - 1
        else:
            ref_seq = self._next_seq
            self._next_seq += 1

        ref_msg = Message(seq=ref_seq, role="user", content=ref_content, run_id=self._run_id)

        # Persist: delete old messages from store, write reference + kept structural.
        # In aggressive mode, collapsed messages may be interspersed with kept
        # messages, so we delete everything before the recent boundary and
        # rewrite only what we want to keep.
        if self._store:
            recent_boundary = recent_messages[0].seq if recent_messages else self._next_seq
            await self._store.delete_parts_before(recent_boundary)
            # Write the reference message
            await self._store.write_part(ref_msg.seq, ref_msg.to_storage_dict())
            # Write kept structural messages (they may have been modified)
            for msg in kept_structural:
                await self._store.write_part(msg.seq, msg.to_storage_dict())
            await self._write_next_seq()

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
            await self._write_next_seq()
        self._messages.clear()
        self._last_api_input_tokens = None

    def export_summary(self) -> str:
        """Structured summary with [STATS], [CONFIG], [RECENT_MESSAGES] sections."""
        prompt_preview = self._system_prompt[:80] + "..." if len(self._system_prompt) > 80 else self._system_prompt

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
        await self._write_next_seq()
        # Any partial checkpoint for this seq is now superseded by the real
        # part — clear it so a future restore doesn't resurrect stale text.
        try:
            await self._store.clear_partial(message.seq)
        except AttributeError:
            # Older stores may not implement partials; ignore.
            pass

    async def checkpoint_partial_assistant(
        self,
        accumulated_text: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Write an in-flight assistant turn's state to disk under the next seq.

        Called from the stream event loop. Safe to call repeatedly — each call
        overwrites the prior checkpoint. Persisted via ``write_partial`` so it
        does NOT appear in ``read_parts()`` and cannot be double-loaded. Cleared
        automatically when ``add_assistant_message`` for this seq lands.
        """
        if self._store is None:
            return
        if not self._meta_persisted:
            await self._persist_meta()
        payload: dict[str, Any] = {
            "seq": self._next_seq,
            "role": "assistant",
            "content": accumulated_text,
            "phase_id": self._current_phase,
            "run_id": self._run_id,
            "truncated": True,
        }
        if tool_calls:
            payload["tool_calls"] = tool_calls
        try:
            await self._store.write_partial(self._next_seq, payload)
        except AttributeError:
            # Older stores may not implement partials; ignore.
            pass

    async def _persist_meta(self) -> None:
        """Lazily write conversation metadata to the store (called once).

        When ``self._run_id`` is set, metadata is written flat for backward
        compatibility (run-scoped isolation has been reverted).
        """
        if self._store is None:
            return
        run_meta = {
            "system_prompt": self._system_prompt,
            "max_context_tokens": self._max_context_tokens,
            "compaction_threshold": self._compaction_threshold,
            "compaction_buffer_tokens": self._compaction_buffer_tokens,
            "compaction_warning_buffer_tokens": (self._compaction_warning_buffer_tokens),
            "output_keys": self._output_keys,
        }
        await self._store.write_meta(run_meta)
        self._meta_persisted = True

    async def _write_next_seq(self) -> None:
        if self._store is None:
            return
        cursor = await self._store.read_cursor() or {}
        cursor["next_seq"] = self._next_seq
        await self._store.write_cursor(cursor)

    # --- Restore -----------------------------------------------------------

    @classmethod
    async def restore(
        cls,
        store: ConversationStore,
        phase_id: str | None = None,
        run_id: str | None = None,
    ) -> NodeConversation | None:
        """Reconstruct a NodeConversation from a store.

        Args:
            store: The conversation store to read from.
            phase_id: If set, only load parts matching this phase_id.
                Used in isolated mode so a node only sees its own
                messages in the shared flat store.  In continuous mode
                pass ``None`` to load all parts.
            run_id: If set, only load parts matching this run_id.
                Ensures intentional restarts (new run_id) start fresh
                while crash recovery (same run_id) resumes correctly.

        Returns ``None`` if the store contains no metadata (i.e. the
        conversation was never persisted).
        """
        meta = await store.read_meta()
        if meta is None:
            return None

        conv = cls(
            system_prompt=meta.get("system_prompt", ""),
            max_context_tokens=meta.get("max_context_tokens", 32000),
            compaction_threshold=meta.get("compaction_threshold", 0.8),
            output_keys=meta.get("output_keys"),
            store=store,
            run_id=run_id,
            compaction_buffer_tokens=meta.get("compaction_buffer_tokens"),
            compaction_warning_buffer_tokens=meta.get("compaction_warning_buffer_tokens"),
        )
        conv._meta_persisted = True

        parts = await store.read_parts()
        if phase_id:
            filtered_parts = [p for p in parts if p.get("phase_id") == phase_id]
            if filtered_parts:
                parts = filtered_parts
            elif parts and all(p.get("phase_id") is None for p in parts):
                # Backward compatibility: older isolated stores (including queen
                # sessions) persisted parts without phase_id. In that case, the
                # phase filter would incorrectly hide the entire conversation.
                logger.info(
                    "Restoring legacy unphased conversation without applying phase filter (phase_id=%s, parts=%d)",
                    phase_id,
                    len(parts),
                )
            else:
                parts = filtered_parts
        # Filter by run_id so intentional restarts (new run_id) start fresh
        # while crash recovery (same run_id) loads prior parts.
        if run_id and not is_legacy_run_id(run_id):
            parts = [p for p in parts if p.get("run_id") == run_id]
        conv._messages = [Message.from_storage_dict(p) for p in parts]

        cursor = await store.read_cursor()
        next_seq = get_cursor_next_seq(cursor)
        if next_seq is not None:
            conv._next_seq = next_seq
        elif conv._messages:
            conv._next_seq = conv._messages[-1].seq + 1

        # Surface any leftover partial checkpoints as truncated messages so
        # the next turn sees what the interrupted stream was in the middle
        # of producing. Only partials whose seq is >= next_seq are meaningful;
        # anything lower was already superseded by a real part.
        try:
            partials = await store.read_all_partials()
        except AttributeError:
            partials = []
        for p in partials:
            pseq = p.get("seq", -1)
            if pseq < conv._next_seq:
                # Stale — clean it up.
                try:
                    await store.clear_partial(pseq)
                except AttributeError:
                    pass
                continue
            # Only resurrect partials relevant to this run / phase.
            if run_id and not is_legacy_run_id(run_id) and p.get("run_id") != run_id:
                continue
            if phase_id and p.get("phase_id") is not None and p.get("phase_id") != phase_id:
                continue
            # Reconstruct as a truncated assistant message.
            msg = Message(
                seq=pseq,
                role="assistant",
                content=p.get("content", "") or "",
                tool_calls=p.get("tool_calls"),
                phase_id=p.get("phase_id"),
                run_id=p.get("run_id"),
                truncated=True,
            )
            conv._messages.append(msg)
            conv._next_seq = max(conv._next_seq, pseq + 1)
            logger.info(
                "restore: resurrected truncated partial seq=%d (text=%d chars, tool_calls=%d)",
                pseq,
                len(msg.content),
                len(msg.tool_calls or []),
            )

        return conv
