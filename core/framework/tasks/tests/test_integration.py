"""Integration tests that wire multiple subsystems together.

Verifies that each agent session operates on its own session list and that
sessions stay isolated from one another.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from framework.llm.provider import ToolUse
from framework.loader.tool_registry import ToolRegistry
from framework.tasks import TaskStore
from framework.tasks.hooks import clear_hooks
from framework.tasks.tools import register_task_tools


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
async def test_session_tools_write_to_own_session_list(tmp_path: Path) -> None:
    """The four session tools operate exclusively on the caller's session list.

    Even when colony_id is set in execution context, task_create writes to
    the agent's own session list.
    """
    store = TaskStore(hive_root=tmp_path)
    reg = ToolRegistry()
    register_task_tools(reg, store=store)

    token = ToolRegistry.set_execution_context(
        agent_id="alice",
        session_id="sess1",
        colony_id="alpha",  # colony_id set, but tasks still go to the session list
    )
    try:
        await _invoke(reg, "task_create", goal="test goal", tasks=[{"subject": "my work"}])
    finally:
        ToolRegistry.reset_execution_context(token)

    session_tasks = await store.list_tasks("sess1")
    assert len(session_tasks) == 1
    assert session_tasks[0].subject == "my work"


@pytest.mark.asyncio
async def test_workers_have_independent_session_lists(tmp_path: Path) -> None:
    """Each worker writes to its own session list with no cross-talk."""
    store = TaskStore(hive_root=tmp_path)
    worker_ids = ["w1", "w2", "w3"]
    for wid in worker_ids:
        worker_reg = ToolRegistry()
        register_task_tools(worker_reg, store=store)
        # Worker convention: session_id == worker_id.
        wtoken = ToolRegistry.set_execution_context(agent_id=wid, session_id=wid)
        try:
            await _invoke(worker_reg, "task_create", goal=f"goal for {wid}", tasks=[{"subject": f"setup for {wid}"}])
            await _invoke(worker_reg, "task_update", id=1, status="in_progress")
        finally:
            ToolRegistry.reset_execution_context(wtoken)

    for wid in worker_ids:
        worker_tasks = await store.list_tasks(wid)
        assert len(worker_tasks) == 1
        assert worker_tasks[0].owner == wid  # auto-stamped on in_progress
        assert worker_tasks[0].subject == f"setup for {wid}"


@pytest.mark.asyncio
async def test_resume_persisted_handle(tmp_path: Path) -> None:
    """A session list created in 'session A' is still readable as long as
    we resolve to the same session_id."""
    store = TaskStore(hive_root=tmp_path)
    session_id = "sess_persistent"

    await store.ensure_task_list(session_id)
    await store.create_task(session_id, subject="a")
    await store.create_task(session_id, subject="b")

    # Simulate a fresh process / "resume" — same hive_root, same session_id.
    store2 = TaskStore(hive_root=tmp_path)
    rs = await store2.list_tasks(session_id)
    assert [t.subject for t in rs] == ["a", "b"]
