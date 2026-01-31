import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_write(path: Path, mode: str = "w", encoding: str = "utf-8"):
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp_path, mode, encoding=encoding) as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
