import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from framework.tools.session_graph_tools import register_graph_tools


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
    runtime.list_graphs = MagicMock(return_value=["primary"])
    runtime.add_graph = AsyncMock()
    runtime.remove_graph = AsyncMock()
    runtime.get_graph_registration = MagicMock()
    runtime._get_primary_session_state = MagicMock()
    return runtime


def test_register_graph_tools(mock_registry, mock_runtime):
    count = register_graph_tools(mock_registry, mock_runtime)
    assert count >= 5
    assert "load_agent" in mock_registry.tools
    assert "unload_agent" in mock_registry.tools
    assert "start_agent" in mock_registry.tools
    assert "restart_agent" in mock_registry.tools
    assert "list_agents" in mock_registry.tools


@pytest.mark.asyncio
async def test_load_agent_success(mock_registry, mock_runtime, tmp_path):
    register_graph_tools(mock_registry, mock_runtime)
    load_agent = mock_registry.tools["load_agent"]

    agent_dir = tmp_path / "test_agent"
    agent_dir.mkdir()

    mock_runner = MagicMock()
    mock_runner.graph.nodes = [MagicMock(id="node1")]
    mock_runner.graph.entry_node = "node1"
    mock_runner.graph.async_entry_points = []

    with patch("framework.runner.runner.AgentRunner.load", return_value=mock_runner):
        res_str = await load_agent({"agent_path": str(agent_dir)})
        res = json.loads(res_str)
        assert res["status"] == "loaded"
        assert res["graph_id"] == "test_agent"
        mock_runtime.add_graph.assert_called_once()


@pytest.mark.asyncio
async def test_unload_agent_success(mock_registry, mock_runtime):
    register_graph_tools(mock_registry, mock_runtime)
    unload_agent = mock_registry.tools["unload_agent"]

    res_str = await unload_agent({"graph_id": "test_agent"})
    res = json.loads(res_str)
    assert res["status"] == "unloaded"
    mock_runtime.remove_graph.assert_called_once_with("test_agent")


@pytest.mark.asyncio
async def test_start_agent_success(mock_registry, mock_runtime):
    register_graph_tools(mock_registry, mock_runtime)
    start_agent = mock_registry.tools["start_agent"]

    mock_reg = MagicMock()
    mock_stream = AsyncMock()
    mock_stream.execute.return_value = "exec_123"
    mock_reg.streams = {"default": mock_stream}
    mock_runtime.get_graph_registration.return_value = mock_reg

    res_str = await start_agent({"graph_id": "test_agent", "entry_point": "default"})
    res = json.loads(res_str)
    assert res["status"] == "triggered"
    assert res["execution_id"] == "exec_123"


@pytest.mark.asyncio
async def test_list_agents(mock_registry, mock_runtime):
    register_graph_tools(mock_registry, mock_runtime)
    list_agents = mock_registry.tools["list_agents"]

    mock_reg = MagicMock()
    mock_reg.graph.goal.name = "Test Goal"
    mock_stream = MagicMock()
    mock_stream.active_execution_ids = ["e1"]
    mock_reg.streams = {"default": mock_stream}

    mock_runtime.list_graphs.return_value = ["g1"]
    mock_runtime.get_graph_registration.return_value = mock_reg

    res_str = list_agents({})
    res = json.loads(res_str)
    assert "graphs" in res
    assert len(res["graphs"]) == 1
    assert res["graphs"][0]["graph_id"] == "g1"
