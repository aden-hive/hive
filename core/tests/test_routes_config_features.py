"""HTTP + resolution tests for the global feature-flags surface.

GET/PUT /api/config/features backs the desktop Developer-options toggle
for colony-adaptive worker budgets: PUT persists whitelisted boolean
keys top-level in configuration.json and hot-applies the flag to
running colony runtimes (skipping colonies whose metadata.json pins it).
Also covers config.get_adaptive_tool_budget_enabled resolution order:
env (when set) > configuration.json > default True.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import framework.config as config_mod
import framework.server.routes_config as routes_config_mod
from framework.config import get_adaptive_tool_budget_enabled

pytestmark = pytest.mark.asyncio


class _StubManager:
    def __init__(self, sessions: list | None = None):
        self._sessions = sessions or []

    def list_sessions(self):
        return list(self._sessions)


def _session(colony_id: str | None, adaptive: bool | None):
    """Session stub: colony present iff adaptive is not None."""
    colony = None
    if adaptive is not None:
        colony = SimpleNamespace(_config=SimpleNamespace(adaptive_tool_budget=adaptive))
    return SimpleNamespace(colony=colony, colony_id=colony_id)


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point config reads/writes at a temp file; neutralize the env var."""
    cfg_file = tmp_path / "configuration.json"
    monkeypatch.setattr(config_mod, "HIVE_CONFIG_FILE", cfg_file)
    monkeypatch.setattr(routes_config_mod, "HIVE_CONFIG_FILE", cfg_file)
    monkeypatch.setattr(config_mod, "COLONIES_DIR", tmp_path / "colonies")
    monkeypatch.delenv("HIVE_ADAPTIVE_TOOL_BUDGET", raising=False)
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


# ---------------------------------------------------------------------------
# Getter resolution order
# ---------------------------------------------------------------------------


def test_getter_defaults_true(_isolated_config: Path) -> None:
    assert get_adaptive_tool_budget_enabled() is True


def test_getter_reads_config_file(_isolated_config: Path) -> None:
    _isolated_config.write_text(json.dumps({"adaptive_tool_budget": False}), encoding="utf-8")
    assert get_adaptive_tool_budget_enabled() is False
    _isolated_config.write_text(json.dumps({"adaptive_tool_budget": True}), encoding="utf-8")
    assert get_adaptive_tool_budget_enabled() is True
    # Non-boolean values are ignored.
    _isolated_config.write_text(json.dumps({"adaptive_tool_budget": "nope"}), encoding="utf-8")
    assert get_adaptive_tool_budget_enabled() is True


def test_getter_env_wins_over_file(_isolated_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolated_config.write_text(json.dumps({"adaptive_tool_budget": True}), encoding="utf-8")
    monkeypatch.setenv("HIVE_ADAPTIVE_TOOL_BUDGET", "0")
    assert get_adaptive_tool_budget_enabled() is False
    monkeypatch.setenv("HIVE_ADAPTIVE_TOOL_BUDGET", "1")
    _isolated_config.write_text(json.dumps({"adaptive_tool_budget": False}), encoding="utf-8")
    assert get_adaptive_tool_budget_enabled() is True


# ---------------------------------------------------------------------------
# GET/PUT /api/config/features
# ---------------------------------------------------------------------------


async def test_get_features_default(make_client) -> None:
    client = await make_client()
    resp = await client.get("/api/config/features")
    assert resp.status == 200
    body = await resp.json()
    # Senders default OFF — it is an advanced developer feature, and this
    # default is what keeps the sender tools out of every queen's hands until
    # the user opts in. Adaptive budgets default ON.
    assert body == {"features": {"adaptive_tool_budget": True, "email_senders": False}}


async def test_put_email_senders_persists_and_publishes_env(
    make_client,
    _isolated_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabling senders must reach the MCP subprocesses, not just the file.

    The tools are registered by the `hive_tools` server, which reads
    HIVE_EMAIL_SENDERS from the environment it inherits. If the PUT only wrote
    configuration.json, the toggle would light up the UI while every queen
    still had no send tools until the next runtime restart.
    """
    # HIVE_EMAIL_SENDERS is process-global and the handler writes it directly;
    # this hands cleanup to monkeypatch so an enabled sender pool can't leak
    # into the tests that run after this one.
    monkeypatch.delenv("HIVE_EMAIL_SENDERS", raising=False)
    client = await make_client()
    resp = await client.put("/api/config/features", json={"features": {"email_senders": True}})
    assert resp.status == 200
    assert (await resp.json())["features"] == {"email_senders": True}

    on_disk = json.loads(_isolated_config.read_text(encoding="utf-8"))
    assert on_disk["email_senders"] is True
    assert os.environ["HIVE_EMAIL_SENDERS"] == "1"
    assert (await client.get("/api/config/features")).status == 200

    # …and turning it back off must retract the env var, or the tools would
    # keep being registered for every session started afterwards.
    resp = await client.put("/api/config/features", json={"features": {"email_senders": False}})
    assert resp.status == 200
    assert os.environ["HIVE_EMAIL_SENDERS"] == "0"
    body = await (await client.get("/api/config/features")).json()
    assert body["features"]["email_senders"] is False


async def test_put_features_persists_and_get_reflects(make_client, _isolated_config: Path) -> None:
    client = await make_client()
    resp = await client.put("/api/config/features", json={"features": {"adaptive_tool_budget": False}})
    assert resp.status == 200
    body = await resp.json()
    assert body["features"] == {"adaptive_tool_budget": False}
    # Persisted top-level in configuration.json…
    on_disk = json.loads(_isolated_config.read_text(encoding="utf-8"))
    assert on_disk["adaptive_tool_budget"] is False
    # …and the GET (used by the toggle to load state) reflects it.
    resp = await client.get("/api/config/features")
    assert (await resp.json())["features"]["adaptive_tool_budget"] is False


async def test_put_features_preserves_other_config_keys(make_client, _isolated_config: Path) -> None:
    _isolated_config.write_text(json.dumps({"llm": {"provider": "anthropic"}, "gcu_enabled": False}), encoding="utf-8")
    client = await make_client()
    resp = await client.put("/api/config/features", json={"adaptive_tool_budget": True})
    assert resp.status == 200
    on_disk = json.loads(_isolated_config.read_text(encoding="utf-8"))
    assert on_disk["llm"] == {"provider": "anthropic"}
    assert on_disk["gcu_enabled"] is False
    assert on_disk["adaptive_tool_budget"] is True


async def test_put_features_validation(make_client) -> None:
    client = await make_client()
    # Non-boolean value.
    resp = await client.put("/api/config/features", json={"features": {"adaptive_tool_budget": "yes"}})
    assert resp.status == 400
    # No known keys.
    resp = await client.put("/api/config/features", json={"features": {"unknown_flag": True}})
    assert resp.status == 400
    # Non-object block.
    resp = await client.put("/api/config/features", json={"features": [1, 2]})
    assert resp.status == 400


async def test_put_features_hot_applies_respecting_colony_pins(make_client, tmp_path: Path) -> None:
    """Running colonies flip live; a colony whose metadata.json pins the
    flag keeps its pinned value (per-colony override beats the global)."""
    unpinned = _session("colony_a", adaptive=True)
    pinned = _session("colony_b", adaptive=True)
    no_colony = _session(None, adaptive=None)
    already_off = _session("colony_c", adaptive=False)

    # Pin colony_b via metadata.json under the monkeypatched COLONIES_DIR.
    meta_dir = tmp_path / "colonies" / "colony_b"
    meta_dir.mkdir(parents=True)
    (meta_dir / "metadata.json").write_text(json.dumps({"adaptive_tool_budget": True}), encoding="utf-8")

    client = await make_client(_StubManager([unpinned, pinned, no_colony, already_off]))
    resp = await client.put("/api/config/features", json={"features": {"adaptive_tool_budget": False}})
    assert resp.status == 200
    body = await resp.json()
    # Only colony_a flipped: colony_b is pinned, colony_c already off,
    # the DM session has no colony.
    assert body["colonies_applied"] == 1
    assert unpinned.colony._config.adaptive_tool_budget is False
    assert pinned.colony._config.adaptive_tool_budget is True
    assert already_off.colony._config.adaptive_tool_budget is False
