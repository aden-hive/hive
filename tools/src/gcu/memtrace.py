"""Opt-in memory tracing for diagnosing gcu.server retention.

gcu.server can accumulate hundreds of MB of *retained* Python objects over a
long browser-automation session (a real reference leak — verified not to be
malloc fragmentation: freed transients return to the OS cleanly in this env).
Static analysis can't see where the references are held (likely a library/C
layer or a reference cycle), so this module captures the answer at runtime.

Enable with ``HIVE_GCU_MEMTRACE=1``. A daemon thread then periodically logs:
  - current RSS,
  - the tracemalloc allocation sites that GREW the most since the previous tick
    (a monotonic leak's source is whatever keeps showing up here), and
  - a histogram of live object counts by type (catches an accumulating type
    even when tracemalloc attribution is spread across many small sites).

Output goes through the ``gcu.memtrace`` logger. In stdio mode the MCP client
discards stderr, so pair this with ``GCU_LOG_FILE=/tmp/gcu.log`` to read it.

Zero cost when the env var is unset: tracemalloc is never started and no thread
is spawned. tracemalloc itself adds per-allocation overhead, so this is strictly
a debugging switch, not something to leave on in production.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import tracemalloc
from collections import Counter

logger = logging.getLogger("gcu.memtrace")

_started = False


def _truthy(val: str) -> bool:
    return val.strip().lower() not in ("", "0", "false", "no", "off")


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (ValueError, TypeError):
        return default


def _rss_mb() -> float:
    """Resident set size in MB from /proc (Linux). -1 if unavailable."""
    try:
        with open(f"/proc/{os.getpid()}/statm") as fh:
            resident_pages = int(fh.read().split()[1])
        return resident_pages * (os.sysconf("SC_PAGE_SIZE") / (1024 * 1024))
    except (OSError, ValueError, IndexError):
        return -1.0


def _objtype_histogram(top: int) -> str:
    """Live-object counts grouped by type name. Walks the whole heap, so it is
    only run in debug mode at a slow cadence."""
    import gc

    counts: Counter[str] = Counter(type(o).__name__ for o in gc.get_objects())
    return ", ".join(f"{name}={n}" for name, n in counts.most_common(top))


def _loop(interval_s: float, top_n: int) -> None:
    prev: tracemalloc.Snapshot | None = None
    while True:
        time.sleep(interval_s)
        try:
            snap = tracemalloc.take_snapshot()
            traced, peak = tracemalloc.get_traced_memory()
            logger.warning(
                "memtrace tick: rss=%.0fMB traced=%.0fMB peak=%.0fMB",
                _rss_mb(),
                traced / 1e6,
                peak / 1e6,
            )
            # The leak's source is whatever keeps GROWING tick over tick.
            if prev is not None:
                for stat in snap.compare_to(prev, "traceback")[:top_n]:
                    if stat.size_diff <= 0:
                        continue
                    frames = stat.traceback.format()
                    logger.warning(
                        "memtrace grew +%.1fMB (%+d objs) at:\n    %s",
                        stat.size_diff / 1e6,
                        stat.count_diff,
                        "\n    ".join(frames[-4:]),
                    )
            else:
                for stat in snap.statistics("traceback")[:top_n]:
                    frames = stat.traceback.format()
                    logger.warning(
                        "memtrace top %.1fMB (%d objs) at:\n    %s",
                        stat.size / 1e6,
                        stat.count,
                        "\n    ".join(frames[-4:]),
                    )
            prev = snap
            logger.warning("memtrace objtypes: %s", _objtype_histogram(top_n + 7))
        except Exception:
            logger.exception("memtrace tick failed")


def maybe_start() -> None:
    """Start memory tracing iff ``HIVE_GCU_MEMTRACE`` is truthy. Idempotent and
    a safe no-op otherwise."""
    global _started
    if _started or not _truthy(os.environ.get("HIVE_GCU_MEMTRACE", "")):
        return
    frames = _env_int("HIVE_GCU_MEMTRACE_FRAMES", 12, 1)
    interval_s = float(_env_int("HIVE_GCU_MEMTRACE_INTERVAL_S", 60, 10))
    top_n = _env_int("HIVE_GCU_MEMTRACE_TOP", 8, 1)
    # Optional dedicated file sink. Needed for processes (e.g. bridge_host) that
    # don't wire a GCU_LOG_FILE root handler — without it the gcu.memtrace logger
    # would propagate to a handler-less root and be lost. When attached we stop
    # propagation so a process that DOES have a root file handler (gcu.server)
    # doesn't double-log.
    sink = os.environ.get("HIVE_GCU_MEMTRACE_FILE", "").strip()
    if sink:
        handler = logging.FileHandler(sink, mode="a", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(handler)
        logger.propagate = False
        logger.setLevel(logging.WARNING)
    tracemalloc.start(frames)
    threading.Thread(target=_loop, args=(interval_s, top_n), name="gcu-memtrace", daemon=True).start()
    _started = True
    logger.warning(
        "gcu memtrace ENABLED (interval=%.0fs frames=%d top=%d) — set GCU_LOG_FILE to capture it",
        interval_s,
        frames,
        top_n,
    )
