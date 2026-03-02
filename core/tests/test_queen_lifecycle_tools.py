import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from framework.tools.queen_lifecycle_tools import (
    register_queen_lifecycle_tools,
)


@pytest.fixture
def mock_registry():
    class MockRegistry:
        def __init__(self):
            self.tools = {}

        def register(self, name, tool, impl):
            self.tools[name] = impl

    return MockRegistry()


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.graph_id = "worker_1"
    runtime.goal.name = "Test Goal"
    runtime.trigger = AsyncMock(return_value="exec_123")
    runtime.get_graph_registration = MagicMock()
    runtime._get_primary_session_state = MagicMock(return_value={})
    return runtime


@pytest.fixture
def mock_session(mock_runtime):
    session = MagicMock()
    session.worker_runtime = mock_runtime
    return session


def test_register_queen_lifecycle_tools(mock_registry, mock_session):
    count = register_queen_lifecycle_tools(mock_registry, session=mock_session)
    assert count >= 4
    assert "start_worker" in mock_registry.tools
    assert "stop_worker" in mock_registry.tools
    assert "get_worker_status" in mock_registry.tools
    assert "inject_worker_message" in mock_registry.tools


@pytest.mark.asyncio
async def test_start_worker_success(mock_registry, mock_session, mock_runtime):
    register_queen_lifecycle_tools(mock_registry, session=mock_session)
    start_worker = mock_registry.tools["start_worker"]

    with patch(
        "framework.tools.queen_lifecycle_tools.validate_agent_credentials",
        return_value=None,
    ):
        res_str = await start_worker({"task": "Do something"})
        res = json.loads(res_str)
        assert res["status"] == "started"
        assert res["execution_id"] == "exec_123"
        mock_runtime.trigger.assert_called_once()


@pytest.mark.asyncio
async def test_stop_worker_success(mock_registry, mock_session, mock_runtime):
    register_queen_lifecycle_tools(mock_registry, session=mock_session)
    stop_worker = mock_registry.tools["stop_worker"]

    mock_reg = MagicMock()
    mock_stream = AsyncMock()
    mock_stream.active_execution_ids = ["exec_123"]
    mock_stream.cancel_execution = AsyncMock(return_value=True)
    mock_reg.streams = {"default": mock_stream}
    mock_runtime.get_graph_registration.return_value = mock_reg

    res_str = await stop_worker({})
    res = json.loads(res_str)
    assert res["status"] == "stopped"
    assert "exec_123" in res["cancelled"]


@pytest.mark.asyncio
async def test_get_worker_status(mock_registry, mock_session, mock_runtime):
    register_queen_lifecycle_tools(mock_registry, session=mock_session)
    get_status = mock_registry.tools["get_worker_status"]

    mock_reg = MagicMock()
    mock_stream = MagicMock()
    mock_stream.active_execution_ids = ["exec_123"]
    mock_reg.streams = {"default": mock_stream}
    mock_runtime.get_graph_registration.return_value = mock_reg

    res_str = await get_status({})
    res = json.loads(res_str)
    assert res["status"] == "running"
    assert res["worker_graph_id"] == "worker_1"


@pytest.mark.asyncio
async def test_inject_worker_message(mock_registry, mock_session, mock_runtime):
    register_queen_lifecycle_tools(mock_registry, session=mock_session)
    inject = mock_registry.tools["inject_worker_message"]

    mock_reg = MagicMock()
    mock_stream = AsyncMock()
    mock_stream.get_injectable_nodes.return_value = [{"node_id": "node1"}]
    mock_stream.inject_input.return_value = True
    mock_reg.streams = {"default": mock_stream}
    mock_runtime.get_graph_registration.return_value = mock_reg

    res_str = await inject({"content": "Hello worker"})
    res = json.loads(res_str)
    assert res["status"] == "delivered"
    assert res["node_id"] == "node1"
