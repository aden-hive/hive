"""Tests for output_schema contract enforcement on worker to queen reports."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from framework.agent_loop.types import AgentSpec
from framework.host.colony_runtime import ColonyRuntime
from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import FinishEvent, ToolCallEvent
from framework.loader.tool_registry import ToolRegistry
from framework.schemas.goal import Goal
from framework.tools.queen_lifecycle_tools import register_queen_lifecycle_tools


class _MockLLM(LLMProvider):
    model: str = "mock"

    def __init__(self, status: str, summary: str, data: dict[str, Any]):
        self.status = status
        self.summary = summary
        self.data = data
        self.called = False

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
        **kwargs,
    ) -> AsyncIterator:
        if not self.called:
            self.called = True
            yield ToolCallEvent(
                tool_use_id="tu_report",
                tool_name="report_to_parent",
                tool_input={"status": self.status, "summary": self.summary, "data": self.data},
            )
            yield FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock")
        else:
            yield FinishEvent(stop_reason="stop", input_tokens=1, output_tokens=1, model="mock")

    def complete(self, messages, system="", **kwargs) -> LLMResponse:
        return LLMResponse(content="", model="mock", stop_reason="stop")


def _stub_executor(tool_use: ToolUse) -> ToolResult:
    return ToolResult(tool_use_id=tool_use.tool_use_id, content="ok", is_error=False)


class _FakeSession:
    def __init__(self, colony: ColonyRuntime, session_id: str):
        self.colony = colony
        self.id = session_id
        self.colony_runtime = None
        self.event_bus = colony.event_bus
        self.worker_path = None
        self.available_triggers = {}
        self.active_trigger_ids = set()


async def _run_colony_validation_test(
    tmp_path: Path,
    status: str,
    summary: str,
    data: dict[str, Any],
    output_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    bus = EventBus()
    llm = _MockLLM(status, summary, data)

    colony = ColonyRuntime(
        agent_spec=AgentSpec(
            id="test_colony",
            name="Test Colony",
            description="Schema validation test colony.",
            system_prompt="You are a test agent.",
            agent_type="event_loop",
            output_keys=[],
            tool_access_policy="all",
        ),
        goal=Goal(id="g", name="g", description="g"),
        storage_path=tmp_path / "colony",
        llm=llm,
        tools=[],
        tool_executor=_stub_executor,
        event_bus=bus,
        colony_id="test_session",
        pipeline_stages=[],
    )
    await colony.start()

    collected_reports: list[dict] = []

    async def _on_report(event: AgentEvent) -> None:
        collected_reports.append(event.data or {})

    bus.subscribe(event_types=[EventType.SUBAGENT_REPORT], handler=_on_report)

    session = _FakeSession(colony, "test_session")
    registry = ToolRegistry()
    register_queen_lifecycle_tools(registry, session=session, session_id=session.id)

    try:
        executor = registry.get_executor()
        task_spec = {"task": "run-validation-task"}
        if output_schema is not None:
            task_spec["output_schema"] = output_schema

        tool_use = ToolUse(
            id="tu_run_parallel",
            name="run_parallel_workers",
            input={
                "tasks": [task_spec],
                "timeout": 30.0,
            },
        )

        async def _invoke() -> Any:
            r = executor(tool_use)
            if asyncio.iscoroutine(r):
                r = await r
            return r

        await asyncio.wait_for(_invoke(), timeout=5.0)

        # Wait for worker to finish and SUBAGENT_REPORT to fire.
        for _ in range(50):
            if len(collected_reports) >= 1:
                break
            await asyncio.sleep(0.05)

        assert len(collected_reports) == 1, "Expected 1 report"
        return collected_reports[0]

    finally:
        await colony.stop()


@pytest.mark.asyncio
async def test_valid_schema_valid_payload(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "properties": {
            "rows": {"type": "integer"},
            "table": {"type": "string"},
        },
        "required": ["rows", "table"],
    }
    data = {"rows": 42, "table": "users"}
    report = await _run_colony_validation_test(tmp_path, "success", "All good", data, schema)
    assert report["status"] == "success"
    assert report["summary"] == "All good"
    assert report["data"] == data
    assert report.get("error") is None


@pytest.mark.asyncio
async def test_valid_schema_invalid_payload(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "properties": {
            "rows": {"type": "integer"},
        },
    }
    data = {"rows": "not-an-integer"}
    report = await _run_colony_validation_test(tmp_path, "success", "My summary", data, schema)
    assert report["status"] == "failed"
    assert "[Schema Validation Failure]" in report["summary"]
    assert "Schema validation failed" in report["error"]
    assert report["data"] == data  # Preserved original payload


@pytest.mark.asyncio
async def test_missing_required_fields(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "required": ["rows", "table"],
    }
    data = {"rows": 42}
    report = await _run_colony_validation_test(tmp_path, "success", "My summary", data, schema)
    assert report["status"] == "failed"
    assert "table" in report["summary"]
    assert report["data"] == data


@pytest.mark.asyncio
async def test_nested_objects(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "properties": {
            "meta": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                },
                "required": ["count"],
            }
        },
    }
    # Invalid nested field
    data = {"meta": {"count": "not-an-int"}}
    report = await _run_colony_validation_test(tmp_path, "success", "My summary", data, schema)
    assert report["status"] == "failed"
    assert "meta.count" in report["summary"]


@pytest.mark.asyncio
async def test_arrays_validation(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {"type": "integer"},
            }
        },
    }
    data = {"items": [1, 2, "not-an-int"]}
    report = await _run_colony_validation_test(tmp_path, "success", "My summary", data, schema)
    assert report["status"] == "failed"
    assert "items.2" in report["summary"]


@pytest.mark.asyncio
async def test_multiple_validation_failures(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "name": {"type": "string"},
        },
        "required": ["count", "name"],
    }
    data = {"count": "not-an-int"}  # missing name, invalid count
    report = await _run_colony_validation_test(tmp_path, "success", "My summary", data, schema)
    assert report["status"] == "failed"
    assert "name" in report["summary"]
    assert "count" in report["summary"]


@pytest.mark.asyncio
async def test_no_schema_provided(tmp_path: Path) -> None:
    data = {"arbitrary": "anything"}
    report = await _run_colony_validation_test(tmp_path, "success", "All good", data, None)
    assert report["status"] == "success"
    assert report["summary"] == "All good"
    assert report["data"] == data


@pytest.mark.asyncio
async def test_failed_report_exemption(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "properties": {
            "rows": {"type": "integer"},
        },
        "required": ["rows"],
    }
    data = {"bad": "payload"}
    # Worker reports "failed" - must be exempt from validation
    report = await _run_colony_validation_test(tmp_path, "failed", "I failed", data, schema)
    assert report["status"] == "failed"
    assert "[Schema Validation Failure]" not in report["summary"]
    assert report["summary"] == "I failed"


@pytest.mark.asyncio
async def test_partial_report_exemption(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "properties": {
            "rows": {"type": "integer"},
        },
        "required": ["rows"],
    }
    data = {"bad": "payload"}
    # Worker reports "partial" - must be exempt from validation
    report = await _run_colony_validation_test(tmp_path, "partial", "Some progress", data, schema)
    assert report["status"] == "partial"
    assert "[Schema Validation Failure]" not in report["summary"]
    assert report["summary"] == "Some progress"
