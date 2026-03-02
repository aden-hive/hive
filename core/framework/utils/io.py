import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_write(
    path: Path, mode: str = "w", encoding: str = "utf-8", perms: int | None = None
):
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        if perms is not None:
            # Use os.open to ensure permissions are set correctly from the start
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            fd = os.open(tmp_path, flags, perms)
            with os.fdopen(fd, mode, encoding=encoding) as f:
                yield f
                f.flush()
                os.fsync(f.fileno())
        else:
            with open(tmp_path, mode, encoding=encoding) as f:
                yield f
                f.flush()
                os.fsync(f.fileno())
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
