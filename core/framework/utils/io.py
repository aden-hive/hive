import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def atomic_write(path: Path, mode: str = "w", encoding: str = "utf-8"):
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        kwargs = {"mode": mode}
        if "b" not in mode:
            kwargs["encoding"] = encoding
        with open(tmp_path, **kwargs) as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
