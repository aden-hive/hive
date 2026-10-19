import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_write(path: Path, mode: str = "w", encoding: str = "utf-8"):
    """tempfile + os.replace so readers never observe a half-written file.

    The temp name comes from ``tempfile.mkstemp`` — UNIQUE per writer. The
    previous fixed ``<name>.tmp`` scheme made concurrent writers of the same
    file (two coroutines, or two processes sharing a HIVE_HOME) truncate
    each other's temp file mid-write, and the loser's cleanup could delete
    the winner's temp before its rename — corrupting cursor.json /
    summary.json / reminder_state.json under load.
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
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
