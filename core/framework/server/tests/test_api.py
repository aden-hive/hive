"""
Comprehensive tests for the Hive HTTP API server.

Uses aiohttp TestClient with mocked sessions to test all endpoints
without requiring actual LLM calls or agent loading.
"""

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from framework.host.execution_manager import ExecutionAlreadyRunningError
from framework.host.triggers import TriggerDefinition
from framework.llm.model_catalog import get_models_catalogue
from framework.server import (
    routes_messages,
    routes_queens,
    session_manager as session_manager_module,
)
from framework.server.app import CREDENTIAL_STORE_KEY, SESSION_MANAGER_KEY, create_app
from framework.server.session_manager import Session

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLE_AGENT_PATH = REPO_ROOT / "examples" / "templates" / "deep_research_agent"

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
    sub_agents: list = field(default_factory=list)


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
    trigger_config: dict = field(default_factory=dict)


@dataclass
class MockStream:
    is_awaiting_input: bool = False
    _execution_tasks: dict = field(default_factory=dict)
    _active_executors: dict = field(default_factory=dict)
    active_execution_ids: set = field(default_factory=set)

    async def cancel_execution(self, execution_id: str, reason: str | None = None) -> str:
        return "cancelled" if execution_id in self._execution_tasks else "not_found"


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

    def get_graph_registration(self, colony_id):
        if colony_id == "primary":
            return self._registration
        return None

    def get_entry_points(self):
        return self._entry_points

    async def trigger(self, ep_id, input_data=None, session_state=None):
        return "exec_test_123"

    async def inject_input(self, node_id, content, graph_id=None, *, is_client_input=False):
        return True

    def pause_timers(self):
        pass

    async def get_goal_progress(self):
        return {"progress": 0.5, "criteria": []}

    def find_awaiting_node(self):
        return None, None

    def get_stats(self):
        return {"running": True, "executions": 1}

    def get_timer_next_fire_in(self, ep_id):
        return None


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
    runner.cleanup = AsyncMock()
    runner.intro_message = "Test intro"

    mock_event_bus = MagicMock()
    mock_event_bus.publish = AsyncMock()
    mock_llm = MagicMock()

    queen_executor = _make_queen_executor() if with_queen else None

    return Session(
        id=agent_id,
        event_bus=mock_event_bus,
        llm=mock_llm,
        loaded_at=1000000.0,
        queen_executor=queen_executor,
        colony_id=agent_id,
        worker_path=agent_path,
        runner=runner,
        colony_runtime=rt,
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


def _write_sample_session(base: Path, session_id: str):
    """Create a sample worker session on disk."""
    session_dir = base / "sessions" / session_id

    # state.json
    session_dir.mkdir(parents=True)
    state = {
        "status": "paused",
        "started_at": "2026-02-20T12:00:00",
        "completed_at": None,
        "input_data": {"user_request": "test input"},
        "data_buffer": {"key1": "value1"},
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
    (conv_dir / "0002.json").write_text(json.dumps({"seq": 2, "role": "assistant", "content": "hi there"}))

    conv_dir_b = session_dir / "conversations" / "node_b" / "parts"
    conv_dir_b.mkdir(parents=True)
    (conv_dir_b / "0003.json").write_text(json.dumps({"seq": 3, "role": "user", "content": "continue"}))

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
    (logs_dir / "details.jsonl").write_text(json.dumps(detail_a) + "\n" + json.dumps(detail_b) + "\n")

    step_a = {"node_id": "node_a", "step_index": 0, "llm_text": "thinking..."}
    step_b = {"node_id": "node_b", "step_index": 0, "llm_text": "retrying..."}
    (logs_dir / "tool_logs.jsonl").write_text(json.dumps(step_a) + "\n" + json.dumps(step_b) + "\n")

    return session_id, session_dir, state


def _write_queen_session(tmp_path: Path, queen_id: str, session_id: str, meta: dict | None = None) -> Path:
    """Create a persisted queen session directory for restore tests."""
    session_dir = tmp_path / ".hive" / "agents" / "queens" / queen_id / "sessions" / session_id
    session_dir.mkdir(parents=True)
    if meta is not None:
        (session_dir / "meta.json").write_text(json.dumps(meta))
    return session_dir


def _patch_queen_storage(monkeypatch, tmp_path: Path) -> Path:
    """Point queen storage helpers at the test hive home."""
    queens_dir = tmp_path / ".hive" / "agents" / "queens"
    monkeypatch.setattr(routes_queens, "QUEENS_DIR", queens_dir)
    monkeypatch.setattr(session_manager_module, "QUEENS_DIR", queens_dir)
    return queens_dir


@pytest.fixture
def sample_session(tmp_agent_dir):
    """Create a sample session with state.json, checkpoints, and conversations."""
    _tmp_path, _agent_name, base = tmp_agent_dir
    return _write_sample_session(base, "session_20260220_120000_abc12345")


@pytest.fixture
def custom_id_session(tmp_agent_dir):
    """Create a sample session that uses a custom non-session_* ID."""
    _tmp_path, _agent_name, base = tmp_agent_dir
    return _write_sample_session(base, "my-custom-session")


def _make_app_with_session(session):
    """Create an aiohttp app with a pre-loaded session."""
    app = create_app()
    mgr = app[SESSION_MANAGER_KEY]
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
    async def test_create_session_with_worker_forwards_session_id(self):
        app = create_app()
        manager = app[SESSION_MANAGER_KEY]
        manager.create_session_with_worker_colony = AsyncMock(return_value=_make_session(agent_id="my-custom-session"))

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions",
                json={
                    "session_id": "my-custom-session",
                    "agent_path": str(EXAMPLE_AGENT_PATH),
                },
            )
            data = await resp.json()

        assert resp.status == 201
        assert data["session_id"] == "my-custom-session"
        manager.create_session_with_worker_colony.assert_awaited_once_with(
            str(EXAMPLE_AGENT_PATH.resolve()),
            agent_id=None,
            session_id="my-custom-session",
            model=None,
            initial_prompt=None,
            queen_resume_from=None,
            queen_name=None,
            initial_phase=None,
            worker_name=None,
        )

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

    @pytest.mark.asyncio
    async def test_update_trigger_task(self, tmp_path):
        session = _make_session(tmp_dir=tmp_path)
        session.available_triggers["daily"] = TriggerDefinition(
            id="daily",
            trigger_type="timer",
            trigger_config={"cron": "0 5 * * *"},
            task="Old task",
        )
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.patch(
                "/api/sessions/test_agent/triggers/daily",
                json={"task": "New task"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["task"] == "New task"
            assert data["trigger_config"]["cron"] == "0 5 * * *"
            assert session.available_triggers["daily"].task == "New task"

    @pytest.mark.asyncio
    async def test_update_trigger_cron_restarts_active_timer(self, tmp_path):
        session = _make_session(tmp_dir=tmp_path)
        session.available_triggers["daily"] = TriggerDefinition(
            id="daily",
            trigger_type="timer",
            trigger_config={"cron": "0 5 * * *"},
            task="Run task",
            active=True,
        )
        session.active_trigger_ids.add("daily")
        session.active_timer_tasks["daily"] = asyncio.create_task(asyncio.sleep(60))
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.patch(
                "/api/sessions/test_agent/triggers/daily",
                json={"trigger_config": {"cron": "0 6 * * *"}},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["trigger_config"]["cron"] == "0 6 * * *"
            assert "daily" in session.active_timer_tasks
            assert session.active_timer_tasks["daily"] is not None
            assert session.available_triggers["daily"].trigger_config["cron"] == "0 6 * * *"
            session.active_timer_tasks["daily"].cancel()

    @pytest.mark.asyncio
    async def test_update_trigger_cron_rejects_invalid_expression(self, tmp_path):
        session = _make_session(tmp_dir=tmp_path)
        session.available_triggers["daily"] = TriggerDefinition(
            id="daily",
            trigger_type="timer",
            trigger_config={"cron": "0 5 * * *"},
            task="Run task",
        )
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.patch(
                "/api/sessions/test_agent/triggers/daily",
                json={"trigger_config": {"cron": "not a cron"}},
            )
            assert resp.status == 400


class TestMessageBootstrap:
    @pytest.mark.asyncio
    async def test_classify_requires_non_empty_message(self):
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/api/messages/classify", json={"message": "   "})
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_classify_returns_queen_id_without_touching_sessions(self, monkeypatch):
        app = create_app()
        manager = app[SESSION_MANAGER_KEY]
        # Pre-existing live session must NOT be stopped by classify.
        existing = _make_session(agent_id="live_session")
        existing.queen_name = "queen_growth"
        manager._sessions[existing.id] = existing
        manager.build_llm = MagicMock(return_value=MagicMock())
        manager.stop_session = AsyncMock()
        manager.create_session = AsyncMock()
        monkeypatch.setattr(routes_messages, "select_queen", AsyncMock(return_value="queen_technology"))

        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/api/messages/classify", json={"message": "Build me a scraper"})
            assert resp.status == 200
            data = await resp.json()
            # Assert inside the async-with so app shutdown (which stops
            # sessions as cleanup) doesn't pollute the assertions.
            assert data == {"queen_id": "queen_technology"}
            routes_messages.select_queen.assert_awaited_once()
            manager.stop_session.assert_not_awaited()
            manager.create_session.assert_not_awaited()
            assert "live_session" in manager._sessions


class TestQueenSessionSelection:
    @pytest.mark.asyncio
    async def test_select_queen_session_rejects_foreign_session(self, monkeypatch, tmp_path):
        _patch_queen_storage(monkeypatch, tmp_path)
        _write_queen_session(tmp_path, "queen_growth", "other_session", {"queen_id": "queen_growth"})

        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/queen/queen_technology/session/select",
                json={"session_id": "other_session"},
            )
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_select_queen_session_returns_live_session_without_duplication(self):
        app = create_app()
        manager = app[SESSION_MANAGER_KEY]
        target = _make_session(agent_id="queen_live")
        target.queen_name = "queen_technology"
        other = _make_session(agent_id="other_live")
        other.queen_name = "queen_growth"
        manager._sessions[target.id] = target
        manager._sessions[other.id] = other
        manager.stop_session = AsyncMock(side_effect=lambda sid: manager._sessions.pop(sid, None))

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/queen/queen_technology/session/select",
                json={"session_id": "queen_live"},
            )
            assert resp.status == 200
            data = await resp.json()
            # Assert inside the async-with so app shutdown (which stops
            # remaining sessions as cleanup) doesn't pollute the assertions.
            assert data == {
                "session_id": "queen_live",
                "queen_id": "queen_technology",
                "status": "live",
            }
            # Other queen's live session must be left running so multiple
            # queens can stay active in parallel across navigation.
            manager.stop_session.assert_not_awaited()
            assert "other_live" in manager._sessions

    @pytest.mark.asyncio
    async def test_select_queen_session_restores_specific_history_session(self, monkeypatch, tmp_path):
        _patch_queen_storage(monkeypatch, tmp_path)
        _write_queen_session(
            tmp_path,
            "queen_technology",
            "queen_history",
            {"queen_id": "queen_technology"},
        )

        app = create_app()
        manager = app[SESSION_MANAGER_KEY]
        manager.stop_session = AsyncMock()
        restored = _make_session(agent_id="queen_history", with_queen=False)
        restored.queen_name = "queen_technology"
        manager.create_session = AsyncMock(return_value=restored)

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/queen/queen_technology/session/select",
                json={"session_id": "queen_history"},
            )
            assert resp.status == 200
            data = await resp.json()

        assert data == {
            "session_id": "queen_history",
            "queen_id": "queen_technology",
            "status": "resumed",
        }
        manager.create_session.assert_awaited_once_with(
            queen_resume_from="queen_history",
            initial_prompt=None,
            queen_name="queen_technology",
            initial_phase="independent",
        )

    @pytest.mark.asyncio
    async def test_select_queen_session_restores_worker_backed_history(self, monkeypatch, tmp_path):
        _patch_queen_storage(monkeypatch, tmp_path)
        _write_queen_session(
            tmp_path,
            "queen_technology",
            "worker_history",
            {
                "queen_id": "queen_technology",
                "agent_path": str(EXAMPLE_AGENT_PATH),
            },
        )

        app = create_app()
        manager = app[SESSION_MANAGER_KEY]
        manager.stop_session = AsyncMock()
        restored = _make_session(agent_id="worker_history", with_queen=False)
        restored.queen_name = "queen_technology"
        manager.create_session_with_worker_colony = AsyncMock(return_value=restored)
        manager.create_session = AsyncMock()

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/queen/queen_technology/session/select",
                json={"session_id": "worker_history"},
            )
            assert resp.status == 200
            data = await resp.json()

        assert data == {
            "session_id": "worker_history",
            "queen_id": "queen_technology",
            "status": "resumed",
        }
        manager.create_session_with_worker_colony.assert_awaited_once_with(
            str(EXAMPLE_AGENT_PATH.resolve()),
            queen_resume_from="worker_history",
            initial_prompt=None,
            queen_name="queen_technology",
            initial_phase=None,
        )
        manager.create_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_new_queen_session_creates_fresh_thread(self):
        app = create_app()
        manager = app[SESSION_MANAGER_KEY]
        existing = _make_session(agent_id="old_live")
        existing.queen_name = "queen_growth"
        manager._sessions[existing.id] = existing
        manager.stop_session = AsyncMock(side_effect=lambda sid: manager._sessions.pop(sid, None))
        created = _make_session(agent_id="fresh_thread", with_queen=False)
        created.queen_name = "queen_technology"
        manager.create_session = AsyncMock(return_value=created)

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/queen/queen_technology/session/new",
                json={"initial_phase": "independent"},
            )
            assert resp.status == 200
            data = await resp.json()
            # Assert inside the async-with so app shutdown (which stops
            # remaining sessions as cleanup) doesn't pollute the assertions.
            assert data == {
                "session_id": "fresh_thread",
                "queen_id": "queen_technology",
                "status": "created",
            }
            # Other queen's live session must be left running.
            manager.stop_session.assert_not_awaited()
            assert "old_live" in manager._sessions
            manager.create_session.assert_awaited_once_with(
                initial_prompt=None,
                queen_name="queen_technology",
                initial_phase="independent",
            )


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
    async def test_trigger_returns_409_when_execution_still_running(self):
        session = _make_session()
        session.colony_runtime.trigger = AsyncMock(side_effect=ExecutionAlreadyRunningError("default", ["session-1"]))
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/trigger",
                json={"entry_point_id": "default", "input_data": {"msg": "hi"}},
            )
            assert resp.status == 409
            data = await resp.json()
            assert data["stream_id"] == "default"
            assert data["active_execution_ids"] == ["session-1"]

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
    async def test_chat_publishes_display_message_when_provided(self):
        session = _make_session()
        queen_node = session.queen_executor.node_registry["queen"]
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/chat",
                json={
                    "message": '[Worker asked: "Need approval"]\nUser answered: "Ship it"',
                    "display_message": "Ship it",
                },
            )
            assert resp.status == 200

        published_event = session.event_bus.publish.await_args.args[0]
        assert published_event.data["content"] == "Ship it"
        queen_node.inject_event.assert_awaited_once_with(
            '[Worker asked: "Need approval"]\nUser answered: "Ship it"',
            is_client_input=True,
            image_content=None,
        )

    @pytest.mark.asyncio
    async def test_chat_prefers_queen_even_when_node_waiting(self):
        """When the queen is alive, /chat routes to queen even if a node is waiting."""
        session = _make_session()
        session.colony_runtime.find_awaiting_node = lambda: ("chat_node", "primary")
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/chat",
                json={"message": "user reply"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "queen"
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
    async def test_worker_input_route_removed(self):
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/worker-input",
                json={"message": "hello"},
            )
            # No POST handler remains for this path; aiohttp falls through to an
            # overlapping GET/HEAD route and reports method-not-allowed.
            assert resp.status == 405

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
    async def test_pause_no_active_executions(self):
        """Pause with no active executions returns stopped=False."""
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/pause",
                json={},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["stopped"] is False
            assert data["cancelled"] == []
            assert data["cancelling"] == []
            assert data["timers_paused"] is True

    @pytest.mark.asyncio
    async def test_pause_does_not_cancel_queen(self):
        """Pause should stop the worker but leave the queen running."""
        session = _make_session()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/pause",
                json={},
            )
            assert resp.status == 200
            # Queen's cancel_current_turn should NOT have been called
            queen_node = session.queen_executor.node_registry["queen"]
            queen_node.cancel_current_turn.assert_not_called()

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
        """Direct state-based resume is rejected; checkpoint resume is required."""
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/resume",
                json={"session_id": session_id},
            )
            assert resp.status == 400
            data = await resp.json()
            assert "checkpoint_id is required" in data["error"]

    @pytest.mark.asyncio
    async def test_resume_with_checkpoint(self, sample_session, tmp_agent_dir):
        """Resume using checkpoint-based recovery."""
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        session = _make_session(tmp_dir=tmp_path / ".hive" / "agents" / agent_name)
        session.colony_runtime.trigger = AsyncMock(return_value="exec_test_123")
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
            _, kwargs = session.colony_runtime.trigger.await_args
            assert kwargs["session_state"]["run_id"] == "__legacy_run__"

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
        session.colony_runtime._mock_streams["default"]._execution_tasks["exec_abc"] = MagicMock()
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/stop",
                json={"execution_id": "exec_abc"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["stopped"] is True
            assert data["cancelling"] is False

    @pytest.mark.asyncio
    async def test_stop_returns_accepted_while_execution_is_still_cancelling(self):
        session = _make_session()
        session.colony_runtime._mock_streams["default"].cancel_execution = AsyncMock(return_value="cancelling")
        app = _make_app_with_session(session)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/sessions/test_agent/stop",
                json={"execution_id": "exec_abc"},
            )
            assert resp.status == 202
            data = await resp.json()
            assert data["stopped"] is False
            assert data["cancelling"] is True

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
        session.colony_runtime.trigger = AsyncMock(return_value="exec_test_123")
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
            _, kwargs = session.colony_runtime.trigger.await_args
            assert kwargs["session_state"]["run_id"] == "__legacy_run__"

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
    async def test_list_nodes_with_session_enrichment(self, nodes_and_edges, sample_session, tmp_agent_dir):
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
            resp = await client.get(f"/api/sessions/test_agent/graphs/primary/nodes?session_id={session_id}")
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
            assert data["system_prompt"] == "You are a helpful assistant that produces valid results."

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
    async def test_criteria_with_log_enrichment(self, nodes_and_edges, sample_session, tmp_agent_dir):
        """Criteria endpoint enriched with last execution from logs."""
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir
        nodes, edges = nodes_and_edges

        # Create a real RuntimeLogStore pointed at the temp agent dir
        from framework.tracker.runtime_log_store import RuntimeLogStore

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
                f"/api/sessions/test_agent/graphs/primary/nodes/node_b/criteria?session_id={session_id}"
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
            resp = await client.get("/api/sessions/test_agent/graphs/primary/nodes/nonexistent/criteria")
            assert resp.status == 404


class TestLogs:
    @pytest.mark.asyncio
    async def test_logs_no_log_store(self):
        """Agent without log store returns 404."""
        session = _make_session()
        session.colony_runtime._runtime_log_store = None
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/sessions/test_agent/logs")
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_logs_list_summaries(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        from framework.tracker.runtime_log_store import RuntimeLogStore

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
    async def test_logs_list_summaries_with_custom_id(self, custom_id_session, tmp_agent_dir):
        session_id, session_dir, state = custom_id_session
        tmp_path, agent_name, base = tmp_agent_dir

        from framework.tracker.runtime_log_store import RuntimeLogStore

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

        from framework.tracker.runtime_log_store import RuntimeLogStore

        log_store = RuntimeLogStore(base)
        session = _make_session(
            tmp_dir=tmp_path / ".hive" / "agents" / agent_name,
            log_store=log_store,
        )
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(f"/api/sessions/test_agent/logs?session_id={session_id}&level=summary")
            assert resp.status == 200
            data = await resp.json()
            assert data["run_id"] == session_id
            assert data["status"] == "paused"

    @pytest.mark.asyncio
    async def test_logs_session_details(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        from framework.tracker.runtime_log_store import RuntimeLogStore

        log_store = RuntimeLogStore(base)
        session = _make_session(
            tmp_dir=tmp_path / ".hive" / "agents" / agent_name,
            log_store=log_store,
        )
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(f"/api/sessions/test_agent/logs?session_id={session_id}&level=details")
            assert resp.status == 200
            data = await resp.json()
            assert data["session_id"] == session_id
            assert len(data["nodes"]) == 2
            assert data["nodes"][0]["node_id"] == "node_a"

    @pytest.mark.asyncio
    async def test_logs_session_tools(self, sample_session, tmp_agent_dir):
        session_id, session_dir, state = sample_session
        tmp_path, agent_name, base = tmp_agent_dir

        from framework.tracker.runtime_log_store import RuntimeLogStore

        log_store = RuntimeLogStore(base)
        session = _make_session(
            tmp_dir=tmp_path / ".hive" / "agents" / agent_name,
            log_store=log_store,
        )
        app = _make_app_with_session(session)

        async with TestClient(TestServer(app)) as client:
            resp = await client.get(f"/api/sessions/test_agent/logs?session_id={session_id}&level=tools")
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

        from framework.tracker.runtime_log_store import RuntimeLogStore

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
        from framework.tracker.runtime_log_store import RuntimeLogStore

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
        app[CREDENTIAL_STORE_KEY] = CredentialStore.for_testing(initial_creds or {})
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
    async def test_list_credentials_skips_unreadable_encrypted_entry(self):
        from pydantic import SecretStr

        from framework.credentials.models import CredentialDecryptionError, CredentialKey, CredentialObject

        class BrokenStore:
            def list_credentials(self):
                return ["good_cred", "bad_cred"]

            def get_credential(self, credential_id, refresh_if_needed=False):
                if credential_id == "bad_cred":
                    raise CredentialDecryptionError("bad encrypted file")
                return CredentialObject(
                    id=credential_id,
                    keys={"api_key": CredentialKey(name="api_key", value=SecretStr("secret"))},
                )

        app = create_app()
        app[CREDENTIAL_STORE_KEY] = BrokenStore()

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/credentials")
            assert resp.status == 200
            data = await resp.json()

        assert [c["credential_id"] for c in data["credentials"]] == ["good_cred"]
        assert data["unreadable_credentials"] == ["bad_cred"]
        assert "secret" not in json.dumps(data)

    @pytest.mark.asyncio
    async def test_get_credential_unreadable_returns_recoverable_conflict(self):
        from framework.credentials.models import CredentialDecryptionError

        class BrokenStore:
            def get_credential(self, credential_id, refresh_if_needed=False):
                raise CredentialDecryptionError("bad encrypted file")

        app = create_app()
        app[CREDENTIAL_STORE_KEY] = BrokenStore()

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/credentials/bad_cred")
            data = await resp.json()

        assert resp.status == 409
        assert data["credential_id"] == "bad_cred"
        assert data["recoverable"] is True

    def test_specs_availability_treats_decryption_error_as_unavailable(self):
        from framework.credentials.models import CredentialDecryptionError
        from framework.server.routes_credentials import _is_available_for_specs

        class BrokenStore:
            def is_available(self, credential_id):
                raise CredentialDecryptionError("bad encrypted file")

        assert _is_available_for_specs(BrokenStore(), "exa_search") is False

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

            store = app[CREDENTIAL_STORE_KEY]
            assert store.get_key("test_cred", "api_key") == "new-value"


class TestConfigRoutes:
    """Tests for LLM configuration endpoints."""

    @pytest.mark.asyncio
    async def test_get_models_uses_shared_model_catalogue(self):
        app = create_app()

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/config/models")
            data = await resp.json()

        assert resp.status == 200
        assert data["models"] == get_models_catalogue()

    @pytest.mark.asyncio
    async def test_get_llm_config_exposes_subscription_defaults_from_presets(self):
        app = create_app()
        app[CREDENTIAL_STORE_KEY] = MagicMock()
        app[CREDENTIAL_STORE_KEY].get.return_value = None

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/config/llm")
            data = await resp.json()

        assert resp.status == 200
        subscriptions = {subscription["id"]: subscription for subscription in data["subscriptions"]}
        assert subscriptions["codex"]["default_model"] == "gpt-5.3-codex"
        assert subscriptions["codex"]["api_base"] == "https://chatgpt.com/backend-api/codex"
        assert subscriptions["kimi_code"]["default_model"] == "kimi-k2.5"


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
    async def test_unknown_api_route_falls_back_to_frontend(self):
        app = create_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/nonexistent")
            assert resp.status == 200


class TestCleanupStaleActiveSessions:
    """Tests for _cleanup_stale_active_sessions with two-layer protection."""

    def _make_manager(self):
        from framework.server.session_manager import SessionManager

        return SessionManager()

    def _write_state(self, session_dir: Path, status: str, pid: int | None = None) -> None:
        session_dir.mkdir(parents=True, exist_ok=True)
        state: dict = {"status": status, "session_id": session_dir.name}
        if pid is not None:
            state["pid"] = pid
        (session_dir / "state.json").write_text(json.dumps(state))

    def _read_state(self, session_dir: Path) -> dict:
        return json.loads((session_dir / "state.json").read_text())

    def test_stale_session_is_cancelled(self, tmp_path, monkeypatch):
        """Truly stale active sessions (no live tracking, no PID) get cancelled."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        agent_path = Path("my_agent")
        sessions_dir = tmp_path / ".hive" / "agents" / "my_agent" / "sessions"
        session_dir = sessions_dir / "session_stale_001"

        self._write_state(session_dir, "active")

        mgr = self._make_manager()
        mgr._cleanup_stale_active_sessions(agent_path)

        state = self._read_state(session_dir)
        assert state["status"] == "cancelled"
        assert "Stale session" in state["result"]["error"]

    def test_live_in_memory_session_is_skipped(self, tmp_path, monkeypatch):
        """Sessions tracked in self._sessions must NOT be cancelled (Layer 1)."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        agent_path = Path("my_agent")
        sessions_dir = tmp_path / ".hive" / "agents" / "my_agent" / "sessions"
        session_dir = sessions_dir / "session_live_002"

        self._write_state(session_dir, "active")

        mgr = self._make_manager()
        # Simulate a live session in the manager's in-memory map
        mgr._sessions["session_live_002"] = MagicMock()

        mgr._cleanup_stale_active_sessions(agent_path)

        state = self._read_state(session_dir)
        assert state["status"] == "active", "Live in-memory session should NOT be cancelled"

    def test_session_with_live_pid_is_skipped(self, tmp_path, monkeypatch):
        """Sessions whose owning PID is still alive must NOT be cancelled (Layer 2)."""
        import os

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        agent_path = Path("my_agent")
        sessions_dir = tmp_path / ".hive" / "agents" / "my_agent" / "sessions"
        session_dir = sessions_dir / "session_pid_003"

        # Use the current process PID — guaranteed to be alive
        self._write_state(session_dir, "active", pid=os.getpid())

        mgr = self._make_manager()
        mgr._cleanup_stale_active_sessions(agent_path)

        state = self._read_state(session_dir)
        assert state["status"] == "active", "Session with live PID should NOT be cancelled"

    def test_session_with_dead_pid_is_cancelled(self, tmp_path, monkeypatch):
        """Sessions whose owning PID is dead should be cancelled."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        agent_path = Path("my_agent")
        sessions_dir = tmp_path / ".hive" / "agents" / "my_agent" / "sessions"
        session_dir = sessions_dir / "session_dead_004"

        # Use a PID that is almost certainly not running
        self._write_state(session_dir, "active", pid=999999999)

        mgr = self._make_manager()
        mgr._cleanup_stale_active_sessions(agent_path)

        state = self._read_state(session_dir)
        assert state["status"] == "cancelled"
        assert "Stale session" in state["result"]["error"]

    def test_paused_session_is_never_touched(self, tmp_path, monkeypatch):
        """Paused sessions should remain intact regardless of PID or tracking."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        agent_path = Path("my_agent")
        sessions_dir = tmp_path / ".hive" / "agents" / "my_agent" / "sessions"
        session_dir = sessions_dir / "session_paused_005"

        self._write_state(session_dir, "paused")

        mgr = self._make_manager()
        mgr._cleanup_stale_active_sessions(agent_path)

        state = self._read_state(session_dir)
        assert state["status"] == "paused", "Paused sessions must remain untouched"
