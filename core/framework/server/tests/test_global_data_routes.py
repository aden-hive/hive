"""Tests for the global-db proxy routes touched by the CRM insert/changes work.

The cloud backend is faked with an ``httpx.MockTransport`` wired through
``framework.global_db.client._TRANSPORT_OVERRIDE`` (same seam as
test_cloud_sync), so no network is touched. Covers:

- POST insert: server-side lead_id derivation (LinkedIn > email), the 400
  when a lead has no identifier, mode='insert' passthrough, and the 409
  conflict envelope carrying the attempted pk.
- GET /api/global/data/changes: since-param passthrough + shape passthrough.
"""

from __future__ import annotations

import json

import httpx
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import framework.server.routes_colony_workers as rcw
from framework.global_db import client as gdb

LEADS_META = {
    "table": "leads",
    "columns": [
        {"name": "lead_id", "type": "text", "notnull": True, "pk": 1, "dflt_value": None},
        {"name": "name", "type": "text", "notnull": False, "pk": 0, "dflt_value": None},
        {"name": "email", "type": "text", "notnull": False, "pk": 0, "dflt_value": None},
        {"name": "linkedin_url", "type": "text", "notnull": False, "pk": 0, "dflt_value": None},
    ],
    "primary_key": ["lead_id"],
    "rows": [],
    "total": 0,
    "limit": 1,
    "offset": 0,
}

CHANGES_PAYLOAD = {
    "cursor": "2026-07-20 01:02:03.000004+00",
    "covered": ["interactions", "leads"],
    "truncated": False,
    "tables": {"leads": {"count": 1, "rows": [{"pk": {"lead_id": "x"}, "op": "update"}]}},
}


class FakeBackend:
    """Minimal /v1/global-db backend. Records upsert bodies and changes params."""

    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.changes_params: list[dict] = []
        self.conflict = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.endswith("/rows"):
            return httpx.Response(200, json=LEADS_META)
        if request.method == "GET" and path == "/v1/global-db/changes":
            self.changes_params.append(dict(request.url.params))
            return httpx.Response(200, json=CHANGES_PAYLOAD)
        if request.method == "POST" and path == "/v1/global-db/upsert":
            self.upserts.append(json.loads(request.content))
            if self.conflict:
                return httpx.Response(
                    409,
                    json={"error": {"code": "conflict", "message": "A row with this key already exists in 'leads'."}},
                )
            return httpx.Response(200, json={"success": True, "inserted": 1})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": path}})


@pytest.fixture
def backend(monkeypatch) -> FakeBackend:
    fb = FakeBackend()
    monkeypatch.setenv("HIVE_CLOUD_JWT", "test-jwt")
    monkeypatch.setenv("HIVE_CLOUD_BASE", "https://cloud.test")
    gdb._TRANSPORT_OVERRIDE = httpx.MockTransport(fb.handler)
    yield fb
    gdb._TRANSPORT_OVERRIDE = None


def _app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/global/data/tables/{table}/rows", rcw.handle_global_insert_row)
    app.router.add_get("/api/global/data/changes", rcw.handle_global_changes)
    return app


async def _client(app: web.Application) -> TestClient:
    return TestClient(TestServer(app))


# ---------------------------------------------------------------------------
# lead_id derivation (server-side canonical form)
# ---------------------------------------------------------------------------


def test_derive_lead_id_prefers_linkedin_slug() -> None:
    row = {
        "email": "Jane@Acme.com",
        "linkedin_url": "https://www.LinkedIn.com/in/Jane-Doe/?utm_source=x#top",
    }
    assert rcw._derive_lead_id(row) == "linkedin.com/in/jane-doe"


def test_derive_lead_id_falls_back_to_email() -> None:
    assert rcw._derive_lead_id({"email": "  Jane@Acme.com "}) == "jane@acme.com"
    assert rcw._derive_lead_id({"name": "no identifiers"}) is None


@pytest.mark.asyncio
async def test_insert_lead_derives_pk_and_uses_insert_mode(backend: FakeBackend) -> None:
    async with await _client(_app()) as c:
        resp = await c.post(
            "/api/global/data/tables/leads/rows",
            json={"row": {"name": "Jane", "linkedin_url": "https://www.linkedin.com/in/jane/"}},
        )
        assert resp.status == 200, await resp.text()
        body = await resp.json()
    assert body == {"inserted": 1, "pk": {"lead_id": "linkedin.com/in/jane"}}
    assert backend.upserts[-1]["mode"] == "insert"
    assert backend.upserts[-1]["row"]["lead_id"] == "linkedin.com/in/jane"


@pytest.mark.asyncio
async def test_insert_lead_without_identifier_400s_before_backend(backend: FakeBackend) -> None:
    async with await _client(_app()) as c:
        resp = await c.post(
            "/api/global/data/tables/leads/rows",
            json={"row": {"name": "No Id"}},
        )
        assert resp.status == 400
        body = await resp.json()
    assert "email or LinkedIn" in body["error"]
    assert backend.upserts == []  # rejected locally, no cloud write attempted


@pytest.mark.asyncio
async def test_insert_conflict_maps_to_409_with_pk(backend: FakeBackend) -> None:
    backend.conflict = True
    async with await _client(_app()) as c:
        resp = await c.post(
            "/api/global/data/tables/leads/rows",
            json={"row": {"name": "Dup", "email": "dup@x.com"}},
        )
        assert resp.status == 409
        body = await resp.json()
    # The envelope carries the attempted pk so the UI can open the existing
    # record instead of silently overwriting it.
    assert body["error"] == "conflict"
    assert body["pk"] == {"lead_id": "dup@x.com"}


# ---------------------------------------------------------------------------
# /changes proxy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_changes_init_omits_since(backend: FakeBackend) -> None:
    async with await _client(_app()) as c:
        resp = await c.get("/api/global/data/changes")
        assert resp.status == 200
        body = await resp.json()
    assert body == CHANGES_PAYLOAD
    assert backend.changes_params == [{}]  # init call: no since param


@pytest.mark.asyncio
async def test_changes_passes_cursor_through(backend: FakeBackend) -> None:
    async with await _client(_app()) as c:
        resp = await c.get(
            "/api/global/data/changes",
            params={"since": "2026-07-20 01:02:03.000004+00"},
        )
        assert resp.status == 200
    assert backend.changes_params == [{"since": "2026-07-20 01:02:03.000004+00"}]


@pytest.mark.asyncio
async def test_changes_signed_out_maps_to_401(backend: FakeBackend, monkeypatch) -> None:
    monkeypatch.delenv("HIVE_CLOUD_JWT")
    async with await _client(_app()) as c:
        resp = await c.get("/api/global/data/changes")
        assert resp.status == 401
        body = await resp.json()
    assert body.get("signed_out") is True
