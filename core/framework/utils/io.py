import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

_MAX_REPLACE_RETRIES = 5
_REPLACE_RETRY_DELAY = 0.01


@contextmanager
def atomic_write(path: Path, mode: str = "w", encoding: str = "utf-8"):
    """tempfile + os.replace so readers never observe a half-written file.

    The temp name comes from ``tempfile.mkstemp`` — UNIQUE per writer. The
    previous fixed ``<name>.tmp`` scheme made concurrent writers of the same
    file (two coroutines, or two processes sharing a HIVE_HOME) truncate
    each other's temp file mid-write, and the loser's cleanup could delete
    the winner's temp before its rename — corrupting cursor.json /
    summary.json / reminder_state.json under load.

    On Windows, ``os.replace`` can raise ``PermissionError`` when the
    destination is momentarily held open by another handle (antivirus
    scanner, search indexer, concurrent reader). We retry a few times
    with a short backoff to tolerate this transient sharing violation.
    """
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        if "b" in mode:
            f = os.fdopen(fd, mode)
        else:
            f = os.fdopen(fd, mode, encoding=encoding)
        with f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retry(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _replace_with_retry(src: Path, dst: Path) -> None:
    """Replace *dst* with *src*, retrying on transient Windows sharing violations."""
    last_err: OSError | None = None
    for attempt in range(_MAX_REPLACE_RETRIES):
        try:
            src.replace(dst)
            return
        except PermissionError as exc:
            if sys.platform != "win32":
                raise
            last_err = exc
            time.sleep(_REPLACE_RETRY_DELAY * (attempt + 1))
    raise last_err  # type: ignore[misc]
