"""GET/PUT /api/config/memory: Settings → Memory, how notes reach a queen and which model writes them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import framework.config as config_mod
import framework.server.routes_config as routes_config_mod

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg_file = tmp_path / "configuration.json"
    monkeypatch.setattr(config_mod, "HIVE_CONFIG_FILE", cfg_file)
    monkeypatch.setattr(routes_config_mod, "HIVE_CONFIG_FILE", cfg_file)
    monkeypatch.delenv("HIVE_MEMORY_RECALL", raising=False)
    return cfg_file


@pytest_asyncio.fixture
async def client():
    app = web.Application()
    routes_config_mod.register_routes(app)
    tc = TestClient(TestServer(app))
    await tc.start_server()
    yield tc
    await tc.close()


async def test_get_shows_the_defaults_and_the_choices(client: TestClient) -> None:
    resp = await client.get("/api/config/memory")

    assert resp.status == 200
    assert await resp.json() == {
        "memory": {
            "recall_mode": "index",
            "recall_modes": ["index", "wait", "background"],
            "recall_mode_env": None,
            "reflection_model": "worker",
            "reflection_models": ["worker", "main"],
        }
    }


async def test_get_says_when_the_env_overrides_the_recall_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIVE_MEMORY_RECALL", "wait")

    memory = (await (await client.get("/api/config/memory")).json())["memory"]

    assert (memory["recall_mode"], memory["recall_mode_env"]) == ("wait", "wait")


async def test_put_saves_the_choices_and_keeps_the_rest_of_each_section(client: TestClient, _config_file: Path) -> None:
    _config_file.write_text(
        json.dumps({"llm": {"model": "m"}, "memory_recall": {"wait_seconds": 4}, "memory_reflection": {"every_turns": 3}}),
        encoding="utf-8",
    )

    resp = await client.put("/api/config/memory", json={"memory": {"recall_mode": "wait", "reflection_model": "main"}})

    assert resp.status == 200
    memory = (await resp.json())["memory"]
    assert (memory["recall_mode"], memory["reflection_model"]) == ("wait", "main")
    assert json.loads(_config_file.read_text(encoding="utf-8")) == {
        "llm": {"model": "m"},
        "memory_recall": {"wait_seconds": 4, "mode": "wait"},
        "memory_reflection": {"every_turns": 3, "model": "main"},
    }


async def test_put_changes_only_the_setting_it_names(client: TestClient, _config_file: Path) -> None:
    resp = await client.put("/api/config/memory", json={"memory": {"reflection_model": "main"}})

    assert resp.status == 200
    assert json.loads(_config_file.read_text(encoding="utf-8")) == {"memory_reflection": {"model": "main"}}


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"memory": {"recall_mode": "someday"}}, "recall_mode must be one of: index, wait, background"),
        ({"memory": {"recall_mode": "wait", "reflection_model": "cheap"}}, "reflection_model must be one of: worker, main"),
        ({"memory": {"timeline": True}}, "No known memory settings. Supported: recall_mode, reflection_model"),
        ({"memory": "wait"}, "memory must be an object"),
    ],
)
async def test_put_rejects_what_it_cannot_save_and_saves_nothing(client: TestClient, _config_file: Path, body: dict, error: str) -> None:
    resp = await client.put("/api/config/memory", json=body)

    assert resp.status == 400
    assert (await resp.json())["error"] == error
    assert not _config_file.exists()
