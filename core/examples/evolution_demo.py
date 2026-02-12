"""Simple evolution demo script.

Demonstrates listening for GRAPH_EVOLUTION_REQUEST and proposing a candidate
graph to runtime.update_graph(...). The demo runs two scenarios: one using
an approving stub guard and one using a rejecting stub guard.

Run with:

    source .venv/bin/activate
    python core/examples/evolution_demo.py

"""
import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.runtime.agent_runtime import AgentRuntime
from framework.runtime.event_bus import EventType

# Simple stub guards
class StubGuardApprove:
    def snapshot(self, graph):
        return "snap-approve"

    async def probation_run(self, snapshot_id, candidate_graph, steps=10):
        return type("VR", (), {"passed": True, "violations": [], "metrics": {}})()

    def approve(self, result):
        return bool(result.passed)

    def rollback(self, snapshot_id):
        return None

    def audit_log(self, entry):
        print("[audit]", json.dumps(entry, indent=2))


class StubGuardReject(StubGuardApprove):
    async def probation_run(self, snapshot_id, candidate_graph, steps=10):
        return type("VR", (), {"passed": False, "violations": ["infinite_loop"], "metrics": {}})()

    def approve(self, result):
        return False


async def run_scenario(guard, scenario_name: str, storage_path: str | None = None):
    print(f"=== Running scenario: {scenario_name} ===")

    old = GraphSpec(id="g1", goal_id="goal1", entry_node="start", nodes=[], edges=[])
    goal = Goal(id="goal1", name="G", description="demo")

    runtime = AgentRuntime(graph=old, goal=goal, storage_path=storage_path, evolution_guard=guard)

    # Subscribe to GRAPH_EVOLUTION_REQUEST to demonstrate a builder that proposes a change
    async def on_request(event):
        print("Received GRAPH_EVOLUTION_REQUEST, proposing candidate graph...")
        # Create a tiny candidate graph that changes the id and adds a node
        candidate = GraphSpec(
            id="g1-evolved",
            goal_id=old.goal_id,
            entry_node="start",
            nodes=[{"id": "start", "type": "start"}, {"id": "new_node", "type": "task"}],
            edges=[{"source": "start", "target": "new_node", "condition": "always"}],
        )
        await runtime.update_graph(new_graph=candidate, correlation_id="demo-1")

    sub_id = runtime.event_bus.subscribe(
        event_types=[EventType.GRAPH_EVOLUTION_REQUEST], handler=on_request
    )

    # Fire a request to simulate aggregator recommending an adjustment
    await runtime.event_bus.emit_graph_evolution_request(
        stream_id="demo", context={"why": "demo"}, correlation_id="demo-ctx"
    )

    # Small sleep to allow async handler to run
    await asyncio.sleep(0.2)

    # Clean up subscription if possible
    try:
        runtime.event_bus.unsubscribe(sub_id)
    except Exception:
        pass


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--storage-path",
        type=str,
        default=None,
        help="Storage path for runtime data",
    )
    args = parser.parse_args()

    storage_path = args.storage_path or tempfile.gettempdir()

    await run_scenario(StubGuardApprove(), "approve-path", storage_path=storage_path)
    await asyncio.sleep(0.2)
    await run_scenario(StubGuardReject(), "reject-path", storage_path=storage_path)


if __name__ == "__main__":
    asyncio.run(main())
