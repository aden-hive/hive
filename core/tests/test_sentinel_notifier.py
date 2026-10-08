"""Tests for Sentinel's outbound notifier (framework.sentinel.notifier).

httpx is stubbed — no network. We assert the request bodies thread correctly
(Telegram reply_to_message_id / Slack thread_ts) and the token-bearing header.
"""

from __future__ import annotations

import httpx
import pytest

from framework.sentinel import notifier


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class _FakeClient:
    def __init__(self, captured, resp):
        self._captured = captured
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self._captured.append({"url": url, "json": json, "headers": headers})
        return _FakeResp(self._resp)


def _patch_client(monkeypatch, captured, resp):
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeClient(captured, resp))


@pytest.mark.asyncio
async def test_telegram_send_threads_reply(monkeypatch):
    monkeypatch.setattr(notifier, "telegram_token", lambda: "T")
    captured: list[dict] = []
    _patch_client(monkeypatch, captured, {"ok": True, "result": {"message_id": 77}})

    res = await notifier.send("telegram", {"chat_id": "9"}, "hello", {"message_id": 5})

    assert res.ok and res.message_id == "77"
    body = captured[0]["json"]
    assert body["chat_id"] == "9"
    assert body["reply_to_message_id"] == 5


@pytest.mark.asyncio
async def test_slack_send_threads_and_auths(monkeypatch):
    monkeypatch.setattr(notifier, "slack_bot_token", lambda: "xoxb-1")
    captured: list[dict] = []
    _patch_client(monkeypatch, captured, {"ok": True, "ts": "123.45"})

    res = await notifier.send("slack", {"channel": "C1"}, "hi", {"ts": "100.1"})

    assert res.ok and res.message_id == "123.45"
    body = captured[0]["json"]
    assert body["channel"] == "C1"
    assert body["thread_ts"] == "100.1"
    assert captured[0]["headers"]["Authorization"] == "Bearer xoxb-1"


@pytest.mark.asyncio
async def test_telegram_error_surfaces(monkeypatch):
    monkeypatch.setattr(notifier, "telegram_token", lambda: "T")
    _patch_client(monkeypatch, [], {"ok": False, "description": "chat not found"})
    res = await notifier.send("telegram", {"chat_id": "9"}, "hi", None)
    assert not res.ok
    assert "chat not found" in res.error


@pytest.mark.asyncio
async def test_missing_token_fails_cleanly(monkeypatch):
    monkeypatch.setattr(notifier, "telegram_token", lambda: None)
    res = await notifier.send("telegram", {"chat_id": "9"}, "hi", None)
    assert not res.ok
    assert "token" in res.error.lower()


@pytest.mark.asyncio
async def test_unknown_channel(monkeypatch):
    res = await notifier.send("carrier_pigeon", {}, "hi", None)
    assert not res.ok
