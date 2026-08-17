import os
import time
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

        max_retries = 10 if os.name == "nt" else 1
        for attempt in range(max_retries):
            try:
                tmp_path.replace(path)
                break
            except PermissionError:
                if attempt < max_retries - 1:
                    time.sleep(0.01)
                else:
                    raise
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
