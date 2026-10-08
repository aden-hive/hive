#!/usr/bin/env python
"""Per-process memory breakdown for a running Hive runtime.

The runtime's headline "RSS" is misleading: a live runtime is a *fan* of
processes — the main ``hive serve`` process, one ``uv run python`` per stdio
MCP server (files-tools / gcu-tools / hive_tools), the detached bridge_host
supervisor + worker, and a full Chrome multi-process tree. Summing each
process's RSS double-counts shared pages (Chrome's zygote copy-on-write, the
shared ``libpython`` / ``.so`` mappings every interpreter maps), so the total
reads far higher than the memory actually resident uniquely.

This tool attributes the footprint per process using **PSS** (proportional set
size — shared pages divided across the processes that map them) and **USS**
(unique/private set size), so you can see how much of the headline is real and
which category of process actually holds the memory.

Usage:
    uv run python scripts/mem_report.py            # one-shot table
    uv run python scripts/mem_report.py --json     # machine-readable
    uv run python scripts/mem_report.py --watch 5  # resample every 5s
    uv run python scripts/mem_report.py --pid 1234 # anchor on a runtime PID

PSS/USS are read from ``/proc/<pid>/smaps`` (Linux) and require the same user
as the target process (or root). Run as the runtime user (``appuser`` in the
sandbox) or root; processes that can't be read are reported as skipped.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a core dependency
    print(
        "psutil is required. Run inside the runtime venv: "
        "`uv run python scripts/mem_report.py`",
        file=sys.stderr,
    )
    sys.exit(2)


# --- process categorisation -------------------------------------------------
#
# Markers are matched against the joined command line. Order matters: Chrome is
# checked first (its renderers carry many flags), then the bridge_host before
# the gcu MCP server (so ``-m gcu.bridge_host`` doesn't fall through to a
# broader ``gcu`` match), then the remaining stdio MCP entrypoints, then the
# main runtime.

_CHROME_TOKENS = ("chrome", "chromium", "headless_shell", "chrome-headless-shell")


def categorize(cmdline: list[str]) -> str:
    """Bucket a process by its command line. Returns a category label."""
    cmd = " ".join(cmdline)

    # Chrome / Chromium tree — sub-type from the renderer/gpu/utility flag.
    low = cmd.lower()
    if any(tok in low for tok in _CHROME_TOKENS):
        ctype = "browser"
        for part in cmdline:
            if part.startswith("--type="):
                ctype = part.split("=", 1)[1] or "browser"
                break
        return f"chrome:{ctype}"

    if "gcu.bridge_host" in cmd:
        return "bridge_host"
    if "gcu.server" in cmd:
        return "mcp:gcu-tools"
    if "mcp_server.py" in cmd:
        return "mcp:hive_tools"
    if "files_server.py" in cmd:
        return "mcp:files-tools"
    if "terminal_tools_server.py" in cmd:
        return "mcp:terminal-tools"
    if "chart_tools_server.py" in cmd:
        return "mcp:chart-tools"
    if "hive serve" in cmd or ("hive" in cmd and "serve" in cmdline) or "framework.loader" in cmd:
        return "runtime-main"
    return "other"


# --- discovery & sampling ---------------------------------------------------


def _safe_cmdline(proc: psutil.Process) -> list[str]:
    try:
        return proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return []


def discover_pids(root_pid: int | None) -> set[int]:
    """Collect the PIDs that make up the runtime.

    Combines two strategies so detached children (Chrome, bridge_host are
    started with ``start_new_session`` / Popen and are *not* descendants of
    ``hive serve``) are still captured:
      1. a global cmdline scan for known runtime markers, and
      2. the recursive child tree of the runtime root.
    """
    pids: set[int] = set()
    roots: list[int] = []

    for proc in psutil.process_iter(["pid", "cmdline"]):
        cmdline = proc.info.get("cmdline") or []
        if not cmdline:
            continue
        cat = categorize(cmdline)
        if cat != "other":
            pids.add(proc.info["pid"])
        if cat == "runtime-main":
            roots.append(proc.info["pid"])

    if root_pid is not None:
        roots = [root_pid]
        pids.add(root_pid)

    for r in roots:
        try:
            parent = psutil.Process(r)
            pids.add(r)
            for child in parent.children(recursive=True):
                pids.add(child.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return pids


class Sample:
    """One process's memory snapshot."""

    __slots__ = ("pid", "category", "rss", "pss", "uss", "cmd")

    def __init__(self, pid: int, category: str, rss: int, pss: int, uss: int, cmd: str):
        self.pid = pid
        self.category = category
        self.rss = rss
        self.pss = pss
        self.uss = uss
        self.cmd = cmd


def collect(pids: set[int]) -> tuple[list[Sample], int, int]:
    """Read memory for each pid. Returns (samples, n_gone, n_denied)."""
    samples: list[Sample] = []
    gone = denied = 0
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            cmdline = proc.cmdline()
            mi = proc.memory_full_info()
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            gone += 1
            continue
        except psutil.AccessDenied:
            denied += 1
            continue
        # pss/uss exist on Linux; fall back to rss-derived values elsewhere.
        rss = getattr(mi, "rss", 0)
        pss = getattr(mi, "pss", 0) or rss
        uss = getattr(mi, "uss", 0) or rss
        cmd = " ".join(cmdline) if cmdline else f"(pid {pid})"
        samples.append(Sample(pid, categorize(cmdline), rss, pss, uss, cmd))
    return samples, gone, denied


# --- formatting -------------------------------------------------------------


def human(nbytes: int) -> str:
    mib = nbytes / (1024 * 1024)
    if mib >= 1024:
        return f"{mib / 1024:.2f} GiB"
    return f"{mib:6.1f} MiB"


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def build_report(samples: list[Sample], gone: int, denied: int) -> dict:
    """Aggregate samples into a serialisable report."""
    cats: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "rss": 0, "pss": 0, "uss": 0})
    tot_rss = tot_pss = tot_uss = 0
    for s in samples:
        c = cats[s.category]
        c["count"] += 1
        c["rss"] += s.rss
        c["pss"] += s.pss
        c["uss"] += s.uss
        tot_rss += s.rss
        tot_pss += s.pss
        tot_uss += s.uss
    return {
        "processes": [
            {"pid": s.pid, "category": s.category, "rss": s.rss, "pss": s.pss, "uss": s.uss, "cmd": s.cmd}
            for s in sorted(samples, key=lambda x: x.pss, reverse=True)
        ],
        "categories": dict(sorted(cats.items(), key=lambda kv: kv[1]["pss"], reverse=True)),
        "totals": {"count": len(samples), "rss": tot_rss, "pss": tot_pss, "uss": tot_uss},
        "skipped": {"gone": gone, "access_denied": denied},
    }


def print_report(report: dict) -> None:
    procs = report["processes"]
    if not procs:
        print("No runtime processes found. Is `hive serve` running? "
              "(use --pid to anchor on a specific PID)")
        return

    # Per-process table, sorted by PSS desc.
    print(f"{'CATEGORY':<18} {'PID':>7} {'RSS':>11} {'PSS':>11} {'USS':>11}  CMD")
    print("-" * 100)
    for p in procs:
        print(
            f"{p['category']:<18} {p['pid']:>7} "
            f"{human(p['rss']):>11} {human(p['pss']):>11} {human(p['uss']):>11}  "
            f"{_truncate(p['cmd'], 44)}"
        )

    # Per-category subtotals.
    print()
    print(f"{'CATEGORY':<18} {'COUNT':>7} {'RSS':>11} {'PSS':>11} {'USS':>11}")
    print("-" * 62)
    for cat, c in report["categories"].items():
        print(
            f"{cat:<18} {c['count']:>7} "
            f"{human(c['rss']):>11} {human(c['pss']):>11} {human(c['uss']):>11}"
        )

    t = report["totals"]
    shared = t["rss"] - t["pss"]
    print("-" * 62)
    print(f"{'TOTAL':<18} {t['count']:>7} {human(t['rss']):>11} {human(t['pss']):>11} {human(t['uss']):>11}")
    print()
    print("Headline:")
    print(f"  Summed RSS = {human(t['rss'])}   <- the inflated 'how much is it using' number")
    print(f"  Summed PSS = {human(t['pss'])}   <- true unique footprint (shared pages counted once)")
    print(f"  Shared / double-counted = {human(shared)}   ({100 * shared / t['rss']:.0f}% of summed RSS)")

    if any(c.startswith("chrome") for c in report["categories"]):
        print()
        print("Note: chrome:* covers ALL Chrome/Chromium on this host. In an isolated sandbox "
              "that is the runtime's browser; on a\n      shared/dev machine it also includes "
              "unrelated browsers. Use --no-chrome to isolate the Python runtime footprint.")

    sk = report["skipped"]
    if sk["gone"] or sk["access_denied"]:
        print()
        print(f"Skipped: {sk['gone']} exited mid-scan, {sk['access_denied']} access-denied "
              f"(run as the runtime user or root to read their PSS).")

    print()
    print("Deeper attribution once you know the dominant process:")
    print("  - per-import cost:  python -X importtime -m <entrypoint>  2>importtime.log")
    print("  - per-allocation :  set HIVE_GCU_MEMTRACE=1 (see tools/src/gcu/memtrace.py)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-process PSS/USS breakdown for a running Hive runtime.")
    ap.add_argument("--pid", type=int, default=None,
                    help="Anchor on this runtime root PID instead of auto-detecting `hive serve`.")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    ap.add_argument("--watch", type=float, default=None, metavar="SECS",
                    help="Resample every SECS seconds until interrupted.")
    ap.add_argument("--no-chrome", action="store_true",
                    help="Exclude chrome:* processes and focus on the Python runtime footprint.")
    args = ap.parse_args()

    def one_pass() -> dict:
        pids = discover_pids(args.pid)
        samples, gone, denied = collect(pids)
        if args.no_chrome:
            samples = [s for s in samples if not s.category.startswith("chrome")]
        return build_report(samples, gone, denied)

    if args.watch:
        try:
            while True:
                report = one_pass()
                if args.json:
                    print(json.dumps(report))
                else:
                    print(f"\n=== {time.strftime('%H:%M:%S')} ===")
                    print_report(report)
                time.sleep(args.watch)
        except KeyboardInterrupt:
            return 0

    report = one_pass()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
