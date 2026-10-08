"""HTTP-wiring tests for the Sentinel config/connect routes.

The heavy logic (store, notifier, token) is unit-tested elsewhere; here we
cover JSON parsing, status codes, colony 404s, and that handlers call through
to the store/notifier. httpx + notifier are stubbed — no network.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import framework.host.colony_metadata as cmeta
import framework.sentinel.notifier as notifier
import framework.sentinel.store as store
from framework.server.routes_sentinel import register_routes

pytestmark = pytest.mark.asyncio


class _Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


def _fake_httpx(resp):
    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            return _Resp(resp)

        async def post(self, url, json=None, headers=None):
            return _Resp(resp)

    return lambda *a, **k: _Client()


@pytest_asyncio.fixture
async def http(tmp_path, monkeypatch) -> AsyncIterator[TestClient]:
    root = tmp_path / "colonies"
    (root / "c1").mkdir(parents=True)
    (root / "c1" / "metadata.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(store, "COLONIES_DIR", root)
    monkeypatch.setattr(cmeta, "COLONIES_DIR", root)
    monkeypatch.setattr(store, "get_hive_config", lambda: {"sentinel": {"enabled": True}})
    app = web.Application()
    register_routes(app)
    async with TestClient(TestServer(app)) as tc:
        yield tc


# ----- config GET/PUT -----------------------------------------------------


async def test_get_notifications_default(http, monkeypatch):
    monkeypatch.setattr(notifier, "telegram_token", lambda: None)
    monkeypatch.setattr(notifier, "slack_bot_token", lambda: None)
    monkeypatch.setattr(notifier, "slack_app_token", lambda: None)
    resp = await http.get("/api/colony/c1/notifications")
    assert resp.status == 200
    data = await resp.json()
    # On by default via the built-in Hive Inbox channel (no token needed).
    assert data["sentinel_enabled"] is True
    assert data["channel"] == "hive"
    assert data["credentials"]["telegram"]["configured"] is False


async def test_get_notifications_404(http):
    resp = await http.get("/api/colony/ghost/notifications")
    assert resp.status == 404


async def test_put_notifications_saves(http, monkeypatch):
    monkeypatch.setattr(notifier, "telegram_token", lambda: "T")
    monkeypatch.setattr(notifier, "slack_bot_token", lambda: None)
    monkeypatch.setattr(notifier, "slack_app_token", lambda: None)
    body = {
        "sentinel_enabled": True,
        "channel": "telegram",
        "target": {"chat_id": "9"},
        "allowlist": ["42"],
    }
    resp = await http.put("/api/colony/c1/notifications", json=body)
    assert resp.status == 200
    data = await resp.json()
    assert data["sentinel_enabled"] is True
    assert data["channel"] == "telegram"
    # Persisted.
    assert store.load_notifications_config("c1").target == {"chat_id": "9"}


async def test_put_rejects_enabled_without_channel(http):
    resp = await http.put("/api/colony/c1/notifications", json={"sentinel_enabled": True})
    assert resp.status == 400


# ----- credential status + connect helpers --------------------------------


async def test_credential_status(http, monkeypatch):
    monkeypatch.setattr(notifier, "telegram_token", lambda: "T")
    monkeypatch.setattr(notifier, "slack_bot_token", lambda: "xoxb")
    monkeypatch.setattr(notifier, "slack_app_token", lambda: None)
    resp = await http.get("/api/sentinel/credentials")
    data = await resp.json()
    assert data["telegram"]["configured"] is True
    assert data["slack"]["bot"] is True
    assert data["slack"]["app"] is False


async def test_telegram_validate_ok(http, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _fake_httpx({"ok": True, "result": {"username": "mybot", "first_name": "My Bot"}}))
    resp = await http.post("/api/sentinel/telegram/validate", json={"token": "123:abc"})
    data = await resp.json()
    assert data["ok"] is True
    assert data["bot_username"] == "mybot"


async def test_telegram_validate_bad_token(http, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _fake_httpx({"ok": False, "description": "Unauthorized"}))
    resp = await http.post("/api/sentinel/telegram/validate", json={"token": "bad"})
    data = await resp.json()
    assert data["ok"] is False
    assert "Unauthorized" in data["error"]


async def test_telegram_detect_chat(http, monkeypatch):
    monkeypatch.setattr(notifier, "telegram_token", lambda: "T")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _fake_httpx({"ok": True, "result": [{"message": {"chat": {"id": 555, "first_name": "Rich"}, "from": {"id": 555, "username": "rich"}}}]}),
    )
    resp = await http.post("/api/sentinel/telegram/detect-chat", json={})
    data = await resp.json()
    assert data["ok"] is True
    assert data["chat_id"] == "555"
    assert data["sender_id"] == "555"


async def test_telegram_detect_chat_pending(http, monkeypatch):
    monkeypatch.setattr(notifier, "telegram_token", lambda: "T")
    monkeypatch.setattr(httpx, "AsyncClient", _fake_httpx({"ok": True, "result": []}))
    resp = await http.post("/api/sentinel/telegram/detect-chat", json={})
    data = await resp.json()
    assert data["ok"] is False
    assert data["pending"] is True


async def test_detect_chat_requires_token(http, monkeypatch):
    monkeypatch.setattr(notifier, "telegram_token", lambda: None)
    resp = await http.post("/api/sentinel/telegram/detect-chat", json={})
    assert resp.status == 400


async def test_test_send(http, monkeypatch):
    async def _fake_send(channel, target, text, thread_ref):
        return SimpleNamespace(ok=True, message_id="1", error=None)

    monkeypatch.setattr(notifier, "send", _fake_send)
    resp = await http.post(
        "/api/colony/c1/notifications/test",
        json={"channel": "telegram", "target": {"chat_id": "9"}},
    )
    data = await resp.json()
    assert data["ok"] is True


async def test_test_send_requires_target(http):
    resp = await http.post("/api/colony/c1/notifications/test", json={})
    assert resp.status == 400
