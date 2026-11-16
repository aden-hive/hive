"""HTTP tests for the provider library surface.

GET/PUT /api/config/provider-library manage named vendor configs stored
verbatim under "provider_library" in configuration.json; POST
/api/config/provider-library/apply copies one entry into a provider slot
(llm / worker_llm / vision_fallback) through the same validated write +
hot-swap path as the direct slot editor (PUT /api/config/llm-sections).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import framework.config as config_mod
import framework.server.routes_config as routes_config_mod

pytestmark = pytest.mark.asyncio


class _StubManager:
    def __init__(self, sessions: list | None = None):
        self._model = "anthropic/old-model"
        self._sessions = sessions or []

    def list_sessions(self):
        return list(self._sessions)


class _StubProvider:
    def __init__(self):
        self.reconfigured_with: tuple | None = None

    def reconfigure(self, model, api_key=None, api_base=None):
        self.reconfigured_with = (model, api_key, api_base)


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point config reads/writes at a temp file."""
    cfg_file = tmp_path / "configuration.json"
    monkeypatch.setattr(config_mod, "HIVE_CONFIG_FILE", cfg_file)
    monkeypatch.setattr(routes_config_mod, "HIVE_CONFIG_FILE", cfg_file)
    return cfg_file


def _build_app(manager: _StubManager) -> web.Application:
    app = web.Application()
    app["manager"] = manager
    routes_config_mod.register_routes(app)
    return app


@pytest_asyncio.fixture
async def make_client():
    clients: list[TestClient] = []

    async def _make(manager: _StubManager | None = None) -> TestClient:
        tc = TestClient(TestServer(_build_app(manager or _StubManager())))
        await tc.start_server()
        clients.append(tc)
        return tc

    yield _make
    for tc in clients:
        await tc.close()


ENTRY = {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "api_key": "sk-test-1234",
    "custom_extra": {"nested": True},  # unknown keys survive verbatim
}


# ---------------------------------------------------------------------------
# GET / PUT /api/config/provider-library
# ---------------------------------------------------------------------------


async def test_get_library_empty(make_client) -> None:
    client = await make_client()
    resp = await client.get("/api/config/provider-library")
    assert resp.status == 200
    assert await resp.json() == {"library": {}}


async def test_put_saves_entry_verbatim(make_client, _isolated_config: Path) -> None:
    client = await make_client()
    resp = await client.put("/api/config/provider-library", json={"name": "ds-prod", "section": ENTRY})
    assert resp.status == 200
    assert (await resp.json())["section"] == ENTRY

    on_disk = json.loads(_isolated_config.read_text(encoding="utf-8"))
    assert on_disk["provider_library"]["ds-prod"] == ENTRY

    resp = await client.get("/api/config/provider-library")
    assert (await resp.json())["library"] == {"ds-prod": ENTRY}


async def test_put_validation(make_client) -> None:
    client = await make_client()
    # Missing name.
    resp = await client.put("/api/config/provider-library", json={"section": ENTRY})
    assert resp.status == 400
    # Missing model.
    resp = await client.put(
        "/api/config/provider-library",
        json={"name": "x", "section": {"provider": "openai"}},
    )
    assert resp.status == 400
    # Non-object section.
    resp = await client.put("/api/config/provider-library", json={"name": "x", "section": [1]})
    assert resp.status == 400


async def test_put_null_deletes_and_prunes_empty_library(make_client, _isolated_config: Path) -> None:
    client = await make_client()
    await client.put("/api/config/provider-library", json={"name": "a", "section": ENTRY})
    resp = await client.put("/api/config/provider-library", json={"name": "a", "section": None})
    assert resp.status == 200
    assert (await resp.json())["section"] is None
    # Deleting the last entry removes the key from configuration.json entirely.
    on_disk = json.loads(_isolated_config.read_text(encoding="utf-8"))
    assert "provider_library" not in on_disk
    # Deleting a nonexistent entry is a no-op, not an error.
    resp = await client.put("/api/config/provider-library", json={"name": "ghost", "section": None})
    assert resp.status == 200


# ---------------------------------------------------------------------------
# POST /api/config/provider-library/apply
# ---------------------------------------------------------------------------


async def test_apply_to_worker_slot(make_client, _isolated_config: Path) -> None:
    client = await make_client()
    await client.put("/api/config/provider-library", json={"name": "ds", "section": ENTRY})
    resp = await client.post("/api/config/provider-library/apply", json={"name": "ds", "role": "worker_llm"})
    assert resp.status == 200
    body = await resp.json()
    assert body["role"] == "worker_llm"
    assert body["section"] == ENTRY
    assert body["sessions_swapped"] == 0  # only the main slot hot-swaps

    on_disk = json.loads(_isolated_config.read_text(encoding="utf-8"))
    assert on_disk["worker_llm"] == ENTRY
    assert on_disk["provider_library"]["ds"] == ENTRY  # library keeps its copy

    # The slot editor's GET now shows the applied section.
    resp = await client.get("/api/config/llm-sections")
    assert (await resp.json())["worker_llm"] == ENTRY


async def test_apply_to_llm_slot_hot_swaps_sessions(make_client) -> None:
    provider = _StubProvider()
    manager = _StubManager([SimpleNamespace(llm=provider, colony=None)])
    client = await make_client(manager)
    await client.put("/api/config/provider-library", json={"name": "ds", "section": ENTRY})
    resp = await client.post("/api/config/provider-library/apply", json={"name": "ds", "role": "llm"})
    assert resp.status == 200
    assert (await resp.json())["sessions_swapped"] == 1
    assert provider.reconfigured_with == ("deepseek/deepseek-chat", "sk-test-1234", None)
    assert manager._model == "deepseek/deepseek-chat"


async def test_apply_unknown_name_and_role(make_client) -> None:
    client = await make_client()
    resp = await client.post("/api/config/provider-library/apply", json={"name": "nope", "role": "llm"})
    assert resp.status == 404
    await client.put("/api/config/provider-library", json={"name": "ds", "section": ENTRY})
    resp = await client.post("/api/config/provider-library/apply", json={"name": "ds", "role": "bogus"})
    assert resp.status == 400


async def test_apply_health_checks_key_against_base(make_client, monkeypatch: pytest.MonkeyPatch) -> None:
    """An entry with api_key + api_base runs the same health check as the
    slot editor; a failing check must not touch the slot."""
    calls: list[tuple] = []

    async def _fake_validate(provider, api_key, api_base=None, model=None):
        calls.append((provider, api_key, api_base, model))
        return {"valid": False, "message": "bad key"}

    monkeypatch.setattr(routes_config_mod, "_validate_provider_key", _fake_validate)
    client = await make_client()
    entry = {**ENTRY, "api_base": "https://ds.example.com/v1"}
    # Library save itself never health-checks (endpoint may be down/rotated).
    resp = await client.put("/api/config/provider-library", json={"name": "ds", "section": entry})
    assert resp.status == 200
    assert calls == []

    resp = await client.post("/api/config/provider-library/apply", json={"name": "ds", "role": "worker_llm"})
    assert resp.status == 400
    assert calls == [("deepseek", "sk-test-1234", "https://ds.example.com/v1", "deepseek-chat")]
    resp = await client.get("/api/config/llm-sections")
    assert (await resp.json())["worker_llm"] is None
