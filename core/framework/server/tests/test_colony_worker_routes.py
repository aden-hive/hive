"""Tests for the colony worker inspect-detail route.

Covers ``GET /api/sessions/{id}/workers/{worker_id}`` in
``routes_colony_workers.py`` — the per-worker detail endpoint. (Stop and
stop-all already exist in ``routes_workers.py`` and are tested there.)

The colony runtime and workers are faked: these tests exercise the HTTP
layer, not the real AgentLoop machinery.
"""

import json
from unittest.mock import MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from framework import config as framework_config
from framework.host.worker import WorkerInfo, WorkerStatus
from framework.server.app import create_app
from framework.server.session_manager import Session


class FakeWorker:
    """Minimal stand-in for ``framework.host.worker.Worker``."""

    def __init__(self, wid: str, status: WorkerStatus = WorkerStatus.RUNNING):
        self.id = wid
        self.task = "do a thing"
        self.status = status
        self._started_at = 1000.0
        self._result = None
        self._profile_name = "profile-x"
        self._batch_id = "batch_1"
        self._batch_index = 2
        self._batch_size = 5

    @property
    def info(self) -> WorkerInfo:
        return WorkerInfo(
            id=self.id,
            task=self.task,
            status=self.status,
            started_at=self._started_at,
            result=self._result,
            profile_name=self._profile_name,
            batch_id=self._batch_id,
            batch_index=self._batch_index,
            batch_size=self._batch_size,
        )


class FakeRuntime:
    """Minimal stand-in for ``ColonyRuntime`` exposing the read surface."""

    def __init__(self, workers: list[FakeWorker], colony_id: str = "test_colony"):
        self._workers = {w.id: w for w in workers}
        self.colony_id = colony_id

    def get_worker(self, wid: str):
        return self._workers.get(wid)

    def list_workers(self) -> list[WorkerInfo]:
        return [w.info for w in self._workers.values()]

    async def stop(self) -> None:
        """No-op so session teardown (stop_session) doesn't warn."""


def _app_with(runtime, sid: str = "s1"):
    """Create an aiohttp app with one session bound to ``runtime``."""
    app = create_app()
    session = Session(
        id=sid,
        event_bus=MagicMock(),
        llm=MagicMock(),
        loaded_at=1000.0,
        colony=runtime,
        colony_id=getattr(runtime, "colony_id", None),
    )
    app["manager"]._sessions[sid] = session
    return app


@pytest.mark.asyncio
async def test_inspect_live_worker_includes_batch_and_tasks():
    runtime = FakeRuntime([FakeWorker("w1", WorkerStatus.RUNNING)])
    async with TestClient(TestServer(_app_with(runtime))) as client:
        resp = await client.get("/api/sessions/s1/workers/w1")
        assert resp.status == 200
        worker = (await resp.json())["worker"]
    assert worker["worker_id"] == "w1"
    assert worker["status"] == "running"
    assert worker["batch"] == {
        "batch_id": "batch_1",
        "batch_index": 2,
        "batch_size": 5,
        "worker_seq": 0,
    }
    # No task list was created for this worker.
    assert worker["tasks"] == []
    # No goal was seeded for this worker.
    assert worker["goal"] is None


@pytest.mark.asyncio
async def test_inspect_unknown_worker_returns_404(monkeypatch, tmp_path):
    # Point colony storage at an empty temp dir so the disk fallback misses.
    monkeypatch.setattr(framework_config, "COLONIES_DIR", tmp_path)
    runtime = FakeRuntime([])
    async with TestClient(TestServer(_app_with(runtime))) as client:
        resp = await client.get("/api/sessions/s1/workers/ghost")
        assert resp.status == 404


@pytest.mark.asyncio
async def test_inspect_historical_worker_reads_disk(monkeypatch, tmp_path):
    """A worker pruned from memory is served from its on-disk run dir."""
    monkeypatch.setattr(framework_config, "COLONIES_DIR", tmp_path)
    wdir = tmp_path / "test_colony" / "workers" / "w_old"
    wdir.mkdir(parents=True)
    (wdir / "meta.json").write_text(
        json.dumps(
            {
                "task": "scrape page 7",
                "spawned_at": 1234.0,
                "profile_name": "profile-x",
                "batch_id": "batch_9",
                "batch_index": 1,
                "batch_size": 4,
            }
        )
    )
    (wdir / "result.json").write_text(json.dumps({"status": "success", "summary": "done"}))

    runtime = FakeRuntime([])  # nothing live — forces the disk path
    async with TestClient(TestServer(_app_with(runtime))) as client:
        resp = await client.get("/api/sessions/s1/workers/w_old")
        assert resp.status == 200
        worker = (await resp.json())["worker"]
    assert worker["worker_id"] == "w_old"
    assert worker["status"] == "historical"
    assert worker["task"] == "scrape page 7"
    assert worker["result"] == {"status": "success", "summary": "done"}
    assert worker["batch"]["batch_id"] == "batch_9"


def _write_parts(parts_dir, parts):
    """Write conversation part files (zero-padded ``<seq>.json``)."""
    parts_dir.mkdir(parents=True)
    for part in parts:
        (parts_dir / f"{part['seq']:010d}.json").write_text(json.dumps(part))


@pytest.mark.asyncio
async def test_worker_conversation_returns_transcript(monkeypatch, tmp_path):
    """The transcript endpoint serves conversation parts oldest-first,
    flattening each tool call down to its name + arguments."""
    monkeypatch.setattr(framework_config, "COLONIES_DIR", tmp_path)
    parts_dir = tmp_path / "test_colony" / "workers" / "w_conv" / "conversations" / "parts"
    _write_parts(
        parts_dir,
        [
            {"seq": 0, "role": "user", "content": "go scrape page 7"},
            {
                "seq": 1,
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "browser_click", "arguments": '{"sel": "a"}'}}],
            },
            {"seq": 2, "role": "tool", "content": '{"ok": true}', "tool_use_id": "call_1"},
        ],
    )

    runtime = FakeRuntime([])  # nothing live — forces the disk path
    async with TestClient(TestServer(_app_with(runtime))) as client:
        resp = await client.get("/api/sessions/s1/workers/w_conv/conversation")
        assert resp.status == 200
        body = await resp.json()

    assert body["worker_id"] == "w_conv"
    assert body["total"] == 3
    assert body["truncated"] is False
    # Ordered by seq; the tool call is flattened to {name, arguments}.
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "tool"]
    assert body["messages"][1]["tool_calls"] == [{"name": "browser_click", "arguments": '{"sel": "a"}'}]
    assert body["messages"][2]["tool_use_id"] == "call_1"


@pytest.mark.asyncio
async def test_worker_conversation_unknown_returns_404(monkeypatch, tmp_path):
    monkeypatch.setattr(framework_config, "COLONIES_DIR", tmp_path)
    runtime = FakeRuntime([])
    async with TestClient(TestServer(_app_with(runtime))) as client:
        resp = await client.get("/api/sessions/s1/workers/ghost/conversation")
        assert resp.status == 404


@pytest.mark.asyncio
async def test_inspect_live_worker_surfaces_seeded_goal_and_tasks(monkeypatch, tmp_path):
    """WHY: the queen seeds `goal` (TaskStore.set_goal) and the worker writes
    its task list — BOTH keyed by the BARE worker_id. The detail route must
    read that key: the old ``session:<id>:<id>`` composite resolved to the
    empty _misc/ sandbox, so tasks (and now goal) silently vanished from the
    UI even though tasks.json existed on disk."""
    from framework.tasks import store as store_mod
    from framework.tasks.store import TaskStore

    # Worker task lists resolve via session_storage_dir under hive_root —
    # give the singleton a temp root with the worker's canonical dir.
    (tmp_path / "colonies" / "test_colony" / "workers" / "w1").mkdir(parents=True)
    test_store = TaskStore(hive_root=tmp_path)
    monkeypatch.setattr(store_mod, "_default_store", test_store)

    await test_store.set_goal("w1", "Checking 6 Instagram profiles")
    await test_store.create_tasks_batch("w1", [{"subject": "triage"}])

    runtime = FakeRuntime([FakeWorker("w1", WorkerStatus.RUNNING)])
    async with TestClient(TestServer(_app_with(runtime))) as client:
        resp = await client.get("/api/sessions/s1/workers/w1")
        assert resp.status == 200
        worker = (await resp.json())["worker"]

    assert worker["goal"] == "Checking 6 Instagram profiles"
    assert [t["subject"] for t in worker["tasks"]] == ["triage"]


@pytest.mark.asyncio
async def test_completed_in_memory_worker_keeps_goal_in_list(monkeypatch, tmp_path):
    """WHY: runtime._workers is not pruned on termination, so a COMPLETED
    worker keeps being served from the in-memory path (whose WorkerInfo has
    no goal) while its id suppresses the disk walk that would have read
    meta.json. If the list route only fetched goals for active statuses,
    a card's title regressed to the raw task prompt at the exact moment
    its worker finished."""
    from framework.tasks import store as store_mod
    from framework.tasks.store import TaskStore

    (tmp_path / "colonies" / "test_colony" / "workers" / "w_done").mkdir(parents=True)
    test_store = TaskStore(hive_root=tmp_path)
    monkeypatch.setattr(store_mod, "_default_store", test_store)
    await test_store.set_goal("w_done", "Reviewing 6 Instagram leads")

    runtime = FakeRuntime([FakeWorker("w_done", WorkerStatus.COMPLETED)])
    async with TestClient(TestServer(_app_with(runtime))) as client:
        resp = await client.get("/api/sessions/s1/workers")
        assert resp.status == 200
        workers = (await resp.json())["workers"]

    assert len(workers) == 1
    assert workers[0]["status"] == "completed"
    assert workers[0]["goal"] == "Reviewing 6 Instagram leads"
    # Completed workers still have no task_summary — only actives are counted.
    assert workers[0].get("task_summary") is None
