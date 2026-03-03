"""Tests for phase-aware compaction in continuous conversation mode.

Validates:
  - Phase tags persist through storage roundtrip
  - Transition markers survive compaction
  - Current phase messages protected during compaction
  - Older phase tool results pruned first
  - Phase metadata fields have safe defaults
"""

from __future__ import annotations

import pytest

from framework.graph.conversation import Message, NodeConversation


class TestPhaseMetadata:
    """Phase metadata on Message dataclass."""

    def test_defaults(self):
        msg = Message(seq=0, role="user", content="hello")
        assert msg.phase_id is None
        assert msg.is_transition_marker is False

    def test_set_phase(self):
        msg = Message(seq=0, role="user", content="hello", phase_id="research")
        assert msg.phase_id == "research"

    def test_transition_marker(self):
        msg = Message(
            seq=0,
            role="user",
            content="PHASE TRANSITION",
            is_transition_marker=True,
            phase_id="report",
        )
        assert msg.is_transition_marker is True
        assert msg.phase_id == "report"

    def test_storage_roundtrip(self):
        """Phase metadata should survive to_storage_dict → from_storage_dict."""
        msg = Message(
            seq=5,
            role="user",
            content="transition",
            phase_id="review",
            is_transition_marker=True,
        )
        d = msg.to_storage_dict()
        assert d["phase_id"] == "review"
        assert d["is_transition_marker"] is True

        restored = Message.from_storage_dict(d)
        assert restored.phase_id == "review"
        assert restored.is_transition_marker is True

    def test_storage_roundtrip_no_phase(self):
        """Messages without phase metadata should roundtrip cleanly."""
        msg = Message(seq=0, role="assistant", content="hello")
        d = msg.to_storage_dict()
        assert "phase_id" not in d
        assert "is_transition_marker" not in d

        restored = Message.from_storage_dict(d)
        assert restored.phase_id is None
        assert restored.is_transition_marker is False

    def test_to_llm_dict_no_metadata(self):
        """Phase metadata should NOT appear in LLM-facing dicts."""
        msg = Message(
            seq=0,
            role="user",
            content="hello",
            phase_id="research",
            is_transition_marker=True,
        )
        d = msg.to_llm_dict()
        assert "phase_id" not in d
        assert "is_transition_marker" not in d
        assert d == {"role": "user", "content": "hello"}


class TestPhaseStamping:
    """Messages are stamped with current phase."""

    @pytest.mark.asyncio
    async def test_messages_stamped_with_phase(self):
        conv = NodeConversation(system_prompt="test")
        conv.set_current_phase("research")

        msg1 = await conv.add_user_message("search for X")
        msg2 = await conv.add_assistant_message("Found it.")

        assert msg1.phase_id == "research"
        assert msg2.phase_id == "research"

    @pytest.mark.asyncio
    async def test_phase_changes_stamp(self):
        conv = NodeConversation(system_prompt="test")
        conv.set_current_phase("research")

        msg1 = await conv.add_user_message("research msg")

        conv.set_current_phase("report")
        msg2 = await conv.add_user_message("report msg")

        assert msg1.phase_id == "research"
        assert msg2.phase_id == "report"

    @pytest.mark.asyncio
    async def test_no_phase_no_stamp(self):
        conv = NodeConversation(system_prompt="test")
        msg = await conv.add_user_message("no phase")
        assert msg.phase_id is None

    @pytest.mark.asyncio
    async def test_transition_marker_flag(self):
        conv = NodeConversation(system_prompt="test")
        conv.set_current_phase("report")

        msg = await conv.add_user_message(
            "PHASE TRANSITION: Research → Report",
            is_transition_marker=True,
        )
        assert msg.is_transition_marker is True
        assert msg.phase_id == "report"

    @pytest.mark.asyncio
    async def test_tool_result_stamped(self):
        conv = NodeConversation(system_prompt="test")
        conv.set_current_phase("research")

        msg = await conv.add_tool_result("call_1", "tool output here")
        assert msg.phase_id == "research"


class TestPhaseAwareCompaction:
    """prune_old_tool_results protects current phase and transition markers."""

    @pytest.mark.asyncio
    async def test_transition_marker_survives_compaction(self):
        """Transition markers should never be pruned."""
        conv = NodeConversation(system_prompt="test")

        # Old phase with a big tool result
        conv.set_current_phase("research")
        await conv.add_assistant_message(
            "calling tool",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{}"},
                }
            ],
        )
        await conv.add_tool_result("call_1", "x" * 20000)  # big tool result

        # Transition marker
        await conv.add_user_message(
            "PHASE TRANSITION: Research → Report",
            is_transition_marker=True,
        )

        # New phase
        conv.set_current_phase("report")
        await conv.add_assistant_message(
            "calling another tool",
            tool_calls=[
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "save", "arguments": "{}"},
                }
            ],
        )
        await conv.add_tool_result("call_2", "y" * 200)

        pruned = await conv.prune_old_tool_results(protect_tokens=0, min_prune_tokens=100)
        assert pruned >= 1

        # Transition marker should still be intact
        marker_msgs = [m for m in conv.messages if m.is_transition_marker]
        assert len(marker_msgs) == 1
        assert "PHASE TRANSITION" in marker_msgs[0].content

    @pytest.mark.asyncio
    async def test_current_phase_protected(self):
        """Tool results in the current phase should not be pruned."""
        conv = NodeConversation(system_prompt="test")

        # Old phase
        conv.set_current_phase("research")
        await conv.add_assistant_message(
            "tool call",
            tool_calls=[
                {"id": "c1", "type": "function", "function": {"name": "s", "arguments": "{}"}}
            ],
        )
        await conv.add_tool_result("c1", "old_data " * 5000)

        # Current phase
        conv.set_current_phase("report")
        await conv.add_assistant_message(
            "tool call",
            tool_calls=[
                {"id": "c2", "type": "function", "function": {"name": "s", "arguments": "{}"}}
            ],
        )
        await conv.add_tool_result("c2", "current_data " * 5000)

        await conv.prune_old_tool_results(protect_tokens=0, min_prune_tokens=100)

        # Old phase's tool result should be pruned
        msgs = conv.messages
        old_tool = [m for m in msgs if m.role == "tool" and m.phase_id == "research"]
        assert len(old_tool) == 1
        assert old_tool[0].content.startswith("[Pruned tool result")

        # Current phase's tool result should be intact
        current_tool = [m for m in msgs if m.role == "tool" and m.phase_id == "report"]
        assert len(current_tool) == 1
        assert "current_data" in current_tool[0].content

    @pytest.mark.asyncio
    async def test_no_phase_metadata_works_normally(self):
        """Without phase metadata, compaction works as before (no regression)."""
        conv = NodeConversation(system_prompt="test")

        # No phase set — messages have phase_id=None
        await conv.add_assistant_message(
            "tool call",
            tool_calls=[
                {"id": "c1", "type": "function", "function": {"name": "s", "arguments": "{}"}}
            ],
        )
        await conv.add_tool_result("c1", "data " * 5000)  # ~6250 tokens

        await conv.add_assistant_message(
            "another tool call",
            tool_calls=[
                {"id": "c2", "type": "function", "function": {"name": "s", "arguments": "{}"}}
            ],
        )
        await conv.add_tool_result("c2", "more " * 100)  # ~125 tokens

        # protect_tokens=100: c2 (~125 tokens) fills the budget,
        # c1 (~6250 tokens) becomes pruneable
        pruned = await conv.prune_old_tool_results(protect_tokens=100, min_prune_tokens=100)
        assert pruned >= 1

    @pytest.mark.asyncio
    async def test_pruned_message_preserves_phase_metadata(self):
        """Pruned messages should keep their phase_id."""
        conv = NodeConversation(system_prompt="test")
        conv.set_current_phase("research")

        await conv.add_assistant_message(
            "tool call",
            tool_calls=[
                {"id": "c1", "type": "function", "function": {"name": "s", "arguments": "{}"}}
            ],
        )
        await conv.add_tool_result("c1", "data " * 5000)

        # Switch to new phase so research messages become pruneable
        conv.set_current_phase("report")
        await conv.add_assistant_message(
            "recent",
            tool_calls=[
                {"id": "c2", "type": "function", "function": {"name": "s", "arguments": "{}"}}
            ],
        )
        await conv.add_tool_result("c2", "x" * 200)

        await conv.prune_old_tool_results(protect_tokens=0, min_prune_tokens=100)

        pruned_msg = [m for m in conv.messages if m.content.startswith("[Pruned")][0]
        assert pruned_msg.phase_id == "research"
