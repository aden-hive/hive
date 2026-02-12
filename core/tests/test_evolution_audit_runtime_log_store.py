import asyncio
import pytest

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.runtime.agent_runtime import AgentRuntime
# EventType not required in this test


class FakeRuntimeLogStore:
    def __init__(self):
        self.writes = []

    def write(self, entry):
        # simple capture
        self.writes.append(entry)


class StubGuardRejectAndAudit:
    def __init__(self):
        self.rolled_back = False

    def snapshot(self, graph):
        return "snap-rls"

    async def probation_run(self, snapshot_id, candidate_graph, steps=10):
        return type("VR", (), {"passed": False, "violations": ["bad"], "metrics": {}})()

    def approve(self, result):
        return False

    def rollback(self, snapshot_id):
        self.rolled_back = True

    def audit_log(self, entry):
        # no-op: runtime should also persist via runtime_log_store
        return None


@pytest.mark.asyncio
async def test_runtime_log_store_used_for_audit(tmp_path):
    old = GraphSpec(id="g1", goal_id="goal1", entry_node="start", nodes=[], edges=[])
    new = GraphSpec(id="g2", goal_id="goal1", entry_node="start", nodes=[], edges=[])

    goal = Goal(id="goal1", name="G", description="d")

    fake_store = FakeRuntimeLogStore()
    guard = StubGuardRejectAndAudit()

    runtime = AgentRuntime(
        graph=old, goal=goal, storage_path=tmp_path, evolution_guard=guard, runtime_log_store=fake_store
    )

    # trigger update
    await runtime.update_graph(new_graph=new, correlation_id="cid-rls")

    # allow async dispatch
    await asyncio.sleep(0.01)

    # runtime_log_store.write should have been called with an audit entry
    assert len(fake_store.writes) >= 1
    assert any(w.get("correlation_id") == "cid-rls" for w in fake_store.writes)
