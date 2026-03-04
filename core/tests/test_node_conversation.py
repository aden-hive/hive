"""Tests for NodeConversation, Message, ConversationStore, and FileConversationStore."""

from __future__ import annotations

import json
from typing import Any

import pytest

from framework.graph.conversation import Message, NodeConversation, extract_tool_call_history
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
        m = Message(seq=0, role="tool", content="not found", tool_use_id="call_1", is_error=True)
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
    async def test_update_token_count_overrides_estimate(self):
        """When actual API token count is provided, estimate_tokens uses it."""
        conv = NodeConversation()
        await conv.add_user_message("a" * 400)
        assert conv.estimate_tokens() == 100  # chars/4 fallback

        conv.update_token_count(500)
        assert conv.estimate_tokens() == 500  # actual API value

    @pytest.mark.asyncio
    async def test_compact_resets_token_count(self):
        """After compaction, actual token count is cleared (recalibrates on next LLM call)."""
        conv = NodeConversation()
        await conv.add_user_message("a" * 400)
        conv.update_token_count(500)
        assert conv.estimate_tokens() == 500

        await conv.compact("summary", keep_recent=0)
        # Falls back to chars/4 for the summary message
        assert conv.estimate_tokens() == len("summary") // 4

    @pytest.mark.asyncio
    async def test_clear_resets_token_count(self):
        """clear() also resets the actual token count."""
        conv = NodeConversation()
        await conv.add_user_message("hello")
        conv.update_token_count(1000)
        assert conv.estimate_tokens() == 1000

        await conv.clear()
        assert conv.estimate_tokens() == 0

    @pytest.mark.asyncio
    async def test_usage_ratio(self):
        """usage_ratio returns estimate / max_history_tokens."""
        conv = NodeConversation(max_history_tokens=1000)
        await conv.add_user_message("a" * 400)
        assert conv.usage_ratio() == pytest.approx(0.1)  # 100/1000

        conv.update_token_count(800)
        assert conv.usage_ratio() == pytest.approx(0.8)  # 800/1000

    @pytest.mark.asyncio
    async def test_usage_ratio_zero_budget(self):
        """usage_ratio returns 0 when max_history_tokens is 0 (unlimited)."""
        conv = NodeConversation(max_history_tokens=0)
        await conv.add_user_message("a" * 400)
        assert conv.usage_ratio() == 0.0

    @pytest.mark.asyncio
    async def test_needs_compaction_with_actual_tokens(self):
        """needs_compaction uses actual API token count when available."""
        conv = NodeConversation(max_history_tokens=1000, compaction_threshold=0.8)
        await conv.add_user_message("a" * 100)  # chars/4 = 25, well under 800

        assert conv.needs_compaction() is False

        # Simulate API reporting much higher actual token usage
        conv.update_token_count(850)
        assert conv.needs_compaction() is True

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
        await conv.add_user_message("m1")  # seq=0
        await conv.add_assistant_message("m2")  # seq=1
        await conv.add_user_message("m3")  # seq=2
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
        assert conv._extract_protected_values(conv.messages) == {"meetings": '["standup", "retro"]'}

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


# ===================================================================
# Integration tests — real FileConversationStore, no mocks
# ===================================================================


class TestConversationIntegration:
    """End-to-end tests using real FileConversationStore on disk.

    Every test creates a fresh directory, writes real JSON files,
    and restores from a *new* store instance (simulating process restart).
    """

    @pytest.mark.asyncio
    async def test_multi_turn_agent_conversation(self, tmp_path):
        """Simulate a realistic agent conversation with multiple turns,
        tool calls, and tool results — then restore from disk."""
        base = tmp_path / "agent_conv"
        store = FileConversationStore(base)
        conv = NodeConversation(
            system_prompt="You are a helpful travel agent.",
            max_history_tokens=16000,
            store=store,
        )

        # Turn 1: user asks, assistant responds with tool call
        await conv.add_user_message("Find me flights from NYC to London next Friday.")
        await conv.add_assistant_message(
            "Let me search for flights.",
            tool_calls=[
                {
                    "id": "call_flight_1",
                    "type": "function",
                    "function": {
                        "name": "search_flights",
                        "arguments": '{"origin":"JFK","destination":"LHR","date":"2025-06-13"}',
                    },
                }
            ],
        )
        await conv.add_tool_result(
            "call_flight_1",
            '{"flights":[{"airline":"BA","price":450,"departure":"08:00"},{"airline":"AA","price":520,"departure":"14:30"}]}',
        )

        # Turn 2: assistant presents results, user picks one
        await conv.add_assistant_message(
            "I found 2 flights:\n"
            "1. British Airways at $450, departing 08:00\n"
            "2. American Airlines at $520, departing 14:30\n"
            "Which one would you like?"
        )
        await conv.add_user_message("Book the British Airways one.")
        await conv.add_assistant_message(
            "Booking the BA flight now.",
            tool_calls=[
                {
                    "id": "call_book_1",
                    "type": "function",
                    "function": {
                        "name": "book_flight",
                        "arguments": '{"flight_id":"BA-JFK-LHR-0800","passenger":"user"}',
                    },
                }
            ],
        )
        await conv.add_tool_result(
            "call_book_1",
            '{"confirmation":"BA-12345","status":"confirmed"}',
        )
        await conv.add_assistant_message("Your flight is booked! Confirmation: BA-12345.")

        # Verify in-memory state
        assert conv.turn_count == 2
        assert conv.message_count == 8
        assert conv.next_seq == 8

        # --- Simulate process restart: new store, same path ---
        store2 = FileConversationStore(base)
        restored = await NodeConversation.restore(store2)

        assert restored is not None
        assert restored.system_prompt == "You are a helpful travel agent."
        assert restored.turn_count == 2
        assert restored.message_count == 8
        assert restored.next_seq == 8

        # Verify message content integrity
        msgs = restored.messages
        assert msgs[0].role == "user"
        assert "NYC to London" in msgs[0].content
        assert msgs[1].role == "assistant"
        assert msgs[1].tool_calls[0]["id"] == "call_flight_1"
        assert msgs[2].role == "tool"
        assert msgs[2].tool_use_id == "call_flight_1"
        assert "BA" in msgs[2].content
        assert msgs[7].content == "Your flight is booked! Confirmation: BA-12345."

        # Verify LLM-format output
        llm_msgs = restored.to_llm_messages()
        assert llm_msgs[0] == {"role": "user", "content": msgs[0].content}
        assert llm_msgs[2]["role"] == "tool"
        assert llm_msgs[2]["tool_call_id"] == "call_flight_1"

    @pytest.mark.asyncio
    async def test_compaction_and_restore_preserves_continuity(self, tmp_path):
        """Build up a long conversation, compact it, continue adding
        messages, then restore — verifying seq continuity and content."""
        base = tmp_path / "compact_conv"
        store = FileConversationStore(base)
        conv = NodeConversation(
            system_prompt="research assistant",
            store=store,
        )

        # Build 10 messages (5 turns)
        for i in range(5):
            await conv.add_user_message(f"question {i}")
            await conv.add_assistant_message(f"answer {i}")

        assert conv.message_count == 10
        assert conv.next_seq == 10

        # Compact: keep last 2 messages (question 4, answer 4)
        await conv.compact("Summary of questions 0-3 and their answers.", keep_recent=2)

        assert conv.message_count == 3  # summary + 2 recent
        assert conv.messages[0].content == "Summary of questions 0-3 and their answers."
        assert conv.messages[1].content == "question 4"
        assert conv.messages[2].content == "answer 4"

        # Continue the conversation post-compaction
        await conv.add_user_message("question 5")
        await conv.add_assistant_message("answer 5")
        assert conv.next_seq == 12

        # Verify disk: old part files (seq 0-7) should be deleted
        parts_dir = base / "parts"
        part_files = sorted(parts_dir.glob("*.json"))
        part_seqs = [int(f.stem) for f in part_files]
        # Should have: summary (seq 7), question 4 (seq 8), answer 4 (seq 9),
        #              question 5 (seq 10), answer 5 (seq 11)
        assert all(s >= 7 for s in part_seqs), f"Stale parts found: {part_seqs}"

        # Restore from fresh store
        store2 = FileConversationStore(base)
        restored = await NodeConversation.restore(store2)

        assert restored is not None
        assert restored.next_seq == 12
        assert restored.message_count == 5
        assert "Summary of questions 0-3" in restored.messages[0].content
        assert restored.messages[-1].content == "answer 5"

        # Verify seq monotonicity across all restored messages
        seqs = [m.seq for m in restored.messages]
        assert seqs == sorted(seqs), f"Seqs not monotonic: {seqs}"

    @pytest.mark.asyncio
    async def test_output_key_preservation_through_compact_and_restore(self, tmp_path):
        """Output keys in compacted messages survive disk persistence."""
        base = tmp_path / "output_key_conv"
        store = FileConversationStore(base)
        conv = NodeConversation(
            system_prompt="classifier",
            output_keys=["classification", "confidence"],
            store=store,
        )

        await conv.add_user_message("Classify this email: 'You won a prize!'")
        await conv.add_assistant_message('{"classification": "spam", "confidence": "0.97"}')
        await conv.add_user_message("What about: 'Meeting at 3pm'")
        await conv.add_assistant_message('{"classification": "ham", "confidence": "0.99"}')
        await conv.add_user_message("And: 'Buy cheap meds now'")
        await conv.add_assistant_message('{"classification": "spam", "confidence": "0.95"}')

        # Compact keeping only the last 2 messages
        await conv.compact("Classified 3 emails.", keep_recent=2)

        # The summary should contain preserved output keys from discarded messages
        summary_content = conv.messages[0].content
        assert "PRESERVED VALUES" in summary_content
        # Most recent values from discarded messages (msgs 0-3) are "ham"/"0.99"
        assert "ham" in summary_content or "spam" in summary_content

        # Restore and verify the preserved values survived
        store2 = FileConversationStore(base)
        restored = await NodeConversation.restore(store2)
        assert restored is not None
        assert "PRESERVED VALUES" in restored.messages[0].content

    @pytest.mark.asyncio
    async def test_tool_error_roundtrip(self, tmp_path):
        """Tool errors persist and restore with ERROR: prefix in LLM output."""
        base = tmp_path / "error_conv"
        store = FileConversationStore(base)
        conv = NodeConversation(store=store)

        await conv.add_user_message("Calculate 1/0")
        await conv.add_assistant_message(
            "Let me calculate that.",
            tool_calls=[
                {
                    "id": "call_calc",
                    "type": "function",
                    "function": {"name": "calculator", "arguments": '{"expr":"1/0"}'},
                }
            ],
        )
        await conv.add_tool_result(
            "call_calc", "ZeroDivisionError: division by zero", is_error=True
        )
        await conv.add_assistant_message("The calculation failed: division by zero is undefined.")

        # Restore
        store2 = FileConversationStore(base)
        restored = await NodeConversation.restore(store2)
        assert restored is not None

        tool_msg = restored.messages[2]
        assert tool_msg.role == "tool"
        assert tool_msg.is_error is True
        assert tool_msg.tool_use_id == "call_calc"

        llm_dict = tool_msg.to_llm_dict()
        assert llm_dict["content"].startswith("ERROR: ")
        assert "ZeroDivisionError" in llm_dict["content"]
        assert llm_dict["tool_call_id"] == "call_calc"

    @pytest.mark.asyncio
    async def test_concurrent_conversations_isolated(self, tmp_path):
        """Two conversations in separate directories don't interfere."""
        store_a = FileConversationStore(tmp_path / "conv_a")
        store_b = FileConversationStore(tmp_path / "conv_b")

        conv_a = NodeConversation(system_prompt="Agent A", store=store_a)
        conv_b = NodeConversation(system_prompt="Agent B", store=store_b)

        await conv_a.add_user_message("Hello from A")
        await conv_b.add_user_message("Hello from B")
        await conv_a.add_assistant_message("Response A")
        await conv_b.add_assistant_message("Response B")
        await conv_b.add_user_message("Follow-up B")

        # Restore independently
        restored_a = await NodeConversation.restore(FileConversationStore(tmp_path / "conv_a"))
        restored_b = await NodeConversation.restore(FileConversationStore(tmp_path / "conv_b"))

        assert restored_a.system_prompt == "Agent A"
        assert restored_b.system_prompt == "Agent B"
        assert restored_a.message_count == 2
        assert restored_b.message_count == 3
        assert restored_a.messages[0].content == "Hello from A"
        assert restored_b.messages[2].content == "Follow-up B"

    @pytest.mark.asyncio
    async def test_destroy_removes_all_files(self, tmp_path):
        """destroy() wipes the entire conversation directory."""
        base = tmp_path / "doomed_conv"
        store = FileConversationStore(base)
        conv = NodeConversation(system_prompt="temp", store=store)
        await conv.add_user_message("ephemeral")
        await conv.add_assistant_message("gone soon")

        assert base.exists()
        assert (base / "meta.json").exists()
        assert (base / "parts").exists()

        await store.destroy()

        assert not base.exists()

    @pytest.mark.asyncio
    async def test_restore_empty_store_returns_none(self, tmp_path):
        """Restoring from a path that was never written to returns None."""
        store = FileConversationStore(tmp_path / "empty")
        result = await NodeConversation.restore(store)
        assert result is None

    @pytest.mark.asyncio
    async def test_clear_then_continue_then_restore(self, tmp_path):
        """clear() removes messages but preserves seq counter for new messages."""
        base = tmp_path / "clear_conv"
        store = FileConversationStore(base)
        conv = NodeConversation(system_prompt="s", store=store)

        await conv.add_user_message("old msg 0")
        await conv.add_assistant_message("old msg 1")
        assert conv.next_seq == 2

        await conv.clear()
        assert conv.message_count == 0
        assert conv.next_seq == 2  # seq counter preserved

        # Continue with new messages — seqs should start at 2
        await conv.add_user_message("new msg")
        await conv.add_assistant_message("new response")
        assert conv.next_seq == 4
        assert conv.messages[0].seq == 2
        assert conv.messages[1].seq == 3

        # Restore
        store2 = FileConversationStore(base)
        restored = await NodeConversation.restore(store2)
        assert restored is not None
        assert restored.message_count == 2
        assert restored.next_seq == 4
        assert restored.messages[0].content == "new msg"
        assert restored.messages[0].seq == 2


# ---------------------------------------------------------------------------
# Helpers for aggressive compaction tests
# ---------------------------------------------------------------------------


def _make_tool_call(call_id: str, name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


async def _build_tool_heavy_conversation(
    store: MockConversationStore | None = None,
) -> NodeConversation:
    """Build a conversation with many tool call pairs.

    Layout: user msg, then 5x (assistant with append_data tool_call + tool result),
    then 1x (assistant with set_output tool_call + tool result), then user msg + assistant msg.
    """
    conv = NodeConversation(store=store)
    await conv.add_user_message("Process the data")  # seq 0

    for i in range(5):
        args = {"filename": "output.html", "content": "x" * 500}
        tc = [_make_tool_call(f"call_{i}", "append_data", args)]
        conv._messages.append(
            Message(
                seq=conv._next_seq,
                role="assistant",
                content=f"Appending part {i}",
                tool_calls=tc,
            )
        )
        if store:
            await store.write_part(conv._next_seq, conv._messages[-1].to_storage_dict())
        conv._next_seq += 1
        conv._messages.append(
            Message(
                seq=conv._next_seq,
                role="tool",
                content='{"success": true}',
                tool_use_id=f"call_{i}",
            )
        )
        if store:
            await store.write_part(conv._next_seq, conv._messages[-1].to_storage_dict())
        conv._next_seq += 1

    # set_output call — must be protected
    so_tc = [_make_tool_call("call_so", "set_output", {"key": "result", "value": "done"})]
    conv._messages.append(
        Message(seq=conv._next_seq, role="assistant", content="Setting output", tool_calls=so_tc)
    )
    if store:
        await store.write_part(conv._next_seq, conv._messages[-1].to_storage_dict())
    conv._next_seq += 1
    conv._messages.append(
        Message(
            seq=conv._next_seq,
            role="tool",
            content="Output 'result' set successfully.",
            tool_use_id="call_so",
        )
    )
    if store:
        await store.write_part(conv._next_seq, conv._messages[-1].to_storage_dict())
    conv._next_seq += 1

    # Recent messages
    await conv.add_user_message("Continue")
    await conv.add_assistant_message("Working on it")
    return conv


# ---------------------------------------------------------------------------
# Tests: aggressive structural compaction
# ---------------------------------------------------------------------------


class TestAggressiveStructuralCompaction:
    @pytest.mark.asyncio
    async def test_aggressive_collapses_tool_pairs(self, tmp_path):
        """Aggressive mode should collapse non-essential tool pairs into a summary."""
        conv = await _build_tool_heavy_conversation()
        spill = str(tmp_path)

        await conv.compact_preserving_structure(
            spillover_dir=spill,
            keep_recent=2,
            aggressive=True,
        )

        # The 5 append_data pairs (10 msgs) + 1 user msg should be collapsed.
        # Remaining: ref_msg + set_output pair (2 msgs) + 2 recent = 5
        assert conv.message_count == 5
        assert conv.messages[0].role == "user"  # ref message
        assert "TOOLS ALREADY CALLED" in conv.messages[0].content
        assert "append_data (5x)" in conv.messages[0].content

        # set_output pair should be preserved
        assert conv.messages[1].role == "assistant"
        assert conv.messages[1].tool_calls is not None
        assert conv.messages[1].tool_calls[0]["function"]["name"] == "set_output"
        assert conv.messages[2].role == "tool"

        # Recent messages intact
        assert conv.messages[3].content == "Continue"
        assert conv.messages[4].content == "Working on it"

    @pytest.mark.asyncio
    async def test_aggressive_preserves_set_output(self, tmp_path):
        """set_output tool calls are always protected in aggressive mode."""
        conv = await _build_tool_heavy_conversation()
        spill = str(tmp_path)

        await conv.compact_preserving_structure(
            spillover_dir=spill,
            keep_recent=2,
            aggressive=True,
        )

        # Find all tool calls in remaining messages
        tool_names = []
        for msg in conv.messages:
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_names.append(tc["function"]["name"])

        assert "set_output" in tool_names
        # append_data should NOT be in remaining messages (collapsed)
        assert "append_data" not in tool_names

    @pytest.mark.asyncio
    async def test_aggressive_preserves_errors(self, tmp_path):
        """Error tool results are always protected in aggressive mode."""
        conv = NodeConversation()
        await conv.add_user_message("Start")

        # Regular tool call
        tc1 = [_make_tool_call("call_ok", "web_search", {"query": "test"})]
        conv._messages.append(
            Message(seq=conv._next_seq, role="assistant", content="", tool_calls=tc1)
        )
        conv._next_seq += 1
        conv._messages.append(
            Message(seq=conv._next_seq, role="tool", content="results", tool_use_id="call_ok")
        )
        conv._next_seq += 1

        # Error tool call
        tc2 = [_make_tool_call("call_err", "web_scrape", {"url": "http://broken.com"})]
        conv._messages.append(
            Message(seq=conv._next_seq, role="assistant", content="", tool_calls=tc2)
        )
        conv._next_seq += 1
        conv._messages.append(
            Message(
                seq=conv._next_seq,
                role="tool",
                content="Connection timeout",
                tool_use_id="call_err",
                is_error=True,
            )
        )
        conv._next_seq += 1

        await conv.add_user_message("Next")
        await conv.add_assistant_message("OK")

        spill = str(tmp_path)
        await conv.compact_preserving_structure(
            spillover_dir=spill,
            keep_recent=2,
            aggressive=True,
        )

        # Error pair should be preserved
        error_msgs = [m for m in conv.messages if m.role == "tool" and m.is_error]
        assert len(error_msgs) == 1
        assert error_msgs[0].content == "Connection timeout"

    @pytest.mark.asyncio
    async def test_standard_mode_keeps_all_tool_pairs(self, tmp_path):
        """Non-aggressive mode should keep all tool pairs (existing behavior)."""
        conv = await _build_tool_heavy_conversation()
        spill = str(tmp_path)

        await conv.compact_preserving_structure(
            spillover_dir=spill,
            keep_recent=2,
            aggressive=False,
        )

        # All 6 tool pairs (12 msgs) should be kept as structural.
        # Removed: 1 user msg (freeform). Remaining: ref + 12 structural + 2 recent = 15
        assert conv.message_count == 15

    @pytest.mark.asyncio
    async def test_two_pass_sequence(self, tmp_path):
        """Standard pass then aggressive pass produces valid result."""
        conv = await _build_tool_heavy_conversation()
        spill = str(tmp_path)

        # Pass 1: standard
        await conv.compact_preserving_structure(
            spillover_dir=spill,
            keep_recent=2,
        )
        after_standard = conv.message_count
        assert after_standard == 15  # all structural kept

        # Pass 2: aggressive
        await conv.compact_preserving_structure(
            spillover_dir=spill,
            keep_recent=2,
            aggressive=True,
        )
        after_aggressive = conv.message_count
        assert after_aggressive < after_standard
        # ref + set_output pair + 2 recent = 5
        assert after_aggressive == 5

    @pytest.mark.asyncio
    async def test_aggressive_persists_correctly(self, tmp_path):
        """Aggressive compaction correctly updates the store."""
        store = MockConversationStore()
        conv = await _build_tool_heavy_conversation(store=store)
        spill = str(tmp_path)

        await conv.compact_preserving_structure(
            spillover_dir=spill,
            keep_recent=2,
            aggressive=True,
        )

        # Verify store state matches in-memory state
        parts = await store.read_parts()
        assert len(parts) == conv.message_count


class TestExtractToolCallHistory:
    def test_basic_extraction(self):
        msgs = [
            Message(
                seq=0,
                role="assistant",
                content="",
                tool_calls=[
                    _make_tool_call("c1", "web_search", {"query": "python async"}),
                ],
            ),
            Message(seq=1, role="tool", content="results", tool_use_id="c1"),
            Message(
                seq=2,
                role="assistant",
                content="",
                tool_calls=[
                    _make_tool_call(
                        "c2", "save_data", {"filename": "output.txt", "content": "data"}
                    ),
                ],
            ),
            Message(seq=3, role="tool", content="saved", tool_use_id="c2"),
        ]
        result = extract_tool_call_history(msgs)
        assert "web_search (1x)" in result
        assert "save_data (1x)" in result
        assert "FILES SAVED: output.txt" in result

    def test_errors_included(self):
        msgs = [
            Message(
                seq=0,
                role="tool",
                content="Connection refused",
                is_error=True,
                tool_use_id="c1",
            ),
        ]
        result = extract_tool_call_history(msgs)
        assert "ERRORS" in result
        assert "Connection refused" in result

    def test_empty_messages(self):
        assert extract_tool_call_history([]) == ""


# ---------------------------------------------------------------------------
# Tests for _is_context_too_large_error
# ---------------------------------------------------------------------------


class TestIsContextTooLargeError:
    def test_context_window_class_name(self):
        from framework.graph.event_loop_node import _is_context_too_large_error

        class ContextWindowExceededError(Exception):
            pass

        assert _is_context_too_large_error(ContextWindowExceededError("x"))

    def test_openai_context_length(self):
        from framework.graph.event_loop_node import _is_context_too_large_error

        err = RuntimeError("This model's maximum context length is 128000 tokens")
        assert _is_context_too_large_error(err)

    def test_anthropic_too_long(self):
        from framework.graph.event_loop_node import _is_context_too_large_error

        err = RuntimeError("prompt is too long: 150000 tokens > 100000")
        assert _is_context_too_large_error(err)

    def test_generic_exceeds_limit(self):
        from framework.graph.event_loop_node import _is_context_too_large_error

        err = ValueError("Request exceeds token limit")
        assert _is_context_too_large_error(err)

    def test_unrelated_error(self):
        from framework.graph.event_loop_node import _is_context_too_large_error

        assert not _is_context_too_large_error(ValueError("connection refused"))
        assert not _is_context_too_large_error(RuntimeError("timeout"))


# ---------------------------------------------------------------------------
# Tests for _format_messages_for_summary
# ---------------------------------------------------------------------------


class TestFormatMessagesForSummary:
    def test_user_assistant_messages(self):
        from framework.graph.event_loop_node import EventLoopNode

        msgs = [
            Message(seq=0, role="user", content="Hello world"),
            Message(seq=1, role="assistant", content="Hi there"),
        ]
        result = EventLoopNode._format_messages_for_summary(msgs)
        assert "[user]: Hello world" in result
        assert "[assistant]: Hi there" in result

    def test_tool_result_truncated(self):
        from framework.graph.event_loop_node import EventLoopNode

        msgs = [
            Message(seq=0, role="tool", content="x" * 1000, tool_use_id="c1"),
        ]
        result = EventLoopNode._format_messages_for_summary(msgs)
        assert "[tool result]:" in result
        assert "..." in result
        # Should be truncated to 500 + "..."
        assert len(result) < 600

    def test_assistant_with_tool_calls(self):
        from framework.graph.event_loop_node import EventLoopNode

        tc = [_make_tool_call("c1", "web_search", {"query": "test"})]
        msgs = [
            Message(seq=0, role="assistant", content="Searching", tool_calls=tc),
        ]
        result = EventLoopNode._format_messages_for_summary(msgs)
        assert "web_search" in result
        assert "[assistant (calls:" in result


# ---------------------------------------------------------------------------
# Tests for _llm_compact (recursive binary-search)
# ---------------------------------------------------------------------------


class TestLlmCompact:
    """Test the recursive LLM compaction with mock LLM."""

    def _make_node(self):
        """Create a minimal EventLoopNode for testing."""
        from framework.graph.event_loop_node import EventLoopNode, LoopConfig

        config = LoopConfig(max_history_tokens=32000)
        node = EventLoopNode.__new__(EventLoopNode)
        node._config = config
        node._event_bus = None
        node._judge = None
        node._approval_callback = None
        node._tool_executor = None
        node._adaptive_learner = None
        # Set class-level constants (already on class, but explicit)
        return node

    def _make_ctx(self, llm_responses=None, llm_error=None):
        """Create a mock NodeContext with controllable LLM."""
        from unittest.mock import AsyncMock, MagicMock

        from framework.graph.node import NodeSpec

        spec = NodeSpec(
            id="test",
            name="Test Node",
            description="A test node",
            node_type="event_loop",
            input_keys=[],
            output_keys=["result"],
        )

        ctx = MagicMock()
        ctx.node_spec = spec
        ctx.node_id = "test"
        ctx.stream_id = "test"
        ctx.continuous_mode = False
        ctx.runtime_logger = None

        mock_llm = AsyncMock()
        if llm_error:
            mock_llm.acomplete.side_effect = llm_error
        elif llm_responses:
            responses = []
            for text in llm_responses:
                resp = MagicMock()
                resp.content = text
                responses.append(resp)
            mock_llm.acomplete.side_effect = responses
        else:
            resp = MagicMock()
            resp.content = "Summary of conversation."
            mock_llm.acomplete.return_value = resp

        ctx.llm = mock_llm
        return ctx

    @pytest.mark.asyncio
    async def test_single_call_success(self):
        node = self._make_node()
        ctx = self._make_ctx()
        msgs = [
            Message(seq=0, role="user", content="Do something"),
            Message(seq=1, role="assistant", content="Done"),
        ]
        result = await node._llm_compact(ctx, msgs, None)
        assert "Summary of conversation." in result
        ctx.llm.acomplete.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_too_large_triggers_split(self):
        """When LLM raises context error, should split and retry."""
        from unittest.mock import MagicMock

        node = self._make_node()

        call_count = 0

        async def mock_acomplete(**kwargs):
            nonlocal call_count
            call_count += 1
            # First call with full messages → fail
            # Subsequent calls with smaller chunks → succeed
            if call_count == 1:
                raise RuntimeError("This model's maximum context length is 128000 tokens")
            resp = MagicMock()
            resp.content = f"Summary part {call_count}"
            return resp

        ctx = self._make_ctx()
        ctx.llm.acomplete = mock_acomplete

        msgs = [Message(seq=i, role="user", content=f"Message {i}") for i in range(10)]
        result = await node._llm_compact(ctx, msgs, None)
        # Should have split and produced two summaries
        assert "Summary part" in result
        assert call_count >= 3  # 1 failure + 2 successful halves

    @pytest.mark.asyncio
    async def test_non_context_error_propagates(self):
        """Non-context errors should propagate, not trigger splitting."""
        node = self._make_node()
        ctx = self._make_ctx(llm_error=ValueError("API key invalid"))
        msgs = [
            Message(seq=0, role="user", content="Hello"),
            Message(seq=1, role="assistant", content="Hi"),
        ]
        with pytest.raises(ValueError, match="API key invalid"):
            await node._llm_compact(ctx, msgs, None)

    @pytest.mark.asyncio
    async def test_proactive_split_for_large_input(self):
        """Messages exceeding char limit should be split proactively."""
        node = self._make_node()
        # Lower the limit for testing
        node._LLM_COMPACT_CHAR_LIMIT = 100

        ctx = self._make_ctx(
            llm_responses=["Part 1 summary", "Part 2 summary"],
        )
        msgs = [
            Message(seq=0, role="user", content="x" * 80),
            Message(seq=1, role="user", content="y" * 80),
        ]
        result = await node._llm_compact(ctx, msgs, None)
        assert "Part 1 summary" in result
        assert "Part 2 summary" in result
        # LLM should have been called twice (no failure, proactive split)
        assert ctx.llm.acomplete.call_count == 2

    @pytest.mark.asyncio
    async def test_tool_history_appended_at_top_level(self):
        """Tool history should only be appended at depth 0."""
        node = self._make_node()
        ctx = self._make_ctx()

        tc = [_make_tool_call("c1", "web_search", {"query": "test"})]
        msgs = [
            Message(seq=0, role="assistant", content="", tool_calls=tc),
            Message(seq=1, role="tool", content="results", tool_use_id="c1"),
        ]
        result = await node._llm_compact(ctx, msgs, None)
        assert "TOOLS ALREADY CALLED" in result
        assert "web_search" in result


# ---------------------------------------------------------------------------
# Orphaned tool result repair
# ---------------------------------------------------------------------------


class TestRepairOrphanedToolCalls:
    """Test _repair_orphaned_tool_calls handles both directions."""

    def test_orphaned_tool_result_dropped(self):
        """Tool result with no matching tool_use should be dropped."""
        msgs = [
            # tool result with no preceding assistant tool_use
            {"role": "tool", "tool_call_id": "orphan_1", "content": "stale result"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        repaired = NodeConversation._repair_orphaned_tool_calls(msgs)
        assert len(repaired) == 2
        assert repaired[0]["role"] == "user"
        assert repaired[1]["role"] == "assistant"

    def test_valid_tool_pair_preserved(self):
        """Tool result with matching tool_use should be kept."""
        msgs = [
            {"role": "user", "content": "search"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc_1", "function": {"name": "search", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "tc_1", "content": "results"},
        ]
        repaired = NodeConversation._repair_orphaned_tool_calls(msgs)
        assert len(repaired) == 3
        assert repaired[2]["tool_call_id"] == "tc_1"

    def test_orphaned_tool_use_gets_stub(self):
        """Tool use with no following tool result gets a synthetic error stub."""
        msgs = [
            {"role": "user", "content": "search"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc_1", "function": {"name": "search", "arguments": "{}"}}],
            },
            # No tool result follows
            {"role": "user", "content": "what happened?"},
        ]
        repaired = NodeConversation._repair_orphaned_tool_calls(msgs)
        # Should insert a synthetic tool result between assistant and user
        assert len(repaired) == 4
        assert repaired[2]["role"] == "tool"
        assert repaired[2]["tool_call_id"] == "tc_1"
        assert "interrupted" in repaired[2]["content"].lower()

    def test_mixed_orphans(self):
        """Both orphaned results and orphaned calls handled together."""
        msgs = [
            # Orphaned result (no matching tool_use)
            {"role": "tool", "tool_call_id": "gone_1", "content": "old result"},
            {"role": "user", "content": "try again"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc_2", "function": {"name": "fetch", "arguments": "{}"}}],
            },
            # Missing result for tc_2
            {"role": "user", "content": "done?"},
        ]
        repaired = NodeConversation._repair_orphaned_tool_calls(msgs)
        # orphaned result dropped, stub added for tc_2
        roles = [m["role"] for m in repaired]
        assert roles == ["user", "assistant", "tool", "user"]
        assert repaired[2]["tool_call_id"] == "tc_2"
