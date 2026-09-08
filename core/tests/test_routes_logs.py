"""Regression tests for the log HTTP routes.

These live in ``core/tests/`` rather than ``core/framework/server/tests/``
because only this directory is collected by ``make test``. The sibling suite
under ``framework/server/`` already covers these routes but is not wired into
any test command, which is how an ``UnboundLocalError`` on the success path of
both handlers survived: ``log_store = ...`` sat inside the
``if not session.colony_runtime`` guard, after its ``return``, so it was dead
code and the name was never bound on the normal path.

The handlers are driven directly with a stub request. That keeps the test
independent of the aiohttp app wiring (and of the ``graphs``/``colonies`` route
prefix mismatch in the sibling suite) while still exercising the exact lines
that broke.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from framework.server.routes_logs import handle_logs, handle_node_logs
from framework.tracker.runtime_log_schemas import NodeDetail, NodeStepLog, RunSummaryLog
from framework.tracker.runtime_log_store import RuntimeLogStore

_SID = "session_20250101_000000_logs"


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubRequest:
    """The minimum surface ``resolve_session`` and the handlers touch."""

    def __init__(self, session, query=None, match_info=None):
        self.app = {"manager": SimpleNamespace(get_session=lambda _sid: session)}
        self.match_info = {"session_id": "test_agent", **(match_info or {})}
        self.query = query or {}


def _session(log_store) -> SimpleNamespace:
    """A session whose colony_runtime carries a real log store."""
    return SimpleNamespace(colony_runtime=SimpleNamespace(_runtime_log_store=log_store))


def _body(response) -> dict:
    return json.loads(response.body.decode())


@pytest.fixture
def store(tmp_path: Path) -> RuntimeLogStore:
    """A store holding one run with a summary, one node, and two steps."""
    log_store = RuntimeLogStore(tmp_path)
    log_store.ensure_session_run_dir(_SID)
    log_store.append_node_detail(_SID, NodeDetail(node_id="node_a", node_name="A", success=True, tokens_used=42))
    log_store.append_node_detail(_SID, NodeDetail(node_id="node_b", node_name="B", success=True))
    log_store.append_step(_SID, NodeStepLog(node_id="node_a", step_index=0, llm_text="hello"))
    log_store.append_step(_SID, NodeStepLog(node_id="node_b", step_index=0, llm_text="world"))
    summary = RunSummaryLog(run_id=_SID, agent_id="test_agent", status="success", total_nodes_executed=2)
    (tmp_path / "sessions" / _SID / "logs" / "summary.json").write_text(
        json.dumps(summary.model_dump()), encoding="utf-8"
    )
    return log_store


# ---------------------------------------------------------------------------
# handle_logs — the success path that used to raise UnboundLocalError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logs_lists_run_summaries(store: RuntimeLogStore) -> None:
    response = await handle_logs(_StubRequest(_session(store)))
    assert response.status == 200
    logs = _body(response)["logs"]
    assert [entry["run_id"] for entry in logs] == [_SID]
    assert logs[0]["status"] == "success"


@pytest.mark.asyncio
async def test_logs_returns_summary_for_one_session(store: RuntimeLogStore) -> None:
    request = _StubRequest(_session(store), query={"session_id": _SID, "level": "summary"})
    response = await handle_logs(request)
    assert response.status == 200
    assert _body(response)["total_nodes_executed"] == 2


@pytest.mark.asyncio
async def test_logs_returns_node_details(store: RuntimeLogStore) -> None:
    request = _StubRequest(_session(store), query={"session_id": _SID, "level": "details"})
    response = await handle_logs(request)
    assert response.status == 200
    body = _body(response)
    assert body["session_id"] == _SID
    assert [node["node_id"] for node in body["nodes"]] == ["node_a", "node_b"]


@pytest.mark.asyncio
async def test_logs_returns_tool_steps(store: RuntimeLogStore) -> None:
    request = _StubRequest(_session(store), query={"session_id": _SID, "level": "tools"})
    response = await handle_logs(request)
    assert response.status == 200
    assert [step["llm_text"] for step in _body(response)["steps"]] == ["hello", "world"]


@pytest.mark.asyncio
async def test_logs_survives_a_bad_limit(store: RuntimeLogStore) -> None:
    """A non-numeric limit falls back to the default rather than 500ing."""
    response = await handle_logs(_StubRequest(_session(store), query={"limit": "not-a-number"}))
    assert response.status == 200


# ---------------------------------------------------------------------------
# handle_logs — guard branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logs_503_without_a_worker() -> None:
    response = await handle_logs(_StubRequest(SimpleNamespace(colony_runtime=None)))
    assert response.status == 503


@pytest.mark.asyncio
async def test_logs_404_when_logging_disabled() -> None:
    response = await handle_logs(_StubRequest(_session(None)))
    assert response.status == 404
    assert _body(response)["error"] == "Logging not enabled for this agent"


@pytest.mark.asyncio
async def test_logs_404_for_unknown_worker_session(store: RuntimeLogStore) -> None:
    request = _StubRequest(_session(store), query={"session_id": "session_does_not_exist"})
    response = await handle_logs(request)
    assert response.status == 404


# ---------------------------------------------------------------------------
# handle_node_logs — same defect, same file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_logs_scopes_to_one_node(store: RuntimeLogStore) -> None:
    request = _StubRequest(
        _session(store),
        query={"session_id": _SID},
        match_info={"node_id": "node_a"},
    )
    response = await handle_node_logs(request)
    assert response.status == 200
    body = _body(response)
    assert body["node_id"] == "node_a"
    # Only node_a's rows come back, not node_b's.
    assert [node["node_id"] for node in body["details"]] == ["node_a"]
    assert [step["llm_text"] for step in body["tool_logs"]] == ["hello"]


@pytest.mark.asyncio
async def test_node_logs_400_without_session_id(store: RuntimeLogStore) -> None:
    request = _StubRequest(_session(store), match_info={"node_id": "node_a"})
    response = await handle_node_logs(request)
    assert response.status == 400


@pytest.mark.asyncio
async def test_node_logs_404_when_logging_disabled() -> None:
    request = _StubRequest(_session(None), match_info={"node_id": "node_a"})
    response = await handle_node_logs(request)
    assert response.status == 404
