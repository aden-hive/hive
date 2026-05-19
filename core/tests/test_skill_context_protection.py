"""Tests for AS-10: Activated skill content protected from context pruning."""

import pytest

from framework.graph.conversation import Message, NodeConversation


def _make_conversation() -> NodeConversation:
    conv = NodeConversation.__new__(NodeConversation)
    conv._messages = []
    conv._next_seq = 0
    conv._current_phase = None
    conv._store = None
    return conv


async def _add_tool_msg(conv: NodeConversation, content: str, **kwargs) -> Message:
    return await conv.add_tool_result(
        tool_use_id=f"tc-{conv._next_seq}",
        content=content,
        **kwargs,
    )


class TestSkillContentProtection:
    @pytest.mark.asyncio
    async def test_is_skill_content_flag_persists(self):
        """Message created with is_skill_content=True retains the flag."""
        conv = _make_conversation()
        msg = await _add_tool_msg(conv, "skill instructions", is_skill_content=True)
        assert msg.is_skill_content is True

    @pytest.mark.asyncio
    async def test_regular_message_not_marked(self):
        """Normal tool result messages are not marked as skill content."""
        conv = _make_conversation()
        msg = await _add_tool_msg(conv, "some tool output")
        assert msg.is_skill_content is False

    @pytest.mark.asyncio
    async def test_skill_content_survives_prune(self):
        """Skill content messages are skipped by prune_old_tool_results."""
        conv = _make_conversation()

        # Add many regular tool results to push over prune threshold
        for _ in range(30):
            await _add_tool_msg(conv, "x" * 500)  # ~125 tokens each

        # Add a skill content message
        skill_msg = await _add_tool_msg(
            conv,
            "## Deep Research\n" + "instructions " * 200,
            is_skill_content=True,
        )

        pruned = await conv.prune_old_tool_results(protect_tokens=500, min_prune_tokens=100)

        assert pruned > 0, "Expected some messages to be pruned"
        # Find the skill message — it must not be pruned
        matching = [m for m in conv._messages if m.seq == skill_msg.seq]
        assert matching, "Skill content message was removed"
        assert not matching[0].content.startswith("[Pruned tool result")

    @pytest.mark.asyncio
    async def test_regular_content_can_be_pruned(self):
        """Regular tool results are still pruned when over threshold."""
        conv = _make_conversation()

        for _ in range(20):
            await _add_tool_msg(conv, "regular tool output " * 50)

        pruned = await conv.prune_old_tool_results(protect_tokens=500, min_prune_tokens=100)

        assert pruned > 0, "Expected regular messages to be pruned"

    @pytest.mark.asyncio
    async def test_error_messages_also_protected(self):
        """Existing is_error protection still works alongside is_skill_content."""
        conv = _make_conversation()

        for _ in range(20):
            await _add_tool_msg(conv, "output " * 100)

        err_msg = await _add_tool_msg(conv, "tool failed", is_error=True)

        await conv.prune_old_tool_results(protect_tokens=200, min_prune_tokens=50)

        matching = [m for m in conv._messages if m.seq == err_msg.seq]
        assert matching
        assert not matching[0].content.startswith("[Pruned tool result")
