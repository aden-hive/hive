"""End-to-end tool tests via ToolRegistry.get_executor()."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from framework.llm.provider import ToolUse
from framework.loader.tool_registry import ToolRegistry
from framework.tasks import TaskStore
from framework.tasks.hooks import (
    HOOK_TASK_COMPLETED,
    HOOK_TASK_CREATED,
    BlockingHookError,
    clear_hooks,
    register_hook,
)
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
def registry_with_session_tools(store: TaskStore) -> ToolRegistry:
    reg = ToolRegistry()
    register_task_tools(reg, store=store)
    return reg


async def _invoke(registry: ToolRegistry, name: str, **inputs):
    """Invoke a tool via the registry's executor protocol."""
    executor = registry.get_executor()
    result = executor(ToolUse(id=f"call_{name}", name=name, input=inputs))
    if asyncio.iscoroutine(result):
        result = await result
    return result


def _set_ctx(*, agent_id: str, task_list_id: str, **extra):
    return ToolRegistry.set_execution_context(agent_id=agent_id, task_list_id=task_list_id, **extra)


# ---------------------------------------------------------------------------
# Session tools — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_then_list(registry_with_session_tools: ToolRegistry) -> None:
    reg = registry_with_session_tools
    list_id = "session:agent_a:sess_1"
    token = _set_ctx(agent_id="agent_a", task_list_id=list_id)
    try:
        result = await _invoke(reg, "task_create", subject="Plan retrieval")
        assert result.is_error is False
        body = json.loads(result.content)
        assert body["success"] is True
        assert body["task_id"] == 1

        result2 = await _invoke(reg, "task_list")
        body2 = json.loads(result2.content)
        assert body2["count"] == 1
        assert body2["tasks"][0]["subject"] == "Plan retrieval"
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_update_in_progress_auto_owner(
    registry_with_session_tools: ToolRegistry,
) -> None:
    reg = registry_with_session_tools
    list_id = "session:agent_a:sess_1"
    token = _set_ctx(agent_id="agent_a", task_list_id=list_id)
    try:
        await _invoke(reg, "task_create", subject="x")
        result = await _invoke(reg, "task_update", id=1, status="in_progress")
        body = json.loads(result.content)
        assert body["success"] is True
        assert body["task"]["status"] == "in_progress"
        assert body["task"]["owner"] == "agent_a"  # auto-filled
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_update_status_deleted(
    registry_with_session_tools: ToolRegistry,
) -> None:
    reg = registry_with_session_tools
    list_id = "session:agent_a:sess_1"
    token = _set_ctx(agent_id="agent_a", task_list_id=list_id)
    try:
        await _invoke(reg, "task_create", subject="x")
        result = await _invoke(reg, "task_update", id=1, status="deleted")
        body = json.loads(result.content)
        assert body["success"] is True
        assert body["deleted"] is True
        # Subsequent list sees nothing.
        body2 = json.loads((await _invoke(reg, "task_list")).content)
        assert body2["count"] == 0
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_get_returns_full_record(
    registry_with_session_tools: ToolRegistry,
) -> None:
    reg = registry_with_session_tools
    list_id = "session:agent_a:sess_1"
    token = _set_ctx(agent_id="agent_a", task_list_id=list_id)
    try:
        await _invoke(reg, "task_create", subject="x", description="full body")
        result = await _invoke(reg, "task_get", id=1)
        body = json.loads(result.content)
        assert body["task"]["description"] == "full body"
    finally:
        ToolRegistry.reset_execution_context(token)


# ---------------------------------------------------------------------------
# Task-not-found is non-error (so sibling tool cancellation doesn't cascade)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_not_found_is_not_error(
    registry_with_session_tools: ToolRegistry,
) -> None:
    reg = registry_with_session_tools
    list_id = "session:agent_a:sess_1"
    token = _set_ctx(agent_id="agent_a", task_list_id=list_id)
    try:
        result = await _invoke(reg, "task_update", id=42, subject="ghost")
        # is_error must be False so the streaming executor doesn't cascade-cancel.
        assert result.is_error is False
        body = json.loads(result.content)
        assert body["success"] is False
    finally:
        ToolRegistry.reset_execution_context(token)


# ---------------------------------------------------------------------------
# Hooks: task_created blocking deletes the just-created task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completion_suffix_points_to_next_pending(
    registry_with_session_tools: ToolRegistry,
) -> None:
    """When a task is marked completed, the result should point at the
    lowest-id pending task as a steering nudge."""
    reg = registry_with_session_tools
    list_id = "session:agent_a:sess_1"
    token = _set_ctx(agent_id="agent_a", task_list_id=list_id)
    try:
        await _invoke(reg, "task_create", subject="step 1")
        await _invoke(reg, "task_create", subject="step 2")
        await _invoke(reg, "task_create", subject="step 3")
        await _invoke(reg, "task_update", id=1, status="in_progress")
        result = await _invoke(reg, "task_update", id=1, status="completed")
        body = json.loads(result.content)
        assert body["success"] is True
        assert "Next pending: #2" in body["message"]
        assert "step 2" in body["message"]
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_completion_suffix_signals_all_done(
    registry_with_session_tools: ToolRegistry,
) -> None:
    reg = registry_with_session_tools
    list_id = "session:agent_a:sess_1"
    token = _set_ctx(agent_id="agent_a", task_list_id=list_id)
    try:
        await _invoke(reg, "task_create", subject="only step")
        await _invoke(reg, "task_update", id=1, status="in_progress")
        result = await _invoke(reg, "task_update", id=1, status="completed")
        body = json.loads(result.content)
        assert "All tasks complete" in body["message"]
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_completion_suffix_skips_blocked_pending(
    registry_with_session_tools: ToolRegistry,
) -> None:
    """If the only pending task is blocked, the suffix should not point at
    it — fall through to "all done" or note in-progress siblings."""
    reg = registry_with_session_tools
    list_id = "session:agent_a:sess_1"
    token = _set_ctx(agent_id="agent_a", task_list_id=list_id)
    try:
        await _invoke(reg, "task_create", subject="prereq")
        await _invoke(reg, "task_create", subject="blocked dep")
        # #2 is blocked by #1.
        await _invoke(reg, "task_update", id=2, add_blocked_by=[1])
        await _invoke(reg, "task_update", id=1, status="in_progress")
        # Don't actually complete #1 — instead add an unrelated done.
        await _invoke(reg, "task_create", subject="extra step")
        await _invoke(reg, "task_update", id=3, status="in_progress")
        result = await _invoke(reg, "task_update", id=3, status="completed")
        body = json.loads(result.content)
        # #2 is still blocked by uncompleted #1, so the suffix shouldn't
        # surface it. #1 is in_progress, so the suffix highlights that.
        assert "Still in progress: #1" in body["message"]
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_hook_blocks_task_created(
    registry_with_session_tools: ToolRegistry,
) -> None:
    reg = registry_with_session_tools
    list_id = "session:agent_a:sess_1"

    def blocker(ctx) -> None:
        raise BlockingHookError("test policy")

    register_hook(HOOK_TASK_CREATED, blocker)
    token = _set_ctx(agent_id="agent_a", task_list_id=list_id)
    try:
        result = await _invoke(reg, "task_create", subject="will be aborted")
        body = json.loads(result.content)
        assert body["success"] is False
        # The task must have been rolled back.
        body2 = json.loads((await _invoke(reg, "task_list")).content)
        assert body2["count"] == 0
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_hook_blocks_task_completed(
    registry_with_session_tools: ToolRegistry,
) -> None:
    reg = registry_with_session_tools
    list_id = "session:agent_a:sess_1"

    register_hook(HOOK_TASK_COMPLETED, lambda ctx: (_ for _ in ()).throw(BlockingHookError("nope")))
    token = _set_ctx(agent_id="agent_a", task_list_id=list_id)
    try:
        await _invoke(reg, "task_create", subject="x")
        await _invoke(reg, "task_update", id=1, status="in_progress")
        result = await _invoke(reg, "task_update", id=1, status="completed")
        body = json.loads(result.content)
        assert body["success"] is False
        # Status rolled back to in_progress, not stuck on completed.
        body2 = json.loads((await _invoke(reg, "task_get", id=1)).content)
        assert body2["task"]["status"] == "in_progress"
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_hook_blocks_task_completed_never_writes(
    registry_with_session_tools: ToolRegistry,
    store: TaskStore,
) -> None:
    """Veto-before-write: when the task_completed hook blocks, the COMPLETED
    status must NEVER touch disk — `updated_at` should equal the value from
    the prior in_progress write, not be bumped by a transient COMPLETED
    write + rollback."""
    from framework.tasks.models import TaskStatus

    reg = registry_with_session_tools
    list_id = "session:agent_a:sess_1"
    register_hook(HOOK_TASK_COMPLETED, lambda ctx: (_ for _ in ()).throw(BlockingHookError("nope")))
    token = _set_ctx(agent_id="agent_a", task_list_id=list_id)
    try:
        await _invoke(reg, "task_create", subject="x")
        await _invoke(reg, "task_update", id=1, status="in_progress")
        # Snapshot updated_at after the in_progress write — this is the
        # value that should persist if veto-before-write is honored.
        before = await store.get_task(list_id, 1)
        assert before is not None
        ts_before = before.updated_at

        # Vetoed completion attempt.
        result = await _invoke(reg, "task_update", id=1, status="completed")
        body = json.loads(result.content)
        assert body["success"] is False

        # On-disk record must be byte-identical to the pre-vet snapshot —
        # no transient COMPLETED write, no rollback updated_at bump.
        after = await store.get_task(list_id, 1)
        assert after is not None
        assert after.status == TaskStatus.IN_PROGRESS
        assert after.updated_at == ts_before, (
            "veto-before-write violated: updated_at changed, indicating a transient write happened"
        )
    finally:
        ToolRegistry.reset_execution_context(token)


# ---------------------------------------------------------------------------
# Colony template tools
# ---------------------------------------------------------------------------


@pytest.fixture
def queen_registry(store: TaskStore) -> ToolRegistry:
    reg = ToolRegistry()
    register_task_tools(reg, store=store)
    register_colony_template_tools(reg, colony_id="abc", store=store)
    return reg


@pytest.mark.asyncio
async def test_colony_template_add_and_list(queen_registry: ToolRegistry) -> None:
    reg = queen_registry
    queen_session_list = "session:queen:sess_1"
    token = _set_ctx(agent_id="queen", task_list_id=queen_session_list, colony_id="abc")
    try:
        await _invoke(reg, "colony_template_add", subject="crawl")
        await _invoke(reg, "colony_template_add", subject="parse")
        body = json.loads((await _invoke(reg, "colony_template_list")).content)
        assert body["count"] == 2

        # The session task list should be empty — colony tools don't write there.
        body_session = json.loads((await _invoke(reg, "task_list")).content)
        assert body_session["count"] == 0
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_colony_template_remove(queen_registry: ToolRegistry) -> None:
    reg = queen_registry
    token = _set_ctx(agent_id="queen", task_list_id="session:queen:sess_1", colony_id="abc")
    try:
        await _invoke(reg, "colony_template_add", subject="a")
        await _invoke(reg, "colony_template_add", subject="b")
        result = await _invoke(reg, "colony_template_remove", id=2)
        body = json.loads(result.content)
        assert body["success"] is True
        # Next add gets id 3 (highwatermark preserved)
        result2 = await _invoke(reg, "colony_template_add", subject="c")
        body2 = json.loads(result2.content)
        assert body2["task_id"] == 3
    finally:
        ToolRegistry.reset_execution_context(token)
