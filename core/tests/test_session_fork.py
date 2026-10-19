"""Forking a queen DM session at a user message."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from framework.server.session_fork import ForkError, fork_session_dir

T1, T2, T3 = "2026-10-17T09:00:00.000001", "2026-10-17T09:05:00.000002", "2026-10-17T09:10:00.000003"


def _event(type_: str, timestamp: str, **extra) -> str:
    return json.dumps({"type": type_, "stream_id": "queen", "timestamp": timestamp, **extra}) + "\n"


def _make_session(queens_dir: Path, sid: str = "session_20261017_090000_aaaa1111") -> Path:
    """Three exchanges: user messages at seq 0, 2, 4; queen replies at 1, 3, 5."""
    d = queens_dir / "queen_x" / "sessions" / sid
    parts = d / "conversations" / "parts"
    parts.mkdir(parents=True)
    for seq in range(6):
        role = "user" if seq % 2 == 0 else "assistant"
        (parts / f"{seq:010d}.json").write_text(json.dumps({"seq": seq, "role": role, "content": f"m{seq}"}))
    (d / "conversations" / "meta.json").write_text(json.dumps({"system_prompt": "you are x"}))
    (d / "conversations" / "cursor.json").write_text(
        json.dumps(
            {
                "next_seq": 6,
                "iteration": 9,
                "recent_responses": ["m5"],
                "pending_input": {"reason": "ask_user", "questions": [{"id": "q"}]},
            }
        )
    )
    log = ""
    for n, (ts, seq) in enumerate(((T1, 0), (T2, 2), (T3, 4))):
        log += _event("client_input_received", ts, correlation_id=f"c{n}", data={"content": f"ask {n}"})
        log += _event("client_input_committed", ts, correlation_id=f"c{n}", data={"seq": seq})
        log += _event("client_output_delta", ts, data={"snapshot": f"reply {n}", "iteration": n})
    (d / "events.jsonl").write_text(log)
    (d / "meta.json").write_text(json.dumps({"queen_id": "queen_x", "phase": "independent", "title": "Trip plan", "superseded_by": "session_z"}))
    (d / "data" / "attachments").mkdir(parents=True)
    (d / "data" / "attachments" / "photo.png").write_bytes(b"png")
    (d / "tasks.json").write_text("[]")
    return d


def test_fork_before_a_message_keeps_only_what_came_before_it(tmp_path):
    src = _make_session(tmp_path)

    dst = fork_session_dir(src, "session_20261017_100000_bbbb2222", before_input_at=T2)

    parts = sorted(p.name for p in (dst / "conversations" / "parts").iterdir())
    assert parts == ["0000000000.json", "0000000001.json"]
    events = [json.loads(line) for line in (dst / "events.jsonl").read_text().splitlines()]
    assert [e["type"] for e in events] == ["client_input_received", "client_input_committed", "client_output_delta"]
    cursor = json.loads((dst / "conversations" / "cursor.json").read_text())
    assert cursor["next_seq"] == 2
    assert cursor["iteration"] == 9
    assert cursor["recent_responses"] == []
    assert cursor["pending_input"]["reason"] == "turn_done"


def test_fork_carries_the_session_files_but_not_its_plan_or_fate(tmp_path):
    src = _make_session(tmp_path)

    dst = fork_session_dir(src, "session_20261017_100000_bbbb2222", before_input_at=T3)

    assert (dst / "data" / "attachments" / "photo.png").read_bytes() == b"png"
    assert (dst / "conversations" / "meta.json").exists()
    assert not (dst / "tasks.json").exists()
    meta = json.loads((dst / "meta.json").read_text())
    assert meta["title"] == "Trip plan"
    assert meta["forked_from"] == {"session_id": src.name, "before_input_at": T3}
    assert "superseded_by" not in meta
    # The inherited messages' facts are already in the source's timeline.
    assert json.loads((dst / "timeline_meta.json").read_text())["user_turns"] == 2


def test_fork_without_a_point_copies_the_whole_session(tmp_path):
    src = _make_session(tmp_path)

    dst = fork_session_dir(src, "session_20261017_100000_bbbb2222")

    assert len(list((dst / "conversations" / "parts").iterdir())) == 6
    assert (dst / "events.jsonl").read_text() == (src / "events.jsonl").read_text()
    assert json.loads((dst / "conversations" / "cursor.json").read_text())["next_seq"] == 6


def test_unknown_point_is_refused_and_leaves_nothing_behind(tmp_path):
    src = _make_session(tmp_path)

    with pytest.raises(ForkError, match="No message sent at"):
        fork_session_dir(src, "session_20261017_100000_bbbb2222", before_input_at="2026-01-01T00:00:00")
    assert not (src.parent / "session_20261017_100000_bbbb2222").exists()


def test_point_lost_to_compaction_is_refused(tmp_path):
    src = _make_session(tmp_path)
    (src / "conversations" / "parts" / "0000000002.json").unlink()

    with pytest.raises(ForkError, match="compacted"):
        fork_session_dir(src, "session_20261017_100000_bbbb2222", before_input_at=T2)
    assert not (src.parent / "session_20261017_100000_bbbb2222").exists()


@pytest.mark.asyncio
async def test_fork_route_returns_the_new_session_which_history_lists():
    from framework.server import session_manager
    from framework.server.app import create_app

    src = _make_session(session_manager.QUEENS_DIR)
    async with TestClient(TestServer(create_app())) as client:
        resp = await client.post(f"/api/sessions/{src.name}/fork", json={"before_input_at": T2})
        created = await resp.json()
        history = await (await client.get("/api/sessions/history")).json()

    assert resp.status == 201
    assert created["queen_id"] == "queen_x"
    listed = {s["session_id"]: s for s in history["sessions"]}
    assert listed[created["session_id"]]["forked_from"] == src.name
    assert listed[created["session_id"]]["title"] == "Trip plan"


@pytest.mark.asyncio
async def test_fork_route_rejects_an_unknown_session():
    from framework.server.app import create_app

    async with TestClient(TestServer(create_app())) as client:
        resp = await client.post("/api/sessions/session_20990101_000000_deadbeef/fork", json={})

    assert resp.status == 404
