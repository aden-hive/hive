"""NodeConversation: Message history management for graph nodes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
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
        )


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

    # --- Properties --------------------------------------------------------

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

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

    async def add_user_message(self, content: str) -> Message:
        msg = Message(seq=self._next_seq, role="user", content=content)
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
        )
        self._messages.append(msg)
        self._next_seq += 1
        await self._persist(msg)
        return msg

    # --- Query -------------------------------------------------------------

    def to_llm_messages(self) -> list[dict[str, Any]]:
        """Return messages as OpenAI-format dicts (system prompt excluded)."""
        return [m.to_llm_dict() for m in self._messages]

    def estimate_tokens(self) -> int:
        """Rough token estimate: total characters / 4."""
        total_chars = sum(len(m.content) for m in self._messages)
        return total_chars // 4

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
        match = re.search(rf'\b{re.escape(key)}\s*:\s*(.+)', content)
        if match:
            return match.group(1).strip()

        # 4. Equals format: key = value
        match = re.search(rf'\b{re.escape(key)}\s*=\s*(.+)', content)
        if match:
            return match.group(1).strip()

        return None

    # --- Lifecycle ---------------------------------------------------------

    async def compact(self, summary: str, keep_recent: int = 2) -> None:
        """Replace old messages with a summary, optionally keeping recent ones.

        Args:
            summary: Caller-provided summary text.
            keep_recent: Number of recent messages to preserve (default 2).
                         Clamped to [0, len(messages) - 1].
        """
        if not self._messages:
            return

        # Clamp: must discard at least 1 message
        keep_recent = max(0, min(keep_recent, len(self._messages) - 1))

        if keep_recent > 0:
            old_messages = self._messages[:-keep_recent]
            recent_messages = self._messages[-keep_recent:]
        else:
            old_messages = self._messages
            recent_messages = []

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

    async def clear(self) -> None:
        """Remove all messages, keep system prompt, preserve ``_next_seq``."""
        if self._store:
            await self._store.delete_parts_before(self._next_seq)
            await self._store.write_cursor({"next_seq": self._next_seq})
        self._messages.clear()

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
    async def restore(cls, store: ConversationStore) -> NodeConversation | None:
        """Reconstruct a NodeConversation from a store.

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
        conv._messages = [Message.from_storage_dict(p) for p in parts]

        cursor = await store.read_cursor()
        if cursor:
            conv._next_seq = cursor["next_seq"]
        elif conv._messages:
            conv._next_seq = conv._messages[-1].seq + 1

        return conv
