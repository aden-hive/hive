import asyncio
import json
import os
import pytest

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.runtime.agent_runtime import AgentRuntime
from framework.runtime.event_bus import EventType


class StubGuardAuditAndReject:
    def __init__(self):
        self.audit_entries = []
        self.rolled_back = False

    def snapshot(self, graph):
        return "s-audit-1"

    async def probation_run(self, snapshot_id, candidate_graph, steps=10):
        # Fail probation to trigger rejection
        return type("VR", (), {"passed": False, "violations": ["bad"], "metrics": {}})()

    def approve(self, result):
        return False

    def rollback(self, snapshot_id):
        self.rolled_back = True

    def audit_log(self, entry):
        # record in-memory
        self.audit_entries.append(entry)


@pytest.mark.asyncio
async def test_audit_and_rollback_persisted_to_disk(tmp_path):
    old = GraphSpec(id="g1", goal_id="goal1", entry_node="start", nodes=[], edges=[])
    new = GraphSpec(id="g2", goal_id="goal1", entry_node="start", nodes=[], edges=[])

    goal = Goal(id="goal1", name="G", description="d")

    guard = StubGuardAuditAndReject()
    runtime = AgentRuntime(graph=old, goal=goal, storage_path=tmp_path, evolution_guard=guard)

    # Subscribe to rejection event
    received = []

    async def on_rejected(event):
        received.append(event)

    runtime.event_bus.subscribe(event_types=[EventType.GRAPH_EVOLUTION_REJECTED], handler=on_rejected)

    await runtime.update_graph(new_graph=new, correlation_id="cid-123")

    # allow async event dispatch
    await asyncio.sleep(0.01)

    # guard should have recorded audit entry
    assert len(guard.audit_entries) == 1
    entry = guard.audit_entries[0]
    assert entry.get("correlation_id") == "cid-123"

    # audit file should exist on disk under storage_path/evolution_audit
    audit_dir = tmp_path / "evolution_audit"
    files = list(audit_dir.glob("*.json"))
    assert len(files) >= 1

    # rollback should have been invoked
    assert guard.rolled_back is True

    # event should have been emitted
    assert len(received) == 1
