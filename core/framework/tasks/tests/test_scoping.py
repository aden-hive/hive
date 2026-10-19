"""Tests for resolve_task_list_id."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from framework.tasks.scoping import (
    colony_task_list_id,
    parse_task_list_id,
    resolve_task_list_id,
    session_task_list_id,
)


@dataclass
class FakeCtx:
    agent_id: str = ""
    run_id: str = ""
    execution_id: str = ""
    stream_id: str = ""
    task_list_id: str | None = None


def test_session_helper() -> None:
    assert session_task_list_id("a", "b") == "session:a:b"


def test_colony_helper() -> None:
    assert colony_task_list_id("c") == "colony:c"


def test_parse_session() -> None:
    parts = parse_task_list_id("session:agent:sess")
    assert parts == {"kind": "session", "agent_id": "agent", "session_id": "sess"}


def test_parse_colony() -> None:
    parts = parse_task_list_id("colony:abc")
    assert parts == {"kind": "colony", "colony_id": "abc"}


def test_resolve_uses_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HIVE_TASK_LIST_ID", raising=False)
    ctx = FakeCtx(agent_id="x", run_id="r1", task_list_id="session:x:r1")
    assert resolve_task_list_id(ctx) == "session:x:r1"


def test_resolve_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIVE_TASK_LIST_ID", "forced")
    ctx = FakeCtx(agent_id="x", run_id="r1")
    assert resolve_task_list_id(ctx) == "forced"


def test_resolve_synthesizes_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HIVE_TASK_LIST_ID", raising=False)
    ctx = FakeCtx(agent_id="alice", run_id="r123")
    assert resolve_task_list_id(ctx) == "session:alice:r123"


def test_resolve_falls_back_to_unscoped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HIVE_TASK_LIST_ID", raising=False)
    ctx = FakeCtx(agent_id="alice")
    assert resolve_task_list_id(ctx).startswith("unscoped:")
