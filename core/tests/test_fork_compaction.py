"""Colony fork compaction: sized to its input, skipped when the chat is small.

Regression: forking a 69k-char DM into a colony asked the model for a
360k-char "summary" (half the 180k window, regardless of input). It wrote
40k chars in 261s, the fork's 180s cap always fired, and every colony
creation sat on "Creating…" for three minutes before opening on the raw
transcript anyway.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from framework.agent_loop.conversation import NodeConversation
from framework.agent_loop.internals.compaction import compaction_target_chars
from framework.server.routes_execution import _compact_inherited_conversation
from framework.storage.conversation_store import FileConversationStore


def test_target_never_outgrows_the_input():
    assert compaction_target_chars(69_271, 180_000) == 34_635


def test_target_still_caps_at_half_the_window_for_large_inputs():
    assert compaction_target_chars(2_000_000, 180_000) == 360_000


def test_target_has_a_floor_for_tiny_inputs():
    assert compaction_target_chars(500, 180_000) == 2_000


class _NoCallsLLM:
    async def acomplete(self, **_kwargs):
        raise AssertionError("a small inherited chat must not be sent for compaction")


async def _write_chat(queen_dir, n_turns: int) -> list[dict]:
    conv = NodeConversation(system_prompt="", store=FileConversationStore(queen_dir / "conversations"))
    for i in range(n_turns):
        await conv.add_user_message(f"request {i}", is_client_input=True)
        await conv.add_assistant_message(f"done {i}")
    return await FileConversationStore(queen_dir / "conversations").read_parts()


@pytest.mark.asyncio
async def test_small_inherited_chat_is_kept_verbatim_without_an_llm_call(tmp_path):
    before = await _write_chat(tmp_path, n_turns=5)

    await _compact_inherited_conversation(
        dest_queen_dir=tmp_path,
        queen_ctx=SimpleNamespace(llm=_NoCallsLLM()),
        queen_loop=SimpleNamespace(_config=SimpleNamespace(max_context_tokens=180_000)),
        source_session_id="session_src",
    )

    assert await FileConversationStore(tmp_path / "conversations").read_parts() == before
    # The fork boundary is still marked, so the UI groups the inherited turns.
    markers = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert markers[-1]["type"] == "colony_fork_marker"
    assert markers[-1]["data"]["inherited_message_count"] == len(before)


@pytest.mark.asyncio
async def test_large_inherited_chat_is_still_compacted(tmp_path):
    await _write_chat(tmp_path, n_turns=3)
    calls = []

    class _LLM:
        async def acomplete(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(content="summary")

    # A tiny window makes even this chat "large".
    await _compact_inherited_conversation(
        dest_queen_dir=tmp_path,
        queen_ctx=SimpleNamespace(llm=_LLM(), agent_spec=SimpleNamespace(name="q", id="q", description="", success_criteria="", output_keys=[])),
        queen_loop=SimpleNamespace(_config=SimpleNamespace(max_context_tokens=40)),
        source_session_id="session_src",
    )

    assert len(calls) == 1
    parts = await FileConversationStore(tmp_path / "conversations").read_parts()
    assert len(parts) == 1 and "summary" in parts[0]["content"]
