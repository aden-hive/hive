from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import framework.tools.queen_lifecycle_tools as qlt
from framework.llm.provider import Tool
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.event_bus import EventBus
from framework.tools.queen_lifecycle_tools import QueenPhaseState, register_queen_lifecycle_tools


def _write_worker_logs(
    storage_path: Path,
    session_id: str,
    *,
    session_status: str,
    steps: list[dict[str, object]],
) -> Path:
    session_dir = storage_path / "sessions" / session_id
    logs_dir = session_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "state.json").write_text(
        json.dumps({"status": session_status}),
        encoding="utf-8",
    )
    log_path = logs_dir / "tool_logs.jsonl"
    log_path.write_text(
        "".join(json.dumps(step) + "\n" for step in steps),
        encoding="utf-8",
    )
    return log_path


def _register_fake_validator(registry: ToolRegistry, report: dict) -> None:
    registry.register(
        "validate_agent_package",
        Tool(
            name="validate_agent_package",
            description="fake validator",
            parameters={"type": "object", "properties": {"agent_name": {"type": "string"}}},
        ),
        lambda _inputs: json.dumps(report),
    )


def test_parse_validation_report_handles_saved_footer() -> None:
    raw = (
        '{\n  "valid": false,\n  "steps": {"tool_validation": {"passed": false}}\n}\n\n'
        "[Saved to 'validate.txt']"
    )

    parsed = qlt._parse_validation_report(raw)

    assert parsed == {"valid": False, "steps": {"tool_validation": {"passed": False}}}


def test_validation_blocks_stage_or_run_ignores_non_blocking_warnings() -> None:
    report = {
        "steps": {
            "behavior_validation": {
                "passed": True,
                "warnings": ["placeholder prompt"],
                "output": "placeholder prompt",
            },
            "tests": {
                "passed": True,
                "warnings": ["1 failed"],
                "summary": "1 failed",
            },
        },
    }

    assert qlt._validation_blocks_stage_or_run(report) is False


@pytest.mark.asyncio
async def test_get_worker_status_summary_flags_retry_and_judge_pressure() -> None:
    registry = ToolRegistry()
    bus = EventBus()

    await bus.emit_node_retry(
        stream_id="worker",
        node_id="scan",
        retry_count=1,
        max_retries=3,
        error="still missing required result",
    )
    for _ in range(4):
        await bus.emit_judge_verdict(
            stream_id="worker",
            node_id="scan",
            action="RETRY",
            feedback="missing structured output",
        )

    runtime = SimpleNamespace(
        graph_id="worker-graph",
        get_graph_registration=lambda _gid: SimpleNamespace(
            streams={
                "default": SimpleNamespace(
                    active_execution_ids=["exec-1"],
                        get_context=lambda _exec_id: SimpleNamespace(started_at=datetime.now()),
                    get_waiting_nodes=lambda: [],
                )
            }
        ),
    )
    session = SimpleNamespace(worker_runtime=runtime, event_bus=bus, worker_path=None, runner=None)

    register_queen_lifecycle_tools(registry, session=session, session_id="sess-status")

    summary = await registry._tools["get_worker_status"].executor({})

    assert "issue type(s) detected" in summary


@pytest.mark.asyncio
async def test_get_worker_status_issues_reports_judge_pressure() -> None:
    registry = ToolRegistry()
    bus = EventBus()

    for action in ("CONTINUE", "RETRY", "RETRY", "ESCALATE"):
        await bus.emit_judge_verdict(
            stream_id="worker",
            node_id="review",
            action=action,
            feedback="still not converging",
        )

    runtime = SimpleNamespace(
        graph_id="worker-graph",
        get_graph_registration=lambda _gid: SimpleNamespace(streams={}),
    )
    session = SimpleNamespace(worker_runtime=runtime, event_bus=bus, worker_path=None, runner=None)

    register_queen_lifecycle_tools(registry, session=session, session_id="sess-issues")

    issues = await registry._tools["get_worker_status"].executor({"focus": "issues"})

    assert "Judge pressure detected" in issues
    assert "consecutive non-ACCEPT judge verdict" in issues


@pytest.mark.asyncio
async def test_get_worker_status_summary_uses_health_snapshot_signals(tmp_path: Path) -> None:
    storage_path = tmp_path / "agent_store"
    storage_path.mkdir(parents=True, exist_ok=True)
    log_path = _write_worker_logs(
        storage_path,
        "sess-health",
        session_status="running",
        steps=[
            {"verdict": "CONTINUE", "llm_text": "thinking"},
            {"verdict": "RETRY", "llm_text": "retrying"},
            {"verdict": "RETRY", "llm_text": "still retrying"},
            {"verdict": "ESCALATE", "llm_text": "need help"},
        ],
    )
    three_minutes_ago = time.time() - 180
    os.utime(log_path, (three_minutes_ago, three_minutes_ago))

    registry = ToolRegistry()
    bus = EventBus()
    runtime = SimpleNamespace(
        graph_id="worker-graph",
        get_graph_registration=lambda _gid: SimpleNamespace(
            streams={
                "default": SimpleNamespace(
                    active_execution_ids=["exec-1"],
                    get_context=lambda _exec_id: SimpleNamespace(started_at=datetime.now()),
                    get_waiting_nodes=lambda: [],
                )
            }
        ),
    )
    session = SimpleNamespace(
        worker_runtime=runtime,
        event_bus=bus,
        worker_path=storage_path,
        runner=None,
    )

    register_queen_lifecycle_tools(registry, session=session, session_id="sess-health")

    summary = await registry._tools["get_worker_status"].executor({})

    assert "issue signal(s) detected" in summary
    assert "judge_pressure" in summary
    assert "recent_non_accept_churn" in summary


@pytest.mark.asyncio
async def test_get_worker_status_issues_includes_health_snapshot_signals(tmp_path: Path) -> None:
    storage_path = tmp_path / "agent_store"
    storage_path.mkdir(parents=True, exist_ok=True)
    log_path = _write_worker_logs(
        storage_path,
        "sess-health",
        session_status="running",
        steps=[
            {"verdict": "CONTINUE", "llm_text": "thinking"},
            {"verdict": "RETRY", "llm_text": "retrying"},
            {"verdict": "RETRY", "llm_text": "still retrying"},
            {"verdict": "ESCALATE", "llm_text": "need help"},
        ],
    )
    three_minutes_ago = time.time() - 180
    os.utime(log_path, (three_minutes_ago, three_minutes_ago))

    registry = ToolRegistry()
    bus = EventBus()
    runtime = SimpleNamespace(
        graph_id="worker-graph",
        get_graph_registration=lambda _gid: SimpleNamespace(streams={}),
    )
    session = SimpleNamespace(
        worker_runtime=runtime,
        event_bus=bus,
        worker_path=storage_path,
        runner=None,
    )

    register_queen_lifecycle_tools(registry, session=session, session_id="sess-health")

    issues = await registry._tools["get_worker_status"].executor({"focus": "issues"})

    assert "Health signals:" in issues
    assert "slow_progress" in issues
    assert "recent_non_accept_churn" in issues


def test_build_worker_input_data_maps_bullet_task_fields_to_entry_inputs(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()

    runtime = SimpleNamespace(
        get_entry_points=lambda: [SimpleNamespace(id="default", entry_node="process")],
        graph=SimpleNamespace(
            entry_node="process",
            get_node=lambda node_id: SimpleNamespace(
                input_keys=[
                    "docs_dir",
                    "review_dir",
                    "word_threshold",
                    "style_rules",
                    "target_ratio",
                ]
            )
            if node_id == "process"
            else None,
        ),
    )

    payload = qlt._build_worker_input_data(
        runtime,
        (
            "Run md_condense_reviewer with the following runtime config:\n"
            "- docs_dir: docs/\n"
            "- review_dir: docs_reviews/\n"
            "- word_threshold: 800\n"
            "- target_ratio: 0.6 (default)\n"
            "- style_rules: Preserve headings and links.\n\n"
            "Execution requirements:\n"
            "1) Scan the docs directory.\n"
            "2) Write review copies."
        ),
    )

    assert payload == {
        "docs_dir": str((tmp_path / "docs").resolve()),
        "review_dir": str((tmp_path / "docs_reviews").resolve()),
        "word_threshold": 800,
        "style_rules": "Preserve headings and links.",
        "target_ratio": 0.6,
    }


def test_build_worker_input_data_maps_equals_style_runtime_fields(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    runtime = SimpleNamespace(
        get_entry_points=lambda: [SimpleNamespace(id="default", entry_node="process")],
        graph=SimpleNamespace(
            entry_node="process",
            get_node=lambda node_id: SimpleNamespace(
                input_keys=["target_dir", "review_dir_mode", "word_threshold"]
            )
            if node_id == "process"
            else None,
        ),
    )

    payload = qlt._build_worker_input_data(
        runtime,
        (
            "Yes, rerun with target_dir=docs "
            "review_dir_mode=next_to_source "
            "word_threshold=800"
        ),
    )

    assert payload == {
        "target_dir": str((tmp_path / "docs").resolve()),
        "review_dir_mode": "next_to_source",
        "word_threshold": 800,
    }


def test_build_worker_input_data_backfills_missing_fields_from_recent_session(
    monkeypatch, tmp_path: Path
) -> None:
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
        get_entry_points=lambda: [SimpleNamespace(id="default", entry_node="process")],
        graph=SimpleNamespace(
            entry_node="process",
            get_node=lambda node_id: SimpleNamespace(
                input_keys=["target_dir", "review_dir", "word_threshold"]
            )
            if node_id == "process"
            else None,
        ),
    )

    payload = qlt._build_worker_input_data(
        runtime,
        (
            "review_dir: docs_reviews\n"
            "word_threshold: 800. Validate inputs and continue."
        ),
    )

    assert payload == {
        "target_dir": str((tmp_path / "docs").resolve()),
        "review_dir": str((tmp_path / "docs_reviews").resolve()),
        "word_threshold": 800,
    }


def test_build_worker_input_data_reuses_recent_defaults_for_rerun_phrase(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    sessions_dir = tmp_path / "agent_store" / "sessions"
    sessions_dir.mkdir(parents=True)

    state = {
        "timestamps": {"updated_at": "2026-03-24T21:17:00"},
        "input_data": {
            "target_dir": "docs",
            "review_dir": "docs_reviews",
            "word_threshold": 800,
        },
    }
    session_dir = sessions_dir / "session_20260324_211700_prev"
    session_dir.mkdir()
    (session_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    runtime = SimpleNamespace(
        _session_store=SimpleNamespace(sessions_dir=sessions_dir),
        get_entry_points=lambda: [SimpleNamespace(id="default", entry_node="process")],
        graph=SimpleNamespace(
            entry_node="process",
            get_node=lambda node_id: SimpleNamespace(
                input_keys=["target_dir", "review_dir", "word_threshold"]
            )
            if node_id == "process"
            else None,
        ),
    )

    payload = qlt._build_worker_input_data(runtime, "Run again with same defaults")

    assert payload == {
        "target_dir": str((tmp_path / "docs").resolve()),
        "review_dir": str((tmp_path / "docs_reviews").resolve()),
        "word_threshold": 800,
    }


def test_build_worker_input_data_backfills_from_recent_result_output(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    sessions_dir = tmp_path / "agent_store" / "sessions"
    sessions_dir.mkdir(parents=True)

    state = {
        "timestamps": {"updated_at": "2026-03-24T23:35:19"},
        "input_data": {
            "review_dir": "docs_reviews",
            "word_threshold": 800,
        },
        "result": {
            "output": {
                "target_dir": "docs",
                "review_dir": "docs_reviews",
                "word_threshold": 800,
            }
        },
    }
    session_dir = sessions_dir / "session_20260324_233519_prev"
    session_dir.mkdir()
    (session_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    runtime = SimpleNamespace(
        _session_store=SimpleNamespace(sessions_dir=sessions_dir),
        get_entry_points=lambda: [SimpleNamespace(id="default", entry_node="process")],
        graph=SimpleNamespace(
            entry_node="process",
            get_node=lambda node_id: SimpleNamespace(
                input_keys=["target_dir", "review_dir", "word_threshold"]
            )
            if node_id == "process"
            else None,
        ),
    )

    payload = qlt._build_worker_input_data(
        runtime,
        (
            "review_dir: docs_reviews\n"
            "word_threshold: 600"
        ),
    )

    assert payload == {
        "target_dir": str((tmp_path / "docs").resolve()),
        "review_dir": str((tmp_path / "docs_reviews").resolve()),
        "word_threshold": 600,
    }


@pytest.mark.asyncio
async def test_load_built_agent_blocks_invalid_package(monkeypatch, tmp_path: Path) -> None:
    registry = ToolRegistry()
    captured: dict[str, str] = {}
    registry.register(
        "validate_agent_package",
        Tool(
            name="validate_agent_package",
            description="fake validator",
            parameters={"type": "object", "properties": {"agent_name": {"type": "string"}}},
        ),
        lambda inputs: (
            captured.setdefault("agent_name", inputs["agent_name"]),
            json.dumps(
                {
                    "valid": False,
                    "steps": {
                        "behavior_validation": {
                            "passed": False,
                            "output": (
                                "Node 'scan-markdown' has a blank or placeholder"
                                " system_prompt"
                            ),
                        }
                    },
                }
            ),
        )[1],
    )

    session = SimpleNamespace(worker_runtime=None, event_bus=None, worker_path=None, runner=None)
    fake_manager = SimpleNamespace(
        get_session=lambda _sid: None,
        unload_worker=AsyncMock(),
        load_worker=AsyncMock(),
    )
    phase_state = QueenPhaseState(phase="building")
    register_queen_lifecycle_tools(
        registry,
        session=session,
        session_manager=fake_manager,
        manager_session_id="sess-1",
        phase_state=phase_state,
    )

    agent_dir = tmp_path / "broken_agent"
    agent_dir.mkdir()
    monkeypatch.setattr(qlt, "validate_agent_path", lambda _path: agent_dir)

    result_raw = await registry._tools["load_built_agent"].executor({"agent_path": str(agent_dir)})
    result = json.loads(result_raw)

    assert "Cannot load agent" in result["error"]
    assert "behavior_validation" in result["validation_failures"][0]
    assert captured["agent_name"] == str(agent_dir)
    fake_manager.load_worker.assert_not_called()


@pytest.mark.asyncio
async def test_run_agent_with_input_blocks_loaded_invalid_worker() -> None:
    registry = ToolRegistry()
    _register_fake_validator(
        registry,
        {
            "valid": False,
            "steps": {
                "tool_validation": {
                    "passed": False,
                    "output": "Scan Markdown Files missing run_command",
                }
            },
        },
    )

    runtime = SimpleNamespace(
        resume_timers=MagicMock(),
        trigger=AsyncMock(),
        _get_primary_session_state=MagicMock(return_value={}),
        graph=SimpleNamespace(nodes=[]),
    )
    session = SimpleNamespace(
        worker_runtime=runtime,
        event_bus=None,
        worker_path=Path("exports/broken_agent"),
        runner=None,
    )
    phase_state = QueenPhaseState(phase="staging")
    register_queen_lifecycle_tools(
        registry,
        session=session,
        session_id="sess-2",
        phase_state=phase_state,
    )

    result_raw = await registry._tools["run_agent_with_input"].executor({"task": "run it"})
    result = json.loads(result_raw)

    assert "Cannot run agent" in result["error"]
    assert "tool_validation" in result["validation_failures"][0]
    runtime.trigger.assert_not_called()


@pytest.mark.asyncio
async def test_run_agent_with_input_uses_structured_entry_inputs(
    monkeypatch, tmp_path: Path
) -> None:
    registry = ToolRegistry()
    _register_fake_validator(registry, {"valid": True, "steps": {}})

    monkeypatch.setattr(qlt, "validate_credentials", lambda *args, **kwargs: None)
    monkeypatch.chdir(tmp_path)

    runtime = SimpleNamespace(
        resume_timers=MagicMock(),
        trigger=AsyncMock(return_value="exec-1"),
        _get_primary_session_state=MagicMock(return_value={}),
        get_entry_points=lambda: [SimpleNamespace(id="default", entry_node="process")],
        graph=SimpleNamespace(
            nodes=[],
            entry_node="process",
            get_node=lambda node_id: SimpleNamespace(
                input_keys=["docs_path", "review_path", "word_threshold", "style_rules"]
            )
            if node_id == "process"
            else None,
        ),
    )
    session = SimpleNamespace(
        worker_runtime=runtime,
        event_bus=None,
        worker_path=Path("exports/markdown_condense_approver"),
        runner=None,
    )
    phase_state = QueenPhaseState(phase="staging")
    register_queen_lifecycle_tools(
        registry,
        session=session,
        session_id="sess-3",
        phase_state=phase_state,
    )

    result_raw = await registry._tools["run_agent_with_input"].executor(
        {
            "task": (
                "docs_path: docs/ review_path: docs_reviews/ word_threshold: 800 "
                "style_rules: Preserve headings, keep links intact."
            )
        }
    )
    result = json.loads(result_raw)

    assert result["status"] == "started"
    runtime.trigger.assert_awaited_once()
    trigger_kwargs = runtime.trigger.await_args.kwargs
    assert trigger_kwargs["input_data"] == {
        "docs_path": str((tmp_path / "docs").resolve()),
        "review_path": str((tmp_path / "docs_reviews").resolve()),
        "word_threshold": 800,
        "style_rules": "Preserve headings, keep links intact.",
    }
    assert trigger_kwargs["session_state"] is None
    runtime._get_primary_session_state.assert_not_called()


@pytest.mark.asyncio
async def test_rerun_worker_with_last_input_reuses_complete_recent_defaults(
    monkeypatch, tmp_path: Path
) -> None:
    registry = ToolRegistry()
    _register_fake_validator(registry, {"valid": True, "steps": {}})

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
    phase_state = QueenPhaseState(phase="staging")
    register_queen_lifecycle_tools(
        registry,
        session=session,
        session_id="sess-rerun",
        phase_state=phase_state,
    )

    result_raw = await registry._tools["rerun_worker_with_last_input"].executor({})
    result = json.loads(result_raw)

    assert result["status"] == "started"
    runtime.trigger.assert_awaited_once()
    trigger_kwargs = runtime.trigger.await_args.kwargs
    assert trigger_kwargs["input_data"] == {
        "target_dir": str((tmp_path / "docs").resolve()),
        "review_dir": str((tmp_path / "docs_reviews").resolve()),
        "word_threshold": 800,
    }
    assert trigger_kwargs["session_state"] is None


@pytest.mark.asyncio
async def test_start_worker_starts_fresh_worker_session(monkeypatch, tmp_path: Path) -> None:
    registry = ToolRegistry()
    monkeypatch.setattr(qlt, "validate_credentials", lambda *args, **kwargs: None)
    monkeypatch.chdir(tmp_path)

    runtime = SimpleNamespace(
        resume_timers=MagicMock(),
        trigger=AsyncMock(return_value="exec-2"),
        _get_primary_session_state=MagicMock(return_value={"resume_session_id": "old"}),
        graph=SimpleNamespace(nodes=[]),
    )
    session = SimpleNamespace(
        worker_runtime=runtime,
        event_bus=None,
        worker_path=Path("exports/docs_sanitizer_agent"),
        runner=None,
    )
    register_queen_lifecycle_tools(
        registry,
        session=session,
        session_id="sess-4",
        phase_state=QueenPhaseState(phase="staging"),
    )

    result_raw = await registry._tools["start_worker"].executor(
        {"task": "run with docs_path: docs/"}
    )
    result = json.loads(result_raw)

    assert result["status"] == "started"
    runtime.trigger.assert_awaited_once()
    trigger_kwargs = runtime.trigger.await_args.kwargs
    assert trigger_kwargs["session_state"] is None
    runtime._get_primary_session_state.assert_not_called()
