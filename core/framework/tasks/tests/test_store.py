"""Tests for the file-backed task store.

Concurrency / id-monotonicity / cascade / claim / reset — the engineering
primitives the rest of the system relies on.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from framework.tasks import TaskListRole, TaskStatus, TaskStore
from framework.tasks.models import ClaimAlreadyOwned, ClaimBlocked, ClaimNotFound, ClaimOk


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(hive_root=tmp_path)


@pytest.fixture
def list_id() -> str:
    return "session:test_agent:test_session"


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.SESSION)
    rec = await store.create_task(list_id, subject="hi")
    assert rec.id == 1
    fetched = await store.get_task(list_id, 1)
    assert fetched is not None
    assert fetched.subject == "hi"
    assert fetched.status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_get_missing_returns_none(store: TaskStore, list_id: str) -> None:
    assert await store.get_task(list_id, 999) is None


@pytest.mark.asyncio
async def test_list_ascending(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.SESSION)
    await store.create_task(list_id, subject="a")
    await store.create_task(list_id, subject="b")
    await store.create_task(list_id, subject="c")
    rs = await store.list_tasks(list_id)
    assert [r.id for r in rs] == [1, 2, 3]


@pytest.mark.asyncio
async def test_list_filters_internal(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.SESSION)
    await store.create_task(list_id, subject="visible")
    await store.create_task(list_id, subject="hidden", metadata={"_internal": True})
    public = await store.list_tasks(list_id)
    assert len(public) == 1
    all_ = await store.list_tasks(list_id, include_internal=True)
    assert len(all_) == 2


# ---------------------------------------------------------------------------
# Concurrent creation: two parallel calls -> N and N+1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_create_distinct_ids(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.SESSION)
    results = await asyncio.gather(*(store.create_task(list_id, subject=f"t{i}") for i in range(20)))
    ids = sorted(r.id for r in results)
    assert ids == list(range(1, 21))


# ---------------------------------------------------------------------------
# Update + change detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_returns_changed_fields(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.SESSION)
    rec = await store.create_task(list_id, subject="orig")
    new, fields = await store.update_task(list_id, rec.id, subject="orig", status=TaskStatus.IN_PROGRESS)
    assert fields == ["status"]  # subject unchanged shouldn't appear
    assert new.status == TaskStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_update_missing_returns_none(store: TaskStore, list_id: str) -> None:
    new, fields = await store.update_task(list_id, 42, subject="x")
    assert new is None
    assert fields == []


@pytest.mark.asyncio
async def test_metadata_patch_merges_and_deletes(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.SESSION)
    rec = await store.create_task(list_id, subject="x", metadata={"a": 1, "b": 2})
    new, _ = await store.update_task(list_id, rec.id, metadata_patch={"a": 10, "b": None})
    assert new.metadata == {"a": 10}


# ---------------------------------------------------------------------------
# Bidirectional blocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocks_bidirectional(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.SESSION)
    a = await store.create_task(list_id, subject="a")
    b = await store.create_task(list_id, subject="b")
    new_a, _ = await store.update_task(list_id, a.id, add_blocks=[b.id])
    assert b.id in new_a.blocks
    fetched_b = await store.get_task(list_id, b.id)
    assert a.id in fetched_b.blocked_by


@pytest.mark.asyncio
async def test_blocked_by_bidirectional(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.SESSION)
    a = await store.create_task(list_id, subject="a")
    b = await store.create_task(list_id, subject="b")
    new_b, _ = await store.update_task(list_id, b.id, add_blocked_by=[a.id])
    assert a.id in new_b.blocked_by
    fetched_a = await store.get_task(list_id, a.id)
    assert b.id in fetched_a.blocks


# ---------------------------------------------------------------------------
# Delete: highwatermark + cascade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_increments_highwatermark(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.SESSION)
    await store.create_task(list_id, subject="a")
    b = await store.create_task(list_id, subject="b")
    deleted, _ = await store.delete_task(list_id, b.id)
    assert deleted
    new = await store.create_task(list_id, subject="c")
    assert new.id == b.id + 1, "deleted ids must never be reused"


@pytest.mark.asyncio
async def test_delete_cascades_blocks(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.SESSION)
    a = await store.create_task(list_id, subject="a")
    b = await store.create_task(list_id, subject="b")
    c = await store.create_task(list_id, subject="c")
    await store.update_task(list_id, a.id, add_blocks=[b.id])
    await store.update_task(list_id, c.id, add_blocked_by=[b.id])
    _, cascade = await store.delete_task(list_id, b.id)
    assert sorted(cascade) == sorted([a.id, c.id])
    fetched_a = await store.get_task(list_id, a.id)
    fetched_c = await store.get_task(list_id, c.id)
    assert b.id not in fetched_a.blocks
    assert b.id not in fetched_c.blocked_by


@pytest.mark.asyncio
async def test_delete_missing_returns_false(store: TaskStore, list_id: str) -> None:
    deleted, cascade = await store.delete_task(list_id, 42)
    assert not deleted
    assert cascade == []


# ---------------------------------------------------------------------------
# Reset preserves high-water-mark
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_preserves_floor(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.SESSION)
    for _ in range(5):
        await store.create_task(list_id, subject="x")
    await store.reset_task_list(list_id)
    new = await store.create_task(list_id, subject="post-reset")
    assert new.id == 6


# ---------------------------------------------------------------------------
# Claim semantics (used by run_parallel_workers)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_ok(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.TEMPLATE)
    rec = await store.create_task(list_id, subject="x")
    result = await store.claim_task_with_busy_check(list_id, rec.id, "agent_a")
    assert isinstance(result, ClaimOk)
    assert result.record.owner == "agent_a"


@pytest.mark.asyncio
async def test_claim_already_owned(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.TEMPLATE)
    rec = await store.create_task(list_id, subject="x", owner="agent_a")
    result = await store.claim_task_with_busy_check(list_id, rec.id, "agent_b")
    assert isinstance(result, ClaimAlreadyOwned)
    assert result.by == "agent_a"


@pytest.mark.asyncio
async def test_claim_not_found(store: TaskStore, list_id: str) -> None:
    result = await store.claim_task_with_busy_check(list_id, 999, "agent_a")
    assert isinstance(result, ClaimNotFound)


@pytest.mark.asyncio
async def test_claim_blocked(store: TaskStore, list_id: str) -> None:
    await store.ensure_task_list(list_id, role=TaskListRole.TEMPLATE)
    a = await store.create_task(list_id, subject="prereq")
    b = await store.create_task(list_id, subject="dep")
    await store.update_task(list_id, b.id, add_blocked_by=[a.id])
    # a is still pending -> b blocked.
    result = await store.claim_task_with_busy_check(list_id, b.id, "agent_a")
    assert isinstance(result, ClaimBlocked)
    assert a.id in result.by


# ---------------------------------------------------------------------------
# Meta lifecycle: ensure_task_list is idempotent and tracks last_seen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_task_list_idempotent(store: TaskStore, list_id: str) -> None:
    m1 = await store.ensure_task_list(list_id, role=TaskListRole.SESSION, session_id="s1")
    m2 = await store.ensure_task_list(list_id, role=TaskListRole.SESSION, session_id="s2")
    assert m1.created_at == m2.created_at  # same dir
    assert "s1" in m2.last_seen_session_ids
    assert "s2" in m2.last_seen_session_ids


@pytest.mark.asyncio
async def test_ensure_task_list_caps_history(store: TaskStore, list_id: str) -> None:
    for i in range(15):
        await store.ensure_task_list(list_id, role=TaskListRole.SESSION, session_id=f"s{i}")
    meta = await store.get_meta(list_id)
    assert len(meta.last_seen_session_ids) == 10
    assert "s14" in meta.last_seen_session_ids
    assert "s4" not in meta.last_seen_session_ids


# ---------------------------------------------------------------------------
# Path resolution sanity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_colony_path(store: TaskStore, tmp_path: Path) -> None:
    await store.ensure_task_list("colony:abc", role=TaskListRole.TEMPLATE)
    assert (tmp_path / "colonies" / "abc" / "tasks" / "meta.json").exists()


@pytest.mark.asyncio
async def test_session_path(store: TaskStore, tmp_path: Path) -> None:
    await store.ensure_task_list("session:agent_x:sess_y", role=TaskListRole.SESSION)
    p = tmp_path / "agents" / "agent_x" / "sessions" / "sess_y" / "tasks" / "meta.json"
    assert p.exists()
