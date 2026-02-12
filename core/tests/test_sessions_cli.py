import argparse
import json
from datetime import datetime
from pathlib import Path

import pytest

from framework.runner.cli import cmd_sessions_checkpoints, cmd_sessions_list, cmd_sessions_show
from framework.schemas.checkpoint import Checkpoint, CheckpointIndex
from framework.schemas.session_state import (
    SessionProgress,
    SessionResult,
    SessionState,
    SessionStatus,
    SessionTimestamps,
)


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def _write_session_state(
    base_home: Path,
    agent_name: str,
    state: SessionState,
) -> Path:
    state_path = (
        base_home
        / ".hive"
        / "agents"
        / agent_name
        / "sessions"
        / state.session_id
        / "state.json"
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    return state_path


def _make_state(
    session_id: str,
    status: SessionStatus,
    *,
    checkpoint_enabled: bool = False,
    latest_checkpoint_id: str | None = None,
) -> SessionState:
    now = datetime.now().isoformat()
    return SessionState(
        session_id=session_id,
        goal_id="goal_x",
        status=status,
        timestamps=SessionTimestamps(started_at=now, updated_at=now),
        progress=SessionProgress(current_node="node_a"),
        result=SessionResult(success=None),
        checkpoint_enabled=checkpoint_enabled,
        latest_checkpoint_id=latest_checkpoint_id,
    )


def test_sessions_list_filters_has_checkpoints(fake_home: Path, capsys: pytest.CaptureFixture[str]):
    agent_name = "my_agent"
    with_cp = _make_state(
        "session_20260212_010101_aaaabbbb",
        SessionStatus.PAUSED,
        checkpoint_enabled=True,
        latest_checkpoint_id="cp_node_complete_node_a_20260212_010102",
    )
    without_cp = _make_state(
        "session_20260212_020202_ccccdddd",
        SessionStatus.COMPLETED,
        checkpoint_enabled=False,
        latest_checkpoint_id=None,
    )
    _write_session_state(fake_home, agent_name, with_cp)
    _write_session_state(fake_home, agent_name, without_cp)

    args = argparse.Namespace(
        agent_path=f"exports/{agent_name}",
        status="all",
        has_checkpoints=True,
    )
    rc = cmd_sessions_list(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert with_cp.session_id in out
    assert without_cp.session_id not in out


def test_sessions_show_json(fake_home: Path, capsys: pytest.CaptureFixture[str]):
    agent_name = "my_agent"
    state = _make_state(
        "session_20260212_030303_eeeeffff",
        SessionStatus.FAILED,
    )
    _write_session_state(fake_home, agent_name, state)

    args = argparse.Namespace(
        agent_path=f"exports/{agent_name}",
        session_id=state.session_id,
        json=True,
    )
    rc = cmd_sessions_show(args)
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["session_id"] == state.session_id
    assert payload["goal_id"] == "goal_x"


def test_sessions_checkpoints_lists_index(
    fake_home: Path, capsys: pytest.CaptureFixture[str]
):
    agent_name = "my_agent"
    session_id = "session_20260212_040404_11112222"

    state = _make_state(
        session_id,
        SessionStatus.FAILED,
        checkpoint_enabled=True,
        latest_checkpoint_id="cp_node_complete_node_a_20260212_040405",
    )
    _write_session_state(fake_home, agent_name, state)

    session_dir = fake_home / ".hive" / "agents" / agent_name / "sessions" / session_id
    checkpoints_dir = session_dir / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)

    cp = Checkpoint(
        checkpoint_id=state.latest_checkpoint_id,
        checkpoint_type="node_complete",
        session_id=session_id,
        created_at=datetime.now().isoformat(),
        current_node="node_a",
        next_node="node_b",
        execution_path=["node_a"],
        shared_memory={"k": "v"},
    )
    (checkpoints_dir / f"{cp.checkpoint_id}.json").write_text(
        cp.model_dump_json(indent=2),
        encoding="utf-8",
    )

    index = CheckpointIndex(session_id=session_id)
    index.add_checkpoint(cp)
    (checkpoints_dir / "index.json").write_text(
        index.model_dump_json(indent=2),
        encoding="utf-8",
    )

    args = argparse.Namespace(
        agent_path=f"exports/{agent_name}",
        session_id=session_id,
    )
    rc = cmd_sessions_checkpoints(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert cp.checkpoint_id in out
    assert "Latest:" in out


def test_resume_tui_setup_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from framework.runner.cli import cmd_resume

    class _StubRunner:
        _agent_runtime = None

        def _setup(self) -> None:
            raise RuntimeError("boom")

        async def cleanup_async(self) -> None:
            return None

    monkeypatch.setattr("framework.runner.cli._load_resume_state", lambda *a, **k: {})
    monkeypatch.setattr("framework.runner.AgentRunner.load", lambda *a, **k: _StubRunner())

    args = argparse.Namespace(
        agent_path="exports/my_agent",
        session_id="session_20260212_050505_33334444",
        checkpoint=None,
        tui=True,
    )
    rc = cmd_resume(args)
    assert rc == 1
    err = capsys.readouterr().err
    assert "Error setting up runtime" in err

