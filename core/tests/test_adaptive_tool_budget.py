"""Tests for the colony-adaptive worker operating budget.

Within a colony, successful workers define the norm: the colony's
nominal ``tool_call_lifetime_budget`` shrinks toward what successful
workers actually consume (2x median with a 1.25x max-guard, floored,
capped at the profile base), so likely-failing workers are wound down
early via the loop's existing budget-grace machinery instead of
burning the full fixed ceiling.

Three layers:
- ``AgentLoop.apply_lifetime_budget_cap`` — the shrink-only setter.
- ``ColonyRuntime._maybe_adapt_colony_budget`` — the sampler/policy
  (driven directly with synthetic SUBAGENT_REPORT payloads).
- End-to-end through the scheduler with the mock report LLM: samples
  accumulate, the nominal shrinks, in-flight workers get clamped, and
  the report payload carries the new telemetry fields.

NOTE: never assert exact tool-call counts at the clamp edge — the
dispatch loop captures the budget per tool batch, so a clamp landing
mid-batch legally takes effect one batch late.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import framework.host.colony_runtime as colony_runtime_mod
from framework.agent_loop.agent_loop import AgentLoop, LoopConfig
from framework.agent_loop.types import AgentSpec
from framework.agents.queen.worker_definition import DEFAULT_LOOP_CONFIG
from framework.host.colony_runtime import ColonyConfig, ColonyRuntime
from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.host.worker import WorkerStatus
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent
from framework.schemas.goal import Goal

# Hermetic policy constants: the module reads HIVE_ADAPTIVE_BUDGET_* env
# at import time, so pin the values the assertions below assume.
_FLOOR = 30
_MIN_SAMPLES = 3
# The profile ceiling the adaptation clamps toward. Sourced from the single
# source of truth so a norm bump (e.g. 150 -> 200) does not silently rot
# the cap-at-base assertions below.
_BASE = DEFAULT_LOOP_CONFIG["tool_call_lifetime_budget"]


@pytest.fixture(autouse=True)
def _fixed_budget_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(colony_runtime_mod, "_ADAPTIVE_BUDGET_FLOOR", _FLOOR)
    monkeypatch.setattr(colony_runtime_mod, "_ADAPTIVE_BUDGET_MIN_SAMPLES", _MIN_SAMPLES)


# ---------------------------------------------------------------------------
# Harness (mirrors test_colony_scheduler.py)
# ---------------------------------------------------------------------------


class _ControlledReportLLM(LLMProvider):
    """LLM that fires report_to_parent for any task whose key matches."""

    model: str = "mock"

    def __init__(
        self,
        by_task: dict[str, list],
        gates: dict[str, asyncio.Event] | None = None,
    ):
        self.by_task = by_task
        self.gates = gates or {}
        self._used: set[str] = set()

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
        **kwargs,
    ) -> AsyncIterator:
        first_user = ""
        for m in messages:
            if m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            content = block.get("text", "")
                            break
                first_user = str(content)
                break
        for key, events in self.by_task.items():
            if key in first_user:
                if key in self._used:
                    yield TextDeltaEvent(content="Done.", snapshot="Done.")
                    yield FinishEvent(
                        stop_reason="stop",
                        input_tokens=1,
                        output_tokens=1,
                        model="mock",
                    )
                    return
                self._used.add(key)
                gate = self.gates.get(key)
                if gate is not None:
                    await gate.wait()
                for ev in events:
                    yield ev
                return

    def complete(self, messages, system="", **kwargs) -> LLMResponse:
        return LLMResponse(content="", model="mock", stop_reason="stop")


def _report(status: str, summary: str) -> list:
    return [
        ToolCallEvent(
            tool_use_id=f"r_{summary}",
            tool_name="report_to_parent",
            tool_input={"status": status, "summary": summary, "data": {}},
        ),
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _stub_executor(tool_use: ToolUse) -> ToolResult:
    return ToolResult(tool_use_id=tool_use.tool_use_id, content="ok", is_error=False)


def _make_colony(
    tmp_path: Path,
    *,
    max_concurrent: int = 2,
    by_task: dict[str, list] | None = None,
    gates: dict[str, asyncio.Event] | None = None,
    colony_id: str = "budget_test",
    config: ColonyConfig | None = None,
) -> ColonyRuntime:
    bus = EventBus()
    return ColonyRuntime(
        agent_spec=AgentSpec(
            id="t",
            name="t",
            description="t",
            system_prompt="t",
            agent_type="event_loop",
            output_keys=[],
            tool_access_policy="all",
        ),
        goal=Goal(id="g", name="g", description="g"),
        storage_path=tmp_path / "colony",
        llm=_ControlledReportLLM(by_task=by_task or {}, gates=gates),
        tools=[],
        tool_executor=_stub_executor,
        event_bus=bus,
        stream_id=colony_id,
        pipeline_stages=[],
        # adaptive_tool_budget pinned True: the ColonyConfig default reads
        # the HIVE_ADAPTIVE_TOOL_BUDGET kill switch from the environment,
        # and these tests must pass regardless of the developer's env.
        config=config or ColonyConfig(max_concurrent_workers=max_concurrent, adaptive_tool_budget=True),
    )


class _StubWorker:
    """Registry entry with just the fields the adaptation paths read."""

    def __init__(
        self,
        wid: str,
        status: WorkerStatus,
        *,
        pinned: bool = False,
        persistent: bool = False,
        budget: int = 150,
        grace: int = 1,
    ):
        self.id = wid
        self.status = status
        self.budget_pinned = pinned
        self.is_persistent = persistent
        self.agent_loop = AgentLoop(
            config=LoopConfig(
                tool_call_lifetime_budget=budget,
                grace_iterations=grace,
            )
        )

    @property
    def effective_budget(self) -> int:
        return self.agent_loop._config.tool_call_lifetime_budget


def _success(used: int, **extra: Any) -> dict[str, Any]:
    data = {"status": "success", "tool_calls_used": used}
    data.update(extra)
    return data


# ---------------------------------------------------------------------------
# AgentLoop.apply_lifetime_budget_cap — the shrink-only setter
# ---------------------------------------------------------------------------


def test_setter_shrinks_and_reports_true() -> None:
    loop = AgentLoop(config=LoopConfig(tool_call_lifetime_budget=150, grace_iterations=1))
    assert loop.apply_lifetime_budget_cap(60) is True
    assert loop._config.tool_call_lifetime_budget == 60


def test_setter_refuses_raise_zero_and_unlimited() -> None:
    loop = AgentLoop(config=LoopConfig(tool_call_lifetime_budget=100, grace_iterations=1))
    # Raise refused.
    assert loop.apply_lifetime_budget_cap(200) is False
    # Equal refused (not a shrink).
    assert loop.apply_lifetime_budget_cap(100) is False
    # Zero / negative refused (0 means "disabled", never disable via cap).
    assert loop.apply_lifetime_budget_cap(0) is False
    assert loop.apply_lifetime_budget_cap(-5) is False
    assert loop._config.tool_call_lifetime_budget == 100
    # Unlimited loops stay unlimited.
    unlimited = AgentLoop(config=LoopConfig(tool_call_lifetime_budget=0, grace_iterations=1))
    assert unlimited.apply_lifetime_budget_cap(50) is False
    assert unlimited._config.tool_call_lifetime_budget == 0


def test_setter_refuses_without_grace_phase() -> None:
    # A capped worker with no grace turn would die silently instead of
    # reporting — the setter must refuse.
    loop = AgentLoop(config=LoopConfig(tool_call_lifetime_budget=150, grace_iterations=0))
    assert loop.apply_lifetime_budget_cap(60) is False
    assert loop._config.tool_call_lifetime_budget == 150


def test_public_tool_calls_used_property() -> None:
    loop = AgentLoop(config=LoopConfig())
    assert loop.tool_calls_used == 0
    loop._tool_calls_used = 7
    assert loop.tool_calls_used == 7


def test_workers_route_serializes_budget_telemetry() -> None:
    """The workers API (used by the UI and the e2e adaptive-budget eval)
    must expose tool_calls_used/budget_limited on serialized results —
    and tolerate pre-upgrade results that lack the fields."""
    from framework.host.worker import WorkerInfo, WorkerResult, WorkerStatus
    from framework.server.routes_colony_workers import _worker_info_to_dict

    info = WorkerInfo(
        id="w1",
        task="t",
        status=WorkerStatus.COMPLETED,
        result=WorkerResult(status="success", tool_calls_used=12, budget_limited=True),
    )
    result = _worker_info_to_dict(info)["result"]
    assert result["tool_calls_used"] == 12
    assert result["budget_limited"] is True

    # Pre-upgrade shape (e.g. historical result.json): fields absent → defaults.
    legacy = SimpleNamespace(status="success", summary="", error=None, tokens_used=1, duration_seconds=1.0)
    legacy_info = SimpleNamespace(id="w2", task="t", status=WorkerStatus.COMPLETED, started_at=0.0, result=legacy)
    result = _worker_info_to_dict(legacy_info)["result"]
    assert result["tool_calls_used"] == 0
    assert result["budget_limited"] is False


def test_worker_cancel_paths_read_live_budget_limited() -> None:
    """The cancelled/crashed result paths have no AgentResult; they must
    mirror _build_result's budget_limited from the live loop counters so
    a budget-cut worker hard-stopped mid-grace stays a censored sample.
    """
    from framework.host.worker import Worker

    loop = AgentLoop(config=LoopConfig(tool_call_lifetime_budget=30, grace_iterations=1))
    worker = Worker(worker_id="w", task="t", agent_loop=loop, context=None)
    assert worker._loop_budget_limited() is False
    loop._counters["tool_lifetime_budget_grace"] = 1
    assert worker._loop_budget_limited() is True
    loop._tool_calls_used = 30
    assert worker._loop_tool_calls_used() == 30


# ---------------------------------------------------------------------------
# _maybe_adapt_colony_budget — sampler / policy matrix
# ---------------------------------------------------------------------------


def test_no_shrink_below_min_samples(tmp_path: Path) -> None:
    colony = _make_colony(tmp_path)
    for _ in range(_MIN_SAMPLES - 1):
        colony._maybe_adapt_colony_budget(_success(10))
    assert colony._budget_applied is None


def test_shrink_hits_floor_and_clamps_running_workers(tmp_path: Path) -> None:
    colony = _make_colony(tmp_path)
    running = _StubWorker("w_run", WorkerStatus.RUNNING)
    queued = _StubWorker("w_queued", WorkerStatus.QUEUED)
    pinned = _StubWorker("w_pin", WorkerStatus.RUNNING, pinned=True)
    persistent = _StubWorker("w_pers", WorkerStatus.RUNNING, persistent=True)
    done = _StubWorker("w_done", WorkerStatus.COMPLETED)
    for w in (running, queued, pinned, persistent, done):
        colony._workers[w.id] = w

    # Three cheap successes: nominal = max(2*10, ceil(1.25*10)) = 20,
    # floored up to the safety floor.
    for _ in range(3):
        colony._maybe_adapt_colony_budget(_success(10))

    assert colony._budget_applied == _FLOOR
    # Live clamp reaches RUNNING unpinned workers only.
    assert running.effective_budget == _FLOOR
    assert queued.effective_budget == 150  # picks it up at promotion instead
    assert pinned.effective_budget == 150
    assert persistent.effective_budget == 150
    assert done.effective_budget == 150


def test_formula_max_guard_keeps_headroom_over_observed_max(tmp_path: Path) -> None:
    colony = _make_colony(tmp_path)
    for used in (40, 40, 100):
        colony._maybe_adapt_colony_budget(_success(used))
    # median=40 → 2x = 80; max-guard = ceil(1.25*100) = 125 wins.
    assert colony._budget_applied == 125


def test_median_driven_raise_is_refused(tmp_path: Path) -> None:
    """Shrinking is statistical; raising is not. A rising *median* must
    never lift the nominal — once a clamp is censoring the expensive tail,
    the window is a biased sample, so only the max-guard (an uncensored,
    observed success cost) may raise. See test_evidence_driven_raise.
    """
    colony = _make_colony(tmp_path)
    for _ in range(3):
        colony._maybe_adapt_colony_budget(_success(30))
    assert colony._budget_applied == 60  # 2 * median(30)
    # Median climbs 30 -> 48, pushing the recomputed nominal to 96, but
    # max success is only 48 → evidence floor is ceil(1.25*48) = 60, which
    # does not exceed the applied 60. The nominal must not follow the median.
    for _ in range(5):
        colony._maybe_adapt_colony_budget(_success(48))
    assert colony._budget_applied == 60


def test_evidence_driven_raise_recovers_from_a_stale_low_norm(tmp_path: Path) -> None:
    """The anti-one-way-ratchet property: a colony whose work gets more
    expensive must be able to climb back out. Successes still land under
    the current cap, so a worker finishing just below it lifts max_success
    and the nominal ratchets up ~1.25x per near-cap success — no extra
    tool-call spend, no queen intervention.
    """
    colony = _make_colony(tmp_path)
    for _ in range(3):
        colony._maybe_adapt_colony_budget(_success(30))
    assert colony._budget_applied == 60

    # Work gets more expensive: a worker succeeds at 59, just under the cap.
    # max-guard = ceil(1.25 * 59) = 74 > 60 → the nominal climbs.
    colony._maybe_adapt_colony_budget(_success(59))
    assert colony._budget_applied == 74
    # And keeps climbing as workers crowd the raised cap.
    colony._maybe_adapt_colony_budget(_success(73))
    assert colony._budget_applied == 92


def test_raise_is_capped_at_the_profile_base(tmp_path: Path) -> None:
    colony = _make_colony(tmp_path)
    colony._budget_applied = 60
    # max success 180 → evidence floor ceil(1.25*180) = 225, over base 200.
    for _ in range(3):
        colony._maybe_adapt_colony_budget(_success(180))
    assert colony._budget_applied == _BASE  # never above the profile ceiling


def test_raise_does_not_lift_already_clamped_inflight_workers(tmp_path: Path) -> None:
    """The setter is shrink-only and refuses raises: workers already
    clamped finish under the old, lower cap. Only workers admitted after
    the raise see the higher nominal (via _apply_adaptive_budget).
    """
    colony = _make_colony(tmp_path)
    running = _StubWorker("w_run", WorkerStatus.RUNNING)
    colony._workers[running.id] = running
    for _ in range(3):
        colony._maybe_adapt_colony_budget(_success(10))
    assert colony._budget_applied == _FLOOR
    assert running.effective_budget == _FLOOR

    # Near-cap success at 29 → evidence floor ceil(1.25*29) = 37.
    colony._maybe_adapt_colony_budget(_success(29))
    assert colony._budget_applied == 37
    # The in-flight worker keeps its lower cap...
    assert running.effective_budget == _FLOOR
    # ...but a freshly admitted one starts at the raised nominal.
    fresh = _StubWorker("w_new", WorkerStatus.PENDING)
    colony._apply_adaptive_budget(fresh)
    assert fresh.effective_budget == 37


def test_max_guard_survives_window_eviction(tmp_path: Path) -> None:
    """The 1.25x max-guard reads the colony-lifetime max, so a flood of
    cheap samples evicting the expensive success from the rolling window
    cannot re-open the death spiral.
    """
    colony = _make_colony(tmp_path)
    for used in (40, 40, 100):
        colony._maybe_adapt_colony_budget(_success(used))
    assert colony._budget_applied == 125  # ceil(1.25 * 100)
    # 60 cheap successes — more than the 50-slot window — evict the 100.
    for _ in range(60):
        colony._maybe_adapt_colony_budget(_success(10))
    assert 100 not in colony._budget_samples
    # Median is now 10 (2x = 20), but the lifetime max-guard holds at 125.
    assert colony._budget_applied == 125


def test_dispersion_guard_skips_heterogeneous_samples(tmp_path: Path) -> None:
    colony = _make_colony(tmp_path)
    # p90 (100) > 4 x median (10) → visibly mixed work, no shrink.
    for used in (10, 10, 100):
        colony._maybe_adapt_colony_budget(_success(used))
    assert colony._budget_applied is None


def test_nominal_capped_at_base_no_shrink_when_typical_is_expensive(tmp_path: Path) -> None:
    colony = _make_colony(tmp_path)
    # 2 x median = 240 > base 200 → nominal caps at base → no shrink.
    for _ in range(3):
        colony._maybe_adapt_colony_budget(_success(120))
    assert colony._budget_applied is None


def test_sampler_exclusions(tmp_path: Path) -> None:
    colony = _make_colony(tmp_path)
    # None of these may enter the sample pool.
    colony._maybe_adapt_colony_budget({"status": "failed", "tool_calls_used": 10})
    colony._maybe_adapt_colony_budget({"status": "partial", "tool_calls_used": 10})
    colony._maybe_adapt_colony_budget(_success(10, budget_limited=True))
    colony._maybe_adapt_colony_budget(_success(10, budget_pinned=True))
    colony._maybe_adapt_colony_budget(_success(0))
    colony._maybe_adapt_colony_budget({"status": "success", "tool_calls_used": "10"})
    assert len(colony._budget_samples) == 0
    assert colony._budget_applied is None


def test_config_kill_switch(tmp_path: Path) -> None:
    colony = _make_colony(
        tmp_path,
        config=ColonyConfig(max_concurrent_workers=2, adaptive_tool_budget=False),
    )
    for _ in range(5):
        colony._maybe_adapt_colony_budget(_success(10))
    assert len(colony._budget_samples) == 0
    assert colony._budget_applied is None


# ---------------------------------------------------------------------------
# _apply_adaptive_budget — admission/promotion clamp
# ---------------------------------------------------------------------------


def test_admission_clamp_applies_current_nominal(tmp_path: Path) -> None:
    colony = _make_colony(tmp_path)
    w = _StubWorker("w1", WorkerStatus.PENDING)
    # No nominal yet → no-op.
    colony._apply_adaptive_budget(w)
    assert w.effective_budget == 150
    colony._budget_applied = 40
    colony._apply_adaptive_budget(w)
    assert w.effective_budget == 40
    # Pinned workers are never clamped.
    p = _StubWorker("w2", WorkerStatus.PENDING, pinned=True)
    colony._apply_adaptive_budget(p)
    assert p.effective_budget == 150


def test_get_stats_exposes_nominal(tmp_path: Path) -> None:
    colony = _make_colony(tmp_path)
    stats = colony.get_stats()["adaptive_tool_budget"]
    assert stats == {"enabled": True, "nominal": None, "samples": 0}
    for _ in range(3):
        colony._maybe_adapt_colony_budget(_success(10))
    stats = colony.get_stats()["adaptive_tool_budget"]
    assert stats["nominal"] == _FLOOR
    assert stats["samples"] == 3


# ---------------------------------------------------------------------------
# End-to-end through the scheduler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_norm_established_and_inflight_worker_clamped(tmp_path: Path) -> None:
    """Three cheap successes establish the colony norm; the stalled
    fourth worker (in flight) is live-clamped, and report payloads carry
    the new telemetry fields.
    """
    gates = {f"task-{i}": asyncio.Event() for i in range(4)}
    colony = _make_colony(
        tmp_path,
        max_concurrent=2,
        by_task={f"task-{i}": _report("success", f"{i} done") for i in range(4)},
        gates=gates,
    )

    reports: list[dict] = []

    async def _on_report(event: AgentEvent) -> None:
        reports.append(event.data or {})

    colony.event_bus.subscribe(
        event_types=[EventType.SUBAGENT_REPORT],
        handler=_on_report,
    )

    await colony.start()
    try:
        ids = await colony.spawn_batch([{"task": f"task-{i}"} for i in range(4)])
        # cap=2: task-0/1 running, task-2/3 queued.
        # Finish the first three; each success (1 tool call each) is a
        # sample. Mock workers report via a single report_to_parent call,
        # so median=1 → the nominal lands on the safety floor.
        for i in range(3):
            gates[f"task-{i}"].set()
            for _ in range(120):
                if len(reports) >= i + 1:
                    break
                await asyncio.sleep(0.05)
        assert len(reports) >= 3

        # Norm established at the floor.
        for _ in range(120):
            if colony._budget_applied is not None:
                break
            await asyncio.sleep(0.05)
        assert colony._budget_applied == _FLOOR

        # The straggler (task-3, promoted from the queue, stalled at its
        # gate) must have been clamped — either at promotion or by the
        # live broadcast on the norm-establishing report.
        straggler = next(colony._workers[wid] for wid in ids if colony._workers[wid].is_active)
        for _ in range(120):
            if straggler.agent_loop._config.tool_call_lifetime_budget == _FLOOR:
                break
            await asyncio.sleep(0.05)
        assert straggler.agent_loop._config.tool_call_lifetime_budget == _FLOOR

        # Telemetry fields ride every report.
        for r in reports[:3]:
            assert isinstance(r.get("tool_calls_used"), int) and r["tool_calls_used"] >= 1
            assert r.get("budget_limited") is False
            assert r.get("budget_pinned") is False
            assert isinstance(r.get("tool_call_lifetime_budget"), int)
            assert r["tool_call_lifetime_budget"] > 0

        gates["task-3"].set()
        for _ in range(120):
            if len(reports) >= 4:
                break
            await asyncio.sleep(0.05)
        assert len(reports) == 4
    finally:
        for g in gates.values():
            g.set()
        await colony.stop()


@pytest.mark.asyncio
async def test_e2e_explicit_override_pins_batch_out_of_adaptation(tmp_path: Path) -> None:
    """An explicit queen tool_call_lifetime_budget override pins the
    workers: they are never clamped and never feed the sample pool.
    """
    colony = _make_colony(
        tmp_path,
        max_concurrent=4,
        by_task={f"pin-{i}": _report("success", f"{i} done") for i in range(3)},
    )

    reports: list[dict] = []

    async def _on_report(event: AgentEvent) -> None:
        reports.append(event.data or {})

    colony.event_bus.subscribe(
        event_types=[EventType.SUBAGENT_REPORT],
        handler=_on_report,
    )

    await colony.start()
    try:
        ids = await colony.spawn_batch(
            [{"task": f"pin-{i}"} for i in range(3)],
            loop_config_overrides={"tool_call_lifetime_budget": 80},
        )
        for wid in ids:
            assert colony._workers[wid].budget_pinned is True
        for _ in range(120):
            if len(reports) >= 3:
                break
            await asyncio.sleep(0.05)
        assert len(reports) == 3
        # Pinned successes exert no force on the colony norm.
        assert len(colony._budget_samples) == 0
        assert colony._budget_applied is None
        for r in reports:
            assert r.get("budget_pinned") is True
    finally:
        await colony.stop()
