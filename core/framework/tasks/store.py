"""File-backed task store with filelock-based coordination.

Layout per list::

    {root}/{task_list_id}/
        meta.json                       -- TaskListMeta
        tasks/
            0001.json                   -- TaskRecord (zero-padded for ls-sort)
            0002.json
            ...
        .lock                           -- list-level lock
        .highwatermark                  -- ID floor (deleted ids never reused)

Two list-roots:

    colony:{colony_id}     -> ~/.hive/colonies/{colony_id}/tasks/
    session:{a}:{s}        -> ~/.hive/agents/{a}/sessions/{s}/tasks/

All filesystem I/O is wrapped in ``asyncio.to_thread`` so the event loop
never blocks. Locks use a 30-retry / ~2.6s budget — comfortable headroom
for the only realistic write contender (colony template under concurrent
``colony_template_*`` and ``run_parallel_workers`` stamps).

The "_unsafe" variants exist because filelock is **not re-entrant**: a
caller already holding a lock must NOT re-acquire it (would deadlock).
The unsafe path skips acquisition and is callable only from inside another
locked function. See ``claim_task_with_busy_check`` and ``delete_task``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from filelock import FileLock

from framework.tasks.models import (
    ClaimAlreadyCompleted,
    ClaimAlreadyOwned,
    ClaimBlocked,
    ClaimNotFound,
    ClaimOk,
    ClaimResult,
    TaskListMeta,
    TaskListRole,
    TaskRecord,
    TaskStatus,
)
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_SECONDS = 3.0  # ~30 retries × ~100ms


class _Unset:
    """Sentinel for "owner argument not provided" — distinct from owner=None."""

    __slots__ = ()


_UNSET_SENTINEL: _Unset = _Unset()


def _hive_root() -> Path:
    """Location of the hive data dir; honors HIVE_HOME for tests."""
    return Path(os.environ.get("HIVE_HOME", str(Path.home() / ".hive")))


def task_list_path(task_list_id: str, *, hive_root: Path | None = None) -> Path:
    """Resolve task_list_id -> on-disk root."""
    root = hive_root or _hive_root()
    if task_list_id.startswith("colony:"):
        colony_id = task_list_id[len("colony:") :]
        return root / "colonies" / colony_id / "tasks"
    if task_list_id.startswith("session:"):
        rest = task_list_id[len("session:") :]
        agent_id, _, session_id = rest.partition(":")
        if not session_id:
            raise ValueError(f"Malformed session task_list_id: {task_list_id!r}")
        return root / "agents" / agent_id / "sessions" / session_id / "tasks"
    if task_list_id.startswith("unscoped:"):
        agent_id = task_list_id[len("unscoped:") :]
        return root / "unscoped" / agent_id / "tasks"
    # Last-ditch sanitization for HIVE_TASK_LIST_ID overrides — slugify the
    # whole thing so the test/dev path can't escape the hive root.
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_list_id)
    return root / "_misc" / safe


# ---------------------------------------------------------------------------
# TaskStore — public façade
# ---------------------------------------------------------------------------


class TaskStore:
    """Async wrapper around the on-disk store.

    A single TaskStore is fine to share across the process; locking is
    file-based, so even multiple processes are safe.
    """

    def __init__(self, *, hive_root: Path | None = None) -> None:
        self._hive_root = hive_root

    # ----- list-level ---------------------------------------------------

    async def ensure_task_list(
        self,
        task_list_id: str,
        *,
        role: TaskListRole,
        creator_agent_id: str | None = None,
        session_id: str | None = None,
    ) -> TaskListMeta:
        """Create a list if absent; if present, append session_id to last_seen.

        Idempotent: callers (ColonyRuntime bringup, lazy session creation)
        can call this every time.
        """
        return await asyncio.to_thread(
            self._ensure_task_list_sync,
            task_list_id,
            role,
            creator_agent_id,
            session_id,
        )

    async def list_exists(self, task_list_id: str) -> bool:
        """A list exists if its meta.json OR any task file is on disk.

        meta.json is normally written by ``ensure_task_list``, but session
        lists may be created lazily via the first ``task_create`` (see
        ``_create_task_sync``) — in that case meta.json is backfilled the
        first time the list is read. Until then, we still want to expose
        the list's tasks via REST.
        """

        def _check() -> bool:
            root = self._list_root(task_list_id)
            if (root / "meta.json").exists():
                return True
            tasks_dir = root / "tasks"
            if tasks_dir.exists() and any(p.suffix == ".json" for p in tasks_dir.iterdir()):
                return True
            return False

        return await asyncio.to_thread(_check)

    async def get_meta(self, task_list_id: str) -> TaskListMeta | None:
        return await asyncio.to_thread(self._read_meta_sync, task_list_id)

    async def reset_task_list(self, task_list_id: str) -> None:
        """Delete all task files but preserve the high-water-mark.

        Test helper. Never wired to runtime lifecycle.
        """
        await asyncio.to_thread(self._reset_sync, task_list_id)

    # ----- task CRUD ----------------------------------------------------

    async def create_task(
        self,
        task_list_id: str,
        *,
        subject: str,
        description: str = "",
        active_form: str | None = None,
        owner: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskRecord:
        return await asyncio.to_thread(
            self._create_task_sync,
            task_list_id,
            subject,
            description,
            active_form,
            owner,
            metadata or {},
        )

    async def get_task(self, task_list_id: str, task_id: int) -> TaskRecord | None:
        return await asyncio.to_thread(self._read_task_sync, task_list_id, task_id)

    async def list_tasks(
        self,
        task_list_id: str,
        *,
        include_internal: bool = False,
    ) -> list[TaskRecord]:
        records = await asyncio.to_thread(self._list_tasks_sync, task_list_id)
        if include_internal:
            return records
        return [r for r in records if not r.metadata.get("_internal")]

    async def update_task(
        self,
        task_list_id: str,
        task_id: int,
        *,
        subject: str | None = None,
        description: str | None = None,
        active_form: str | None = None,
        owner: str | None | _Unset = _UNSET_SENTINEL,
        status: TaskStatus | None = None,
        add_blocks: list[int] | None = None,
        add_blocked_by: list[int] | None = None,
        metadata_patch: dict[str, Any] | None = None,
    ) -> tuple[TaskRecord | None, list[str]]:
        """Update a task; returns (new_record, fields_changed) or (None, [])."""
        return await asyncio.to_thread(
            self._update_task_sync,
            task_list_id,
            task_id,
            subject,
            description,
            active_form,
            owner,
            status,
            add_blocks,
            add_blocked_by,
            metadata_patch,
        )

    async def delete_task(self, task_list_id: str, task_id: int) -> tuple[bool, list[int]]:
        """Delete a task; returns (was_deleted, cascaded_ids).

        ``cascaded_ids`` are the ids of other tasks whose blocks/blocked_by
        referenced the deleted id and were stripped.
        """
        return await asyncio.to_thread(self._delete_task_sync, task_list_id, task_id)

    async def claim_task_with_busy_check(
        self,
        task_list_id: str,
        task_id: int,
        claimant: str,
    ) -> ClaimResult:
        """Atomic claim under list-lock.

        Used internally by ``run_parallel_workers`` when stamping
        ``metadata.assigned_session`` on colony template entries — not
        exposed to LLMs as a worker-facing claim race.
        """
        return await asyncio.to_thread(self._claim_sync, task_list_id, task_id, claimant)

    # =====================================================================
    # Sync internals — all called via asyncio.to_thread
    # =====================================================================

    def _list_root(self, task_list_id: str) -> Path:
        return task_list_path(task_list_id, hive_root=self._hive_root)

    def _tasks_dir(self, task_list_id: str) -> Path:
        return self._list_root(task_list_id) / "tasks"

    def _list_lock(self, task_list_id: str) -> FileLock:
        # FileLock targets a sentinel file; it tolerates the file being absent
        # by creating it on first acquire. We use the .lock filename so it's
        # visible alongside the other list files.
        root = self._list_root(task_list_id)
        root.mkdir(parents=True, exist_ok=True)
        return FileLock(str(root / ".lock"), timeout=LOCK_TIMEOUT_SECONDS)

    def _highwatermark_path(self, task_list_id: str) -> Path:
        return self._list_root(task_list_id) / ".highwatermark"

    def _meta_path(self, task_list_id: str) -> Path:
        return self._list_root(task_list_id) / "meta.json"

    def _task_path(self, task_list_id: str, task_id: int) -> Path:
        return self._tasks_dir(task_list_id) / f"{task_id:04d}.json"

    # ----- meta ---------------------------------------------------------

    def _ensure_task_list_sync(
        self,
        task_list_id: str,
        role: TaskListRole,
        creator_agent_id: str | None,
        session_id: str | None,
    ) -> TaskListMeta:
        root = self._list_root(task_list_id)
        root.mkdir(parents=True, exist_ok=True)
        (root / "tasks").mkdir(exist_ok=True)
        meta_path = self._meta_path(task_list_id)
        with self._list_lock(task_list_id):
            if meta_path.exists():
                meta = self._read_meta_sync(task_list_id)
                if meta is None:
                    # File existed but failed to parse — rewrite fresh.
                    meta = TaskListMeta(
                        task_list_id=task_list_id,
                        role=role,
                        creator_agent_id=creator_agent_id,
                    )
                if session_id and session_id not in meta.last_seen_session_ids:
                    meta.last_seen_session_ids.append(session_id)
                    # Cap at 10 to keep the audit trail bounded.
                    meta.last_seen_session_ids = meta.last_seen_session_ids[-10:]
                    self._write_meta_sync(task_list_id, meta)
                return meta
            meta = TaskListMeta(
                task_list_id=task_list_id,
                role=role,
                creator_agent_id=creator_agent_id,
                last_seen_session_ids=[session_id] if session_id else [],
            )
            self._write_meta_sync(task_list_id, meta)
            return meta

    def _read_meta_sync(self, task_list_id: str) -> TaskListMeta | None:
        path = self._meta_path(task_list_id)
        if not path.exists():
            return None
        try:
            return TaskListMeta.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Corrupt meta.json at %s", path, exc_info=True)
            return None

    def _write_meta_sync(self, task_list_id: str, meta: TaskListMeta) -> None:
        path = self._meta_path(task_list_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_write(path) as f:
            f.write(meta.model_dump_json(indent=2))

    # ----- task IO ------------------------------------------------------

    def _read_task_sync(self, task_list_id: str, task_id: int) -> TaskRecord | None:
        path = self._task_path(task_list_id, task_id)
        if not path.exists():
            return None
        try:
            return TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Corrupt task file at %s", path, exc_info=True)
            return None

    def _write_task_sync(self, task_list_id: str, record: TaskRecord) -> None:
        path = self._task_path(task_list_id, record.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_write(path) as f:
            f.write(record.model_dump_json(indent=2))

    def _list_tasks_sync(self, task_list_id: str) -> list[TaskRecord]:
        d = self._tasks_dir(task_list_id)
        if not d.exists():
            return []
        records: list[TaskRecord] = []
        for path in sorted(d.iterdir()):
            if path.suffix != ".json":
                continue
            try:
                records.append(TaskRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                logger.warning("Skipping corrupt task file %s", path, exc_info=True)
        records.sort(key=lambda r: r.id)
        return records

    # ----- highwatermark / id assignment --------------------------------

    def _read_highwatermark_sync(self, task_list_id: str) -> int:
        path = self._highwatermark_path(task_list_id)
        if not path.exists():
            return 0
        try:
            return int(path.read_text(encoding="utf-8").strip() or "0")
        except (ValueError, OSError):
            return 0

    def _write_highwatermark_sync(self, task_list_id: str, value: int) -> None:
        path = self._highwatermark_path(task_list_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_write(path) as f:
            f.write(str(value))

    def _next_id_sync(self, task_list_id: str) -> int:
        """Compute next id under the assumption the list-lock is held."""
        existing = self._list_tasks_sync(task_list_id)
        max_existing = max((r.id for r in existing), default=0)
        floor = self._read_highwatermark_sync(task_list_id)
        return max(max_existing, floor) + 1

    # ----- create -------------------------------------------------------

    def _create_task_sync(
        self,
        task_list_id: str,
        subject: str,
        description: str,
        active_form: str | None,
        owner: str | None,
        metadata: dict[str, Any],
    ) -> TaskRecord:
        with self._list_lock(task_list_id):
            # Lazy-create meta.json on first task. Session lists are
            # frequently created via the first task_create (no explicit
            # ensure_task_list call); without this backfill the REST
            # endpoint can't discover them. Role is inferred from prefix.
            if not self._meta_path(task_list_id).exists():
                inferred_role = TaskListRole.TEMPLATE if task_list_id.startswith("colony:") else TaskListRole.SESSION
                self._write_meta_sync(
                    task_list_id,
                    TaskListMeta(
                        task_list_id=task_list_id,
                        role=inferred_role,
                    ),
                )
            new_id = self._next_id_sync(task_list_id)
            now = time.time()
            record = TaskRecord(
                id=new_id,
                subject=subject,
                description=description,
                active_form=active_form,
                owner=owner,
                status=TaskStatus.PENDING,
                metadata=metadata,
                created_at=now,
                updated_at=now,
            )
            self._write_task_sync(task_list_id, record)
            # Bump high-water-mark eagerly so even a concurrent racer that
            # somehow missed the listing snapshot can't pick the same id.
            if new_id > self._read_highwatermark_sync(task_list_id):
                self._write_highwatermark_sync(task_list_id, new_id)
            return record

    # ----- update -------------------------------------------------------

    def _update_task_sync(
        self,
        task_list_id: str,
        task_id: int,
        subject: str | None,
        description: str | None,
        active_form: str | None,
        owner: str | None | _Unset,
        status: TaskStatus | None,
        add_blocks: list[int] | None,
        add_blocked_by: list[int] | None,
        metadata_patch: dict[str, Any] | None,
    ) -> tuple[TaskRecord | None, list[str]]:
        with self._list_lock(task_list_id):
            current = self._read_task_sync(task_list_id, task_id)
            if current is None:
                return None, []
            return self._update_task_unsafe(
                task_list_id,
                current,
                subject=subject,
                description=description,
                active_form=active_form,
                owner=owner,
                status=status,
                add_blocks=add_blocks,
                add_blocked_by=add_blocked_by,
                metadata_patch=metadata_patch,
            )

    def _update_task_unsafe(
        self,
        task_list_id: str,
        current: TaskRecord,
        *,
        subject: str | None = None,
        description: str | None = None,
        active_form: str | None = None,
        owner: str | None | _Unset = _UNSET_SENTINEL,
        status: TaskStatus | None = None,
        add_blocks: list[int] | None = None,
        add_blocked_by: list[int] | None = None,
        metadata_patch: dict[str, Any] | None = None,
    ) -> tuple[TaskRecord, list[str]]:
        """Update without acquiring the list-lock. Caller MUST hold it."""
        changed: list[str] = []
        new = current.model_copy(deep=True)

        if subject is not None and subject != new.subject:
            new.subject = subject
            changed.append("subject")
        if description is not None and description != new.description:
            new.description = description
            changed.append("description")
        if active_form is not None and active_form != new.active_form:
            new.active_form = active_form
            changed.append("active_form")
        if not isinstance(owner, _Unset) and owner != new.owner:
            new.owner = owner
            changed.append("owner")
        if status is not None and status != new.status:
            new.status = status
            changed.append("status")
        if add_blocks:
            for b in add_blocks:
                if b not in new.blocks and b != new.id:
                    new.blocks.append(b)
                    if "blocks" not in changed:
                        changed.append("blocks")
                    # Maintain the bidirectional invariant by stamping
                    # blocked_by on the target as well.
                    target = self._read_task_sync(task_list_id, b)
                    if target and new.id not in target.blocked_by:
                        target.blocked_by.append(new.id)
                        target.updated_at = time.time()
                        self._write_task_sync(task_list_id, target)
        if add_blocked_by:
            for b in add_blocked_by:
                if b not in new.blocked_by and b != new.id:
                    new.blocked_by.append(b)
                    if "blocked_by" not in changed:
                        changed.append("blocked_by")
                    target = self._read_task_sync(task_list_id, b)
                    if target and new.id not in target.blocks:
                        target.blocks.append(new.id)
                        target.updated_at = time.time()
                        self._write_task_sync(task_list_id, target)
        if metadata_patch is not None:
            md = dict(new.metadata)
            for k, v in metadata_patch.items():
                if v is None:
                    md.pop(k, None)
                else:
                    md[k] = v
            if md != new.metadata:
                new.metadata = md
                changed.append("metadata")

        if not changed:
            return new, []

        new.updated_at = time.time()
        self._write_task_sync(task_list_id, new)
        return new, changed

    # ----- delete -------------------------------------------------------

    def _delete_task_sync(self, task_list_id: str, task_id: int) -> tuple[bool, list[int]]:
        with self._list_lock(task_list_id):
            path = self._task_path(task_list_id, task_id)
            if not path.exists():
                return False, []
            # 1. Bump high-water-mark BEFORE unlinking so a crash mid-delete
            #    can't accidentally re-allocate the id.
            current_floor = self._read_highwatermark_sync(task_list_id)
            if task_id > current_floor:
                self._write_highwatermark_sync(task_list_id, task_id)
            # 2. Unlink the task itself.
            path.unlink()
            # 3. Cascade: strip references from all other tasks.
            cascaded: list[int] = []
            for other in self._list_tasks_sync(task_list_id):
                touched = False
                if task_id in other.blocks:
                    other.blocks = [b for b in other.blocks if b != task_id]
                    touched = True
                if task_id in other.blocked_by:
                    other.blocked_by = [b for b in other.blocked_by if b != task_id]
                    touched = True
                if touched:
                    other.updated_at = time.time()
                    self._write_task_sync(task_list_id, other)
                    cascaded.append(other.id)
            return True, cascaded

    # ----- reset --------------------------------------------------------

    def _reset_sync(self, task_list_id: str) -> None:
        with self._list_lock(task_list_id):
            tasks = self._list_tasks_sync(task_list_id)
            max_id = max((r.id for r in tasks), default=0)
            floor = self._read_highwatermark_sync(task_list_id)
            new_floor = max(max_id, floor)
            self._write_highwatermark_sync(task_list_id, new_floor)
            d = self._tasks_dir(task_list_id)
            if d.exists():
                for p in d.iterdir():
                    if p.suffix == ".json":
                        p.unlink()

    # ----- claim --------------------------------------------------------

    def _claim_sync(self, task_list_id: str, task_id: int, claimant: str) -> ClaimResult:
        with self._list_lock(task_list_id):
            current = self._read_task_sync(task_list_id, task_id)
            if current is None:
                return ClaimNotFound(kind="not_found")
            if current.status == TaskStatus.COMPLETED:
                return ClaimAlreadyCompleted(kind="already_completed")
            if current.owner is not None and current.owner != claimant:
                return ClaimAlreadyOwned(kind="already_owned", by=current.owner)
            unresolved_blockers: list[int] = []
            for b in current.blocked_by:
                blocker = self._read_task_sync(task_list_id, b)
                if blocker is not None and blocker.status != TaskStatus.COMPLETED:
                    unresolved_blockers.append(b)
            if unresolved_blockers:
                return ClaimBlocked(kind="blocked", by=unresolved_blockers)
            new, _ = self._update_task_unsafe(task_list_id, current, owner=claimant)
            return ClaimOk(kind="ok", record=new)


# ---------------------------------------------------------------------------
# Process-wide singleton (small, stateless wrapper)
# ---------------------------------------------------------------------------


_default_store: TaskStore | None = None


def get_task_store() -> TaskStore:
    """Process-wide default TaskStore (resolves HIVE_HOME at first call).

    Tests should construct a TaskStore directly with hive_root=tmp_path
    rather than relying on the singleton.
    """
    global _default_store
    if _default_store is None:
        _default_store = TaskStore()
    return _default_store


# Convenience for tests / utilities.
def fingerprint_for_test(task_list_id: str, hive_root: Path) -> Iterable[Path]:
    """Yield every file under a list root — used by tests to assert
    byte-equivalence pre/post shutdown.
    """
    root = task_list_path(task_list_id, hive_root=hive_root)
    if not root.exists():
        return []
    return sorted(root.rglob("*"))
