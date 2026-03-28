from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from framework.runner.tool_registry import ToolRegistry
from framework.runtime.event_bus import EventBus
from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools


def _write_session_logs(
    storage_path: Path,
    session_id: str,
    *,
    session_status: str,
    steps: list[dict],
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


@pytest.mark.asyncio
async def test_worker_health_summary_marks_healthy_runs(tmp_path: Path) -> None:
    registry = ToolRegistry()
    event_bus = EventBus()
    storage_path = tmp_path / "agent_store"
    storage_path.mkdir(parents=True, exist_ok=True)

    _write_session_logs(
        storage_path,
        "session-healthy",
        session_status="running",
        steps=[
            {"verdict": "RETRY", "llm_text": "first pass"},
            {"verdict": "ACCEPT", "llm_text": "done"},
        ],
    )

    register_worker_monitoring_tools(
        registry,
        event_bus,
        storage_path,
        default_session_id="session-healthy",
    )

    raw = await registry._tools["get_worker_health_summary"].executor({})
    data = json.loads(raw)

    assert data["health_status"] == "healthy"
    assert data["issue_signals"] == []
    assert data["recent_verdicts"] == ["RETRY", "ACCEPT"]
    assert data["steps_since_last_accept"] == 0


@pytest.mark.asyncio
async def test_worker_health_summary_flags_stall_and_non_accept_churn(tmp_path: Path) -> None:
    registry = ToolRegistry()
    event_bus = EventBus()
    storage_path = tmp_path / "agent_store"
    storage_path.mkdir(parents=True, exist_ok=True)

    log_path = _write_session_logs(
        storage_path,
        "session-stalled",
        session_status="running",
        steps=[
            {"verdict": "CONTINUE", "llm_text": "thinking"},
            {"verdict": "RETRY", "llm_text": "still working"},
            {"verdict": "RETRY", "llm_text": "trying again"},
            {"verdict": "ESCALATE", "llm_text": "blocked"},
        ],
    )
    ten_minutes_ago = time.time() - 600
    os.utime(log_path, (ten_minutes_ago, ten_minutes_ago))

    register_worker_monitoring_tools(
        registry,
        event_bus,
        storage_path,
        default_session_id="session-stalled",
    )

    raw = await registry._tools["get_worker_health_summary"].executor({})
    data = json.loads(raw)

    assert data["health_status"] == "critical"
    assert "stalled" in data["issue_signals"]
    assert "judge_pressure" in data["issue_signals"]
    assert "recent_non_accept_churn" in data["issue_signals"]
    assert data["steps_since_last_accept"] == 4
    assert data["stall_minutes"] is not None


@pytest.mark.asyncio
async def test_worker_health_summary_errors_when_default_session_has_no_state(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry()
    event_bus = EventBus()
    storage_path = tmp_path / "agent_store"
    (storage_path / "sessions" / "session-stale").mkdir(parents=True, exist_ok=True)

    register_worker_monitoring_tools(
        registry,
        event_bus,
        storage_path,
        default_session_id="session-stale",
    )

    raw = await registry._tools["get_worker_health_summary"].executor({})
    data = json.loads(raw)

    assert "error" in data
    assert "session-stale" in data["error"]
