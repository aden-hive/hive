"""
Tests for LifecycleServer REST API.

Tests the HTTP lifecycle control surface that wraps AgentRuntime.
All tests use port=0 so the OS picks a free port, preventing conflicts.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal, SuccessCriterion
from framework.graph.node import NodeSpec
from framework.runtime.agent_runtime import AgentRuntime, AgentRuntimeConfig
from framework.runtime.execution_stream import EntryPointSpec
from framework.runtime.lifecycle_server import LifecycleServer, LifecycleServerConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph_and_goal() -> tuple[GraphSpec, Goal]:
    """Minimal graph + goal for testing."""
    nodes = [
        NodeSpec(
            id="start-node",
            name="Start",
            description="Entry node",
            node_type="event_loop",
            input_keys=["task"],
            output_keys=["result"],
        ),
    ]
    graph = GraphSpec(
        id="test-graph",
        goal_id="test-goal",
        version="1.0.0",
        entry_node="start-node",
        entry_points={"main": "start-node"},
        async_entry_points=[],
        terminal_nodes=[],
        pause_nodes=[],
        nodes=nodes,
        edges=[],
    )
    goal = Goal(
        id="test-goal",
        name="Test",
        description="Test goal",
        success_criteria=[
            SuccessCriterion(
                id="sc-1",
                description="Done",
                metric="done",
                target="yes",
                weight=1.0,
            )
        ],
    )
    return graph, goal


def _make_runtime(tmpdir: str) -> AgentRuntime:
    graph, goal = _make_graph_and_goal()
    runtime = AgentRuntime(
        graph=graph,
        goal=goal,
        storage_path=Path(tmpdir),
    )
    runtime.register_entry_point(
        EntryPointSpec(
            id="main",
            name="Main",
            entry_node="start-node",
            trigger_type="manual",
        )
    )
    return runtime


def _make_server(runtime: AgentRuntime) -> LifecycleServer:
    """Create a LifecycleServer on port=0 (OS-assigned)."""
    return LifecycleServer(runtime, LifecycleServerConfig(host="127.0.0.1", port=0))


def _base_url(server: LifecycleServer) -> str:
    return f"http://127.0.0.1:{server.port}"


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


class TestLifecycleServerLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            await server.start()
            assert server.is_running
            assert server.port is not None

            await server.stop()
            assert not server.is_running
            assert server.port is None

    @pytest.mark.asyncio
    async def test_stop_when_not_started_is_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            # Should not raise
            await server.stop()
            assert not server.is_running


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_when_not_running(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            await server.start()
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{_base_url(server)}/health") as resp:
                        assert resp.status == 200
                        body = await resp.json()
                        assert body["ok"] is True
                        assert body["running"] is False  # runtime not started
            finally:
                await server.stop()

    @pytest.mark.asyncio
    async def test_health_when_running(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            await server.start()
            await runtime.start()
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{_base_url(server)}/health") as resp:
                        assert resp.status == 200
                        body = await resp.json()
                        assert body["ok"] is True
                        assert body["running"] is True
            finally:
                await runtime.stop()
                await server.stop()


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


class TestStatusEndpoint:
    @pytest.mark.asyncio
    async def test_status_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            await server.start()
            await runtime.start()
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{_base_url(server)}/status") as resp:
                        assert resp.status == 200
                        body = await resp.json()
                        assert "running" in body
                        assert "graph_id" in body
                        assert "graphs" in body
                        assert "stats" in body
                        assert body["running"] is True
                        assert isinstance(body["graphs"], list)
            finally:
                await runtime.stop()
                await server.stop()


# ---------------------------------------------------------------------------
# POST /trigger/{entry_point_id}
# ---------------------------------------------------------------------------


class TestTriggerEndpoint:
    @pytest.mark.asyncio
    async def test_trigger_returns_202_and_exec_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            await server.start()
            await runtime.start()
            try:
                with patch.object(runtime, "trigger", new=AsyncMock(return_value="exec-abc123")):
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{_base_url(server)}/trigger/main",
                            json={"input": {"task": "do something"}},
                        ) as resp:
                            assert resp.status == 202
                            body = await resp.json()
                            assert body["execution_id"] == "exec-abc123"
                            assert body["entry_point_id"] == "main"
                            assert body["status"] == "accepted"
            finally:
                await runtime.stop()
                await server.stop()

    @pytest.mark.asyncio
    async def test_trigger_unknown_entry_point_returns_404(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            await server.start()
            await runtime.start()
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{_base_url(server)}/trigger/nonexistent",
                        json={"input": {}},
                    ) as resp:
                        assert resp.status == 404
                        body = await resp.json()
                        assert "error" in body
            finally:
                await runtime.stop()
                await server.stop()

    @pytest.mark.asyncio
    async def test_trigger_when_runtime_not_running_returns_503(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            await server.start()
            # runtime is NOT started
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{_base_url(server)}/trigger/main",
                        json={"input": {}},
                    ) as resp:
                        assert resp.status == 503
                        body = await resp.json()
                        assert "error" in body
            finally:
                await server.stop()

    @pytest.mark.asyncio
    async def test_trigger_passes_input_and_correlation_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            await server.start()
            await runtime.start()

            captured_calls: list[tuple] = []

            async def _mock_trigger(ep_id, input_data, correlation_id=None, **kwargs):
                captured_calls.append((ep_id, input_data, correlation_id))
                return "exec-xyz"

            try:
                with patch.object(runtime, "trigger", side_effect=_mock_trigger):
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{_base_url(server)}/trigger/main",
                            json={
                                "input": {"task": "hello"},
                                "correlation_id": "corr-1",
                            },
                        ) as resp:
                            assert resp.status == 202

                assert len(captured_calls) == 1
                ep_id, input_data, corr_id = captured_calls[0]
                assert ep_id == "main"
                assert input_data == {"task": "hello"}
                assert corr_id == "corr-1"
            finally:
                await runtime.stop()
                await server.stop()

    @pytest.mark.asyncio
    async def test_trigger_empty_body_uses_empty_input(self):
        """Empty POST body should not raise; input defaults to empty dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            await server.start()
            await runtime.start()

            captured: list[dict] = []

            async def _mock_trigger(ep_id, input_data, **kwargs):
                captured.append(input_data)
                return "exec-empty"

            try:
                with patch.object(runtime, "trigger", side_effect=_mock_trigger):
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{_base_url(server)}/trigger/main",
                        ) as resp:
                            assert resp.status == 202

                assert captured == [{}]
            finally:
                await runtime.stop()
                await server.stop()


# ---------------------------------------------------------------------------
# POST /trigger/{entry_point_id}/wait
# ---------------------------------------------------------------------------


class TestTriggerWaitEndpoint:
    @pytest.mark.asyncio
    async def test_trigger_wait_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            from framework.graph.executor import ExecutionResult

            mock_result = ExecutionResult(
                success=True,
                output={"result": "done"},
                error=None,
                node_path=["start-node"],
            )

            await server.start()
            await runtime.start()
            try:
                with patch.object(
                    runtime,
                    "trigger_and_wait",
                    new=AsyncMock(return_value=mock_result),
                ):
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{_base_url(server)}/trigger/main/wait",
                            json={"input": {"task": "run"}},
                        ) as resp:
                            assert resp.status == 200
                            body = await resp.json()
                            assert body["status"] == "completed"
                            assert body["success"] is True
                            assert body["output"] == {"result": "done"}
                            assert body["node_path"] == ["start-node"]
            finally:
                await runtime.stop()
                await server.stop()

    @pytest.mark.asyncio
    async def test_trigger_wait_timeout_returns_408(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            await server.start()
            await runtime.start()
            try:
                with patch.object(
                    runtime,
                    "trigger_and_wait",
                    new=AsyncMock(return_value=None),
                ):
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{_base_url(server)}/trigger/main/wait",
                            json={"input": {}, "timeout": 1.0},
                        ) as resp:
                            assert resp.status == 408
                            body = await resp.json()
                            assert body["status"] == "timeout"
            finally:
                await runtime.stop()
                await server.stop()


# ---------------------------------------------------------------------------
# GET /executions/{entry_point_id}/{execution_id}
# ---------------------------------------------------------------------------


class TestGetExecutionEndpoint:
    @pytest.mark.asyncio
    async def test_get_existing_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            from framework.graph.executor import ExecutionResult

            mock_result = ExecutionResult(
                success=True,
                output={"result": "42"},
                error=None,
                node_path=["start-node"],
            )

            await server.start()
            try:
                with patch.object(
                    runtime,
                    "get_execution_result",
                    return_value=mock_result,
                ):
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"{_base_url(server)}/executions/main/exec-abc"
                        ) as resp:
                            assert resp.status == 200
                            body = await resp.json()
                            assert body["execution_id"] == "exec-abc"
                            assert body["entry_point_id"] == "main"
                            assert body["success"] is True
                            assert body["output"] == {"result": "42"}
            finally:
                await server.stop()

    @pytest.mark.asyncio
    async def test_get_missing_execution_returns_404(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            await server.start()
            try:
                with patch.object(runtime, "get_execution_result", return_value=None):
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"{_base_url(server)}/executions/main/no-such-exec"
                        ) as resp:
                            assert resp.status == 404
                            body = await resp.json()
                            assert "error" in body
            finally:
                await server.stop()


# ---------------------------------------------------------------------------
# POST /stop
# ---------------------------------------------------------------------------


class TestStopEndpoint:
    @pytest.mark.asyncio
    async def test_stop_schedules_shutdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            await server.start()
            await runtime.start()

            stop_called = []

            async def _mock_stop():
                stop_called.append(True)

            try:
                with patch.object(runtime, "stop", side_effect=_mock_stop):
                    async with aiohttp.ClientSession() as session:
                        async with session.post(f"{_base_url(server)}/stop") as resp:
                            assert resp.status == 202
                            body = await resp.json()
                            assert body["status"] == "stopping"

                import asyncio

                await asyncio.sleep(0.05)
                assert len(stop_called) == 1
            finally:
                await server.stop()

    @pytest.mark.asyncio
    async def test_stop_when_already_stopped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = _make_runtime(tmpdir)
            server = _make_server(runtime)

            await server.start()
            # runtime is NOT started
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(f"{_base_url(server)}/stop") as resp:
                        assert resp.status == 200
                        body = await resp.json()
                        assert body["status"] == "already_stopped"
            finally:
                await server.stop()


# ---------------------------------------------------------------------------
# AgentRuntimeConfig integration
# ---------------------------------------------------------------------------


class TestAgentRuntimeLifecycleConfig:
    @pytest.mark.asyncio
    async def test_lifecycle_disabled_by_default(self):
        graph, goal = _make_graph_and_goal()
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = AgentRuntime(
                graph=graph,
                goal=goal,
                storage_path=Path(tmpdir),
            )
            runtime.register_entry_point(
                EntryPointSpec(
                    id="main",
                    name="Main",
                    entry_node="start-node",
                    trigger_type="manual",
                )
            )
            await runtime.start()
            try:
                assert runtime.lifecycle_server is None
            finally:
                await runtime.stop()

    @pytest.mark.asyncio
    async def test_lifecycle_enabled_via_config(self):
        graph, goal = _make_graph_and_goal()
        config = AgentRuntimeConfig(
            lifecycle_enabled=True,
            lifecycle_host="127.0.0.1",
            lifecycle_port=0,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = AgentRuntime(
                graph=graph,
                goal=goal,
                storage_path=Path(tmpdir),
                config=config,
            )
            runtime.register_entry_point(
                EntryPointSpec(
                    id="main",
                    name="Main",
                    entry_node="start-node",
                    trigger_type="manual",
                )
            )
            await runtime.start()
            try:
                assert runtime.lifecycle_server is not None
                assert runtime.lifecycle_server.is_running
                assert runtime.lifecycle_server.port is not None
            finally:
                await runtime.stop()
                assert runtime.lifecycle_server is None
