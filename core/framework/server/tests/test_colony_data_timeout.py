"""The colony data endpoints must fail fast (503) instead of hanging when the
shared thread pool is saturated.

Regression for the swarm hang: hung browser-MCP tool calls leak default-pool
threads; the colony tables/rows handlers used un-timed ``asyncio.to_thread``
reads and so waited for a free thread forever, piling up unanswered requests.
They now wrap the off-loop resolve+read in ``asyncio.wait_for`` and return 503.
"""

from __future__ import annotations

import time

import pytest
from aiohttp.test_utils import make_mocked_request

import framework.server.routes_colony_workers as rcw


def _slow_resolve(_colony_id):
    # Simulate the resolve/read being stuck on a saturated pool: block longer
    # than the (shrunk) timeout while running on the worker thread.
    time.sleep(0.5)
    return None


@pytest.mark.asyncio
async def test_table_rows_times_out_to_503(monkeypatch) -> None:
    monkeypatch.setattr(rcw, "_resolve_tracker_db_by_name", _slow_resolve)
    monkeypatch.setattr(rcw, "_COLONY_DATA_READ_TIMEOUT_S", 0.05)
    req = make_mocked_request(
        "GET",
        "/api/colonies/c1/data/tables/t1/rows",
        match_info={"colony_id": "c1", "table": "t1"},
    )
    resp = await rcw.handle_table_rows(req)
    assert resp.status == 503


@pytest.mark.asyncio
async def test_list_tables_times_out_to_503(monkeypatch) -> None:
    monkeypatch.setattr(rcw, "_resolve_tracker_db_by_name", _slow_resolve)
    monkeypatch.setattr(rcw, "_COLONY_DATA_READ_TIMEOUT_S", 0.05)
    req = make_mocked_request("GET", "/api/colonies/c1/data/tables", match_info={"colony_id": "c1"})
    resp = await rcw.handle_list_tables(req)
    assert resp.status == 503


@pytest.mark.asyncio
async def test_list_tables_ok_when_no_db(monkeypatch) -> None:
    """A fast 'no tracker.db' resolve still returns 200 (empty), not 503."""
    monkeypatch.setattr(rcw, "_resolve_tracker_db_by_name", lambda _c: None)
    req = make_mocked_request("GET", "/api/colonies/c1/data/tables", match_info={"colony_id": "c1"})
    resp = await rcw.handle_list_tables(req)
    assert resp.status == 200
