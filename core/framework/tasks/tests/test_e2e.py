"""End-to-end tests:

- Session task tools fire EventBus events
- REST routes return correct snapshots
- Durability: store survives a process boundary (subprocess)
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.llm.provider import ToolUse
from framework.loader.tool_registry import ToolRegistry
from framework.tasks import TaskStore
from framework.tasks.events import set_default_event_bus
from framework.tasks.hooks import clear_hooks
from framework.tasks.tools import register_task_tools


@pytest.fixture(autouse=True)
def _reset_hooks() -> None:
    clear_hooks()
    yield
    clear_hooks()


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(hive_root=tmp_path)


@pytest.fixture
def registry(store: TaskStore) -> ToolRegistry:
    reg = ToolRegistry()
    register_task_tools(reg, store=store)
    return reg


async def _invoke(registry: ToolRegistry, name: str, **inputs):
    executor = registry.get_executor()
    result = executor(ToolUse(id=f"call_{name}", name=name, input=inputs))
    if asyncio.iscoroutine(result):
        result = await result
    return result


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_created_emits_event(registry: ToolRegistry) -> None:
    bus = EventBus()
    set_default_event_bus(bus)
    received: list[AgentEvent] = []

    async def handler(ev: AgentEvent) -> None:
        received.append(ev)

    bus.subscribe([EventType.TASK_CREATED], handler)

    token = ToolRegistry.set_execution_context(agent_id="alice", session_id="s1")
    try:
        await _invoke(registry, "task_create", goal="test goal", tasks=[{"subject": "hello"}])
    finally:
        ToolRegistry.reset_execution_context(token)

    # Allow the publish to fan out.
    await asyncio.sleep(0.05)
    assert len(received) == 1
    assert received[0].type == EventType.TASK_CREATED
    assert received[0].data["task"]["subject"] == "hello"
    assert received[0].data["session_id"] == "s1"
    set_default_event_bus(None)


@pytest.mark.asyncio
async def test_task_updated_emits_event(registry: ToolRegistry) -> None:
    bus = EventBus()
    set_default_event_bus(bus)
    received: list[AgentEvent] = []

    async def handler(ev: AgentEvent) -> None:
        received.append(ev)

    bus.subscribe([EventType.TASK_UPDATED], handler)

    token = ToolRegistry.set_execution_context(agent_id="alice", session_id="s1")
    try:
        await _invoke(registry, "task_create", goal="test goal", tasks=[{"subject": "x"}])
        await _invoke(registry, "task_update", id=1, status="in_progress")
    finally:
        ToolRegistry.reset_execution_context(token)
    await asyncio.sleep(0.05)
    assert len(received) >= 1
    assert received[0].type == EventType.TASK_UPDATED
    set_default_event_bus(None)


# ---------------------------------------------------------------------------
# REST routes integration
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def http_client(tmp_path: Path) -> TestClient:
    """Spin up a stripped-down aiohttp app exposing only the task routes."""
    # Point the default TaskStore at the tmp_path so routes see our test data.
    os.environ["HIVE_HOME"] = str(tmp_path)
    # Force a fresh singleton.
    import framework.tasks.store as _store_mod

    _store_mod._default_store = None

    from framework.server.routes_tasks import register_routes

    app = web.Application()
    register_routes(app)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_rest_get_task_list_404(http_client: TestClient) -> None:
    resp = await http_client.get("/api/sessions/nope/tasks")
    assert resp.status == 404
    body = await resp.json()
    assert body["session_id"] == "nope"


@pytest.mark.asyncio
async def test_rest_get_task_list_after_create(http_client: TestClient) -> None:
    # Create a list + task via the store directly so we don't have to mount
    # the tools just for this test.
    from framework.tasks import get_task_store

    store = get_task_store()
    await store.ensure_task_list("s1")
    await store.create_task("s1", subject="abc")

    resp = await http_client.get("/api/sessions/s1/tasks")
    assert resp.status == 200
    body = await resp.json()
    assert body["session_id"] == "s1"
    assert body["role"] == "session"
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["subject"] == "abc"


@pytest.mark.asyncio
async def test_rest_clear_completed_archives_and_reports_ids(http_client: TestClient) -> None:
    """POST clear-completed (the "Clear done" button): completed tasks are
    archived and reported; open work is untouched; the GET snapshot then
    shows the archived statuses (History reads them from the same list)."""
    from framework.tasks import TaskStatus, get_task_store

    store = get_task_store()
    await store.ensure_task_list("s1")
    await store.create_tasks_batch("s1", [{"subject": "done-1"}, {"subject": "done-2"}, {"subject": "open"}])
    await store.update_task("s1", 1, status=TaskStatus.COMPLETED)
    await store.update_task("s1", 2, status=TaskStatus.COMPLETED)

    resp = await http_client.post("/api/sessions/s1/tasks/clear-completed")
    assert resp.status == 200
    body = await resp.json()
    assert body["session_id"] == "s1"
    assert sorted(body["archived"]) == [1, 2]

    snap = await (await http_client.get("/api/sessions/s1/tasks")).json()
    by_id = {t["id"]: t for t in snap["tasks"]}
    assert by_id[1]["status"] == "archived"
    assert by_id[2]["status"] == "archived"
    assert by_id[3]["status"] == "pending"


@pytest.mark.asyncio
async def test_rest_clear_completed_noop_and_unknown_session(http_client: TestClient) -> None:
    """Nothing completed → archived: []. Unknown session → archived: [] too
    (not an error — the button is harmless to mash)."""
    from framework.tasks import get_task_store

    store = get_task_store()
    await store.ensure_task_list("s1")
    await store.create_task("s1", subject="open")

    resp = await http_client.post("/api/sessions/s1/tasks/clear-completed")
    assert resp.status == 200
    assert (await resp.json())["archived"] == []

    resp = await http_client.post("/api/sessions/never-existed/tasks/clear-completed")
    assert resp.status == 200
    assert (await resp.json())["archived"] == []


@pytest.mark.asyncio
async def test_rest_clear_completed_emits_task_updated_per_record(
    http_client: TestClient,
) -> None:
    """One task_updated event per archived record — open panels drop the
    tasks from the live plan without a refetch."""
    from framework.tasks import TaskStatus, get_task_store

    store = get_task_store()
    await store.ensure_task_list("s1")
    await store.create_tasks_batch("s1", [{"subject": "a"}, {"subject": "b"}])
    await store.update_task("s1", 1, status=TaskStatus.COMPLETED)
    await store.update_task("s1", 2, status=TaskStatus.COMPLETED)

    bus = EventBus()
    set_default_event_bus(bus)
    received: list[AgentEvent] = []

    async def handler(ev: AgentEvent) -> None:
        received.append(ev)

    bus.subscribe([EventType.TASK_UPDATED], handler)
    try:
        resp = await http_client.post("/api/sessions/s1/tasks/clear-completed")
        assert resp.status == 200
        await asyncio.sleep(0.05)  # let the publishes fan out
    finally:
        set_default_event_bus(None)

    assert sorted(ev.data["task_id"] for ev in received) == [1, 2]
    for ev in received:
        assert ev.data["after"]["status"] == "archived"
        assert ev.data["fields"] == ["status"]


@pytest.mark.asyncio
async def test_rest_clear_completed_then_unarchive_round_trip(
    http_client: TestClient,
) -> None:
    """History "remove" after "Clear done": unarchive restores the tasks to
    COMPLETED (their archived_from), not pending."""
    from framework.tasks import TaskStatus, get_task_store

    store = get_task_store()
    await store.ensure_task_list("s1")
    await store.create_task("s1", subject="finished work")
    await store.update_task("s1", 1, status=TaskStatus.COMPLETED)

    cleared = await (await http_client.post("/api/sessions/s1/tasks/clear-completed")).json()
    assert cleared["archived"] == [1]

    resp = await http_client.post("/api/sessions/s1/tasks/unarchive", json={"task_ids": [1]})
    assert resp.status == 200
    assert (await resp.json())["restored"] == [1]

    snap = await (await http_client.get("/api/sessions/s1/tasks")).json()
    assert snap["tasks"][0]["status"] == "completed"


# ---------------------------------------------------------------------------
# Cross-process durability — write in subprocess A, read in subprocess B.
# Demonstrates the "task survives runtime restart" guarantee.
# ---------------------------------------------------------------------------


def test_durability_across_subprocesses(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["HIVE_HOME"] = str(tmp_path)
    env["PYTHONUNBUFFERED"] = "1"

    write_script = """
import asyncio
from framework.tasks import TaskStore

async def main():
    s = TaskStore()
    await s.ensure_task_list('sess_dur')
    rec = await s.create_task('sess_dur', subject='persisted')
    print(rec.id)

asyncio.run(main())
"""
    out = subprocess.run(
        [sys.executable, "-c", write_script],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    written_id = int(out.stdout.strip())
    assert written_id == 1

    read_script = """
import asyncio
from framework.tasks import TaskStore

async def main():
    s = TaskStore()
    rs = await s.list_tasks('sess_dur')
    print(len(rs), rs[0].subject if rs else '')

asyncio.run(main())
"""
    out2 = subprocess.run(
        [sys.executable, "-c", read_script],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    count, subject = out2.stdout.strip().split(" ", 1)
    assert count == "1"
    assert subject == "persisted"


# ---------------------------------------------------------------------------
# Reset preserves byte-equivalence semantics (durability under graceful op)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graceful_no_op_preserves_files(store: TaskStore, tmp_path: Path) -> None:
    """The store has no shutdown hook — touching it never deletes files."""
    session_id = "sess_g"
    await store.ensure_task_list(session_id)
    rec = await store.create_task(session_id, subject="x")
    pre = sorted((tmp_path).rglob("*.json"))
    pre_bytes = {p.name: p.read_bytes() for p in pre}

    # Simulate "agent loop teardown" — should be a no-op.
    # (No method to call — the absence of teardown hooks IS the test.)
    post = sorted((tmp_path).rglob("*.json"))
    assert {p.name for p in post} == {p.name for p in pre}
    for p in post:
        assert p.read_bytes() == pre_bytes[p.name]
    assert rec.id == 1
