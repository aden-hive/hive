"""Tests for NodeConversation, Message, ConversationStore, and FileConversationStore."""

from __future__ import annotations

import json
from typing import Any

import pytest

from framework.agent_loop.conversation import (
    Message,
    NodeConversation,
    extract_tool_call_history,
)
from framework.storage.conversation_store import FileConversationStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockConversationStore:
    """In-memory dict-based store for testing."""

    def __init__(self) -> None:
        self._parts: dict[int, dict] = {}
        self._partials: dict[int, dict] = {}
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

    async def delete_parts_before(self, seq: int, run_id: str | None = None) -> None:
        self._parts = {k: v for k, v in self._parts.items() if k >= seq}

    async def write_partial(self, seq: int, data: dict[str, Any]) -> None:
        self._partials[seq] = data

    async def read_partial(self, seq: int) -> dict[str, Any] | None:
        return self._partials.get(seq)

    async def read_all_partials(self) -> list[dict[str, Any]]:
        return [self._partials[k] for k in sorted(self._partials)]

    async def clear_partial(self, seq: int) -> None:
        self._partials.pop(seq, None)

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

    def test_thinking_blocks_echoed_back_in_llm_dict(self):
        """Reasoning models require prior `thinking` blocks — signature
        included — to be sent back verbatim, or the next request 400s.
        ``to_llm_dict`` must carry them so litellm's Anthropic transform
        re-emits them as content blocks."""
        tb = [{"type": "thinking", "thinking": "weighing options", "signature": "SIG-XYZ"}]
        m = Message(seq=0, role="assistant", content="answer", thinking_blocks=tb)
        d = m.to_llm_dict()
        assert d["thinking_blocks"] == tb
        # Also present when the turn made tool calls.
        m_tc = Message(seq=1, role="assistant", content="", tool_calls=SAMPLE_TOOL_CALLS, thinking_blocks=tb)
        assert m_tc.to_llm_dict()["thinking_blocks"] == tb
        # Absent for non-reasoning turns — no empty key.
        assert "thinking_blocks" not in Message(seq=2, role="assistant", content="hi").to_llm_dict()

    def test_thinking_blocks_survive_storage_roundtrip(self):
        """thinking_blocks must persist so they are echoed back even after a
        session reload — display state and API state both keep them."""
        tb = [{"type": "thinking", "thinking": "step one", "signature": "SIG-1"}]
        m = Message(seq=7, role="assistant", content="ok", thinking_blocks=tb)
        restored = Message.from_storage_dict(m.to_storage_dict())
        assert restored.thinking_blocks == tb
        # Omitted when absent.
        assert "thinking_blocks" not in Message(seq=8, role="assistant", content="x").to_storage_dict()


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
        # chars // 3 (4/3 safety margin over chars/4 base)
        assert conv.estimate_tokens() == 400 // 3

    @pytest.mark.asyncio
    async def test_update_token_count_overrides_estimate(self):
        """When actual API token count is provided, estimate_tokens uses it."""
        conv = NodeConversation()
        await conv.add_user_message("a" * 400)
        assert conv.estimate_tokens() == 400 // 3  # char-based fallback with safety margin

        conv.update_token_count(500)
        assert conv.estimate_tokens() == 500  # actual API value

    @pytest.mark.asyncio
    async def test_update_token_count_reflects_last_call_not_sum(self):
        """Repeated updates store the latest call's input size, not a sum.

        Regression for the unit-mismatch bug where the per-iteration caller
        was passing token_counts["input"] (a cumulative billing sum across
        all inner LLM calls in a turn). That made usage_ratio compare a
        billing aggregate against max_context_tokens (a single-prompt
        budget), producing fictional 1000%+ ratios. update_token_count is
        single-call by contract; subsequent calls replace, never sum.
        """
        conv = NodeConversation(max_context_tokens=180_000)

        conv.update_token_count(40_000)
        assert conv.estimate_tokens() == 40_000
        assert conv.usage_ratio() < 1.0

        # Simulate the next inner LLM call returning a slightly larger prompt
        conv.update_token_count(50_000)
        assert conv.estimate_tokens() == 50_000  # NOT 40_000 + 50_000

        # And many more calls — the value tracks the LAST one, not the sum
        for size in (60_000, 70_000, 80_000, 90_000):
            conv.update_token_count(size)
        assert conv.estimate_tokens() == 90_000  # NOT 40 + 50 + 60 + 70 + 80 + 90 = 390k
        assert conv.usage_ratio() == 90_000 / 180_000

    @pytest.mark.asyncio
    async def test_compact_resets_token_count(self):
        """After compaction, actual token count is cleared (recalibrates on next LLM call)."""
        conv = NodeConversation()
        await conv.add_user_message("a" * 400)
        conv.update_token_count(500)
        assert conv.estimate_tokens() == 500

        await conv.compact("summary", keep_recent=0)
        # Falls back to char-based heuristic with 4/3 safety margin (chars // 3)
        assert conv.estimate_tokens() == len("summary") // 3

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
        """usage_ratio returns estimate / max_context_tokens."""
        conv = NodeConversation(max_context_tokens=1000)
        await conv.add_user_message("a" * 400)
        # 400 // 3 = 133 tokens (with safety margin), so 133/1000
        assert conv.usage_ratio() == pytest.approx(400 // 3 / 1000)

        conv.update_token_count(800)
        assert conv.usage_ratio() == pytest.approx(0.8)  # 800/1000

    @pytest.mark.asyncio
    async def test_usage_ratio_zero_budget(self):
        """usage_ratio returns 0 when max_context_tokens is 0 (unlimited)."""
        conv = NodeConversation(max_context_tokens=0)
        await conv.add_user_message("a" * 400)
        assert conv.usage_ratio() == 0.0

    @pytest.mark.asyncio
    async def test_needs_compaction_with_actual_tokens(self):
        """needs_compaction uses actual API token count when available."""
        conv = NodeConversation(max_context_tokens=1000, compaction_threshold=0.8)
        await conv.add_user_message("a" * 100)  # chars/4 = 25, well under 800

        assert conv.needs_compaction() is False

        # Simulate API reporting much higher actual token usage
        conv.update_token_count(850)
        assert conv.needs_compaction() is True

    @pytest.mark.asyncio
    async def test_needs_compaction(self):
        conv = NodeConversation(max_context_tokens=100, compaction_threshold=0.8)
        await conv.add_user_message("x" * 320)
        assert conv.needs_compaction() is True

    @pytest.mark.asyncio
    async def test_needs_compaction_uses_buffer_when_set(self):
        """Gap 7: a compaction_buffer_tokens overrides the multiplicative
        threshold - compaction triggers when estimate + buffer would
        cross the hard context limit, not at a fractional threshold."""
        conv = NodeConversation(
            max_context_tokens=1000,
            compaction_threshold=0.9,  # would normally trigger at 900
            compaction_buffer_tokens=300,  # buffer wants 700 hard cap
        )
        # 650 tokens is below the 700 budget - no compaction yet.
        conv.update_token_count(650)
        assert conv.needs_compaction() is False
        # 700+ crosses the budget - compaction fires BEFORE reaching
        # the hard 1000 limit, so the next turn's input has headroom.
        conv.update_token_count(700)
        assert conv.needs_compaction() is True

    @pytest.mark.asyncio
    async def test_compaction_warning_fires_before_hard_trigger(self):
        """Gap 7: the warning threshold is meant to surface early signal
        to telemetry without actually triggering compaction."""
        conv = NodeConversation(
            max_context_tokens=1000,
            compaction_buffer_tokens=200,
            compaction_warning_buffer_tokens=400,
        )
        conv.update_token_count(500)
        assert conv.compaction_warning() is False
        assert conv.needs_compaction() is False

        # Cross 600 tokens: warning fires (1000 - 400) but compaction
        # doesn't yet (1000 - 200 = 800 budget).
        conv.update_token_count(650)
        assert conv.compaction_warning() is True
        assert conv.needs_compaction() is False

        # Cross 800: both fire.
        conv.update_token_count(820)
        assert conv.compaction_warning() is True
        assert conv.needs_compaction() is True

    @pytest.mark.asyncio
    async def test_needs_compaction_uses_hybrid_buffer(self):
        """Hybrid: effective buffer is fixed_tokens + ratio * max_context.

        With max=1000, fixed=200, ratio=0.1 → effective_buffer=300, so
        the trigger threshold is 700.
        """
        conv = NodeConversation(
            max_context_tokens=1000,
            compaction_buffer_tokens=200,
            compaction_buffer_ratio=0.1,
        )
        conv.update_token_count(650)
        assert conv.needs_compaction() is False
        conv.update_token_count(700)
        assert conv.needs_compaction() is True

    @pytest.mark.asyncio
    async def test_needs_compaction_ratio_only(self):
        """Ratio component alone (without a fixed floor) still works."""
        conv = NodeConversation(
            max_context_tokens=1000,
            compaction_buffer_ratio=0.25,
        )
        conv.update_token_count(740)
        assert conv.needs_compaction() is False
        conv.update_token_count(760)
        assert conv.needs_compaction() is True

    @pytest.mark.asyncio
    async def test_legacy_threshold_rule_still_works_without_buffer(self):
        """Without compaction_buffer_tokens, the old multiplicative rule
        applies so existing callers keep behaving identically."""
        conv = NodeConversation(
            max_context_tokens=1000,
            compaction_threshold=0.75,
        )
        conv.update_token_count(700)
        assert conv.needs_compaction() is False
        conv.update_token_count(800)
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
    async def test_compact_preserves_client_input_messages(self):
        """Real client input survives compaction verbatim, not via LLM paraphrase."""
        conv = NodeConversation()
        await conv.add_user_message("original task: chart ISRG", is_client_input=True)
        await conv.add_assistant_message("starting work")
        await conv.add_user_message("[system nudge — continue]")  # not client input
        await conv.add_assistant_message("continuing")
        await conv.add_user_message("also check OSCR", is_client_input=True)
        await conv.add_assistant_message("acknowledged")
        await conv.add_assistant_message("most recent")

        await conv.compact("LLM summary text", keep_recent=1)

        # Live order: [client_input_1, client_input_2, summary, recent]
        roles = [m.role for m in conv.messages]
        contents = [m.content for m in conv.messages]
        assert roles == ["user", "user", "user", "assistant"]
        assert contents[0] == "original task: chart ISRG"
        assert contents[1] == "also check OSCR"
        assert contents[2] == "LLM summary text"
        assert contents[3] == "most recent"
        # System nudge (is_client_input=False) was discarded.
        assert all("[system nudge" not in c for c in contents)

    @pytest.mark.asyncio
    async def test_compact_client_input_preserved_across_chained_compactions(self):
        """Successive compactions keep the original prompt without unbounded growth."""
        conv = NodeConversation()
        await conv.add_user_message("ORIGINAL", is_client_input=True)
        for i in range(6):
            await conv.add_assistant_message(f"work {i}")

        await conv.compact("first summary", keep_recent=1)
        # After 1st pass: [client_input, summary, recent]
        assert [m.content for m in conv.messages] == ["ORIGINAL", "first summary", "work 5"]

        # Add more activity, then compact again
        for i in range(6):
            await conv.add_assistant_message(f"more {i}")
        await conv.compact("second summary", keep_recent=1)

        # The first summary (which is role=user but is_client_input=False) must NOT
        # be re-preserved; only the original client input should survive.
        contents = [m.content for m in conv.messages]
        assert contents.count("first summary") == 0
        assert contents == ["ORIGINAL", "second summary", "more 5"]

    @pytest.mark.asyncio
    async def test_compact_client_input_collision_at_boundary(self):
        """If the last old message is itself client input, it merges into the summary."""
        conv = NodeConversation()
        await conv.add_user_message("first prompt", is_client_input=True)
        await conv.add_assistant_message("response")
        # This client input sits at the split boundary (its seq == summary_seq)
        await conv.add_user_message("boundary prompt", is_client_input=True)
        await conv.add_assistant_message("most recent")

        await conv.compact("SUMMARY", keep_recent=1)

        # The boundary client input got absorbed into the summary slot,
        # so only the first prompt survives as a standalone preserved message.
        contents = [m.content for m in conv.messages]
        assert contents == ["first prompt", "SUMMARY", "most recent"]

    @pytest.mark.asyncio
    async def test_compact_client_input_persisted_to_store(self):
        """Preserved client inputs survive a cold restore from disk."""
        store = MockConversationStore()
        conv = NodeConversation(store=store)
        await conv.add_user_message("keep me", is_client_input=True)
        await conv.add_assistant_message("work 1")
        await conv.add_assistant_message("work 2")
        await conv.add_assistant_message("work 3")
        await conv.add_assistant_message("most recent")

        await conv.compact("summary", keep_recent=1)

        # Verify in-memory state
        assert [m.content for m in conv.messages] == ["keep me", "summary", "most recent"]

        # Verify store reflects the same order (parts are read sorted by seq).
        parts = await store.read_parts()
        roles_in_store = [p["role"] for p in parts]
        contents_in_store = [p["content"] for p in parts]
        assert contents_in_store == ["keep me", "summary", "most recent"]
        assert roles_in_store == ["user", "user", "assistant"]

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
        await conv.add_assistant_message('Based on my analysis, here are the results: {"lead_score": 87, "status": "hot"}')
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

        conv = NodeConversation(system_prompt="hello", max_context_tokens=500, store=store)
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
    async def test_restore_filters_by_run_id_for_crash_recovery(self):
        """Restore with a non-legacy run_id only loads parts from that run.

        This ensures intentional restarts (new run_id) start fresh while
        crash recovery (same run_id) resumes correctly. Legacy parts (no
        run_id) and other runs' parts are excluded.
        """
        store = MockConversationStore()
        await store.write_meta({"system_prompt": "hello"})
        await store.write_part(0, {"seq": 0, "role": "user", "content": "legacy"})
        await store.write_part(1, {"seq": 1, "role": "user", "content": "run-a", "run_id": "run-a"})
        await store.write_part(
            2,
            {"seq": 2, "role": "assistant", "content": "run-b", "run_id": "run-b"},
        )
        await store.write_cursor({"next_seq": 3})

        restored = await NodeConversation.restore(store, run_id="run-a")
        assert restored is not None
        assert [m.content for m in restored.messages] == ["run-a"]
        assert restored.next_seq == 3

    @pytest.mark.asyncio
    async def test_restore_phase_filter_falls_back_for_legacy_unphased_parts(self):
        """Legacy stores without phase_id should still restore in isolated mode."""
        store = MockConversationStore()
        await store.write_meta({"system_prompt": "hello"})
        await store.write_part(0, {"seq": 0, "role": "assistant", "content": "restored"})
        await store.write_cursor({"next_seq": 1})

        restored = await NodeConversation.restore(store, phase_id="queen")
        assert restored is not None
        assert [m.content for m in restored.messages] == ["restored"]
        assert restored.next_seq == 1

    @pytest.mark.asyncio
    async def test_restore_phase_filter_does_not_fall_back_for_mismatched_phased_parts(self):
        """Phase filtering should still exclude stores that use explicit phase ids."""
        store = MockConversationStore()
        await store.write_meta({"system_prompt": "hello"})
        await store.write_part(
            0,
            {"seq": 0, "role": "assistant", "content": "node-a only", "phase_id": "node-a"},
        )
        await store.write_cursor({"next_seq": 1})

        restored = await NodeConversation.restore(store, phase_id="queen")
        assert restored is not None
        assert restored.message_count == 0
        assert restored.next_seq == 1

    @pytest.mark.asyncio
    async def test_clear_deletes_all_parts(self):
        store = MockConversationStore()
        conv_a = NodeConversation(system_prompt="hello", store=store, run_id="run-a")
        conv_b = NodeConversation(system_prompt="hello", store=store, run_id="run-b")

        await conv_a.add_user_message("a1")
        await conv_b.add_user_message("b1")

        await conv_a.clear()

        restored = await NodeConversation.restore(store)
        assert restored is not None
        assert [m.content for m in restored.messages] == []

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

    @pytest.mark.asyncio
    async def test_partials_separate_from_parts(self, tmp_path):
        """Partial checkpoints must not pollute read_parts() and vice versa."""
        store = FileConversationStore(tmp_path / "conv")
        await store.write_part(0, {"seq": 0, "content": "real"})
        await store.write_partial(1, {"seq": 1, "content": "inflight", "truncated": True})
        parts = await store.read_parts()
        assert [p["seq"] for p in parts] == [0]
        partials = await store.read_all_partials()
        assert [p["seq"] for p in partials] == [1]
        assert partials[0]["content"] == "inflight"
        assert (await store.read_partial(1))["content"] == "inflight"
        assert await store.read_partial(99) is None
        await store.clear_partial(1)
        assert await store.read_all_partials() == []

    @pytest.mark.asyncio
    async def test_partials_dir_does_not_break_parts_glob(self, tmp_path):
        """delete_parts_before parses stems as int — partial files must not trip it."""
        store = FileConversationStore(tmp_path / "conv")
        for i in range(3):
            await store.write_part(i, {"seq": i})
            await store.write_partial(i + 100, {"seq": i + 100})
        await store.delete_parts_before(2)
        assert [p["seq"] for p in await store.read_parts()] == [2]
        assert [p["seq"] for p in await store.read_all_partials()] == [100, 101, 102]


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
            max_context_tokens=16000,
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
        await conv.add_tool_result("call_calc", "ZeroDivisionError: division by zero", is_error=True)
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
                    _make_tool_call("c2", "terminal_exec", {"command": "cat /tmp/output.txt"}),
                ],
            ),
            Message(seq=3, role="tool", content="contents", tool_use_id="c2"),
        ]
        result = extract_tool_call_history(msgs)
        assert "web_search (1x)" in result
        assert "terminal_exec (1x)" in result

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
        from framework.agent_loop.agent_loop import _is_context_too_large_error

        class ContextWindowExceededError(Exception):
            pass

        assert _is_context_too_large_error(ContextWindowExceededError("x"))

    def test_openai_context_length(self):
        from framework.agent_loop.agent_loop import _is_context_too_large_error

        err = RuntimeError("This model's maximum context length is 128000 tokens")
        assert _is_context_too_large_error(err)

    def test_anthropic_too_long(self):
        from framework.agent_loop.agent_loop import _is_context_too_large_error

        err = RuntimeError("prompt is too long: 150000 tokens > 100000")
        assert _is_context_too_large_error(err)

    def test_generic_exceeds_limit(self):
        from framework.agent_loop.agent_loop import _is_context_too_large_error

        err = ValueError("Request exceeds token limit")
        assert _is_context_too_large_error(err)

    def test_unrelated_error(self):
        from framework.agent_loop.agent_loop import _is_context_too_large_error

        assert not _is_context_too_large_error(ValueError("connection refused"))
        assert not _is_context_too_large_error(RuntimeError("timeout"))


# ---------------------------------------------------------------------------
# Tests for _format_messages_for_summary
# ---------------------------------------------------------------------------


class TestFormatMessagesForSummary:
    def test_user_assistant_messages(self):
        from framework.agent_loop.agent_loop import AgentLoop as EventLoopNode

        msgs = [
            Message(seq=0, role="user", content="Hello world"),
            Message(seq=1, role="assistant", content="Hi there"),
        ]
        result = EventLoopNode._format_messages_for_summary(msgs)
        assert "[user]: Hello world" in result
        assert "[assistant]: Hi there" in result

    def test_tool_result_truncated(self):
        from framework.agent_loop.agent_loop import AgentLoop as EventLoopNode

        msgs = [
            Message(seq=0, role="tool", content="x" * 1000, tool_use_id="c1"),
        ]
        result = EventLoopNode._format_messages_for_summary(msgs)
        assert "[tool result]:" in result
        assert "..." in result
        # Should be truncated to 500 + "..."
        assert len(result) < 600

    def test_assistant_with_tool_calls(self):
        from framework.agent_loop.agent_loop import AgentLoop as EventLoopNode

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
        from framework.agent_loop.agent_loop import AgentLoop as EventLoopNode
        from framework.agent_loop.internals.types import LoopConfig

        config = LoopConfig(max_context_tokens=32000)
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

        from framework.orchestrator.node import NodeSpec

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

    def test_interleaved_user_messages_hoist_real_result(self):
        """Async user injections between a tool_call and its result must not
        mask the real result with an 'interrupted' stub (worker-report bug)."""
        msgs = [
            {
                "role": "assistant",
                "content": "Hollinden in.",
                "tool_calls": [{"id": "tc_1", "function": {"name": "tracker_sql", "arguments": "{}"}}],
            },
            {"role": "user", "content": "[WORKER_REPORT] Hubcap"},
            {"role": "user", "content": "[WORKER_REPORT] Hivehouse"},
            {"role": "tool", "tool_call_id": "tc_1", "content": '{"success": true}'},
        ]
        repaired = NodeConversation._repair_orphaned_tool_calls(msgs)
        roles = [m["role"] for m in repaired]
        assert roles == ["assistant", "tool", "user", "user"]
        # The real result was hoisted, not replaced by a synthetic error.
        assert repaired[1]["tool_call_id"] == "tc_1"
        assert repaired[1]["content"] == '{"success": true}'
        assert not any("interrupted" in str(m.get("content", "")).lower() for m in repaired)

    def test_injection_splitting_multiple_results(self):
        """Injection lands between results of the same assistant block."""
        msgs = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "tc_1", "function": {"name": "a", "arguments": "{}"}},
                    {"id": "tc_2", "function": {"name": "b", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "tc_1", "content": "r1"},
            {"role": "user", "content": "[WORKER_REPORT]"},
            {"role": "tool", "tool_call_id": "tc_2", "content": "r2"},
        ]
        repaired = NodeConversation._repair_orphaned_tool_calls(msgs)
        roles = [m["role"] for m in repaired]
        assert roles == ["assistant", "tool", "tool", "user"]
        assert repaired[1]["content"] == "r1"
        assert repaired[2]["content"] == "r2"

    def test_hoist_across_later_assistant_block(self):
        """A displaced result found after a later assistant block is hoisted
        to its own tool_call; the later block still pairs normally."""
        msgs = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc_1", "function": {"name": "a", "arguments": "{}"}}],
            },
            {"role": "user", "content": "injected"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "tc_2", "function": {"name": "b", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "tc_1", "content": "r1"},
            {"role": "tool", "tool_call_id": "tc_2", "content": "r2"},
        ]
        repaired = NodeConversation._repair_orphaned_tool_calls(msgs)
        roles = [m["role"] for m in repaired]
        assert roles == ["assistant", "tool", "user", "assistant", "tool"]
        assert repaired[1]["tool_call_id"] == "tc_1"
        assert repaired[1]["content"] == "r1"
        assert repaired[4]["tool_call_id"] == "tc_2"
        assert repaired[4]["content"] == "r2"


# ===================================================================
# Continue-nudge + replay-detector helpers (DS-14)
# ===================================================================


def _mk_assistant_with_tool_call(seq: int, tc_id: str, name: str, args: dict) -> Message:
    return Message(
        seq=seq,
        role="assistant",
        content="",
        tool_calls=[
            {
                "id": tc_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    )


class TestFindCompletedToolCall:
    def test_returns_match_when_prior_non_error_result_exists(self):
        conv = NodeConversation(system_prompt="s")
        conv._messages = [
            Message(seq=0, role="user", content="go"),
            _mk_assistant_with_tool_call(1, "tc_a", "browser_setup", {}),
            Message(seq=2, role="tool", content="ok", tool_use_id="tc_a"),
        ]
        match = conv.find_completed_tool_call("browser_setup", {})
        assert match is not None
        assert match.seq == 1

    def test_ignores_error_result(self):
        conv = NodeConversation(system_prompt="s")
        conv._messages = [
            Message(seq=0, role="user", content="go"),
            _mk_assistant_with_tool_call(1, "tc_a", "browser_navigate", {"url": "x"}),
            Message(seq=2, role="tool", content="boom", tool_use_id="tc_a", is_error=True),
        ]
        assert conv.find_completed_tool_call("browser_navigate", {"url": "x"}) is None

    def test_canonicalizes_json_args_regardless_of_key_order(self):
        conv = NodeConversation(system_prompt="s")
        # Prior args written in one order, new call re-emits in different order.
        conv._messages = [
            Message(seq=0, role="user", content="go"),
            _mk_assistant_with_tool_call(1, "tc_a", "fetch", {"b": 2, "a": 1}),
            Message(seq=2, role="tool", content="ok", tool_use_id="tc_a"),
        ]
        assert conv.find_completed_tool_call("fetch", {"a": 1, "b": 2}) is not None
        # Different args should NOT match.
        assert conv.find_completed_tool_call("fetch", {"a": 1, "b": 3}) is None

    def test_respects_within_last_turns_window(self):
        conv = NodeConversation(system_prompt="s")
        # Prior successful call, then 4 newer assistant turns of noise.
        conv._messages = [
            Message(seq=0, role="user", content="go"),
            _mk_assistant_with_tool_call(1, "tc_a", "browser_setup", {}),
            Message(seq=2, role="tool", content="ok", tool_use_id="tc_a"),
        ]
        # 4 newer assistant turns (no tool calls that match)
        for i in range(3, 7):
            conv._messages.append(Message(seq=i, role="assistant", content=f"noise {i}"))
        # Window=3 → prior assistant with browser_setup is at turn index 5
        # backwards (noise, noise, noise, noise, setup) — skipped.
        assert conv.find_completed_tool_call("browser_setup", {}, within_last_turns=3) is None
        # Window=10 → found.
        assert conv.find_completed_tool_call("browser_setup", {}, within_last_turns=10) is not None


class TestCountConsecutiveCompletedToolCalls:
    def test_returns_zero_when_no_prior(self):
        conv = NodeConversation(system_prompt="s")
        conv._messages = [Message(seq=0, role="user", content="go")]
        assert conv.count_consecutive_completed_tool_calls("get_time", {}) == 0

    def test_counts_three_consecutive_matching_turns(self):
        conv = NodeConversation(system_prompt="s")
        msgs: list[Message] = [Message(seq=0, role="user", content="go")]
        for i in range(3):
            tc_id = f"tc_{i}"
            msgs.append(_mk_assistant_with_tool_call(1 + i * 2, tc_id, "get_time", {"tz": "UTC"}))
            msgs.append(Message(seq=2 + i * 2, role="tool", content="ok", tool_use_id=tc_id))
        conv._messages = msgs
        assert conv.count_consecutive_completed_tool_calls("get_time", {"tz": "UTC"}) == 3

    def test_non_matching_turn_breaks_streak(self):
        conv = NodeConversation(system_prompt="s")
        # 2 matching turns, then 1 turn with a different tool, then 1 matching.
        # Walking back from end, the latest turn matches, the one before is
        # "other" → streak breaks at 1.
        conv._messages = [
            Message(seq=0, role="user", content="go"),
            _mk_assistant_with_tool_call(1, "tc_a", "get_time", {"tz": "UTC"}),
            Message(seq=2, role="tool", content="ok", tool_use_id="tc_a"),
            _mk_assistant_with_tool_call(3, "tc_b", "get_time", {"tz": "UTC"}),
            Message(seq=4, role="tool", content="ok", tool_use_id="tc_b"),
            _mk_assistant_with_tool_call(5, "tc_c", "other_tool", {}),
            Message(seq=6, role="tool", content="ok", tool_use_id="tc_c"),
            _mk_assistant_with_tool_call(7, "tc_d", "get_time", {"tz": "UTC"}),
            Message(seq=8, role="tool", content="ok", tool_use_id="tc_d"),
        ]
        assert conv.count_consecutive_completed_tool_calls("get_time", {"tz": "UTC"}) == 1

    def test_error_result_does_not_count(self):
        conv = NodeConversation(system_prompt="s")
        conv._messages = [
            Message(seq=0, role="user", content="go"),
            _mk_assistant_with_tool_call(1, "tc_a", "get_time", {}),
            Message(seq=2, role="tool", content="boom", tool_use_id="tc_a", is_error=True),
        ]
        assert conv.count_consecutive_completed_tool_calls("get_time", {}) == 0

    def test_canonicalises_args(self):
        conv = NodeConversation(system_prompt="s")
        conv._messages = [
            Message(seq=0, role="user", content="go"),
            _mk_assistant_with_tool_call(1, "tc_a", "fetch", {"b": 2, "a": 1}),
            Message(seq=2, role="tool", content="ok", tool_use_id="tc_a"),
        ]
        assert conv.count_consecutive_completed_tool_calls("fetch", {"a": 1, "b": 2}) == 1
        assert conv.count_consecutive_completed_tool_calls("fetch", {"a": 1, "b": 3}) == 0

    def test_text_only_turn_breaks_streak(self):
        conv = NodeConversation(system_prompt="s")
        # 2 matching turns then a text-only turn (no tool_calls) — streak resets.
        conv._messages = [
            Message(seq=0, role="user", content="go"),
            _mk_assistant_with_tool_call(1, "tc_a", "get_time", {}),
            Message(seq=2, role="tool", content="ok", tool_use_id="tc_a"),
            _mk_assistant_with_tool_call(3, "tc_b", "get_time", {}),
            Message(seq=4, role="tool", content="ok", tool_use_id="tc_b"),
            Message(seq=5, role="assistant", content="just thinking"),
        ]
        assert conv.count_consecutive_completed_tool_calls("get_time", {}) == 0

    def test_respects_within_last_turns_window(self):
        conv = NodeConversation(system_prompt="s")
        msgs: list[Message] = [Message(seq=0, role="user", content="go")]
        for i in range(5):
            tc_id = f"tc_{i}"
            msgs.append(_mk_assistant_with_tool_call(1 + i * 2, tc_id, "get_time", {}))
            msgs.append(Message(seq=2 + i * 2, role="tool", content="ok", tool_use_id=tc_id))
        conv._messages = msgs
        # Window=3 caps the count at 3 even though 5 matching turns exist.
        assert conv.count_consecutive_completed_tool_calls("get_time", {}, within_last_turns=3) == 3
        # Window=10 sees all 5.
        assert conv.count_consecutive_completed_tool_calls("get_time", {}, within_last_turns=10) == 5


class TestPartialCheckpoint:
    @pytest.mark.asyncio
    async def test_checkpoint_is_cleared_when_real_part_lands(self, tmp_path):
        """A partial for seq N is wiped once add_assistant_message(seq=N) persists."""
        store = FileConversationStore(tmp_path / "c")
        conv = NodeConversation(system_prompt="s", store=store)
        await conv.add_user_message("hi")
        # Seed a partial for the would-be next assistant seq.
        await conv.checkpoint_partial_assistant("half-written...")
        partials = await store.read_all_partials()
        assert len(partials) == 1
        assert partials[0]["content"] == "half-written..."
        # Commit the real assistant turn — partial should be swept.
        await conv.add_assistant_message("fully written")
        assert await store.read_all_partials() == []

    @pytest.mark.asyncio
    async def test_restore_surfaces_partial_as_truncated_message(self, tmp_path):
        """A partial left behind by a crashed stream is resurrected on restore."""
        store = FileConversationStore(tmp_path / "c")
        conv = NodeConversation(system_prompt="s", store=store)
        await conv.add_user_message("hi")
        # Simulate a stream that produced some text + a tool call, then died
        # before finishing. The checkpoint captures both.
        await conv.checkpoint_partial_assistant(
            "I was working on this when the stream died",
            tool_calls=[
                {
                    "id": "tc_x",
                    "type": "function",
                    "function": {"name": "browser_click", "arguments": "{}"},
                }
            ],
        )
        # Fresh process — restore from disk.
        fresh = await NodeConversation.restore(store)
        assert fresh is not None
        # The user message is there, plus the truncated assistant resurrected
        # from the partial.
        roles = [m.role for m in fresh.messages]
        assert roles == ["user", "assistant"]
        last = fresh.messages[-1]
        assert last.truncated is True
        assert last.content == "I was working on this when the stream died"
        assert last.tool_calls and last.tool_calls[0]["function"]["name"] == "browser_click"

    @pytest.mark.asyncio
    async def test_restore_cleans_stale_partials(self, tmp_path):
        """A partial whose seq was already committed as a real part is discarded."""
        store = FileConversationStore(tmp_path / "c")
        conv = NodeConversation(system_prompt="s", store=store)
        await conv.add_user_message("hi")
        await conv.add_assistant_message("real")  # seq=1
        # Manually plant a stale partial at seq=1 (already committed).
        await store.write_partial(1, {"seq": 1, "role": "assistant", "content": "stale", "truncated": True})
        fresh = await NodeConversation.restore(store)
        assert fresh is not None
        assert [m.content for m in fresh.messages] == ["hi", "real"]
        # Stale partial swept by restore.
        assert await store.read_all_partials() == []


class TestProactiveMicrocompact:
    """``add_tool_result`` triggers ``microcompact`` when the new result
    pushes the conversation past ``MICROCOMPACT_KEEP_RECENT`` compactable
    tool results in flight. Compactable tools are those in
    ``COMPACTABLE_TOOLS`` (terminal_exec, terminal_rg, browser_*, etc.) —
    their results are re-derivable from their tool name + args, so
    clearing older ones early is a free win.
    """

    @pytest.mark.asyncio
    async def test_over_keep_recent_clears_oldest_recoverably(self) -> None:
        from framework.agent_loop.internals.compaction import MICROCOMPACT_KEEP_RECENT

        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)

        # Seed KEEP_RECENT + 2 terminal_exec results, each with a recorded
        # spillover_path. Once the count exceeds MICROCOMPACT_KEEP_RECENT the
        # oldest are cleared to RECOVERABLE placeholders (cite the spill path),
        # leaving the most recent KEEP_RECENT intact.
        n = MICROCOMPACT_KEEP_RECENT + 2
        for i in range(n):
            await conv.add_assistant_message(
                content="",
                tool_calls=[
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "terminal_exec", "arguments": '{"command": "cat /tmp/x"}'},
                    }
                ],
            )
            big_payload = f"file_{i}_contents: " + ("x" * 200)
            await conv.add_tool_result(
                tool_use_id=f"call_{i}",
                content=big_payload,
                spillover_path=f"/tmp/data/terminal_exec_{i}.txt",
            )

        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        assert len(tool_msgs) == n

        cleared = tool_msgs[: n - MICROCOMPACT_KEEP_RECENT]
        kept = tool_msgs[n - MICROCOMPACT_KEEP_RECENT :]
        for m in cleared:
            assert m.content.startswith("Old tool result"), f"oldest should be cleared, got {m.content[:80]!r}"
            assert "terminal_rg" in m.content and "/tmp/data/terminal_exec_" in m.content, (
                f"cleared placeholder must cite a recovery path, got {m.content!r}"
            )
        for m in kept:
            assert m.content.startswith("file_"), f"recent result should be intact, got {m.content[:80]!r}"

    @pytest.mark.asyncio
    async def test_pathless_results_are_never_cleared(self) -> None:
        """Recoverability invariant: a compactable result with NO spill path
        (and no path in its text) is left INTACT rather than stranded as an
        unrecoverable placeholder — the cause of the re-read loop."""
        from framework.agent_loop.internals.compaction import MICROCOMPACT_KEEP_RECENT

        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)
        for i in range(MICROCOMPACT_KEEP_RECENT + 4):  # well over the keep count
            await conv.add_assistant_message(
                content="",
                tool_calls=[
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "terminal_exec", "arguments": "{}"},
                    }
                ],
            )
            # No spillover_path, and no 'saved at:'/'Full result at:' in the text.
            await conv.add_tool_result(tool_use_id=f"call_{i}", content=f"result_{i} " + ("y" * 200))

        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        for m in tool_msgs:
            assert not m.content.startswith("Old tool result"), f"path-less result must not be cleared, got {m.content[:80]!r}"
            assert m.content.startswith("result_")

    @pytest.mark.asyncio
    async def test_batch_within_keep_recent_all_survive(self) -> None:
        """A batch no larger than KEEP_RECENT survives intact (the fix for a
        batch of read queries losing entries mid-reasoning)."""
        from framework.agent_loop.internals.compaction import MICROCOMPACT_KEEP_RECENT

        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)
        for i in range(MICROCOMPACT_KEEP_RECENT):
            await conv.add_assistant_message(
                content="",
                tool_calls=[{"id": f"c{i}", "type": "function", "function": {"name": "terminal_exec", "arguments": "{}"}}],
            )
            await conv.add_tool_result(tool_use_id=f"c{i}", content="z" * 200, spillover_path=f"/d/e_{i}.txt")
        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        assert all(not m.content.startswith("Old tool result") for m in tool_msgs)

    @pytest.mark.asyncio
    async def test_metadata_spillover_path_preferred_over_text(self) -> None:
        """When a cleared result has a spillover_path AND no path in its text,
        the placeholder cites the metadata path."""
        from framework.agent_loop.internals.compaction import MICROCOMPACT_KEEP_RECENT

        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)
        for i in range(MICROCOMPACT_KEEP_RECENT + 1):
            await conv.add_assistant_message(
                content="",
                tool_calls=[{"id": f"c{i}", "type": "function", "function": {"name": "terminal_exec", "arguments": "{}"}}],
            )
            await conv.add_tool_result(
                tool_use_id=f"c{i}", content=f"payload_{i} " + ("x" * 200), spillover_path=f"/session/data/terminal_exec_{i}.txt"
            )
        oldest = [m for m in conv.messages if m.role == "tool"][0]
        assert oldest.content.startswith("Old tool result")
        assert "/session/data/terminal_exec_0.txt" in oldest.content

    @pytest.mark.asyncio
    async def test_non_compactable_tool_does_not_trigger(self) -> None:
        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)
        # Use a tool name NOT in COMPACTABLE_TOOLS — set_output, write_file
        # are explicit-side-effect tools. set_output is in the allowlist;
        # use a custom name that isn't on the allowlist.
        for i in range(8):
            await conv.add_assistant_message(
                content="",
                tool_calls=[
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "my_custom_irreversible_tool", "arguments": "{}"},
                    }
                ],
            )
            await conv.add_tool_result(tool_use_id=f"call_{i}", content="x" * 200)
        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        assert len(tool_msgs) == 8
        for m in tool_msgs:
            assert not m.content.startswith("Old tool result")

    @pytest.mark.asyncio
    async def test_error_results_skip_microcompact(self) -> None:
        # Error tool results never get microcompacted. Seed 5 errors then
        # confirm none were cleared.
        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)
        for i in range(5):
            await conv.add_assistant_message(
                content="",
                tool_calls=[
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "terminal_exec", "arguments": "{}"},
                    }
                ],
            )
            await conv.add_tool_result(tool_use_id=f"call_{i}", content="ERR " * 50, is_error=True)
        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        for m in tool_msgs:
            assert m.is_error
            assert not m.content.startswith("Old tool result")


class TestSpilloverPathExtraction:
    """``_extract_spillover_filename_inline`` parses spillover paths from
    three placeholder formats:
      * NEW    — "Old tool result (44,754 chars) at /tmp/.../web_scrape_1.txt."
        (emitted by post-density-refactor microcompact + truncate_tool_result)
      * MID    — "...Full data saved at: /tmp/.../web_scrape_1.txt"
        (emitted by the previous prose form; appears in long-lived
        conversations resumed from disk)
      * LEGACY — "[Saved to '/tmp/.../web_scrape_1.txt']"
        (bracketed trailer the framework moved off of in 2026-04;
        still appears in cold-loaded conversations)
    """

    def test_new_format_at_path(self) -> None:
        from framework.agent_loop.internals.compaction import (
            _extract_spillover_filename_inline,
        )

        content = (
            "Old tool result (44,754 chars) at /tmp/data/web_scrape_1.txt. Use terminal_rg with a pattern against this path to recover specifics."
        )
        assert _extract_spillover_filename_inline(content) == "/tmp/data/web_scrape_1.txt"

    def test_mid_saved_at_form(self) -> None:
        from framework.agent_loop.internals.compaction import (
            _extract_spillover_filename_inline,
        )

        content = (
            "Old tool result (44,754 chars) cleared from context. "
            "Full data saved at: /tmp/data/web_scrape_1.txt\n"
            "Read the complete data with read_file(path='/tmp/data/web_scrape_1.txt')."
        )
        # New regex catches the NEW form pattern first ("chars) at /path"
        # — there's no "chars) at" here, so it falls through to the
        # legacy "saved at:" branch.
        assert _extract_spillover_filename_inline(content) == "/tmp/data/web_scrape_1.txt"

    def test_legacy_bracketed_saved_to(self) -> None:
        from framework.agent_loop.internals.compaction import (
            _extract_spillover_filename_inline,
        )

        content = "Some prose. [Saved to '/tmp/data/web_scrape_1.txt']"
        assert _extract_spillover_filename_inline(content) == "/tmp/data/web_scrape_1.txt"

    def test_no_spillover_returns_none(self) -> None:
        from framework.agent_loop.internals.compaction import (
            _extract_spillover_filename_inline,
        )

        assert _extract_spillover_filename_inline("a small tool result") is None
        assert _extract_spillover_filename_inline("Old tool result (44,754 chars) cleared from context.") is None


class TestMicrocompactRecoveryHint:
    """microcompact's placeholder should steer the agent toward
    terminal_rg (ripgrep on the spillover path) rather than read_file.
    Re-reading the full file would hit max_tool_result_chars and force
    pagination; rg returns only matching lines."""

    @pytest.mark.asyncio
    async def test_placeholder_recommends_terminal_rg(self) -> None:
        from framework.agent_loop.internals.compaction import MICROCOMPACT_KEEP_RECENT

        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)
        # Seed enough results to exceed KEEP_RECENT so the oldest is cleared,
        # with a spillover path embedded in the text (proves text extraction
        # still works as a fallback).
        for i in range(MICROCOMPACT_KEEP_RECENT + 2):
            await conv.add_assistant_message(
                content="",
                tool_calls=[
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {"name": "terminal_exec", "arguments": "{}"},
                    }
                ],
            )
            payload = f"file_{i}_head_content " + ("x" * 200) + f"\nsaved at: /tmp/data/file_{i}.txt"
            await conv.add_tool_result(tool_use_id=f"call_{i}", content=payload)

        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        cleared = tool_msgs[0]
        assert "terminal_rg" in cleared.content, f"Expected terminal_rg recovery hint, got: {cleared.content!r}"
        assert "read_file" not in cleared.content, f"Should NOT push read_file (it would re-truncate), got: {cleared.content!r}"


class TestMessageFlags:
    def test_is_system_reminder_roundtrip(self):
        m = Message(seq=0, role="user", content="reminder", is_system_reminder=True)
        d = m.to_storage_dict()
        assert d.get("is_system_reminder") is True
        r = Message.from_storage_dict(d)
        assert r.is_system_reminder is True
        assert r.role == "user"

    def test_is_system_reminder_loads_legacy_key(self):
        """Conversations persisted before the rename used is_system_nudge."""
        r = Message.from_storage_dict({"seq": 0, "role": "user", "content": "x", "is_system_nudge": True})
        assert r.is_system_reminder is True

    def test_truncated_roundtrip(self):
        m = Message(seq=0, role="assistant", content="half", truncated=True)
        d = m.to_storage_dict()
        assert d.get("truncated") is True
        r = Message.from_storage_dict(d)
        assert r.truncated is True

    def test_defaults_omit_flags_from_storage(self):
        m = Message(seq=0, role="user", content="plain")
        d = m.to_storage_dict()
        assert "is_system_reminder" not in d
        assert "truncated" not in d


# ---------------------------------------------------------------------------
# Defensive truncation guard for oversized user messages.
#
# The upload-path size gate (Layer E) prevents huge PDFs from ever landing
# as a giant user message going forward. But sessions persisted before
# that gate shipped (or any future bug that bypasses it) could still leave
# a multi-MB user message in the conversation. Compaction itself would
# choke trying to summarize it, leaving the loop stuck. The guard runs at
# the start of every compact() pass.
# ---------------------------------------------------------------------------


class TestTruncateOversizedUserMessages:
    """``truncate_oversized_user_messages`` clips user messages past
    :data:`USER_MESSAGE_MAX_CHARS` so compaction can survive historical
    bloat (e.g. a 2.4 MB calc-textbook text-prepend persisted before
    Layer E shipped)."""

    def test_small_message_untouched(self) -> None:
        from framework.agent_loop.internals.compaction import (
            truncate_oversized_user_messages,
        )

        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)
        conv._messages.append(Message(seq=0, role="user", content="hello", is_client_input=True))

        clipped = truncate_oversized_user_messages(conv)
        assert clipped == 0
        assert conv.messages[0].content == "hello"

    def test_oversized_user_message_clipped(self) -> None:
        from framework.agent_loop.internals.compaction import (
            USER_MESSAGE_HEAD_CHARS,
            USER_MESSAGE_MAX_CHARS,
            truncate_oversized_user_messages,
        )

        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)
        head_marker = "USER_TYPED_THIS_PREFIX " * 50  # ~1.2 KB
        tail_marker = "[Attachments saved to disk]\n- PDF: /path/to/doc.pdf"
        # Roughly 500 KB of filler in the middle — well past the threshold.
        oversized = head_marker + ("FILLER" * 100_000) + "\n" + tail_marker
        assert len(oversized) > USER_MESSAGE_MAX_CHARS

        conv._messages.append(Message(seq=0, role="user", content=oversized, is_client_input=True))

        clipped = truncate_oversized_user_messages(conv)
        assert clipped == 1
        new_content = conv.messages[0].content
        # Result is small: head + reminder + tail, no filler in between.
        assert len(new_content) < USER_MESSAGE_MAX_CHARS
        # Head and tail are preserved verbatim — that's how the agent
        # retains the original message's intent + the attachments hint.
        assert new_content.startswith(head_marker[:USER_MESSAGE_HEAD_CHARS])
        assert new_content.endswith(tail_marker)
        # The truncation marker is a system-reminder so the LLM treats
        # it as framework metadata, not user speech.
        assert "<system-reminder>" in new_content
        assert "chars truncated" in new_content

    def test_skips_system_reminder_messages(self) -> None:
        """Framework-injected reminders are not user input — leave them
        alone even if they grow large (idle nudges, etc. could in theory
        accumulate)."""
        from framework.agent_loop.internals.compaction import (
            truncate_oversized_user_messages,
        )

        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)
        huge = "x" * 500_000
        conv._messages.append(
            Message(
                seq=0,
                role="user",
                content=huge,
                is_client_input=False,
                is_system_reminder=True,
            )
        )

        clipped = truncate_oversized_user_messages(conv)
        assert clipped == 0
        assert conv.messages[0].content == huge

    def test_skips_skill_content_messages(self) -> None:
        from framework.agent_loop.internals.compaction import (
            truncate_oversized_user_messages,
        )

        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)
        huge_skill = "skill body " * 50_000
        conv._messages.append(
            Message(
                seq=0,
                role="user",
                content=huge_skill,
                is_skill_content=True,
            )
        )

        clipped = truncate_oversized_user_messages(conv)
        assert clipped == 0
        assert conv.messages[0].content == huge_skill

    def test_skips_non_user_roles(self) -> None:
        """Tool and assistant messages have their own pruning paths
        (microcompact, prune_old_tool_results); the user-message guard
        must not interfere."""
        from framework.agent_loop.internals.compaction import (
            truncate_oversized_user_messages,
        )

        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)
        huge = "x" * 500_000
        conv._messages.append(Message(seq=0, role="assistant", content=huge))
        conv._messages.append(Message(seq=1, role="tool", content=huge, tool_use_id="t1"))

        clipped = truncate_oversized_user_messages(conv)
        assert clipped == 0
        assert conv.messages[0].content == huge
        assert conv.messages[1].content == huge

    def test_idempotent_on_already_clipped(self) -> None:
        """Re-running the guard on already-truncated messages must be a
        no-op — the head + reminder + tail sit well under the threshold."""
        from framework.agent_loop.internals.compaction import (
            truncate_oversized_user_messages,
        )

        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)
        oversized = "x" * 500_000
        conv._messages.append(Message(seq=0, role="user", content=oversized, is_client_input=True))

        first = truncate_oversized_user_messages(conv)
        assert first == 1
        second = truncate_oversized_user_messages(conv)
        assert second == 0

    def test_calc_textbook_scenario(self) -> None:
        """End-to-end repro of the failure mode: two 2.4 MB user messages
        (identical PDF text-prepends from twice-uploaded calc textbook).
        Both clipped, conversation total drops by orders of magnitude."""
        from framework.agent_loop.internals.compaction import (
            USER_MESSAGE_MAX_CHARS,
            truncate_oversized_user_messages,
        )

        conv = NodeConversation(system_prompt="sys", max_context_tokens=10_000)
        textbook = (
            "[2026-05-21 16:40 PDT] teach me calculus 1\n\n"
            "--- Attached file content ---\n"
            + ("[PDF page N] dense math content " * 50_000)
            + "\n\n[Attachments saved to disk]\n- PDF: data/attachments/X.pdf"
        )
        original_size = len(textbook)
        conv._messages.append(Message(seq=0, role="user", content=textbook, is_client_input=True))
        conv._messages.append(Message(seq=1, role="user", content=textbook, is_client_input=True))

        clipped = truncate_oversized_user_messages(conv)
        assert clipped == 2
        total_after = sum(len(m.content) for m in conv.messages)
        # 2 × 2.4 MB → ~16 KB total. Orders of magnitude.
        assert total_after < USER_MESSAGE_MAX_CHARS, (
            f"Expected post-truncate total < {USER_MESSAGE_MAX_CHARS}, got {total_after} (orig {original_size * 2})"
        )
        for m in conv.messages:
            # Each retains the typed prompt and the attachments hint.
            assert "teach me calculus 1" in m.content
            assert "[Attachments saved to disk]" in m.content


# ---------------------------------------------------------------------------
# Tool-result image hoisting
# ---------------------------------------------------------------------------

IMG_A = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAA"}}
IMG_B = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,BBB"}}


class TestHoistToolResultImages:
    """Screenshots must reach models whose API drops tool-result images.

    Regression: on an OpenAI-compatible endpoint the agent took a
    screenshot, got a tool result describing an image the provider had
    silently stripped, and spent the rest of the session insisting it
    could not see.
    """

    @staticmethod
    async def _screenshot_turn(model: str | None) -> list[dict[str, Any]]:
        conv = NodeConversation(system_prompt="sys")
        await conv.add_user_message("take a screenshot")
        await conv.add_assistant_message(
            "",
            tool_calls=[{"id": "c1", "type": "function", "function": {"name": "browser_screenshot", "arguments": "{}"}}],
        )
        await conv.add_tool_result(tool_use_id="c1", content='{"ok": true}', image_content=[IMG_A])
        return conv.to_llm_messages(model) if model is not None else conv.to_llm_messages()

    @pytest.mark.asyncio
    async def test_openai_model_receives_image_as_user_message(self):
        msgs = await self._screenshot_turn("openai/gpt-6-astra")

        tool_msg = next(m for m in msgs if m["role"] == "tool")
        assert tool_msg["content"] == '{"ok": true}', "tool result keeps its text"

        hoisted = msgs[-1]
        assert hoisted["role"] == "user"
        assert hoisted["content"][1] == IMG_A
        # The label names the call so the model can tie image to tool.
        assert "browser_screenshot" in hoisted["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_anthropic_model_keeps_image_in_tool_result(self):
        msgs = await self._screenshot_turn("anthropic/claude-opus-4-6")

        tool_msg = next(m for m in msgs if m["role"] == "tool")
        assert tool_msg["content"][1] == IMG_A
        assert not any(m["role"] == "user" and isinstance(m["content"], list) for m in msgs)

    @pytest.mark.asyncio
    async def test_no_model_leaves_shape_untouched(self):
        msgs = await self._screenshot_turn(None)
        tool_msg = next(m for m in msgs if m["role"] == "tool")
        assert tool_msg["content"][1] == IMG_A

    @pytest.mark.asyncio
    async def test_parallel_tool_results_stay_contiguous(self):
        """All tool results must land before any other role, or the API
        400s on the tool message that follows a user turn."""
        conv = NodeConversation(system_prompt="sys")
        await conv.add_user_message("screenshot both tabs")
        await conv.add_assistant_message(
            "",
            tool_calls=[
                {"id": "c1", "type": "function", "function": {"name": "browser_screenshot", "arguments": "{}"}},
                {"id": "c2", "type": "function", "function": {"name": "attach_file", "arguments": "{}"}},
            ],
        )
        await conv.add_tool_result(tool_use_id="c1", content="tab one", image_content=[IMG_A])
        await conv.add_tool_result(tool_use_id="c2", content="tab two", image_content=[IMG_B])

        msgs = conv.to_llm_messages("openai/gpt-6-astra")

        roles = [m["role"] for m in msgs]
        assert roles == ["user", "assistant", "tool", "tool", "user"]
        # Both images ride in the single trailing user message, in order.
        blocks = msgs[-1]["content"]
        assert blocks[1:] == [IMG_A, IMG_B]
        assert "browser_screenshot (1)" in blocks[0]["text"]
        assert "attach_file (1)" in blocks[0]["text"]

    @pytest.mark.asyncio
    async def test_hoisted_images_merge_with_a_following_user_message(self):
        """A user reply right after the tool turn must not leave two
        consecutive user messages behind."""
        conv = NodeConversation(system_prompt="sys")
        await conv.add_user_message("look")
        await conv.add_assistant_message(
            "",
            tool_calls=[{"id": "c1", "type": "function", "function": {"name": "browser_screenshot", "arguments": "{}"}}],
        )
        await conv.add_tool_result(tool_use_id="c1", content="ok", image_content=[IMG_A])
        await conv.add_user_message("what do you see?")

        msgs = conv.to_llm_messages("openai/gpt-6-astra")

        assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "user"]
        blocks = msgs[-1]["content"]
        assert IMG_A in blocks
        assert blocks[-1]["text"] == "what do you see?"

    @pytest.mark.asyncio
    async def test_text_only_tool_results_are_untouched(self):
        conv = NodeConversation(system_prompt="sys")
        await conv.add_user_message("run it")
        await conv.add_assistant_message(
            "",
            tool_calls=[{"id": "c1", "type": "function", "function": {"name": "terminal_exec", "arguments": "{}"}}],
        )
        await conv.add_tool_result(tool_use_id="c1", content="exit 0")

        assert conv.to_llm_messages("openai/gpt-6-astra") == conv.to_llm_messages("anthropic/claude-opus-4-6")

    @pytest.mark.asyncio
    async def test_stored_image_content_survives_hoisting(self):
        """Hoisting shapes the request only — eviction, persistence and the
        UI all read Message.image_content and must still find it."""
        conv = NodeConversation(system_prompt="sys")
        await conv.add_user_message("look")
        await conv.add_assistant_message(
            "",
            tool_calls=[{"id": "c1", "type": "function", "function": {"name": "browser_screenshot", "arguments": "{}"}}],
        )
        await conv.add_tool_result(tool_use_id="c1", content="ok", image_content=[IMG_A])

        conv.to_llm_messages("openai/gpt-6-astra")

        assert conv.messages[-1].image_content == [IMG_A]
