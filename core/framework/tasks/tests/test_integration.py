"""Integration tests that wire multiple subsystems together.

Verifies the plan-and-spawn pattern end-to-end:
  - Queen authors colony template entries (via colony_template_add)
  - "spawn" stamps assigned_session metadata + emits the right event
  - Workers operate on their own session list (no fall-through)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.llm.provider import ToolUse
from framework.loader.tool_registry import ToolRegistry
from framework.tasks import TaskListRole, TaskStore
from framework.tasks.events import (
    emit_colony_template_assignment,
    set_default_event_bus,
)
from framework.tasks.hooks import clear_hooks
from framework.tasks.scoping import (
    colony_task_list_id,
    session_task_list_id,
)
from framework.tasks.tools import register_colony_template_tools, register_task_tools


@pytest.fixture(autouse=True)
def _reset_hooks() -> None:
    clear_hooks()
    yield
    clear_hooks()


async def _invoke(reg: ToolRegistry, name: str, **inputs):
    executor = reg.get_executor()
    result = executor(ToolUse(id=f"call_{name}", name=name, input=inputs))
    if asyncio.iscoroutine(result):
        result = await result
    return result


@pytest.mark.asyncio
async def test_queen_plans_workers_pick_up(tmp_path: Path) -> None:
    """Queen authors a 3-step plan; we simulate spawning 3 workers, each
    associated with one template entry. Each worker writes to its own
    session list. The colony template gets stamped with assigned_session.
    """
    bus = EventBus()
    set_default_event_bus(bus)
    received: list[AgentEvent] = []

    async def handler(ev: AgentEvent) -> None:
        received.append(ev)

    bus.subscribe(
        [
            EventType.TASK_CREATED,
            EventType.TASK_UPDATED,
            EventType.COLONY_TEMPLATE_ASSIGNMENT,
        ],
        handler,
    )

    store = TaskStore(hive_root=tmp_path)
    queen_reg = ToolRegistry()
    register_task_tools(queen_reg, store=store)
    register_colony_template_tools(queen_reg, colony_id="alpha", store=store)

    # 1. Queen authors the plan.
    qtoken = ToolRegistry.set_execution_context(
        agent_id="queen",
        task_list_id=session_task_list_id("queen", "qsess"),
        colony_id="alpha",
    )
    try:
        for subject in ("crawl A", "crawl B", "crawl C"):
            r = await _invoke(queen_reg, "colony_template_add", subject=subject)
            assert json.loads(r.content)["success"] is True

        # Verify the colony template now has 3 entries.
        list_result = await _invoke(queen_reg, "colony_template_list")
        body = json.loads(list_result.content)
        assert body["count"] == 3
        template_entries = body["tasks"]
    finally:
        ToolRegistry.reset_execution_context(qtoken)

    template_list_id = colony_task_list_id("alpha")

    # 2. Simulate spawning a worker per template entry: stamp the
    #    assigned_session and emit the assignment event.
    worker_ids = ["w1", "w2", "w3"]
    for entry, wid in zip(template_entries, worker_ids, strict=True):
        await store.update_task(
            template_list_id,
            entry["id"],
            metadata_patch={
                "assigned_session": session_task_list_id(wid, wid),
                "assigned_worker_id": wid,
            },
        )
        await emit_colony_template_assignment(
            colony_id="alpha",
            task_id=entry["id"],
            assigned_session=session_task_list_id(wid, wid),
            assigned_worker_id=wid,
        )

    # 3. Each worker operates on its OWN session list.
    for wid in worker_ids:
        worker_reg = ToolRegistry()
        register_task_tools(worker_reg, store=store)
        wtoken = ToolRegistry.set_execution_context(agent_id=wid, task_list_id=session_task_list_id(wid, wid))
        try:
            await _invoke(worker_reg, "task_create", subject=f"setup for {wid}")
            await _invoke(worker_reg, "task_update", id=1, status="in_progress")
        finally:
            ToolRegistry.reset_execution_context(wtoken)

    # 4. Verify the colony template entries are stamped + workers have
    #    their own private lists.
    template_after = await store.list_tasks(template_list_id)
    assert all(t.metadata.get("assigned_worker_id") in {"w1", "w2", "w3"} for t in template_after)

    for wid in worker_ids:
        worker_tasks = await store.list_tasks(session_task_list_id(wid, wid))
        assert len(worker_tasks) == 1
        assert worker_tasks[0].owner == wid  # auto-stamped on in_progress
        assert worker_tasks[0].subject == f"setup for {wid}"

    # 5. Confirm the assignment events fired.
    await asyncio.sleep(0.05)
    assignments = [e for e in received if e.type == EventType.COLONY_TEMPLATE_ASSIGNMENT]
    assert len(assignments) == 3

    set_default_event_bus(None)


@pytest.mark.asyncio
async def test_session_tools_never_touch_template(tmp_path: Path) -> None:
    """The four session tools must operate exclusively on the session list.

    Even when colony_id is set in execution context, task_create writes to
    session list, not the template.
    """
    store = TaskStore(hive_root=tmp_path)
    reg = ToolRegistry()
    register_task_tools(reg, store=store)

    token = ToolRegistry.set_execution_context(
        agent_id="alice",
        task_list_id=session_task_list_id("alice", "sess1"),
        colony_id="alpha",  # has colony_id but we still write to session
    )
    try:
        await _invoke(reg, "task_create", subject="my work")
    finally:
        ToolRegistry.reset_execution_context(token)

    # Session list got the task.
    session_tasks = await store.list_tasks(session_task_list_id("alice", "sess1"))
    assert len(session_tasks) == 1

    # Colony template MUST be empty (no leakage).
    assert not await store.list_exists(colony_task_list_id("alpha"))


@pytest.mark.asyncio
async def test_resume_persisted_handle(tmp_path: Path) -> None:
    """A session list created in 'session A' is still readable as long as
    we resolve to the same task_list_id."""
    store = TaskStore(hive_root=tmp_path)
    list_id = session_task_list_id("alice", "sess_persistent")

    await store.ensure_task_list(list_id, role=TaskListRole.SESSION)
    await store.create_task(list_id, subject="a")
    await store.create_task(list_id, subject="b")

    # Simulate a fresh process / "resume" — same hive_root, same list_id.
    store2 = TaskStore(hive_root=tmp_path)
    rs = await store2.list_tasks(list_id)
    assert [t.subject for t in rs] == ["a", "b"]
