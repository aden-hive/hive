"""Unit tests for shared graph context helpers."""

from __future__ import annotations

from framework.graph.context import (
    GraphContext,
    build_node_accounts_prompt,
    build_node_context,
    build_node_context_from_graph_context,
    build_scoped_buffer,
)
from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import DataBuffer, NodeSpec
from framework.llm.provider import Tool
from framework.skills.defaults import DATA_BUFFER_KEYS


class DummyRuntime:
    execution_id = ""


def _make_tool(name: str) -> Tool:
    return Tool(
        name=name,
        description=f"Tool {name}",
        parameters={"type": "object", "properties": {}},
    )


def _make_goal() -> Goal:
    return Goal(id="goal-1", name="Goal", description="Test goal")


def _make_graph(node_spec: NodeSpec) -> GraphSpec:
    return GraphSpec(
        id="graph-1",
        goal_id="goal-1",
        nodes=[node_spec],
        edges=[],
        entry_node=node_spec.id,
        terminal_nodes=[node_spec.id],
        max_tokens=2048,
    )


def test_build_scoped_buffer_includes_skill_and_existing_internal_keys():
    buffer = DataBuffer()
    buffer.write("task", "draft")
    buffer.write("_worker_state", "active")

    node_spec = NodeSpec(
        id="writer",
        name="Writer",
        description="Writes output",
        node_type="event_loop",
        input_keys=["task"],
        output_keys=["result"],
    )

    scoped = build_scoped_buffer(buffer, node_spec)

    assert "task" in scoped._allowed_read
    assert "result" in scoped._allowed_write
    assert "_worker_state" in scoped._allowed_read
    assert "_worker_state" in scoped._allowed_write
    for key in DATA_BUFFER_KEYS:
        assert key in scoped._allowed_read
        assert key in scoped._allowed_write


def test_build_scoped_buffer_keeps_empty_permissions_unrestricted():
    buffer = DataBuffer()
    buffer.write("task", "draft")
    buffer.write("_worker_state", "active")

    node_spec = NodeSpec(
        id="reader",
        name="Reader",
        description="Reads everything",
        node_type="event_loop",
        input_keys=[],
        output_keys=[],
    )

    scoped = build_scoped_buffer(buffer, node_spec)

    assert scoped._allowed_read == set()
    assert scoped._allowed_write == set()
    assert scoped.read_all()["task"] == "draft"
    assert scoped.read_all()["_worker_state"] == "active"


def test_accounts_prompt_falls_back_when_filtered_prompt_is_empty():
    prompt = build_node_accounts_prompt(
        accounts_prompt="DEFAULT_ACCOUNTS",
        accounts_data=[{"provider": "google", "alias": "personal", "identity": {}}],
        tool_provider_map={"gmail_list_messages": "google"},
        node_tool_names=["slack_post_message"],
        fallback_to_default=True,
    )

    assert prompt == "DEFAULT_ACCOUNTS"


def test_build_node_context_from_graph_context_preserves_continuous_state():
    node_spec = NodeSpec(
        id="writer",
        name="Writer",
        description="Writes output",
        node_type="event_loop",
        input_keys=["task"],
        output_keys=["draft"],
        tools=["save_data"],
    )
    buffer = DataBuffer()
    buffer.write("task", "write the draft")
    conversation = object()
    save_data = _make_tool("save_data")
    fallback_tool = _make_tool("web_search")
    graph = _make_graph(node_spec)

    graph_context = GraphContext(
        graph=graph,
        goal=_make_goal(),
        buffer=buffer,
        runtime=DummyRuntime(),
        llm=None,
        tools=[save_data, fallback_tool],
        tool_executor=None,
        event_bus=None,
        execution_id="exec-1",
        stream_id="stream-1",
        run_id="run-1",
        storage_path=None,
        is_continuous=True,
        continuous_conversation=conversation,
        cumulative_tools=[fallback_tool],
        cumulative_output_keys=["outline", "draft"],
        accounts_prompt="ACCOUNTS",
        skills_catalog_prompt="SKILLS",
        protocols_prompt="PROTOCOLS",
    )

    ctx = build_node_context_from_graph_context(
        graph_context,
        node_spec=node_spec,
        pause_event="pause-signal",
    )

    assert ctx.input_data == {"task": "write the draft"}
    assert ctx.inherited_conversation is conversation
    assert ctx.cumulative_output_keys == ["outline", "draft"]
    assert [tool.name for tool in ctx.available_tools] == ["web_search"]
    assert ctx.pause_event == "pause-signal"
    assert ctx.accounts_prompt == "ACCOUNTS"
    assert ctx.skills_catalog_prompt == "SKILLS"
    assert ctx.protocols_prompt == "PROTOCOLS"


def test_build_node_context_uses_override_tools_for_legacy_executor_path():
    node_spec = NodeSpec(
        id="branch",
        name="Branch",
        description="Legacy branch execution",
        node_type="event_loop",
        input_keys=["task"],
        output_keys=["result"],
        tools=["save_data"],
    )
    buffer = DataBuffer()
    save_data = _make_tool("save_data")
    web_search = _make_tool("web_search")

    ctx = build_node_context(
        runtime=DummyRuntime(),
        node_spec=node_spec,
        buffer=buffer,
        goal=_make_goal(),
        llm=None,
        tools=[save_data],
        max_tokens=1024,
        input_data={"task": "run branch"},
        override_tools=[save_data, web_search],
        node_registry={"branch": node_spec},
    )

    assert ctx.input_data == {"task": "run branch"}
    assert [tool.name for tool in ctx.available_tools] == ["save_data", "web_search"]
    assert ctx.node_registry == {"branch": node_spec}
