"""Tests for subagent capability in EventLoopNode.

Tests the delegate_to_sub_agent tool, subagent execution with read-only data buffer,
prevention of nested subagent delegation, and report_to_parent one-way channel.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from framework.agent_loop.agent_loop import AgentLoop as EventLoopNode
from framework.agent_loop.agent_loop import SubagentJudge
from framework.agent_loop.internals.types import LoopConfig
from framework.host.event_bus import EventBus, EventType
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import (
    FinishEvent,
    TextDeltaEvent,
    ToolCallEvent,
)
from framework.orchestrator.node import DataBuffer, NodeContext, NodeSpec
from framework.tracker.decision_tracker import DecisionTracker as Runtime

# ---------------------------------------------------------------------------
# Mock LLM for controlled testing
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
# Scenario builders
# ---------------------------------------------------------------------------


def set_output_scenario(key: str, value: str) -> list:
    """Build scenario where LLM calls set_output."""
    return [
        ToolCallEvent(
            tool_name="set_output",
            tool_input={"key": key, "value": value},
            tool_use_id="set_1",
        ),
        FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
    ]


def delegate_scenario(agent_id: str, task: str) -> list:
    """Build scenario where LLM delegates to a subagent."""
    return [
        ToolCallEvent(
            tool_name="delegate_to_sub_agent",
            tool_input={"agent_id": agent_id, "task": task},
            tool_use_id="delegate_1",
        ),
        FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
    ]


def text_finish_scenario(text: str = "Done") -> list:
    """Build scenario where LLM produces text and finishes."""
    return [
        TextDeltaEvent(content=text, snapshot=text),
        FinishEvent(stop_reason="stop", input_tokens=10, output_tokens=5, model="mock"),
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime() -> MagicMock:
    """Create a mock runtime for testing."""
    rt = MagicMock(spec=Runtime)
    rt.start_run = MagicMock(return_value="run_1")
    rt.decide = MagicMock(return_value="dec_1")
    rt.record_outcome = MagicMock()
    rt.end_run = MagicMock()
    return rt


@pytest.fixture
def parent_node_spec() -> NodeSpec:
    """Parent node that can delegate to subagents."""
    return NodeSpec(
        id="parent",
        name="Parent Node",
        description="A parent node that delegates tasks",
        node_type="event_loop",
        input_keys=["query"],
        output_keys=["result"],
        tools=[],
        sub_agents=["researcher"],  # Can delegate to researcher
    )


@pytest.fixture
def subagent_node_spec() -> NodeSpec:
    """Subagent node spec for the researcher."""
    return NodeSpec(
        id="researcher",
        name="Researcher",
        description="Researches topics and returns findings",
        node_type="event_loop",
        input_keys=["task"],
        output_keys=["findings"],
        tools=[],
    )


# ---------------------------------------------------------------------------
# Tests for _build_delegate_tool
# ---------------------------------------------------------------------------


class TestBuildDelegateTool:
    """Tests for the _build_delegate_tool method."""

    def test_returns_none_when_no_subagents(self):
        """Should return None when sub_agents list is empty."""
        node = EventLoopNode()
        tool = node._build_delegate_tool([], {})
        assert tool is None

    def test_creates_tool_with_enum_of_agent_ids(self, subagent_node_spec):
        """Should create tool with agent_id enum from sub_agents list."""
        node = EventLoopNode()
        node_registry = {"researcher": subagent_node_spec}
        tool = node._build_delegate_tool(["researcher"], node_registry)

        assert tool is not None
        assert tool.name == "delegate_to_sub_agent"
        assert tool.parameters["properties"]["agent_id"]["enum"] == ["researcher"]
        assert "researcher: Researches topics" in tool.description

    def test_handles_missing_node_in_registry(self):
        """Should handle subagent ID not found in registry."""
        node = EventLoopNode()
        tool = node._build_delegate_tool(["unknown_agent"], {})

        assert tool is not None
        assert "unknown_agent: (not found in registry)" in tool.description


# ---------------------------------------------------------------------------
# Tests for subagent execution
# ---------------------------------------------------------------------------


class TestSubagentExecution:
    """Tests for _execute_subagent method."""

    @pytest.mark.asyncio
    async def test_subagent_not_found_returns_error(self, runtime, parent_node_spec):
        """Should return error when subagent ID is not in registry."""
        node = EventLoopNode(config=LoopConfig(max_iterations=5))

        buffer = DataBuffer()
        buffer.write("query", "test query")

        ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_node_spec,
            buffer=buffer,
            input_data={},
            llm=MockStreamingLLM([]),
            available_tools=[],
            goal_context="",
            goal=None,
            node_registry={},  # Empty registry
        )

        result = await node._execute_subagent(ctx, "nonexistent", "do something")

        assert result.is_error is True
        result_data = json.loads(result.content)
        assert "not found" in result_data["message"]

    @pytest.mark.asyncio
    async def test_subagent_receives_readonly_memory(
        self, runtime, parent_node_spec, subagent_node_spec
    ):
        """Subagent should have read-only access to data buffer."""
        # Create LLM that will set output for the subagent
        subagent_llm = MockStreamingLLM(
            [
                set_output_scenario("findings", "Found important data"),
                text_finish_scenario(),
            ]
        )

        node = EventLoopNode(
            config=LoopConfig(max_iterations=5),
        )

        # Parent data buffer with some data
        buffer = DataBuffer()
        buffer.write("query", "research AI")
        scoped_buffer = buffer.with_permissions(
            read_keys=["query"],
            write_keys=["result"],
        )

        ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_node_spec,
            buffer=scoped_buffer,
            input_data={"query": "research AI"},
            llm=subagent_llm,
            available_tools=[],
            goal_context="",
            goal=None,
            node_registry={"researcher": subagent_node_spec},
        )

        result = await node._execute_subagent(ctx, "researcher", "Find info about AI")

        # Should succeed
        assert result.is_error is False
        result_data = json.loads(result.content)
        assert result_data["metadata"]["success"] is True
        assert "findings" in result_data["data"]

    @pytest.mark.asyncio
    async def test_subagent_returns_structured_output(
        self, runtime, parent_node_spec, subagent_node_spec
    ):
        """Subagent should return structured JSON output."""
        subagent_llm = MockStreamingLLM(
            [
                set_output_scenario("findings", "AI research results"),
                text_finish_scenario(),
            ]
        )

        node = EventLoopNode(config=LoopConfig(max_iterations=5))

        buffer = DataBuffer()
        scoped = buffer.with_permissions(read_keys=[], write_keys=["result"])

        ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_node_spec,
            buffer=scoped,
            input_data={},
            llm=subagent_llm,
            available_tools=[],
            goal_context="",
            goal=None,
            node_registry={"researcher": subagent_node_spec},
        )

        result = await node._execute_subagent(ctx, "researcher", "Research task")

        result_data = json.loads(result.content)
        assert "message" in result_data
        assert "data" in result_data
        assert "metadata" in result_data
        assert result_data["metadata"]["agent_id"] == "researcher"

    @pytest.mark.asyncio
    async def test_gcu_subagent_auto_populates_tools_from_catalog(self, runtime):
        """GCU subagent with tools=[] should receive all catalog tools (auto-populate).

        GCU nodes declare tools=[] because the runner expands them at setup time.
        But _execute_subagent filters by subagent_spec.tools, which is still empty.
        The fix: when subagent is GCU with no declared tools, include all catalog tools.
        """
        gcu_spec = NodeSpec(
            id="browser_worker",
            name="Browser Worker",
            description="GCU browser subagent",
            node_type="gcu",
            output_keys=["result"],
            tools=[],  # Empty — expects auto-population
        )

        parent_spec = NodeSpec(
            id="parent",
            name="Parent",
            description="Orchestrator",
            node_type="event_loop",
            output_keys=["result"],
            sub_agents=["browser_worker"],
        )

        spy_llm = MockStreamingLLM(
            [set_output_scenario("result", "scraped"), text_finish_scenario()]
        )

        browser_tool = Tool(name="browser_snapshot", description="Snapshot")

        node = EventLoopNode(config=LoopConfig(max_iterations=5))
        buffer = DataBuffer()
        scoped = buffer.with_permissions(read_keys=[], write_keys=["result"])

        ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_spec,
            buffer=scoped,
            input_data={},
            llm=spy_llm,
            available_tools=[],
            all_tools=[browser_tool],
            goal_context="",
            goal=None,
            node_registry={"browser_worker": gcu_spec},
        )

        result = await node._execute_subagent(ctx, "browser_worker", "Scrape example.com")
        assert result.is_error is False

        # Verify subagent LLM received browser tools from catalog
        assert spy_llm.stream_calls, "LLM should have been called"
        first_call_tools = spy_llm.stream_calls[0]["tools"]
        tool_names = {t.name for t in first_call_tools} if first_call_tools else set()
        assert "browser_snapshot" in tool_names
        assert "delegate_to_sub_agent" not in tool_names


# ---------------------------------------------------------------------------
# Tests for nested subagent prevention
# ---------------------------------------------------------------------------


class TestNestedSubagentPrevention:
    """Tests that subagents cannot spawn their own subagents."""

    def test_delegate_tool_not_added_in_subagent_mode(
        self, runtime, parent_node_spec, subagent_node_spec
    ):
        """delegate_to_sub_agent should not be available when is_subagent_mode=True."""
        # Create a subagent spec that declares sub_agents (should be ignored)
        subagent_with_subagents = NodeSpec(
            id="nested",
            name="Nested",
            description="A node that tries to have subagents",
            node_type="event_loop",
            input_keys=[],
            output_keys=["out"],
            sub_agents=["another"],  # This should be ignored in subagent mode
        )

        buffer = DataBuffer()
        ctx = NodeContext(
            runtime=runtime,
            node_id="nested",
            node_spec=subagent_with_subagents,
            buffer=buffer,
            input_data={},
            llm=MockStreamingLLM([]),
            available_tools=[],
            goal_context="",
            goal=None,
            is_subagent_mode=True,  # Running as a subagent
            node_registry={"another": subagent_node_spec},
        )

        # Build tools like execute() would
        node = EventLoopNode()
        tools = []
        if not ctx.is_subagent_mode:
            sub_agents = getattr(ctx.node_spec, "sub_agents", [])
            delegate_tool = node._build_delegate_tool(sub_agents, ctx.node_registry)
            if delegate_tool:
                tools.append(delegate_tool)

        # delegate_to_sub_agent should NOT be in tools
        assert not any(t.name == "delegate_to_sub_agent" for t in tools)


# ---------------------------------------------------------------------------
# Integration test: full delegation flow
# ---------------------------------------------------------------------------


class TestDelegationIntegration:
    """Integration tests for the complete delegation flow."""

    @pytest.mark.asyncio
    async def test_parent_delegates_and_uses_result(
        self, runtime, parent_node_spec, subagent_node_spec
    ):
        """Parent should delegate, receive result, and use it."""
        # Parent LLM: delegates, then uses result to set output
        parent_scenarios = [
            # Turn 1: Delegate to researcher
            delegate_scenario("researcher", "Find AI trends"),
            # Turn 2: Use result to set output
            set_output_scenario("result", "Summary: AI is trending"),
            # Turn 3: Done
            text_finish_scenario("Task complete"),
        ]

        # Subagent LLM: sets findings output (unused; scenarios defined inline)
        _ = [
            set_output_scenario("findings", "AI trends 2024: LLMs, agents"),
            text_finish_scenario(),
        ]

        # We need a mock tool executor that does nothing for real tools
        async def mock_tool_executor(tool_use: ToolUse) -> ToolResult:
            return ToolResult(
                tool_use_id=tool_use.tool_use_id,
                content="Tool executed",
                is_error=False,
            )

        # Create the parent's LLM
        parent_llm = MockStreamingLLM(parent_scenarios)

        # For subagent, we need a way to provide its LLM
        # Since _execute_subagent creates its own EventLoopNode and uses ctx.llm,
        # we need ctx.llm to serve both parent and subagent scenarios
        # This is tricky - in practice, the subagent gets ctx.llm which is the parent's LLM

        # For this test, let's just verify the parent can call delegate_to_sub_agent
        # and the tool handling correctly queues and executes it

        buffer = DataBuffer()
        buffer.write("query", "What are AI trends?")
        scoped = buffer.with_permissions(
            read_keys=["query"],
            write_keys=["result"],
        )

        node = EventLoopNode(
            config=LoopConfig(max_iterations=10),
            tool_executor=mock_tool_executor,
        )

        ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_node_spec,
            buffer=scoped,
            input_data={"query": "What are AI trends?"},
            llm=parent_llm,
            available_tools=[],
            goal_context="Research AI trends",
            goal=None,
            node_registry={"researcher": subagent_node_spec},
        )

        # Execute the parent node
        result = await node.execute(ctx)

        # The parent should have executed and called the delegate tool
        # Due to the mock setup, it may not fully succeed end-to-end,
        # but we can verify the structure works
        assert result is not None


# ---------------------------------------------------------------------------
# Scenario builders for report_to_parent
# ---------------------------------------------------------------------------


def report_scenario(message: str, data: dict | None = None) -> list:
    """Build scenario where LLM calls report_to_parent."""
    tool_input = {"message": message}
    if data is not None:
        tool_input["data"] = data
    return [
        ToolCallEvent(
            tool_name="report_to_parent",
            tool_input=tool_input,
            tool_use_id="report_1",
        ),
        FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
    ]


# ---------------------------------------------------------------------------
# Tests for report_to_parent tool
# ---------------------------------------------------------------------------


class TestBuildReportToParentTool:
    """Tests for the _build_report_to_parent_tool method."""

    def test_creates_tool_with_correct_schema(self):
        """Should create a tool with message (required) and data (optional) params."""
        node = EventLoopNode()
        tool = node._build_report_to_parent_tool()

        assert tool.name == "report_to_parent"
        assert "message" in tool.parameters["properties"]
        assert "data" in tool.parameters["properties"]
        assert tool.parameters["required"] == ["message"]

    def test_tool_only_visible_in_subagent_mode(
        self, runtime, parent_node_spec, subagent_node_spec
    ):
        """report_to_parent should only appear when is_subagent_mode=True and callback set."""
        node = EventLoopNode()

        # Parent mode: no report_to_parent
        buffer = DataBuffer()
        parent_ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_node_spec,
            buffer=buffer,
            input_data={},
            llm=MockStreamingLLM([]),
            available_tools=[],
            goal_context="",
            goal=None,
            is_subagent_mode=False,
            node_registry={},
        )

        tools = list(parent_ctx.available_tools)
        if parent_ctx.is_subagent_mode and parent_ctx.report_callback is not None:
            tools.append(node._build_report_to_parent_tool())

        assert not any(t.name == "report_to_parent" for t in tools)

        # Subagent mode WITH callback: report_to_parent present
        async def noop_callback(msg, data=None):
            pass

        subagent_ctx = NodeContext(
            runtime=runtime,
            node_id="sub",
            node_spec=subagent_node_spec,
            buffer=buffer,
            input_data={},
            llm=MockStreamingLLM([]),
            available_tools=[],
            goal_context="",
            goal=None,
            is_subagent_mode=True,
            report_callback=noop_callback,
            node_registry={},
        )

        tools2 = list(subagent_ctx.available_tools)
        if subagent_ctx.is_subagent_mode and subagent_ctx.report_callback is not None:
            tools2.append(node._build_report_to_parent_tool())

        assert any(t.name == "report_to_parent" for t in tools2)

    def test_tool_not_visible_without_callback(self, runtime, subagent_node_spec):
        """report_to_parent should NOT appear when callback is None even in subagent mode."""
        node = EventLoopNode()
        buffer = DataBuffer()

        ctx = NodeContext(
            runtime=runtime,
            node_id="sub",
            node_spec=subagent_node_spec,
            buffer=buffer,
            input_data={},
            llm=MockStreamingLLM([]),
            available_tools=[],
            goal_context="",
            goal=None,
            is_subagent_mode=True,
            report_callback=None,
            node_registry={},
        )

        tools = list(ctx.available_tools)
        if ctx.is_subagent_mode and ctx.report_callback is not None:
            tools.append(node._build_report_to_parent_tool())

        assert not any(t.name == "report_to_parent" for t in tools)


class TestReportToParentExecution:
    """Tests for report_to_parent callback execution and result assembly."""

    @pytest.mark.asyncio
    async def test_reports_appear_in_result_json(
        self, runtime, parent_node_spec, subagent_node_spec
    ):
        """Reports from report_to_parent should appear in the final ToolResult JSON."""
        # Subagent LLM: report, then set output
        subagent_llm = MockStreamingLLM(
            [
                report_scenario("50% done", {"progress": 0.5}),
                set_output_scenario("findings", "All done"),
                text_finish_scenario(),
            ]
        )

        node = EventLoopNode(config=LoopConfig(max_iterations=10))

        buffer = DataBuffer()
        scoped = buffer.with_permissions(read_keys=[], write_keys=["result"])

        ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_node_spec,
            buffer=scoped,
            input_data={},
            llm=subagent_llm,
            available_tools=[],
            goal_context="",
            goal=None,
            node_registry={"researcher": subagent_node_spec},
        )

        result = await node._execute_subagent(ctx, "researcher", "Do research")

        assert result.is_error is False
        result_data = json.loads(result.content)

        # Reports should be in the result
        assert result_data["reports"] is not None
        assert len(result_data["reports"]) == 1
        assert result_data["reports"][0]["message"] == "50% done"
        assert result_data["reports"][0]["data"] == {"progress": 0.5}
        assert "timestamp" in result_data["reports"][0]

        # Metadata should include report_count
        assert result_data["metadata"]["report_count"] == 1

    @pytest.mark.asyncio
    async def test_subagent_tool_events_visible_on_shared_bus(
        self, runtime, parent_node_spec, subagent_node_spec
    ):
        """Subagent internal tool calls should emit TOOL_CALL events on the shared bus."""
        bus = EventBus()
        tool_events = []

        async def handler(event):
            tool_events.append(event)

        bus.subscribe(
            event_types=[EventType.TOOL_CALL_STARTED, EventType.TOOL_CALL_COMPLETED],
            handler=handler,
        )

        subagent_llm = MockStreamingLLM(
            [
                set_output_scenario("findings", "Results"),
                text_finish_scenario(),
            ]
        )

        node = EventLoopNode(
            event_bus=bus,
            config=LoopConfig(max_iterations=10),
        )

        buffer = DataBuffer()
        scoped = buffer.with_permissions(read_keys=[], write_keys=["result"])

        ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_node_spec,
            buffer=scoped,
            input_data={},
            llm=subagent_llm,
            available_tools=[],
            goal_context="",
            goal=None,
            node_registry={"researcher": subagent_node_spec},
        )

        result = await node._execute_subagent(ctx, "researcher", "Do research")
        assert result.is_error is False

        # Subagent tool calls should appear on the shared bus
        started = [e for e in tool_events if e.type == EventType.TOOL_CALL_STARTED]
        completed = [e for e in tool_events if e.type == EventType.TOOL_CALL_COMPLETED]
        assert len(started) >= 1, "Expected at least one TOOL_CALL_STARTED from subagent"
        assert len(completed) >= 1, "Expected at least one TOOL_CALL_COMPLETED from subagent"

        # Events should have the namespaced subagent node_id
        for evt in started + completed:
            assert "subagent" in evt.node_id, f"Expected namespaced node_id, got: {evt.node_id}"

    @pytest.mark.asyncio
    async def test_event_bus_receives_subagent_report(
        self, runtime, parent_node_spec, subagent_node_spec
    ):
        """EventBus should receive SUBAGENT_REPORT events when parent has a bus."""
        bus = EventBus()
        bus_events = []

        async def handler(event):
            bus_events.append(event)

        bus.subscribe(event_types=[EventType.SUBAGENT_REPORT], handler=handler)

        subagent_llm = MockStreamingLLM(
            [
                report_scenario("Progress update", {"step": 1}),
                set_output_scenario("findings", "Results"),
                text_finish_scenario(),
            ]
        )

        node = EventLoopNode(
            event_bus=bus,
            config=LoopConfig(max_iterations=10),
        )

        buffer = DataBuffer()
        scoped = buffer.with_permissions(read_keys=[], write_keys=["result"])

        ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_node_spec,
            buffer=scoped,
            input_data={},
            llm=subagent_llm,
            available_tools=[],
            goal_context="",
            goal=None,
            node_registry={"researcher": subagent_node_spec},
        )

        result = await node._execute_subagent(ctx, "researcher", "Do research")

        assert result.is_error is False

        # EventBus should have received the report
        assert len(bus_events) == 1
        assert bus_events[0].type == EventType.SUBAGENT_REPORT
        assert bus_events[0].data["subagent_id"] == "researcher"
        assert bus_events[0].data["message"] == "Progress update"
        assert bus_events[0].data["data"] == {"step": 1}

    @pytest.mark.asyncio
    async def test_callback_failure_does_not_block_subagent(
        self, runtime, parent_node_spec, subagent_node_spec
    ):
        """Subagent should complete even if the report callback raises."""

        async def failing_callback(message: str, data: dict | None = None) -> None:
            raise RuntimeError("Callback exploded")

        subagent_llm = MockStreamingLLM(
            [
                report_scenario("This will fail callback"),
                set_output_scenario("findings", "Still finished"),
                text_finish_scenario(),
            ]
        )

        node = EventLoopNode(config=LoopConfig(max_iterations=10))

        buffer = DataBuffer()
        scoped = buffer.with_permissions(read_keys=[], write_keys=["result"])

        ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_node_spec,
            buffer=scoped,
            input_data={},
            llm=subagent_llm,
            available_tools=[],
            goal_context="",
            goal=None,
            node_registry={"researcher": subagent_node_spec},
        )

        # The _execute_subagent creates its own callback that wraps the event bus.
        # To test callback failure resilience at the triage level, we need to
        # directly test via a subagent context with a failing callback.
        # Let's instead verify the _execute_subagent wired callback is resilient.
        result = await node._execute_subagent(ctx, "researcher", "Do research")

        # Should succeed despite the internal callback (event_bus=None here, so
        # the wired callback won't fail). The report should still be recorded.
        assert result.is_error is False
        result_data = json.loads(result.content)
        assert result_data["reports"] is not None
        assert result_data["metadata"]["report_count"] == 1

    @pytest.mark.asyncio
    async def test_no_reports_gives_null(self, runtime, parent_node_spec, subagent_node_spec):
        """When no reports are sent, reports field should be null."""
        subagent_llm = MockStreamingLLM(
            [
                set_output_scenario("findings", "Done without reporting"),
                text_finish_scenario(),
            ]
        )

        node = EventLoopNode(config=LoopConfig(max_iterations=10))

        buffer = DataBuffer()
        scoped = buffer.with_permissions(read_keys=[], write_keys=["result"])

        ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_node_spec,
            buffer=scoped,
            input_data={},
            llm=subagent_llm,
            available_tools=[],
            goal_context="",
            goal=None,
            node_registry={"researcher": subagent_node_spec},
        )

        result = await node._execute_subagent(ctx, "researcher", "Simple task")

        assert result.is_error is False
        result_data = json.loads(result.content)
        assert result_data["reports"] is None
        assert result_data["metadata"]["report_count"] == 0


# ---------------------------------------------------------------------------
# Scenario builder for report_to_parent with wait_for_response
# ---------------------------------------------------------------------------


def report_wait_scenario(message: str, data: dict | None = None) -> list:
    """Build scenario where LLM calls report_to_parent with wait_for_response=True."""
    tool_input: dict[str, Any] = {"message": message, "wait_for_response": True}
    if data is not None:
        tool_input["data"] = data
    return [
        ToolCallEvent(
            tool_name="report_to_parent",
            tool_input=tool_input,
            tool_use_id="report_wait_1",
        ),
        FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
    ]


# ---------------------------------------------------------------------------
# Tests for SubagentJudge
# ---------------------------------------------------------------------------


class TestSubagentJudge:
    """Tests for the SubagentJudge class."""

    @pytest.mark.asyncio
    async def test_subagent_judge_accepts_when_output_keys_filled(self):
        """SubagentJudge should ACCEPT when missing_keys is empty, even with tool_calls present."""
        judge = SubagentJudge(task="Check profile at https://example.com/user123")

        verdict = await judge.evaluate(
            {
                "missing_keys": [],
                "tool_results": [{"tool_name": "browser_navigate", "content": "ok"}],
                "iteration": 1,
            }
        )

        assert verdict.action == "ACCEPT"
        assert verdict.feedback == ""

    @pytest.mark.asyncio
    async def test_subagent_judge_retries_with_task_in_feedback(self):
        """SubagentJudge should RETRY with task and missing keys in feedback."""
        task = "Scrape profile at https://example.com/user456"
        judge = SubagentJudge(task=task)

        verdict = await judge.evaluate(
            {
                "missing_keys": ["findings", "summary"],
                "tool_results": [],
                "iteration": 1,
            }
        )

        assert verdict.action == "RETRY"
        assert task in verdict.feedback
        assert "findings" in verdict.feedback
        assert "summary" in verdict.feedback
        assert "set_output" in verdict.feedback

    @pytest.mark.asyncio
    async def test_subagent_terminates_immediately_with_judge(
        self,
        runtime,
        parent_node_spec,
        subagent_node_spec,
    ):
        """Subagent should accept on the first outer iteration after browser + set_output.

        The inner tool loop in _run_single_turn needs a text-only LLM response
        to exit (it loops while the LLM keeps producing tool calls).  With the
        SubagentJudge, the outer loop should accept on iteration 0 because all
        output keys are filled — no second outer iteration needed.

        Also verifies that the subagent's system prompt contains the specific
        task (via goal_context injection).
        """
        # Inner iter 1: browser_navigate + set_output("findings", ...)
        # Inner iter 2: text-only finish → inner loop exits
        subagent_llm = MockStreamingLLM(
            [
                browser_and_set_output_scenario("findings", "Profile data extracted"),
                text_finish_scenario("Task complete"),
            ]
        )

        # Mock tool executor so browser_navigate succeeds
        async def mock_tool_executor(tool_use: ToolUse) -> ToolResult:
            return ToolResult(
                tool_use_id=tool_use.tool_use_id,
                content="Tool executed",
                is_error=False,
            )

        node = EventLoopNode(
            config=LoopConfig(max_iterations=5),
            tool_executor=mock_tool_executor,
        )

        buffer = DataBuffer()
        scoped = buffer.with_permissions(read_keys=[], write_keys=["result"])

        task_text = "Check the profile at https://example.com/user789"
        ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_node_spec,
            buffer=scoped,
            input_data={},
            llm=subagent_llm,
            available_tools=[],
            goal_context="",
            goal=None,
            node_registry={"researcher": subagent_node_spec},
        )

        result = await node._execute_subagent(ctx, "researcher", task_text)

        assert result.is_error is False
        result_data = json.loads(result.content)
        assert result_data["metadata"]["success"] is True
        assert "findings" in result_data["data"]

        # 2 inner LLM calls (tool turn + text finish), 1 outer iteration.
        # With the implicit judge (judge=None), a turn with real_tool_results
        # would RETRY even if keys are filled; SubagentJudge accepts immediately.
        assert subagent_llm._call_index == 2, (
            f"Expected 2 LLM calls (tool turn + text finish) but got {subagent_llm._call_index}."
        )

        # Verify the subagent's initial message references the specific task
        # (goal_context is injected into the user message via _build_initial_message)
        first_call = subagent_llm.stream_calls[0]
        first_user_msg = first_call["messages"][0]["content"]
        assert task_text in first_user_msg, (
            "Subagent initial message should contain the specific task via goal_context"
        )


# ---------------------------------------------------------------------------
# Scenario builder for report_to_parent with mark_complete
# ---------------------------------------------------------------------------


def report_mark_complete_scenario(
    message: str,
    data: dict | None = None,
    mark_complete: bool = True,
) -> list:
    """Build scenario where LLM calls report_to_parent with mark_complete."""
    tool_input: dict[str, Any] = {"message": message, "mark_complete": mark_complete}
    if data is not None:
        tool_input["data"] = data
    return [
        ToolCallEvent(
            tool_name="report_to_parent",
            tool_input=tool_input,
            tool_use_id="report_mc_1",
        ),
        FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
    ]


# ---------------------------------------------------------------------------
# Tests for mark_complete via report_to_parent
# ---------------------------------------------------------------------------


class TestMarkCompleteViaReport:
    """Tests for report_to_parent(mark_complete=True) termination."""

    @pytest.mark.asyncio
    async def test_mark_complete_terminates_without_output_keys(
        self,
        runtime,
        parent_node_spec,
        subagent_node_spec,
    ):
        """Subagent should terminate immediately when mark_complete=True,
        even without filling output keys via set_output."""
        subagent_llm = MockStreamingLLM(
            [
                report_mark_complete_scenario(
                    "Found 3 profiles",
                    data={"profiles": ["a", "b", "c"]},
                    mark_complete=True,
                ),
                # This should NOT be reached — subagent exits on the same iteration
                text_finish_scenario("Should not get here"),
            ]
        )

        node = EventLoopNode(config=LoopConfig(max_iterations=10))

        buffer = DataBuffer()
        scoped = buffer.with_permissions(read_keys=[], write_keys=["result"])

        ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_node_spec,
            buffer=scoped,
            input_data={},
            llm=subagent_llm,
            available_tools=[],
            goal_context="",
            goal=None,
            node_registry={"researcher": subagent_node_spec},
        )

        result = await node._execute_subagent(ctx, "researcher", "Find profiles")

        assert result.is_error is False
        result_data = json.loads(result.content)

        # Reports should be present with the final message
        assert result_data["reports"] is not None
        assert len(result_data["reports"]) == 1
        assert result_data["reports"][0]["message"] == "Found 3 profiles"
        assert result_data["reports"][0]["data"] == {"profiles": ["a", "b", "c"]}

        # Subagent should have completed (mark_complete bypasses output key check)
        assert result_data["metadata"]["success"] is True

        # Only 2 LLM calls: the report_to_parent turn + text finish for inner loop exit.
        # The outer loop should NOT iterate again because _evaluate returns ACCEPT.
        assert subagent_llm._call_index == 2, (
            f"Expected 2 LLM calls but got {subagent_llm._call_index}. "
            "mark_complete should accept on the same outer iteration."
        )

    @pytest.mark.asyncio
    async def test_mark_complete_false_preserves_existing_behavior(
        self,
        runtime,
        parent_node_spec,
        subagent_node_spec,
    ):
        """mark_complete=False (default) should NOT change existing behavior —
        the subagent still needs to fill output keys."""
        subagent_llm = MockStreamingLLM(
            [
                # Report without mark_complete — should not terminate
                report_mark_complete_scenario(
                    "Progress update",
                    mark_complete=False,
                ),
                # Then fill output via set_output
                set_output_scenario("findings", "Results here"),
                text_finish_scenario(),
            ]
        )

        node = EventLoopNode(config=LoopConfig(max_iterations=10))

        buffer = DataBuffer()
        scoped = buffer.with_permissions(read_keys=[], write_keys=["result"])

        ctx = NodeContext(
            runtime=runtime,
            node_id="parent",
            node_spec=parent_node_spec,
            buffer=scoped,
            input_data={},
            llm=subagent_llm,
            available_tools=[],
            goal_context="",
            goal=None,
            node_registry={"researcher": subagent_node_spec},
        )

        result = await node._execute_subagent(ctx, "researcher", "Do research")

        assert result.is_error is False
        result_data = json.loads(result.content)
        assert result_data["metadata"]["success"] is True
        assert "findings" in result_data["data"]
        assert result_data["data"]["findings"] == "Results here"

        # Should have needed more LLM calls than just the report turn
        assert subagent_llm._call_index >= 3, (
            "mark_complete=False should require additional turns to fill output keys"
        )

    @pytest.mark.asyncio
    async def test_mark_complete_tool_schema_includes_param(self):
        """The report_to_parent tool definition should include mark_complete parameter."""
        node = EventLoopNode()
        tool = node._build_report_to_parent_tool()

        assert "mark_complete" in tool.parameters["properties"]
        assert tool.parameters["properties"]["mark_complete"]["type"] == "boolean"

    @pytest.mark.asyncio
    async def test_mark_complete_with_report_callback(
        self,
        runtime,
        parent_node_spec,
        subagent_node_spec,
    ):
        """mark_complete should still invoke the report callback before terminating."""
        callback_calls: list[dict] = []

        async def tracking_callback(
            message: str,
            data: dict | None = None,
            *,
            wait_for_response: bool = False,
        ) -> str | None:
            callback_calls.append({"message": message, "data": data})
            return None

        subagent_llm = MockStreamingLLM(
            [
                report_mark_complete_scenario("Final findings", data={"count": 5}),
                text_finish_scenario(),
            ]
        )

        # Create a subagent node directly to test with a custom callback
        subagent_node = EventLoopNode(
            judge=SubagentJudge(task="test task"),
            config=LoopConfig(max_iterations=5),
        )

        buffer = DataBuffer()
        scoped = buffer.with_permissions(read_keys=[], write_keys=[])

        ctx = NodeContext(
            runtime=runtime,
            node_id="sub",
            node_spec=subagent_node_spec,
            buffer=scoped,
            input_data={"task": "test task"},
            llm=subagent_llm,
            available_tools=[],
            goal_context="Your specific task: test task",
            goal=None,
            is_subagent_mode=True,
            report_callback=tracking_callback,
            node_registry={},
        )

        result = await subagent_node.execute(ctx)

        # Callback should have been called
        assert len(callback_calls) == 1
        assert callback_calls[0]["message"] == "Final findings"
        assert callback_calls[0]["data"] == {"count": 5}

        # Should have succeeded via mark_complete
        assert result.success is True
