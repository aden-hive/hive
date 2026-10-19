"""File-backed task store.

Layout per session::

    {session_storage_dir}/tasks.json   -- TaskListDocument (meta + hwm + tasks)

Where ``session_storage_dir`` is the canonical session folder, located by
scanning the three known session layouts (queen DM, queen overseer,
worker) — see ``_find_session_dir``. The task doc lives next to the rest
of that session's data: conversations, events, summary, meta.

All filesystem I/O is wrapped in ``asyncio.to_thread`` so the event loop
never blocks. Each session has a single owning agent, so writes are
serialised by an in-process ``threading.Lock`` keyed by session_id — no
cross-process file lock is needed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from framework.tasks.models import (
    ClaimAlreadyCompleted,
    ClaimAlreadyOwned,
    ClaimBlocked,
    ClaimNotFound,
    ClaimOk,
    ClaimResult,
    TaskListDocument,
    TaskListMeta,
    TaskRecord,
    TaskStatus,
    is_task_idle,
)
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)

DOC_FILENAME = "tasks.json"

# Per-session in-memory locks. Each session has one owning agent, so only
# same-process concurrency matters (e.g. parallel tool use within a single
# turn) — no on-disk lock needed.
_INPROC_LOCKS: dict[str, threading.Lock] = {}
_INPROC_LOCKS_GUARD = threading.Lock()


def _get_inproc_lock(session_id: str) -> threading.Lock:
    with _INPROC_LOCKS_GUARD:
        lock = _INPROC_LOCKS.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _INPROC_LOCKS[session_id] = lock
        return lock


# Resolved-session-dir cache: (session_id, hive_root) -> canonical folder.
# Session folders are created once and never move, so a positive resolution
# is stable for the process; we still re-validate it exists (one stat) on
# read so a deleted/relocated session falls back to a fresh scan. NEGATIVE
# results are deliberately NOT cached — a session dir frequently doesn't
# exist on disk yet on the first lookup and appears moments later. Without
# this cache every task-store read (including the per-session idle-nudge
# poll) re-walks the entire queens/ + colonies/ tree; over a long idle that
# repeated blocking scan starves the shared thread pool and hangs reads.
_SESSION_DIR_CACHE: dict[tuple[str, str], Path] = {}
_SESSION_DIR_CACHE_GUARD = threading.Lock()


class _Unset:
    """Sentinel for "owner argument not provided" — distinct from owner=None."""

    __slots__ = ()


_UNSET_SENTINEL: _Unset = _Unset()


def _hive_root() -> Path:
    """Location of the hive data dir; honors HIVE_HOME for tests."""
    return Path(os.environ.get("HIVE_HOME", str(Path.home() / ".hive")))


def _find_session_dir(session_id: str, *, hive_root: Path) -> Path | None:
    """Return the on-disk session folder if one exists, regardless of agent type.

    Three canonical homes — session_id is globally unique (timestamp +
    UUID), so a cross-layout scan finds exactly one match:

    - Queen DM:       ``queens/<queen>/sessions/<session_id>/``
    - Queen overseer: ``colonies/<c>/queens/<queen>/sessions/<session_id>/``
    - Worker:         ``colonies/<c>/workers/<session_id>/``
    """
    queens_dir = hive_root / "queens"
    if queens_dir.exists():
        try:
            for queen_root in queens_dir.iterdir():
                if not queen_root.is_dir():
                    continue
                candidate = queen_root / "sessions" / session_id
                if candidate.is_dir():
                    return candidate
        except OSError:
            pass
    colonies_dir = hive_root / "colonies"
    if colonies_dir.exists():
        try:
            for colony_root in colonies_dir.iterdir():
                if not colony_root.is_dir():
                    continue
                # Worker session: colonies/<c>/workers/<sid>/
                candidate = colony_root / "workers" / session_id
                if candidate.is_dir():
                    return candidate
                # Queen overseer session: colonies/<c>/queens/<q>/sessions/<sid>/
                queens_root = colony_root / "queens"
                if not queens_root.is_dir():
                    continue
                for queen_root in queens_root.iterdir():
                    if not queen_root.is_dir():
                        continue
                    candidate = queen_root / "sessions" / session_id
                    if candidate.is_dir():
                        return candidate
        except OSError:
            pass
    return None


def session_storage_dir(session_id: str, *, hive_root: Path | None = None) -> Path:
    """Resolve a session_id to the directory containing its ``tasks.json``.

    Returns the canonical session folder if found by scanning the known
    layouts; otherwise falls back to ``_misc/<session_id>/`` so callers
    operating outside the canonical layouts (tests, ad-hoc tools) still
    get a deterministic, sandboxed path inside hive_root.
    """
    if not session_id:
        raise ValueError("session_id must be a non-empty string")
    root = hive_root or _hive_root()
    cache_key = (session_id, str(root))
    with _SESSION_DIR_CACHE_GUARD:
        cached = _SESSION_DIR_CACHE.get(cache_key)
    if cached is not None:
        if cached.is_dir():
            return cached
        # The cached folder vanished (session deleted/relocated) — drop the
        # stale entry and fall through to a fresh scan.
        with _SESSION_DIR_CACHE_GUARD:
            if _SESSION_DIR_CACHE.get(cache_key) == cached:
                del _SESSION_DIR_CACHE[cache_key]
    canonical = _find_session_dir(session_id, hive_root=root)
    if canonical is not None:
        with _SESSION_DIR_CACHE_GUARD:
            _SESSION_DIR_CACHE[cache_key] = canonical
        return canonical
    # Sandboxed fallback for ids that don't (yet) have a canonical folder
    # on disk — slugify so a malformed id can't escape hive_root. Not cached:
    # the canonical folder may appear on a later call.
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    return root / "_misc" / safe


# ---------------------------------------------------------------------------
# TaskStore — public façade
# ---------------------------------------------------------------------------


class TaskStore:
    """Async wrapper around the on-disk store.

    A single TaskStore is fine to share across the process; locking is
    in-memory per session_id, so multi-process is not supported (and not
    needed — each session is owned by a single process).
    """

    def __init__(self, *, hive_root: Path | None = None) -> None:
        self._hive_root = hive_root

    # ----- list-level ---------------------------------------------------

    async def ensure_task_list(
        self,
        session_id: str,
        *,
        creator_agent_id: str | None = None,
    ) -> TaskListMeta:
        """Create the session's task list if absent.

        Idempotent: callers (ColonyRuntime bringup, lazy session creation)
        can call this every time.
        """
        return await asyncio.to_thread(
            self._ensure_task_list_sync,
            session_id,
            creator_agent_id,
        )

    async def set_goal(self, session_id: str, goal: str) -> None:
        """Write ``meta.goal`` without creating any tasks.

        Used by ColonyRuntime at worker spawn to seed the queen-authored
        goal — the human-readable "what is this worker doing" line the UI
        shows as the worker's title. Composes with the task_create
        executor's documented contract: a later task_create that omits
        ``goal`` keeps this one; one that passes its own overwrites it.
        """
        await asyncio.to_thread(self._set_goal_sync, session_id, goal)

    def _set_goal_sync(self, session_id: str, goal: str) -> None:
        with self._list_lock(session_id):
            doc = self._read_doc_unsafe(session_id)
            if doc is None:
                doc = TaskListDocument(meta=TaskListMeta())
            doc.meta.goal = goal
            self._write_doc_unsafe(session_id, doc)

    async def list_exists(self, session_id: str) -> bool:
        """True iff ``tasks.json`` is on disk for this session."""

        def _check() -> bool:
            return self._doc_path(session_id).exists()

        return await asyncio.to_thread(_check)

    async def get_meta(self, session_id: str) -> TaskListMeta | None:
        return await asyncio.to_thread(self._read_meta_sync, session_id)

    async def reset_task_list(self, session_id: str) -> None:
        """Delete all tasks but preserve the high-water-mark.

        Test helper. Never wired to runtime lifecycle.
        """
        await asyncio.to_thread(self._reset_sync, session_id)

    async def archive_completed_tasks(self, session_id: str) -> list[TaskRecord]:
        """Archive every completed task on the list; return the archived records.

        The user-facing "clean up the plan" action (the panel's "Clear done"
        button). Mirrors the agent's own ``task_update`` status="archived" for
        each completed task — stamping the same ``archived_from`` /
        ``archived_at`` / ``archived_goal`` markers History groups by — so
        button-archived and agent-archived tasks land in the same History
        batches. Non-completed and already-archived tasks are left untouched.
        Emitting ``task_updated`` for each returned record is the caller's job
        (the store stays event-free — see events.py).
        """
        return await asyncio.to_thread(self._archive_completed_sync, session_id)

    async def unarchive_tasks(self, session_id: str, task_ids: list[int]) -> list[int]:
        """Restore archived tasks to their pre-archive status; return the
        restored ids.

        Reverses an archive (the agent's ``task_update`` status="archived",
        or the History "remove") for the given ids: reads
        ``metadata.archived_from`` to put each task back where it was
        (falling back to ``pending`` if that's missing), strips the
        ``archived_*`` markers, and touches ``updated_at``. Ids not found
        or not currently archived are skipped.
        """
        return await asyncio.to_thread(self._unarchive_sync, session_id, list(task_ids))

    # ----- task CRUD ----------------------------------------------------

    async def create_tasks_batch(
        self,
        session_id: str,
        specs: list[dict[str, Any]],
        *,
        goal: str | None = None,
    ) -> list[TaskRecord]:
        """Atomically create N tasks under a single list-lock acquisition.

        Each spec is a dict with keys: subject (required), description,
        active_form, owner, metadata. Ids are assigned sequentially and
        contiguously; if any spec is malformed the whole batch is
        rejected before any write. The doc model makes "atomic-or-none"
        free — we mutate one in-memory document and write it once.

        ``goal`` — when provided, also writes ``meta.goal`` under the same
        lock. Used by the task-create executor so the anchor goal lands
        atomically with the first batch (and re-anchors are coherent with
        the tasks that introduced them).
        """
        return await asyncio.to_thread(self._create_tasks_batch_sync, session_id, specs, goal)

    async def create_task(
        self,
        session_id: str,
        *,
        subject: str,
        description: str = "",
        active_form: str | None = None,
        owner: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskRecord:
        return await asyncio.to_thread(
            self._create_task_sync,
            session_id,
            subject,
            description,
            active_form,
            owner,
            metadata or {},
        )

    async def get_task(self, session_id: str, task_id: int) -> TaskRecord | None:
        return await asyncio.to_thread(self._read_task_sync, session_id, task_id)

    async def list_tasks(
        self,
        session_id: str,
        *,
        include_internal: bool = False,
    ) -> list[TaskRecord]:
        records = await asyncio.to_thread(self._list_tasks_sync, session_id)
        if include_internal:
            return records
        return [r for r in records if not r.metadata.get("_internal")]

    async def update_task(
        self,
        session_id: str,
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
            session_id,
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

    async def sweep_idle_tasks(self, session_id: str) -> list[TaskRecord]:
        """Flip stale `in_progress` tasks to `abandoned` and persist.

        Returns the records that changed (empty if nothing was stale). The
        caller is responsible for emitting `task_updated` events for each
        — the store itself stays event-free by design (see events.py).

        Idempotent: a task already in `abandoned` is left alone, and a
        sweep that finds nothing skips the disk write.
        """
        return await asyncio.to_thread(self._sweep_idle_tasks_sync, session_id)

    async def delete_task(self, session_id: str, task_id: int) -> tuple[bool, list[int]]:
        """Delete a task; returns (was_deleted, cascaded_ids).

        ``cascaded_ids`` are the ids of other tasks whose blocks/blocked_by
        referenced the deleted id and were stripped.
        """
        return await asyncio.to_thread(self._delete_task_sync, session_id, task_id)

    async def claim_task_with_busy_check(
        self,
        session_id: str,
        task_id: int,
        claimant: str,
    ) -> ClaimResult:
        """Atomic claim under list-lock.

        Used internally by ``run_worker`` when stamping
        ``metadata.assigned_session`` on colony template entries — not
        exposed to LLMs as a worker-facing claim race.
        """
        return await asyncio.to_thread(self._claim_sync, session_id, task_id, claimant)

    # =====================================================================
    # Sync internals — all called via asyncio.to_thread
    # =====================================================================

    def _list_dir(self, session_id: str) -> Path:
        return session_storage_dir(session_id, hive_root=self._hive_root)

    def _doc_path(self, session_id: str) -> Path:
        return self._list_dir(session_id) / DOC_FILENAME

    def _list_lock(self, session_id: str):
        """Return a context manager that serialises writes to this session's list.

        Each session has a single owning agent, so only same-process
        concurrency matters (e.g. parallel tool use within one turn) —
        an in-memory ``threading.Lock`` is enough.
        """
        d = self._list_dir(session_id)
        d.mkdir(parents=True, exist_ok=True)
        return _get_inproc_lock(session_id)

    # ----- doc IO -------------------------------------------------------

    def _read_doc_sync(self, session_id: str) -> TaskListDocument | None:
        """Lock-free read of the session's task doc, or None if absent."""
        doc_path = self._doc_path(session_id)
        if doc_path.exists():
            try:
                return TaskListDocument.model_validate_json(doc_path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Corrupt tasks.json at %s", doc_path, exc_info=True)
        return None

    def _read_doc_unsafe(self, session_id: str) -> TaskListDocument | None:
        """Same as ``_read_doc_sync`` but assumes the list-lock is already held."""
        doc_path = self._doc_path(session_id)
        if doc_path.exists():
            try:
                return TaskListDocument.model_validate_json(doc_path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Corrupt tasks.json at %s", doc_path, exc_info=True)
        return None

    def _write_doc_unsafe(self, session_id: str, doc: TaskListDocument) -> None:
        """Atomically rewrite the doc. Caller MUST hold the list-lock."""
        path = self._doc_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_write(path) as f:
            f.write(doc.model_dump_json(indent=2))

    # ----- meta accessors over the doc ----------------------------------

    def _ensure_task_list_sync(
        self,
        session_id: str,
        creator_agent_id: str | None,
    ) -> TaskListMeta:
        with self._list_lock(session_id):
            doc = self._read_doc_unsafe(session_id)
            if doc is None:
                meta = TaskListMeta(creator_agent_id=creator_agent_id)
                doc = TaskListDocument(meta=meta)
                self._write_doc_unsafe(session_id, doc)
                return meta
            return doc.meta

    def _read_meta_sync(self, session_id: str) -> TaskListMeta | None:
        doc = self._read_doc_sync(session_id)
        return doc.meta if doc is not None else None

    # ----- task IO ------------------------------------------------------

    def _read_task_sync(self, session_id: str, task_id: int) -> TaskRecord | None:
        doc = self._read_doc_sync(session_id)
        if doc is None:
            return None
        for r in doc.tasks:
            if r.id == task_id:
                return r
        return None

    def _list_tasks_sync(self, session_id: str) -> list[TaskRecord]:
        doc = self._read_doc_sync(session_id)
        if doc is None:
            return []
        return sorted(doc.tasks, key=lambda r: r.id)

    # ----- create -------------------------------------------------------

    def _create_task_sync(
        self,
        session_id: str,
        subject: str,
        description: str,
        active_form: str | None,
        owner: str | None,
        metadata: dict[str, Any],
    ) -> TaskRecord:
        with self._list_lock(session_id):
            doc = self._read_doc_unsafe(session_id)
            if doc is None:
                doc = TaskListDocument(meta=TaskListMeta())
            new_id = self._next_id_for_doc(doc)
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
            doc.tasks.append(record)
            if new_id > doc.highwatermark:
                doc.highwatermark = new_id
            self._write_doc_unsafe(session_id, doc)
            return record

    def _create_tasks_batch_sync(
        self,
        session_id: str,
        specs: list[dict[str, Any]],
        goal: str | None = None,
    ) -> list[TaskRecord]:
        if not specs:
            return []
        # Validate up-front so we don't half-create on a malformed entry.
        for i, spec in enumerate(specs):
            subj = spec.get("subject")
            if not isinstance(subj, str) or not subj.strip():
                raise ValueError(f"specs[{i}].subject must be a non-empty string")

        with self._list_lock(session_id):
            doc = self._read_doc_unsafe(session_id)
            if doc is None:
                doc = TaskListDocument(meta=TaskListMeta())
            if goal is not None:
                doc.meta.goal = goal

            base_id = self._next_id_for_doc(doc)
            now = time.time()
            records: list[TaskRecord] = []
            for offset, spec in enumerate(specs):
                spec_desc = spec.get("description", "")
                rec = TaskRecord(
                    id=base_id + offset,
                    subject=spec["subject"],
                    description=spec_desc,
                    active_form=spec.get("active_form"),
                    owner=spec.get("owner"),
                    status=TaskStatus.PENDING,
                    metadata=dict(spec.get("metadata") or {}),
                    created_at=now,
                    updated_at=now,
                )
                records.append(rec)

            doc.tasks.extend(records)
            highest = records[-1].id
            if highest > doc.highwatermark:
                doc.highwatermark = highest
            # Single write — atomic batch is free with the doc model.
            self._write_doc_unsafe(session_id, doc)
            return records

    # ----- id assignment ------------------------------------------------

    def _next_id_for_doc(self, doc: TaskListDocument) -> int:
        max_existing = max((r.id for r in doc.tasks), default=0)
        return max(max_existing, doc.highwatermark) + 1

    # ----- update -------------------------------------------------------

    def _update_task_sync(
        self,
        session_id: str,
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
        with self._list_lock(session_id):
            doc = self._read_doc_unsafe(session_id)
            if doc is None:
                return None, []
            target = next((r for r in doc.tasks if r.id == task_id), None)
            if target is None:
                return None, []
            new, changed = self._update_task_in_doc(
                doc,
                target,
                subject=subject,
                description=description,
                active_form=active_form,
                owner=owner,
                status=status,
                add_blocks=add_blocks,
                add_blocked_by=add_blocked_by,
                metadata_patch=metadata_patch,
            )
            if changed:
                self._write_doc_unsafe(session_id, doc)
            return new, changed

    def _sweep_idle_tasks_sync(self, session_id: str) -> list[TaskRecord]:
        with self._list_lock(session_id):
            doc = self._read_doc_unsafe(session_id)
            if doc is None:
                return []
            now = time.time()
            changed: list[TaskRecord] = []
            for record in doc.tasks:
                if is_task_idle(record, now=now):
                    record.status = TaskStatus.ABANDONED
                    record.updated_at = now
                    changed.append(record)
            if not changed:
                return []
            self._write_doc_unsafe(session_id, doc)
            return changed

    def _update_task_in_doc(
        self,
        doc: TaskListDocument,
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
        """Mutate ``current`` in place inside ``doc`` and return (record, changed).
        Bidirectional blocks/blocked_by also mutate the targets in ``doc``.
        """
        changed: list[str] = []

        if subject is not None and subject != current.subject:
            current.subject = subject
            changed.append("subject")
        if description is not None and description != current.description:
            current.description = description
            changed.append("description")
        if active_form is not None and active_form != current.active_form:
            current.active_form = active_form
            changed.append("active_form")
        if not isinstance(owner, _Unset) and owner != current.owner:
            current.owner = owner
            changed.append("owner")
        if status is not None and status != current.status:
            if status is TaskStatus.ARCHIVED:
                # Archiving (task_update status="archived"): stamp the
                # markers History groups by (goal) and restore reads
                # (archived_from). Each task carries its own archive time;
                # History groups by goal, not timestamp, so that's fine.
                current.metadata["archived_from"] = current.status.value
                current.metadata["archived_at"] = time.time()
                current.metadata["archived_goal"] = doc.meta.goal
            elif current.status is TaskStatus.ARCHIVED:
                # Restoring an archived task by editing its status back to a
                # live one — clear the markers so it re-enters the plan clean.
                current.metadata.pop("archived_from", None)
                current.metadata.pop("archived_at", None)
                current.metadata.pop("archived_goal", None)
            current.status = status
            changed.append("status")

        if add_blocks:
            for b in add_blocks:
                if b in current.blocks or b == current.id:
                    continue
                current.blocks.append(b)
                if "blocks" not in changed:
                    changed.append("blocks")
                target = next((r for r in doc.tasks if r.id == b), None)
                if target is not None and current.id not in target.blocked_by:
                    target.blocked_by.append(current.id)
                    target.updated_at = time.time()

        if add_blocked_by:
            for b in add_blocked_by:
                if b in current.blocked_by or b == current.id:
                    continue
                current.blocked_by.append(b)
                if "blocked_by" not in changed:
                    changed.append("blocked_by")
                target = next((r for r in doc.tasks if r.id == b), None)
                if target is not None and current.id not in target.blocks:
                    target.blocks.append(current.id)
                    target.updated_at = time.time()

        if metadata_patch is not None:
            md = dict(current.metadata)
            for k, v in metadata_patch.items():
                if v is None:
                    md.pop(k, None)
                else:
                    md[k] = v
            if md != current.metadata:
                current.metadata = md
                changed.append("metadata")

        if not changed:
            return current, []

        current.updated_at = time.time()
        return current, changed

    # ----- delete -------------------------------------------------------

    def _delete_task_sync(self, session_id: str, task_id: int) -> tuple[bool, list[int]]:
        with self._list_lock(session_id):
            doc = self._read_doc_unsafe(session_id)
            if doc is None:
                return False, []
            idx = next((i for i, r in enumerate(doc.tasks) if r.id == task_id), None)
            if idx is None:
                return False, []
            # 1. Bump high-water-mark BEFORE removing so a crash mid-write
            #    can't cause id reuse on the next create. (atomic_write
            #    guarantees we either commit the whole new state or none.)
            if task_id > doc.highwatermark:
                doc.highwatermark = task_id
            # 2. Remove the task itself.
            doc.tasks.pop(idx)
            # 3. Cascade: strip references from all other tasks.
            cascaded: list[int] = []
            now = time.time()
            for other in doc.tasks:
                touched = False
                if task_id in other.blocks:
                    other.blocks = [b for b in other.blocks if b != task_id]
                    touched = True
                if task_id in other.blocked_by:
                    other.blocked_by = [b for b in other.blocked_by if b != task_id]
                    touched = True
                if touched:
                    other.updated_at = now
                    cascaded.append(other.id)
            self._write_doc_unsafe(session_id, doc)
            return True, cascaded

    # ----- reset --------------------------------------------------------

    def _reset_sync(self, session_id: str) -> None:
        with self._list_lock(session_id):
            doc = self._read_doc_unsafe(session_id)
            if doc is None:
                return
            max_id = max((r.id for r in doc.tasks), default=0)
            doc.highwatermark = max(doc.highwatermark, max_id)
            doc.tasks = []
            self._write_doc_unsafe(session_id, doc)

    def _archive_completed_sync(self, session_id: str) -> list[TaskRecord]:
        with self._list_lock(session_id):
            doc = self._read_doc_unsafe(session_id)
            if doc is None:
                return []
            now = time.time()
            archived: list[TaskRecord] = []
            for record in doc.tasks:
                if record.status is not TaskStatus.COMPLETED:
                    continue
                # Same markers the update executor's archive branch stamps —
                # keep them in lockstep so History groups both sources alike.
                record.metadata["archived_from"] = record.status.value
                record.metadata["archived_at"] = now
                record.metadata["archived_goal"] = doc.meta.goal
                record.status = TaskStatus.ARCHIVED
                record.updated_at = now
                archived.append(record)
            if not archived:
                return []
            self._write_doc_unsafe(session_id, doc)
            return archived

    def _unarchive_sync(self, session_id: str, task_ids: list[int]) -> list[int]:
        with self._list_lock(session_id):
            doc = self._read_doc_unsafe(session_id)
            if doc is None:
                return []
            wanted = set(task_ids)
            now = time.time()
            restored: list[int] = []
            for record in doc.tasks:
                if record.id not in wanted or record.status is not TaskStatus.ARCHIVED:
                    continue
                origin = record.metadata.pop("archived_from", None)
                record.metadata.pop("archived_at", None)
                record.metadata.pop("archived_goal", None)
                try:
                    record.status = TaskStatus(origin) if origin else TaskStatus.PENDING
                except ValueError:
                    record.status = TaskStatus.PENDING
                record.updated_at = now
                restored.append(record.id)
            if not restored:
                return []
            self._write_doc_unsafe(session_id, doc)
            return restored

    # ----- claim --------------------------------------------------------

    def _claim_sync(self, session_id: str, task_id: int, claimant: str) -> ClaimResult:
        with self._list_lock(session_id):
            doc = self._read_doc_unsafe(session_id)
            if doc is None:
                return ClaimNotFound(kind="not_found")
            current = next((r for r in doc.tasks if r.id == task_id), None)
            if current is None:
                return ClaimNotFound(kind="not_found")
            if current.status == TaskStatus.COMPLETED:
                return ClaimAlreadyCompleted(kind="already_completed")
            if current.owner is not None and current.owner != claimant:
                return ClaimAlreadyOwned(kind="already_owned", by=current.owner)
            unresolved_blockers: list[int] = []
            for b in current.blocked_by:
                blocker = next((r for r in doc.tasks if r.id == b), None)
                if blocker is not None and blocker.status != TaskStatus.COMPLETED:
                    unresolved_blockers.append(b)
            if unresolved_blockers:
                return ClaimBlocked(kind="blocked", by=unresolved_blockers)
            new, _ = self._update_task_in_doc(doc, current, owner=claimant)
            self._write_doc_unsafe(session_id, doc)
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
def fingerprint_for_test(session_id: str, hive_root: Path) -> Iterable[Path]:
    """Yield every task-list-related file — used by tests to assert
    byte-equivalence pre/post shutdown.
    """
    base = session_storage_dir(session_id, hive_root=hive_root)
    if not base.exists():
        return []
    doc = base / DOC_FILENAME
    return [doc] if doc.exists() else []
