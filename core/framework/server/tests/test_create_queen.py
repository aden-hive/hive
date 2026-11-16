"""POST /api/queen/create.

Regression: the handler called ``schedule_push()`` with no arguments after
writing the profile, so every create answered 500 (``TypeError: missing
'kind' and 'key'``) although the queen had been saved — and a retry then hit
409 "already exists".
"""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from framework.server import routes_queens
from framework.server.app import create_app


@pytest.mark.asyncio
async def test_create_queen_returns_the_new_queen_and_syncs_it(monkeypatch):
    pushed: list[tuple[str, str]] = []
    monkeypatch.setattr(routes_queens, "schedule_push", lambda kind, key: pushed.append((kind, key)))

    async with TestClient(TestServer(create_app())) as client:
        resp = await client.post("/api/queen/create", json={"name": "Ada Lovelace", "queen_id": "ada"})
        data = await resp.json()

    assert resp.status == 201
    assert data["queen"]["id"] == "ada"
    assert pushed == [("queen_profile", "ada")]
