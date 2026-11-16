"""The Runtime logs drawer reads the server's recent log from /api/runtime-logs."""

from __future__ import annotations

import logging

import pytest
from aiohttp.test_utils import TestClient, TestServer

from framework.observability.logging import recent_logs
from framework.server.app import create_app

log = logging.getLogger("framework.server.tests.runtime_logs")


@pytest.fixture
def root_logs_to_drawer():
    root, aiohttp_access = logging.getLogger(), logging.getLogger("aiohttp.access")
    level = root.level
    root.addHandler(recent_logs)
    root.setLevel(logging.INFO)
    # `hive serve` runs aiohttp with access_log=None and writes its own [access] lines.
    aiohttp_access.disabled = True
    yield
    root.removeHandler(recent_logs)
    root.setLevel(level)
    aiohttp_access.disabled = False


def _cursor() -> int:
    entries = recent_logs.since(0)
    return entries[-1]["seq"] if entries else 0


@pytest.mark.asyncio
async def test_the_drawer_gets_the_lines_after_its_cursor(root_logs_to_drawer):
    async with TestClient(TestServer(create_app())) as client:
        after = _cursor()
        log.info("onebot: QQ account connected")
        try:
            raise RuntimeError("judge unreachable")
        except RuntimeError:
            log.exception("stall check failed")

        first = await (await client.get(f"/api/runtime-logs?after={after}&boot={recent_logs.boot}")).json()
        last = first["entries"][-1]["seq"]
        again = await (await client.get(f"/api/runtime-logs?after={last}&boot={recent_logs.boot}")).json()

    texts = [e["text"] for e in first["entries"]]
    assert texts[0].endswith("[INFO] onebot: QQ account connected")
    assert first["entries"][0]["stream"] == "stdout"
    assert "[ERROR] stall check failed\nTraceback" in texts[1]
    assert texts[1].endswith("RuntimeError: judge unreachable")
    assert first["entries"][1]["stream"] == "stderr"
    assert again == {"boot": recent_logs.boot, "entries": []}


@pytest.mark.asyncio
async def test_a_drawer_from_an_earlier_server_gets_the_whole_buffer(root_logs_to_drawer):
    log.info("fresh start")
    async with TestClient(TestServer(create_app())) as client:
        body = await (await client.get(f"/api/runtime-logs?after={_cursor()}&boot=earlier")).json()
        buffer = recent_logs.since(0)

    assert body["boot"] == recent_logs.boot
    assert body["entries"] == buffer


@pytest.mark.asyncio
async def test_polling_the_log_does_not_write_to_it(root_logs_to_drawer):
    async with TestClient(TestServer(create_app())) as client:
        after = _cursor()
        await client.get("/api/health")
        await client.get(f"/api/runtime-logs?after={after}&boot={recent_logs.boot}")

    texts = [e["text"] for e in recent_logs.since(after)]
    assert any("[access] GET /api/health -> 200" in t for t in texts)
    assert not any("/api/runtime-logs" in t for t in texts)
