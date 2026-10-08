"""Tests for the file-backed task store.

Concurrency / id-monotonicity / cascade / claim / reset — the engineering
primitives the rest of the system relies on.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from framework.tasks import TaskStatus, TaskStore
from framework.tasks.models import ClaimAlreadyOwned, ClaimBlocked, ClaimNotFound, ClaimOk


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(hive_root=tmp_path)


@pytest.fixture
def session_id() -> str:
    return "test_session"


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    rec = await store.create_task(session_id, subject="hi")
    assert rec.id == 1
    fetched = await store.get_task(session_id, 1)
    assert fetched is not None
    assert fetched.subject == "hi"
    assert fetched.status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_get_missing_returns_none(store: TaskStore, session_id: str) -> None:
    assert await store.get_task(session_id, 999) is None


@pytest.mark.asyncio
async def test_list_ascending(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    await store.create_task(session_id, subject="a")
    await store.create_task(session_id, subject="b")
    await store.create_task(session_id, subject="c")
    rs = await store.list_tasks(session_id)
    assert [r.id for r in rs] == [1, 2, 3]


@pytest.mark.asyncio
async def test_list_filters_internal(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    await store.create_task(session_id, subject="visible")
    await store.create_task(session_id, subject="hidden", metadata={"_internal": True})
    public = await store.list_tasks(session_id)
    assert len(public) == 1
    all_ = await store.list_tasks(session_id, include_internal=True)
    assert len(all_) == 2


# ---------------------------------------------------------------------------
# Concurrent creation: two parallel calls -> N and N+1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_create_distinct_ids(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    results = await asyncio.gather(*(store.create_task(session_id, subject=f"t{i}") for i in range(20)))
    ids = sorted(r.id for r in results)
    assert ids == list(range(1, 21))


# ---------------------------------------------------------------------------
# Update + change detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_returns_changed_fields(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    rec = await store.create_task(session_id, subject="orig")
    new, fields = await store.update_task(session_id, rec.id, subject="orig", status=TaskStatus.IN_PROGRESS)
    assert fields == ["status"]  # subject unchanged shouldn't appear
    assert new.status == TaskStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_update_missing_returns_none(store: TaskStore, session_id: str) -> None:
    new, fields = await store.update_task(session_id, 42, subject="x")
    assert new is None
    assert fields == []


@pytest.mark.asyncio
async def test_metadata_patch_merges_and_deletes(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    rec = await store.create_task(session_id, subject="x", metadata={"a": 1, "b": 2})
    new, _ = await store.update_task(session_id, rec.id, metadata_patch={"a": 10, "b": None})
    assert new.metadata == {"a": 10}


# ---------------------------------------------------------------------------
# Bidirectional blocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocks_bidirectional(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    a = await store.create_task(session_id, subject="a")
    b = await store.create_task(session_id, subject="b")
    new_a, _ = await store.update_task(session_id, a.id, add_blocks=[b.id])
    assert b.id in new_a.blocks
    fetched_b = await store.get_task(session_id, b.id)
    assert a.id in fetched_b.blocked_by


@pytest.mark.asyncio
async def test_blocked_by_bidirectional(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    a = await store.create_task(session_id, subject="a")
    b = await store.create_task(session_id, subject="b")
    new_b, _ = await store.update_task(session_id, b.id, add_blocked_by=[a.id])
    assert a.id in new_b.blocked_by
    fetched_a = await store.get_task(session_id, a.id)
    assert b.id in fetched_a.blocks


# ---------------------------------------------------------------------------
# Delete: highwatermark + cascade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_increments_highwatermark(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    await store.create_task(session_id, subject="a")
    b = await store.create_task(session_id, subject="b")
    deleted, _ = await store.delete_task(session_id, b.id)
    assert deleted
    new = await store.create_task(session_id, subject="c")
    assert new.id == b.id + 1, "deleted ids must never be reused"


@pytest.mark.asyncio
async def test_delete_cascades_blocks(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    a = await store.create_task(session_id, subject="a")
    b = await store.create_task(session_id, subject="b")
    c = await store.create_task(session_id, subject="c")
    await store.update_task(session_id, a.id, add_blocks=[b.id])
    await store.update_task(session_id, c.id, add_blocked_by=[b.id])
    _, cascade = await store.delete_task(session_id, b.id)
    assert sorted(cascade) == sorted([a.id, c.id])
    fetched_a = await store.get_task(session_id, a.id)
    fetched_c = await store.get_task(session_id, c.id)
    assert b.id not in fetched_a.blocks
    assert b.id not in fetched_c.blocked_by


@pytest.mark.asyncio
async def test_delete_missing_returns_false(store: TaskStore, session_id: str) -> None:
    deleted, cascade = await store.delete_task(session_id, 42)
    assert not deleted
    assert cascade == []


# ---------------------------------------------------------------------------
# Reset preserves high-water-mark
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_preserves_floor(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    for _ in range(5):
        await store.create_task(session_id, subject="x")
    await store.reset_task_list(session_id)
    new = await store.create_task(session_id, subject="post-reset")
    assert new.id == 6


# ---------------------------------------------------------------------------
# Archive / unarchive — the agent archives via update_task(status="archived")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archiving_stamps_batch_markers(store: TaskStore, session_id: str) -> None:
    """Archiving a task (update_task → archived) stamps the markers History
    groups by (goal) and un-archive restores from (archived_from)."""
    await store.ensure_task_list(session_id)
    await store.create_tasks_batch(session_id, [{"subject": "x"}], goal="Grow pipeline")
    await store.update_task(session_id, 1, status=TaskStatus.COMPLETED)

    await store.update_task(session_id, 1, status=TaskStatus.ARCHIVED)

    rec = (await store.list_tasks(session_id))[0]
    assert rec.status is TaskStatus.ARCHIVED
    assert rec.metadata["archived_from"] == "completed"
    assert rec.metadata["archived_goal"] == "Grow pipeline"
    assert isinstance(rec.metadata["archived_at"], float)


@pytest.mark.asyncio
async def test_unarchive_restores_prior_status_and_strips_markers(store: TaskStore, session_id: str) -> None:
    """Un-archiving puts each task back where it was (not a blanket
    'pending') and removes the markers, so a restored task re-enters the
    plan exactly as it left."""
    await store.ensure_task_list(session_id)
    await store.create_task(session_id, subject="was-done")
    await store.create_task(session_id, subject="was-pending")
    await store.update_task(session_id, 1, status=TaskStatus.COMPLETED)
    await store.update_task(session_id, 1, status=TaskStatus.ARCHIVED)
    await store.update_task(session_id, 2, status=TaskStatus.ARCHIVED)

    restored = await store.unarchive_tasks(session_id, [1, 2])

    assert sorted(restored) == [1, 2]
    by_id = {r.id: r for r in await store.list_tasks(session_id)}
    assert by_id[1].status is TaskStatus.COMPLETED  # restored to its prior status
    assert by_id[2].status is TaskStatus.PENDING
    assert "archived_from" not in by_id[1].metadata
    assert "archived_at" not in by_id[1].metadata


@pytest.mark.asyncio
async def test_unarchive_ignores_non_archived_ids(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    await store.create_task(session_id, subject="active")  # never archived
    assert await store.unarchive_tasks(session_id, [1, 999]) == []


@pytest.mark.asyncio
async def test_archive_completed_archives_only_completed(store: TaskStore, session_id: str) -> None:
    """ "Clear done" archives every completed task and leaves the rest,
    stamping the same History markers the agent's own archive path does."""
    await store.ensure_task_list(session_id)
    await store.create_tasks_batch(
        session_id,
        [{"subject": "done-1"}, {"subject": "done-2"}, {"subject": "open"}],
        goal="Ship it",
    )
    await store.update_task(session_id, 1, status=TaskStatus.COMPLETED)
    await store.update_task(session_id, 2, status=TaskStatus.COMPLETED)

    archived = await store.archive_completed_tasks(session_id)

    assert sorted(r.id for r in archived) == [1, 2]
    by_id = {r.id: r for r in await store.list_tasks(session_id)}
    assert by_id[1].status is TaskStatus.ARCHIVED
    assert by_id[2].status is TaskStatus.ARCHIVED
    assert by_id[3].status is TaskStatus.PENDING  # open task untouched
    # Same markers History groups by — so button- and agent-archived tasks
    # land in one batch.
    assert by_id[1].metadata["archived_from"] == "completed"
    assert by_id[1].metadata["archived_goal"] == "Ship it"
    assert isinstance(by_id[1].metadata["archived_at"], float)


@pytest.mark.asyncio
async def test_archive_completed_is_noop_without_completed(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    await store.create_task(session_id, subject="open")
    await store.update_task(session_id, 1, status=TaskStatus.IN_PROGRESS)
    assert await store.archive_completed_tasks(session_id) == []
    # The in_progress task is left exactly as it was.
    assert (await store.get_task(session_id, 1)).status is TaskStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_archive_completed_missing_list_returns_empty(store: TaskStore, session_id: str) -> None:
    """No task list for the session → [] (the route hits this for unknown
    sessions and must not error or create a doc as a side effect)."""
    assert await store.archive_completed_tasks(session_id) == []
    assert not await store.list_exists(session_id)


@pytest.mark.asyncio
async def test_archive_completed_second_call_is_noop_and_preserves_stamps(store: TaskStore, session_id: str) -> None:
    """Idempotence: a second "Clear done" archives nothing new, and does NOT
    restamp the History markers of tasks archived by the first call (a
    restamp would tear them out of their original History batch)."""
    await store.ensure_task_list(session_id)
    await store.create_task(session_id, subject="done")
    await store.update_task(session_id, 1, status=TaskStatus.COMPLETED)

    first = await store.archive_completed_tasks(session_id)
    assert [r.id for r in first] == [1]
    stamp = (await store.get_task(session_id, 1)).metadata["archived_at"]

    await asyncio.sleep(0.02)  # a restamp would produce a later time.time()
    assert await store.archive_completed_tasks(session_id) == []
    after = await store.get_task(session_id, 1)
    assert after.status is TaskStatus.ARCHIVED
    assert after.metadata["archived_at"] == stamp


@pytest.mark.asyncio
async def test_archive_completed_then_unarchive_restores_completed(store: TaskStore, session_id: str) -> None:
    """Round-trip with History "remove": archived_from='completed' means
    unarchive puts the task back as COMPLETED (not pending) and strips the
    archive markers."""
    await store.ensure_task_list(session_id)
    await store.create_tasks_batch(session_id, [{"subject": "done"}, {"subject": "open"}], goal="Ship it")
    await store.update_task(session_id, 1, status=TaskStatus.COMPLETED)
    archived = await store.archive_completed_tasks(session_id)
    assert [r.id for r in archived] == [1]

    assert await store.unarchive_tasks(session_id, [1]) == [1]
    restored = await store.get_task(session_id, 1)
    assert restored.status is TaskStatus.COMPLETED
    assert "archived_from" not in restored.metadata
    assert "archived_at" not in restored.metadata


# ---------------------------------------------------------------------------
# Claim semantics — atomic owner-claim under the list lock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_ok(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    rec = await store.create_task(session_id, subject="x")
    result = await store.claim_task_with_busy_check(session_id, rec.id, "agent_a")
    assert isinstance(result, ClaimOk)
    assert result.record.owner == "agent_a"


@pytest.mark.asyncio
async def test_claim_already_owned(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    rec = await store.create_task(session_id, subject="x", owner="agent_a")
    result = await store.claim_task_with_busy_check(session_id, rec.id, "agent_b")
    assert isinstance(result, ClaimAlreadyOwned)
    assert result.by == "agent_a"


@pytest.mark.asyncio
async def test_claim_not_found(store: TaskStore, session_id: str) -> None:
    result = await store.claim_task_with_busy_check(session_id, 999, "agent_a")
    assert isinstance(result, ClaimNotFound)


@pytest.mark.asyncio
async def test_claim_blocked(store: TaskStore, session_id: str) -> None:
    await store.ensure_task_list(session_id)
    a = await store.create_task(session_id, subject="prereq")
    b = await store.create_task(session_id, subject="dep")
    await store.update_task(session_id, b.id, add_blocked_by=[a.id])
    # a is still pending -> b blocked.
    result = await store.claim_task_with_busy_check(session_id, b.id, "agent_a")
    assert isinstance(result, ClaimBlocked)
    assert a.id in result.by


# ---------------------------------------------------------------------------
# Meta lifecycle: ensure_task_list is idempotent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_task_list_idempotent(store: TaskStore, session_id: str) -> None:
    m1 = await store.ensure_task_list(session_id)
    m2 = await store.ensure_task_list(session_id)
    assert m1.created_at == m2.created_at  # same dir


# ---------------------------------------------------------------------------
# Path resolution: canonical session-folder layouts win
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_path_for_unknown_session(store: TaskStore, tmp_path: Path) -> None:
    """A session_id with no canonical folder on disk lands in the
    sandboxed ``_misc/`` fallback."""
    await store.ensure_task_list("free_floating_session")
    assert (tmp_path / "_misc" / "free_floating_session" / "tasks.json").exists()


@pytest.mark.asyncio
async def test_canonical_queen_session_dir_wins(store: TaskStore, tmp_path: Path) -> None:
    """When ``queens/<q>/sessions/<sid>/`` exists on disk, the task doc
    lands there — beside conversations/events/summary."""
    sid = "session_20260429_test"
    canonical = tmp_path / "queens" / "queen_growth" / "sessions" / sid
    canonical.mkdir(parents=True)
    # Pretend the rest of the session is here.
    (canonical / "events.jsonl").write_text("", encoding="utf-8")

    await store.ensure_task_list(sid)
    rec = await store.create_task(sid, subject="hello")

    assert (canonical / "tasks.json").exists()
    assert not (tmp_path / "_misc" / sid / "tasks.json").exists()
    fetched = await store.list_tasks(sid)
    assert [r.id for r in fetched] == [rec.id]


@pytest.mark.asyncio
async def test_colony_queen_session_dir_wins(store: TaskStore, tmp_path: Path) -> None:
    """``colonies/<c>/queens/<q>/sessions/<sid>/`` is a canonical home for
    a colony-overseer queen task list."""
    sid = "session_20260429_overseer"
    canonical = tmp_path / "colonies" / "alpha" / "queens" / "queen_growth" / "sessions" / sid
    canonical.mkdir(parents=True)
    (canonical / "events.jsonl").write_text("", encoding="utf-8")

    await store.ensure_task_list(sid)
    rec = await store.create_task(sid, subject="oversee me")

    assert (canonical / "tasks.json").exists()
    fetched = await store.list_tasks(sid)
    assert [r.id for r in fetched] == [rec.id]


@pytest.mark.asyncio
async def test_colony_worker_session_dir_wins(store: TaskStore, tmp_path: Path) -> None:
    """``colonies/<c>/workers/<sid>/`` is the canonical home for a worker
    task list. This regression-tests the Phase-1 bug fix: before it,
    workers wrote to the wrong fallback path."""
    sid = "session_20260513_worker"
    canonical = tmp_path / "colonies" / "alpha" / "workers" / sid
    canonical.mkdir(parents=True)
    (canonical / "events.jsonl").write_text("", encoding="utf-8")

    await store.ensure_task_list(sid)
    rec = await store.create_task(sid, subject="worker work")

    assert (canonical / "tasks.json").exists()
    fetched = await store.list_tasks(sid)
    assert [r.id for r in fetched] == [rec.id]


# ---------------------------------------------------------------------------
# Session-dir resolution cache (long-idle thread-pool starvation fix)
# ---------------------------------------------------------------------------


def test_session_dir_cache_avoids_rescan(tmp_path: Path, monkeypatch) -> None:
    """A resolved canonical session dir is cached, so repeated lookups don't
    re-walk the queens/colonies tree. That per-call scan, paid on every
    task-store read (incl. the per-session idle-nudge poll), starved the
    shared thread pool over a long idle and hung session-load reads."""
    from framework.tasks import store as store_mod
    from framework.tasks.store import session_storage_dir

    sid = "session_20260101_000000_abc"
    canonical = tmp_path / "queens" / "vision_queen" / "sessions" / sid
    canonical.mkdir(parents=True)

    real = store_mod._find_session_dir
    calls = 0

    def _counting(session_id, *, hive_root):
        nonlocal calls
        calls += 1
        return real(session_id, hive_root=hive_root)

    monkeypatch.setattr(store_mod, "_find_session_dir", _counting)
    store_mod._SESSION_DIR_CACHE.clear()

    first = session_storage_dir(sid, hive_root=tmp_path)
    for _ in range(20):
        assert session_storage_dir(sid, hive_root=tmp_path) == canonical
    assert first == canonical
    assert calls == 1  # scanned once; every later lookup served from cache


def test_session_dir_cache_skips_negative(tmp_path: Path) -> None:
    """A session dir that doesn't exist yet is NOT cached, so it's found the
    moment it appears (a negative cache would pin the _misc fallback)."""
    from framework.tasks import store as store_mod
    from framework.tasks.store import session_storage_dir

    sid = "session_20260101_000001_def"
    store_mod._SESSION_DIR_CACHE.clear()

    # No canonical folder yet → sandboxed fallback, not cached.
    assert session_storage_dir(sid, hive_root=tmp_path) == tmp_path / "_misc" / sid

    # It appears → canonical resolution wins, no stale negative cache.
    canonical = tmp_path / "queens" / "q" / "sessions" / sid
    canonical.mkdir(parents=True)
    assert session_storage_dir(sid, hive_root=tmp_path) == canonical


def test_session_dir_cache_invalidates_on_delete(tmp_path: Path) -> None:
    """A cached folder that's since been removed triggers a fresh scan rather
    than returning the dead path."""
    import shutil

    from framework.tasks import store as store_mod
    from framework.tasks.store import session_storage_dir

    sid = "session_20260101_000002_ghi"
    store_mod._SESSION_DIR_CACHE.clear()
    canonical = tmp_path / "queens" / "q" / "sessions" / sid
    canonical.mkdir(parents=True)
    assert session_storage_dir(sid, hive_root=tmp_path) == canonical  # caches it

    shutil.rmtree(canonical)
    assert session_storage_dir(sid, hive_root=tmp_path) == tmp_path / "_misc" / sid


# ---------------------------------------------------------------------------
# Spawn-seeded goal (queen-authored worker titles, 2026-07-21)
# ---------------------------------------------------------------------------
# WHY: the UI titles a worker card with the session's meta.goal. The queen
# seeds it at spawn (set_goal, before any task exists); the worker's own
# task_create must KEEP it when it omits goal (the executor contract) and
# may replace it when it passes one. If seeding started requiring tasks, or
# a goal-less batch started clearing the goal, worker cards would lose
# their human-readable titles.


@pytest.mark.asyncio
async def test_set_goal_before_any_tasks(store: TaskStore, session_id: str) -> None:
    await store.set_goal(session_id, "Checking 20 Instagram profiles")
    meta = await store.get_meta(session_id)
    assert meta is not None and meta.goal == "Checking 20 Instagram profiles"
    assert await store.list_tasks(session_id) == []


@pytest.mark.asyncio
async def test_task_create_without_goal_keeps_seeded_goal(store: TaskStore, session_id: str) -> None:
    await store.set_goal(session_id, "Checking 20 Instagram profiles")
    await store.create_tasks_batch(session_id, [{"subject": "triage batch"}])
    meta = await store.get_meta(session_id)
    assert meta is not None and meta.goal == "Checking 20 Instagram profiles"


@pytest.mark.asyncio
async def test_task_create_with_goal_overwrites_seeded_goal(store: TaskStore, session_id: str) -> None:
    await store.set_goal(session_id, "Seeded by queen")
    await store.create_tasks_batch(session_id, [{"subject": "t"}], goal="Refined by worker")
    meta = await store.get_meta(session_id)
    assert meta is not None and meta.goal == "Refined by worker"
