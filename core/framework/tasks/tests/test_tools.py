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


async def _create_one(registry: ToolRegistry, *, goal: str = "test goal", **fields):
    """task_create with a single-entry `tasks` array — test convenience.

    Defaults a ``goal`` so tests that don't care about the goal-anchor
    contract don't have to spell it out on every first-create. The tool
    requires a goal on the first call of a session; subsequent calls
    inherit the stored one regardless of what's passed.
    """
    return await _invoke(registry, "task_create", tasks=[fields], goal=goal)


def _set_ctx(*, agent_id: str, session_id: str, **extra):
    return ToolRegistry.set_execution_context(agent_id=agent_id, session_id=session_id, **extra)


# ---------------------------------------------------------------------------
# Session tools — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_then_list(registry_with_session_tools: ToolRegistry) -> None:
    reg = registry_with_session_tools
    session_id = "sess_1"
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        result = await _create_one(reg, subject="Plan retrieval")
        assert result.is_error is False
        body = json.loads(result.content)
        assert body["success"] is True
        assert body["task_ids"] == [1]

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
    session_id = "sess_1"
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        await _create_one(reg, subject="x")
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
    session_id = "sess_1"
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        await _create_one(reg, subject="x")
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
async def test_task_list_hides_archived_from_agent(
    registry_with_session_tools: ToolRegistry,
) -> None:
    """Archived tasks leave the agent's working set — task_list is the only
    task data the agent reads, so an archived task should not resurface in
    it while active tasks stay."""
    reg = registry_with_session_tools
    session_id = "sess_1"
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        await _create_one(reg, subject="stays")
        await _invoke(reg, "task_create", tasks=[{"subject": "archive me"}])
        await _invoke(reg, "task_update", id=2, status="archived")
        await _invoke(reg, "task_create", tasks=[{"subject": "new plan"}])

        body = json.loads((await _invoke(reg, "task_list")).content)
        subjects = sorted(t["subject"] for t in body["tasks"])
        assert subjects == ["new plan", "stays"]  # #2 archived, excluded
        assert body["count"] == 2
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_agent_can_archive_via_task_update(
    registry_with_session_tools: ToolRegistry,
) -> None:
    """The agent archives its own finished work with status='archived' —
    the task leaves task_list and carries the History batch markers so the
    UI can group and later restore it."""
    reg = registry_with_session_tools
    session_id = "sess_1"
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        await _create_one(reg, subject="done thing", goal="Ship v1")
        await _invoke(reg, "task_update", id=1, status="completed")
        result = await _invoke(reg, "task_update", id=1, status="archived")
        body = json.loads(result.content)
        assert body["success"] is True
        assert body["task"]["status"] == "archived"
        # History markers: prior status + goal snapshot stamped.
        assert body["task"]["metadata"]["archived_from"] == "completed"
        assert body["task"]["metadata"]["archived_goal"] == "Ship v1"

        # Hidden from the default list, but visible with include_archived.
        listed = json.loads((await _invoke(reg, "task_list")).content)
        assert listed["count"] == 0
        with_arch = json.loads((await _invoke(reg, "task_list", include_archived=True)).content)
        assert with_arch["count"] == 1
        assert with_arch["tasks"][0]["status"] == "archived"
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_agent_can_restore_archived_via_task_update(
    registry_with_session_tools: ToolRegistry,
) -> None:
    """Archiving is reversible: editing an archived task's status back to a
    live one restores it to the plan and strips the archived_* markers."""
    reg = registry_with_session_tools
    session_id = "sess_1"
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        await _create_one(reg, subject="x")
        await _invoke(reg, "task_update", id=1, status="archived")

        result = await _invoke(reg, "task_update", id=1, status="pending")
        body = json.loads(result.content)
        assert body["success"] is True
        assert body["task"]["status"] == "pending"
        # Markers stripped — it re-enters the plan clean.
        assert "archived_from" not in body["task"]["metadata"]
        assert "archived_at" not in body["task"]["metadata"]

        # Back in the default list.
        listed = json.loads((await _invoke(reg, "task_list")).content)
        assert listed["count"] == 1
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_get_returns_full_record(
    registry_with_session_tools: ToolRegistry,
) -> None:
    reg = registry_with_session_tools
    session_id = "sess_1"
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        await _create_one(reg, subject="x", description="full body")
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
    session_id = "sess_1"
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
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
async def test_create_batch_creates_n_tasks_atomically(
    registry_with_session_tools: ToolRegistry,
) -> None:
    reg = registry_with_session_tools
    session_id = "sess_1"
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        result = await _invoke(
            reg,
            "task_create",
            goal="test goal",
            tasks=[
                {"subject": "step 1", "active_form": "Doing 1"},
                {"subject": "step 2"},
                {"subject": "step 3"},
            ],
        )
        assert result.is_error is False
        body = json.loads(result.content)
        assert body["success"] is True
        assert body["task_ids"] == [1, 2, 3]
        # Compact summary message — references first id and the range.
        assert "#1-#3" in body["message"] or "#1, #2, #3" in body["message"]
        assert "Mark #1 in_progress" in body["message"]

        # Sanity: list shows all three.
        body2 = json.loads((await _invoke(reg, "task_list")).content)
        assert body2["count"] == 3
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_create_batch_rejects_empty(
    registry_with_session_tools: ToolRegistry,
) -> None:
    reg = registry_with_session_tools
    token = _set_ctx(agent_id="a", session_id="s")
    try:
        result = await _invoke(reg, "task_create", tasks=[])
        body = json.loads(result.content)
        assert body["success"] is False
        assert "non-empty" in body["error"]
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_create_batch_rejects_malformed_spec_atomically(
    registry_with_session_tools: ToolRegistry,
) -> None:
    """A bad subject in the middle of the batch must reject the whole
    batch — not leave partial state on disk."""
    reg = registry_with_session_tools
    token = _set_ctx(agent_id="a", session_id="s")
    try:
        result = await _invoke(
            reg,
            "task_create",
            goal="test goal",
            tasks=[{"subject": "good"}, {"subject": ""}],
        )
        body = json.loads(result.content)
        assert body["success"] is False
        # Confirm zero tasks landed.
        body2 = json.loads((await _invoke(reg, "task_list")).content)
        assert body2["count"] == 0
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_create_batch_hook_blocks_rolls_back_whole_batch(
    registry_with_session_tools: ToolRegistry,
) -> None:
    """If a task_created hook blocks even one task in the batch, the
    entire batch must roll back."""
    reg = registry_with_session_tools

    # Block on the second task only.
    def selective_blocker(ctx) -> None:
        if ctx.task.subject == "block me":
            raise BlockingHookError("policy")

    register_hook(HOOK_TASK_CREATED, selective_blocker)

    token = _set_ctx(agent_id="a", session_id="s")
    try:
        result = await _invoke(
            reg,
            "task_create",
            goal="test goal",
            tasks=[
                {"subject": "ok 1"},
                {"subject": "block me"},
                {"subject": "ok 3"},
            ],
        )
        body = json.loads(result.content)
        assert body["success"] is False
        assert "rolled back" in body["error"]
        # All three rolled back.
        body2 = json.loads((await _invoke(reg, "task_list")).content)
        assert body2["count"] == 0
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_create_batch_then_single_create_keeps_id_monotonic(
    registry_with_session_tools: ToolRegistry,
) -> None:
    """A multi-entry task_create uses sequential ids; a follow-up
    task_create should pick up at the next id after the highest."""
    reg = registry_with_session_tools
    token = _set_ctx(agent_id="a", session_id="s")
    try:
        await _invoke(
            reg,
            "task_create",
            goal="test goal",
            tasks=[{"subject": "a"}, {"subject": "b"}, {"subject": "c"}],
        )
        result = await _create_one(reg, subject="d")
        body = json.loads(result.content)
        assert body["task_ids"] == [4]
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_completion_suffix_points_to_next_pending(
    registry_with_session_tools: ToolRegistry,
) -> None:
    """When a task is marked completed, the result should point at the
    lowest-id pending task as a steering nudge."""
    reg = registry_with_session_tools
    session_id = "sess_1"
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        await _create_one(reg, subject="step 1")
        await _create_one(reg, subject="step 2")
        await _create_one(reg, subject="step 3")
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
    session_id = "sess_1"
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        await _create_one(reg, subject="only step")
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
    session_id = "sess_1"
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        await _create_one(reg, subject="prereq")
        await _create_one(reg, subject="blocked dep")
        # #2 is blocked by #1.
        await _invoke(reg, "task_update", id=2, add_blocked_by=[1])
        await _invoke(reg, "task_update", id=1, status="in_progress")
        # Don't actually complete #1 — instead add an unrelated done.
        await _create_one(reg, subject="extra step")
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
    session_id = "sess_1"

    def blocker(ctx) -> None:
        raise BlockingHookError("test policy")

    register_hook(HOOK_TASK_CREATED, blocker)
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        result = await _create_one(reg, subject="will be aborted")
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
    session_id = "sess_1"

    register_hook(HOOK_TASK_COMPLETED, lambda ctx: (_ for _ in ()).throw(BlockingHookError("nope")))
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        await _create_one(reg, subject="x")
        await _invoke(reg, "task_update", id=1, status="in_progress")
        result = await _invoke(reg, "task_update", id=1, status="completed")
        body = json.loads(result.content)
        assert body["success"] is False
        # Status rolled back to in_progress, not stuck on completed.
        body2 = json.loads((await _invoke(reg, "task_get", id=1)).content)
        assert body2["task"]["status"] == "in_progress"
    finally:
        ToolRegistry.reset_execution_context(token)


# ---------------------------------------------------------------------------
# goal anchor + PivotHandler dispatch (the new_session / new_colony fork)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_task_create_requires_goal(store: TaskStore) -> None:
    """The very first task_create of a session must include a goal —
    without one there's no anchor to compare a later pivot against."""
    reg = ToolRegistry()
    register_task_tools(reg, store=store)
    token = _set_ctx(agent_id="a", session_id="fresh_session")
    try:
        # Missing goal on a fresh session → reject (soft tool result).
        result = await _invoke(reg, "task_create", tasks=[{"subject": "x"}])
        body = json.loads(result.content)
        assert body["success"] is False
        assert "goal" in body["error"].lower()

        # Same call with a goal → succeeds and stores the goal on meta.
        result = await _invoke(reg, "task_create", goal="research competitor pricing", tasks=[{"subject": "x"}])
        body = json.loads(result.content)
        assert body["success"] is True
        meta = await store.get_meta("fresh_session")
        assert meta is not None
        assert meta.goal == "research competitor pricing"
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_followup_task_create_inherits_goal(store: TaskStore) -> None:
    """Once the goal is anchored, subsequent task_create calls may omit
    `goal` and the stored one is preserved (not cleared)."""
    reg = ToolRegistry()
    register_task_tools(reg, store=store)
    token = _set_ctx(agent_id="a", session_id="s")
    try:
        await _invoke(reg, "task_create", goal="anchor", tasks=[{"subject": "a"}])
        # Follow-up with no goal — should succeed and leave meta.goal intact.
        result = await _invoke(reg, "task_create", tasks=[{"subject": "b"}])
        body = json.loads(result.content)
        assert body["success"] is True
        meta = await store.get_meta("s")
        assert meta is not None
        assert meta.goal == "anchor"
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_task_list_surfaces_goal(store: TaskStore) -> None:
    """task_list must lead with the stored goal so the queen has the
    anchor in view when judging a possible pivot."""
    reg = ToolRegistry()
    register_task_tools(reg, store=store)
    token = _set_ctx(agent_id="a", session_id="s")
    try:
        await _invoke(reg, "task_create", goal="ship the launch", tasks=[{"subject": "x"}])
        body = json.loads((await _invoke(reg, "task_list")).content)
        assert body["goal"] == "ship the launch"
        assert body["lines"][0].startswith("Goal: ship the launch")
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_pivot_handler_routes_when_field_set(store: TaskStore) -> None:
    """When the handler's field is set true, the executor delegates to
    the handler and does NOT touch the local task list."""
    from framework.tasks.tools.session_tools import PivotHandler

    handler_calls: list[dict] = []

    async def fake_handle(*, goal, handoff, tasks):
        handler_calls.append({"goal": goal, "handoff": handoff, "tasks": list(tasks)})
        return {"success": True, "routed": "new_session", "task_ids": [99]}

    reg = ToolRegistry()
    register_task_tools(
        reg,
        store=store,
        pivot_handler=PivotHandler(
            field_name="new_session",
            field_description="test",
            handle=fake_handle,
        ),
    )
    token = _set_ctx(agent_id="a", session_id="s")
    try:
        result = await _invoke(
            reg,
            "task_create",
            goal="new goal",
            handoff="full context here",
            new_session=True,
            tasks=[{"subject": "x"}],
        )
        body = json.loads(result.content)
        assert body["success"] is True
        assert body["routed"] == "new_session"
        # Handler received goal/handoff/tasks; local list stays empty.
        assert handler_calls == [{"goal": "new goal", "handoff": "full context here", "tasks": [{"subject": "x"}]}]
        assert await store.list_tasks("s") == []
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_pivot_handler_field_name_is_per_handler(store: TaskStore) -> None:
    """A handler whose field_name is `new_colony` exposes that field
    instead of `new_session`, so colony-phase queens see the right
    vocabulary."""
    from framework.tasks.tools.session_tools import PivotHandler

    captured: list[str] = []

    async def fake_handle(*, goal, handoff, tasks):
        captured.append(goal)
        return {"success": True, "routed": "new_colony"}

    reg = ToolRegistry()
    register_task_tools(
        reg,
        store=store,
        pivot_handler=PivotHandler(
            field_name="new_colony",
            field_description="colony pivot",
            handle=fake_handle,
        ),
    )
    # Schema check: the registered tool's parameters must carry the
    # handler-chosen field, not the other one.
    tool = reg.get_tools()["task_create"]
    assert "new_colony" in tool.parameters["properties"]
    assert "new_session" not in tool.parameters["properties"]

    token = _set_ctx(agent_id="a", session_id="s")
    try:
        await _invoke(
            reg,
            "task_create",
            goal="sibling colony goal",
            handoff="brief",
            new_colony=True,
            tasks=[{"subject": "x"}],
        )
        # The DM field, even if the LLM accidentally sets it, is ignored:
        # the executor only inspects the handler's chosen field.
        result = await _invoke(
            reg,
            "task_create",
            goal="ignored second call",
            new_session=True,
            tasks=[{"subject": "y"}],
        )
        body = json.loads(result.content)
        # Falls through to a normal local create — not routed to the
        # colony handler (whose field is new_colony).
        assert body["success"] is True
        assert "routed" not in body
        assert captured == ["sibling colony goal"]
    finally:
        ToolRegistry.reset_execution_context(token)


@pytest.mark.asyncio
async def test_pivot_requires_goal_on_pivot_call(store: TaskStore) -> None:
    """Setting the pivot bool without a goal must reject — the new
    context needs its own anchor, distinct from the source's."""
    from framework.tasks.tools.session_tools import PivotHandler

    async def fake_handle(*, goal, handoff, tasks):  # noqa: ARG001
        return {"success": True}

    reg = ToolRegistry()
    register_task_tools(
        reg,
        store=store,
        pivot_handler=PivotHandler(
            field_name="new_session",
            field_description="test",
            handle=fake_handle,
        ),
    )
    token = _set_ctx(agent_id="a", session_id="s")
    try:
        # Seed the session so we're past the first-create gate.
        await _invoke(reg, "task_create", goal="original", tasks=[{"subject": "x"}])
        # Pivot without a goal → reject.
        result = await _invoke(
            reg,
            "task_create",
            handoff="brief",
            new_session=True,
            tasks=[{"subject": "y"}],
        )
        body = json.loads(result.content)
        assert body["success"] is False
        assert "goal" in body["error"].lower()
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
    session_id = "sess_1"
    register_hook(HOOK_TASK_COMPLETED, lambda ctx: (_ for _ in ()).throw(BlockingHookError("nope")))
    token = _set_ctx(agent_id="agent_a", session_id=session_id)
    try:
        await _create_one(reg, subject="x")
        await _invoke(reg, "task_update", id=1, status="in_progress")
        # Snapshot updated_at after the in_progress write — this is the
        # value that should persist if veto-before-write is honored.
        before = await store.get_task(session_id, 1)
        assert before is not None
        ts_before = before.updated_at

        # Vetoed completion attempt.
        result = await _invoke(reg, "task_update", id=1, status="completed")
        body = json.loads(result.content)
        assert body["success"] is False

        # On-disk record must be byte-identical to the pre-vet snapshot —
        # no transient COMPLETED write, no rollback updated_at bump.
        after = await store.get_task(session_id, 1)
        assert after is not None
        assert after.status == TaskStatus.IN_PROGRESS
        assert after.updated_at == ts_before, "veto-before-write violated: updated_at changed, indicating a transient write happened"
    finally:
        ToolRegistry.reset_execution_context(token)
