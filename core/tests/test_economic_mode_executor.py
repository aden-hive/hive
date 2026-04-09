"""Tests for economic mode budget propagation through GraphExecutor -> LoopConfig."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from framework.graph.event_loop_node import EventLoopNode, LoopConfig
from framework.graph.executor import GraphExecutor
from framework.graph.node import DataBuffer, NodeContext, NodeSpec
from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent
from framework.runtime.core import Runtime


@pytest.fixture
def runtime():
    r = MagicMock(spec=Runtime)
    r.start_run = MagicMock(return_value="test_run_id")
    r.decide = MagicMock(return_value="test_decision_id")
    r.record_outcome = MagicMock()
    r.end_run = MagicMock()
    r.report_problem = MagicMock()
    r.set_node = MagicMock()
    return r


def _event_loop_node_spec() -> NodeSpec:
    return NodeSpec(
        id="main",
        name="Main",
        description="",
        node_type="event_loop",
        output_keys=[],
    )


def _capture_loop_config(runtime, loop_config: dict) -> LoopConfig:
    """
    Build a GraphExecutor with the given loop_config, call _get_node_implementation
    for an event_loop node, and return the LoopConfig the EventLoopNode was built with.
    """
    captured = {}
    original_init = EventLoopNode.__init__

    def spy_init(self_node, *args, **kwargs):
        original_init(self_node, *args, **kwargs)
        captured["config"] = self_node._config

    executor = GraphExecutor(runtime=runtime, loop_config=loop_config)
    with patch.object(EventLoopNode, "__init__", spy_init):
        executor._get_node_implementation(_event_loop_node_spec())

    return captured["config"]


class TestExecutorLoopConfigPropagation:
    """Verify GraphExecutor passes loop_config['max_paid_calls_per_node'] into LoopConfig."""

    def test_budget_propagated_to_loop_config(self, runtime):
        cfg = _capture_loop_config(runtime, {"max_paid_calls_per_node": 5})
        assert cfg.max_paid_calls_per_node == 5

    def test_zero_budget_propagated(self, runtime):
        cfg = _capture_loop_config(runtime, {"max_paid_calls_per_node": 0})
        assert cfg.max_paid_calls_per_node == 0

    def test_absent_key_defaults_to_minus_one(self, runtime):
        """When the key is absent, max_paid_calls_per_node must default to -1 (mode off)."""
        cfg = _capture_loop_config(runtime, {})
        assert cfg.max_paid_calls_per_node == -1

    def test_other_loop_config_keys_unaffected(self, runtime):
        """Setting max_paid_calls_per_node should not disturb other LoopConfig fields."""
        cfg = _capture_loop_config(runtime, {"max_paid_calls_per_node": 3, "max_iterations": 77})
        assert cfg.max_paid_calls_per_node == 3
        assert cfg.max_iterations == 77


# ===========================================================================
# Budget blocking: end-to-end EventLoopNode execution tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Minimal streaming LLM mock for budget-blocking tests
# ---------------------------------------------------------------------------


class _MockLLM(LLMProvider):
    """Pre-programmed LLM mock. Each call consumes the next scenario."""

    def __init__(self, scenarios: list[list]) -> None:
        self.scenarios = scenarios
        self._call = 0
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator:
        self.calls.append({"messages": messages, "tools": tools or []})
        events = self.scenarios[self._call % len(self.scenarios)]
        self._call += 1
        for event in events:
            yield event

    def complete(self, messages: list, system: str = "", **kwargs: Any) -> LLMResponse:
        return LLMResponse(content="summary", model="mock", stop_reason="stop")


def _tc(name: str, inp: dict, uid: str | None = None) -> ToolCallEvent:
    return ToolCallEvent(tool_use_id=uid or f"id_{name}", tool_name=name, tool_input=inp)


def _tool_turn(*events: ToolCallEvent) -> list:
    return [*events, FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock")]


def _text_turn(text: str = "Done.") -> list:
    return [
        TextDeltaEvent(content=text, snapshot=text),
        FinishEvent(stop_reason="stop", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _node_spec(output_keys: list[str] | None = None) -> NodeSpec:
    return NodeSpec(
        id="main",
        name="Main",
        description="",
        node_type="event_loop",
        output_keys=output_keys if output_keys is not None else ["result"],
    )


def _ctx(
    runtime: MagicMock,
    spec: NodeSpec,
    llm: _MockLLM,
    tools: list[Tool] | None = None,
    runtime_logger: Any = None,
) -> NodeContext:
    return NodeContext(
        runtime=runtime,
        node_id=spec.id,
        node_spec=spec,
        buffer=DataBuffer(),
        input_data={},
        llm=llm,
        available_tools=tools or [],
        goal_context="",
        runtime_logger=runtime_logger,
    )


class TestBudgetBlocking:
    """Verify that EventLoopNode actually blocks paid calls when the budget is exhausted."""

    @pytest.mark.asyncio
    async def test_paid_call_blocked_at_zero_budget(self, runtime):
        """budget=0: paid tool is blocked; node still completes successfully (soft block)."""
        paid_tool = Tool(name="search", description="Web search", is_paid=True)
        llm = _MockLLM([
            # Turn 1 (inner): LLM calls paid tool → gets budget-exhausted error
            _tool_turn(_tc("search", {"q": "test"}, "ws1")),
            # Turn 2 (inner): LLM calls set_output after seeing the budget error
            _tool_turn(_tc("set_output", {"key": "result", "value": "done"}, "so1")),
            # Turn 3 (inner): text-only → exits _run_single_turn → outer judge accepts
            _text_turn("All done."),
        ])
        spec = _node_spec(["result"])
        node = EventLoopNode(config=LoopConfig(max_paid_calls_per_node=0, max_iterations=10))

        result = await node.execute(_ctx(runtime, spec, llm, tools=[paid_tool]))

        assert result.success is True
        assert result.output.get("result") == "done"

    @pytest.mark.asyncio
    async def test_budget_blocked_calls_reported_to_logger(self, runtime):
        """budget=0: budget_blocked_calls=1 is passed to runtime_logger.log_node_complete."""
        paid_tool = Tool(name="search", description="Web search", is_paid=True)
        llm = _MockLLM([
            _tool_turn(_tc("search", {"q": "test"}, "ws1")),
            _tool_turn(_tc("set_output", {"key": "result", "value": "done"}, "so1")),
            _text_turn("Done."),
        ])
        mock_logger = MagicMock()
        spec = _node_spec(["result"])
        node = EventLoopNode(config=LoopConfig(max_paid_calls_per_node=0, max_iterations=10))

        result = await node.execute(_ctx(runtime, spec, llm, tools=[paid_tool], runtime_logger=mock_logger))

        assert result.success is True
        # The success log_node_complete call must carry budget_blocked_calls=1
        success_calls = [
            c for c in mock_logger.log_node_complete.call_args_list
            if c.kwargs.get("success") is True
        ]
        assert success_calls, "log_node_complete(success=True) was never called"
        assert success_calls[-1].kwargs.get("budget_blocked_calls") == 1

    @pytest.mark.asyncio
    async def test_first_paid_call_allowed_second_blocked_in_batch(self, runtime):
        """budget=1: when two paid calls arrive in the same LLM turn, the first is
        allowed (executes with no-executor error) and the second is blocked."""
        paid_tool = Tool(name="search", description="Web search", is_paid=True)
        llm = _MockLLM([
            # Turn 1: two paid calls in the same batch; second should be blocked
            _tool_turn(
                _tc("search", {"q": "a"}, "ws1"),
                _tc("search", {"q": "b"}, "ws2"),
            ),
            # Turn 2: set_output (after one search executed, one blocked)
            _tool_turn(_tc("set_output", {"key": "result", "value": "done"}, "so1")),
            _text_turn("Done."),
        ])
        mock_logger = MagicMock()
        spec = _node_spec(["result"])
        node = EventLoopNode(config=LoopConfig(max_paid_calls_per_node=1, max_iterations=10))

        result = await node.execute(
            _ctx(runtime, spec, llm, tools=[paid_tool], runtime_logger=mock_logger)
        )

        assert result.success is True
        success_calls = [
            c for c in mock_logger.log_node_complete.call_args_list
            if c.kwargs.get("success") is True
        ]
        assert success_calls, "log_node_complete(success=True) was never called"
        last = success_calls[-1].kwargs
        assert last.get("paid_tool_calls_used") == 1   # first search executed
        assert last.get("budget_blocked_calls") == 1   # second search blocked

    @pytest.mark.asyncio
    async def test_paid_tool_hidden_from_llm_stream_when_budget_zero(self, runtime):
        """budget=0: the paid tool must NOT appear in the tools list sent to the LLM."""
        paid_tool = Tool(name="search", description="Web search", is_paid=True)
        free_tool = Tool(name="calculator", description="Free tool", is_paid=False)
        # Node with no output_keys so it accepts on first text response
        spec = _node_spec([])
        llm = _MockLLM([_text_turn("No search needed.")])
        node = EventLoopNode(config=LoopConfig(max_paid_calls_per_node=0, max_iterations=5))

        result = await node.execute(_ctx(runtime, spec, llm, tools=[paid_tool, free_tool]))

        assert result.success is True
        # The framework-visible tools in the first LLM stream call must not include the paid tool.
        first_call_tool_names = {t.name for t in llm.calls[0]["tools"]}
        assert "search" not in first_call_tool_names, "Paid tool must be hidden when budget=0"
        assert "calculator" in first_call_tool_names, "Free tool must remain visible"
