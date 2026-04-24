"""Tests for the MCP server CRUD HTTP routes.

Monkey-patches ``MCPRegistry`` inside ``routes_mcp`` so the HTTP layer is
exercised without reading or writing ``~/.hive/mcp_registry/installed.json``
or spawning actual subprocesses.
"""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from framework.loader.mcp_errors import MCPError, MCPErrorCode
from framework.server import routes_mcp


class _FakeRegistry:
    """Stand-in for MCPRegistry — just enough surface for the routes."""

    def __init__(self) -> None:
        self._servers: dict[str, dict[str, Any]] = {
            "built-in-seed": {
                "source": "registry",
                "transport": "stdio",
                "enabled": True,
                "manifest": {"description": "Factory-seeded server", "tools": []},
                "last_health_status": "healthy",
                "last_error": None,
                "last_health_check_at": None,
            }
        }

    def initialize(self) -> None:  # noqa: D401 — registry idempotent init
        return

    def list_installed(self) -> list[dict[str, Any]]:
        return [{"name": name, **entry} for name, entry in self._servers.items()]

    def get_server(self, name: str) -> dict | None:
        if name not in self._servers:
            return None
        return {"name": name, **self._servers[name]}

    def add_local(self, *, name: str, transport: str, **kwargs: Any) -> dict:
        if name in self._servers:
            raise MCPError(
                code=MCPErrorCode.MCP_INSTALL_FAILED,
                what=f"Server '{name}' already exists",
                why="A server with this name is already registered locally.",
                fix=f"Run: hive mcp remove {name}",
            )
        entry = {
            "source": "local",
            "transport": transport,
            "enabled": True,
            "manifest": {"description": kwargs.get("description") or ""},
            "last_health_status": None,
            "last_error": None,
            "last_health_check_at": None,
        }
        self._servers[name] = entry
        return entry

    def remove(self, name: str) -> None:
        if name not in self._servers:
            raise MCPError(
                code=MCPErrorCode.MCP_INSTALL_FAILED,
                what=f"Cannot remove server '{name}'",
                why="Server is not installed.",
                fix="Run: hive mcp list",
            )
        del self._servers[name]

    def enable(self, name: str) -> None:
        if name not in self._servers:
            raise MCPError(
                code=MCPErrorCode.MCP_INSTALL_FAILED,
                what="not found",
                why="not found",
                fix="x",
            )
        self._servers[name]["enabled"] = True

    def disable(self, name: str) -> None:
        if name not in self._servers:
            raise MCPError(
                code=MCPErrorCode.MCP_INSTALL_FAILED,
                what="not found",
                why="not found",
                fix="x",
            )
        self._servers[name]["enabled"] = False

    def health_check(self, name: str) -> dict[str, Any]:
        if name not in self._servers:
            raise MCPError(
                code=MCPErrorCode.MCP_HEALTH_FAILED,
                what="not found",
                why="not found",
                fix="x",
            )
        return {"name": name, "status": "healthy", "tools": 3, "error": None}


@pytest.fixture
def registry(monkeypatch):
    reg = _FakeRegistry()
    monkeypatch.setattr(routes_mcp, "_registry", lambda: reg)
    return reg


async def _make_app() -> web.Application:
    app = web.Application()
    routes_mcp.register_routes(app)
    return app


@pytest.mark.asyncio
async def test_list_servers_returns_built_in(registry):
    app = await _make_app()
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/api/mcp/servers")
        assert resp.status == 200
        body = await resp.json()
    names = {s["name"] for s in body["servers"]}
    # The registry fake carries one entry; the list also merges package-
    # baked entries from core/framework/agents/queen/mcp_servers.json so
    # the UI matches what the queen actually loads. Both should appear.
    assert "built-in-seed" in names
    sources = {s["name"]: s["source"] for s in body["servers"]}
    assert sources.get("built-in-seed") == "registry"
    # The package-baked servers (coder-tools/gcu-tools/hive_tools) carry
    # source=="built-in" and are non-removable.
    pkg_entries = [s for s in body["servers"] if s["source"] == "built-in"]
    assert pkg_entries, "expected at least one package-baked MCP server"
    assert all(s.get("removable") is False for s in pkg_entries)


@pytest.mark.asyncio
async def test_add_local_server(registry):
    app = await _make_app()
    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            "/api/mcp/servers",
            json={
                "name": "my-tool",
                "transport": "stdio",
                "command": "echo",
                "args": ["hi"],
                "description": "says hi",
            },
        )
        assert resp.status == 201
        body = await resp.json()
        assert body["server"]["name"] == "my-tool"
        assert body["server"]["source"] == "local"

        resp = await client.get("/api/mcp/servers")
        names = [s["name"] for s in (await resp.json())["servers"]]
    assert "my-tool" in names


@pytest.mark.asyncio
async def test_add_rejects_duplicate(registry):
    app = await _make_app()
    async with TestClient(TestServer(app)) as client:
        for _ in range(2):
            resp = await client.post(
                "/api/mcp/servers",
                json={"name": "dup", "transport": "stdio", "command": "x"},
            )
        assert resp.status == 409
        body = await resp.json()
        assert "already exists" in body["error"].lower()
        assert body["fix"]


@pytest.mark.asyncio
async def test_add_rejects_invalid_transport(registry):
    app = await _make_app()
    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            "/api/mcp/servers",
            json={"name": "x", "transport": "nope"},
        )
        assert resp.status == 400


@pytest.mark.asyncio
async def test_enable_disable_cycle(registry):
    app = await _make_app()
    # Seed a local server
    registry.add_local(name="local-one", transport="stdio", command="x")

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/api/mcp/servers/local-one/disable")
        assert resp.status == 200
        assert (await resp.json())["enabled"] is False
        assert registry._servers["local-one"]["enabled"] is False

        resp = await client.post("/api/mcp/servers/local-one/enable")
        assert resp.status == 200
        assert (await resp.json())["enabled"] is True


@pytest.mark.asyncio
async def test_remove_local_only(registry):
    app = await _make_app()
    registry.add_local(name="local-two", transport="stdio", command="x")

    async with TestClient(TestServer(app)) as client:
        # Built-ins are protected
        resp = await client.delete("/api/mcp/servers/built-in-seed")
        assert resp.status == 400

        # Missing
        resp = await client.delete("/api/mcp/servers/ghost")
        assert resp.status == 404

        # Happy path
        resp = await client.delete("/api/mcp/servers/local-two")
        assert resp.status == 200
        assert "local-two" not in registry._servers


@pytest.mark.asyncio
async def test_health_check(registry, monkeypatch):
    app = await _make_app()
    registry.add_local(name="pingable", transport="stdio", command="x")

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/api/mcp/servers/pingable/health")
        assert resp.status == 200
        body = await resp.json()
    assert body["status"] == "healthy"
    assert body["tools"] == 3
