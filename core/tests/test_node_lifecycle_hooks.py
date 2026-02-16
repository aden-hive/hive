"""
Tests for the node lifecycle hook system.

Covers:
- Hook execution order (on_node_start before on_node_end)
- Error hook (on_node_error fired on failure, not on_node_end)
- Hook isolation (exception in hook does not crash node execution)
- Event payload correctness
- Partial implementation (object with only some hook methods)
- Multi-node hook ordering
- EventBus integration (NODE_STARTED / NODE_COMPLETED / NODE_ERROR events)
- Retry sequence (start -> error -> retry -> start -> end)
- Branching graph (hooks fire only for executed nodes)
- Hook exception logging
"""

import logging

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import (
    BaseNodeLifecycleHook,
    NodeEndEvent,
    NodeErrorEvent,
    NodeResult,
    NodeSpec,
    NodeStartEvent,
)

# ---- Shared test fixtures ----


class DummyRuntime:
    def start_run(self, **kwargs):
        return "run-1"

    def end_run(self, **kwargs):
        pass

    def report_problem(self, **kwargs):
        pass


class SuccessNode:
    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=True,
            output={"result": 42},
            tokens_used=1,
            latency_ms=1,
        )


class FailingNode:
    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=False,
            error="intentional failure",
            output={},
            tokens_used=0,
            latency_ms=0,
        )


class ExplodingNode:
    """Node that raises an unhandled exception."""

    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        raise RuntimeError("unhandled boom")


def _single_node_graph(node_id="n1", node_type="llm_generate"):
    return GraphSpec(
        id="graph-hook",
        goal_id="g-hook",
        nodes=[
            NodeSpec(
                id=node_id,
                name="test-node",
                description="hook test node",
                node_type=node_type,
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            )
        ],
        edges=[],
        entry_node=node_id,
    )


def _two_node_graph():
    return GraphSpec(
        id="graph-two",
        goal_id="g-two",
        nodes=[
            NodeSpec(
                id="n1",
                name="first",
                description="first node",
                node_type="llm_generate",
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            ),
            NodeSpec(
                id="n2",
                name="second",
                description="second node",
                node_type="llm_generate",
                input_keys=["result"],
                output_keys=["result"],
                max_retries=0,
            ),
        ],
        edges=[
            EdgeSpec(
                id="e1",
                source="n1",
                target="n2",
                condition=EdgeCondition.ON_SUCCESS,
            ),
        ],
        entry_node="n1",
        terminal_nodes=["n2"],
    )


GOAL = Goal(id="g-hook", name="hook-test", description="lifecycle hook test")
GOAL_TWO = Goal(id="g-two", name="two-test", description="two-node hook test")


# ---- Recording hook ----


class RecordingHook(BaseNodeLifecycleHook):
    """Hook that records every lifecycle event it receives."""

    def __init__(self):
        self.events: list[tuple[str, object]] = []

    async def on_node_start(self, event: NodeStartEvent) -> None:
        self.events.append(("on_node_start", event))

    async def on_node_end(self, event: NodeEndEvent) -> None:
        self.events.append(("on_node_end", event))

    async def on_node_error(self, event: NodeErrorEvent) -> None:
        self.events.append(("on_node_error", event))


# ---- Tests ----


@pytest.mark.asyncio
async def test_hook_execution_order_on_success():
    """on_node_start fires before on_node_end for a successful node."""
    hook = RecordingHook()

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": SuccessNode()},
        lifecycle_hooks=[hook],
    )

    result = await executor.execute(graph=_single_node_graph(), goal=GOAL)

    assert result.success is True
    assert len(hook.events) == 2
    assert hook.events[0][0] == "on_node_start"
    assert hook.events[1][0] == "on_node_end"


@pytest.mark.asyncio
async def test_hook_on_node_error_on_failure():
    """on_node_error fires (not on_node_end) when a node returns success=False."""
    hook = RecordingHook()

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": FailingNode()},
        lifecycle_hooks=[hook],
    )

    result = await executor.execute(graph=_single_node_graph(), goal=GOAL)

    assert result.success is False
    assert len(hook.events) == 2
    assert hook.events[0][0] == "on_node_start"
    assert hook.events[1][0] == "on_node_error"

    error_event = hook.events[1][1]
    assert isinstance(error_event, NodeErrorEvent)
    assert error_event.error == "intentional failure"
    assert error_event.exception is None  # No unhandled exception


@pytest.mark.asyncio
async def test_hook_on_unhandled_exception():
    """on_node_error fires with the exception when a node raises."""
    hook = RecordingHook()

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": ExplodingNode()},
        lifecycle_hooks=[hook],
    )

    result = await executor.execute(graph=_single_node_graph(), goal=GOAL)

    assert result.success is False

    # on_node_start fires, then the unhandled exception triggers on_node_error
    start_events = [e for e in hook.events if e[0] == "on_node_start"]
    error_events = [e for e in hook.events if e[0] == "on_node_error"]
    assert len(start_events) == 1
    assert len(error_events) == 1

    error_event = error_events[0][1]
    assert isinstance(error_event, NodeErrorEvent)
    assert "unhandled boom" in error_event.error
    assert isinstance(error_event.exception, RuntimeError)


@pytest.mark.asyncio
async def test_retry_sequence(monkeypatch):
    """Verify lifecycle hooks and retry event ordering for a flaky node."""

    async def fake_sleep(*args, **kwargs):
        return None

    monkeypatch.setattr("framework.graph.executor.asyncio.sleep", fake_sleep)

    class FlakyNode:
        def __init__(self):
            self.calls = 0

        def validate_input(self, ctx):
            return []

        async def execute(self, ctx):
            self.calls += 1
            if self.calls == 1:
                return NodeResult(
                    success=False, error="boom", output={}, tokens_used=0, latency_ms=0
                )
            return NodeResult(success=True, output={"result": "ok"}, tokens_used=1, latency_ms=1)

    hook = RecordingHook()

    class FakeBus:
        def __init__(self):
            self.events = []

        async def emit_node_loop_started(self, **kw):
            self.events.append(("loop_started", kw))

        async def emit_node_loop_completed(self, **kw):
            self.events.append(("loop_completed", kw))

        async def emit_node_started(self, **kw):
            self.events.append(("node_started", kw))

        async def emit_node_completed(self, **kw):
            self.events.append(("node_completed", kw))

        async def emit_node_error(self, **kw):
            self.events.append(("node_error", kw))

        async def emit_node_retry(self, **kw):
            self.events.append(("retry", kw))

    graph = GraphSpec(
        id="g-retry",
        goal_id="gr",
        nodes=[
            NodeSpec(
                id="n1",
                name="n1",
                description="flaky",
                node_type="llm_generate",
                input_keys=[],
                output_keys=["result"],
                max_retries=2,
            )
        ],
        edges=[],
        entry_node="n1",
    )

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": FlakyNode()},
        lifecycle_hooks=[hook],
        event_bus=FakeBus(),
        stream_id="s-retry",
    )

    res = await executor.execute(graph=graph, goal=GOAL)
    assert res.success is True

    # Hook event order: start, error, start, end
    assert [e[0] for e in hook.events] == [
        "on_node_start",
        "on_node_error",
        "on_node_start",
        "on_node_end",
    ]

    # EventBus saw a retry
    assert any(ev[0] == "retry" for ev in executor._event_bus.events)


@pytest.mark.asyncio
async def test_branching_hooks_only_for_executed_nodes():
    """Hooks fire only for nodes on the executed path."""
    hook = RecordingHook()

    graph = GraphSpec(
        id="g-branch",
        goal_id="gb",
        nodes=[
            NodeSpec(
                id="n1",
                name="n1",
                description="",
                node_type="llm_generate",
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            ),
            NodeSpec(
                id="n2",
                name="n2",
                description="",
                node_type="llm_generate",
                input_keys=["result"],
                output_keys=["result"],
                max_retries=0,
            ),
        ],
        edges=[
            EdgeSpec(id="e1", source="n1", target="n2", condition=EdgeCondition.ON_SUCCESS),
        ],
        entry_node="n1",
        terminal_nodes=["n2"],
    )

    class EchoNode:
        def validate_input(self, ctx):
            return []

        async def execute(self, ctx):
            return NodeResult(success=True, output={"result": "v"}, tokens_used=1, latency_ms=1)

    # n3 is registered but NOT in the graph -- should never fire
    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": EchoNode(), "n2": EchoNode(), "n3": EchoNode()},
        lifecycle_hooks=[hook],
    )

    res = await executor.execute(graph=graph, goal=GOAL)
    assert res.success is True

    seen_ids = [e[1].node_id for e in hook.events if e[0] == "on_node_start"]
    assert "n1" in seen_ids
    assert "n2" in seen_ids
    assert "n3" not in seen_ids


@pytest.mark.asyncio
async def test_hook_exception_logged(caplog):
    """If a hook raises, the executor logs a warning with the hook identity."""

    class BadHook(BaseNodeLifecycleHook):
        async def on_node_start(self, event):
            raise RuntimeError("bad hook")

    caplog.set_level(logging.WARNING)
    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": SuccessNode()},
        lifecycle_hooks=[BadHook()],
    )
    await executor.execute(graph=_single_node_graph(), goal=GOAL)

    assert any(
        "Hook BadHook.on_node_start raised an exception" in rec.getMessage()
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_hook_isolation_exception_suppressed():
    """A hook that raises does not crash node execution; subsequent hooks still fire."""

    class CrashingHook(BaseNodeLifecycleHook):
        async def on_node_start(self, event):
            raise RuntimeError("hook crash")

    crashing = CrashingHook()
    recording = RecordingHook()

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": SuccessNode()},
        lifecycle_hooks=[crashing, recording],
    )

    result = await executor.execute(graph=_single_node_graph(), goal=GOAL)

    assert result.success is True

    # The recording hook still received both events despite the crash
    assert len(recording.events) == 2
    assert recording.events[0][0] == "on_node_start"
    assert recording.events[1][0] == "on_node_end"


@pytest.mark.asyncio
async def test_event_payloads():
    """Verify NodeStartEvent and NodeEndEvent carry correct identity fields."""
    hook = RecordingHook()

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": SuccessNode()},
        lifecycle_hooks=[hook],
    )

    await executor.execute(graph=_single_node_graph(), goal=GOAL)

    start_event = hook.events[0][1]
    assert isinstance(start_event, NodeStartEvent)
    assert start_event.node_id == "n1"
    assert start_event.node_name == "test-node"
    assert start_event.node_type == "llm_generate"

    end_event = hook.events[1][1]
    assert isinstance(end_event, NodeEndEvent)
    assert end_event.node_id == "n1"
    assert end_event.node_name == "test-node"
    assert end_event.node_type == "llm_generate"
    assert end_event.success is True
    assert end_event.error is None


@pytest.mark.asyncio
async def test_frozen_event_dataclasses():
    """Event dataclasses are frozen and cannot be mutated."""
    hook = RecordingHook()

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": SuccessNode()},
        lifecycle_hooks=[hook],
    )

    await executor.execute(graph=_single_node_graph(), goal=GOAL)

    start_event = hook.events[0][1]
    with pytest.raises(AttributeError):
        start_event.node_id = "tampered"


@pytest.mark.asyncio
async def test_partial_hook_implementation():
    """An object with only on_node_start (no on_node_end/error) does not raise."""

    class StartOnlyHook:
        def __init__(self):
            self.called = False

        async def on_node_start(self, event):
            self.called = True

    hook = StartOnlyHook()

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": SuccessNode()},
        lifecycle_hooks=[hook],
    )

    result = await executor.execute(graph=_single_node_graph(), goal=GOAL)

    assert result.success is True
    assert hook.called is True


@pytest.mark.asyncio
async def test_multi_node_hook_ordering():
    """Hooks fire for each node in traversal order (n1 then n2)."""
    hook = RecordingHook()

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": SuccessNode(), "n2": SuccessNode()},
        lifecycle_hooks=[hook],
    )

    result = await executor.execute(graph=_two_node_graph(), goal=GOAL_TWO)

    assert result.success is True
    assert result.path == ["n1", "n2"]

    # 4 events: start(n1), end(n1), start(n2), end(n2)
    assert len(hook.events) == 4
    assert hook.events[0][0] == "on_node_start"
    assert hook.events[0][1].node_id == "n1"
    assert hook.events[1][0] == "on_node_end"
    assert hook.events[1][1].node_id == "n1"
    assert hook.events[2][0] == "on_node_start"
    assert hook.events[2][1].node_id == "n2"
    assert hook.events[3][0] == "on_node_end"
    assert hook.events[3][1].node_id == "n2"


@pytest.mark.asyncio
async def test_eventbus_node_started_and_completed():
    """NODE_STARTED and NODE_COMPLETED events are published to the EventBus."""

    class FakeEventBus:
        def __init__(self):
            self.events = []

        async def emit_node_loop_started(self, **kw):
            self.events.append(("loop_started", kw))

        async def emit_node_loop_completed(self, **kw):
            self.events.append(("loop_completed", kw))

        async def emit_node_started(self, **kw):
            self.events.append(("node_started", kw))

        async def emit_node_completed(self, **kw):
            self.events.append(("node_completed", kw))

        async def emit_node_error(self, **kw):
            self.events.append(("node_error", kw))

        async def emit_edge_traversed(self, **kw):
            self.events.append(("edge_traversed", kw))

    bus = FakeEventBus()

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": SuccessNode()},
        event_bus=bus,
        stream_id="s1",
    )

    result = await executor.execute(graph=_single_node_graph(), goal=GOAL)
    assert result.success is True

    started = [e for e in bus.events if e[0] == "node_started"]
    completed = [e for e in bus.events if e[0] == "node_completed"]

    assert len(started) == 1
    assert started[0][1]["node_id"] == "n1"
    assert started[0][1]["node_name"] == "test-node"

    assert len(completed) == 1
    assert completed[0][1]["node_id"] == "n1"
    assert completed[0][1]["success"] is True


@pytest.mark.asyncio
async def test_eventbus_node_error_on_failure():
    """NODE_ERROR event is published to the EventBus when a node fails."""

    class FakeEventBus:
        def __init__(self):
            self.events = []

        async def emit_node_loop_started(self, **kw):
            self.events.append(("loop_started", kw))

        async def emit_node_loop_completed(self, **kw):
            self.events.append(("loop_completed", kw))

        async def emit_node_started(self, **kw):
            self.events.append(("node_started", kw))

        async def emit_node_completed(self, **kw):
            self.events.append(("node_completed", kw))

        async def emit_node_error(self, **kw):
            self.events.append(("node_error", kw))

        async def emit_edge_traversed(self, **kw):
            pass

        async def emit_node_retry(self, **kw):
            pass

    bus = FakeEventBus()

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": FailingNode()},
        event_bus=bus,
        stream_id="s1",
    )

    result = await executor.execute(graph=_single_node_graph(), goal=GOAL)
    assert result.success is False

    errors = [e for e in bus.events if e[0] == "node_error"]
    assert len(errors) == 1
    assert errors[0][1]["node_id"] == "n1"
    assert "intentional failure" in errors[0][1]["error"]


@pytest.mark.asyncio
async def test_no_hooks_no_regression():
    """Executor works identically when no lifecycle_hooks are provided."""
    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": SuccessNode()},
    )

    result = await executor.execute(graph=_single_node_graph(), goal=GOAL)

    assert result.success is True
    assert result.path == ["n1"]
    assert result.steps_executed == 1
