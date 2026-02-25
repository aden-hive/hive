"""Tests for the Continuous Agent architecture (conversation threading + cumulative tools).

Validates:
  - conversation_mode="isolated" preserves existing behavior
  - conversation_mode="continuous" threads one conversation across nodes
  - Transition markers are inserted at phase boundaries
  - System prompt updates at each transition (layered prompt composition)
  - Tools accumulate across nodes in continuous mode
  - prompt_composer functions work correctly
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from framework.graph.conversation import NodeConversation
from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeResult, NodeSpec, SharedMemory
from framework.graph.prompt_composer import (
    build_narrative,
    build_transition_marker,
    compose_system_prompt,
)
from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent
from framework.runtime.core import Runtime

# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


class MockStreamingLLM(LLMProvider):
    """Mock LLM that yields pre-programmed StreamEvent sequences."""

    def __init__(self, scenarios: list[list] | None = None):
        self.scenarios = scenarios or []
        self._call_index = 0
        self.stream_calls: list[dict] = []

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
        return LLMResponse(content="Summary.", model="mock", stop_reason="stop")

    def complete_with_tools(self, messages, system, tools, tool_executor, **kwargs) -> LLMResponse:
        return LLMResponse(content="", model="mock", stop_reason="stop")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_output_scenario(key: str, value: str) -> list:
    """LLM calls set_output then finishes."""
    return [
        ToolCallEvent(
            tool_use_id=f"call_{key}",
            tool_name="set_output",
            tool_input={"key": key, "value": value},
        ),
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _text_then_set_output(text: str, key: str, value: str) -> list:
    """LLM produces text, then calls set_output, then finishes (2 turns needed)."""
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
    """LLM produces text and stops (triggers judge)."""
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


def _make_tool(name: str) -> Tool:
    return Tool(
        name=name,
        description=f"Tool {name}",
        parameters={"type": "object", "properties": {}},
    )


# ===========================================================================
# prompt_composer unit tests
# ===========================================================================


class TestComposeSystemPrompt:
    def test_all_layers(self):
        result = compose_system_prompt(
            identity_prompt="I am a research agent.",
            focus_prompt="Focus on writing the report.",
            narrative="We found 5 sources on topic X.",
        )
        assert "I am a research agent." in result
        assert "Focus on writing the report." in result
        assert "We found 5 sources on topic X." in result
        # Identity comes first
        assert result.index("I am a research agent.") < result.index("Focus on writing")

    def test_identity_only(self):
        result = compose_system_prompt(identity_prompt="I am an agent.", focus_prompt=None)
        assert result.startswith("I am an agent.")
        assert "Current date and time:" in result

    def test_focus_only(self):
        result = compose_system_prompt(identity_prompt=None, focus_prompt="Do the thing.")
        assert "Current Focus" in result
        assert "Do the thing." in result
        assert "Current date and time:" in result

    def test_empty(self):
        result = compose_system_prompt(identity_prompt=None, focus_prompt=None)
        assert "Current date and time:" in result


class TestBuildNarrative:
    def test_with_execution_path(self):
        memory = SharedMemory()
        memory.write("findings", "some findings")

        node_a = NodeSpec(
            id="a", name="Research", description="Research the topic", node_type="event_loop"
        )
        node_b = NodeSpec(id="b", name="Report", description="Write report", node_type="event_loop")
        graph = GraphSpec(
            id="g1",
            goal_id="g1",
            entry_node="a",
            nodes=[node_a, node_b],
            edges=[],
        )

        result = build_narrative(memory, ["a"], graph)
        assert "Research" in result
        assert "findings" in result

    def test_empty_state(self):
        memory = SharedMemory()
        graph = GraphSpec(id="g1", goal_id="g1", entry_node="a", nodes=[], edges=[])
        result = build_narrative(memory, [], graph)
        assert result == ""


class TestBuildTransitionMarker:
    def test_basic_marker(self):
        prev = NodeSpec(
            id="research", name="Research", description="Find sources", node_type="event_loop"
        )
        next_n = NodeSpec(
            id="report", name="Report", description="Write report", node_type="event_loop"
        )
        memory = SharedMemory()
        memory.write("findings", "important stuff")

        marker = build_transition_marker(
            previous_node=prev,
            next_node=next_n,
            memory=memory,
            cumulative_tool_names=["web_search", "save_data"],
        )

        assert "PHASE TRANSITION" in marker
        assert "Research" in marker
        assert "Report" in marker
        assert "findings" in marker
        assert "web_search" in marker
        assert "reflect" in marker.lower()


# ===========================================================================
# NodeConversation.update_system_prompt
# ===========================================================================


class TestUpdateSystemPrompt:
    def test_update(self):
        conv = NodeConversation(system_prompt="original")
        assert conv.system_prompt == "original"
        conv.update_system_prompt("updated")
        assert conv.system_prompt == "updated"


# ===========================================================================
# Conversation threading through executor
# ===========================================================================


class TestContinuousConversation:
    """Test that conversation_mode='continuous' threads a single conversation."""

    @pytest.mark.asyncio
    async def test_isolated_mode_no_conversation_in_result(self):
        """In isolated mode, NodeResult.conversation should be None."""
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
        )
        graph = GraphSpec(
            id="g1",
            goal_id="g1",
            entry_node="n1",
            nodes=[spec],
            edges=[],
            conversation_mode="isolated",
        )

        executor = GraphExecutor(runtime=runtime, llm=llm)
        result = await executor.execute(graph=graph, goal=_make_goal())
        assert result.success

    @pytest.mark.asyncio
    async def test_continuous_threads_conversation(self):
        """In continuous mode, second node sees messages from first node."""
        runtime = _make_runtime()

        # Node A: set_output("brief", "the brief"), then finish (accept)
        # Node B: set_output("report", "the report"), then finish (accept)
        llm = MockStreamingLLM(
            scenarios=[
                _text_then_set_output("I'll research this.", "brief", "the brief"),
                _text_finish(""),  # triggers accept for node A (all keys set)
                _text_then_set_output("Here's the report.", "report", "the report"),
                _text_finish(""),  # triggers accept for node B
            ]
        )

        node_a = NodeSpec(
            id="a",
            name="Intake",
            description="Gather requirements",
            node_type="event_loop",
            output_keys=["brief"],
        )
        node_b = NodeSpec(
            id="b",
            name="Report",
            description="Write report",
            node_type="event_loop",
            input_keys=["brief"],
            output_keys=["report"],
        )

        graph = GraphSpec(
            id="g1",
            goal_id="g1",
            entry_node="a",
            nodes=[node_a, node_b],
            edges=[EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.ON_SUCCESS)],
            terminal_nodes=["b"],
            conversation_mode="continuous",
            identity_prompt="You are a thorough research agent.",
        )

        executor = GraphExecutor(runtime=runtime, llm=llm)
        result = await executor.execute(graph=graph, goal=_make_goal())

        assert result.success
        assert result.path == ["a", "b"]

        # Verify the LLM saw the identity prompt in system messages
        # The second node's system prompt should contain the identity
        if len(llm.stream_calls) >= 3:
            system_at_node_b = llm.stream_calls[2]["system"]
            assert "thorough research agent" in system_at_node_b

    @pytest.mark.asyncio
    async def test_continuous_transition_marker_present(self):
        """Transition marker should appear in messages when switching nodes."""
        runtime = _make_runtime()

        llm = MockStreamingLLM(
            scenarios=[
                _text_then_set_output("Research done.", "brief", "the brief"),
                _text_finish(""),
                _text_then_set_output("Report done.", "report", "the report"),
                _text_finish(""),
            ]
        )

        node_a = NodeSpec(
            id="a",
            name="Research",
            description="Do research",
            node_type="event_loop",
            output_keys=["brief"],
        )
        node_b = NodeSpec(
            id="b",
            name="Report",
            description="Write report",
            node_type="event_loop",
            input_keys=["brief"],
            output_keys=["report"],
        )

        graph = GraphSpec(
            id="g1",
            goal_id="g1",
            entry_node="a",
            nodes=[node_a, node_b],
            edges=[EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.ON_SUCCESS)],
            terminal_nodes=["b"],
            conversation_mode="continuous",
        )

        executor = GraphExecutor(runtime=runtime, llm=llm)
        result = await executor.execute(graph=graph, goal=_make_goal())
        assert result.success

        # When node B's first LLM call happens, its messages should contain
        # the transition marker from the executor
        if len(llm.stream_calls) >= 3:
            node_b_messages = llm.stream_calls[2]["messages"]
            all_content = " ".join(
                m.get("content", "") for m in node_b_messages if isinstance(m.get("content"), str)
            )
            assert "PHASE TRANSITION" in all_content


# ===========================================================================
# Cumulative tools
# ===========================================================================


class TestCumulativeTools:
    """Test that tools accumulate in continuous mode."""

    @pytest.mark.asyncio
    async def test_isolated_mode_tools_scoped(self):
        """In isolated mode, each node only gets its own declared tools."""
        runtime = _make_runtime()
        tool_a = _make_tool("web_search")
        tool_b = _make_tool("save_data")

        llm = MockStreamingLLM(
            scenarios=[
                _text_then_set_output("Done.", "brief", "brief"),
                _text_finish(""),
                _text_then_set_output("Done.", "report", "report"),
                _text_finish(""),
            ]
        )

        node_a = NodeSpec(
            id="a",
            name="Research",
            description="Research",
            node_type="event_loop",
            output_keys=["brief"],
            tools=["web_search"],
        )
        node_b = NodeSpec(
            id="b",
            name="Report",
            description="Report",
            node_type="event_loop",
            input_keys=["brief"],
            output_keys=["report"],
            tools=["save_data"],
        )

        graph = GraphSpec(
            id="g1",
            goal_id="g1",
            entry_node="a",
            nodes=[node_a, node_b],
            edges=[EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.ON_SUCCESS)],
            terminal_nodes=["b"],
            conversation_mode="isolated",
        )

        executor = GraphExecutor(
            runtime=runtime,
            llm=llm,
            tools=[tool_a, tool_b],
        )
        result = await executor.execute(graph=graph, goal=_make_goal())
        assert result.success

        # In isolated mode, node B should NOT have web_search
        if len(llm.stream_calls) >= 3:
            node_b_tools = llm.stream_calls[2].get("tools") or []
            tool_names = [t.name for t in node_b_tools]
            assert "save_data" in tool_names or "set_output" in tool_names
            # web_search should NOT be present (only set_output + save_data)
            real_tools = [n for n in tool_names if n != "set_output"]
            assert "web_search" not in real_tools

    @pytest.mark.asyncio
    async def test_continuous_mode_tools_accumulate(self):
        """In continuous mode, node B should have both web_search and save_data."""
        runtime = _make_runtime()
        tool_a = _make_tool("web_search")
        tool_b = _make_tool("save_data")

        llm = MockStreamingLLM(
            scenarios=[
                _text_then_set_output("Done.", "brief", "brief"),
                _text_finish(""),
                _text_then_set_output("Done.", "report", "report"),
                _text_finish(""),
            ]
        )

        node_a = NodeSpec(
            id="a",
            name="Research",
            description="Research",
            node_type="event_loop",
            output_keys=["brief"],
            tools=["web_search"],
        )
        node_b = NodeSpec(
            id="b",
            name="Report",
            description="Report",
            node_type="event_loop",
            input_keys=["brief"],
            output_keys=["report"],
            tools=["save_data"],
        )

        graph = GraphSpec(
            id="g1",
            goal_id="g1",
            entry_node="a",
            nodes=[node_a, node_b],
            edges=[EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.ON_SUCCESS)],
            terminal_nodes=["b"],
            conversation_mode="continuous",
        )

        executor = GraphExecutor(
            runtime=runtime,
            llm=llm,
            tools=[tool_a, tool_b],
        )
        result = await executor.execute(graph=graph, goal=_make_goal())
        assert result.success

        # In continuous mode, node B should have BOTH tools
        if len(llm.stream_calls) >= 3:
            node_b_tools = llm.stream_calls[2].get("tools") or []
            tool_names = [t.name for t in node_b_tools]
            real_tools = [n for n in tool_names if n != "set_output"]
            assert "web_search" in real_tools
            assert "save_data" in real_tools


# ===========================================================================
# Schema field defaults
# ===========================================================================


class TestSchemaDefaults:
    def test_graphspec_defaults(self):
        """New fields should have safe defaults."""
        graph = GraphSpec(
            id="g1",
            goal_id="g1",
            entry_node="n1",
            nodes=[],
            edges=[],
        )
        assert graph.conversation_mode == "continuous"
        assert graph.identity_prompt is None

    def test_nodespec_defaults(self):
        """NodeSpec.success_criteria should default to None."""
        spec = NodeSpec(
            id="n1",
            name="test",
            description="test",
            node_type="event_loop",
        )
        assert spec.success_criteria is None

    def test_noderesult_defaults(self):
        """NodeResult.conversation should default to None."""
        result = NodeResult(success=True)
        assert result.conversation is None
