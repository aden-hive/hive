import asyncio
import pytest

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.runtime.agent_runtime import AgentRuntime


class FakeStore:
    def __init__(self):
        self.writes = []

    def write(self, entry):
        self.writes.append(entry)


class StubGuardApproveAndAudit:
    def __init__(self):
        self.audit_entries = []

    def snapshot(self, graph):
        return "snap-approve-2"

    async def probation_run(self, snapshot_id, candidate_graph, steps=10):
        return type("VR", (), {"passed": True, "violations": [], "metrics": {}})()

    def approve(self, result):
        return True

    def rollback(self, snapshot_id):
        # should not be called in approve path
        raise RuntimeError("rollback called unexpectedly")

    def audit_log(self, entry):
        self.audit_entries.append(entry)


@pytest.mark.asyncio
async def test_approve_path_persists_audit_and_applies_graph(tmp_path):
    old = GraphSpec(id="g1", goal_id="goal1", entry_node="start", nodes=[], edges=[])
    new = GraphSpec(id="g2", goal_id="goal1", entry_node="start", nodes=[], edges=[])

    goal = Goal(id="goal1", name="G", description="d")

    fake = FakeStore()
    guard = StubGuardApproveAndAudit()

    runtime = AgentRuntime(graph=old, goal=goal, storage_path=tmp_path, evolution_guard=guard, runtime_log_store=fake)

    received = []

    async def on_evolved(event):
        received.append(event)

    runtime.event_bus.subscribe(event_types=["graph_evolved"], handler=on_evolved)

    await runtime.update_graph(new_graph=new, correlation_id="cid-approve-2")
    await asyncio.sleep(0.01)

    assert runtime.graph is new
    # runtime_log_store.write should have been called
    assert len(fake.writes) >= 1
    assert any(w.get("correlation_id") == "cid-approve-2" for w in fake.writes)
    # guard audit should have been called
    assert len(guard.audit_entries) == 1
    # event emitted
    assert len(received) == 1
