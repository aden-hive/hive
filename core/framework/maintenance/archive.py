"""Archive-then-delete disposal for the retention janitor.

Wraps the plain DeleteDisposer: every file/tree is archived under
``$HIVE_HOME/archive/janitor-<stamp>/`` with member paths relative to
HIVE_HOME, so untarring the archives over a directory reproduces the
original layout (the hive-eval training exporter globs
``**/conversations/parts`` and can be pointed at an extracted archive).

Each disposal target gets its OWN tarball, fully written, fsynced, and
atomically renamed into place BEFORE its source is deleted. One shared
run-long tar stream would be torn by a crash or a failed member add —
every already-deleted source would sit in an unreadable archive. With
per-item archives the worst crash outcome is an orphan tarball next to
an intact source (a rerun re-archives it).

Compression is stdlib tar.gz only — no new dependencies.
"""

from __future__ import annotations

import logging
import os
import tarfile
import time
from pathlib import Path

from framework import config
from framework.maintenance.retention import DeleteDisposer, assert_safe_target

logger = logging.getLogger(__name__)


class ArchiveDisposer:
    """Tar each disposal target (relative to HIVE_HOME), then delete it."""

    dry_run = False
    archives = True

    def __init__(self, archive_dir: Path | None = None) -> None:
        self._inner = DeleteDisposer()
        self._hive_home = config.HIVE_HOME.resolve()
        root = archive_dir or (config.HIVE_HOME / "archive")
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self._run_dir = root / f"janitor-{stamp}"
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._seq = 0
        self.members = 0

    @property
    def archive_path(self) -> Path:
        return self._run_dir

    def _archive_one(self, path: Path) -> None:
        """Write one durable tarball for ``path``; raises on any failure."""
        arcname = str(path.resolve().relative_to(self._hive_home))
        self._seq += 1
        final = self._run_dir / f"{self._seq:05d}-{path.name}.tar.gz"
        tmp = final.with_suffix(final.suffix + ".tmp")
        try:
            with tarfile.open(tmp, "w:gz") as tar:
                tar.add(path, arcname=arcname, recursive=True)
            with open(tmp, "rb") as f:
                os.fsync(f.fileno())
            tmp.replace(final)
        except (OSError, tarfile.TarError) as exc:
            tmp.unlink(missing_ok=True)
            # Do NOT delete what we failed to archive.
            raise OSError(f"archive failed for {path}: {exc}") from exc
        self.members += 1

    def dispose_file(self, path: Path) -> int:
        assert_safe_target(path)
        self._archive_one(path)
        return self._inner.dispose_file(path)

    def dispose_dir(self, path: Path) -> tuple[int, int]:
        assert_safe_target(path)
        self._archive_one(path)
        return self._inner.dispose_dir(path)

    def close(self) -> Path | None:
        """Return the run's archive dir, or None if nothing was archived."""
        if self.members == 0:
            try:
                self._run_dir.rmdir()
            except OSError:
                return self._run_dir
            return None
        return self._run_dir
