"""Unit tests for the built-in runtime resource monitor.

psutil and time are monkeypatched so the sampler is deterministic and offline:
we assert process→component attribution (incl. excluding Electron renderers from
the Chrome count), non-blocking CPU% deltas, history bounding, the health
verdict thresholds, and that a verdict transition logs exactly once.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque

import pytest

import framework.host.runtime_resources as rr

SELF_PID = 1000


# ── psutil fakes ─────────────────────────────────────────────────────────────
class _Mem:
    def __init__(self, rss_mb: float):
        self.rss = int(rss_mb * 1048576)


class _Cpu:
    def __init__(self, secs: float):
        self.user = secs
        self.system = 0.0


class _Proc:
    def __init__(self, pid, name, exe, cmdline, rss_mb, cpu_secs=0.0):
        self.pid = pid
        self.info = {
            "pid": pid,
            "name": name,
            "exe": exe,
            "cmdline": cmdline,
            "memory_info": _Mem(rss_mb),
            "cpu_times": _Cpu(cpu_secs),
        }


class _Handle:
    """Stands in for psutil.Process(pid); .children() returns descendants."""

    def __init__(self, kids):
        self._kids = kids

    def children(self, recursive=False):
        return self._kids


class _VM:
    def __init__(self, total_mb, avail_mb):
        self.total = int(total_mb * 1048576)
        self.available = int(avail_mb * 1048576)
        self.used = self.total - self.available
        self.percent = round(100.0 * self.used / self.total, 1)


def _install(monkeypatch, *, procs, descendant_pids, vm, now):
    """Wire fake psutil + clock into the module. Keeps real psutil exception
    classes so the module's except clauses still match."""
    monkeypatch.setattr(rr.os, "getpid", lambda: SELF_PID)
    monkeypatch.setattr(rr.time, "time", lambda: now[0])
    kids = [p for p in procs if p.pid in descendant_pids]
    monkeypatch.setattr(rr.psutil, "Process", lambda pid=SELF_PID: _Handle(kids))
    monkeypatch.setattr(rr.psutil, "process_iter", lambda attrs=None: list(procs))
    monkeypatch.setattr(rr.psutil, "virtual_memory", lambda: vm)


# ── attribution ──────────────────────────────────────────────────────────────
def test_sample_attribution_and_chrome_excludes_electron(monkeypatch):
    procs = [
        _Proc(SELF_PID, "python3", "/venv/bin/python3", ["python3", "-m", "framework.cli", "serve"], 150),
        _Proc(1001, "python3", "/venv/bin/python3", ["python3", "-m", "gcu.server", "--capabilities", "browser"], 90),
        _Proc(1002, "python3", "/venv/bin/python3", ["python3", "mcp_server.py", "--stdio"], 60),
        _Proc(2001, "python3", "/venv/bin/python3", ["python3", "-m", "gcu.bridge_host", "--supervise"], 80),  # detached, not a descendant
        _Proc(3001, "chrome", "/opt/google/chrome/chrome", ["/opt/google/chrome/chrome", "--type=renderer"], 200),
        _Proc(3002, "chrome", "/opt/google/chrome/chrome", ["/opt/google/chrome/chrome"], 300),  # MAIN chrome, not a renderer
        _Proc(4001, "code", "/usr/share/code/code", ["/usr/share/code/code", "--type=renderer"], 250),  # Electron — must NOT count as chrome
    ]
    _install(monkeypatch, procs=procs, descendant_pids={1001, 1002}, vm=_VM(31000, 12000), now=[100.0])
    m = rr.ResourceMonitor()
    s = m.sample({"active_workers": 2})

    assert s["components"]["hive_serve"]["procs"] == 1
    assert s["components"]["hive_serve"]["rss_mb"] == 150.0
    assert s["components"]["gcu"]["procs"] == 1 and s["components"]["gcu"]["rss_mb"] == 90.0
    assert s["components"]["mcp_servers"]["procs"] == 1
    assert s["components"]["bridge_host"]["procs"] == 1 and s["components"]["bridge_host"]["rss_mb"] == 80.0
    # Only the real chrome renderer — the main chrome process and the Electron
    # (VS Code) renderer are excluded.
    assert s["chrome"]["renderers"] == 1
    assert s["chrome"]["rss_mb"] == 200.0
    assert s["system"]["avail_mb"] == 12000
    assert s["verdict"] == "ok"


def test_cpu_pct_is_delta_over_wall(monkeypatch):
    now = [100.0]
    procs = [_Proc(SELF_PID, "python3", "/venv/bin/python3", ["python3", "serve"], 150, cpu_secs=10.0)]
    _install(monkeypatch, procs=procs, descendant_pids=set(), vm=_VM(31000, 12000), now=now)
    m = rr.ResourceMonitor()
    s1 = m.sample(None)
    assert s1["components"]["hive_serve"]["cpu_pct"] == 0.0  # first sight → no prior

    # 10s later, +5 cpu-seconds → 50% of one core.
    now[0] = 110.0
    procs[0].info["cpu_times"] = _Cpu(15.0)
    s2 = m.sample(None)
    assert s2["components"]["hive_serve"]["cpu_pct"] == pytest.approx(50.0, abs=0.1)


# ── verdict thresholds ───────────────────────────────────────────────────────
# Memory verdict is now fraction-of-total, not absolute MiB. Test values below
# use a 16000 MiB (16 GiB) total system, which yields warn=4000 MiB (25 %) and
# crit=2400 MiB (15 %) — deliberately close to the old absolute defaults so
# the pre-change semantics carry over on desktop-class hosts. A 4000 MiB VM
# (sandbox) would resolve to warn=1000 MiB / crit=600 MiB — verified in a
# separate assertion below.
def _mk(avail_mb, renderers, total_mb=16000):
    return {
        "system": {"avail_mb": avail_mb, "total_mb": total_mb},
        "chrome": {"renderers": renderers},
    }


def test_classify_thresholds():
    # Desktop-class 16 GiB: warn @ 4000 MiB, crit @ 2400 MiB.
    assert rr._classify(_mk(10000, 10))[0] == "ok"
    assert rr._classify(_mk(3500, 10))[0] == "warn"  # avail < 25% warn
    assert rr._classify(_mk(2000, 10))[0] == "critical"  # avail < 15% crit
    assert rr._classify(_mk(10000, 50))[0] == "warn"  # renderers > warn
    assert rr._classify(_mk(10000, 70))[0] == "critical"  # renderers > crit
    # worst-of-dimensions: warn memory + critical renderers → critical
    assert rr._classify(_mk(3500, 70))[0] == "critical"

    # Sandbox-class 4 GiB: warn @ 1000 MiB, crit @ 600 MiB. The old
    # absolute thresholds (5000/3000) fired "critical" at avail=1200 MiB
    # — pure noise on this VM class. Now avail=1200 MiB is "ok".
    assert rr._classify(_mk(1200, 3, total_mb=4000))[0] == "ok"
    assert rr._classify(_mk(900, 3, total_mb=4000))[0] == "warn"
    assert rr._classify(_mk(500, 3, total_mb=4000))[0] == "critical"


# ── history + transition logging ─────────────────────────────────────────────
def _sample(verdict="ok", avail=10000, renderers=10):
    return {
        "ts": 1.0,
        "system": {"avail_mb": avail, "pct": 50.0},
        "components": {"hive_serve": {"rss_mb": 100.0, "cpu_pct": 0.0, "procs": 1}},
        "chrome": {"renderers": renderers, "rss_mb": 1.0},
        "context": {"active_workers": 1},
        "verdict": verdict,
        "reasons": [],
    }


def test_history_is_bounded():
    m = rr.ResourceMonitor()
    m._history = deque(maxlen=3)
    for _ in range(6):
        m.record(_sample())
    assert len(m._history) == 3


def test_verdict_transition_logs_once(caplog):
    m = rr.ResourceMonitor()
    with caplog.at_level("INFO", logger="framework.host.runtime_resources"):
        m.record(_sample("ok"))  # init -> ok  (one transition, INFO)
        m.record(_sample("ok"))  # no change   (silent)
        m.record(_sample("warn"))  # ok -> warn  (WARNING)
        m.record(_sample("critical"))  # warn -> crit (ERROR)
        m.record(_sample("critical"))  # no change   (silent)
        m.record(_sample("ok"))  # crit -> ok  (INFO)
    transitions = [r for r in caplog.records if "verdict" in r.getMessage()]
    assert len(transitions) == 4  # init->ok, ok->warn, warn->crit, crit->ok
    levels = [r.levelname for r in transitions]
    assert "WARNING" in levels and "ERROR" in levels


# ── snapshot slicing ─────────────────────────────────────────────────────────
def test_snapshot_history_slicing():
    m = rr.ResourceMonitor()
    for i in range(10):
        s = _sample()
        s["ts"] = float(i)
        m.record(s)
    assert len(m.snapshot(history_n=0)["history"]) == 0
    assert len(m.snapshot(history_n=3)["history"]) == 3
    assert len(m.snapshot(history_n=None)["history"]) == 10
    snap = m.snapshot(history_n=3)
    assert snap["available"] is True
    assert snap["verdict"] == "ok"
    assert "warn_avail_mb" in snap["thresholds"]


def test_snapshot_when_never_sampled():
    m = rr.ResourceMonitor()
    snap = m.snapshot()
    assert snap["available"] is False and snap["verdict"] == "unknown"
    assert m.rollup() == {"verdict": "unknown"}


def test_history_entry_has_per_component_rss():
    """Each compact history entry carries per-bucket RSS so the UI can chart a
    trend for each component, not just the aggregate hive_rss_mb."""
    m = rr.ResourceMonitor()
    m.record(_sample())
    entry = m.snapshot(history_n=1)["history"][0]
    assert entry["comp_rss_mb"] == {"hive_serve": 100.0}
    # Aggregate still equals the sum of the per-bucket breakdown.
    assert entry["hive_rss_mb"] == round(sum(entry["comp_rss_mb"].values()), 1)


def test_sample_never_raises_on_psutil_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("psutil exploded")

    monkeypatch.setattr(rr.psutil, "process_iter", boom)
    monkeypatch.setattr(rr.psutil, "virtual_memory", boom)
    monkeypatch.setattr(rr.psutil, "Process", boom)
    m = rr.ResourceMonitor()
    s = m.sample({"active_workers": 0})  # must not raise
    assert s["chrome"]["renderers"] == 0
    assert s["system"]["avail_mb"] is None
    assert s["verdict"] == "ok"  # no signals → ok


# ── attribution: the *_tools_server.py MCP servers + no double-count ──────────
def test_tools_servers_bucket_as_mcp_not_other(monkeypatch):
    # The terminal/chart/memory MCP servers launch as `uv run python
    # <name>_tools_server.py --stdio` — they must land in mcp_servers, not other.
    procs = [
        _Proc(SELF_PID, "python3", "/venv/bin/python3", ["python3", "serve"], 100),
        _Proc(1101, "python3", "/venv/bin/python3", ["uv", "run", "python", "terminal_tools_server.py", "--stdio"], 40),
        _Proc(1102, "python3", "/venv/bin/python3", ["uv", "run", "python", "chart_tools_server.py", "--stdio"], 30),
        _Proc(1103, "python3", "/venv/bin/python3", ["uv", "run", "python", "memory_tools_server.py", "--stdio"], 20),
    ]
    _install(monkeypatch, procs=procs, descendant_pids={1101, 1102, 1103}, vm=_VM(31000, 12000), now=[1.0])
    s = rr.ResourceMonitor().sample(None)
    assert s["components"]["mcp_servers"]["procs"] == 3
    assert s["components"]["mcp_servers"]["rss_mb"] == 90.0
    assert s["components"]["other"]["procs"] == 0


def test_bridge_host_counted_once_even_if_descendant(monkeypatch):
    # A bridge_host that is ALSO in the descendant set must be bucketed once,
    # as bridge_host (the cmdline check precedes the descendant block).
    procs = [
        _Proc(SELF_PID, "python3", "/venv/bin/python3", ["python3", "serve"], 100),
        _Proc(2001, "python3", "/venv/bin/python3", ["python3", "-m", "gcu.bridge_host", "--supervise"], 80),
    ]
    _install(monkeypatch, procs=procs, descendant_pids={2001}, vm=_VM(31000, 12000), now=[1.0])
    s = rr.ResourceMonitor().sample(None)
    assert s["components"]["bridge_host"]["procs"] == 1
    assert s["components"]["gcu"]["procs"] == 0
    assert s["components"]["other"]["procs"] == 0


# ── CPU pid-reuse clamp ───────────────────────────────────────────────────────
def test_cpu_pct_clamps_to_zero_on_pid_reuse(monkeypatch):
    now = [100.0]
    procs = [_Proc(SELF_PID, "python3", "/venv/bin/python3", ["python3", "serve"], 100, cpu_secs=10.0)]
    _install(monkeypatch, procs=procs, descendant_pids=set(), vm=_VM(31000, 12000), now=now)
    m = rr.ResourceMonitor()
    m.sample(None)  # prime: pid SELF_PID cpu=10
    # Next tick the cumulative cpu went DOWN (pid reused by a new process) —
    # the delta must clamp to 0, never go negative.
    now[0] = 110.0
    procs[0].info["cpu_times"] = _Cpu(2.0)
    s2 = m.sample(None)
    assert s2["components"]["hive_serve"]["cpu_pct"] == 0.0


# ── cross-platform chrome renderer detection ──────────────────────────────────
@pytest.mark.parametrize(
    "name,exe,cmd,expected",
    [
        # Linux
        ("chrome", "/opt/google/chrome/chrome", "/opt/google/chrome/chrome --type=renderer", True),
        # macOS renderer helper
        ("Google Chrome Helper (Renderer)", "/Applications/Google Chrome.app/.../Helper", "... --type=renderer", True),
        # Windows
        ("chrome.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe", "chrome.exe --type=renderer", True),
        # Chromium
        ("chromium", "/usr/lib/chromium/chromium", "/usr/lib/chromium/chromium --type=renderer", True),
        # Electron renderer (VS Code) — must be EXCLUDED
        ("code", "/usr/share/code/code", "/usr/share/code/code --type=renderer", False),
        # Chrome main process (no --type=renderer) — not a renderer
        ("chrome", "/opt/google/chrome/chrome", "/opt/google/chrome/chrome", False),
        # GPU process under chrome — not a renderer
        ("chrome", "/opt/google/chrome/chrome", "/opt/google/chrome/chrome --type=gpu-process", False),
    ],
)
def test_is_chrome_renderer_cross_platform(name, exe, cmd, expected):
    assert rr._is_chrome_renderer(name, exe, cmd.lower()) is expected


# ── verdict threshold boundaries (< vs > correctness) ─────────────────────────
def test_classify_threshold_boundaries():
    # Memory thresholds are now fractions of total_mb; resolve them for the
    # 16000 MiB total the default _mk uses.
    TOTAL = 16000
    W = int(TOTAL * rr._WARN_AVAIL_FRAC)
    C = int(TOTAL * rr._CRIT_AVAIL_FRAC)
    assert rr._classify(_mk(W, 10))[0] == "ok"  # avail == warn → ok (strict <)
    assert rr._classify(_mk(W - 1, 10))[0] == "warn"
    assert rr._classify(_mk(C, 10))[0] == "warn"  # avail == crit → warn (strict <)
    assert rr._classify(_mk(C - 1, 10))[0] == "critical"
    wr, cr = rr._WARN_RENDERERS, rr._CRIT_RENDERERS
    assert rr._classify(_mk(10000, wr))[0] == "ok"  # == warn → ok (strict >)
    assert rr._classify(_mk(10000, wr + 1))[0] == "warn"
    assert rr._classify(_mk(10000, cr))[0] == "warn"  # == crit → warn (strict >)
    assert rr._classify(_mk(10000, cr + 1))[0] == "critical"


# ── env-override safety ───────────────────────────────────────────────────────
def test_env_num_falls_back_on_garbage(caplog):
    with caplog.at_level("WARNING", logger="framework.host.runtime_resources"):
        assert rr._env_num("HIVE_X_UNSET_VAR", 42, int) == 42  # unset → default
        import os as _os

        _os.environ["HIVE_X_BAD"] = "not-a-number"
        try:
            assert rr._env_num("HIVE_X_BAD", 7, int) == 7  # garbage → default + warn
        finally:
            del _os.environ["HIVE_X_BAD"]
    assert any("invalid" in r.getMessage().lower() for r in caplog.records)


# ── sampler loop lifecycle (app.py) ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_sampler_loop_survives_tick_error_and_cancels_clean(monkeypatch):
    from framework.server import app as appmod

    monkeypatch.setattr(rr, "SAMPLE_INTERVAL_S", 0.01)
    calls = {"sample": 0, "record": 0}

    class _FakeMon:
        def sample(self, ctx):
            calls["sample"] += 1
            if calls["sample"] == 1:
                raise RuntimeError("transient probe failure")  # must NOT kill the loop
            return {"verdict": "ok"}

        def record(self, s):
            calls["record"] += 1

    monkeypatch.setattr(rr, "get_monitor", lambda: _FakeMon())

    async def _fake_probe():
        return {"connected": True}

    monkeypatch.setattr(appmod, "_probe_browser_bridge", _fake_probe)
    monkeypatch.setattr(appmod, "_runtime_resource_context", lambda app: {"active_workers": 0})

    task = asyncio.create_task(appmod._resource_sampler_loop({}))
    await asyncio.sleep(0.08)  # several ticks, incl. the one that raises
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert calls["sample"] >= 2  # kept sampling after the first tick raised
    assert calls["record"] >= 1  # at least one successful record
