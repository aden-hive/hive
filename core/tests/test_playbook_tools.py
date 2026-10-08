"""Tests for run_playbook tool helpers — specifically the rows-extraction that
prevents a trailing-semicolon pending query from looking like convergence (#3)."""

from __future__ import annotations

from framework.tools.playbook_tools import _extract_rows_result


def test_extract_rows_kind_passthrough():
    res = {"kind": "rows", "columns": ["a"], "rows": [[1]]}
    assert _extract_rows_result(res) is res


def test_extract_script_kind_trailing_semicolon():
    # execute_sql returns kind="script" for a query with a trailing ';' —
    # the rows must still be found, else converge sees [] = "converged".
    res = {
        "kind": "script",
        "results": [{"kind": "rows", "columns": ["a"], "rows": [[1], [2]]}],
    }
    out = _extract_rows_result(res)
    assert out is not None and out["rows"] == [[1], [2]]


def test_extract_script_uses_last_rows_result():
    res = {
        "kind": "script",
        "results": [
            {"kind": "exec", "rowcount": 0},
            {"kind": "rows", "columns": ["a"], "rows": [[9]]},
        ],
    }
    assert _extract_rows_result(res)["rows"] == [[9]]


def test_extract_exec_kind_is_none():
    assert _extract_rows_result({"kind": "exec", "rowcount": 1}) is None


def test_extract_script_without_rows_is_none():
    assert _extract_rows_result({"kind": "script", "results": [{"kind": "exec"}]}) is None


def test_error_detail_surfaces_original_cause():
    """A run() failure is wrapped in PlaybookScriptError; _error_detail must
    still expose the ORIGINAL error (type + message + line) via the cause chain —
    that's what was missing from the log before."""
    import asyncio

    from framework.host.playbook import PlaybookRun, PlaybookScriptError
    from framework.tools.playbook_tools import _error_detail

    async def _dispatch(**_kwargs):
        return {}

    run = PlaybookRun(dispatch_one=_dispatch, query_rows=lambda _sql: [], run_id="t")
    run.load('meta = {"name": "x"}\nasync def run(args):\n    return undefined_name\n')
    try:
        asyncio.run(run.run_loaded(None))
        raise AssertionError("expected PlaybookScriptError")
    except PlaybookScriptError as exc:
        concise, tb = _error_detail(exc)
        # Concise names the ROOT cause + playbook line, not the wrapper.
        assert concise.startswith("NameError:")
        assert "undefined_name" in concise
        assert "playbook line 3" in concise  # `return undefined_name` is line 3
        # Full traceback retains everything.
        assert "undefined_name" in tb and "NameError" in tb


def test_persist_script_enables_resume(tmp_path):
    """Inline scripts are saved to colony scope so the queen can re-run by path
    (resume) and edit the file to iterate — without re-supplying the script."""
    from framework.tools.playbook_tools import _persist_script, _sanitize_name

    assert _sanitize_name("Reactor Outreach Batch!") == "reactor-outreach-batch"
    assert _sanitize_name("   ") == "playbook"

    p = _persist_script(tmp_path, "Reactor Outreach Batch!", "meta = {}\n# v1\n")
    assert p is not None and p.exists()
    assert p.name == "reactor-outreach-batch.play.py"
    assert p.parent.name == "playbooks"
    assert "# v1" in p.read_text()

    # Re-saving the same-named playbook overwrites — the edit-and-re-run loop.
    p2 = _persist_script(tmp_path, "Reactor Outreach Batch!", "meta = {}\n# v2\n")
    assert p2 == p and "# v2" in p.read_text()


def test_resolve_script_three_sources(tmp_path):
    """Inline / saved-name / path resolution, with clear errors."""
    from framework.tools.playbook_tools import _persist_script, _resolve_script

    pdir = tmp_path / "playbooks"

    # inline
    script, src, err = _resolve_script("meta={}\n# inline", None, None, pdir)
    assert err is None and src is None and "# inline" in script

    # more than one source -> error
    _, _, err = _resolve_script("x", "y", None, pdir)
    assert err and "exactly ONE" in err

    # saved name (after persisting one)
    _persist_script(tmp_path, "Enrich Leads", "meta={}\n# saved")
    script, src, err = _resolve_script(None, None, "Enrich Leads", pdir)
    assert err is None and "# saved" in script
    assert src is not None and src.endswith("enrich-leads.play.py")

    # unknown name -> helpful error listing the library
    _, _, err = _resolve_script(None, None, "nope", pdir)
    assert err and "no saved playbook named 'nope'" in err and "enrich-leads" in err


def test_resolve_concurrency_queen_declared():
    """The queen programs concurrency in meta; we honor it, rejecting only when
    it exceeds the hard ceiling."""
    from framework.tools.playbook_tools import (
        _DEFAULT_PLAYBOOK_CONCURRENCY,
        _MAX_PLAYBOOK_CONCURRENCY,
        _resolve_concurrency,
    )

    # declared value honored
    n, err = _resolve_concurrency({"concurrency": 12})
    assert err is None and n == 12

    # default when omitted
    n, err = _resolve_concurrency({})
    assert err is None and n == _DEFAULT_PLAYBOOK_CONCURRENCY

    # too big -> rejected with a clear, actionable error
    n, err = _resolve_concurrency({"concurrency": _MAX_PLAYBOOK_CONCURRENCY + 1})
    assert n == 0 and err and "exceeds the maximum" in err

    # non-integer -> rejected
    n, err = _resolve_concurrency({"concurrency": "lots"})
    assert n == 0 and err and "must be an integer" in err

    # floor at 1
    n, err = _resolve_concurrency({"concurrency": 0})
    assert err is None and n == 1


def test_playbook_tools_are_colony_queen_only():
    """Every playbook tool must be visible to the COLONY-phase queen only, never
    to the independent-phase queen, and stripped from spawned workers."""
    from framework.agents.queen.nodes import _QUEEN_COLONY_TOOLS, _QUEEN_INDEPENDENT_TOOLS
    from framework.server.routes_execution import _resolve_queen_only_tools

    queen_only = _resolve_queen_only_tools()
    for tool in ("run_playbook", "list_playbook_runs", "get_playbook_status", "stop_playbook"):
        assert tool in _QUEEN_COLONY_TOOLS  # colony-phase queen sees it
        assert tool not in _QUEEN_INDEPENDENT_TOOLS  # independent queen does not
        assert tool in queen_only  # stripped from workers (no recursion)
    # Same classification as the renamed low-level fan-out tool.
    assert "run_worker" in queen_only and "run_worker" in _QUEEN_COLONY_TOOLS


def test_stop_batch_workers_targets_only_the_batch():
    """_stop_batch_workers stops only active workers of the given batch."""
    import asyncio
    from types import SimpleNamespace

    from framework.tools.playbook_tools import _stop_batch_workers

    stopped: list[str] = []

    class FakeColony:
        def __init__(self):
            self._workers = {
                "w1": SimpleNamespace(id="w1", batch_id="pb_A", is_active=True),
                "w2": SimpleNamespace(id="w2", batch_id="pb_A", is_active=False),  # already done
                "w3": SimpleNamespace(id="w3", batch_id="pb_B", is_active=True),  # other batch
            }

        async def stop_worker(self, wid):
            stopped.append(wid)

    n = asyncio.run(_stop_batch_workers(FakeColony(), "pb_A"))
    assert n == 1 and stopped == ["w1"]  # only the active worker in pb_A


def test_stop_playbooks_for_colony_cancels_only_its_runs():
    """stop_playbooks_for_colony cancels the convergence loops owned by the given
    colony (so they stop re-dispatching), scoped by colony identity so another
    colony's run is untouched. In-flight workers are intentionally left running —
    the caller's stop_worker pass stops them with the normal grace window."""
    import asyncio

    from framework.tools.playbook_tools import (
        _RUNNING_PLAYBOOKS,
        stop_playbooks_for_colony,
    )

    colony_a = object()
    colony_b = object()

    async def scenario():
        async def forever():
            await asyncio.Event().wait()

        task_a = asyncio.create_task(forever())
        task_b = asyncio.create_task(forever())
        await asyncio.sleep(0)  # let both suspend at the await
        _RUNNING_PLAYBOOKS["run_a"] = {"task": task_a, "run": None, "colony": colony_a}
        _RUNNING_PLAYBOOKS["run_b"] = {"task": task_b, "run": None, "colony": colony_b}
        try:
            cancelled = await stop_playbooks_for_colony(colony_a)
            # Capture state BEFORE teardown — the finally block cancels task_b.
            a_cancelled = task_a.cancelled()
            b_cancelled = task_b.cancelled()
        finally:
            _RUNNING_PLAYBOOKS.pop("run_a", None)
            _RUNNING_PLAYBOOKS.pop("run_b", None)
            task_b.cancel()
            await asyncio.gather(task_a, task_b, return_exceptions=True)
        return cancelled, a_cancelled, b_cancelled

    cancelled, a_cancelled, b_cancelled = asyncio.run(scenario())
    assert cancelled == ["run_a"]  # only colony_a's run
    assert a_cancelled is True  # its convergence loop was cancelled
    assert b_cancelled is False  # colony_b's run untouched until we tore it down
