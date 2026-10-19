"""Unit tests for the playbook convergence runner.

The runner is decoupled from the colony via two injected callables, so these
tests drive it with a fake in-memory "tracker" whose rows a fake worker
advances — exercising convergence, retry, dead-letter, schema validation, lane
concurrency, and resume-by-requery without a live colony.
"""

from __future__ import annotations

import asyncio
import collections
import time

from framework.host.playbook.runner import PlaybookScriptError, run_playbook_script


def make_script(
    *,
    max_rounds: int = 4,
    retries: int = 2,
    chunk: int = 2,
    lane: bool = True,
    lane_concurrency: int = 2,
    rate_per_min: int | None = None,
) -> str:
    """Build a playbook mirroring the design's worked example."""
    rate_arg = f", rate_per_min={rate_per_min}" if rate_per_min is not None else ""
    lane_decl = f'lane("acct-1", concurrency={lane_concurrency}{rate_arg})\n' if lane else ""
    lane_arg = ', lane="acct-1"' if lane else ""
    return f"""
meta = {{"name": "test-enrich", "description": "converge the leads table",
        "phases": ["Enrich"]}}

RECEIPT = {{"type": "object", "required": ["slug", "status"],
           "properties": {{"slug": {{"type": "string"}},
                          "status": {{"enum": ["enriched", "no-data"]}}}}}}

{lane_decl}
async def run(args):
    await converge(
        pending=lambda: tracker_query("SELECT slug FROM leads WHERE done=0"),
        dispatch=lambda row, i: worker(
            task=f"Enrich {{row['slug']}}",
            data={{"slug": row["slug"]}},
            retries={retries}, schema=RECEIPT{lane_arg}),
        max_rounds={max_rounds},
        chunk={chunk},
    )
    remaining = tracker_count("SELECT slug FROM leads WHERE done=0")
    log(f"remaining={{remaining}}")
    return {{"remaining": remaining, "dead": deadletter.size}}
"""


class FakeColony:
    """In-memory tracker + worker. ``done`` is the row's done-predicate; a
    successful dispatch marks the row done (the worker advancing its own row)."""

    def __init__(self, slugs, *, fail_once=(), always_fail=(), bad_receipt=(), track_concurrency=False, dispatch_delay=0.01):
        self.rows = dict.fromkeys(slugs, False)
        self.fail_once = set(fail_once)
        self.always_fail = set(always_fail)
        self.bad_receipt = set(bad_receipt)
        self.attempts: collections.Counter = collections.Counter()
        self.profiles_seen: dict[str, str | None] = {}
        self.schemas_seen: dict[str, dict | None] = {}
        self.track_concurrency = track_concurrency
        self.dispatch_delay = dispatch_delay
        self._inflight = 0
        self.max_inflight = 0

    def query_rows(self, sql):
        # The test playbook has a single pending query; return undone rows.
        # Synchronous, matching the runner's tracker-read contract.
        return [{"slug": s} for s, done in self.rows.items() if not done]

    async def dispatch_one(self, task, *, data, profile, timeout, schema=None):
        slug = (data or {}).get("slug")
        self.attempts[slug] += 1
        self.profiles_seen[slug] = profile
        self.schemas_seen[slug] = schema
        if self.track_concurrency:
            self._inflight += 1
            self.max_inflight = max(self.max_inflight, self._inflight)
            await asyncio.sleep(self.dispatch_delay)
        try:
            if slug in self.always_fail:
                return {"status": "failed", "summary": "boom", "data": {}, "error": "permanent"}
            if slug in self.fail_once and self.attempts[slug] == 1:
                return {"status": "failed", "summary": "boom", "data": {}, "error": "transient"}
            if slug in self.bad_receipt:
                # Reports success but does NOT advance its row — a worker that
                # claims done while the tracker still says pending. The tracker is
                # the source of truth, so converge must NOT trust this into done.
                return {"status": "success", "summary": "ok", "data": {"oops": True}}
            self.rows[slug] = True
            return {"status": "success", "summary": "ok", "data": {"slug": slug, "status": "enriched"}}
        finally:
            if self.track_concurrency:
                self._inflight -= 1


def _run(colony, script=None, args=None, concurrency_cap=None):
    return asyncio.run(
        run_playbook_script(
            script if script is not None else make_script(),
            args=args,
            dispatch_one=colony.dispatch_one,
            query_rows=colony.query_rows,
            run_id="test",
            concurrency_cap=concurrency_cap,
        )
    )


def test_converges_all_rows():
    colony = FakeColony(["a", "b", "c", "d", "e"])
    out = _run(colony)
    assert out["result"]["remaining"] == 0
    assert out["result"]["dead"] == 0
    assert all(colony.rows.values())
    # Each row dispatched exactly once (no retries needed).
    assert all(colony.attempts[s] == 1 for s in colony.rows)


def test_retry_then_succeed():
    colony = FakeColony(["a", "b", "c"], fail_once={"b"})
    out = _run(colony)
    assert out["result"]["remaining"] == 0
    assert out["result"]["dead"] == 0
    # 'b' failed once then succeeded on the retry inside worker().
    assert colony.attempts["b"] == 2
    assert colony.attempts["a"] == 1


def test_permanent_failure_is_dead_lettered_once():
    colony = FakeColony(["a", "b"], always_fail={"b"})
    # max_rounds=1 so 'b' is attempted exactly retries+1 = 3 times.
    out = _run(colony, script=make_script(max_rounds=1))
    assert colony.rows["a"] is True
    assert colony.rows["b"] is False
    assert out["result"]["remaining"] == 1
    # Dead-lettered exactly once (converge owns it), not once per round.
    assert out["result"]["dead"] == 1
    dead = out["deadletter"]
    assert len(dead) == 1 and dead[0]["row"]["slug"] == "b"
    assert colony.attempts["b"] == 3


def test_tracker_is_truth_not_the_receipt():
    # Schema is enforced WORKER-SIDE now (it rides the spawn spec). The queen no
    # longer re-validates the receipt, so a "success" report is NOT trusted into
    # done — the TRACKER is the source of truth. Here the worker claims success
    # but never advances its row, so the row stays pending and is dead-lettered.
    colony = FakeColony(["a"], bad_receipt={"a"})
    out = _run(colony, script=make_script(max_rounds=1))
    assert colony.rows["a"] is False  # never advanced
    assert out["result"]["remaining"] == 1
    assert out["result"]["dead"] == 1  # caught by the tracker, not a receipt gate
    # Dispatched once: a "success" report is accepted, so there is NO shape-driven
    # retry (the tracker-blind retry that caused duplicate sends is gone).
    assert colony.attempts["a"] == 1


def test_schema_rides_the_spawn_spec():
    # The receipt schema reaches the worker dispatch (where it specializes
    # report_to_parent + the worker prompt) instead of being a queen-side gate.
    colony = FakeColony(["a", "b"])
    _run(colony, script=make_script(max_rounds=1))
    for slug in ("a", "b"):
        assert colony.schemas_seen[slug] is not None
        assert colony.schemas_seen[slug]["required"] == ["slug", "status"]


def test_lane_limits_concurrency():
    colony = FakeColony([str(i) for i in range(8)], track_concurrency=True)
    out = _run(colony)
    assert out["result"]["remaining"] == 0
    # lane concurrency=2 AND chunk=2 both bound in-flight to 2.
    assert colony.max_inflight <= 2


def test_rate_per_min_spaces_dispatches():
    # rate_per_min throttles the START rate: N dispatches in a lane are spaced
    # >= 60/rate apart. With lane concurrency high enough that the semaphore
    # never serializes, the gate is the ONLY thing imposing spacing, so the run
    # cannot finish before (N-1) * min_interval.
    colony = FakeColony([str(i) for i in range(4)], track_concurrency=True)
    t0 = time.monotonic()
    out = _run(
        colony,
        script=make_script(max_rounds=1, lane_concurrency=4, chunk=4, rate_per_min=600),  # 0.1s interval
    )
    elapsed = time.monotonic() - t0
    assert out["result"]["remaining"] == 0
    assert elapsed >= 0.29, f"expected >= 3*0.1s of spacing, got {elapsed:.3f}s"


def test_rate_per_min_none_no_throttle():
    # rate_per_min=None (the default everywhere today) => no gate => dispatches
    # are bounded only by concurrency. 8 rows at concurrency 8 finish in roughly
    # one dispatch_delay, well under any spacing a gate would impose.
    colony = FakeColony([str(i) for i in range(8)], track_concurrency=True)
    t0 = time.monotonic()
    out = _run(colony, script=make_script(max_rounds=1, lane_concurrency=8, chunk=8))
    elapsed = time.monotonic() - t0
    assert out["result"]["remaining"] == 0
    assert elapsed < 0.2, f"no throttle expected, but took {elapsed:.3f}s"


def test_rate_gate_composes_with_concurrency():
    # The gate (start-rate) and the semaphore (simultaneity) compose: the
    # semaphore still caps in-flight to `concurrency` even though chunk=4 would
    # otherwise let all four flow, AND the rows genuinely overlap (so the gate's
    # tiny spacing didn't serialize them). dispatch_delay > min_interval makes
    # the overlap observable.
    colony = FakeColony([str(i) for i in range(4)], track_concurrency=True, dispatch_delay=0.2)
    out = _run(
        colony,
        script=make_script(max_rounds=1, lane_concurrency=2, chunk=4, rate_per_min=600),  # 0.1s interval
    )
    assert out["result"]["remaining"] == 0
    assert colony.max_inflight <= 2, "lane semaphore must bound simultaneity to concurrency"
    assert colony.max_inflight == 2, "rows must actually overlap — the gate must not serialize a concurrency>1 lane"


def test_rerun_is_resume():
    colony = FakeColony(["a", "b", "c"])
    first = _run(colony)
    assert first["result"]["remaining"] == 0
    # Re-running the same playbook over the converged tracker dispatches nothing.
    second = _run(colony)
    assert second["dispatched"] == 0
    assert second["result"]["remaining"] == 0


def test_bad_script_missing_run():
    colony = FakeColony(["a"])
    try:
        _run(colony, script='meta = {"name": "x"}\n')
        raise AssertionError("expected PlaybookScriptError")
    except PlaybookScriptError as e:
        assert "run(args)" in str(e)


def test_bad_script_missing_meta():
    colony = FakeColony(["a"])
    try:
        _run(colony, script="async def run(args):\n    return 1\n")
        raise AssertionError("expected PlaybookScriptError")
    except PlaybookScriptError as e:
        assert "meta" in str(e)


def test_profile_rotates_to_dispatch():
    # Fix #1: rotating `profile` actually reaches the worker (accounts are spread).
    script = """
meta = {"name": "rotate", "description": "x"}
ACCOUNTS = ["p1", "p2", "p3"]


async def run(args):
    await converge(
        pending=lambda: tracker_query("SELECT slug FROM leads WHERE done=0"),
        dispatch=lambda row, i: worker(
            task=f"do {row['slug']}",
            data={"slug": row["slug"]},
            profile=ACCOUNTS[i % len(ACCOUNTS)]),
        max_rounds=1,
    )
"""
    colony = FakeColony(["a", "b", "c", "d"])
    _run(colony, script=script)
    # index 0..3 -> p1, p2, p3, p1 (rows in insertion order)
    assert colony.profiles_seen == {"a": "p1", "b": "p2", "c": "p3", "d": "p1"}


def test_chunk_defaults_to_cap():
    # Fix #2: with no chunk and no lane, the colony cap still bounds in-flight.
    colony = FakeColony([str(i) for i in range(8)], track_concurrency=True)
    out = _run(colony, script=make_script(chunk=None, lane=False), concurrency_cap=2)
    assert out["result"]["remaining"] == 0
    assert colony.max_inflight <= 2  # chunk defaulted to cap=2


def test_warns_when_chunk_exceeds_cap():
    # Fix #1: a chunk above the colony cap is surfaced, not silently throttled.
    colony = FakeColony(["a", "b"])
    out = _run(colony, script=make_script(chunk=50, lane=False), concurrency_cap=4)
    assert any("bounds this run" in line for line in out["logs"])


def test_warns_when_lane_exceeds_cap():
    # Fix #1: a lane concurrency above the colony cap is surfaced.
    colony = FakeColony(["a"])
    out = _run(colony, script=make_script(chunk=1), concurrency_cap=1)  # lane acct-1 conc=2 > 1
    assert any("exceeds the colony cap" in line for line in out["logs"])


def test_load_is_synchronous_and_validates():
    # load() catches structure errors WITHOUT awaiting — so the tool can return
    # a faithful error instead of "started".
    from framework.host.playbook.runner import PlaybookRun

    colony = FakeColony([])
    r = PlaybookRun(dispatch_one=colony.dispatch_one, query_rows=colony.query_rows, run_id="t")
    try:
        r.load('meta = {"name": "x"}\n')  # no run()
        raise AssertionError("expected PlaybookScriptError")
    except PlaybookScriptError as e:
        assert "run(args)" in str(e)


def test_playbook_can_use_stdlib_imports():
    # The script runs in the colony's uv env — `import json` / `datetime` etc.
    # just work. No sandbox, no package enumeration.
    from framework.host.playbook.runner import PlaybookRun

    colony = FakeColony([])
    script = (
        "import json\n"
        "import datetime as dt\n"
        'meta = {"name": "x"}\n'
        "async def run(args):\n"
        '    return {"j": json.dumps({"a": 1}), "has_dt": dt.timezone is not None}\n'
    )
    r = PlaybookRun(dispatch_one=colony.dispatch_one, query_rows=colony.query_rows, run_id="t")
    out = asyncio.run(r.execute(script))
    assert out["result"]["j"] == '{"a": 1}'
    assert out["result"]["has_dt"] is True


def test_run_loaded_surfaces_runtime_error():
    # A NameError inside run() (the common LLM mistake) loads fine but raises
    # when executed — the tool's grace window catches this and returns it.
    from framework.host.playbook.runner import PlaybookRun

    colony = FakeColony([])
    script = 'meta = {"name": "x"}\nasync def run(args):\n    return undefined_name\n'
    r = PlaybookRun(dispatch_one=colony.dispatch_one, query_rows=colony.query_rows, run_id="t")
    r.load(script)  # loads without error
    try:
        asyncio.run(r.run_loaded(None))
        raise AssertionError("expected PlaybookScriptError")
    except PlaybookScriptError as e:
        assert "run() raised" in str(e)


def test_worker_goal_passes_through_to_dispatch():
    # WHY: the queen-authored `goal` titles the worker card in the UI. It must
    # ride worker(...) -> _dispatch_guarded -> dispatch_one unchanged — and be
    # OMITTED entirely when not set, so dispatch_one implementations (and
    # fakes) with the pre-goal signature keep working.
    from framework.host.playbook.runner import PlaybookRun

    captured: list[dict] = []

    async def dispatch_one(task, *, data, profile, timeout, schema=None, **kw):
        captured.append({"task": task, **kw})
        return {"status": "success", "summary": "ok", "data": {"done": True}}

    script = (
        'meta = {"name": "g"}\n'
        "async def run(args):\n"
        '    a = await worker("job A", goal="Checking 6 profiles")\n'
        '    b = await worker("job B")\n'
        '    return {"a": a["status"], "b": b["status"]}\n'
    )
    r = PlaybookRun(dispatch_one=dispatch_one, query_rows=lambda _sql: [], run_id="t")
    out = asyncio.run(r.execute(script))
    assert out["result"] == {"a": "done", "b": "done"}
    assert captured[0]["goal"] == "Checking 6 profiles"
    assert "goal" not in captured[1]  # omitted when unset, not passed as None
