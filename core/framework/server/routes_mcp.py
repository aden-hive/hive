"""MCP server registration routes.

Thin HTTP wrapper around ``MCPRegistry`` so the frontend can add, remove,
enable, and health-check user-registered MCP servers. The CLI path
(``hive mcp add`` / ``hive mcp remove`` / etc.) is unchanged.

- GET    /api/mcp/servers                  -- list installed servers
- POST   /api/mcp/servers                  -- register a local server
- DELETE /api/mcp/servers/{name}           -- remove a local server
- POST   /api/mcp/servers/{name}/enable    -- enable a server
- POST   /api/mcp/servers/{name}/disable   -- disable a server
- POST   /api/mcp/servers/{name}/health    -- probe server health

New servers take effect on the *next* queen session start. Existing live
queen sessions keep the tool list they booted with to avoid mid-turn
cache invalidation. The ``add`` response hints at this explicitly.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from framework.loader.mcp_errors import MCPError
from framework.loader.mcp_registry import MCPRegistry

logger = logging.getLogger(__name__)


_VALID_TRANSPORTS = {"stdio", "http", "sse", "unix"}


def _registry() -> MCPRegistry:
    # MCPRegistry is a thin wrapper around ~/.hive/mcp_registry/installed.json
    # so instantiation is cheap — no need to cache on app["..."].
    reg = MCPRegistry()
    reg.initialize()
    return reg


def _package_builtin_servers() -> list[dict[str, Any]]:
    """Return the package-baked queen MCP servers from ``queen/mcp_servers.json``.

    Those servers are loaded directly by ``ToolRegistry.load_mcp_config``
    at queen boot and never go through ``MCPRegistry.list_installed``,
    so the raw registry view shows them as missing. Surface them here so
    the Tool Library reflects what the queen actually talks to.

    Entries carry ``source: "built-in"`` and are NOT removable / toggleable
    — editing them requires changing the repo file.
    """
    import json
    from pathlib import Path

    import framework.agents.queen as _queen_pkg

    path = Path(_queen_pkg.__file__).parent / "mcp_servers.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    out: list[dict[str, Any]] = []
    for name, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        out.append(
            {
                "name": name,
                "source": "built-in",
                "transport": cfg.get("transport", "stdio"),
                "description": cfg.get("description", "") or "",
                "enabled": True,
                "last_health_status": None,
                "last_error": None,
                "last_health_check_at": None,
                "tool_count": None,
                "removable": False,
            }
        )
    return out


def _server_to_summary(entry: dict[str, Any]) -> dict[str, Any]:
    """Shape an installed.json entry for API responses.

    Strips the full manifest body (which can be large) but keeps the tool
    list if the manifest already embeds one (happens for registry-installed
    servers). Users with ``source: "local"`` only get a tool list after
    running a health check.
    """
    manifest = entry.get("manifest") or {}
    tools = manifest.get("tools") if isinstance(manifest, dict) else None
    if not isinstance(tools, list):
        tools = None
    return {
        "name": entry.get("name"),
        "source": entry.get("source"),
        "transport": entry.get("transport"),
        "description": (manifest.get("description") if isinstance(manifest, dict) else None) or "",
        "enabled": entry.get("enabled", True),
        "last_health_status": entry.get("last_health_status"),
        "last_error": entry.get("last_error"),
        "last_health_check_at": entry.get("last_health_check_at"),
        "tool_count": (len(tools) if tools is not None else None),
    }


def _mcp_error_response(exc: MCPError, *, default_status: int = 400) -> web.Response:
    return web.json_response(
        {
            "error": exc.what,
            "code": exc.code.value,
            "what": exc.what,
            "why": exc.why,
            "fix": exc.fix,
        },
        status=default_status,
    )


async def handle_list_servers(request: web.Request) -> web.Response:
    """GET /api/mcp/servers — list every server the queen actually uses.

    Merges two sources:

    - ``MCPRegistry.list_installed()`` — servers registered via
      ``hive mcp add`` / the ``/api/mcp/servers`` POST route, stored in
      ``~/.hive/mcp_registry/installed.json``. These carry
      ``source: "local"`` (user-added) or ``source: "registry"``
      (installed from the remote registry).
    - Repo-baked queen servers from
      ``core/framework/agents/queen/mcp_servers.json``. These are loaded
      directly by the queen's ``ToolRegistry`` at boot and never touch
      ``MCPRegistry``; we surface them here so the UI reflects what the
      queen really talks to. They are not removable from the UI because
      editing them requires changing the repo.

    If a name collides between the two sources, the registry entry wins
    because that's the one the user has customized.
    """
    reg = _registry()
    registry_entries = [_server_to_summary(e) for e in reg.list_installed()]
    seen_names = {e.get("name") for e in registry_entries}

    package_entries = [e for e in _package_builtin_servers() if e.get("name") not in seen_names]

    servers = [*package_entries, *registry_entries]
    return web.json_response({"servers": servers})


async def handle_add_server(request: web.Request) -> web.Response:
    """POST /api/mcp/servers — register a local MCP server.

    Body mirrors ``MCPRegistry.add_local`` args:

    ::

        {
          "name": "my-tool",
          "transport": "stdio" | "http" | "sse" | "unix",
          "command": "...", "args": [...], "env": {...}, "cwd": "...",
          "url": "...", "headers": {...},
          "socket_path": "...",
          "description": "..."
        }
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be a JSON object"}, status=400)

    name = body.get("name")
    transport = body.get("transport")
    if not isinstance(name, str) or not name.strip():
        return web.json_response({"error": "'name' is required"}, status=400)
    if transport not in _VALID_TRANSPORTS:
        return web.json_response(
            {"error": f"'transport' must be one of {sorted(_VALID_TRANSPORTS)}"},
            status=400,
        )

    reg = _registry()
    try:
        entry = reg.add_local(
            name=name.strip(),
            transport=transport,
            command=body.get("command"),
            args=body.get("args"),
            env=body.get("env"),
            cwd=body.get("cwd"),
            url=body.get("url"),
            headers=body.get("headers"),
            socket_path=body.get("socket_path"),
            description=body.get("description", ""),
        )
    except MCPError as exc:
        status = 409 if "already exists" in exc.what else 400
        return _mcp_error_response(exc, default_status=status)
    except Exception as exc:
        logger.exception("MCP add_local failed for %r", name)
        return web.json_response({"error": str(exc)}, status=500)

    summary = _server_to_summary({"name": name, **entry})
    return web.json_response(
        {
            "server": summary,
            "hint": "Start a new queen session to use this server's tools.",
        },
        status=201,
    )


async def handle_remove_server(request: web.Request) -> web.Response:
    """DELETE /api/mcp/servers/{name} — remove a local server."""
    name = request.match_info["name"]
    reg = _registry()

    existing = reg.get_server(name)
    if existing is None:
        return web.json_response({"error": f"Server '{name}' not installed"}, status=404)
    if existing.get("source") != "local":
        return web.json_response(
            {
                "error": f"Server '{name}' is a built-in; it cannot be removed from the UI.",
            },
            status=400,
        )

    try:
        reg.remove(name)
    except MCPError as exc:
        return _mcp_error_response(exc, default_status=404)
    return web.json_response({"removed": name})


async def handle_set_enabled(request: web.Request, *, enabled: bool) -> web.Response:
    name = request.match_info["name"]
    reg = _registry()
    try:
        if enabled:
            reg.enable(name)
        else:
            reg.disable(name)
    except MCPError as exc:
        return _mcp_error_response(exc, default_status=404)
    return web.json_response({"name": name, "enabled": enabled})


async def handle_enable(request: web.Request) -> web.Response:
    """POST /api/mcp/servers/{name}/enable."""
    return await handle_set_enabled(request, enabled=True)


async def handle_disable(request: web.Request) -> web.Response:
    """POST /api/mcp/servers/{name}/disable."""
    return await handle_set_enabled(request, enabled=False)


async def handle_health(request: web.Request) -> web.Response:
    """POST /api/mcp/servers/{name}/health — probe one server."""
    name = request.match_info["name"]
    reg = _registry()
    try:
        # MCPRegistry.health_check blocks on subprocess IO — run it off
        # the event loop so the HTTP worker stays responsive.
        import asyncio

        result = await asyncio.to_thread(reg.health_check, name)
    except MCPError as exc:
        return _mcp_error_response(exc, default_status=404)
    except Exception as exc:
        logger.exception("MCP health_check failed for %r", name)
        return web.json_response({"error": str(exc)}, status=500)
    return web.json_response(result)


def register_routes(app: web.Application) -> None:
    """Register MCP server CRUD routes."""
    app.router.add_get("/api/mcp/servers", handle_list_servers)
    app.router.add_post("/api/mcp/servers", handle_add_server)
    app.router.add_delete("/api/mcp/servers/{name}", handle_remove_server)
    app.router.add_post("/api/mcp/servers/{name}/enable", handle_enable)
    app.router.add_post("/api/mcp/servers/{name}/disable", handle_disable)
    app.router.add_post("/api/mcp/servers/{name}/health", handle_health)
