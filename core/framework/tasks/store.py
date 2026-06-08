"""File-backed task store with filelock-based coordination.

Layout per list::

    {task_list_path}/tasks.json        -- TaskListDocument (meta + hwm + tasks)
    {task_list_path}/tasks.json.lock   -- list-level lock sentinel

Where ``task_list_path`` is:

    colony:{c}        -> ~/.hive/colonies/{c}/
    session:{a}:{s}   -> ~/.hive/agents/{a}/sessions/{s}/
    unscoped:{a}      -> ~/.hive/unscoped/{a}/
    {malformed}       -> ~/.hive/_misc/{slug}/

An older layout used the same root + a nested ``tasks/`` subdir holding
``meta.json``, ``.highwatermark``, ``.lock``, and ``NNNN.json`` per task.
That produced the ugly ``…/tasks/tasks/0001.json`` path. Migration is
lazy — the first lock-protected access on such a list folds the legacy
artifacts into ``tasks.json`` and unlinks them.

All filesystem I/O is wrapped in ``asyncio.to_thread`` so the event loop
never blocks. Locks use a ~3s budget — comfortable headroom for the only
realistic write contender (colony template under concurrent
``colony_template_*`` and ``run_parallel_workers`` stamps).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import threading
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
    TaskListDocument,
    TaskListMeta,
    TaskListRole,
    TaskRecord,
    TaskStatus,
)
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_SECONDS = 3.0  # ~30 retries × ~100ms

DOC_FILENAME = "tasks.json"
LOCK_FILENAME = "tasks.json.lock"  # only colony lists (cross-process writers)

# Per-list in-memory locks for single-process scopes (session/unscoped/_misc).
# Sessions have one owning agent, so only same-process concurrency matters
# (e.g. parallel tool use within a single turn) — no on-disk lock needed.
_INPROC_LOCKS: dict[str, threading.Lock] = {}
_INPROC_LOCKS_GUARD = threading.Lock()


def _get_inproc_lock(task_list_id: str) -> threading.Lock:
    with _INPROC_LOCKS_GUARD:
        lock = _INPROC_LOCKS.get(task_list_id)
        if lock is None:
            lock = threading.Lock()
            _INPROC_LOCKS[task_list_id] = lock
        return lock


class _Unset:
    """Sentinel for "owner argument not provided" — distinct from owner=None."""

    __slots__ = ()


_UNSET_SENTINEL: _Unset = _Unset()


def _hive_root() -> Path:
    """Location of the hive data dir; honors HIVE_HOME for tests."""
    return Path(os.environ.get("HIVE_HOME", str(Path.home() / ".hive")))


def _find_queen_session_dir(session_id: str, *, hive_root: Path) -> Path | None:
    """Return ``agents/queens/{queen}/sessions/{session_id}`` if one exists.

    Queens live under ``QUEENS_DIR = hive_root / "agents" / "queens"`` (see
    ``framework.config``). The task system gets a generic ``agent_id ==
    "queen"`` in its ``task_list_id``, which would otherwise dead-end at
    ``agents/queen/...``, decoupled from the real session folder. By
    probing the canonical layout we keep the task doc beside conversations,
    events, summary, and meta for the same session.
    """
    queens_dir = hive_root / "agents" / "queens"
    if not queens_dir.exists():
        return None
    try:
        candidates = [d for d in queens_dir.iterdir() if d.is_dir()]
    except OSError:
        return None
    for queen_dir in candidates:
        candidate = queen_dir / "sessions" / session_id
        if candidate.is_dir():
            return candidate
    return None


def task_list_path(task_list_id: str, *, hive_root: Path | None = None) -> Path:
    """Resolve task_list_id -> directory containing ``tasks.json``.

    Note: this returns the *parent* of the doc file, not the file itself.
    For session/colony/unscoped lists, this is the agent or colony's home
    dir; the task doc is one filename inside it. (The older layout had an
    extra ``tasks/`` subdir under this path — see ``_legacy_root``.)

    For ``session:`` lists, the canonical queen session folder is preferred
    when it exists on disk: the task doc lives next to the rest of that
    session's data (conversations, events, summary).
    """
    root = hive_root or _hive_root()
    if task_list_id.startswith("colony:"):
        colony_id = task_list_id[len("colony:") :]
        return root / "colonies" / colony_id
    if task_list_id.startswith("session:"):
        rest = task_list_id[len("session:") :]
        agent_id, _, session_id = rest.partition(":")
        if not session_id:
            raise ValueError(f"Malformed session task_list_id: {task_list_id!r}")
        canonical = _find_queen_session_dir(session_id, hive_root=root)
        if canonical is not None:
            return canonical
        return root / "agents" / agent_id / "sessions" / session_id
    if task_list_id.startswith("unscoped:"):
        agent_id = task_list_id[len("unscoped:") :]
        return root / "unscoped" / agent_id
    # Last-ditch sanitization for HIVE_TASK_LIST_ID overrides — slugify the
    # whole thing so the test/dev path can't escape the hive root.
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_list_id)
    return root / "_misc" / safe


def _legacy_root(task_list_id: str, *, hive_root: Path | None = None) -> Path:
    """Where the older artifacts (meta.json, .highwatermark, tasks/NNNN.json) lived.

    Pinned to the *pre-canonical* layout — for queen session lists this is
    ``agents/{agent_id}/sessions/{session_id}/tasks`` (i.e. the literal
    ``agent_id`` folder, not the canonical ``agents/queens/{queen}/...``
    path). The lazy migration reads from here and writes the new doc to
    wherever ``task_list_path`` resolves now.
    """
    root = hive_root or _hive_root()
    if task_list_id.startswith("colony:"):
        return root / "colonies" / task_list_id[len("colony:") :] / "tasks"
    if task_list_id.startswith("session:"):
        rest = task_list_id[len("session:") :]
        agent_id, _, session_id = rest.partition(":")
        return root / "agents" / agent_id / "sessions" / session_id / "tasks"
    if task_list_id.startswith("unscoped:"):
        return root / "unscoped" / task_list_id[len("unscoped:") :] / "tasks"
    # _misc fallback: legacy lived directly in the slug dir, same as the new parent.
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
        """A list exists if its doc is on disk OR a legacy artifact is.

        The legacy fallback exists so that lists created under the older
        layout and not yet migrated still surface to the REST layer.
        """

        def _check() -> bool:
            if self._doc_path(task_list_id).exists():
                return True
            return self._has_legacy_artifacts(task_list_id)

        return await asyncio.to_thread(_check)

    async def get_meta(self, task_list_id: str) -> TaskListMeta | None:
        return await asyncio.to_thread(self._read_meta_sync, task_list_id)

    async def reset_task_list(self, task_list_id: str) -> None:
        """Delete all tasks but preserve the high-water-mark.

        Test helper. Never wired to runtime lifecycle.
        """
        await asyncio.to_thread(self._reset_sync, task_list_id)

    # ----- task CRUD ----------------------------------------------------

    async def create_tasks_batch(
        self,
        task_list_id: str,
        specs: list[dict[str, Any]],
    ) -> list[TaskRecord]:
        """Atomically create N tasks under a single list-lock acquisition.

        Each spec is a dict with keys: subject (required), description,
        active_form, owner, metadata. Ids are assigned sequentially and
        contiguously; if any spec is malformed the whole batch is
        rejected before any write. The doc model makes "atomic-or-none"
        free — we mutate one in-memory document and write it once.
        """
        return await asyncio.to_thread(self._create_tasks_batch_sync, task_list_id, specs)

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

    def _list_dir(self, task_list_id: str) -> Path:
        return task_list_path(task_list_id, hive_root=self._hive_root)

    def _doc_path(self, task_list_id: str) -> Path:
        return self._list_dir(task_list_id) / DOC_FILENAME

    def _list_lock(self, task_list_id: str):
        """Return a context manager that serialises writes to this list.

        Colony template lists need a cross-process ``FileLock`` because
        ``run_parallel_workers`` spawns worker subprocesses that stamp
        completion back onto the template. Session/unscoped/_misc lists
        have a single owning agent — only same-process concurrency
        matters (e.g. parallel tool use within one turn), so an
        in-memory ``threading.Lock`` is enough and avoids the visible
        ``tasks.json.lock`` sentinel beside session folders.
        """
        d = self._list_dir(task_list_id)
        d.mkdir(parents=True, exist_ok=True)
        if task_list_id.startswith("colony:"):
            return FileLock(str(d / LOCK_FILENAME), timeout=LOCK_TIMEOUT_SECONDS)
        return _get_inproc_lock(task_list_id)

    def _legacy_dir(self, task_list_id: str) -> Path:
        return _legacy_root(task_list_id, hive_root=self._hive_root)

    def _legacy_meta_path(self, task_list_id: str) -> Path:
        return self._legacy_dir(task_list_id) / "meta.json"

    def _legacy_hwm_path(self, task_list_id: str) -> Path:
        return self._legacy_dir(task_list_id) / ".highwatermark"

    def _legacy_lock_path(self, task_list_id: str) -> Path:
        return self._legacy_dir(task_list_id) / ".lock"

    def _legacy_tasks_dir(self, task_list_id: str) -> Path:
        return self._legacy_dir(task_list_id) / "tasks"

    def _has_legacy_artifacts(self, task_list_id: str) -> bool:
        if self._legacy_meta_path(task_list_id).exists():
            return True
        td = self._legacy_tasks_dir(task_list_id)
        if td.exists():
            try:
                return any(p.suffix == ".json" for p in td.iterdir())
            except OSError:
                return False
        return False

    # ----- doc IO -------------------------------------------------------

    def _read_doc_sync(self, task_list_id: str) -> TaskListDocument | None:
        """Lock-free read for already-migrated lists; falls back to a
        lock-protected migration if only legacy artifacts exist.

        Returns None if the list doesn't exist on disk in either form.
        """
        doc_path = self._doc_path(task_list_id)
        if doc_path.exists():
            try:
                return TaskListDocument.model_validate_json(doc_path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Corrupt tasks.json at %s", doc_path, exc_info=True)
                # Fall through — legacy fallback may rescue us.

        if self._has_legacy_artifacts(task_list_id):
            with self._list_lock(task_list_id):
                # Re-check under lock: a parallel writer may have just
                # finished migrating, in which case we read the new doc.
                if doc_path.exists():
                    try:
                        return TaskListDocument.model_validate_json(doc_path.read_text(encoding="utf-8"))
                    except Exception:
                        logger.warning(
                            "Corrupt tasks.json at %s (post-lock)",
                            doc_path,
                            exc_info=True,
                        )
                doc = self._migrate_legacy_unsafe(task_list_id)
                if doc is not None:
                    self._write_doc_unsafe(task_list_id, doc)
                    self._cleanup_legacy_unsafe(task_list_id)
                return doc
        return None

    def _read_doc_unsafe(self, task_list_id: str) -> TaskListDocument | None:
        """Same as ``_read_doc_sync`` but assumes the list-lock is already
        held — used by methods that are already inside ``with self._list_lock``.
        Migration happens in-place without re-entering the lock.
        """
        doc_path = self._doc_path(task_list_id)
        if doc_path.exists():
            try:
                return TaskListDocument.model_validate_json(doc_path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Corrupt tasks.json at %s", doc_path, exc_info=True)
        if self._has_legacy_artifacts(task_list_id):
            doc = self._migrate_legacy_unsafe(task_list_id)
            if doc is not None:
                self._write_doc_unsafe(task_list_id, doc)
                self._cleanup_legacy_unsafe(task_list_id)
                return doc
        return None

    def _write_doc_unsafe(self, task_list_id: str, doc: TaskListDocument) -> None:
        """Atomically rewrite the doc. Caller MUST hold the list-lock."""
        path = self._doc_path(task_list_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_write(path) as f:
            f.write(doc.model_dump_json(indent=2))

    # ----- migration ----------------------------------------------------

    def _migrate_legacy_unsafe(self, task_list_id: str) -> TaskListDocument | None:
        """Fold legacy artifacts into a TaskListDocument. Caller MUST hold lock."""
        meta = self._read_legacy_meta(task_list_id)
        if meta is None:
            inferred_role = TaskListRole.TEMPLATE if task_list_id.startswith("colony:") else TaskListRole.SESSION
            meta = TaskListMeta(task_list_id=task_list_id, role=inferred_role)

        tasks: list[TaskRecord] = []
        td = self._legacy_tasks_dir(task_list_id)
        if td.exists():
            for p in sorted(td.iterdir()):
                if p.suffix != ".json":
                    continue
                try:
                    tasks.append(TaskRecord.model_validate_json(p.read_text(encoding="utf-8")))
                except Exception:
                    logger.warning(
                        "Skipping corrupt legacy task file %s during migration",
                        p,
                        exc_info=True,
                    )
        tasks.sort(key=lambda r: r.id)

        hwm = self._read_legacy_hwm(task_list_id)
        max_id = max((r.id for r in tasks), default=0)
        hwm = max(hwm, max_id)

        if not tasks and hwm == 0 and not self._legacy_meta_path(task_list_id).exists():
            return None

        return TaskListDocument(
            meta=meta,
            highwatermark=hwm,
            tasks=tasks,
        )

    def _read_legacy_meta(self, task_list_id: str) -> TaskListMeta | None:
        path = self._legacy_meta_path(task_list_id)
        if not path.exists():
            return None
        try:
            return TaskListMeta.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Corrupt legacy meta.json at %s", path, exc_info=True)
            return None

    def _read_legacy_hwm(self, task_list_id: str) -> int:
        path = self._legacy_hwm_path(task_list_id)
        if not path.exists():
            return 0
        try:
            return int(path.read_text(encoding="utf-8").strip() or "0")
        except (ValueError, OSError):
            return 0

    def _cleanup_legacy_unsafe(self, task_list_id: str) -> None:
        """Remove the older layout's files. Caller MUST hold the list-lock.

        For session/colony/unscoped lists the legacy_dir is a dedicated
        ``tasks/`` subdir, so we remove the whole tree. For the ``_misc``
        fallback the legacy_dir is the same as the new parent dir — we
        delete only the specific legacy filenames so we don't clobber
        the new ``tasks.json``.
        """
        legacy = self._legacy_dir(task_list_id)
        if not legacy.exists():
            return

        if legacy != self._list_dir(task_list_id):
            try:
                shutil.rmtree(legacy)
            except OSError:
                logger.warning("Failed to remove legacy task dir %s", legacy, exc_info=True)
            return

        # _misc case: shared parent dir — surgical delete only.
        for p in (
            self._legacy_meta_path(task_list_id),
            self._legacy_hwm_path(task_list_id),
            self._legacy_lock_path(task_list_id),
        ):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to remove %s", p, exc_info=True)
        td = self._legacy_tasks_dir(task_list_id)
        if td.exists():
            try:
                shutil.rmtree(td)
            except OSError:
                logger.warning("Failed to remove legacy tasks subdir %s", td, exc_info=True)

    # ----- meta accessors over the doc ----------------------------------

    def _ensure_task_list_sync(
        self,
        task_list_id: str,
        role: TaskListRole,
        creator_agent_id: str | None,
        session_id: str | None,
    ) -> TaskListMeta:
        with self._list_lock(task_list_id):
            doc = self._read_doc_unsafe(task_list_id)
            if doc is None:
                meta = TaskListMeta(
                    task_list_id=task_list_id,
                    role=role,
                    creator_agent_id=creator_agent_id,
                    last_seen_session_ids=[session_id] if session_id else [],
                )
                doc = TaskListDocument(meta=meta)
                self._write_doc_unsafe(task_list_id, doc)
                return meta

            meta = doc.meta
            if session_id and session_id not in meta.last_seen_session_ids:
                meta.last_seen_session_ids.append(session_id)
                # Cap at 10 to keep the audit trail bounded.
                meta.last_seen_session_ids = meta.last_seen_session_ids[-10:]
                self._write_doc_unsafe(task_list_id, doc)
            return meta

    def _read_meta_sync(self, task_list_id: str) -> TaskListMeta | None:
        doc = self._read_doc_sync(task_list_id)
        return doc.meta if doc is not None else None

    # ----- task IO ------------------------------------------------------

    def _read_task_sync(self, task_list_id: str, task_id: int) -> TaskRecord | None:
        doc = self._read_doc_sync(task_list_id)
        if doc is None:
            return None
        for r in doc.tasks:
            if r.id == task_id:
                return r
        return None

    def _list_tasks_sync(self, task_list_id: str) -> list[TaskRecord]:
        doc = self._read_doc_sync(task_list_id)
        if doc is None:
            return []
        return sorted(doc.tasks, key=lambda r: r.id)

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
            doc = self._read_doc_unsafe(task_list_id)
            if doc is None:
                inferred_role = TaskListRole.TEMPLATE if task_list_id.startswith("colony:") else TaskListRole.SESSION
                doc = TaskListDocument(meta=TaskListMeta(task_list_id=task_list_id, role=inferred_role))
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
            self._write_doc_unsafe(task_list_id, doc)
            return record

    def _create_tasks_batch_sync(
        self,
        task_list_id: str,
        specs: list[dict[str, Any]],
    ) -> list[TaskRecord]:
        if not specs:
            return []
        # Validate up-front so we don't half-create on a malformed entry.
        for i, spec in enumerate(specs):
            subj = spec.get("subject")
            if not isinstance(subj, str) or not subj.strip():
                raise ValueError(f"specs[{i}].subject must be a non-empty string")

        with self._list_lock(task_list_id):
            doc = self._read_doc_unsafe(task_list_id)
            if doc is None:
                inferred_role = TaskListRole.TEMPLATE if task_list_id.startswith("colony:") else TaskListRole.SESSION
                doc = TaskListDocument(meta=TaskListMeta(task_list_id=task_list_id, role=inferred_role))

            base_id = self._next_id_for_doc(doc)
            now = time.time()
            records: list[TaskRecord] = []
            for offset, spec in enumerate(specs):
                rec = TaskRecord(
                    id=base_id + offset,
                    subject=spec["subject"],
                    description=spec.get("description", ""),
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
            self._write_doc_unsafe(task_list_id, doc)
            return records

    # ----- id assignment ------------------------------------------------

    def _next_id_for_doc(self, doc: TaskListDocument) -> int:
        max_existing = max((r.id for r in doc.tasks), default=0)
        return max(max_existing, doc.highwatermark) + 1

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
            doc = self._read_doc_unsafe(task_list_id)
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
                self._write_doc_unsafe(task_list_id, doc)
            return new, changed

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

    def _delete_task_sync(self, task_list_id: str, task_id: int) -> tuple[bool, list[int]]:
        with self._list_lock(task_list_id):
            doc = self._read_doc_unsafe(task_list_id)
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
            self._write_doc_unsafe(task_list_id, doc)
            return True, cascaded

    # ----- reset --------------------------------------------------------

    def _reset_sync(self, task_list_id: str) -> None:
        with self._list_lock(task_list_id):
            doc = self._read_doc_unsafe(task_list_id)
            if doc is None:
                return
            max_id = max((r.id for r in doc.tasks), default=0)
            doc.highwatermark = max(doc.highwatermark, max_id)
            doc.tasks = []
            self._write_doc_unsafe(task_list_id, doc)

    # ----- claim --------------------------------------------------------

    def _claim_sync(self, task_list_id: str, task_id: int, claimant: str) -> ClaimResult:
        with self._list_lock(task_list_id):
            doc = self._read_doc_unsafe(task_list_id)
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
            self._write_doc_unsafe(task_list_id, doc)
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
    """Yield every task-list-related file — used by tests to assert
    byte-equivalence pre/post shutdown.

    Includes the doc + lock and any legacy leftovers (so this still works
    while a list is mid-migration).
    """
    files: list[Path] = []
    base = task_list_path(task_list_id, hive_root=hive_root)
    if not base.exists():
        return []
    doc = base / DOC_FILENAME
    if doc.exists():
        files.append(doc)
    lock = base / LOCK_FILENAME
    if lock.exists():
        files.append(lock)
    legacy = _legacy_root(task_list_id, hive_root=hive_root)
    if legacy.exists() and legacy != base:
        files.extend(sorted(legacy.rglob("*")))
    elif legacy.exists():
        # _misc fallback: include only legacy filenames
        for name in ("meta.json", ".highwatermark", ".lock"):
            p = legacy / name
            if p.exists():
                files.append(p)
        td = legacy / "tasks"
        if td.exists():
            files.extend(sorted(td.rglob("*")))
    return sorted(files)
