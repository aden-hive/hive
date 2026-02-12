import asyncio
import asyncio
import pytest

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.runtime.agent_runtime import AgentRuntime
from framework.runtime.event_bus import EventType

# Use the ValidationResult from the runtime skeleton for typing
from framework.runtime.evolution_guard import ValidationResult


class StubGuardApprove:
    def snapshot(self, graph):
        return "s1"

    async def probation_run(self, snapshot_id, candidate_graph, steps=10):
        return ValidationResult(passed=True, violations=[], metrics={})

    def approve(self, result):
        return bool(result.passed)

    def rollback(self, snapshot_id):
        # No-op for approved
        return None

    def audit_log(self, entry):
        return None


class StubGuardReject:
    def snapshot(self, graph):
        return "s2"

    async def probation_run(self, snapshot_id, candidate_graph, steps=10):
        return ValidationResult(passed=False, violations=["infinite_loop"], metrics={})

    def approve(self, result):
        return False

    def rollback(self, snapshot_id):
        # No-op for test
        return None

    def audit_log(self, entry):
        return None


@pytest.mark.asyncio
async def test_update_graph_with_guard_approved(tmp_path):
    """When guard approves, graph should be replaced and GRAPH_EVOLVED should be emitted."""
    old = GraphSpec(
        id="g1",
        goal_id="goal1",
        entry_node="start",
        nodes=[],
        edges=[],
    )
    new = GraphSpec(
        id="g2",
        goal_id="goal1",
        entry_node="start",
        nodes=[],
        edges=[],
    )

    goal = Goal(id="goal1", name="G", description="d")

    runtime = AgentRuntime(
        graph=old,
        goal=goal,
        storage_path=tmp_path,
        evolution_guard=StubGuardApprove(),
    )

    # Subscribe to event
    received = []
    evt = asyncio.Event()

    async def on_evolved(event):
        received.append(event)
        evt.set()

    runtime.event_bus.subscribe(event_types=[EventType.GRAPH_EVOLVED], handler=on_evolved)

    await runtime.update_graph(new_graph=new)

    # Wait briefly if needed (handler should be awaited by publish)
    await asyncio.sleep(0.01)

    assert runtime.graph is new
    assert len(received) == 1


@pytest.mark.asyncio
async def test_update_graph_with_guard_rejected(tmp_path):
    """When guard rejects, graph should remain and GRAPH_EVOLUTION_REJECTED emitted."""
    old = GraphSpec(
        id="g1",
        goal_id="goal1",
        entry_node="start",
        nodes=[],
        edges=[],
    )
    new = GraphSpec(
        id="g2",
        goal_id="goal1",
        entry_node="start",
        nodes=[],
        edges=[],
    )

    goal = Goal(id="goal1", name="G", description="d")

    runtime = AgentRuntime(
        graph=old,
        goal=goal,
        storage_path=tmp_path,
        evolution_guard=StubGuardReject(),
    )

    # Subscribe to rejection event
    received = []
    evt = asyncio.Event()

    async def on_rejected(event):
        received.append(event)
        evt.set()

    runtime.event_bus.subscribe(
        event_types=[EventType.GRAPH_EVOLUTION_REJECTED], handler=on_rejected
    )

    await runtime.update_graph(new_graph=new)

    # Wait briefly to allow event dispatch
    await asyncio.sleep(0.01)

    assert runtime.graph is old
    assert len(received) == 1
