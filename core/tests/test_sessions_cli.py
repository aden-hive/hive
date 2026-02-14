from __future__ import annotations

import argparse
import json
from datetime import datetime

from framework.runner.cli import (
    _load_resume_state,
    cmd_sessions_checkpoints,
    cmd_sessions_list,
    cmd_sessions_show,
)
from framework.schemas.checkpoint import CheckpointIndex, CheckpointSummary
from framework.schemas.session_state import SessionState, SessionStatus, SessionTimestamps


def _write_state(tmp_path, state: SessionState) -> None:
    session_dir = tmp_path / "sessions" / state.session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "state.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")


def test_sessions_list_and_show_use_storage_path(tmp_path, capsys) -> None:
    session_id = "session_20260214_130000_abc12345"
    now = datetime.now().isoformat()
    state = SessionState(
        session_id=session_id,
        goal_id="goal_1",
        status=SessionStatus.PAUSED,
        timestamps=SessionTimestamps(started_at=now, updated_at=now, paused_at_time=now),
        memory={"k": "v"},
    )
    _write_state(tmp_path, state)

    list_args = argparse.Namespace(
        agent_path="exports/my_agent",
        storage_path=str(tmp_path),
        status="all",
        has_checkpoints=False,
        limit=50,
    )
    assert cmd_sessions_list(list_args) == 0
    out = capsys.readouterr().out
    assert session_id in out

    show_args = argparse.Namespace(
        agent_path="exports/my_agent",
        storage_path=str(tmp_path),
        session_id=session_id,
        json=True,
    )
    assert cmd_sessions_show(show_args) == 0
    out = capsys.readouterr().out
    assert session_id in out


def test_sessions_checkpoints_lists_index(tmp_path, capsys) -> None:
    session_id = "session_20260214_130100_def67890"
    now = datetime.now().isoformat()
    state = SessionState(
        session_id=session_id,
        goal_id="goal_1",
        status=SessionStatus.ACTIVE,
        timestamps=SessionTimestamps(started_at=now, updated_at=now),
    )
    _write_state(tmp_path, state)

    checkpoint_id = "cp_node_complete_start_20260214_130101"
    session_dir = tmp_path / "sessions" / session_id
    checkpoints_dir = session_dir / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)

    index = CheckpointIndex(
        session_id=session_id,
        checkpoints=[
            CheckpointSummary(
                checkpoint_id=checkpoint_id,
                checkpoint_type="node_complete",
                created_at=now,
                current_node="start",
                is_clean=True,
                description="Node complete: start",
            )
        ],
        latest_checkpoint_id=checkpoint_id,
        total_checkpoints=1,
    )
    (checkpoints_dir / "index.json").write_text(index.model_dump_json(indent=2), encoding="utf-8")

    args = argparse.Namespace(
        agent_path="exports/my_agent",
        storage_path=str(tmp_path),
        session_id=session_id,
    )
    assert cmd_sessions_checkpoints(args) == 0
    out = capsys.readouterr().out
    assert checkpoint_id in out


def test_load_resume_state_respects_storage_path(tmp_path) -> None:
    session_id = "session_20260214_131000_zzz99999"
    session_dir = tmp_path / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    state = {
        "memory": {"a": 1},
        "progress": {"paused_at": "node_x", "path": ["start", "node_x"], "node_visit_counts": {}},
    }
    (session_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    resume = _load_resume_state(
        agent_path="exports/my_agent",
        session_id=session_id,
        checkpoint_id=None,
        storage_path=str(tmp_path),
    )
    assert resume is not None
    assert resume["paused_at"] == "node_x"
    assert resume["memory"] == {"a": 1}
