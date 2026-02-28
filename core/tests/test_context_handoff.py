"""Tests for ContextHandoff and HandoffContext."""

from __future__ import annotations

from typing import Any

import pytest

from framework.graph.context_handoff import ContextHandoff, HandoffContext
from framework.graph.conversation import NodeConversation
from framework.llm.mock import MockLLMProvider
from framework.llm.provider import LLMProvider, LLMResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SpyLLMProvider(MockLLMProvider):
    """MockLLMProvider that records whether complete() was called."""

    def __init__(self) -> None:
        super().__init__()
        self.complete_called = False
        self.complete_call_args: dict[str, Any] | None = None

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.complete_called = True
        self.complete_call_args = {"messages": messages, **kwargs}
        return super().complete(messages, **kwargs)


class FailingLLMProvider(LLMProvider):
    """LLM provider that always raises."""

    def complete(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        raise RuntimeError("LLM unavailable")


async def _build_conversation(*pairs: tuple[str, str]) -> NodeConversation:
    """Build a NodeConversation from (user, assistant) message pairs."""
    conv = NodeConversation()
    for user_msg, assistant_msg in pairs:
        await conv.add_user_message(user_msg)
        await conv.add_assistant_message(assistant_msg)
    return conv


# ---------------------------------------------------------------------------
# TestHandoffContext
# ---------------------------------------------------------------------------


class TestHandoffContext:
    def test_instantiation(self) -> None:
        hc = HandoffContext(
            source_node_id="node_A",
            summary="Summary text",
            key_outputs={"result": "42"},
            turn_count=3,
            total_tokens_used=1200,
        )
        assert hc.source_node_id == "node_A"
        assert hc.summary == "Summary text"
        assert hc.key_outputs == {"result": "42"}
        assert hc.turn_count == 3
        assert hc.total_tokens_used == 1200

    def test_field_access(self) -> None:
        hc = HandoffContext(
            source_node_id="n1",
            summary="s",
            key_outputs={},
            turn_count=0,
            total_tokens_used=0,
        )
        assert hc.key_outputs == {}


# ---------------------------------------------------------------------------
# TestExtractiveSummary
# ---------------------------------------------------------------------------


class TestExtractiveSummary:
    @pytest.mark.asyncio
    async def test_extractive_summary_includes_first_last(self) -> None:
        conv = await _build_conversation(
            ("hello", "First response here."),
            ("continue", "Middle response."),
            ("finish", "Final conclusion."),
        )
        ch = ContextHandoff()
        hc = ch.summarize_conversation(conv, node_id="test_node")

        assert "First response here." in hc.summary
        assert "Final conclusion." in hc.summary

    @pytest.mark.asyncio
    async def test_extractive_summary_metadata(self) -> None:
        conv = await _build_conversation(
            ("hi", "hello"),
            ("bye", "goodbye"),
        )
        ch = ContextHandoff()
        hc = ch.summarize_conversation(conv, node_id="node_42")

        assert hc.source_node_id == "node_42"
        assert hc.turn_count == 2
        assert hc.total_tokens_used > 0

    @pytest.mark.asyncio
    async def test_extractive_with_output_keys_colon(self) -> None:
        conv = await _build_conversation(
            ("what is the answer?", "answer: 42"),
        )
        ch = ContextHandoff()
        hc = ch.summarize_conversation(conv, node_id="n", output_keys=["answer"])

        assert hc.key_outputs["answer"] == "42"

    @pytest.mark.asyncio
    async def test_extractive_with_output_keys_equals(self) -> None:
        conv = await _build_conversation(
            ("compute", "result = success"),
        )
        ch = ContextHandoff()
        hc = ch.summarize_conversation(conv, node_id="n", output_keys=["result"])

        assert hc.key_outputs["result"] == "success"

    @pytest.mark.asyncio
    async def test_extractive_json_output_keys(self) -> None:
        conv = await _build_conversation(
            ("give me json", '{"score": 95, "grade": "A"}'),
        )
        ch = ContextHandoff()
        hc = ch.summarize_conversation(conv, node_id="n", output_keys=["score", "grade"])

        assert hc.key_outputs["score"] == "95"
        assert hc.key_outputs["grade"] == "A"

    @pytest.mark.asyncio
    async def test_extractive_empty_conversation(self) -> None:
        conv = NodeConversation()
        ch = ContextHandoff()
        hc = ch.summarize_conversation(conv, node_id="empty")

        assert hc.summary == "Empty conversation."
        assert hc.turn_count == 0
        assert hc.key_outputs == {}

    @pytest.mark.asyncio
    async def test_extractive_no_assistant_messages(self) -> None:
        conv = NodeConversation()
        await conv.add_user_message("hello?")
        await conv.add_user_message("anyone there?")

        ch = ContextHandoff()
        hc = ch.summarize_conversation(conv, node_id="silent")

        assert hc.summary == "No assistant responses."

    @pytest.mark.asyncio
    async def test_extractive_most_recent_wins(self) -> None:
        conv = await _build_conversation(
            ("first", "status: old_value"),
            ("second", "status: new_value"),
        )
        ch = ContextHandoff()
        hc = ch.summarize_conversation(conv, node_id="n", output_keys=["status"])

        assert hc.key_outputs["status"] == "new_value"

    @pytest.mark.asyncio
    async def test_extractive_truncation(self) -> None:
        long_text = "x" * 1000
        conv = await _build_conversation(
            ("go", long_text),
        )
        ch = ContextHandoff()
        hc = ch.summarize_conversation(conv, node_id="n")

        # Summary should be truncated to ~500 chars
        assert len(hc.summary) <= 500


# ---------------------------------------------------------------------------
# TestLLMSummary
# ---------------------------------------------------------------------------


class TestLLMSummary:
    @pytest.mark.asyncio
    async def test_llm_summary_calls_provider(self) -> None:
        llm = SpyLLMProvider()
        conv = await _build_conversation(
            ("hi", "hello back"),
            ("what now?", "we are done"),
        )
        ch = ContextHandoff(llm=llm)
        hc = ch.summarize_conversation(conv, node_id="llm_node")

        assert llm.complete_called, "LLM complete() was never invoked"
        assert hc.summary == "This is a mock response for testing purposes."

    @pytest.mark.asyncio
    async def test_llm_summary_includes_output_key_hint(self) -> None:
        llm = SpyLLMProvider()
        conv = await _build_conversation(
            ("compute", '{"score": 95}'),
        )
        ch = ContextHandoff(llm=llm)
        ch.summarize_conversation(conv, node_id="n", output_keys=["score", "grade"])

        assert llm.complete_call_args is not None
        system = llm.complete_call_args.get("system", "")
        assert "score" in system
        assert "grade" in system

    @pytest.mark.asyncio
    async def test_llm_fallback_on_error(self) -> None:
        llm = FailingLLMProvider()
        conv = await _build_conversation(
            ("start", "First assistant message."),
            ("end", "Last assistant message."),
        )
        ch = ContextHandoff(llm=llm)
        hc = ch.summarize_conversation(conv, node_id="fallback_node")

        # Should fall back to extractive (first + last assistant messages)
        assert "First assistant message." in hc.summary
        assert "Last assistant message." in hc.summary


# ---------------------------------------------------------------------------
# TestFormatAsInput
# ---------------------------------------------------------------------------


class TestFormatAsInput:
    def test_format_structure(self) -> None:
        hc = HandoffContext(
            source_node_id="analyzer",
            summary="Analysis complete.",
            key_outputs={"score": "95"},
            turn_count=5,
            total_tokens_used=2000,
        )
        output = ContextHandoff.format_as_input(hc)

        assert "--- CONTEXT FROM: analyzer" in output
        assert "KEY OUTPUTS:" in output
        assert "SUMMARY:" in output
        assert "--- END CONTEXT ---" in output

    def test_format_no_key_outputs(self) -> None:
        hc = HandoffContext(
            source_node_id="simple",
            summary="Done.",
            key_outputs={},
            turn_count=1,
            total_tokens_used=100,
        )
        output = ContextHandoff.format_as_input(hc)

        assert "KEY OUTPUTS:" not in output
        assert "SUMMARY:" in output

    def test_format_content_values(self) -> None:
        hc = HandoffContext(
            source_node_id="node_X",
            summary="Found 3 bugs.",
            key_outputs={"bugs": "3", "severity": "high"},
            turn_count=7,
            total_tokens_used=5000,
        )
        output = ContextHandoff.format_as_input(hc)

        assert "node_X" in output
        assert "7 turns" in output
        assert "~5000 tokens" in output
        assert "- bugs: 3" in output
        assert "- severity: high" in output
        assert "Found 3 bugs." in output

    def test_format_empty_summary(self) -> None:
        hc = HandoffContext(
            source_node_id="n",
            summary="",
            key_outputs={},
            turn_count=0,
            total_tokens_used=0,
        )
        output = ContextHandoff.format_as_input(hc)

        assert "No summary available." in output

    @pytest.mark.asyncio
    async def test_format_as_input_usable_as_message(self) -> None:
        """Formatted output can be fed into a NodeConversation as a user message."""
        hc = HandoffContext(
            source_node_id="prev_node",
            summary="Completed analysis.",
            key_outputs={"result": "42"},
            turn_count=3,
            total_tokens_used=900,
        )
        text = ContextHandoff.format_as_input(hc)

        conv = NodeConversation()
        msg = await conv.add_user_message(text)

        assert msg.role == "user"
        assert "CONTEXT FROM: prev_node" in msg.content
        assert conv.turn_count == 1
