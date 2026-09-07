"""NodeConversation: Message history management for graph nodes."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from framework.llm.capabilities import supports_images_in_tool_results

LEGACY_RUN_ID = "__legacy_run__"
logger = logging.getLogger(__name__)


def is_legacy_run_id(run_id: str | None) -> bool:
    """True when run_id represents pre-migration (no run boundary) data."""
    return run_id is None or run_id == LEGACY_RUN_ID


def _collect_attach_file_chip_urls(messages: list[Any]) -> list[dict[str, Any]]:
    """Scan the current turn's ``tool``-role messages for ``attach_file``
    results that include ``hive_attachment_url`` entries. Returns
    image_url-shaped dicts ready to live on the next assistant message's
    ``images`` field, in chronological order.

    "Current turn" = the messages after the most recent ``assistant``
    message. Tool results from earlier turns are not promoted (they
    already got attached to their own assistant message when it was
    persisted).
    """
    # Find the boundary: index just after the last assistant message.
    boundary = 0
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "role", None) == "assistant":
            boundary = i + 1
            break
    images: list[dict[str, Any]] = []
    for m in messages[boundary:]:
        if getattr(m, "role", None) != "tool":
            continue
        content = getattr(m, "content", "") or ""
        # Cheap pre-filter — most tool results aren't attach_file summaries.
        if "hive_attachment_url" not in content or '"attached"' not in content:
            continue
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        attached = data.get("attached")
        if not isinstance(attached, list):
            continue
        for entry in attached:
            if not isinstance(entry, dict):
                continue
            url = entry.get("hive_attachment_url")
            filename = entry.get("filename")
            if not isinstance(url, str) or not url:
                continue
            images.append(
                {
                    "type": "image_url",
                    "image_url": {"url": url},
                    "filename": filename if isinstance(filename, str) else None,
                }
            )
    return images


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
    # Optional image content blocks (e.g. from a hive-browser screenshot)
    image_content: list[dict[str, Any]] | None = None
    # True when message contains an activated skill body (AS-10: never prune)
    is_skill_content: bool = False
    # Logical worker run identifier for shared-session persistence
    run_id: str | None = None
    # True when this is a framework-injected system reminder (idle nudge,
    # stream-stall continuation hint, …). Stored as a user message for API
    # compatibility, but the UI should render it as a compact system notice,
    # not user speech.
    is_system_reminder: bool = False
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
    # Reasoning/`thinking` content blocks the model produced on this
    # assistant turn (DeepSeek, GLM via the hive-2.1 alias, Anthropic
    # extended thinking). Stored verbatim — including each block's opaque
    # `signature` — and echoed back on every follow-up request. Reasoning
    # models reject the next request with a 400 if a prior assistant turn
    # is missing them. None for non-reasoning models and non-assistant
    # roles.
    thinking_blocks: list[dict[str, Any]] | None = None
    # Optional chip-renderable attachments to surface on this message in
    # the UI. Same shape user messages use for their uploaded files — a
    # list of ``{"type": "image_url", "image_url": {"url": "hive-attachment://..."}, "filename": "..."}`` entries.
    # Populated for assistant messages by `add_assistant_message` when
    # the preceding turn called `attach_file` and the tool result included
    # ``hive_attachment_url`` entries. Renderer uses this directly. Does
    # NOT round-trip through ``to_llm_dict`` — purely UI sidecar.
    images: list[dict[str, Any]] | None = None
    # Absolute path to the on-disk spill file holding this tool result's full
    # content (set for compactable results whenever a spillover dir is
    # configured). Out-of-band metadata — deliberately NOT emitted by
    # ``to_llm_dict`` so the model never sees it on a fresh result (poison
    # pattern). Compaction (microcompact / prune) reads it so a cleared result
    # can always cite a recovery path, even when the result was small enough to
    # be inlined without an in-message ``Full result at:`` pointer.
    spillover_path: str | None = None

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
            # Echo reasoning blocks back verbatim. litellm's Anthropic
            # request transform reads ``thinking_blocks`` off the assistant
            # message and re-emits them as `thinking` content blocks (in
            # order, before text/tool_use). Omitting them 400s reasoning
            # models — see Message.thinking_blocks.
            if self.thinking_blocks:
                d["thinking_blocks"] = self.thinking_blocks
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
        if self.is_system_reminder:
            d["is_system_reminder"] = self.is_system_reminder
        if self.truncated:
            d["truncated"] = self.truncated
        if self.inherited_from is not None:
            d["inherited_from"] = self.inherited_from
        if self.is_trigger:
            d["is_trigger"] = self.is_trigger
        if self.thinking_blocks is not None:
            d["thinking_blocks"] = self.thinking_blocks
        if self.images is not None:
            d["images"] = self.images
        if self.spillover_path is not None:
            d["spillover_path"] = self.spillover_path
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
            is_system_reminder=data.get("is_system_reminder", data.get("is_system_nudge", False)),
            truncated=data.get("truncated", False),
            inherited_from=data.get("inherited_from"),
            is_trigger=data.get("is_trigger", False),
            thinking_blocks=data.get("thinking_blocks"),
            images=data.get("images"),
            spillover_path=data.get("spillover_path"),
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

    Matches every header format ``truncate_tool_result`` and microcompact
    have ever emitted — missing one silently drops the pointer to the
    spilled file when the message is pruned, stranding the only surviving
    copy of the tool result:
        - Current large-result header: "Full result at: /abs/path/file.txt"
        - Microcompact placeholder: "Old tool result (N chars) at /abs/path"
        - Older prose: "Full result saved at: /abs/path/file.txt"
        - Legacy bracketed trailer: "[Saved to 'file.txt']" (pre-2026-04-15)
    """
    match = re.search(r"[Ff]ull result at:\s*(\S+)", content)
    if match:
        return match.group(1).rstrip(".,;:")
    match = re.search(r"\)\s+at\s+(/\S+)", content)
    if match:
        return match.group(1).rstrip(".,;:")
    match = re.search(r"[Ss]aved at:\s*(\S+)", content)
    if match:
        return match.group(1).rstrip(".,;:")
    # Legacy format.
    match = re.search(r"[Ss]aved to '([^']+)'", content)
    return match.group(1) if match else None


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
        if name == "terminal_exec":
            return args.get("command", "")
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

    # Class-level default so ``__new__`` bypass paths (used by some tests
    # and the legacy restore-from-storage flow) still resolve the flag.
    # ``__init__`` overrides this with an instance-level attribute.
    _microcompact_inflight: bool = False

    def __init__(
        self,
        system_prompt: str = "",
        max_context_tokens: int = 180_000,
        compaction_threshold: float = 0.8,
        output_keys: list[str] | None = None,
        store: ConversationStore | None = None,
        run_id: str | None = None,
        compaction_buffer_tokens: int | None = None,
        compaction_buffer_ratio: float | None = None,
        compaction_warning_buffer_tokens: int | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        # Optional split: when a caller updates the prompt with a
        # ``dynamic_suffix`` argument, we remember the static prefix and
        # suffix separately so the LLM wrapper can emit them as two
        # Anthropic system content blocks with a cache breakpoint between
        # them. ``_system_prompt`` stays as the concatenated form used for
        # persistence and for the legacy single-block LLM path.
        # On restore, these default to the concat/empty pair — the next
        # AgentLoop iteration's dynamic-prompt refresh step repopulates.
        self._system_prompt_static: str = system_prompt
        self._system_prompt_dynamic_suffix: str = ""
        self._max_context_tokens = max_context_tokens
        self._compaction_threshold = compaction_threshold
        # Buffer-based compaction trigger (Gap 7). When set, takes
        # precedence over the multiplicative compaction_threshold so the
        # loop reserves a fixed headroom for the next turn's input+output
        # instead of trying to get exactly X% of the way to the hard
        # limit. If left as None the legacy threshold-based rule is
        # used, keeping old call sites behaving identically.
        self._compaction_buffer_tokens = compaction_buffer_tokens
        # Ratio component of the hybrid buffer. Combines additively with
        # _compaction_buffer_tokens so callers can express "reserve N tokens
        # plus M% of the window" — the absolute floor matters on tiny
        # windows, the ratio matters on large ones.
        self._compaction_buffer_ratio = compaction_buffer_ratio
        self._compaction_warning_buffer_tokens = compaction_warning_buffer_tokens
        self._output_keys = output_keys
        self._store = store
        self._messages: list[Message] = []
        self._next_seq: int = 0
        self._meta_persisted: bool = False
        self._last_api_input_tokens: int | None = None
        self._current_phase: str | None = None
        self._run_id: str | None = run_id
        # Re-entrancy guard for proactive microcompaction triggered from
        # add_tool_result. microcompact() itself mutates _messages, and
        # while it doesn't currently call back into add_tool_result, the
        # guard keeps future refactors from looping.
        self._microcompact_inflight: bool = False

    # --- Properties --------------------------------------------------------

    @property
    def system_prompt(self) -> str:
        """Full concatenated system prompt (static + dynamic suffix, if any).

        This is the canonical form used for persistence and for the legacy
        single-block LLM path. Split-prompt callers should read
        ``system_prompt_static`` and ``system_prompt_dynamic_suffix`` instead.
        """
        return self._system_prompt

    @property
    def system_prompt_static(self) -> str:
        """Static prefix of the system prompt (cache-stable).

        Equals ``system_prompt`` when no split is in use. When the AgentLoop
        calls ``update_system_prompt(static, dynamic_suffix=...)``, this is
        the piece sent as the cache-controlled first block.
        """
        return self._system_prompt_static

    @property
    def system_prompt_dynamic_suffix(self) -> str:
        """Dynamic tail of the system prompt (not cached).

        Empty unless the consumer splits its prompt. The LLM wrapper uses a
        non-empty suffix to emit a two-block system content list with a
        cache breakpoint between the static prefix and this tail.
        """
        return self._system_prompt_dynamic_suffix

    def update_system_prompt(self, new_prompt: str, dynamic_suffix: str | None = None) -> None:
        """Update the system prompt.

        Used in continuous conversation mode at phase transitions to swap
        Layer 3 (focus) while preserving the conversation history.

        When ``dynamic_suffix`` is provided, ``new_prompt`` is interpreted as
        the STATIC prefix and ``dynamic_suffix`` as the per-turn tail; they
        travel to the LLM as two separate cache-controlled blocks but are
        persisted as a single concatenated string for backward-compat
        restore. ``new_prompt`` alone (suffix left None) keeps the legacy
        single-string behavior.
        """
        if dynamic_suffix is None:
            # Legacy single-string path — static == full, no suffix split.
            self._system_prompt = new_prompt
            self._system_prompt_static = new_prompt
            self._system_prompt_dynamic_suffix = ""
        else:
            self._system_prompt_static = new_prompt
            self._system_prompt_dynamic_suffix = dynamic_suffix
            self._system_prompt = f"{new_prompt}\n\n{dynamic_suffix}" if dynamic_suffix else new_prompt
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
        is_system_reminder: bool = False,
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
            is_system_reminder=is_system_reminder,
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
        thinking_blocks: list[dict[str, Any]] | None = None,
    ) -> Message:
        # Collect any chip attachments published by attach_file during
        # the run of tools that fed into this assistant turn. We walk
        # back from the end, stopping at the previous assistant message
        # (the boundary of the current turn's tool sequence).
        images = _collect_attach_file_chip_urls(self._messages)
        msg = Message(
            seq=self._next_seq,
            role="assistant",
            content=content,
            tool_calls=tool_calls,
            phase_id=self._current_phase,
            run_id=self._run_id,
            truncated=truncated,
            thinking_blocks=thinking_blocks or None,
            images=images or None,
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
        spillover_path: str | None = None,
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
                    "add_tool_result: dropping duplicate result for tool_use_id=%s (first result preserved, %d chars; new result ignored, %d chars)",
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
            spillover_path=spillover_path,
        )
        self._messages.append(msg)
        self._next_seq += 1
        self._last_api_input_tokens = None
        await self._persist(msg)
        # Proactive microcompaction: when a fresh result lands and the
        # conversation now has more than ``MICROCOMPACT_KEEP_RECENT``
        # compactable results pending, clear the oldest ones immediately
        # rather than waiting until usage_ratio crosses the compaction
        # threshold (~80%). This is cheap (pure Python, no LLM call)
        # and only mutates older compactable results — placeholders
        # already include the spillover path so the agent can re-read.
        # Guarded by ``_microcompact_inflight`` to avoid recursion.
        if not is_error and not is_skill_content and not self._microcompact_inflight:
            self._microcompact_inflight = True
            try:
                from framework.agent_loop.internals.compaction import (
                    COMPACTABLE_TOOLS,
                    microcompact,
                )

                tool_name = self._find_tool_name_for_use_id(tool_use_id)
                if tool_name and tool_name in COMPACTABLE_TOOLS:
                    microcompact(self)
            except Exception:
                # Microcompaction is best-effort. A failure here must
                # not lose the tool result we just persisted.
                logger.debug(
                    "Proactive microcompact failed for tool_use_id=%s",
                    tool_use_id,
                    exc_info=True,
                )
            finally:
                self._microcompact_inflight = False
        return msg

    def _find_tool_name_for_use_id(self, tool_use_id: str) -> str | None:
        """Look up the assistant tool call that produced ``tool_use_id``.

        Walks the message list backwards; returns the function name from
        the matching ``tool_calls`` entry or None when no match is found
        (e.g. the assistant message was already compacted out).
        """
        for msg in reversed(self._messages):
            if not msg.tool_calls:
                continue
            for tc in msg.tool_calls:
                if tc.get("id") == tool_use_id:
                    return tc.get("function", {}).get("name")
        return None

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
        still execute, so calls like a hive-browser screenshot that are
        legitimately repeated are not silently skipped.
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

    def count_consecutive_completed_tool_calls(
        self,
        name: str,
        tool_input: dict[str, Any],
        within_last_turns: int = 3,
        *,
        skip_most_recent_assistant: bool = False,
    ) -> int:
        """Walk backwards over recent assistant turns; count how many
        consecutive turns issued a non-error tool call matching
        ``(name, canonical-args)``. A turn that does NOT include a
        matching call breaks the streak.

        Used by the hard-breaker variant of the replay detector — when
        the count reaches the doom-loop threshold, the next identical
        call is refused instead of nudged.

        ``skip_most_recent_assistant=True`` ignores the most recent
        assistant turn. The breaker call site needs this: by the time
        it runs in Phase 1 of ``_handle_pending_tools``, the in-flight
        assistant message has already been written but its tool
        results have not, so a naive walk-back would mistake the
        in-flight turn for a streak-break.
        """
        try:
            target_canonical = json.dumps(tool_input, sort_keys=True, default=str)
        except (TypeError, ValueError):
            target_canonical = str(tool_input)

        streak = 0
        assistant_turns_seen = 0
        skipped_in_flight = not skip_most_recent_assistant
        for idx in range(len(self._messages) - 1, -1, -1):
            m = self._messages[idx]
            if m.role != "assistant":
                continue
            if not skipped_in_flight:
                # Skip the most recent assistant message — its tool
                # results are still being produced by the caller.
                skipped_in_flight = True
                continue
            assistant_turns_seen += 1
            if assistant_turns_seen > within_last_turns:
                break
            if not m.tool_calls:
                # Text-only turn breaks the streak.
                break
            matched_in_turn = False
            for tc in m.tool_calls:
                func = tc.get("function", {}) if isinstance(tc, dict) else {}
                if func.get("name") != name:
                    continue
                args_str = func.get("arguments", "")
                try:
                    parsed = json.loads(args_str) if isinstance(args_str, str) else args_str
                    canonical = json.dumps(parsed, sort_keys=True, default=str)
                except (TypeError, ValueError):
                    canonical = str(args_str)
                if canonical != target_canonical:
                    continue
                tc_id = tc.get("id")
                for later in self._messages[idx + 1 :]:
                    if later.role == "tool" and later.tool_use_id == tc_id:
                        if not later.is_error:
                            matched_in_turn = True
                        break
                if matched_in_turn:
                    break
            if not matched_in_turn:
                break
            streak += 1
        return streak

    def to_llm_messages(self, model: str | None = None) -> list[dict[str, Any]]:
        """Return messages as OpenAI-format dicts (system prompt excluded).

        Automatically repairs orphaned tool_use blocks (assistant messages
        with tool_calls that lack corresponding tool-result messages).  This
        can happen when a loop is cancelled mid-tool-execution.

        *model* selects the image-delivery shape. Anthropic carries images
        inside a tool result; everywhere else they must be hoisted into a
        following user message or the model never sees them
        (``_hoist_tool_result_images``). Omitting *model* keeps the
        images where they are — pass it whenever the provider is known.
        """
        msgs = [m.to_llm_dict() for m in self._messages]
        msgs = self._repair_orphaned_tool_calls(msgs)
        if not supports_images_in_tool_results(model or ""):
            msgs = self._hoist_tool_result_images(msgs)
        msgs = self._sanitize_for_api(msgs)
        return msgs

    @staticmethod
    def _hoist_tool_result_images(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Move image blocks out of tool messages into a following user message.

        Only Anthropic's ``tool_result`` can hold an image. On every other
        API the image blocks we put in a ``tool`` message are dropped in
        transit without an error, so the agent takes a screenshot, gets
        back a result that describes an image it cannot see, and concludes
        its own eyes are broken.

        The images survive as a synthetic ``user`` message appended after
        the tool run, which every vision-capable API accepts. Placement is
        after the *whole* contiguous run of tool messages, never between
        two of them: a parallel tool batch must deliver all of its results
        before any other role appears, or the API rejects the request.

        The tool message keeps its text — only the non-text blocks move.
        Purely a request-shaping step: the stored ``Message.image_content``
        is untouched, so eviction, persistence and the UI are unaffected.
        """
        # tool_call_id -> tool name, so the hoisted message can say which
        # call each image came from.
        names_by_id: dict[str, str] = {}
        for m in msgs:
            if m.get("role") != "assistant":
                continue
            for tc in m.get("tool_calls") or []:
                tc_id = tc.get("id")
                name = (tc.get("function") or {}).get("name")
                if tc_id and name:
                    names_by_id[tc_id] = name

        out: list[dict[str, Any]] = []
        # (tool name, image blocks) for the tool run being walked.
        pending: list[tuple[str, list[dict[str, Any]]]] = []

        def _flush() -> None:
            if not pending:
                return
            labels = ", ".join(f"{name} ({len(imgs)})" for name, imgs in pending)
            hoisted: list[dict[str, Any]] = [
                {
                    "type": "text",
                    "text": (
                        f"[Image output of the tool call(s) above — {labels}. "
                        "Delivered here because this model's API cannot carry "
                        "images inside a tool result.]"
                    ),
                }
            ]
            for _, images in pending:
                hoisted.extend(images)
            out.append({"role": "user", "content": hoisted})
            pending.clear()

        for m in msgs:
            if m.get("role") != "tool":
                _flush()
                out.append(m)
                continue

            content = m.get("content")
            if not isinstance(content, list):
                out.append(m)
                continue

            text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
            image_blocks = [b for b in content if isinstance(b, dict) and b.get("type") != "text"]
            if not image_blocks:
                out.append(m)
                continue

            stripped = dict(m)
            # Collapse back to the plain string a text-only tool result
            # would have carried, so the payload matches the no-image shape.
            stripped["content"] = "\n".join(b.get("text") or "" for b in text_blocks)
            out.append(stripped)
            pending.append((names_by_id.get(m.get("tool_call_id") or "", "tool"), image_blocks))

        _flush()
        return out

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

                # Mixed content types (one has image blocks as a list,
                # the other is a plain string).  Normalise both sides to
                # content-block lists and concatenate so the API never
                # sees two consecutive user messages.
                def _to_blocks(c: Any) -> list[dict[str, Any]]:
                    if isinstance(c, list):
                        return list(c)
                    return [{"type": "text", "text": c}] if c else []

                cleaned[-1]["content"] = _to_blocks(prev_content) + _to_blocks(curr_content)
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
           from its parent by a non-tool message, e.g. an async user
           injection like a worker report) are hoisted to immediately
           follow the assistant message that issued the matching
           tool_call — the position the Anthropic API requires.  A real
           result must never be masked by a synthetic error: the model
           would retry calls that already succeeded.
        3. **Duplicate tool results** (same tool_call_id appearing more
           than once) are dropped; only the first is kept.
        4. **Orphaned tool calls** (tool_use with no tool_result anywhere)
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
        # dict (insertion-ordered) so hoisted/stubbed results keep the
        # order the tool_calls were issued in.
        open_tool_calls: dict[str, None] = {}
        seen_tool_ids: set[str] = set()
        for i, m in enumerate(msgs):
            role = m.get("role")

            if role == "tool":
                tid = m.get("tool_call_id")
                # Drop tool results with no matching tool_use anywhere.
                if not tid or tid not in all_tool_call_ids:
                    continue
                # Drop duplicates (same id appearing twice) — keep first.
                # Also drops the original position of results hoisted
                # next to their tool_call below.
                if tid in seen_tool_ids:
                    continue
                # Drop positional orphans — tool messages whose parent
                # assistant isn't the still-open assistant block.
                if tid not in open_tool_calls:
                    continue
                open_tool_calls.pop(tid, None)
                seen_tool_ids.add(tid)
                repaired.append(m)
                continue

            # Any non-tool message closes the current assistant tool block.
            # Async events (worker reports, user injections) can land
            # between a tool_call and its result, so the real result may
            # still exist later in the stream: hoist it up to directly
            # follow its tool_call rather than masking a completed call
            # with a synthetic "interrupted" error (which made the model
            # retry writes that had already succeeded).  Only when no
            # result exists anywhere is a synthetic stub patched in.
            if open_tool_calls:
                for stale_id in list(open_tool_calls):
                    real_result = next(
                        (later for later in msgs[i:] if later.get("role") == "tool" and later.get("tool_call_id") == stale_id),
                        None,
                    )
                    repaired.append(
                        real_result
                        if real_result is not None
                        else {
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
                        open_tool_calls[tc_id] = None

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

    def conversation_chars_and_images(self) -> tuple[int, int]:
        """Return (content+args chars, image_block_count) for the conversation only.

        Counts message content, tool_call arguments, and function names from
        the current ``_messages`` list. Does NOT include the system prompt or
        tool definitions — callers add those externally. Used by the
        context-usage telemetry to combine with system+tools sizes for a
        real-time "what will the next prompt cost" estimate.
        """
        total_chars = 0
        image_blocks = 0
        for m in self._messages:
            total_chars += len(m.content)
            if m.tool_calls:
                for tc in m.tool_calls:
                    func = tc.get("function", {})
                    total_chars += len(func.get("arguments", ""))
                    total_chars += len(func.get("name", ""))
            if m.image_content:
                image_blocks += len(m.image_content)
        return total_chars, image_blocks

    def estimate_tokens(self) -> int:
        """Best available token estimate (conversation messages only).

        Uses the actual API input token count from the most recent LLM call
        when available (set via :meth:`update_token_count`); otherwise falls
        back to a character-based heuristic with a 4/3 safety margin.

        This estimate covers only the conversation messages — it does NOT
        include the system prompt or tool definitions. Compaction triggers
        use this value. The real-time UI telemetry (``publish_context_usage``)
        builds a fuller estimate that includes system+tools on top.
        """
        if self._last_api_input_tokens is not None:
            return self._last_api_input_tokens
        total_chars, image_blocks = self.conversation_chars_and_images()
        image_tokens = image_blocks * 2000
        # Apply 4/3 safety margin to character-based estimate
        return (total_chars * 4) // (3 * 4) + image_tokens

    def update_token_count(self, actual_input_tokens: int) -> None:
        """Store the actual size of the most recent single LLM request.

        Called immediately after each FinishEvent with that event's
        ``input_tokens`` (the prompt size the provider counted for that
        one call). This value includes the system prompt and tool
        definitions, so it may be higher than the message-only
        char-based estimate — that's intentional.

        DO NOT pass a cumulative sum across multiple LLM calls here.
        ``max_context_tokens`` is a single-prompt budget, and
        ``usage_ratio()`` divides this field by it; feeding in a
        billing sum would make ``usage_ratio()`` compare billing to a
        request budget and report fictional 1000%+ ratios for turns
        that fan out into many inner LLM calls.
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

        Hybrid buffer rule: the headroom reserved before compaction fires
        is the SUM of an absolute fixed component and a ratio of the hard
        context limit:

            effective_buffer = compaction_buffer_tokens
                             + compaction_buffer_ratio * max_context_tokens

        The fixed component gives a floor on tiny windows; the ratio
        keeps the trigger meaningful on large windows where any constant
        buffer becomes a rounding error (an 8k buffer is 75% on a 32k
        window but 96% on a 200k window). Compaction fires when the
        current estimate would consume more than (limit - effective_buffer).

        When neither component is configured, falls back to the legacy
        multiplicative threshold so old callers keep behaving identically.
        """
        if self._max_context_tokens <= 0:
            return False
        fixed = self._compaction_buffer_tokens
        ratio = self._compaction_buffer_ratio
        if fixed is not None or ratio is not None:
            effective_buffer = (fixed or 0) + (ratio or 0.0) * self._max_context_tokens
            budget = self._max_context_tokens - effective_buffer
            return self.estimate_tokens() >= max(0.0, budget)
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
            # Recoverability invariant: only prune a result we can point back to
            # — the out-of-band spill path recorded when it landed, or a path
            # embedded in its text. A result with no recovery path is KEPT in
            # full (never stranded as an unrecoverable placeholder); it counts
            # toward the protect budget like any retained result but is never
            # added to pruneable.
            recoverable = bool(msg.spillover_path or _extract_spillover_filename(msg.content))
            if protected_tokens < protect_tokens or not recoverable:
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
            # Guaranteed non-None by the eligibility invariant above.
            spillover = msg.spillover_path or _extract_spillover_filename(msg.content)
            placeholder = (
                f"Pruned tool result ({orig_len:,} chars) cleared from context. "
                f"Full data saved at: {spillover}\n"
                f'Read the complete data with terminal_exec("cat {spillover}").'
            )

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
                spillover_path=msg.spillover_path,
            )
            count += 1

            if self._store:
                await self._store.write_part(msg.seq, self._messages[i].to_storage_dict())

        # Reset token estimate — content lengths changed
        self._last_api_input_tokens = None
        return count

    async def evict_old_images(self, keep_latest: int = 2) -> int:
        """Strip ``image_content`` from older messages, keeping the most recent.

        Screenshots from ``hive-browser screenshot`` are inlined into the
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
        max_verbatim_client: int | None = None,
    ) -> None:
        """Replace old messages with a summary, optionally keeping recent ones.

        Args:
            summary: Caller-provided summary text.
            keep_recent: Number of recent messages to preserve (default 2).
                         Clamped to [0, len(messages) - 1].
            phase_graduated: When True and messages have phase_id metadata,
                split at phase boundaries instead of using keep_recent.
                Keeps current + previous phase intact; compacts older phases.
            max_verbatim_client: Cap on how many of the MOST RECENT client-input
                messages survive compaction verbatim. None = unbounded (legacy
                1:1 behaviour). In group chat every member's message is
                is_client_input=True, so the unbounded rule preserves the entire
                group backlog forever and compaction can never shrink the window;
                capping folds older group messages into the summary instead.
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

        # Carve out real client input from the discard set. The LLM summary
        # paraphrases at best; the user's original words must survive
        # verbatim so the agent stays anchored to the original intent even
        # after many compaction cycles. Only ``is_client_input`` messages
        # qualify — synthetic framework-injected user-role messages (prior
        # compaction summaries, continuation nudges, etc.) are filtered out
        # so they don't accumulate across successive compactions.
        preserved_client_messages = [m for m in old_messages if m.role == "user" and m.is_client_input]

        # Group-chat guard: keep only the most recent N verbatim. The dropped
        # older ones already live in ``summary`` (llm_compact saw the full
        # history), so this loses no information — it just stops the group
        # backlog from being pinned in-context forever. In-order list, so the
        # tail is the most recent.
        if max_verbatim_client is not None and len(preserved_client_messages) > max_verbatim_client:
            preserved_client_messages = preserved_client_messages[-max_verbatim_client:]

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

        # If the last old message is itself a client input, its seq equals
        # summary_seq — drop it from the preserved set rather than colliding
        # on the store. Its content is still represented in the summary text.
        preserved_client_messages = [m for m in preserved_client_messages if m.seq != summary_seq]

        summary_msg = Message(seq=summary_seq, role="user", content=summary, run_id=self._run_id)

        # Persist
        if self._store:
            delete_before = recent_messages[0].seq if recent_messages else self._next_seq
            await self._store.delete_parts_before(delete_before)
            for m in preserved_client_messages:
                await self._store.write_part(m.seq, m.to_storage_dict())
            await self._store.write_part(summary_msg.seq, summary_msg.to_storage_dict())
            await self._write_next_seq()

        # Live list order matches sorted-by-seq disk order: preserved client
        # messages keep their original (lower) seqs and sit before the
        # summary; the summary takes the slot just below recent_messages[0].
        self._messages = preserved_client_messages + [summary_msg] + recent_messages
        self._last_api_input_tokens = None  # reset; next LLM call will recalibrate

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
            "compaction_buffer_ratio": self._compaction_buffer_ratio,
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
            max_context_tokens=meta.get("max_context_tokens", 180_000),
            compaction_threshold=meta.get("compaction_threshold", 0.8),
            output_keys=meta.get("output_keys"),
            store=store,
            run_id=run_id,
            compaction_buffer_tokens=meta.get("compaction_buffer_tokens"),
            compaction_buffer_ratio=meta.get("compaction_buffer_ratio"),
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
