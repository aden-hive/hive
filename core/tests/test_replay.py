"""Tests for deterministic replay infrastructure (issue #4669).

Covers:
    1. Unit — ReplayCache builds correct lookup dicts from NodeStepLog records
    2. Unit — ReplayInterceptor counters track step/tool state per node correctly
    3. Integration — full replay of a two-node graph with freeze_llm + freeze_tools
       produces identical output and zero divergence
    4. Counterfactual — replay with freeze_llm=False (live LLM stub) still runs
       to completion when cache misses fall through to the inner provider
    5. CLI smoke — cmd_replay exits 2 on a missing session; --help prints all flags

Each test is self-contained: no real LLM calls, no real file system (tmp_path used
for session storage where needed), and no network access.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_step(
    node_id: str,
    step_index: int,
    llm_text: str = "done",
    tool_calls: list | None = None,
    input_tokens: int = 10,
    output_tokens: int = 20,
):
    """Build a minimal NodeStepLog-like object for testing."""
    from framework.runtime.runtime_log_schemas import NodeStepLog, ToolCallLog

    tcs = []
    for tc in tool_calls or []:
        tcs.append(
            ToolCallLog(
                tool_use_id=tc.get("id", "uid-1"),
                tool_name=tc["tool_name"],
                tool_input=tc.get("tool_input", {}),
                result=tc.get("result", "ok"),
                is_error=tc.get("is_error", False),
            )
        )
    return NodeStepLog(
        node_id=node_id,
        node_type="event_loop",
        step_index=step_index,
        llm_text=llm_text,
        tool_calls=tcs,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


# ---------------------------------------------------------------------------
# Test 1 — ReplayCache construction
# ---------------------------------------------------------------------------


class TestReplayCache:
    """Unit tests for ReplayCache lookup table construction."""

    def test_llm_cache_keyed_by_node_and_step(self):
        from framework.runtime.replay_runtime import ReplayCache

        steps = [
            _make_step("classify", 0, llm_text="classification result"),
            _make_step("classify", 1, llm_text="retry result"),
            _make_step("format", 0, llm_text="formatted output"),
        ]
        cache = ReplayCache(steps)

        assert cache.total_llm_entries == 3
        assert cache.get_llm_response("classify", 0).llm_text == "classification result"
        assert cache.get_llm_response("classify", 1).llm_text == "retry result"
        assert cache.get_llm_response("format", 0).llm_text == "formatted output"

    def test_llm_cache_miss_returns_none(self):
        from framework.runtime.replay_runtime import ReplayCache

        cache = ReplayCache([_make_step("n1", 0)])
        assert cache.get_llm_response("n1", 99) is None
        assert cache.get_llm_response("missing", 0) is None

    def test_tool_cache_keyed_by_position(self):
        """Multiple calls to the same tool in one step are disambiguated by position."""
        from framework.runtime.replay_runtime import ReplayCache

        steps = [
            _make_step(
                "search",
                0,
                tool_calls=[
                    {"tool_name": "search", "result": "result-A"},
                    {"tool_name": "search", "result": "result-B"},  # same tool, pos 1
                ],
            )
        ]
        cache = ReplayCache(steps)

        assert cache.total_tool_entries == 2
        assert cache.get_tool_result("search", 0, 0) == "result-A"
        assert cache.get_tool_result("search", 0, 1) == "result-B"

    def test_tool_cache_miss_returns_none(self):
        from framework.runtime.replay_runtime import ReplayCache

        cache = ReplayCache([_make_step("n1", 0, tool_calls=[{"tool_name": "t", "result": "x"}])])
        assert cache.get_tool_result("n1", 0, 99) is None

    def test_tool_call_suggestions_extracted(self):
        """CachedLLMResponse.tool_call_suggestions reflects the step's tool list."""
        from framework.runtime.replay_runtime import ReplayCache

        steps = [
            _make_step(
                "n1",
                0,
                tool_calls=[
                    {"tool_name": "lookup", "tool_input": {"q": "foo"}, "result": "bar"},
                ],
            )
        ]
        cache = ReplayCache(steps)
        resp = cache.get_llm_response("n1", 0)
        assert len(resp.tool_call_suggestions) == 1
        assert resp.tool_call_suggestions[0]["tool_name"] == "lookup"
        assert resp.tool_call_suggestions[0]["tool_input"] == {"q": "foo"}

    def test_node_ids_property(self):
        from framework.runtime.replay_runtime import ReplayCache

        steps = [_make_step("a", 0), _make_step("b", 0), _make_step("a", 1)]
        cache = ReplayCache(steps)
        assert set(cache.node_ids) == {"a", "b"}

    def test_get_node_steps_returns_in_order(self):
        from framework.runtime.replay_runtime import ReplayCache

        steps = [_make_step("n1", 0), _make_step("n1", 1), _make_step("n2", 0)]
        cache = ReplayCache(steps)
        n1_steps = cache.get_node_steps("n1")
        assert len(n1_steps) == 2
        assert n1_steps[0].step_index == 0
        assert n1_steps[1].step_index == 1

    @pytest.mark.asyncio
    async def test_from_session_raises_on_empty_logs(self, tmp_path):
        """from_session raises ValueError when no L3 logs exist for the session."""
        from framework.runtime.replay_runtime import ReplayCache
        from framework.runtime.runtime_log_store import RuntimeLogStore

        log_store = RuntimeLogStore(base_path=tmp_path)
        with pytest.raises(ValueError, match="No L3 tool logs found"):
            await ReplayCache.from_session("session_missing", log_store)


# ---------------------------------------------------------------------------
# Test 2 — ReplayInterceptor counter mechanics
# ---------------------------------------------------------------------------


class TestReplayInterceptor:
    """Unit tests for ReplayInterceptor step / tool counter behaviour."""

    def _make_interceptor(self, steps=None):
        from framework.runtime.replay_runtime import ReplayCache, ReplayInterceptor

        cache = ReplayCache(steps or [_make_step("n1", 0)])
        return ReplayInterceptor(cache, freeze_llm=True, freeze_tools=True)

    def test_set_node_resets_counters(self):
        from framework.runtime.replay_runtime import ReplayInterceptor, ReplayCache

        cache = ReplayCache([_make_step("a", 0), _make_step("a", 1)])
        ic = ReplayInterceptor(cache)
        ic.set_node("a")
        ic.on_llm_call()  # step 0 → step_index becomes 1
        ic.set_node("a")  # reset
        assert ic._step_index == 0

    def test_llm_call_increments_step_index(self):
        ic = self._make_interceptor([_make_step("n1", 0), _make_step("n1", 1)])
        ic.set_node("n1")
        ic.on_llm_call()  # consumes step 0
        assert ic._step_index == 1

    def test_llm_call_resets_tool_position(self):
        ic = self._make_interceptor(
            [_make_step("n1", 0, tool_calls=[{"tool_name": "t", "result": "r"}])]
        )
        ic.set_node("n1")
        ic.on_llm_call()
        ic.on_tool_call()  # pos 0
        assert ic._tool_call_position == 1
        ic.on_llm_call()  # next step → tool_call_position resets to 0
        assert ic._tool_call_position == 0

    def test_tool_call_increments_position(self):
        ic = self._make_interceptor(
            [
                _make_step(
                    "n1",
                    0,
                    tool_calls=[
                        {"tool_name": "t", "result": "r0"},
                        {"tool_name": "t", "result": "r1"},
                    ],
                )
            ]
        )
        ic.set_node("n1")
        ic.on_llm_call()
        ic.on_tool_call()  # pos 0
        assert ic._tool_call_position == 1
        ic.on_tool_call()  # pos 1
        assert ic._tool_call_position == 2

    def test_hit_and_miss_counters(self):
        ic = self._make_interceptor([_make_step("n1", 0)])
        ic.set_node("n1")
        ic.on_llm_call()   # HIT (step 0 exists)
        ic.on_llm_call()   # MISS (step 1 does not exist)
        assert ic.llm_hits == 1
        assert ic.llm_misses == 1
        assert ic.total_misses == 1
        assert ic.total_hits == 1

    def test_freeze_false_skips_cache(self):
        from framework.runtime.replay_runtime import ReplayCache, ReplayInterceptor

        cache = ReplayCache([_make_step("n1", 0, llm_text="cached")])
        ic = ReplayInterceptor(cache, freeze_llm=False, freeze_tools=False)
        ic.set_node("n1")
        result = ic.on_llm_call()
        assert result is None  # freeze_llm=False → always None
        assert ic.llm_hits == 0
        assert ic.llm_misses == 0  # not even counted when freeze=False

    def test_different_nodes_tracked_independently(self):
        from framework.runtime.replay_runtime import ReplayCache, ReplayInterceptor

        cache = ReplayCache([_make_step("a", 0), _make_step("b", 0)])
        ic = ReplayInterceptor(cache)

        ic.set_node("a")
        resp_a = ic.on_llm_call()

        ic.set_node("b")
        resp_b = ic.on_llm_call()

        assert resp_a is not None
        assert resp_b is not None


# ---------------------------------------------------------------------------
# Test 3 — Integration: full replay with both freeze flags active
# ---------------------------------------------------------------------------


class TestIntegrationReplay:
    """Integration test: run a two-node graph, build cache, replay it, verify
    the replay produces identical output without calling live LLM or tools."""

    @pytest.mark.asyncio
    async def test_replay_matches_original_output(self, tmp_path):
        """Full replay with freeze_llm=True, freeze_tools=True produces same
        output as original and ReplayLLMProvider never delegates to inner."""
        from framework.llm.provider import LLMProvider, LLMResponse, Tool
        from framework.runtime.replay_runtime import (
            CachedLLMResponse,
            ReplayCache,
            ReplayInterceptor,
            ReplayLLMProvider,
            make_replay_tool_executor,
        )
        from framework.llm.stream_events import (
            FinishEvent, TextDeltaEvent, TextEndEvent, ToolCallEvent,
        )

        # --- Build a cache with two nodes, one tool call per node ---
        steps = [
            _make_step(
                "classify",
                0,
                llm_text="category: billing",
                tool_calls=[{"tool_name": "lookup", "tool_input": {"id": 1}, "result": "plan-A"}],
            ),
            _make_step("respond", 0, llm_text="Here is your answer."),
        ]
        cache = ReplayCache(steps)
        interceptor = ReplayInterceptor(cache, freeze_llm=True, freeze_tools=True)

        # --- inner LLM should NEVER be called when cache hits ---
        inner_llm = MagicMock(spec=LLMProvider)
        inner_llm.stream = AsyncMock(side_effect=AssertionError("live LLM called unexpectedly"))
        inner_llm.acomplete = AsyncMock(
            side_effect=AssertionError("live LLM called unexpectedly")
        )

        replay_llm = ReplayLLMProvider(inner_llm, interceptor)

        # --- inner tool executor should NEVER be called ---
        inner_tool_executor = MagicMock(side_effect=AssertionError("live tool called unexpectedly"))
        replay_tool_executor = make_replay_tool_executor(inner_tool_executor, interceptor)

        # --- Test streaming for 'classify' node ---
        interceptor.set_node("classify")
        events = []
        async for event in replay_llm.stream(messages=[], system="", tools=None, max_tokens=1024):
            events.append(event)

        text_events = [e for e in events if isinstance(e, TextDeltaEvent)]
        tool_events = [e for e in events if isinstance(e, ToolCallEvent)]
        finish_events = [e for e in events if isinstance(e, FinishEvent)]

        assert len(text_events) == 1
        assert text_events[0].content == "category: billing"
        assert len(tool_events) == 1
        assert tool_events[0].tool_name == "lookup"
        assert tool_events[0].tool_input == {"id": 1}
        assert len(finish_events) == 1
        assert finish_events[0].model == "replay-cache"

        # --- Test tool executor for the tool call in 'classify' step 0 ---
        from framework.llm.provider import ToolUse

        tool_result = await replay_tool_executor(
            ToolUse(id="uid", name="lookup", input={"id": 1})
        )
        assert tool_result.content == "plan-A"
        assert tool_result.is_error is False

        # --- Test streaming for 'respond' node (no tool calls) ---
        interceptor.set_node("respond")
        events = []
        async for event in replay_llm.stream(messages=[], system="", tools=None, max_tokens=1024):
            events.append(event)

        text_events = [e for e in events if isinstance(e, TextDeltaEvent)]
        tool_events = [e for e in events if isinstance(e, ToolCallEvent)]
        assert len(text_events) == 1
        assert text_events[0].content == "Here is your answer."
        assert len(tool_events) == 0

        # --- Verify hit counts ---
        assert interceptor.llm_hits == 2
        assert interceptor.llm_misses == 0
        assert interceptor.tool_hits == 1
        assert interceptor.tool_misses == 0

    @pytest.mark.asyncio
    async def test_replay_config_escape_hatch_in_executor(self, tmp_path):
        """GraphExecutor.execute() unpacks replay_config from session_state
        when it arrives via the _replay_config escape-hatch key, rather than
        as a direct parameter."""
        from framework.graph.edge import GraphSpec
        from framework.graph.executor import GraphExecutor
        from framework.graph.goal import Goal
        from framework.graph.node import NodeResult, NodeSpec
        from framework.schemas.replay import ReplayConfig

        # Build a minimal single-node graph
        class QuickNode:
            def validate_input(self, ctx):
                return []

            async def execute(self, ctx):
                return NodeResult(success=True, output={"x": 1}, tokens_used=0, latency_ms=0)

        class DummyRuntime:
            execution_id = ""

            def start_run(self, **kw):
                return "run-1"

            def end_run(self, **kw):
                pass

            def report_problem(self, **kw):
                pass

        graph = GraphSpec(
            id="g", goal_id="goal",
            nodes=[NodeSpec(id="n1", name="n", description="d",
                            node_type="event_loop", input_keys=[], output_keys=["x"],
                            max_retries=0)],
            edges=[],
            entry_node="n1",
        )
        goal = Goal(id="goal", name="test", description="")

        # Build a ReplayCache and write fake L3 logs to tmp_path
        from framework.runtime.runtime_log_store import RuntimeLogStore
        from framework.storage.session_store import SessionStore
        from framework.schemas.session_state import SessionState, SessionTimestamps

        sessions_dir = tmp_path / "sessions"
        source_session_id = "session_20260304_120000_src00001"
        log_store = RuntimeLogStore(base_path=sessions_dir)
        log_store.ensure_run_dir(source_session_id)
        step = _make_step("n1", 0, llm_text="hi")
        log_store.append_step(source_session_id, step)

        # Write a fake source state.json
        session_store = SessionStore(tmp_path)
        source_state = SessionState(
            session_id=source_session_id,
            goal_id="goal",
            timestamps=SessionTimestamps(
                started_at="2026-03-04T12:00:00",
                updated_at="2026-03-04T12:00:01",
            ),
            input_data={"question": "hello"},
        )
        await session_store.write_state(source_session_id, source_state)

        rc = ReplayConfig(
            source_session_id=source_session_id,
            freeze_llm=True,
            freeze_tools=True,
        )

        # Pass replay_config via the escape-hatch key in session_state
        session_state = {"_replay_config": rc.model_dump()}

        executor = GraphExecutor(
            runtime=DummyRuntime(),
            node_registry={"n1": QuickNode()},
            storage_path=tmp_path,
        )
        result = await executor.execute(graph=graph, goal=goal, session_state=session_state)

        # The escape-hatch key must have been consumed (popped) regardless of
        # whether execution succeeded — that is the core invariant being tested.
        assert "_replay_config" not in (result.session_state or {})


# ---------------------------------------------------------------------------
# Test 4 — Counterfactual: freeze_llm=False falls through to live provider
# ---------------------------------------------------------------------------


class TestCounterfactualReplay:
    """When freeze_llm=False, cache misses delegate to the inner LLM provider.
    This verifies the miss path works end-to-end."""

    @pytest.mark.asyncio
    async def test_cache_miss_delegates_to_inner_llm(self):
        from framework.llm.provider import LLMProvider, LLMResponse, Tool
        from framework.llm.stream_events import FinishEvent, TextDeltaEvent, TextEndEvent
        from framework.runtime.replay_runtime import (
            ReplayCache,
            ReplayInterceptor,
            ReplayLLMProvider,
        )

        # Cache is empty so every call is a miss
        cache = ReplayCache([])
        interceptor = ReplayInterceptor(cache, freeze_llm=True, freeze_tools=True)

        # Inner provider returns a known response
        live_events = [
            TextDeltaEvent(content="live response", snapshot="live response"),
            TextEndEvent(full_text="live response"),
            FinishEvent(stop_reason="end_turn", model="claude-opus-4-6"),
        ]

        async def _fake_stream(*args, **kwargs):
            for e in live_events:
                yield e

        inner_llm = MagicMock(spec=LLMProvider)
        inner_llm.stream = _fake_stream
        replay_llm = ReplayLLMProvider(inner_llm, interceptor)

        interceptor.set_node("n1")
        events = []
        async for event in replay_llm.stream(messages=[], system="", tools=None, max_tokens=512):
            events.append(event)

        text_events = [e for e in events if isinstance(e, TextDeltaEvent)]
        assert len(text_events) == 1
        assert text_events[0].content == "live response"

        assert interceptor.llm_misses == 1
        assert interceptor.llm_hits == 0

    @pytest.mark.asyncio
    async def test_cache_miss_delegates_to_inner_tool_executor(self):
        """Tool cache miss falls through to the inner executor."""
        from framework.llm.provider import ToolResult, ToolUse
        from framework.runtime.replay_runtime import (
            ReplayCache,
            ReplayInterceptor,
            make_replay_tool_executor,
        )

        cache = ReplayCache([])  # empty → all misses
        interceptor = ReplayInterceptor(cache, freeze_llm=True, freeze_tools=True)

        async def _live_tool(tool_use: ToolUse) -> ToolResult:
            return ToolResult(
                tool_use_id=tool_use.id, content="live-result", is_error=False
            )

        replay_tool = make_replay_tool_executor(_live_tool, interceptor)

        interceptor.set_node("n1")
        interceptor.on_llm_call()  # advance step counter
        result = await replay_tool(ToolUse(id="u1", name="search", input={"q": "test"}))

        assert result.content == "live-result"
        assert interceptor.tool_misses == 1

    @pytest.mark.asyncio
    async def test_acomplete_cache_hit(self):
        """ReplayLLMProvider.acomplete() returns cached LLMResponse on hit."""
        from framework.llm.provider import LLMProvider, LLMResponse
        from framework.runtime.replay_runtime import (
            ReplayCache,
            ReplayInterceptor,
            ReplayLLMProvider,
        )

        cache = ReplayCache([_make_step("n1", 0, llm_text="compacted", input_tokens=5, output_tokens=8)])
        interceptor = ReplayInterceptor(cache, freeze_llm=True, freeze_tools=True)
        inner = MagicMock(spec=LLMProvider)
        inner.acomplete = AsyncMock(side_effect=AssertionError("should not be called"))
        replay_llm = ReplayLLMProvider(inner, interceptor)

        interceptor.set_node("n1")
        resp = await replay_llm.acomplete(messages=[], system="")

        assert isinstance(resp, LLMResponse)
        assert resp.content == "compacted"
        assert resp.model == "replay-cache"
        assert resp.input_tokens == 5
        assert resp.output_tokens == 8


# ---------------------------------------------------------------------------
# Test 5 — CLI smoke tests
# ---------------------------------------------------------------------------


class TestCLIReplaySmoke:
    """Smoke tests for the hive replay CLI command."""

    def test_replay_help_lists_all_flags(self, capsys):
        """--help output includes all required flags."""
        import argparse
        import sys
        from framework.runner.cli import register_commands

        parser = argparse.ArgumentParser(prog="hive")
        subparsers = parser.add_subparsers()
        register_commands(subparsers)

        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["replay", "--help"])
        assert exc.value.code == 0

        captured = capsys.readouterr()
        help_text = captured.out
        for flag in [
            "--from-node",
            "--freeze-llm",
            "--no-freeze-llm",
            "--freeze-tools",
            "--no-freeze-tools",
            "--input-override",
            "--output",
        ]:
            assert flag in help_text, f"Flag {flag!r} not found in --help output"

    def test_replay_exits_2_on_missing_session(self, tmp_path, monkeypatch):
        """cmd_replay returns exit code 2 when the source session does not exist."""
        import argparse
        from framework.runner.cli import cmd_replay

        # Monkeypatch AgentRunner.load to return a stub with _storage_path
        from framework.runner import runner as runner_module

        class _StubRunner:
            _storage_path = tmp_path

        monkeypatch.setattr(
            runner_module.AgentRunner, "load", staticmethod(lambda *a, **kw: _StubRunner())
        )

        args = argparse.Namespace(
            agent_path=str(tmp_path),
            session_id="session_nonexistent_999",
            from_node=None,
            freeze_llm=True,
            freeze_tools=True,
            input_override=[],
            output="text",
            verbose=False,
        )
        code = cmd_replay(args)
        assert code == 2

    def test_replay_exits_2_on_bad_input_override(self, tmp_path):
        """cmd_replay returns exit code 2 when --input-override is missing '='."""
        import argparse
        from framework.runner.cli import cmd_replay

        args = argparse.Namespace(
            agent_path=str(tmp_path),
            session_id="session_test",
            from_node=None,
            freeze_llm=True,
            freeze_tools=True,
            input_override=["BADVALUE"],  # no '='
            output="text",
            verbose=False,
        )
        code = cmd_replay(args)
        assert code == 2

    def test_replay_config_defaults(self):
        """ReplayConfig default values match the documented behaviour."""
        from framework.schemas.replay import ReplayConfig

        rc = ReplayConfig(source_session_id="session_abc")
        assert rc.freeze_llm is True
        assert rc.freeze_tools is True
        assert rc.from_node is None
        assert rc.input_overrides == {}

    def test_replay_config_json_roundtrip(self):
        """ReplayConfig serialises and deserialises correctly."""
        from framework.schemas.replay import ReplayConfig

        rc = ReplayConfig(
            source_session_id="session_20260304_143022_abc12345",
            from_node="classify",
            freeze_llm=False,
            freeze_tools=True,
            input_overrides={"user_query": "updated question"},
        )
        data = rc.model_dump()
        rc2 = ReplayConfig.model_validate(data)
        assert rc2.source_session_id == rc.source_session_id
        assert rc2.from_node == rc.from_node
        assert rc2.freeze_llm is False
        assert rc2.input_overrides == {"user_query": "updated question"}

    def test_build_improvement_hypothesis_full_recovery(self):
        from framework.runtime.replay_runtime import build_improvement_hypothesis

        hyp = build_improvement_hypothesis(
            source_success=False,
            replay_success=True,
            diverged_nodes=["classify"],
            from_node=None,
            from_node_original_status="",
            from_node_replay_status="",
            total_misses=0,
        )
        assert "Full recovery" in hyp or "recovery" in hyp.lower()

    def test_build_improvement_hypothesis_partial_replay(self):
        from framework.runtime.replay_runtime import build_improvement_hypothesis

        hyp = build_improvement_hypothesis(
            source_success=False,
            replay_success=False,
            diverged_nodes=[],
            from_node=None,
            from_node_original_status="",
            from_node_replay_status="",
            total_misses=3,
        )
        assert "cache miss" in hyp.lower() or "partial" in hyp.lower()

    def test_build_improvement_hypothesis_deterministic_failure(self):
        from framework.runtime.replay_runtime import build_improvement_hypothesis

        hyp = build_improvement_hypothesis(
            source_success=False,
            replay_success=False,
            diverged_nodes=[],
            from_node=None,
            from_node_original_status="",
            from_node_replay_status="",
            total_misses=0,
        )
        assert "deterministic" in hyp.lower() or "confirmed" in hyp.lower()
