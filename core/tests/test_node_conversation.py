"""Tests for NodeConversation, Message, ConversationStore, and FileConversationStore."""

from __future__ import annotations

from typing import Any

import pytest

from framework.graph.conversation import Message, NodeConversation
from framework.storage.conversation_store import FileConversationStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockConversationStore:
    """In-memory dict-based store for testing."""

    def __init__(self) -> None:
        self._parts: dict[int, dict] = {}
        self._meta: dict | None = None
        self._cursor: dict | None = None

    async def write_part(self, seq: int, data: dict[str, Any]) -> None:
        self._parts[seq] = data

    async def read_parts(self) -> list[dict[str, Any]]:
        return [self._parts[k] for k in sorted(self._parts)]

    async def write_meta(self, data: dict[str, Any]) -> None:
        self._meta = data

    async def read_meta(self) -> dict[str, Any] | None:
        return self._meta

    async def write_cursor(self, data: dict[str, Any]) -> None:
        self._cursor = data

    async def read_cursor(self) -> dict[str, Any] | None:
        return self._cursor

    async def delete_parts_before(self, seq: int) -> None:
        self._parts = {k: v for k, v in self._parts.items() if k >= seq}

    async def close(self) -> None:
        pass

    async def destroy(self) -> None:
        pass


SAMPLE_TOOL_CALLS = [
    {
        "id": "call_1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city":"SF"}'},
    }
]


# ===================================================================
# Message serialization
# ===================================================================


class TestMessage:
    def test_user_and_assistant_to_llm_dict(self):
        """User and assistant (no tools) produce simple role+content dicts."""
        assert Message(seq=0, role="user", content="hi").to_llm_dict() == {
            "role": "user",
            "content": "hi",
        }
        assert Message(seq=0, role="assistant", content="hello").to_llm_dict() == {
            "role": "assistant",
            "content": "hello",
        }

    def test_assistant_to_llm_dict_with_tools(self):
        m = Message(seq=0, role="assistant", content="", tool_calls=SAMPLE_TOOL_CALLS)
        d = m.to_llm_dict()
        assert d["role"] == "assistant"
        assert d["tool_calls"] == SAMPLE_TOOL_CALLS

    def test_tool_to_llm_dict(self):
        m = Message(seq=0, role="tool", content="sunny", tool_use_id="call_1")
        d = m.to_llm_dict()
        assert d == {"role": "tool", "tool_call_id": "call_1", "content": "sunny"}

    def test_tool_error_to_llm_dict(self):
        m = Message(
            seq=0, role="tool", content="not found", tool_use_id="call_1", is_error=True
        )
        d = m.to_llm_dict()
        assert d["content"] == "ERROR: not found"
        assert d["tool_call_id"] == "call_1"

    def test_storage_roundtrip(self):
        m = Message(seq=5, role="assistant", content="ok", tool_calls=SAMPLE_TOOL_CALLS)
        restored = Message.from_storage_dict(m.to_storage_dict())
        assert restored.seq == m.seq
        assert restored.role == m.role
        assert restored.content == m.content
        assert restored.tool_calls == m.tool_calls

    def test_storage_dict_edge_cases(self):
        """is_error is preserved; None/False fields are omitted."""
        m = Message(seq=1, role="tool", content="fail", tool_use_id="c1", is_error=True)
        d = m.to_storage_dict()
        assert d["is_error"] is True
        assert Message.from_storage_dict(d).is_error is True

        d2 = Message(seq=0, role="user", content="hi").to_storage_dict()
        assert "tool_use_id" not in d2
        assert "tool_calls" not in d2
        assert "is_error" not in d2


# ===================================================================
# NodeConversation (in-memory)
# ===================================================================


class TestNodeConversation:
    @pytest.mark.asyncio
    async def test_multi_turn_build_and_export(self):
        conv = NodeConversation(system_prompt="You are helpful.")
        await conv.add_user_message("hello")
        await conv.add_assistant_message("hi there")
        await conv.add_user_message("weather?")
        await conv.add_assistant_message("", tool_calls=SAMPLE_TOOL_CALLS)
        await conv.add_tool_result("call_1", "sunny")
        await conv.add_assistant_message("It's sunny!")

        assert conv.turn_count == 2
        assert conv.message_count == 6
        llm = conv.to_llm_messages()
        assert len(llm) == 6
        assert llm[0]["role"] == "user"
        assert llm[3]["tool_calls"] == SAMPLE_TOOL_CALLS

        summary = conv.export_summary()
        assert "turns: 2" in summary
        assert "messages: 6" in summary

    @pytest.mark.asyncio
    async def test_system_prompt_excluded_from_messages(self):
        conv = NodeConversation(system_prompt="secret")
        await conv.add_user_message("hi")
        llm = conv.to_llm_messages()
        assert len(llm) == 1
        assert all("secret" not in str(m) for m in llm)

    @pytest.mark.asyncio
    async def test_turn_and_seq_counting(self):
        """turn_count tracks user messages; next_seq increments on every add."""
        conv = NodeConversation()
        assert conv.turn_count == 0
        assert conv.next_seq == 0
        await conv.add_user_message("a")
        assert conv.turn_count == 1
        assert conv.next_seq == 1
        await conv.add_assistant_message("b")
        assert conv.turn_count == 1
        assert conv.next_seq == 2

    @pytest.mark.asyncio
    async def test_token_estimation(self):
        conv = NodeConversation()
        await conv.add_user_message("a" * 400)
        assert conv.estimate_tokens() == 100

    @pytest.mark.asyncio
    async def test_needs_compaction(self):
        conv = NodeConversation(max_history_tokens=100, compaction_threshold=0.8)
        await conv.add_user_message("x" * 320)
        assert conv.needs_compaction() is True

    @pytest.mark.asyncio
    async def test_compact_replaces_with_summary(self):
        """keep_recent=0 replaces all messages; empty conversation is a no-op."""
        conv = NodeConversation()
        await conv.compact("summary")
        assert conv.turn_count == 0

        conv2 = NodeConversation()
        await conv2.add_user_message("one")
        await conv2.add_assistant_message("two")
        seq_before = conv2.next_seq

        await conv2.compact("summary of conversation", keep_recent=0)

        assert conv2.turn_count == 1
        assert conv2.message_count == 1
        assert conv2.messages[0].content == "summary of conversation"
        assert conv2.messages[0].role == "user"
        assert conv2.messages[0].seq == seq_before
        assert conv2.next_seq == seq_before + 1

    @pytest.mark.asyncio
    async def test_compact_keep_recent_default(self):
        """Default keep_recent=2 keeps last 2 messages."""
        conv = NodeConversation()
        await conv.add_user_message("m1")
        await conv.add_assistant_message("m2")
        await conv.add_user_message("m3")
        await conv.add_assistant_message("m4")
        await conv.add_user_message("m5")
        await conv.add_assistant_message("m6")

        await conv.compact("summary of early conversation")

        assert conv.message_count == 3
        assert conv.messages[0].content == "summary of early conversation"
        assert conv.messages[0].role == "user"
        assert conv.messages[1].content == "m5"
        assert conv.messages[2].content == "m6"

    @pytest.mark.asyncio
    async def test_compact_keep_recent_clamped(self):
        """keep_recent larger than len-1 gets clamped."""
        conv = NodeConversation()
        await conv.add_user_message("a")
        await conv.add_assistant_message("b")

        await conv.compact("summary", keep_recent=5)

        assert conv.message_count == 2
        assert conv.messages[0].content == "summary"
        assert conv.messages[1].content == "b"

    @pytest.mark.asyncio
    async def test_compact_preserves_output_keys(self):
        """PRESERVED VALUES block appears in summary when output_keys match."""
        conv = NodeConversation(output_keys=["score", "status"])
        await conv.add_user_message("process this")
        await conv.add_assistant_message("score: 87")
        await conv.add_assistant_message("status = complete")
        await conv.add_user_message("next question")

        await conv.compact("conversation summary", keep_recent=1)

        summary_content = conv.messages[0].content
        assert "PRESERVED VALUES" in summary_content
        assert "score: 87" in summary_content
        assert "status: complete" in summary_content
        assert "CONVERSATION SUMMARY:" in summary_content
        assert "conversation summary" in summary_content

    @pytest.mark.asyncio
    async def test_compact_seq_arithmetic_with_keep_recent(self):
        """Summary seq = recent[0].seq - 1 when keeping recent messages."""
        conv = NodeConversation()
        await conv.add_user_message("m1")      # seq=0
        await conv.add_assistant_message("m2")  # seq=1
        await conv.add_user_message("m3")       # seq=2
        await conv.add_assistant_message("m4")  # seq=3

        await conv.compact("summary", keep_recent=2)

        assert conv.messages[0].seq == 1  # summary
        assert conv.messages[1].seq == 2  # m3
        assert conv.messages[2].seq == 3  # m4
        assert conv.next_seq == 4

    @pytest.mark.asyncio
    async def test_clear(self):
        """Clear removes messages, keeps system prompt, preserves next_seq."""
        conv = NodeConversation(system_prompt="keep me")
        await conv.add_user_message("a")
        await conv.add_user_message("b")
        seq_before = conv.next_seq
        await conv.clear()
        assert conv.turn_count == 0
        assert conv.system_prompt == "keep me"
        assert conv.next_seq == seq_before

    @pytest.mark.asyncio
    async def test_export_summary(self):
        conv = NodeConversation(system_prompt="Be helpful")
        await conv.add_user_message("q1")
        await conv.add_assistant_message("a1")
        s = conv.export_summary()
        assert "[STATS]" in s
        assert "turns: 1" in s
        assert "messages: 2" in s
        assert "[CONFIG]" in s
        assert "Be helpful" in s
        assert "[RECENT_MESSAGES]" in s
        assert "[user]" in s
        assert "[assistant]" in s

    @pytest.mark.asyncio
    async def test_export_summary_output_keys(self):
        """output_keys appear in CONFIG when set, absent when None."""
        conv = NodeConversation(
            system_prompt="test",
            output_keys=["confirmed_meetings", "lead_score"],
        )
        await conv.add_user_message("hi")
        assert "output_keys: confirmed_meetings, lead_score" in conv.export_summary()

        conv2 = NodeConversation(system_prompt="test")
        await conv2.add_user_message("hi")
        assert "output_keys" not in conv2.export_summary()


# ===================================================================
# Output-key extraction
# ===================================================================


class TestExtractProtectedValues:
    @pytest.mark.asyncio
    async def test_extract_colon_format(self):
        conv = NodeConversation(output_keys=["score"])
        await conv.add_assistant_message("The score: 87")
        assert conv._extract_protected_values(conv.messages) == {"score": "87"}

    @pytest.mark.asyncio
    async def test_extract_json_format(self):
        conv = NodeConversation(output_keys=["meetings"])
        await conv.add_assistant_message('{"meetings": ["standup", "retro"]}')
        assert conv._extract_protected_values(conv.messages) == {
            "meetings": '["standup", "retro"]'
        }

    @pytest.mark.asyncio
    async def test_extract_equals_format(self):
        conv = NodeConversation(output_keys=["status"])
        await conv.add_assistant_message("status = done")
        assert conv._extract_protected_values(conv.messages) == {"status": "done"}

    @pytest.mark.asyncio
    async def test_extract_most_recent_wins(self):
        conv = NodeConversation(output_keys=["score"])
        await conv.add_assistant_message("score: 50")
        await conv.add_assistant_message("score: 99")
        assert conv._extract_protected_values(conv.messages) == {"score": "99"}

    @pytest.mark.asyncio
    async def test_extract_embedded_json(self):
        conv = NodeConversation(output_keys=["lead_score"])
        await conv.add_assistant_message(
            'Based on my analysis, here are the results: {"lead_score": 87, "status": "hot"}'
        )
        assert conv._extract_protected_values(conv.messages) == {"lead_score": "87"}

    @pytest.mark.asyncio
    async def test_extract_no_match_cases(self):
        """No extraction: user messages, no output_keys, key not found."""
        conv = NodeConversation(output_keys=["score"])
        await conv.add_user_message("score: 42")
        assert conv._extract_protected_values(conv.messages) == {}

        conv2 = NodeConversation(output_keys=None)
        await conv2.add_assistant_message("score: 42")
        assert conv2._extract_protected_values(conv2.messages) == {}

        conv3 = NodeConversation(output_keys=["missing_key"])
        await conv3.add_assistant_message("nothing relevant here")
        assert conv3._extract_protected_values(conv3.messages) == {}


# ===================================================================
# Persistence (MockConversationStore)
# ===================================================================


class TestPersistence:
    @pytest.mark.asyncio
    async def test_write_through_each_add(self):
        store = MockConversationStore()
        conv = NodeConversation(store=store)
        await conv.add_user_message("a")
        await conv.add_assistant_message("b")
        parts = await store.read_parts()
        assert len(parts) == 2
        assert parts[0]["content"] == "a"
        assert parts[1]["content"] == "b"

    @pytest.mark.asyncio
    async def test_meta_and_cursor_persistence(self):
        """Meta is lazily written on first add; cursor updated on each add."""
        store = MockConversationStore()
        conv = NodeConversation(system_prompt="sys", store=store)
        assert store._meta is None
        await conv.add_user_message("trigger")
        assert store._meta is not None
        assert store._meta["system_prompt"] == "sys"
        assert store._cursor == {"next_seq": 1}
        await conv.add_user_message("b")
        assert store._cursor == {"next_seq": 2}

    @pytest.mark.asyncio
    async def test_restore_from_store(self):
        """Restore reconstructs conversation; empty store returns None."""
        store = MockConversationStore()
        assert await NodeConversation.restore(store) is None

        conv = NodeConversation(system_prompt="hello", max_history_tokens=500, store=store)
        await conv.add_user_message("u1")
        await conv.add_assistant_message("a1")

        restored = await NodeConversation.restore(store)
        assert restored is not None
        assert restored.system_prompt == "hello"
        assert restored.turn_count == 1
        assert restored.message_count == 2
        assert restored.next_seq == 2
        assert restored.messages[0].content == "u1"

    @pytest.mark.asyncio
    async def test_restore_preserves_tool_messages(self):
        store = MockConversationStore()
        conv = NodeConversation(store=store)
        await conv.add_assistant_message("", tool_calls=SAMPLE_TOOL_CALLS)
        await conv.add_tool_result("call_1", "result", is_error=True)

        restored = await NodeConversation.restore(store)
        assert restored is not None
        msgs = restored.messages
        assert msgs[0].tool_calls == SAMPLE_TOOL_CALLS
        assert msgs[1].tool_use_id == "call_1"
        assert msgs[1].is_error is True

    @pytest.mark.asyncio
    async def test_compact_deletes_old_parts(self):
        store = MockConversationStore()
        conv = NodeConversation(store=store)
        await conv.add_user_message("a")
        await conv.add_user_message("b")
        assert len(store._parts) == 2

        await conv.compact("summary", keep_recent=0)
        assert len(store._parts) == 1
        remaining = list(store._parts.values())
        assert remaining[0]["content"] == "summary"

    @pytest.mark.asyncio
    async def test_compact_then_restore(self):
        """Compact with keep_recent persists correctly and restores."""
        store = MockConversationStore()
        conv = NodeConversation(system_prompt="sp", store=store)
        await conv.add_user_message("m1")
        await conv.add_assistant_message("m2")
        await conv.add_user_message("m3")
        await conv.add_assistant_message("m4")

        await conv.compact("early summary", keep_recent=2)

        restored = await NodeConversation.restore(store)
        assert restored is not None
        assert restored.message_count == 3
        assert restored.messages[0].content == "early summary"
        assert restored.messages[1].content == "m3"
        assert restored.messages[2].content == "m4"

    @pytest.mark.asyncio
    async def test_clear_deletes_store_parts(self):
        store = MockConversationStore()
        conv = NodeConversation(store=store)
        await conv.add_user_message("a")
        await conv.add_user_message("b")
        await conv.clear()
        assert len(store._parts) == 0


# ===================================================================
# FileConversationStore
# ===================================================================


class TestFileConversationStore:
    @pytest.mark.asyncio
    async def test_meta_and_cursor_crud(self, tmp_path):
        """Write/read meta and cursor; empty reads return None."""
        store = FileConversationStore(tmp_path / "conv")
        assert await store.read_meta() is None
        await store.write_meta({"system_prompt": "hi"})
        assert await store.read_meta() == {"system_prompt": "hi"}

        await store.write_cursor({"next_seq": 5})
        assert await store.read_cursor() == {"next_seq": 5}

    @pytest.mark.asyncio
    async def test_write_and_read_parts_in_order(self, tmp_path):
        store = FileConversationStore(tmp_path / "conv")
        await store.write_part(2, {"seq": 2, "content": "second"})
        await store.write_part(0, {"seq": 0, "content": "first"})
        await store.write_part(1, {"seq": 1, "content": "middle"})
        parts = await store.read_parts()
        assert [p["seq"] for p in parts] == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_delete_parts_before(self, tmp_path):
        store = FileConversationStore(tmp_path / "conv")
        for i in range(5):
            await store.write_part(i, {"seq": i})
        await store.delete_parts_before(3)
        parts = await store.read_parts()
        assert [p["seq"] for p in parts] == [3, 4]

    @pytest.mark.asyncio
    async def test_idempotent_write_part(self, tmp_path):
        store = FileConversationStore(tmp_path / "conv")
        await store.write_part(0, {"seq": 0, "v": 1})
        await store.write_part(0, {"seq": 0, "v": 2})
        parts = await store.read_parts()
        assert len(parts) == 1
        assert parts[0]["v"] == 2

    @pytest.mark.asyncio
    async def test_integration_with_node_conversation(self, tmp_path):
        """Full round-trip: create -> add messages -> restore from file store."""
        store = FileConversationStore(tmp_path / "conv")
        conv = NodeConversation(system_prompt="test", store=store)
        await conv.add_user_message("u1")
        await conv.add_assistant_message("a1", tool_calls=SAMPLE_TOOL_CALLS)
        await conv.add_tool_result("call_1", "r1", is_error=True)

        restored = await NodeConversation.restore(store)
        assert restored is not None
        assert restored.system_prompt == "test"
        assert restored.turn_count == 1
        assert restored.message_count == 3
        assert restored.next_seq == 3
        msgs = restored.messages
        assert msgs[0].content == "u1"
        assert msgs[1].tool_calls == SAMPLE_TOOL_CALLS
        assert msgs[2].is_error is True

        llm = restored.to_llm_messages()
        assert llm[2]["content"] == "ERROR: r1"

    @pytest.mark.asyncio
    async def test_corrupt_part_skipped_on_read(self, tmp_path):
        """A corrupt JSON part file is skipped, not fatal to restore."""
        store = FileConversationStore(tmp_path / "conv")
        await store.write_part(0, {"seq": 0, "content": "ok"})
        await store.write_part(1, {"seq": 1, "content": "good"})

        # Simulate crash mid-write: corrupt part 0
        corrupt_path = tmp_path / "conv" / "parts" / "0000000000.json"
        corrupt_path.write_text("{truncated", encoding="utf-8")

        parts = await store.read_parts()
        assert len(parts) == 1
        assert parts[0]["seq"] == 1

    @pytest.mark.asyncio
    async def test_directory_structure(self, tmp_path):
        """Verify meta.json, cursor.json, and parts/*.json files exist after writes."""
        store = FileConversationStore(tmp_path / "conv")
        await store.write_meta({"system_prompt": "hi"})
        await store.write_cursor({"next_seq": 2})
        await store.write_part(0, {"seq": 0, "content": "first"})
        await store.write_part(1, {"seq": 1, "content": "second"})

        base = tmp_path / "conv"
        assert (base / "meta.json").exists()
        assert (base / "cursor.json").exists()
        assert (base / "parts" / "0000000000.json").exists()
        assert (base / "parts" / "0000000001.json").exists()
