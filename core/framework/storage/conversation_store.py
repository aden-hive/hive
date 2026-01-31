"""File-per-part ConversationStore implementation.

Each conversation part is stored as a separate JSON file under a
``parts/`` subdirectory.  Meta and cursor are stored as ``meta.json``
and ``cursor.json`` in the base directory.

Directory layout::

    {base_path}/
        meta.json
        cursor.json
        parts/
            0000000000.json
            0000000001.json
            ...
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any


class FileConversationStore:
    """File-per-part ConversationStore.

    Uses one JSON file per message part, with ``pathlib.Path`` for
    cross-platform path handling and ``asyncio.to_thread`` for
    non-blocking I/O.
    """

    def __init__(self, base_path: str | Path) -> None:
        self._base = Path(base_path)
        self._parts_dir = self._base / "parts"

    # --- sync helpers --------------------------------------------------------

    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _read_json(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
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

    async def delete_parts_before(self, seq: int) -> None:
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

    async def destroy(self) -> None:
        """Delete the entire base directory and all persisted data."""
        def _destroy() -> None:
            if self._base.exists():
                shutil.rmtree(self._base)

        await self._run(_destroy)
