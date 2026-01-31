"""Console helpers for cross-platform output."""

from __future__ import annotations

import os
import sys
from typing import Iterable


def _iter_streams() -> Iterable[object]:
    """Yield available stdout/stderr streams."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            yield stream


def configure_console_output(encoding: str = "utf-8", errors: str = "replace") -> None:
    """Best-effort configure stdout/stderr to avoid UnicodeEncodeError on Windows."""
    if os.name != "nt":
        return

    for stream in _iter_streams():
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding=encoding, errors=errors)
            except Exception:
                # Best-effort only; never fail caller.
                pass

    # Hint for child processes started after this point.
    try:
        os.environ.setdefault("PYTHONUTF8", "1")
    except Exception:
        pass
