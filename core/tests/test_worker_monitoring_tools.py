import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools


@pytest.fixture
def mock_registry():
    class MockRegistry:
        def __init__(self):
            self.tools = {}

        def register(self, name, tool, impl):
            self.tools[name] = impl

    return MockRegistry()


@pytest.fixture
def mock_event_bus():
    bus = MagicMock()
    bus.publish = AsyncMock()
    bus.emit_worker_escalation_ticket = AsyncMock()
    bus.emit_queen_intervention_requested = AsyncMock()
    return bus


@pytest.fixture
def storage_dir(tmp_path):
    agent_dir = tmp_path / "test_agent"
    agent_dir.mkdir()
    sessions_dir = agent_dir / "sessions"
    sessions_dir.mkdir()
    return agent_dir


def test_register_worker_monitoring_tools(mock_registry, mock_event_bus, storage_dir):
    count = register_worker_monitoring_tools(mock_registry, mock_event_bus, storage_dir)
    assert count == 3
    assert "get_worker_health_summary" in mock_registry.tools
    assert "emit_escalation_ticket" in mock_registry.tools
    assert "notify_operator" in mock_registry.tools


@pytest.mark.asyncio
async def test_get_worker_health_summary_no_sessions(
    mock_registry, mock_event_bus, storage_dir
):
    register_worker_monitoring_tools(mock_registry, mock_event_bus, storage_dir)
    get_health = mock_registry.tools["get_worker_health_summary"]

    res_str = await get_health({"session_id": "auto"})
    res = json.loads(res_str)
    assert "error" in res
    assert "No sessions found" in res["error"]


@pytest.mark.asyncio
async def test_get_worker_health_summary_auto_discover(
    mock_registry, mock_event_bus, storage_dir
):
    # Setup a dummy session
    session_dir = storage_dir / "sessions" / "sess_123"
    session_dir.mkdir()
    state_path = session_dir / "state.json"
    state_path.write_text(json.dumps({"status": "running"}), encoding="utf-8")

    logs_dir = session_dir / "logs"
    logs_dir.mkdir()
    tool_logs_path = logs_dir / "tool_logs.jsonl"
    tool_logs_path.write_text(
        json.dumps({"verdict": "ACCEPT", "llm_text": "Did some work"})
        + "\n"
        + json.dumps({"verdict": "RETRY", "llm_text": "Failed work"})
        + "\n",
        encoding="utf-8",
    )

    register_worker_monitoring_tools(mock_registry, mock_event_bus, storage_dir)
    get_health = mock_registry.tools["get_worker_health_summary"]

    res_str = await get_health({"session_id": "auto"})
    res = json.loads(res_str)

    assert "error" not in res
    assert res["session_id"] == "sess_123"
    assert res["session_status"] == "running"
    assert res["total_steps"] == 2
    assert res["recent_verdicts"] == ["ACCEPT", "RETRY"]
    assert res["steps_since_last_accept"] == 1


@pytest.mark.asyncio
async def test_emit_escalation_ticket(mock_registry, mock_event_bus, storage_dir):
    register_worker_monitoring_tools(mock_registry, mock_event_bus, storage_dir)
    emit_ticket = mock_registry.tools["emit_escalation_ticket"]

    ticket_data = {
        "severity": "medium",
        "cause": "Agent stuck",
        "suggested_action": "Restart agent",
        "judge_reasoning": "Failed 3 times",
        "ticket_id": "TKT-123",
        "worker_graph_id": "w1",
        "worker_agent_id": "a1",
        "worker_session_id": "s1",
        "worker_node_id": "n1",
        "stall_minutes": 5.0,
        "recent_verdicts": [],
        "session_status": "running",
        "total_steps_checked": 10,
        "steps_since_last_accept": 5,
        "evidence_snippet": "failed",
    }
    res_str = await emit_ticket({"ticket_json": json.dumps(ticket_data)})
    print("EMIT TICKET RES:", res_str)
    res = json.loads(res_str)

    assert res["status"] == "emitted"
    mock_event_bus.emit_worker_escalation_ticket.assert_called_once()
    kwargs = mock_event_bus.emit_worker_escalation_ticket.call_args[1]
    assert (
        kwargs["ticket"].severity == "medium"
        if hasattr(kwargs["ticket"], "severity")
        else kwargs["ticket"]["severity"] == "medium"
    )
    assert (
        kwargs["ticket"].cause == "Agent stuck"
        if hasattr(kwargs["ticket"], "cause")
        else kwargs["ticket"]["cause"] == "Agent stuck"
    )


@pytest.mark.asyncio
async def test_notify_operator(mock_registry, mock_event_bus, storage_dir):
    register_worker_monitoring_tools(mock_registry, mock_event_bus, storage_dir)
    notify = mock_registry.tools["notify_operator"]

    res_str = await notify(
        {"ticket_id": "TKT-123", "analysis": "Needs human input", "urgency": "high"}
    )
    print("NOTIFY RES:", res_str)
    res = json.loads(res_str)

    assert res["status"] == "operator_notified"
    mock_event_bus.emit_queen_intervention_requested.assert_called_once()
    kwargs = mock_event_bus.emit_queen_intervention_requested.call_args[1]
    assert kwargs["analysis"] == "Needs human input"
    assert kwargs["severity"] == "high"
