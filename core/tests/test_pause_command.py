from __future__ import annotations

import argparse
from unittest.mock import MagicMock

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec
from framework.runner.cli import cmd_pause
from framework.runtime.core import Runtime


class FailIfExecutedNode(NodeProtocol):
    async def execute(self, ctx: NodeContext) -> NodeResult:
        raise AssertionError("Node should not execute when pause is requested before start")


@pytest.mark.asyncio
async def test_pause_request_file_triggers_graceful_pause(tmp_path) -> None:
    rt = MagicMock(spec=Runtime)
    rt.start_run = MagicMock(return_value="run_id")
    rt.decide = MagicMock(return_value="decision_id")
    rt.record_outcome = MagicMock()
    rt.end_run = MagicMock()
    rt.report_problem = MagicMock()
    rt.set_node = MagicMock()

    goal = Goal(id="g1", name="Test", description="Pause test")

    n1 = NodeSpec(id="n1", name="N1", description="entry", node_type="function")
    graph = GraphSpec(
        id="g",
        goal_id="g1",
        name="PauseGraph",
        entry_node="n1",
        nodes=[n1],
        edges=[],
        terminal_nodes=["n1"],
    )

    session_dir = tmp_path / "sessions" / "session_20260214_190000_abc12345"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "pause.request").write_text("pause\n", encoding="utf-8")

    executor = GraphExecutor(runtime=rt, storage_path=session_dir)
    executor.register_node("n1", FailIfExecutedNode())

    result = await executor.execute(graph, goal, {})

    assert not result.success
    assert result.paused_at == "n1"
    assert "paused" in (result.error or "").lower()
    assert not (session_dir / "pause.request").exists()


def test_cmd_pause_writes_pause_flag(tmp_path, capsys) -> None:
    agent_path = "exports/my_agent"
    session_id = "session_20260214_190100_def67890"
    session_dir = tmp_path / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    args = argparse.Namespace(
        agent_path=agent_path,
        storage_path=str(tmp_path),
        session_id=session_id,
    )

    rc = cmd_pause(args)
    assert rc == 0
    assert (session_dir / "pause.request").exists()
    out = capsys.readouterr().out
    assert session_id in out
