from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

import framework.tools.queen_lifecycle_tools as qlt
from framework.graph.event_loop_node import EventLoopNode, LoopConfig
from framework.graph.node import NodeContext, NodeSpec, SharedMemory
from framework.llm.provider import LLMProvider, Tool
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.event_bus import AgentEvent, EventBus, EventType
from framework.server.app import create_app, validate_agent_path
from framework.server.session_manager import (
    Session,
    _run_validation_report_sync,
    _validation_blocks_stage_or_run,
)
from framework.tools.queen_lifecycle_tools import QueenPhaseState, register_queen_lifecycle_tools

REPO_ROOT = Path(__file__).resolve().parents[2]


class MockStreamingLLM(LLMProvider):
    """Minimal streaming LLM for parity-gate regressions."""

    def __init__(self, scenarios: list[list[Any]] | None = None):
        self.scenarios = scenarios or []
        self._call_index = 0

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools=None,
        max_tokens: int = 4096,
    ):
        if not self.scenarios:
            return
        events = self.scenarios[self._call_index % len(self.scenarios)]
        self._call_index += 1
        for event in events:
            yield event

    def complete(self, messages, system="", **kwargs):
        raise NotImplementedError


def text_scenario(text: str) -> list[Any]:
    return [
        TextDeltaEvent(content=text, snapshot=text),
        FinishEvent(stop_reason="stop", input_tokens=10, output_tokens=5, model="mock"),
    ]


def tool_call_scenario(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    tool_use_id: str = "call_1",
) -> list[Any]:
    return [
        ToolCallEvent(tool_use_id=tool_use_id, tool_name=tool_name, tool_input=tool_input),
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"),
    ]


def build_ctx(
    spec: NodeSpec,
    llm: LLMProvider,
    *,
    stream_id: str = "worker",
    input_data: dict[str, Any] | None = None,
) -> NodeContext:
    runtime = MagicMock()
    runtime.start_run = MagicMock(return_value="session_codex_parity")
    runtime.decide = MagicMock(return_value="dec_1")
    runtime.record_outcome = MagicMock()
    runtime.end_run = MagicMock()
    runtime.report_problem = MagicMock()
    runtime.set_node = MagicMock()
    return NodeContext(
        runtime=runtime,
        node_id=spec.id,
        node_spec=spec,
        memory=SharedMemory(),
        input_data=input_data or {},
        llm=llm,
        available_tools=[],
        stream_id=stream_id,
    )


@pytest.mark.parametrize(
    "agent_ref",
    [
        "examples/templates/tech_news_reporter",
        "examples/templates/vulnerability_assessment",
    ],
)
def test_codex_parity_existing_templates_validate_for_stage_run(agent_ref: str) -> None:
    """Existing checked-in agents should pass the shared stage/run gate."""
    resolved = validate_agent_path(agent_ref)
    report = _run_validation_report_sync(agent_ref)

    assert resolved.is_dir()
    assert report.get("valid") is True
    assert _validation_blocks_stage_or_run(report) is False


@pytest.mark.asyncio
async def test_codex_parity_local_only_human_in_loop_run_completes() -> None:
    """A local-only client-facing worker flow should complete end to end."""
    spec = NodeSpec(
        id="policy_diff_worker",
        name="Policy Diff Worker",
        description="Compare two policy versions",
        node_type="event_loop",
        output_keys=["important_changes"],
        client_facing=True,
    )
    llm = MockStreamingLLM(
        scenarios=[
            tool_call_scenario(
                "ask_user",
                {"question": "Paste old and new policy text.", "options": ["I'll paste both now"]},
                tool_use_id="ask_1",
            ),
            tool_call_scenario(
                "set_output",
                {
                    "key": "important_changes",
                    "value": (
                        "- Remote days increased from 2 to 4\n"
                        "- Security training increased from annual to twice yearly"
                    ),
                },
                tool_use_id="set_1",
            ),
        ]
    )

    node = EventLoopNode(config=LoopConfig(max_iterations=6))
    ctx = build_ctx(spec, llm, stream_id="worker")

    async def user_responds() -> None:
        await asyncio.sleep(0.05)
        await node.inject_event("Old policy ... New policy ...")

    task = asyncio.create_task(user_responds())
    result = await node.execute(ctx)
    await task

    assert result.success is True
    assert "Remote days increased" in result.output["important_changes"]


@pytest.mark.asyncio
async def test_codex_parity_result_is_visible_before_followup_widget() -> None:
    """Long result-bearing queen prompts should stream the result before the widget."""
    spec = NodeSpec(
        id="queen",
        name="Queen",
        description="orchestrator",
        node_type="event_loop",
        client_facing=True,
        output_keys=[],
        skip_judge=True,
    )
    llm = MockStreamingLLM(
        scenarios=[
            tool_call_scenario(
                "ask_user",
                {
                    "question": (
                        "Root cause: checkout is failing because the DB pool is exhausted.\n\n"
                        "What would you like to do next?"
                    ),
                    "options": ["Rerun", "Stop"],
                },
                tool_use_id="ask_1",
            )
        ]
    )
    bus = EventBus()
    received: list[AgentEvent] = []

    async def capture(event: AgentEvent) -> None:
        received.append(event)

    bus.subscribe(
        event_types=[EventType.CLIENT_OUTPUT_DELTA, EventType.CLIENT_INPUT_REQUESTED],
        handler=capture,
    )

    node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
    ctx = build_ctx(spec, llm, stream_id="queen")

    async def shutdown() -> None:
        await asyncio.sleep(0.05)
        node.signal_shutdown()

    task = asyncio.create_task(shutdown())
    await node.execute(ctx)
    await task

    output_events = [e for e in received if e.type == EventType.CLIENT_OUTPUT_DELTA]
    input_events = [e for e in received if e.type == EventType.CLIENT_INPUT_REQUESTED]

    assert output_events
    assert input_events
    assert "DB pool is exhausted" in output_events[0].data["snapshot"]
    assert input_events[0].data["prompt"] == "What would you like to do next?"


@pytest.mark.asyncio
async def test_codex_parity_rerun_reuses_complete_recent_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Rerun should keep structured inputs stable instead of relying on text reconstruction."""
    registry = ToolRegistry()
    registry.register(
        "validate_agent_package",
        Tool(
            name="validate_agent_package",
            description="fake validator",
            parameters={"type": "object", "properties": {"agent_name": {"type": "string"}}},
        ),
        lambda _inputs: json.dumps({"valid": True, "steps": {}}),
    )

    monkeypatch.setattr(qlt, "validate_credentials", lambda *args, **kwargs: None)
    monkeypatch.chdir(tmp_path)

    sessions_dir = tmp_path / "agent_store" / "sessions"
    sessions_dir.mkdir(parents=True)

    valid_prior_state = {
        "timestamps": {"updated_at": "2026-03-24T20:44:00"},
        "input_data": {
            "target_dir": "docs",
            "review_dir": "docs_reviews",
            "word_threshold": 800,
        },
    }
    malformed_recent_state = {
        "timestamps": {"updated_at": "2026-03-24T21:20:23"},
        "input_data": {
            "review_dir": "docs_reviews",
            "word_threshold": "800. Validate inputs and continue.",
        },
    }

    for session_name, state in {
        "session_20260324_204400_good": valid_prior_state,
        "session_20260324_212023_bad": malformed_recent_state,
    }.items():
        session_dir = sessions_dir / session_name
        session_dir.mkdir()
        (session_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    runtime = SimpleNamespace(
        _session_store=SimpleNamespace(sessions_dir=sessions_dir),
        resume_timers=MagicMock(),
        trigger=AsyncMock(return_value="exec-rerun"),
        graph=SimpleNamespace(
            nodes=[],
            entry_node="process",
            get_node=lambda node_id: SimpleNamespace(
                input_keys=["target_dir", "review_dir", "word_threshold"]
            )
            if node_id == "process"
            else None,
        ),
        get_entry_points=lambda: [SimpleNamespace(id="default", entry_node="process")],
    )
    session = SimpleNamespace(
        worker_runtime=runtime,
        event_bus=None,
        worker_path=Path("exports/local_markdown_review_probe_2"),
        runner=None,
    )
    register_queen_lifecycle_tools(
        registry,
        session=session,
        session_id="sess-rerun",
        phase_state=QueenPhaseState(phase="staging"),
    )

    result_raw = await registry._tools["rerun_worker_with_last_input"].executor({})
    result = json.loads(result_raw)

    assert result["status"] == "started"
    runtime.trigger.assert_awaited_once()
    assert runtime.trigger.await_args.kwargs["input_data"] == {
        "target_dir": str((tmp_path / "docs").resolve()),
        "review_dir": str((tmp_path / "docs_reviews").resolve()),
        "word_threshold": 800,
    }
    assert runtime.trigger.await_args.kwargs["session_state"] is None


@dataclass
class _MockEntryPoint:
    id: str = "default"
    name: str = "Default"
    entry_node: str = "start"
    trigger_type: str = "manual"
    trigger_config: dict = field(default_factory=dict)


@dataclass
class _MockStream:
    is_awaiting_input: bool = False
    _execution_tasks: dict = field(default_factory=dict)
    _active_executors: dict = field(default_factory=dict)
    active_execution_ids: set = field(default_factory=set)

    async def cancel_execution(self, execution_id: str) -> bool:
        return execution_id in self._execution_tasks


@dataclass
class _MockGraphRegistration:
    graph: Any = field(default_factory=lambda: SimpleNamespace(nodes=[], edges=[], entry_node=""))
    streams: dict = field(default_factory=dict)
    entry_points: dict = field(default_factory=dict)


class _MockRuntime:
    def __init__(self):
        self._entry_points = [_MockEntryPoint()]
        self._mock_streams = {"default": _MockStream()}
        self._registration = _MockGraphRegistration(
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


def _make_queen_executor():
    mock_node = MagicMock()
    mock_node.inject_event = AsyncMock()
    executor = MagicMock()
    executor.node_registry = {"queen": mock_node}
    return executor


def _make_session(agent_id="test_agent") -> Session:
    runner = MagicMock()
    runner.intro_message = "Test intro"
    return Session(
        id=agent_id,
        event_bus=EventBus(),
        llm=MagicMock(),
        loaded_at=1000000.0,
        queen_executor=_make_queen_executor(),
        worker_id=agent_id,
        worker_path=Path("/tmp/test_agent"),
        runner=runner,
        worker_runtime=_MockRuntime(),
        worker_info=SimpleNamespace(
            name="test_agent",
            description="A test agent",
            goal_name="test_goal",
            node_count=2,
        ),
        worker_validation_report={"valid": True, "steps": {}},
        worker_validation_failures=[],
    )


def _make_app_with_session(session: Session):
    app = create_app()
    mgr = app["manager"]
    mgr._sessions[session.id] = session
    return app


@pytest.mark.asyncio
async def test_codex_parity_done_for_now_parks_queen_without_new_followup() -> None:
    """Terminal stop choices should acknowledge once and park the queen."""
    session = _make_session()
    session.event_bus.get_history = MagicMock(
        return_value=[
        AgentEvent(
            type=EventType.CLIENT_INPUT_REQUESTED,
            stream_id="queen",
            node_id="queen",
            execution_id=session.id,
            data={"options": ["Run again with same input", "Done for now"]},
        )
        ]
    )
    session.event_bus.emit_client_output_delta = AsyncMock()
    app = _make_app_with_session(session)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            "/api/sessions/test_agent/chat",
            json={"message": "No, stop here"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "queen"
        assert data["delivered"] is True

    assert session.queen_executor is None
    session.event_bus.emit_client_output_delta.assert_awaited_once()
