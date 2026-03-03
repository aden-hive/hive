"""Tests for Level 2 conversation-aware judge.

Validates:
  - No success_criteria → Level 0 only (existing behavior)
  - success_criteria set, good conversation → Level 2 ACCEPT
  - success_criteria set, poor conversation → Level 2 RETRY with feedback
  - Custom explicit judge takes priority over Level 2
  - Level 2 fires only when Level 0 passes (all keys set)
  - _parse_verdict correctly parses LLM responses
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from framework.graph.conversation import NodeConversation
from framework.graph.conversation_judge import (
    _parse_verdict,
    evaluate_phase_completion,
)
from framework.graph.edge import GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeSpec
from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent
from framework.runtime.core import Runtime

# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


class MockStreamingLLM(LLMProvider):
    """Mock LLM that yields pre-programmed StreamEvent sequences."""

    def __init__(self, scenarios: list[list] | None = None, complete_response: str = ""):
        self.scenarios = scenarios or []
        self._call_index = 0
        self.stream_calls: list[dict] = []
        self.complete_response = complete_response
        self.complete_calls: list[dict] = []

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator:
        self.stream_calls.append({"messages": messages, "system": system, "tools": tools})
        if not self.scenarios:
            return
        events = self.scenarios[self._call_index % len(self.scenarios)]
        self._call_index += 1
        for event in events:
            yield event

    def complete(self, messages, system="", **kwargs) -> LLMResponse:
        self.complete_calls.append({"messages": messages, "system": system})
        return LLMResponse(content=self.complete_response, model="mock", stop_reason="stop")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_output_scenario(key: str, value: str) -> list:
    return [
        ToolCallEvent(
            tool_use_id=f"call_{key}",
            tool_name="set_output",
            tool_input={"key": key, "value": value},
        ),
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _text_then_set_output(text: str, key: str, value: str) -> list:
    return [
        TextDeltaEvent(content=text, snapshot=text),
        ToolCallEvent(
            tool_use_id=f"call_{key}",
            tool_name="set_output",
            tool_input={"key": key, "value": value},
        ),
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _text_finish(text: str) -> list:
    return [
        TextDeltaEvent(content=text, snapshot=text),
        FinishEvent(stop_reason="stop", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _make_runtime():
    rt = MagicMock(spec=Runtime)
    rt.start_run = MagicMock(return_value="run_1")
    rt.end_run = MagicMock()
    rt.report_problem = MagicMock()
    rt.decide = MagicMock(return_value="dec_1")
    rt.record_outcome = MagicMock()
    rt.set_node = MagicMock()
    return rt


def _make_goal():
    return Goal(id="g1", name="test", description="test goal")


# ===========================================================================
# Unit tests for _parse_verdict
# ===========================================================================


class TestParseVerdict:
    def test_accept(self):
        v = _parse_verdict("ACTION: ACCEPT\nCONFIDENCE: 0.9\nFEEDBACK:")
        assert v.action == "ACCEPT"
        assert v.confidence == 0.9
        assert v.feedback == ""

    def test_retry_with_feedback(self):
        v = _parse_verdict("ACTION: RETRY\nCONFIDENCE: 0.6\nFEEDBACK: Research is too shallow.")
        assert v.action == "RETRY"
        assert v.confidence == 0.6
        assert "shallow" in v.feedback

    def test_defaults_on_garbage(self):
        v = _parse_verdict("some random text\nno structured output")
        assert v.action == "ACCEPT"  # default
        assert v.confidence == 0.8  # default

    def test_invalid_action_defaults_to_accept(self):
        v = _parse_verdict("ACTION: ESCALATE\nCONFIDENCE: 0.5")
        assert v.action == "ACCEPT"  # ESCALATE not valid for Level 2


# ===========================================================================
# Unit tests for evaluate_phase_completion
# ===========================================================================


class TestEvaluatePhaseCompletion:
    @pytest.mark.asyncio
    async def test_accept_on_good_response(self):
        """LLM says ACCEPT → verdict is ACCEPT."""
        llm = MockStreamingLLM(complete_response="ACTION: ACCEPT\nCONFIDENCE: 0.95\nFEEDBACK:")
        conv = NodeConversation(system_prompt="test")
        await conv.add_user_message("Do research on topic X")
        await conv.add_assistant_message("I found 5 high-quality sources on X.")

        verdict = await evaluate_phase_completion(
            llm=llm,
            conversation=conv,
            phase_name="Research",
            phase_description="Research the topic",
            success_criteria="Find at least 3 credible sources",
            accumulator_state={"findings": "5 sources found"},
        )
        assert verdict.action == "ACCEPT"
        assert verdict.confidence == 0.95

    @pytest.mark.asyncio
    async def test_retry_on_poor_response(self):
        """LLM says RETRY → verdict is RETRY with feedback."""
        llm = MockStreamingLLM(
            complete_response=(
                "ACTION: RETRY\nCONFIDENCE: 0.4\nFEEDBACK: Only found 1 source, need 3."
            )
        )
        conv = NodeConversation(system_prompt="test")
        await conv.add_user_message("Do research")
        await conv.add_assistant_message("I found 1 source.")

        verdict = await evaluate_phase_completion(
            llm=llm,
            conversation=conv,
            phase_name="Research",
            phase_description="Research the topic",
            success_criteria="Find at least 3 credible sources",
            accumulator_state={"findings": "1 source"},
        )
        assert verdict.action == "RETRY"
        assert "1 source" in verdict.feedback

    @pytest.mark.asyncio
    async def test_llm_failure_defaults_to_accept(self):
        """When LLM fails, Level 2 should not block (Level 0 already passed)."""
        llm = MockStreamingLLM()
        # Make complete() raise an exception
        llm.complete = MagicMock(side_effect=RuntimeError("LLM unavailable"))

        conv = NodeConversation(system_prompt="test")
        await conv.add_assistant_message("Done.")

        verdict = await evaluate_phase_completion(
            llm=llm,
            conversation=conv,
            phase_name="Test",
            phase_description="Test phase",
            success_criteria="Do the thing",
            accumulator_state={"result": "done"},
        )
        assert verdict.action == "ACCEPT"
        assert verdict.confidence == 0.5


# ===========================================================================
# Integration: Level 2 in EventLoopNode implicit judge
# ===========================================================================


class TestLevel2InImplicitJudge:
    @pytest.mark.asyncio
    async def test_no_success_criteria_level0_only(self):
        """Without success_criteria, Level 0 accepts normally (existing behavior)."""
        runtime = _make_runtime()
        llm = MockStreamingLLM(
            scenarios=[
                _set_output_scenario("result", "done"),
                _text_finish("accepted"),
            ]
        )

        spec = NodeSpec(
            id="n1",
            name="Node1",
            description="test",
            node_type="event_loop",
            output_keys=["result"],
            # No success_criteria!
        )
        graph = GraphSpec(
            id="g1",
            goal_id="g1",
            entry_node="n1",
            nodes=[spec],
            edges=[],
        )

        executor = GraphExecutor(runtime=runtime, llm=llm)
        result = await executor.execute(graph=graph, goal=_make_goal())
        assert result.success
        # LLM.complete should NOT have been called for Level 2
        assert len(llm.complete_calls) == 0

    @pytest.mark.asyncio
    async def test_success_criteria_accept(self):
        """With success_criteria and good work, Level 2 accepts."""
        runtime = _make_runtime()
        llm = MockStreamingLLM(
            scenarios=[
                _text_then_set_output("I did thorough research.", "result", "done"),
                _text_finish(""),  # triggers judge
            ],
            complete_response="ACTION: ACCEPT\nCONFIDENCE: 0.9\nFEEDBACK:",
        )

        spec = NodeSpec(
            id="n1",
            name="Research",
            description="Do research",
            node_type="event_loop",
            output_keys=["result"],
            success_criteria="Provide thorough research with multiple sources.",
        )
        graph = GraphSpec(
            id="g1",
            goal_id="g1",
            entry_node="n1",
            nodes=[spec],
            edges=[],
        )

        executor = GraphExecutor(runtime=runtime, llm=llm)
        result = await executor.execute(graph=graph, goal=_make_goal())
        assert result.success
        # LLM.complete should have been called for Level 2
        assert len(llm.complete_calls) >= 1

    @pytest.mark.asyncio
    async def test_success_criteria_retry_then_accept(self):
        """Level 2 rejects first attempt, LLM tries again, Level 2 accepts."""
        runtime = _make_runtime()

        # Track complete calls to alternate responses
        complete_responses = [
            "ACTION: RETRY\nCONFIDENCE: 0.4\nFEEDBACK: Need more detail.",
            "ACTION: ACCEPT\nCONFIDENCE: 0.9\nFEEDBACK:",
        ]
        call_count = [0]

        class SequentialLLM(MockStreamingLLM):
            def complete(self, messages, system="", **kwargs):
                idx = call_count[0]
                call_count[0] += 1
                resp = complete_responses[idx % len(complete_responses)]
                return LLMResponse(content=resp, model="mock", stop_reason="stop")

        llm = SequentialLLM(
            scenarios=[
                # Turn 1: set output, then stop → Level 2 RETRY
                _text_then_set_output("Brief research.", "result", "brief"),
                _text_finish(""),  # triggers judge → Level 2 RETRY
                # Turn 2: after retry feedback, set output again, stop → Level 2 ACCEPT
                _text_then_set_output("Much more detailed research.", "result", "detailed"),
                _text_finish(""),  # triggers judge → Level 2 ACCEPT
            ]
        )

        spec = NodeSpec(
            id="n1",
            name="Research",
            description="Do research",
            node_type="event_loop",
            output_keys=["result"],
            success_criteria="Provide thorough research with multiple sources.",
        )
        graph = GraphSpec(
            id="g1",
            goal_id="g1",
            entry_node="n1",
            nodes=[spec],
            edges=[],
        )

        executor = GraphExecutor(runtime=runtime, llm=llm)
        result = await executor.execute(graph=graph, goal=_make_goal())
        assert result.success
        # Should have had 2 complete calls (first RETRY, second ACCEPT)
        assert call_count[0] >= 2

    @pytest.mark.asyncio
    async def test_level2_only_fires_when_level0_passes(self):
        """Level 2 should NOT fire when output keys are missing."""
        runtime = _make_runtime()

        llm = MockStreamingLLM(
            scenarios=[
                # Turn 1: just text, no set_output → Level 0 RETRY (missing keys)
                _text_finish("I did some thinking."),
                # Turn 2: set output → Level 0 ACCEPT, Level 2 check
                _text_then_set_output("Now I have output.", "result", "done"),
                _text_finish(""),  # triggers judge
            ],
            complete_response="ACTION: ACCEPT\nCONFIDENCE: 0.9\nFEEDBACK:",
        )

        spec = NodeSpec(
            id="n1",
            name="Research",
            description="Do research",
            node_type="event_loop",
            output_keys=["result"],
            success_criteria="Provide results.",
        )
        graph = GraphSpec(
            id="g1",
            goal_id="g1",
            entry_node="n1",
            nodes=[spec],
            edges=[],
        )

        executor = GraphExecutor(runtime=runtime, llm=llm)
        result = await executor.execute(graph=graph, goal=_make_goal())
        assert result.success
        # Level 2 should only fire once (when Level 0 passes)
        assert len(llm.complete_calls) == 1
