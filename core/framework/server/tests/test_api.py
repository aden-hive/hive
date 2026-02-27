"""
Comprehensive tests for the Hive HTTP API server.

Uses aiohttp TestClient with mocked sessions to test all endpoints
without requiring actual LLM calls or agent loading.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from framework.server.app import create_app
from framework.server.session_manager import Session

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


@dataclass
class MockNodeSpec:
    id: str
    name: str
    description: str = "A test node"
    node_type: str = "event_loop"
    input_keys: list = field(default_factory=list)
    output_keys: list = field(default_factory=list)
    nullable_output_keys: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    routes: dict = field(default_factory=dict)
    max_retries: int = 3
    max_node_visits: int = 0
    client_facing: bool = False
    success_criteria: str | None = None
    system_prompt: str | None = None


@dataclass
class MockEdgeSpec:
    id: str
    source: str
    target: str
    condition: str = "on_success"
    priority: int = 0


@dataclass
class MockGraphSpec:
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    entry_node: str = ""

    def get_node(self, node_id: str):
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None


@dataclass
class MockEntryPoint:
    id: str = "default"
    name: str = "Default"
    entry_node: str = "start"
    trigger_type: str = "manual"


@dataclass
class MockStream:
    is_awaiting_input: bool = False
    _execution_tasks: dict = field(default_factory=dict)
    _active_executors: dict = field(default_factory=dict)

    async def cancel_execution(self, execution_id: str) -> bool:
        return execution_id in self._execution_tasks


@dataclass
class MockGraphRegistration:
    graph: MockGraphSpec = field(default_factory=MockGraphSpec)
    streams: dict = field(default_factory=dict)
    entry_points: dict = field(default_factory=dict)


class MockRuntime:
    """Minimal mock of AgentRuntime with the methods used by route handlers."""

    def __init__(self, graph=None, entry_points=None, log_store=None):
        self._graph = graph or MockGraphSpec()
        self._entry_points = entry_points or [MockEntryPoint()]
        self._runtime_log_store = log_store
        self._mock_streams = {"default": MockStream()}
        self._registration = MockGraphRegistration(
            graph=self._graph,
            streams=self._mock_streams,
            entry_points={"default": self._entry_points[0]},
        )

    def list_graphs(self):
        return ["primary"]

    def get_graph_registration(self, graph_id):
        if graph_id == "primary":
            return self._registration
        return None

    def get_entry_points(self):
        return self._entry_points

    async def trigger(self, ep_id, input_data=None, session_state=None):
        return "exec_test_123"

    async def inject_input(self, node_id, content, graph_id=None, *, is_client_input=False):
        return True

    async def get_goal_progress(self):
        return {"progress": 0.5, "criteria": []}

    def find_awaiting_node(self):
        return None, None

    def get_stats(self):
        return {"running": True, "executions": 1}


class MockAgentInfo:
    name: str = "test_agent"
    description: str = "A test agent"
    goal_name: str = "test_goal"
    node_count: int = 2


def _make_queen_executor():
    """Create a mock queen executor with an injectable queen node."""
    mock_node = MagicMock()
    mock_node.inject_event = AsyncMock()
    executor = MagicMock()
    executor.node_registry = {"queen": mock_node}
    return executor


def _make_session(
    agent_id="test_agent",
    tmp_dir=None,
    runtime=None,
    nodes=None,
    edges=None,
    log_store=None,
    with_queen=True,
):
    """Create a mock Session backed by a temp directory."""
    agent_path = Path(tmp_dir) if tmp_dir else Path("/tmp/test_agent")
    graph = MockGraphSpec(nodes=nodes or [], edges=edges or [])
    rt = runtime or MockRuntime(graph=graph, log_store=log_store)
    runner = MagicMock()
    runner.intro_message = "Test intro"

    mock_event_bus = MagicMock()
    mock_llm = MagicMock()

    queen_executor = _make_queen_executor() if with_queen else None

    return Session(
        id=agent_id,
        event_bus=mock_event_bus,
        llm=mock_llm,
        loaded_at=1000000.0,
        queen_executor=queen_executor,
        worker_id=agent_id,
        worker_path=agent_path,
        runner=runner,
        worker_runtime=rt,
        worker_info=MockAgentInfo(),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=False)
def tmp_agent_dir(tmp_path, monkeypatch):
    """Create a temporary agent directory with session/checkpoint/conversation data.

    Monkeypatches Path.home() so that route handlers resolve session paths
    to the temp directory instead of the real home.
    """
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    agent_name = "test_agent"
    base = tmp_path / ".hive" / "agents" / agent_name
    sessions_dir = base / "sessions"
    sessions_dir.mkdir(parents=True)
    return tmp_path, agent_name, base


@pytest.fixture
def sample_session(tmp_agent_dir):
    """Create a sample session with state.json, checkpoints, and conversations."""
    tmp_path, agent_name, base = tmp_agent_dir
    session_id = "session_20260220_120000_abc12345"
    session_dir = base / "sessions" / session_id

    # state.json
    session_dir.mkdir(parents=True)
    state = {
        "status": "paused",
        "started_at": "2026-02-20T12:00:00",
        "completed_at": None,
        "input_data": {"user_request": "test input"},
        "memory": {"key1": "value1"},
        "progress": {
            "current_node": "node_b",
            "paused_at": "node_b",
            "steps_executed": 5,
            "path": ["node_a", "node_b"],
            "node_visit_counts": {"node_a": 1, "node_b": 1},
            "nodes_with_failures": ["node_b"],
        },
    }
    (session_dir / "state.json").write_text(json.dumps(state))

    # Checkpoints
    cp_dir = session_dir / "checkpoints"
    cp_dir.mkdir()
    cp_data = {
        "checkpoint_id": "cp_node_complete_node_a_001",
        "current_node": "node_a",
        "next_node": "node_b",
        "is_clean": True,
        "timestamp": "2026-02-20T12:01:00",
    }
    (cp_dir / "cp_node_complete_node_a_001.json").write_text(json.dumps(cp_data))

    # Conversations
    conv_dir = session_dir / "conversations" / "node_a" / "parts"
    conv_dir.mkdir(parents=True)
    (conv_dir / "0001.json").write_text(json.dumps({"seq": 1, "role": "user", "content": "hello"}))
    (conv_dir / "0002.json").write_text(
        json.dumps({"seq": 2, "role": "assistant", "content": "hi there"})
    )

    conv_dir_b = session_dir / "conversations" / "node_b" / "parts"
    conv_dir_b.mkdir(parents=True)
    (conv_dir_b / "0003.json").write_text(
        json.dumps({"seq": 3, "role": "user", "content": "continue"})
    )

    # Logs
    logs_dir = session_dir / "logs"
    logs_dir.mkdir()
    summary = {
        "run_id": session_id,
        "status": "paused",
        "total_nodes_executed": 2,
        "node_path": ["node_a", "node_b"],
    }
    (logs_dir / "summary.json").write_text(json.dumps(summary))

    detail_a = {"node_id": "node_a", "node_name": "Node A", "success": True, "total_steps": 3}
    detail_b = {
        "node_id": "node_b",
        "node_name": "Node B",
        "success": False,
        "error": "timeout",
        "retry_count": 2,
        "needs_attention": True,
        "attention_reasons": ["retried"],
        "total_steps": 1,
    }
    (logs_dir / "details.jsonl").write_text(
        json.dumps(detail_a) + "\n" + json.dumps(detail_b) + "\n"
    )

    step_a = {"node_id": "node_a", "step_index": 0, "llm_text": "thinking..."}
    step_b = {"node_id": "node_b", "step_index": 0, "llm_text": "retrying..."}
    (logs_dir / "tool_logs.jsonl").write_text(json.dumps(step_a) + "\n" + json.dumps(step_b) + "\n")

    return session_id, session_dir, state


def _make_app_with_session(session):
    """Create an aiohttp app with a pre-loaded session."""
    app = create_app()
    mgr = app["manager"]
    mgr._sessions[session.id] = session
    return app


@pytest.fixture
def nodes_and_edges():
    """Standard test nodes and edges."""
    nodes = [
        MockNodeSpec(
            id="node_a",
            name="Node A",
            description="First node",
            input_keys=["user_request"],
            output_keys=["result"],
            success_criteria="Produce a valid result",
            system_prompt="You are a helpful assistant that produces valid results.",
        ),
        MockNodeSpec(
            id="node_b",
            name="Node B",
            description="Second node",
            input_keys=["result"],
            output_keys=["final_output"],
            client_facing=True,
        ),
    ]
    edges = [
        MockEdgeSpec(id="e1", source="node_a", target="node_b", condition="on_success"),
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self):
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/health")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"
            assert data["agents_loaded"] == 0
            assert data["sessions"] == 0


class TestSessionCRUD:
    @pytest.mark.asyncio
    async def test_list_sessions_empty(self):
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions")
            assert resp.status == 200
            data = await resp.json()
            assert data["sessions"] == []

    @pytest.mark.asyncio
    async def test_list_sessions_with_loaded(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions")
            assert resp.status == 200
            data = await resp.json()
            assert len(data["sessions"]) == 1
            assert data["sessions"][0]["session_id"] == "test_agent"
            assert data["sessions"][0]["intro_message"] == "Test intro"

    @pytest.mark.asyncio
    async def test_get_session_found(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent")
            assert resp.status == 200
            data = await resp.json()
            assert data["session_id"] == "test_agent"
            assert data["has_worker"] is True
            assert "entry_points" in data
            assert "graphs" in data

    @pytest.mark.asyncio
    async def test_get_session_not_found(self):
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/nonexistent")
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_stop_session(self):
        session = _make_session()
        session.runner.cleanup_async = AsyncMock()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.delete("/api/sessions/test_agent")
            assert resp.status == 200
            data = await resp.json()
            assert data["stopped"] is True

            # Verify it's gone
            resp2 = await client.get("/api/sessions/test_agent")
            assert resp2.status == 404

    @pytest.mark.asyncio
    async def test_stop_session_not_found(self):
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.delete("/api/sessions/nonexistent")
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_session_stats(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/stats")
            assert resp.status == 200
            data = await resp.json()
            assert data["running"] is True

    @pytest.mark.asyncio
    async def test_session_entry_points(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/entry-points")
            assert resp.status == 200
            data = await resp.json()
            assert len(data["entry_points"]) == 1
            assert data["entry_points"][0]["id"] == "default"

    @pytest.mark.asyncio
    async def test_session_graphs(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/graphs")
            assert resp.status == 200
            data = await resp.json()
            assert "primary" in data["graphs"]


class TestExecution:
    @pytest.mark.asyncio
    async def test_trigger(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/trigger",
                json={"entry_point_id": "default", "input_data": {"msg": "hi"}},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["execution_id"] == "exec_test_123"

    @pytest.mark.asyncio
    async def test_trigger_not_found(self):
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/nope/trigger",
                json={"entry_point_id": "default"},
            )
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_inject(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/inject",
                json={"node_id": "node_a", "content": "answer"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["delivered"] is True

    @pytest.mark.asyncio
    async def test_inject_missing_node_id(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/inject",
                json={"content": "answer"},
            )
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_chat_goes_to_queen_when_not_waiting(self):
        """When worker is not awaiting input, chat goes to queen."""
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/chat",
                json={"message": "hello"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "queen"
            assert data["delivered"] is True

    @pytest.mark.asyncio
    async def test_chat_injects_when_node_waiting(self):
        """When a node is awaiting input, /chat should inject instead of trigger."""
        session = _make_session()
        session.worker_runtime.find_awaiting_node = lambda: ("chat_node", "primary")
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/chat",
                json={"message": "user reply"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "injected"
            assert data["node_id"] == "chat_node"
            assert data["delivered"] is True

    @pytest.mark.asyncio
    async def test_chat_503_when_no_queen_or_worker(self):
        """Without queen or waiting worker, chat returns 503."""
        session = _make_session(with_queen=False)
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/chat",
                json={"message": "hello"},
            )
            assert resp.status == 503

    @pytest.mark.asyncio
    async def test_chat_missing_message(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/chat",
                json={"message": ""},
            )
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_pause_not_found(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/pause",
                json={"execution_id": "nonexistent"},
            )
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_pause_missing_execution_id(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/pause",
                json={},
            )
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_goal_progress(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/goal-progress")
            assert resp.status == 200
            data = await resp.json()
            assert data["progress"] == 0.5


class TestResume:
    @pytest.mark.asyncio
    async def test_resume_from_session_state(self, sample_session, tmp_agent_dir):
        """Resume using session state (paused_at)."""
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/resume",
                json={"session_id": session_id},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["execution_id"] == "exec_test_123"
            assert data["resumed_from"] == session_id
            assert data["checkpoint_id"] is None

    @pytest.mark.asyncio
    async def test_resume_with_checkpoint(self, sample_session, tmp_agent_dir):
        """Resume using checkpoint-based recovery."""
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/resume",
                json={
                    "session_id": session_id,
                    "checkpoint_id": "cp_node_complete_node_a_001",
                },
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["checkpoint_id"] == "cp_node_complete_node_a_001"

    @pytest.mark.asyncio
    async def test_resume_missing_session_id(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/resume",
                json={},
            )
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_resume_session_not_found(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/resume",
                json={"session_id": "session_nonexistent"},
            )
            assert resp.status == 404


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_found(self):
        session = _make_session()
        # Put a mock task in the stream so cancel_execution returns True
        session.worker_runtime._mock_streams["default"]._execution_tasks["exec_abc"] = MagicMock()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/stop",
                json={"execution_id": "exec_abc"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["stopped"] is True

    @pytest.mark.asyncio
    async def test_stop_not_found(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/stop",
                json={"execution_id": "nonexistent"},
            )
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_stop_missing_execution_id(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/stop",
                json={},
            )
            assert resp.status == 400


class TestReplay:
    @pytest.mark.asyncio
    async def test_replay_success(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/replay",
                json={
                    "session_id": session_id,
                    "checkpoint_id": "cp_node_complete_node_a_001",
                },
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["execution_id"] == "exec_test_123"
            assert data["replayed_from"] == session_id

    @pytest.mark.asyncio
    async def test_replay_missing_fields(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/replay",
                json={"session_id": "s1"},
            )
            assert resp.status == 400  # missing checkpoint_id

            resp2 = await client.post(
                "/api/sessions/test_agent/replay",
                json={"checkpoint_id": "cp1"},
            )
            assert resp2.status == 400  # missing session_id

    @pytest.mark.asyncio
    async def test_replay_checkpoint_not_found(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/replay",
                json={
                    "session_id": session_id,
                    "checkpoint_id": "nonexistent_cp",
                },
            )
            assert resp.status == 404


class TestWorkerSessions:
    @pytest.mark.asyncio
    async def test_list_sessions(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/worker-sessions")
            assert resp.status == 200
            data = await resp.json()
            assert len(data["sessions"]) == 1
            assert data["sessions"][0]["session_id"] == session_id
            assert data["sessions"][0]["status"] == "paused"
            assert data["sessions"][0]["steps"] == 5

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, tmp_agent_dir):
        tmp_path, agent_name, base = tmp_agent_dir
        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/worker-sessions")
            assert resp.status == 200
            data = await resp.json()
            assert data["sessions"] == []

    @pytest.mark.asyncio
    async def test_get_session(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(f"/api/sessions/test_agent/worker-sessions/{session_id}")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "paused"
            assert data["memory"]["key1"] == "value1"

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, tmp_agent_dir):
        tmp_path, agent_name, base = tmp_agent_dir
        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/worker-sessions/nonexistent")
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_delete_session(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.delete(f"/api/sessions/test_agent/worker-sessions/{session_id}")
            assert resp.status == 200
            data = await resp.json()
            assert data["deleted"] == session_id

            # Verify deleted
            assert not session_dir.exists()

    @pytest.mark.asyncio
    async def test_delete_session_not_found(self, tmp_agent_dir):
        tmp_path, agent_name, base = tmp_agent_dir
        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.delete("/api/sessions/test_agent/worker-sessions/nonexistent")
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_list_checkpoints(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                f"/api/sessions/test_agent/worker-sessions/{session_id}/checkpoints"
            )
            assert resp.status == 200
            data = await resp.json()
            assert len(data["checkpoints"]) == 1
            cp = data["checkpoints"][0]
            assert cp["checkpoint_id"] == "cp_node_complete_node_a_001"
            assert cp["current_node"] == "node_a"
            assert cp["is_clean"] is True

    @pytest.mark.asyncio
    async def test_restore_checkpoint(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                f"/api/sessions/test_agent/worker-sessions/{session_id}"
                "/checkpoints/cp_node_complete_node_a_001/restore"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["execution_id"] == "exec_test_123"
            assert data["restored_from"] == session_id
            assert data["checkpoint_id"] == "cp_node_complete_node_a_001"

    @pytest.mark.asyncio
    async def test_restore_checkpoint_not_found(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                f"/api/sessions/test_agent/worker-sessions/{session_id}/checkpoints/nonexistent_cp/restore"
            )
            assert resp.status == 404


class TestMessages:
    @pytest.mark.asyncio
    async def test_get_messages(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                f"/api/sessions/test_agent/worker-sessions/{session_id}/messages"
            )
            assert resp.status == 200
            data = await resp.json()
            msgs = data["messages"]
            assert len(msgs) == 3
            # Should be sorted by seq
            assert msgs[0]["seq"] == 1
            assert msgs[0]["role"] == "user"
            assert msgs[0]["_node_id"] == "node_a"
            assert msgs[1]["seq"] == 2
            assert msgs[1]["role"] == "assistant"
            assert msgs[2]["seq"] == 3
            assert msgs[2]["_node_id"] == "node_b"

    @pytest.mark.asyncio
    async def test_get_messages_filtered_by_node(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                f"/api/sessions/test_agent/worker-sessions/{session_id}/messages?node_id=node_a"
            )
            assert resp.status == 200
            data = await resp.json()
            msgs = data["messages"]
            assert len(msgs) == 2
            assert all(m["_node_id"] == "node_a" for m in msgs)

    @pytest.mark.asyncio
    async def test_get_messages_no_conversations(self, tmp_agent_dir):
        """Session without conversations directory returns empty list."""
        tmp_path, agent_name, base = tmp_agent_dir
        worker_session_id = "session_empty"
        session_dir = base / "sessions" / worker_session_id
        session_dir.mkdir(parents=True)
        (session_dir / "state.json").write_text(json.dumps({"status": "completed"}))

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                f"/api/sessions/test_agent/worker-sessions/{worker_session_id}/messages"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["messages"] == []

    @pytest.mark.asyncio
    async def test_get_messages_client_only(self, tmp_agent_dir):
        """client_only=true keeps user+client-facing assistant."""
        tmp_path, agent_name, base = tmp_agent_dir
        worker_session_id = "session_client_only"
        session_dir = base / "sessions" / worker_session_id
        session_dir.mkdir(parents=True)
        (session_dir / "state.json").write_text(json.dumps({"status": "completed"}))

        # node_a is NOT client-facing, chat_node IS
        conv_a = session_dir / "conversations" / "node_a" / "parts"
        conv_a.mkdir(parents=True)
        (conv_a / "0001.json").write_text(
            json.dumps({"seq": 1, "role": "user", "content": "system prompt"})
        )
        (conv_a / "0002.json").write_text(
            json.dumps({"seq": 2, "role": "assistant", "content": "internal work"})
        )
        (conv_a / "0003.json").write_text(
            json.dumps({"seq": 3, "role": "tool", "content": "tool result"})
        )

        conv_chat = session_dir / "conversations" / "chat_node" / "parts"
        conv_chat.mkdir(parents=True)
        (conv_chat / "0004.json").write_text(
            json.dumps({"seq": 4, "role": "user", "content": "hi", "is_client_input": True})
        )
        (conv_chat / "0005.json").write_text(
            json.dumps({"seq": 5, "role": "assistant", "content": "hello!"})
        )
        (conv_chat / "0006.json").write_text(
            json.dumps(
                {
                    "seq": 6,
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "tc1", "function": {"name": "search"}}],
                }
            )
        )
        (conv_chat / "0007.json").write_text(
            json.dumps(
                {
                    "seq": 7,
                    "role": "user",
                    "content": "marker",
                    "is_transition_marker": True,
                }
            )
        )

        nodes = [
            MockNodeSpec(id="node_a", name="Node A", client_facing=False),
            MockNodeSpec(id="chat_node", name="Chat", client_facing=True),
        ]
        session = _make_session(
            tmp_dir=tmp_path / ".hive" / "agents" / agent_name,
            nodes=nodes,
        )
        session.runner.graph = MockGraphSpec(nodes=nodes)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                f"/api/sessions/test_agent/worker-sessions/{worker_session_id}/messages?client_only=true"
            )
            assert resp.status == 200
            msgs = (await resp.json())["messages"]
            # Keep: seq 4 (user+is_client_input), seq 5 (assistant from chat_node)
            # Drop: seq 1,2,3,6,7 (internal / tool / tool_calls / marker)
            assert len(msgs) == 2
            assert msgs[0]["seq"] == 4
            assert msgs[0]["role"] == "user"
            assert msgs[1]["seq"] == 5
            assert msgs[1]["role"] == "assistant"
            assert msgs[1]["_node_id"] == "chat_node"

    @pytest.mark.asyncio
    async def test_get_messages_client_only_no_runner_returns_all(self, tmp_agent_dir):
        """client_only=true with no runner skips filtering (returns all messages)."""
        tmp_path, agent_name, base = tmp_agent_dir
        worker_session_id = "session_no_runner"
        session_dir = base / "sessions" / worker_session_id
        session_dir.mkdir(parents=True)
        (session_dir / "state.json").write_text(json.dumps({"status": "completed"}))

        conv = session_dir / "conversations" / "node_a" / "parts"
        conv.mkdir(parents=True)
        (conv / "0001.json").write_text(json.dumps({"seq": 1, "role": "user", "content": "hello"}))
        (conv / "0002.json").write_text(
            json.dumps({"seq": 2, "role": "assistant", "content": "response"})
        )

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        session.runner = None  # Simulate runner not available
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                f"/api/sessions/test_agent/worker-sessions/{worker_session_id}/messages?client_only=true"
            )
            assert resp.status == 200
            msgs = (await resp.json())["messages"]
            # No runner -> can't resolve client-facing nodes -> returns all messages
            assert len(msgs) == 2


class TestGraphNodes:
    @pytest.mark.asyncio
    async def test_list_nodes(self, nodes_and_edges):
        nodes, edges = nodes_and_edges
        session = _make_session(nodes=nodes, edges=edges)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/graphs/primary/nodes")
            assert resp.status == 200
            data = await resp.json()
            assert len(data["nodes"]) == 2
            node_ids = [n["id"] for n in data["nodes"]]
            assert "node_a" in node_ids
            assert "node_b" in node_ids
            # Edges and entry_node must be present
            assert "edges" in data
            assert "entry_node" in data

    @pytest.mark.asyncio
    async def test_list_nodes_includes_edges(self, nodes_and_edges):
        nodes, edges = nodes_and_edges
        graph = MockGraphSpec(nodes=nodes, edges=edges, entry_node="node_a")
        rt = MockRuntime(graph=graph)
        session = _make_session(runtime=rt)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/graphs/primary/nodes")
            assert resp.status == 200
            data = await resp.json()

            # Edges present and correct
            assert "edges" in data
            assert len(data["edges"]) == 1
            assert data["edges"][0]["source"] == "node_a"
            assert data["edges"][0]["target"] == "node_b"
            assert data["edges"][0]["condition"] == "on_success"
            assert data["edges"][0]["priority"] == 0

            # Entry node present
            assert data["entry_node"] == "node_a"

    @pytest.mark.asyncio
    async def test_list_nodes_with_session_enrichment(
        self, nodes_and_edges, sample_session, tmp_agent_dir
    ):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir
        nodes, edges = nodes_and_edges

        session = _make_session(
            tmp_dir=tmp_path / ".hive" / "agents" / agent_name,
            nodes=nodes,
            edges=edges,
        )
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                f"/api/sessions/test_agent/graphs/primary/nodes?session_id={session_id}"
            )
            assert resp.status == 200
            data = await resp.json()
            node_map = {n["id"]: n for n in data["nodes"]}

            assert node_map["node_a"]["visit_count"] == 1
            assert node_map["node_a"]["in_path"] is True
            assert node_map["node_b"]["is_current"] is True
            assert node_map["node_b"]["has_failures"] is True

    @pytest.mark.asyncio
    async def test_list_nodes_graph_not_found(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/graphs/nonexistent/nodes")
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_get_node(self, nodes_and_edges):
        nodes, edges = nodes_and_edges
        session = _make_session(nodes=nodes, edges=edges)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/graphs/primary/nodes/node_a")
            assert resp.status == 200
            data = await resp.json()
            assert data["id"] == "node_a"
            assert data["name"] == "Node A"
            assert data["input_keys"] == ["user_request"]
            assert data["output_keys"] == ["result"]
            assert data["success_criteria"] == "Produce a valid result"
            # Should include edges from this node
            assert len(data["edges"]) == 1
            assert data["edges"][0]["target"] == "node_b"

    @pytest.mark.asyncio
    async def test_node_detail_includes_system_prompt(self, nodes_and_edges):
        """system_prompt should appear in the single-node GET response."""
        nodes, edges = nodes_and_edges
        session = _make_session(nodes=nodes, edges=edges)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/graphs/primary/nodes/node_a")
            assert resp.status == 200
            data = await resp.json()
            assert "system_prompt" in data
            assert (
                data["system_prompt"] == "You are a helpful assistant that produces valid results."
            )

            # Node without system_prompt should return empty string
            resp2 = await client.get("/api/sessions/test_agent/graphs/primary/nodes/node_b")
            assert resp2.status == 200
            data2 = await resp2.json()
            assert data2["system_prompt"] == ""

    @pytest.mark.asyncio
    async def test_get_node_not_found(self, nodes_and_edges):
        nodes, edges = nodes_and_edges
        session = _make_session(nodes=nodes, edges=edges)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/graphs/primary/nodes/nonexistent")
            assert resp.status == 404


class TestNodeCriteria:
    @pytest.mark.asyncio
    async def test_criteria_static(self, nodes_and_edges):
        nodes, edges = nodes_and_edges
        session = _make_session(nodes=nodes, edges=edges)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/graphs/primary/nodes/node_a/criteria")
            assert resp.status == 200
            data = await resp.json()
            assert data["node_id"] == "node_a"
            assert data["success_criteria"] == "Produce a valid result"
            assert data["output_keys"] == ["result"]

    @pytest.mark.asyncio
    async def test_criteria_with_log_enrichment(
        self, nodes_and_edges, sample_session, tmp_agent_dir
    ):
        """Criteria endpoint enriched with last execution from logs."""
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir
        nodes, edges = nodes_and_edges

        # Create a real RuntimeLogStore pointed at the temp agent dir
        from framework.runtime.runtime_log_store import RuntimeLogStore

        log_store = RuntimeLogStore(base)

        session = _make_session(
            tmp_dir=tmp_path / ".hive" / "agents" / agent_name,
            nodes=nodes,
            edges=edges,
            log_store=log_store,
        )
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                f"/api/sessions/test_agent/graphs/primary/nodes/node_b/criteria"
                f"?session_id={session_id}"
            )
            assert resp.status == 200
            data = await resp.json()
            assert "last_execution" in data
            assert data["last_execution"]["success"] is False
            assert data["last_execution"]["error"] == "timeout"
            assert data["last_execution"]["retry_count"] == 2
            assert data["last_execution"]["needs_attention"] is True

    @pytest.mark.asyncio
    async def test_criteria_node_not_found(self, nodes_and_edges):
        nodes, edges = nodes_and_edges
        session = _make_session(nodes=nodes, edges=edges)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/api/sessions/test_agent/graphs/primary/nodes/nonexistent/criteria"
            )
            assert resp.status == 404


class TestLogs:
    @pytest.mark.asyncio
    async def test_logs_no_log_store(self):
        """Agent without log store returns 404."""
        session = _make_session()
        session.worker_runtime._runtime_log_store = None
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/logs")
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_logs_list_summaries(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        from framework.runtime.runtime_log_store import RuntimeLogStore

        log_store = RuntimeLogStore(base)
        session = _make_session(
            tmp_dir=tmp_path / ".hive" / "agents" / agent_name,
            log_store=log_store,
        )
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/logs")
            assert resp.status == 200
            data = await resp.json()
            assert "logs" in data
            assert len(data["logs"]) >= 1
            assert data["logs"][0]["run_id"] == session_id

    @pytest.mark.asyncio
    async def test_logs_session_summary(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        from framework.runtime.runtime_log_store import RuntimeLogStore

        log_store = RuntimeLogStore(base)
        session = _make_session(
            tmp_dir=tmp_path / ".hive" / "agents" / agent_name,
            log_store=log_store,
        )
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                f"/api/sessions/test_agent/logs?session_id={session_id}&level=summary"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["run_id"] == session_id
            assert data["status"] == "paused"

    @pytest.mark.asyncio
    async def test_logs_session_details(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        from framework.runtime.runtime_log_store import RuntimeLogStore

        log_store = RuntimeLogStore(base)
        session = _make_session(
            tmp_dir=tmp_path / ".hive" / "agents" / agent_name,
            log_store=log_store,
        )
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                f"/api/sessions/test_agent/logs?session_id={session_id}&level=details"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["session_id"] == session_id
            assert len(data["nodes"]) == 2
            assert data["nodes"][0]["node_id"] == "node_a"

    @pytest.mark.asyncio
    async def test_logs_session_tools(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        from framework.runtime.runtime_log_store import RuntimeLogStore

        log_store = RuntimeLogStore(base)
        session = _make_session(
            tmp_dir=tmp_path / ".hive" / "agents" / agent_name,
            log_store=log_store,
        )
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                f"/api/sessions/test_agent/logs?session_id={session_id}&level=tools"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["session_id"] == session_id
            assert len(data["steps"]) == 2


class TestNodeLogs:
    @pytest.mark.asyncio
    async def test_node_logs(self, sample_session, tmp_agent_dir, nodes_and_edges):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir
        nodes, edges = nodes_and_edges

        from framework.runtime.runtime_log_store import RuntimeLogStore

        log_store = RuntimeLogStore(base)
        session = _make_session(
            tmp_dir=tmp_path / ".hive" / "agents" / agent_name,
            nodes=nodes,
            edges=edges,
            log_store=log_store,
        )
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                f"/api/sessions/test_agent/graphs/primary/nodes/node_a/logs?session_id={session_id}"
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["node_id"] == "node_a"
            assert data["session_id"] == session_id
            # Only node_a's details
            assert len(data["details"]) == 1
            assert data["details"][0]["node_id"] == "node_a"
            # Only node_a's tool logs
            assert len(data["tool_logs"]) == 1
            assert data["tool_logs"][0]["node_id"] == "node_a"

    @pytest.mark.asyncio
    async def test_node_logs_missing_session_id(self, nodes_and_edges):
        nodes, edges = nodes_and_edges
        from framework.runtime.runtime_log_store import RuntimeLogStore

        log_store = RuntimeLogStore(Path("/tmp/dummy"))
        session = _make_session(nodes=nodes, edges=edges, log_store=log_store)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/graphs/primary/nodes/node_a/logs")
            assert resp.status == 400


class TestCredentials:
    """Tests for credential CRUD routes (/api/credentials)."""

    def _make_app(self, initial_creds=None):
        """Create app with in-memory credential store."""
        from framework.credentials.store import CredentialStore

        app = create_app()
        app["credential_store"] = CredentialStore.for_testing(initial_creds or {})
        return app

    @pytest.mark.asyncio
    async def test_list_credentials_empty(self):
        app = self._make_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/credentials")
            assert resp.status == 200
            data = await resp.json()
            assert data["credentials"] == []

    @pytest.mark.asyncio
    async def test_save_and_list_credential(self):
        app = self._make_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/credentials",
                json={"credential_id": "brave_search", "keys": {"api_key": "test-key-123"}},
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["saved"] == "brave_search"

            resp2 = await client.get("/api/credentials")
            data2 = await resp2.json()
            assert len(data2["credentials"]) == 1
            assert data2["credentials"][0]["credential_id"] == "brave_search"
            assert "api_key" in data2["credentials"][0]["key_names"]
            # Secret value must NOT appear
            assert "test-key-123" not in json.dumps(data2)

    @pytest.mark.asyncio
    async def test_get_credential(self):
        app = self._make_app({"test_cred": {"api_key": "secret-value"}})
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/credentials/test_cred")
            assert resp.status == 200
            data = await resp.json()
            assert data["credential_id"] == "test_cred"
            assert "api_key" in data["key_names"]
            # Secret value must NOT appear
            assert "secret-value" not in json.dumps(data)

    @pytest.mark.asyncio
    async def test_get_credential_not_found(self):
        app = self._make_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/credentials/nonexistent")
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_delete_credential(self):
        app = self._make_app({"test_cred": {"api_key": "val"}})
        async with TestClient(TestServer(app)) as client:
            resp = await client.delete("/api/credentials/test_cred")
            assert resp.status == 200
            data = await resp.json()
            assert data["deleted"] is True

            # Verify it's gone
            resp2 = await client.get("/api/credentials/test_cred")
            assert resp2.status == 404

    @pytest.mark.asyncio
    async def test_delete_credential_not_found(self):
        app = self._make_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.delete("/api/credentials/nonexistent")
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_save_credential_missing_fields(self):
        app = self._make_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/api/credentials", json={})
            assert resp.status == 400

            resp2 = await client.post("/api/credentials", json={"credential_id": "x"})
            assert resp2.status == 400

    @pytest.mark.asyncio
    async def test_save_overwrites_existing(self):
        app = self._make_app({"test_cred": {"api_key": "old-value"}})
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/credentials",
                json={"credential_id": "test_cred", "keys": {"api_key": "new-value"}},
            )
            assert resp.status == 201

            store = app["credential_store"]
            assert store.get_key("test_cred", "api_key") == "new-value"


class TestSSEFormat:
    """Tests for SSE event wire format -- events must be unnamed (data-only)
    so the frontend's es.onmessage handler receives them."""

    @pytest.mark.asyncio
    async def test_send_event_without_event_field(self):
        """SSE events without event= should NOT include 'event:' line."""
        from framework.server.sse import SSEResponse

        sse = SSEResponse()
        mock_response = MagicMock()
        mock_response.write = AsyncMock()
        sse._response = mock_response

        await sse.send_event({"type": "client_output_delta", "data": {"content": "hello"}})

        written = mock_response.write.call_args[0][0].decode()
        assert "event:" not in written
        assert "data:" in written
        assert "client_output_delta" in written

    @pytest.mark.asyncio
    async def test_send_event_with_event_field_present(self):
        """Passing event= produces 'event:' line (documents named event behavior)."""
        from framework.server.sse import SSEResponse

        sse = SSEResponse()
        mock_response = MagicMock()
        mock_response.write = AsyncMock()
        sse._response = mock_response

        await sse.send_event({"type": "test"}, event="test")

        written = mock_response.write.call_args[0][0].decode()
        assert "event: test" in written

    def test_events_route_does_not_pass_event_param(self):
        """Guardrail: routes_events.py must call send_event(data) without event=."""
        import inspect

        from framework.server import routes_events

        source = inspect.getsource(routes_events.handle_events)
        # Should NOT contain send_event(data, event=...)
        assert "send_event(data," not in source
        # Should contain the simple call
        assert "send_event(data)" in source


class TestErrorMiddleware:
    @pytest.mark.asyncio
    async def test_404_on_unknown_api_route(self):
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/nonexistent")
            assert resp.status == 404
