"""Worker-autonomy guardrails for agent_builder_server."""

import json

from framework.graph import Goal, NodeSpec
from framework.mcp import agent_builder_server as builder


def _make_session(name: str = "autonomy_test"):
    session = builder.BuildSession(name=name)
    session.goal = Goal(
        id="g1",
        name="Autonomy Goal",
        description="Workers stay autonomous.",
        success_criteria=[],
        constraints=[],
    )
    return session


def test_add_node_rejects_client_facing_event_loop(monkeypatch):
    session = _make_session()
    monkeypatch.setattr(builder, "_session", session)
    monkeypatch.setattr(builder, "_save_session", lambda _: None)

    raw = builder.add_node(
        node_id="worker",
        name="Worker",
        description="Autonomous worker node",
        node_type="event_loop",
        input_keys='["task"]',
        output_keys='["result"]',
        system_prompt="Do work.",
        client_facing=True,
    )
    data = json.loads(raw)

    assert data["valid"] is False
    assert any("client_facing=True" in err for err in data["errors"])


def test_validate_graph_rejects_client_facing_event_loop(monkeypatch):
    session = _make_session()
    session.nodes = [
        NodeSpec(
            id="worker",
            name="Worker",
            description="Autonomous worker node",
            node_type="event_loop",
            client_facing=True,
            input_keys=[],
            output_keys=[],
            system_prompt="Do work.",
        )
    ]
    monkeypatch.setattr(builder, "_session", session)

    data = json.loads(builder.validate_graph())

    assert data["valid"] is False
    assert any("must not be client_facing" in err for err in data["errors"])
