"""Regression test for the mid-turn dynamic tool refresh.

Root cause (two stuck queen sessions, chart_render): ``search_tools`` loads a
searchable tool into the queen's phase state mid-conversation, but the ONLY
site that pulled ``dynamic_tools_provider()`` into the live ``tools`` list was
step 6b2 in ``AgentLoop.execute`` — in the OUTER ``for iteration`` loop. The
model streaming happens inside ``_run_turn_loop``'s inner ``while True:`` loop,
which re-streams after every tool batch using a FROZEN ``tools`` list and never
re-pulled the provider. Because the model kept emitting tool calls (trying to
use the tool it could not see), the inner loop never returned, so the outer
loop never cycled back to 6b2, so the freshly-loaded tool never entered the
request's tool schema — a deadlock. The model looped forever on terminal_exec.

The fix re-pulls ``dynamic_tools_provider()`` at the top of the inner loop via
``AgentLoop._refresh_dynamic_tools``. These tests assert a tool loaded by a
``search_tools`` call reaches the model on its very next inner stream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from framework.agent_loop.agent_loop import AgentLoop, LoopConfig
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent
from framework.orchestrator.node import DataBuffer, NodeContext, NodeSpec
from framework.tools.queen_lifecycle_tools import QueenPhaseState
from framework.tracker.decision_tracker import DecisionTracker

SESSION_ID = "s_midturn"


class _ToolsCapturingLLM(LLMProvider):
    """Yields one scripted scenario per stream() call and records the tool
    names it was handed on each call so the test can assert what the model
    actually saw."""

    model = "mock"

    def __init__(self, scenarios: list[list]) -> None:
        self.scenarios = scenarios
        self._i = 0
        self.tools_seen: list[list[str]] = []

    async def stream(self, messages, system="", tools=None, max_tokens=4096, **kw) -> AsyncIterator:
        self.tools_seen.append([t.name for t in (tools or [])])
        events = self.scenarios[min(self._i, len(self.scenarios) - 1)]
        self._i += 1
        for ev in events:
            yield ev

    def complete(self, messages, system="", **kw) -> LLMResponse:
        return LLMResponse(content="summary", model="mock", stop_reason="stop")


def _tool_turn(name: str, args: dict, tool_use_id: str) -> list:
    return [
        ToolCallEvent(tool_use_id=tool_use_id, tool_name=name, tool_input=args),
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _text_turn(text: str) -> list:
    return [
        TextDeltaEvent(content=text, snapshot=text),
        FinishEvent(stop_reason="stop", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _phase_state() -> QueenPhaseState:
    """Queen phase state where terminal_exec + search_tools are eager and
    chart_render is searchable-but-not-loaded (an MCP tool gated by the split)."""
    ps = QueenPhaseState(phase="independent")
    ps.independent_tools = [
        Tool(name="search_tools", description="load tools", parameters={"type": "object"}),
        Tool(name="terminal_exec", description="run shell", parameters={"type": "object"}),
        Tool(name="chart_render", description="render a chart to PNG", parameters={"type": "object"}),
    ]
    # Only chart_render is "MCP" → subject to the eager/searchable split.
    ps.mcp_tool_names_all = {"chart_render"}
    # Non-empty always_enabled enables the split; the two always-on tools are eager.
    ps.always_enabled_names = {"search_tools", "terminal_exec"}
    ps.enabled_mcp_tools = None  # allow-all
    ps.rebuild_independent_filter()
    return ps


def _build_ctx(llm: LLMProvider, phase_state: QueenPhaseState) -> NodeContext:
    rt = MagicMock(spec=DecisionTracker)
    rt.start_run = MagicMock(return_value="session_20260101_000000_midturn01")
    rt.decide = MagicMock(return_value="dec_1")
    for m in ("record_outcome", "end_run", "report_problem", "set_node"):
        setattr(rt, m, MagicMock())
    spec = NodeSpec(
        id="midturn_agent",
        name="Mid-turn Agent",
        description="dynamic tool refresh",
        node_type="event_loop",
        output_keys=[],
        system_prompt="You are a test assistant.",
    )
    ctx = NodeContext(
        runtime=rt,
        node_id=spec.id,
        node_spec=spec,
        buffer=DataBuffer(),
        input_data={"task": "chart the data"},
        llm=llm,
        available_tools=list(phase_state.get_current_tools()),
        stream_id="judge",  # bypass worker auto-escalation + reminder noise
    )
    ctx.session_id = SESSION_ID
    # The queen wiring: dynamic_tools_provider == phase_state.get_current_tools.
    ctx.dynamic_tools_provider = phase_state.get_current_tools
    return ctx


@pytest.fixture
def _hive_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HIVE_HOME", str(tmp_path))
    import framework.tasks.store as store_mod

    monkeypatch.setattr(store_mod, "_default_store", None)
    yield tmp_path


@pytest.mark.asyncio
async def test_search_tools_load_reaches_model_same_turn_loop(_hive_home) -> None:
    """A search_tools load mid-_run_turn_loop must put chart_render into the
    tool schema of the NEXT inner stream — without the outer loop cycling."""
    ps = _phase_state()

    def tool_exec(tu: ToolUse) -> ToolResult:
        if tu.name == "search_tools":
            # Simulate the real search_tools closure: promote chart_render into
            # the eager set (mutates phase_state, NOT the loop's live tools list).
            loaded = ps.promote_searched_tools(["chart_render"])
            return ToolResult(tool_use_id=tu.id, content=f"loaded {loaded}", is_error=False)
        return ToolResult(tool_use_id=tu.id, content="ok", is_error=False)

    # All three model streams are inner turns of ONE _run_turn_loop: the model
    # never yields a tool-free response until the end. Stream 2 (terminal_exec)
    # is the proof point — it occurs AFTER the search_tools load.
    llm = _ToolsCapturingLLM(
        scenarios=[
            _tool_turn("search_tools", {"query": "select:chart_render"}, "c1"),
            _tool_turn("terminal_exec", {"command": "echo prep"}, "c2"),
            _text_turn("done"),
        ]
    )
    ctx = _build_ctx(llm, ps)

    result = await AgentLoop(tool_executor=tool_exec, config=LoopConfig(max_iterations=3)).execute(ctx)
    assert result.success is True

    # At least 2 streams happened in the inner loop.
    assert len(llm.tools_seen) >= 2, llm.tools_seen
    # Stream 1: chart_render is searchable, NOT yet loaded → absent (correct).
    assert "chart_render" not in llm.tools_seen[0], llm.tools_seen[0]
    # Stream 2 (the fix): the mid-turn load reached the model on its next step.
    # Pre-fix this list lacked chart_render and the model could never call it.
    assert "chart_render" in llm.tools_seen[1], llm.tools_seen[1]
    # Eager tools remain present throughout.
    assert "terminal_exec" in llm.tools_seen[1]


def test_refresh_dynamic_tools_in_place_and_guarded() -> None:
    """Unit-level: _refresh_dynamic_tools mutates the list object in place
    (the inner-stream closure holds it by reference), preserves synthetic
    tools, and is a no-op when no provider is wired."""
    loop = AgentLoop()

    # No provider → list untouched (non-queen nodes keep their static tools).
    tools = [Tool(name="a", description="", parameters={})]
    ctx_none = MagicMock()
    ctx_none.dynamic_tools_provider = None
    loop._refresh_dynamic_tools(ctx_none, tools)
    assert [t.name for t in tools] == ["a"]

    # Provider that grows (simulating a search_tools load) → tools updated in
    # place, same object identity, synthetic (ask_user) preserved.
    ps = _phase_state()
    tools = [Tool(name="ask_user", description="synthetic", parameters={})] + list(ps.get_current_tools())
    original_id = id(tools)
    ctx = MagicMock()
    ctx.dynamic_tools_provider = ps.get_current_tools

    loop._refresh_dynamic_tools(ctx, tools)
    assert id(tools) == original_id, "must mutate in place, not rebind"
    assert "ask_user" in [t.name for t in tools], "synthetic tool dropped"
    assert "chart_render" not in [t.name for t in tools], "not loaded yet"

    ps.promote_searched_tools(["chart_render"])
    loop._refresh_dynamic_tools(ctx, tools)
    assert "chart_render" in [t.name for t in tools], "load not reflected after refresh"
    assert "ask_user" in [t.name for t in tools], "synthetic tool dropped after refresh"
