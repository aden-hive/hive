from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import framework.runner as runner_mod
from framework.server import session_manager as sm


@pytest.mark.asyncio
async def test_load_worker_blocks_invalid_package_before_runner_load(monkeypatch) -> None:
    manager = sm.SessionManager()
    session = sm.Session(
        id="sess-1",
        event_bus=MagicMock(),
        llm=MagicMock(),
        loaded_at=0.0,
    )
    manager._sessions[session.id] = session

    captured: dict[str, str] = {}

    def _fake_validation(agent_ref):
        captured["agent_ref"] = str(agent_ref)
        return {
            "valid": False,
            "steps": {
                "behavior_validation": {
                    "passed": False,
                    "errors": ["Node 'scan' has a blank or placeholder system_prompt"],
                }
            },
        }

    monkeypatch.setattr(
        sm,
        "_run_validation_report_sync",
        _fake_validation,
    )

    called = {"runner_load": False}

    class _FakeAgentRunner:
        @staticmethod
        def load(*args, **kwargs):
            called["runner_load"] = True
            raise AssertionError("AgentRunner.load should not run for invalid workers")

    monkeypatch.setattr(runner_mod, "AgentRunner", _FakeAgentRunner)

    with pytest.raises(sm.WorkerValidationError) as exc:
        await manager.load_worker(session.id, Path("/tmp/bad_worker"))

    assert "blank or placeholder system_prompt" in str(exc.value)
    assert Path(captured["agent_ref"]).as_posix() == "/tmp/bad_worker"
    assert called["runner_load"] is False


def test_run_validation_report_sync_uses_internal_validator_impl(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Proc:
        returncode = 0
        stdout = '{"valid": true, "steps": {}}'
        stderr = ""

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _Proc()

    monkeypatch.setattr(sm.subprocess, "run", _fake_run)

    report = sm._run_validation_report_sync("/tmp/demo_agent")

    assert report["valid"] is True
    script = captured["cmd"][4]
    assert "_validate_agent_package_impl" in script
    assert "validate_agent_package(agent_name)" not in script
    assert captured["cmd"][6] == "/tmp/demo_agent"


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

    assert sm._validation_blocks_stage_or_run(report) is False


def test_run_validation_report_sync_handles_subprocess_launcher_errors(monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise FileNotFoundError("uv not found")

    monkeypatch.setattr(sm.subprocess, "run", _boom)

    report = sm._run_validation_report_sync("/tmp/demo_agent")

    assert report["valid"] is False
    assert report["steps"]["validator_subprocess"]["passed"] is False
    assert "uv not found" in report["steps"]["validator_subprocess"]["error"]
