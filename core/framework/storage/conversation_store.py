"""File-per-part ConversationStore implementation.

Each conversation part is stored as a separate JSON file under a
``parts/`` subdirectory.  Meta and cursor are stored as ``meta.json``
and ``cursor.json`` in the base directory.

The store is flat — all nodes in a continuous conversation share one
directory.  Each part carries a ``phase_id`` to identify which node
produced it.

Directory layout::

    {base_path}/          (typically ``{session}/conversations/``)
        meta.json         current node config (overwritten on transition)
        cursor.json       iteration counter, accumulator outputs, stall state
        parts/
            0000000000.json   (phase_id=node_a)
            0000000001.json   (phase_id=node_a)
            0000000002.json   (transition marker)
            0000000003.json   (phase_id=node_b)
            ...
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from framework.utils.io import atomic_write


class FileConversationStore:
    """File-per-part ConversationStore.

    Uses one JSON file per message part, with ``pathlib.Path`` for
    cross-platform path handling and ``asyncio.to_thread`` for
    non-blocking I/O.
    """

    def __init__(self, base_path: str | Path) -> None:
        self._base = Path(base_path)
        self._parts_dir = self._base / "parts"
        # Partial checkpoints for in-flight assistant turns. Written on every
        # stream event, deleted atomically when the final part lands. Kept
        # in a sibling dir so the parts/ glob doesn't pick them up.
        self._partials_dir = self._base / "partials"

    # --- sync helpers --------------------------------------------------------

    def _write_json(self, path: Path, data: dict) -> None:
        # Atomic tmp+rename with fsync — a crash mid-write would otherwise
        # leave a corrupt cursor.json and silently reset the iteration counter.
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_write(path) as f:
            json.dump(data, f)

    def _read_json(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return None

    # --- async wrapper -------------------------------------------------------

    async def _run(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    # --- ConversationStore interface -----------------------------------------

    async def write_part(self, seq: int, data: dict[str, Any]) -> None:
        path = self._parts_dir / f"{seq:010d}.json"
        await self._run(self._write_json, path, data)

    async def read_parts(self) -> list[dict[str, Any]]:
        def _read_all() -> list[dict[str, Any]]:
            if not self._parts_dir.exists():
                return []
            files = sorted(self._parts_dir.glob("*.json"))
            parts = []
            for f in files:
                data = self._read_json(f)
                if data is not None:
                    parts.append(data)
            return parts

        return await self._run(_read_all)

    async def write_meta(self, data: dict[str, Any]) -> None:
        await self._run(self._write_json, self._base / "meta.json", data)

    async def read_meta(self) -> dict[str, Any] | None:
        return await self._run(self._read_json, self._base / "meta.json")

    async def write_cursor(self, data: dict[str, Any]) -> None:
        await self._run(self._write_json, self._base / "cursor.json", data)

    async def read_cursor(self) -> dict[str, Any] | None:
        return await self._run(self._read_json, self._base / "cursor.json")

    async def write_partial(self, seq: int, data: dict[str, Any]) -> None:
        """Checkpoint an in-flight assistant turn. Overwrites any prior partial
        for the same seq. Caller is expected to clear_partial() once the real
        part is written via write_part().
        """
        path = self._partials_dir / f"{seq:010d}.json"
        await self._run(self._write_json, path, data)

    async def read_partial(self, seq: int) -> dict[str, Any] | None:
        path = self._partials_dir / f"{seq:010d}.json"
        return await self._run(self._read_json, path)

    async def read_all_partials(self) -> list[dict[str, Any]]:
        """Return all partial checkpoints, sorted by seq. Used during restore
        to surface any in-flight turn that the last process didn't finish.
        """

        def _read_all() -> list[dict[str, Any]]:
            if not self._partials_dir.exists():
                return []
            files = sorted(self._partials_dir.glob("*.json"))
            partials: list[dict[str, Any]] = []
            for f in files:
                data = self._read_json(f)
                if data is not None:
                    partials.append(data)
            return partials

        return await self._run(_read_all)

    async def clear_partial(self, seq: int) -> None:
        def _clear() -> None:
            path = self._partials_dir / f"{seq:010d}.json"
            if path.exists():
                path.unlink()

        await self._run(_clear)

    async def delete_parts_before(self, seq: int, run_id: str | None = None) -> None:
        def _delete() -> None:
            if not self._parts_dir.exists():
                return
            for f in self._parts_dir.glob("*.json"):
                file_seq = int(f.stem)
                if file_seq < seq:
                    f.unlink()

        await self._run(_delete)

    async def close(self) -> None:
        """No-op — no persistent handles for file-per-part storage."""
        pass

    async def clear(self) -> None:
        """Clear all parts and cursor, keeping the directory structure.

        Used when starting a fresh execution in the same session directory.
        """

        def _clear() -> None:
            # Clear all parts
            if self._parts_dir.exists():
                for f in self._parts_dir.glob("*.json"):
                    f.unlink()
            # Clear partial checkpoints
            if self._partials_dir.exists():
                for f in self._partials_dir.glob("*.json"):
                    f.unlink()
            # Clear cursor
            cursor_path = self._base / "cursor.json"
            if cursor_path.exists():
                cursor_path.unlink()
            # Clear meta
            meta_path = self._base / "meta.json"
            if meta_path.exists():
                meta_path.unlink()

        await self._run(_clear)

    async def destroy(self) -> None:
        """Delete the entire base directory and all persisted data."""

        def _destroy() -> None:
            if self._base.exists():
                shutil.rmtree(self._base)

        await self._run(_destroy)
