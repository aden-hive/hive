"""Built-in system-resource monitor for the Hive runtime.

Why this exists: the 2026-06-12 OOM crash (a Chrome renderer leak ratcheting
to ~18 GB → global OOM → the desktop session died) was only caught by a
throwaway bash sampler in ``/tmp`` that vanished on reboot. The runtime had no
awareness of its own resource health. This module makes that a first-class,
inspectable feature: a background loop samples the runtime's process tree +
system memory, retains a bounded rolling history, classifies a health verdict,
and logs an early warning the moment the verdict degrades — the durable
replacement for the external monitor. Served at ``GET /api/health/resources``.

Process model (why attribution is the way it is): the ``hive serve`` process
spawns its MCP/gcu/terminal subprocesses as DESCENDANTS, but ``bridge_host`` is
detached (parented to the Electron shell) and Chrome is the user's own browser
the extension attaches to — neither is a child of ours. So we walk our own
descendant tree for the parts we own and locate ``bridge_host`` / Chrome
renderers by command line. Chrome renderers are matched on the chrome/chromium
executable specifically (NOT just ``--type=renderer``, which Electron apps —
VS Code, Slack, the Hive desktop shell — also use).

Module-level singleton: there is exactly one runtime per desktop process, so
global state is the right shape here (mirrors ``runtime_health.py``).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from typing import Any

import psutil

logger = logging.getLogger(__name__)


# ── Tunables (env-overridable) ──────────────────────────────────────────────
def _env_num(name: str, default: float, cast):
    """Parse a numeric env override, falling back (with a warning) on garbage.
    A bad value must never raise at import — that would take down the module
    (and the monitor) entirely."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return cast(default)
    try:
        return cast(raw)
    except (TypeError, ValueError):
        logger.warning("invalid %s=%r; using default %s", name, raw, default)
        return cast(default)


# Sampler cadence. The loop owns the sleep; exposed so the loop and tests agree.
SAMPLE_INTERVAL_S: float = _env_num("HIVE_RESOURCE_INTERVAL_S", 15.0, float)
# Rolling history depth. 480 × 15 s ≈ 2 h of trend, in-memory only.
_HISTORY_MAX: int = _env_num("HIVE_RESOURCE_HISTORY", 480, int)

# Health thresholds.
#
# Memory: expressed as FRACTIONS of total system memory, not absolute MiB.
# The old absolute defaults (5 GB warn / 3 GB crit) were tuned for a 16
# GiB+ desktop; on a 4 GiB sandbox VM they fire "critical" as steady
# state — Chrome + Xvfb + hive-serve idle at ~2.7 GiB used, so avail sits
# at 1.2 GiB, well under any 3 GiB absolute threshold. The user perceived
# this as "collapsing under tiny memory pressure" 2026-07-03; the log
# was actually thread-pool starvation, but the verdict noise was drowning
# any real signal. Fractions scale sensibly across host classes:
#   - 16 GiB desktop: warn @ 4 GiB, crit @ 2.4 GiB (≈ previous absolutes)
#   - 4 GiB sandbox:  warn @ 1 GiB, crit @ 600 MiB (a real signal)
_WARN_AVAIL_FRAC: float = _env_num("HIVE_RESOURCE_WARN_AVAIL_FRAC", 0.25, float)
_CRIT_AVAIL_FRAC: float = _env_num("HIVE_RESOURCE_CRIT_AVAIL_FRAC", 0.15, float)
# Renderers: headcount-based, host-class-independent — keep as absolute.
_WARN_RENDERERS: int = _env_num("HIVE_RESOURCE_WARN_RENDERERS", 45, int)
_CRIT_RENDERERS: int = _env_num("HIVE_RESOURCE_CRIT_RENDERERS", 60, int)

_BUCKETS = ("hive_serve", "bridge_host", "gcu", "mcp_servers", "other")


def _bucket_for(pid: int, self_pid: int, descendant_pids: set[int], cmd: str) -> str | None:
    """Classify a process into a Hive component bucket, or None if not ours.

    ``cmd`` is the lower-cased joined command line. Descendants of the runtime
    are definitely ours; bridge_host is matched by command line because it is
    detached (not in our tree).
    """
    if pid == self_pid:
        return "hive_serve"
    if "gcu.bridge_host" in cmd:
        return "bridge_host"
    if pid in descendant_pids:
        if "gcu.server" in cmd or "gcu." in cmd:
            return "gcu"
        # hive_tools is mcp_server.py; the terminal/chart/memory tools servers
        # are launched as `uv run python <name>_tools_server.py --stdio`, so
        # match the shared "tools_server" suffix too (without it they'd fall
        # through to "other", under-counting mcp_servers — see mcp_registry).
        if "mcp_server" in cmd or "tools_server" in cmd or "fastmcp" in cmd or "-m mcp" in cmd:
            return "mcp_servers"
        return "other"
    return None


def _is_chrome_renderer(name: str, exe: str, cmd: str) -> bool:
    """True for a Google Chrome / Chromium RENDERER process.

    Matched on the chrome/chromium executable AND ``--type=renderer`` so that
    Electron renderers (VS Code, Slack, the Hive desktop shell — which also pass
    ``--type=renderer``) are excluded: their executables are electron/Code/slack,
    not chrome.
    """
    if "--type=renderer" not in cmd:
        return False
    hay = f"{name} {exe}".lower()
    if "electron" in hay:  # defensive — an Electron build could embed "chrome"
        return False
    # macOS renderer helper is "Google Chrome Helper (Renderer)"; Linux exe is
    # .../google/chrome/chrome or chromium; Windows is chrome.exe.
    return "chrome" in hay or "chromium" in hay


class ResourceMonitor:
    """Samples the runtime's resource footprint and keeps a rolling history."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._history: deque[dict[str, Any]] = deque(maxlen=_HISTORY_MAX)
        self._last: dict[str, Any] | None = None
        self._last_verdict: str | None = None
        # Per-PID cpu-time + wall snapshot from the previous sample, for a
        # non-blocking CPU% (delta of cpu seconds over wall seconds). New PIDs
        # read 0% on their first appearance; dead PIDs are evicted each sample.
        self._prev_cpu: dict[int, float] = {}
        self._prev_wall: float | None = None

    # ── sampling ────────────────────────────────────────────────────────────
    def sample(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Take one resource snapshot. Never raises — a failed probe degrades
        that field to null/0 rather than killing the caller's loop."""
        now = time.time()
        wall_delta = (now - self._prev_wall) if self._prev_wall else None

        comps: dict[str, dict[str, Any]] = {b: {"rss_mb": 0.0, "cpu_pct": 0.0, "procs": 0} for b in _BUCKETS}
        chrome = {"renderers": 0, "rss_mb": 0.0}
        cur_cpu: dict[int, float] = {}

        try:
            self_pid = os.getpid()
            try:
                descendant_pids = {p.pid for p in psutil.Process(self_pid).children(recursive=True)}
            except Exception:
                descendant_pids = set()

            for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "memory_info", "cpu_times"]):
                try:
                    info = proc.info
                    pid = info["pid"]
                    cmd = " ".join(info.get("cmdline") or []).lower()
                    name = info.get("name") or ""
                    exe = info.get("exe") or ""
                    mem = info.get("memory_info")
                    rss_mb = (mem.rss / 1048576.0) if mem else 0.0
                    cputimes = info.get("cpu_times")
                    cpu_sec = (cputimes.user + cputimes.system) if cputimes else 0.0

                    bucket = _bucket_for(pid, self_pid, descendant_pids, cmd)
                    is_chrome = bucket is None and _is_chrome_renderer(name, exe, cmd)
                    if bucket is None and not is_chrome:
                        continue

                    cur_cpu[pid] = cpu_sec
                    # CPU% over the sample window (% of one core; can exceed 100).
                    cpu_pct = 0.0
                    if wall_delta and wall_delta > 0 and pid in self._prev_cpu:
                        cpu_pct = max(0.0, (cpu_sec - self._prev_cpu[pid]) / wall_delta * 100.0)

                    if is_chrome:
                        chrome["renderers"] += 1
                        chrome["rss_mb"] += rss_mb
                    else:
                        c = comps[bucket]
                        c["rss_mb"] += rss_mb
                        c["cpu_pct"] += cpu_pct
                        c["procs"] += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                except Exception:
                    continue
        except Exception:
            logger.debug("resource sample: process walk failed", exc_info=True)

        # System memory.
        try:
            vm = psutil.virtual_memory()
            system = {
                "total_mb": round(vm.total / 1048576.0),
                "used_mb": round(vm.used / 1048576.0),
                "avail_mb": round(vm.available / 1048576.0),
                "pct": vm.percent,
            }
        except Exception:
            system = {"total_mb": None, "used_mb": None, "avail_mb": None, "pct": None}

        # Round component numbers for a tidy payload.
        for c in comps.values():
            c["rss_mb"] = round(c["rss_mb"], 1)
            c["cpu_pct"] = round(c["cpu_pct"], 1)
        chrome["rss_mb"] = round(chrome["rss_mb"], 1)

        self._prev_cpu = cur_cpu
        self._prev_wall = now

        sample: dict[str, Any] = {
            "ts": now,
            "system": system,
            "components": comps,
            "chrome": chrome,
            "context": context or {},
        }
        verdict, reasons = _classify(sample)
        sample["verdict"] = verdict
        sample["reasons"] = reasons
        return sample

    # ── history + verdict transitions ────────────────────────────────────────
    def record(self, sample: dict[str, Any]) -> None:
        """Store a sample as current + a compact history entry, and log on a
        verdict transition (the early-warning the external monitor used to do)."""
        compact = {
            "ts": sample["ts"],
            "verdict": sample["verdict"],
            "avail_mb": sample["system"].get("avail_mb"),
            "sys_pct": sample["system"].get("pct"),
            "renderers": sample["chrome"]["renderers"],
            "chrome_rss_mb": sample["chrome"]["rss_mb"],
            "hive_rss_mb": round(sum(c["rss_mb"] for c in sample["components"].values()), 1),
            # Per-bucket RSS so the UI can chart each component's trend, not just
            # the aggregate. Keyed by bucket name; ~5 floats per entry (cheap).
            "comp_rss_mb": {b: round(c["rss_mb"], 1) for b, c in sample["components"].items()},
            "active_workers": sample["context"].get("active_workers"),
        }
        with self._lock:
            self._history.append(compact)
            self._last = sample
            prev = self._last_verdict
            self._last_verdict = sample["verdict"]

        if sample["verdict"] != prev:
            self._log_transition(prev, sample)

    def _log_transition(self, prev: str | None, sample: dict[str, Any]) -> None:
        v = sample["verdict"]
        msg = "runtime-resources verdict %s->%s | avail=%sMB renderers=%d chrome_rss=%.0fMB hive_rss=%.0fMB workers=%s | %s"
        args = (
            prev or "init",
            v,
            sample["system"].get("avail_mb"),
            sample["chrome"]["renderers"],
            sample["chrome"]["rss_mb"],
            sum(c["rss_mb"] for c in sample["components"].values()),
            sample["context"].get("active_workers"),
            "; ".join(sample["reasons"]) or "ok",
        )
        if v == "critical":
            logger.error(msg, *args)
        elif v == "warn":
            logger.warning(msg, *args)
        else:
            logger.info(msg, *args)

    def snapshot(self, history_n: int | None = 120) -> dict[str, Any]:
        """Current sample + thresholds + a slice of compact history.

        ``history_n=None`` → full buffer; ``0`` → snapshot only.
        """
        with self._lock:
            last = dict(self._last) if self._last else None
            if history_n is None:
                hist = list(self._history)
            elif history_n <= 0:
                hist = []
            else:
                hist = list(self._history)[-history_n:]
        # Resolve fraction-based memory thresholds against the last sample's
        # total_mb so callers see absolute values matching what _classify
        # compared against. Falls back to raw fractions when there's no
        # sample yet (first request before the sampler ticks).
        total_mb = (last or {}).get("system", {}).get("total_mb")
        if isinstance(total_mb, (int, float)) and total_mb > 0:
            warn_avail_mb: float = round(total_mb * _WARN_AVAIL_FRAC)
            crit_avail_mb: float = round(total_mb * _CRIT_AVAIL_FRAC)
        else:
            warn_avail_mb = _WARN_AVAIL_FRAC
            crit_avail_mb = _CRIT_AVAIL_FRAC
        out: dict[str, Any] = {
            "available": last is not None,
            "interval_s": SAMPLE_INTERVAL_S,
            "thresholds": {
                "warn_avail_mb": warn_avail_mb,
                "crit_avail_mb": crit_avail_mb,
                "warn_avail_frac": _WARN_AVAIL_FRAC,
                "crit_avail_frac": _CRIT_AVAIL_FRAC,
                "warn_renderers": _WARN_RENDERERS,
                "crit_renderers": _CRIT_RENDERERS,
            },
            "history": hist,
        }
        if last is not None:
            out.update(last)
        else:
            out["verdict"] = "unknown"
        return out

    def rollup(self) -> dict[str, Any]:
        """Compact health summary for folding into /api/health."""
        with self._lock:
            last = self._last
        if not last:
            return {"verdict": "unknown"}
        return {
            "verdict": last["verdict"],
            "avail_mb": last["system"].get("avail_mb"),
            "renderers": last["chrome"]["renderers"],
        }


def _classify(sample: dict[str, Any]) -> tuple[str, list[str]]:
    """Worst-of-dimensions health verdict with human reasons."""
    reasons: list[str] = []
    rank = {"ok": 0, "warn": 1, "critical": 2}
    worst = "ok"

    def bump(level: str, reason: str) -> None:
        nonlocal worst
        reasons.append(reason)
        if rank[level] > rank[worst]:
            worst = level

    avail = sample["system"].get("avail_mb")
    total = sample["system"].get("total_mb") or 0
    if isinstance(avail, (int, float)) and total > 0:
        # Compare against fraction-of-total so a 4 GiB VM and a 32 GiB
        # desktop use the same relative pressure signal.
        warn_th = total * _WARN_AVAIL_FRAC
        crit_th = total * _CRIT_AVAIL_FRAC
        if avail < crit_th:
            bump("critical", f"system available {avail:.0f}MB < {crit_th:.0f} ({_CRIT_AVAIL_FRAC:.0%} of {total:.0f}MB total, critical)")
        elif avail < warn_th:
            bump("warn", f"system available {avail:.0f}MB < {warn_th:.0f} ({_WARN_AVAIL_FRAC:.0%} of {total:.0f}MB total, warn)")

    renderers = sample["chrome"]["renderers"]
    if renderers > _CRIT_RENDERERS:
        bump("critical", f"{renderers} chrome renderers > {_CRIT_RENDERERS} (critical)")
    elif renderers > _WARN_RENDERERS:
        bump("warn", f"{renderers} chrome renderers > {_WARN_RENDERERS} (warn)")

    return worst, reasons


# Module-level singleton.
_MONITOR = ResourceMonitor()


def get_monitor() -> ResourceMonitor:
    return _MONITOR
