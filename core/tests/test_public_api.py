"""The ``hive`` package: Hive's primitives for projects built on it.

Every exported name resolves, importing stays light, and an agent loop hands its report to
``on_report`` without being a colony worker.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import AsyncIterator
from typing import Any

import pytest

import hive


@pytest.mark.parametrize("name", sorted(hive._EXPORTS))
def test_every_primitive_resolves(name: str) -> None:
    assert getattr(hive, name) is not None


def test_all_lists_every_export_but_the_optional_ones() -> None:
    # SSEResponse needs the server extra, so a star import must not reach for it.
    assert set(hive.__all__) - {"__version__"} == set(hive._EXPORTS) - {"SSEResponse"}


def test_the_version_is_the_installed_one() -> None:
    from importlib.metadata import version

    assert hive.__version__ == version("aden-hive")


def _loaded_after(statement: str) -> set[str]:
    code = f"import sys; {statement}; print(','.join(sorted(sys.modules)))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    return set(out.strip().split(","))


def test_importing_hive_loads_nothing_until_used() -> None:
    loaded = _loaded_after("import hive")
    assert "framework.agent_loop.agent_loop" not in loaded
    assert "litellm" not in loaded


def test_one_module_of_the_framework_does_not_load_the_rest() -> None:
    loaded = _loaded_after("import framework.host.event_bus")
    assert "framework.host.colony_runtime" not in loaded
    assert "framework.agent_loop.agent_loop" not in loaded


def _report(summary: str, *, uid: str = "r1", status: str = "success", data: dict[str, Any] | None = None) -> hive.ToolCallEvent:
    return hive.ToolCallEvent(tool_use_id=uid, tool_name="report_to_parent", tool_input={"status": status, "summary": summary, "data": data or {}})


_CALLED_TOOLS = hive.FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="scripted")
_TALKS = [
    hive.TextDeltaEvent(content="Done.", snapshot="Done."),
    hive.FinishEvent(stop_reason="stop", input_tokens=10, output_tokens=5, model="scripted"),
]


class _ScriptedLLM(hive.LLMProvider):
    """Plays one scripted turn per call, then repeats the last; remembers the tools it was first offered."""

    model = "scripted"

    def __init__(self, *turns: list[Any]) -> None:
        self.turns = turns
        self.calls = 0
        self.offered: list[str] = []

    async def stream(self, messages: list[dict[str, Any]], system: str = "", tools: list | None = None, **kwargs: Any) -> AsyncIterator:
        if not self.calls:
            self.offered = [t.name for t in tools or []]
        events = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        for event in events:
            yield event

    def complete(self, messages: list[dict[str, Any]], system: str = "", **kwargs: Any) -> Any:
        return hive.LLMResponse(content="", model="scripted", stop_reason="stop")


async def _run(
    llm: hive.LLMProvider, *, max_iterations: int = 3, stream_id: str = "game", reporting: bool = True
) -> tuple[Any, list[hive.AgentReport]]:
    reports: list[hive.AgentReport] = []
    spec = hive.AgentSpec(id="counter", name="Counter", description="Counts", system_prompt="Count the sheep, then report.")
    ctx = hive.AgentContext(runtime=None, agent_id="counter", agent_spec=spec, llm=llm, stream_id=stream_id)
    loop = hive.AgentLoop(config=hive.LoopConfig(max_iterations=max_iterations), on_report=reports.append if reporting else None)
    return await loop.execute(ctx), reports


@pytest.mark.asyncio
async def test_on_report_receives_the_report_without_a_worker_stream() -> None:
    llm = _ScriptedLLM([_report("Counted the sheep.", data={"sheep": 12}), _CALLED_TOOLS], _TALKS)
    result, reports = await _run(llm)
    assert "report_to_parent" in llm.offered and "escalate" not in llm.offered
    assert reports == [hive.AgentReport(status="success", summary="Counted the sheep.", data={"sheep": 12})]
    assert result.success is True


@pytest.mark.asyncio
async def test_without_on_report_only_a_worker_stream_may_report() -> None:
    llm = _ScriptedLLM([_report("x"), _CALLED_TOOLS], _TALKS)
    await _run(llm, max_iterations=1, stream_id="judge", reporting=False)
    assert "report_to_parent" not in llm.offered


@pytest.mark.asyncio
async def test_a_report_on_the_last_iteration_ends_the_run_successfully() -> None:
    result, reports = await _run(_ScriptedLLM([_report("Counted the sheep."), _CALLED_TOOLS], _TALKS), max_iterations=1)
    assert [r.summary for r in reports] == ["Counted the sheep."]
    assert result.success is True


@pytest.mark.asyncio
async def test_only_the_first_report_in_a_batch_is_delivered() -> None:
    llm = _ScriptedLLM([_report("first", uid="r1"), _report("second", uid="r2"), _CALLED_TOOLS], _TALKS)
    _, reports = await _run(llm)
    assert [r.summary for r in reports] == ["first"]


@pytest.mark.asyncio
async def test_an_agent_that_never_reports_is_reported_failed_without_an_event_bus() -> None:
    talk = [[hive.TextDeltaEvent(content=f"Still counting ({n}).", snapshot=f"Still counting ({n})."), _TALKS[-1]] for n in range(8)]
    result, reports = await _run(_ScriptedLLM(*talk), max_iterations=8)  # varied, so the repeated-reply guard stays out of it
    assert [(r.status, r.data.get("auto_fail_reason")) for r in reports] == [("failed", "stall_text_only")]
    assert result.success is True  # the loop ended cleanly; the report says it failed
