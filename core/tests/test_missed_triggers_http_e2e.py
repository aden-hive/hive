"""HTTP-level tests for ``POST /colony/resolve_missed``.

The endpoint takes the user's per-trigger decision after a
``MISSED_TRIGGERS`` event arrives on session load. The handler body
delegates to ``resolve_missed`` in ``queen_lifecycle_tools`` — unit
tested in ``test_missed_triggers.py``. These tests cover the HTTP
wiring: JSON parsing, status codes, and the per-trigger result map.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import framework.config as _cfg
from framework.host.event_bus import EventBus
from framework.host.triggers import TriggerDefinition
from framework.server.routes_sessions import register_routes

pytestmark = pytest.mark.asyncio


class _StubManager:
    """SessionManager double — get_session is the only method the
    resolve_missed route calls."""

    def __init__(self) -> None:
        self._sessions: dict = {}

    def add(self, session) -> None:
        self._sessions[session.id] = session

    def get_session(self, sid):
        return self._sessions.get(sid)


def _make_session(session_id: str, colony_id: str):
    colony_dir = _cfg.COLONIES_DIR / colony_id
    queen_node = SimpleNamespace(inject_trigger=AsyncMock())
    executor = SimpleNamespace(node_registry={"queen": queen_node})
    return SimpleNamespace(
        id=session_id,
        colony_id=colony_id,
        worker_path=colony_dir,
        event_bus=EventBus(),
        available_triggers={},
        active_trigger_ids=set(),
        active_timer_tasks={},
        active_webhook_subs={},
        trigger_next_fire={},
        trigger_fire_stats={},
        queen_executor=executor,
        runner=None,
    )


def _seed_colony(colony_id: str, triggers: list[dict]) -> None:
    colony_dir = _cfg.COLONIES_DIR / colony_id
    colony_dir.mkdir(parents=True, exist_ok=True)
    (colony_dir / "metadata.json").write_text(json.dumps({"name": colony_id}), encoding="utf-8")
    (colony_dir / "triggers.json").write_text(json.dumps(triggers, indent=2), encoding="utf-8")


def _build_app(manager: _StubManager) -> web.Application:
    app = web.Application()
    app["manager"] = manager
    register_routes(app)
    return app


@pytest_asyncio.fixture
async def http() -> AsyncIterator[tuple[TestClient, _StubManager]]:
    manager = _StubManager()
    app = _build_app(manager)
    server = TestServer(app)
    async with TestClient(server) as tc:
        yield tc, manager


async def test_resolve_missed_skip_via_http(http) -> None:
    client, manager = http
    triggers = [
        {
            "id": "hourly",
            "name": "hourly",
            "trigger_type": "timer",
            "trigger_config": {"interval_minutes": 60},
            "task": "go",
            "enabled": True,
            "last_fired_at": "2026-01-01T00:00:00+00:00",
            "next_due_at": None,
        }
    ]
    _seed_colony("c6", triggers=triggers)
    session = _make_session("s6", "c6")
    session.available_triggers["hourly"] = TriggerDefinition(
        id="hourly",
        trigger_type="timer",
        trigger_config={"interval_minutes": 60},
        description="hourly",
        task="go",
        enabled=True,
        last_fired_at="2026-01-01T00:00:00+00:00",
    )
    manager.add(session)

    resp = await client.post(
        "/api/sessions/s6/colony/resolve_missed",
        json={"decisions": {"hourly": "skip"}},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body == {"results": {"hourly": "skipped"}}
    queen = session.queen_executor.node_registry["queen"]
    assert queen.inject_trigger.await_count == 0


async def test_resolve_missed_fire_latest_injects_catch_up_via_http(http) -> None:
    client, manager = http
    triggers = [
        {
            "id": "daily",
            "name": "daily",
            "trigger_type": "timer",
            "trigger_config": {"cron": "0 9 * * *"},
            "task": "send",
            "enabled": True,
            "last_fired_at": "2026-05-18T09:00:00+00:00",
            "next_due_at": None,
        }
    ]
    _seed_colony("c7", triggers=triggers)
    session = _make_session("s7", "c7")
    session.available_triggers["daily"] = TriggerDefinition(
        id="daily",
        trigger_type="timer",
        trigger_config={"cron": "0 9 * * *"},
        description="daily",
        task="send",
        enabled=True,
        last_fired_at="2026-05-18T09:00:00+00:00",
    )
    manager.add(session)

    resp = await client.post(
        "/api/sessions/s7/colony/resolve_missed",
        json={"decisions": {"daily": "fire_latest"}},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body == {"results": {"daily": "fired"}}

    queen = session.queen_executor.node_registry["queen"]
    assert queen.inject_trigger.await_count == 1
    payload = queen.inject_trigger.await_args_list[0].args[0].payload
    assert payload.get("catch_up") is True


async def test_resolve_missed_rejects_non_dict_decisions(http) -> None:
    client, manager = http
    _seed_colony("c8", triggers=[])
    manager.add(_make_session("s8", "c8"))

    resp = await client.post(
        "/api/sessions/s8/colony/resolve_missed",
        json={"decisions": ["fire_latest", "skip"]},  # wrong shape
    )
    assert resp.status == 400


async def test_resolve_missed_returns_per_trigger_markers(http) -> None:
    """The handler returns a result map even when some inputs are bad,
    so the UI can show partial success rather than failing the whole
    handshake on one bad row."""
    client, manager = http
    _seed_colony("c9", triggers=[])
    manager.add(_make_session("s9", "c9"))

    resp = await client.post(
        "/api/sessions/s9/colony/resolve_missed",
        json={
            "decisions": {
                "ghost": "fire_latest",
                "bad": "explode",
            }
        },
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["results"]["ghost"] == "unknown_trigger"
    assert body["results"]["bad"].startswith("invalid_decision")


async def test_resolve_missed_404_for_unknown_session(http) -> None:
    client, _ = http
    resp = await client.post(
        "/api/sessions/ghost/colony/resolve_missed",
        json={"decisions": {}},
    )
    assert resp.status == 404


async def test_resolve_missed_409_when_session_has_no_colony(http) -> None:
    client, manager = http
    session = _make_session("s10", "c10")
    session.colony_id = None
    manager.add(session)

    resp = await client.post(
        "/api/sessions/s10/colony/resolve_missed",
        json={"decisions": {}},
    )
    assert resp.status == 409
