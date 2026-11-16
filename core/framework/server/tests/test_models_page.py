"""The Models page's API: framework.server.routes_models and framework.llm.endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
import yaml
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import framework.config as config_mod
import framework.server.routes_config as routes_config_mod
from framework.agents.queen import queen_profiles
from framework.llm import endpoints as model_endpoints
from framework.server import routes_models

pytestmark = pytest.mark.asyncio

MODELS = {
    "data": [
        {"id": "kimi/k3", "context_length": 262144, "magpie_label": "Kimi K3 · Moonshot"},
        {"id": "deepseek/deepseek-v4-pro"},
        {"id": "group/opus-anywhere"},
    ]
}


class _Provider:
    def __init__(self):
        self.reconfigured: list[tuple] = []

    def reconfigure(self, model, api_key=None, api_base=None, **kwargs):
        self.reconfigured.append((model, api_key, api_base, kwargs))


class _Manager:
    def __init__(self, sessions=()):
        self._model = "deepseek/deepseek-chat"
        self._sessions = list(sessions)

    def list_sessions(self):
        return list(self._sessions)


class _Store:
    def __init__(self):
        self.saved: dict[str, str] = {}

    def save_credential(self, credential):
        self.saved[credential.id] = credential.keys["api_key"].value.get_secret_value()

    def delete_credential(self, credential_id):
        return self.saved.pop(credential_id, None) is not None


@pytest.fixture(autouse=True)
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "configuration.json"
    monkeypatch.setattr(config_mod, "HIVE_CONFIG_FILE", path)
    monkeypatch.setattr(routes_config_mod, "HIVE_CONFIG_FILE", path)
    return path


@pytest.fixture(autouse=True)
def store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    store = _Store()
    monkeypatch.setattr(model_endpoints, "stored_key", lambda name: store.saved.get(model_endpoints.credential_id(name)))
    for name in list(model_endpoints._cache):
        model_endpoints.forget(name)
    return store


def _write(path: Path, config: dict) -> None:
    path.write_text(json.dumps(config), encoding="utf-8")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest_asyncio.fixture
async def gateway():
    """A stand-in for Magpie: an OpenAI-compatible /v1/models that notes the key it was sent."""
    seen: list[str] = []

    async def models(request: web.Request) -> web.Response:
        seen.append(request.headers.get("Authorization", ""))
        return web.json_response(MODELS)

    app = web.Application()
    app.router.add_get("/v1/models", models)
    server = TestServer(app)
    await server.start_server()
    yield SimpleNamespace(base=str(server.make_url("/v1")).rstrip("/"), seen=seen)
    await server.close()


@pytest_asyncio.fixture
async def client(store):
    clients: list[TestClient] = []

    async def make(manager: _Manager | None = None) -> TestClient:
        app = web.Application()
        app["manager"] = manager or _Manager()
        app["credential_store"] = store
        routes_config_mod.register_routes(app)
        routes_models.register_routes(app)
        tc = TestClient(TestServer(app))
        await tc.start_server()
        clients.append(tc)
        return tc

    yield make
    for tc in clients:
        await tc.close()


async def test_magpie_is_there_unconfigured_and_its_models_are_listed_live(config_file, gateway, client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-users-real-openai-key")
    _write(config_file, {"model_endpoints": {"magpie": {"api_base": gateway.base}}, "llm": {"provider": "deepseek", "model": "deepseek-chat"}})
    tc = await client()

    overview = await (await tc.get("/api/models/overview")).json()
    listed = await (await tc.get("/api/models/endpoints/magpie/models")).json()

    assert overview["endpoints"][0] == {"name": "magpie", "api_base": gateway.base, "builtin": True, "has_key": False, "running": True}
    assert overview["slots"]["llm"]["source"] == "catalog" and overview["slots"]["worker_llm"] is None
    assert all(s["own_risk"] for s in overview["subscriptions"])
    assert listed["models"][-1] == {"id": "kimi/k3", "label": "Kimi K3 · Moonshot", "max_context_tokens": 262144}
    assert set(gateway.seen) == {"Bearer magpie"}  # its placeholder, never the ambient OPENAI_API_KEY


async def test_an_endpoint_that_isnt_running_says_so(config_file, client):
    _write(config_file, {"model_endpoints": {"magpie": {"api_base": "http://127.0.0.1:9/v1"}}})
    tc = await client()

    overview = await (await tc.get("/api/models/overview")).json()
    listed = await tc.get("/api/models/endpoints/magpie/models")

    assert overview["endpoints"][0]["running"] is False
    assert listed.status == 502 and "Can't reach" in (await listed.json())["error"]


async def test_the_main_model_moved_to_an_endpoint_leaves_the_old_key_behind(config_file, gateway, client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-users-real-openai-key")
    _write(
        config_file,
        {
            "model_endpoints": {"magpie": {"api_base": gateway.base}},
            "llm": {"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-deepseek-0000", "extra_body": {"reasoning_effort": "max"}},
        },
    )
    queen = _Provider()
    tc = await client(_Manager([SimpleNamespace(llm=queen, queen_name=None, colony=None)]))

    response = await tc.put("/api/models/slots/llm", json={"source": "endpoint", "endpoint": "magpie", "model": "kimi/k3"})

    assert response.status == 200
    assert _read(config_file)["llm"] == {
        "provider": "openai",
        "endpoint": "magpie",
        "model": "kimi/k3",
        "api_base": gateway.base,
        "max_context_tokens": 262144,
    }
    assert queen.reconfigured == [("openai/kimi/k3", "magpie", gateway.base, {"extra_body": None})]
    assert config_mod.get_api_key() == "magpie"


async def test_a_model_change_within_one_endpoint_keeps_its_extra_body(config_file, gateway, client):
    extra = {"reasoning_effort": "high"}
    _write(
        config_file,
        {
            "model_endpoints": {"magpie": {"api_base": gateway.base}},
            "llm": {"provider": "openai", "endpoint": "magpie", "model": "kimi/k3", "api_base": gateway.base, "extra_body": extra},
        },
    )
    tc = await client()

    await tc.put("/api/models/slots/llm", json={"source": "endpoint", "endpoint": "magpie", "model": "deepseek/deepseek-v4-pro"})

    assert _read(config_file)["llm"]["extra_body"] == extra


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"source": "endpoint", "endpoint": "magpie", "model": "no/such-model"}, "magpie has no model 'no/such-model'"),
        ({"source": "endpoint", "endpoint": "nowhere", "model": "kimi/k3"}, "There's no endpoint 'nowhere'"),
        ({"source": "subscription", "model": "claude"}, "'source' must be"),
        ({"source": "endpoint", "endpoint": "magpie"}, "'model' is required"),
    ],
)
async def test_a_slot_refuses_what_it_cant_use(config_file, gateway, client, body, error):
    _write(config_file, {"model_endpoints": {"magpie": {"api_base": gateway.base}}})
    tc = await client()

    response = await tc.put("/api/models/slots/worker_llm", json=body)

    assert response.status == 400 and error in (await response.json())["error"]
    assert "worker_llm" not in _read(config_file)


async def test_every_slot_kind_takes_an_endpoints_key_not_an_ambient_one(config_file, gateway, client, store, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-users-real-openai-key")
    folder = queen_profiles.QUEENS_DIR / "queen_ava"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "profile.yaml").write_text(yaml.safe_dump({"name": "Ava"}), encoding="utf-8")
    _write(config_file, {"model_endpoints": {"ollama": {"api_base": gateway.base}}, "llm": {"provider": "deepseek", "model": "deepseek-chat"}})
    store.saved["endpoint_ollama"] = "ollama-key-0000"
    tc = await client()

    for slot in ("worker_llm", "vision_fallback", "queen:queen_ava"):
        response = await tc.put(f"/api/models/slots/{slot}", json={"source": "endpoint", "endpoint": "ollama", "model": "kimi/k3"})
        assert response.status == 200, await response.text()

    assert config_mod.get_worker_api_key() == "ollama-key-0000"
    assert config_mod.get_vision_fallback_api_key() == "ollama-key-0000"
    assert config_mod.get_queen_api_key("queen_ava") == "ollama-key-0000"
    assert set(gateway.seen) == {"Bearer ollama-key-0000"}

    removed = await tc.delete("/api/models/slots/queen:queen_ava")
    assert removed.status == 200 and "queen_llm" not in _read(config_file)


async def test_a_catalog_model_is_written_clean(config_file, client, monkeypatch):
    async def valid(*args, **kwargs):
        return {"valid": True}

    monkeypatch.setattr(routes_config_mod, "_validate_provider_key", valid)
    monkeypatch.setattr(routes_config_mod, "_resolve_api_key", lambda provider, request: "sk-ant-0000" if provider == "anthropic" else None)
    _write(config_file, {"llm": {"provider": "openai", "endpoint": "magpie", "model": "kimi/k3", "api_base": "http://x/v1", "api_key": "stale"}})
    tc = await client()
    model = routes_config_mod.MODELS_CATALOGUE["anthropic"][0]["id"]

    ok = await tc.put("/api/models/slots/llm", json={"source": "catalog", "provider": "anthropic", "model": model})
    keyless = await tc.put(
        "/api/models/slots/worker_llm",
        json={"source": "catalog", "provider": "openai", "model": routes_config_mod.MODELS_CATALOGUE["openai"][0]["id"]},
    )

    llm = _read(config_file)["llm"]
    assert ok.status == 200
    assert (llm["provider"], llm["model"]) == ("anthropic", model)
    assert not {"api_key", "endpoint", "api_base", "extra_body"} & set(llm)
    assert keyless.status == 400 and "no API key for openai" in (await keyless.json())["error"]


async def test_endpoints_are_added_moved_and_removed(config_file, gateway, client, store):
    _write(config_file, {"llm": {"provider": "deepseek", "model": "deepseek-chat"}})
    tc = await client()

    added = await tc.put("/api/models/endpoints/ollama", json={"api_base": "http://127.0.0.1:9/v1/", "api_key": "ollama-key-0000"})
    assert (added.status, await added.json()) == (200, {"name": "ollama", "api_base": "http://127.0.0.1:9/v1", "builtin": False, "has_key": True})
    assert store.saved == {"endpoint_ollama": "ollama-key-0000"}

    # A slot served from it follows it to a new address.
    await tc.put("/api/models/endpoints/ollama", json={"api_base": gateway.base})
    await tc.put("/api/models/slots/worker_llm", json={"source": "endpoint", "endpoint": "ollama", "model": "kimi/k3"})
    await tc.put("/api/models/endpoints/ollama", json={"api_base": gateway.base + "/"})
    assert _read(config_file)["worker_llm"]["api_base"] == gateway.base

    in_use = await tc.delete("/api/models/endpoints/ollama")
    assert in_use.status == 409 and "worker_llm" in (await in_use.json())["error"]
    await tc.delete("/api/models/slots/worker_llm")
    gone = await tc.delete("/api/models/endpoints/ollama")
    assert gone.status == 200 and "model_endpoints" not in _read(config_file) and store.saved == {}


async def test_magpie_at_its_own_address_needs_no_entry(config_file, client):
    tc = await client()

    await tc.put("/api/models/endpoints/magpie", json={"api_base": model_endpoints.MAGPIE_API_BASE})

    assert "model_endpoints" not in _read(config_file)


@pytest.mark.parametrize(
    ("name", "body", "error"),
    [
        ("Bad Name", {"api_base": "http://x/v1"}, "lowercase"),
        ("lmstudio", {"api_base": "ftp://x"}, "http:// or https://"),
        ("lmstudio", {}, "http:// or https://"),
    ],
)
async def test_an_endpoint_needs_a_plain_name_and_a_web_address(client, name, body, error):
    tc = await client()

    response = await tc.put(f"/api/models/endpoints/{name}", json=body)

    assert response.status == 400 and error in (await response.json())["error"]


async def test_a_keyless_endpoint_counts_as_a_configured_model(config_file, gateway, client):
    _write(config_file, {"llm": {"provider": "openai", "endpoint": "magpie", "model": "kimi/k3", "api_base": gateway.base}})
    tc = await client()

    llm = await (await tc.get("/api/config/llm")).json()

    assert llm["has_api_key"] is True
