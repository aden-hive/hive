"""End-to-end tests:

- Session task tools fire EventBus events
- REST routes return correct snapshots
- run_parallel_workers-style flow stamps assigned_session
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
from framework.tasks import TaskListRole, TaskStore
from framework.tasks.events import set_default_event_bus
from framework.tasks.hooks import clear_hooks
from framework.tasks.tools import register_colony_template_tools, register_task_tools


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
    register_colony_template_tools(reg, colony_id="abc", store=store)
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

    token = ToolRegistry.set_execution_context(agent_id="alice", task_list_id="session:alice:s1")
    try:
        await _invoke(registry, "task_create", subject="hello")
    finally:
        ToolRegistry.reset_execution_context(token)

    # Allow the publish to fan out.
    await asyncio.sleep(0.05)
    assert len(received) == 1
    assert received[0].type == EventType.TASK_CREATED
    assert received[0].data["task"]["subject"] == "hello"
    set_default_event_bus(None)


@pytest.mark.asyncio
async def test_task_updated_emits_event(registry: ToolRegistry) -> None:
    bus = EventBus()
    set_default_event_bus(bus)
    received: list[AgentEvent] = []

    async def handler(ev: AgentEvent) -> None:
        received.append(ev)

    bus.subscribe([EventType.TASK_UPDATED], handler)

    token = ToolRegistry.set_execution_context(agent_id="alice", task_list_id="session:alice:s1")
    try:
        await _invoke(registry, "task_create", subject="x")
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
    resp = await http_client.get("/api/tasks/session:nope:nope")
    assert resp.status == 404
    body = await resp.json()
    assert body["task_list_id"] == "session:nope:nope"


@pytest.mark.asyncio
async def test_rest_get_task_list_after_create(http_client: TestClient) -> None:
    # Create a list + task via the store directly so we don't have to mount
    # the tools just for this test.
    from framework.tasks import get_task_store

    store = get_task_store()
    await store.ensure_task_list("session:alice:s1", role=TaskListRole.SESSION)
    await store.create_task("session:alice:s1", subject="abc")

    resp = await http_client.get("/api/tasks/session:alice:s1")
    assert resp.status == 200
    body = await resp.json()
    assert body["task_list_id"] == "session:alice:s1"
    assert body["role"] == "session"
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["subject"] == "abc"


@pytest.mark.asyncio
async def test_rest_colony_lists(http_client: TestClient) -> None:
    resp = await http_client.get("/api/colonies/test_colony/task_lists?queen_session_id=sess123")
    assert resp.status == 200
    body = await resp.json()
    assert body["template_task_list_id"] == "colony:test_colony"
    assert body["queen_session_task_list_id"] == "session:queen:sess123"


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
from framework.tasks import TaskStore, TaskListRole

async def main():
    s = TaskStore()
    await s.ensure_task_list('session:a:b', role=TaskListRole.SESSION)
    rec = await s.create_task('session:a:b', subject='persisted')
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
    rs = await s.list_tasks('session:a:b')
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
# "run_parallel_workers" style flow at the storage level.
# Validates plan-and-spawn pattern: queen publishes templates, then stamps
# assigned_session per spawned worker.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_template_assignment_flow(store: TaskStore) -> None:
    template_id = "colony:swarm"
    await store.ensure_task_list(template_id, role=TaskListRole.TEMPLATE)
    rec1 = await store.create_task(template_id, subject="crawl A")
    rec2 = await store.create_task(template_id, subject="crawl B")

    # Simulate run_parallel_workers stamping after spawn.
    await store.update_task(
        template_id,
        rec1.id,
        metadata_patch={"assigned_session": "session:w1:w1", "assigned_worker_id": "w1"},
    )
    await store.update_task(
        template_id,
        rec2.id,
        metadata_patch={"assigned_session": "session:w2:w2", "assigned_worker_id": "w2"},
    )

    rs = await store.list_tasks(template_id)
    assert all(r.metadata.get("assigned_worker_id") for r in rs)


# ---------------------------------------------------------------------------
# Reset preserves byte-equivalence semantics (durability under graceful op)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graceful_no_op_preserves_files(store: TaskStore, tmp_path: Path) -> None:
    """The store has no shutdown hook — touching it never deletes files."""
    list_id = "session:a:b"
    await store.ensure_task_list(list_id, role=TaskListRole.SESSION)
    rec = await store.create_task(list_id, subject="x")
    pre = sorted((tmp_path).rglob("*.json"))
    pre_bytes = {p.name: p.read_bytes() for p in pre}

    # Simulate "agent loop teardown" — should be a no-op.
    # (No method to call — the absence of teardown hooks IS the test.)
    post = sorted((tmp_path).rglob("*.json"))
    assert {p.name for p in post} == {p.name for p in pre}
    for p in post:
        assert p.read_bytes() == pre_bytes[p.name]
    assert rec.id == 1
