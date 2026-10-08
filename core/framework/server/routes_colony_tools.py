"""Per-colony MCP tool allowlist routes.

- GET   /api/colony/{colony_id}/tools  -- enumerate colony tool surface
- PATCH /api/colony/{colony_id}/tools  -- set or clear the allowlist

A colony's tool set is inherited from the queen that forked it, so the
tool surface mirrors the queen's MCP servers. Lifecycle/synthetic tools
are included for display only. MCP tools are grouped by origin server
with per-tool ``enabled`` flags.

Semantics:

- ``enabled_mcp_tools: null``  →  allow every MCP tool (default).
- ``enabled_mcp_tools: []``    →  allow no MCP tools (only lifecycle /
  synthetic pass through).
- ``enabled_mcp_tools: [...]`` →  only listed names pass.

The allowlist is persisted in a dedicated ``tools.json`` sidecar at
``~/.hive/colonies/{colony_id}/tools.json``. Changes take effect on
the *next* worker spawn. In-flight workers keep the tool list they
booted with because workers have no dynamic tools provider today —
mutating their tool set mid-turn would diverge from the list the LLM
is already using.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from framework.host.colony_metadata import colony_metadata_path
from framework.host.colony_tools_config import (
    load_colony_tools_config,
    update_colony_tools_config,
)

logger = logging.getLogger(__name__)


_SYNTHETIC_NAMES = {"ask_user"}


def _synthetic_entries() -> list[dict[str, Any]]:
    try:
        from framework.agent_loop.internals.synthetic_tools import build_ask_user_tool

        tool = build_ask_user_tool()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "editable": False,
            }
        ]
    except Exception:
        return [
            {
                "name": "ask_user",
                "description": "Pause and ask the user a structured question.",
                "editable": False,
            }
        ]


def _colony_runtimes_for_name(manager: Any, colony_id: str) -> list[Any]:
    """Return every live ColonyRuntime whose session is attached to ``colony_id``."""
    sessions = getattr(manager, "_sessions", None) or {}
    runtimes: list[Any] = []
    for session in sessions.values():
        if getattr(session, "colony_id", None) != colony_id:
            continue
        rt = getattr(session, "colony", None)
        if rt is not None and rt not in runtimes:
            runtimes.append(rt)
    return runtimes


async def _render_catalog(manager: Any, colony_id: str) -> dict[str, list[dict[str, Any]]]:
    """Build a per-server tool catalog for this colony.

    All colonies inherit the queen's MCP surface, so we reuse the
    manager-level ``_mcp_tool_catalog`` populated during queen boot.
    """
    # If a live runtime exists and carries its own registry, prefer it —
    # it's authoritative (reflects any post-queen-boot MCP additions).
    for rt in _colony_runtimes_for_name(manager, colony_id):
        tools = getattr(rt, "_tools", None)
        if not tools:
            continue
        mcp_names = set(getattr(rt, "_mcp_tool_names_all", set()) or set())
        if not mcp_names:
            continue
        # Stamp provider on each entry so the UI can grey out rows whose
        # credential isn't connected. Adapter is best-effort: when
        # aden_tools isn't available we just emit provider=None.
        tool_provider_map: dict[str, str] = {}
        try:
            from aden_tools.credentials.store_adapter import CredentialStoreAdapter

            tool_provider_map = CredentialStoreAdapter.default().get_tool_provider_map()
        except Exception:
            logger.debug("Colony catalog: provider map unavailable", exc_info=True)
        catalog: dict[str, list[dict[str, Any]]] = {"(mcp)": []}
        for tool in tools:
            name = getattr(tool, "name", None)
            if name in mcp_names:
                catalog["(mcp)"].append(
                    {
                        "name": name,
                        "description": getattr(tool, "description", ""),
                        "input_schema": getattr(tool, "parameters", {}),
                        "provider": tool_provider_map.get(name) or None,
                    }
                )
        return catalog

    # Otherwise read live from the bootstrap registry so credential
    # changes propagate without an explicit invalidation step. Build
    # the registry on demand (off the event loop) on first access.
    registry = getattr(manager, "_bootstrap_tool_registry", None) if manager is not None else None
    if registry is not None:
        return {
            server: sorted((dict(e) for e in entries), key=lambda e: e.get("name", "")) for server, entries in registry.get_full_mcp_catalog().items()
        }
    # Legacy dict snapshot (still used by some tests).
    legacy = getattr(manager, "_mcp_tool_catalog", None) if manager is not None else None
    if isinstance(legacy, dict) and legacy:
        return {server: sorted((dict(e) for e in entries), key=lambda e: e.get("name", "")) for server, entries in legacy.items()}
    if manager is None:
        return {}

    from framework.server.queen_orchestrator import ensure_bootstrap_tool_registry

    registry = await ensure_bootstrap_tool_registry(manager)
    if registry is None:
        return {}
    return {
        server: sorted((dict(e) for e in entries), key=lambda e: e.get("name", "")) for server, entries in registry.get_full_mcp_catalog().items()
    }


def _lifecycle_entries_from_runtime(manager: Any, colony_id: str) -> list[dict[str, Any]]:
    """Non-MCP tools currently registered on the colony runtime (if any).

    When no live runtime is available we fall back to the bootstrap
    registry stashed on the manager by ``routes_queen_tools`` — it
    already has queen lifecycle tools registered, which are also the
    lifecycle tools colonies inherit at spawn time.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _push(name: str, description: str) -> None:
        if not name or name in seen:
            return
        if name in _SYNTHETIC_NAMES:
            return
        seen.add(name)
        out.append({"name": name, "description": description, "editable": False})

    runtimes = _colony_runtimes_for_name(manager, colony_id)
    if runtimes:
        for rt in runtimes:
            mcp_names = set(getattr(rt, "_mcp_tool_names_all", set()) or set())
            for tool in getattr(rt, "_tools", []) or []:
                name = getattr(tool, "name", None)
                if name in mcp_names:
                    continue
                _push(name, getattr(tool, "description", ""))
    else:
        # No live runtime — derive from the bootstrap registry.
        from framework.server.routes_queen_tools import _lifecycle_entries_without_session

        catalog = getattr(manager, "_mcp_tool_catalog", {}) or {}
        mcp_names: set[str] = set()
        for entries in catalog.values():
            for entry in entries:
                if entry.get("name"):
                    mcp_names.add(entry["name"])
        out.extend(_lifecycle_entries_without_session(manager, mcp_names))
        return out
    return sorted(out, key=lambda e: e["name"])


def _render_servers(
    catalog: dict[str, list[dict[str, Any]]],
    enabled_mcp_tools: list[str] | None,
    connected_providers: set[str],
) -> list[dict[str, Any]]:
    allowed: set[str] | None = None if enabled_mcp_tools is None else set(enabled_mcp_tools)
    servers: list[dict[str, Any]] = []
    for name in sorted(catalog):
        tools = []
        for entry in catalog[name]:
            tool_name = entry.get("name")
            provider = entry.get("provider") or None
            tools.append(
                {
                    "name": tool_name,
                    "description": entry.get("description", ""),
                    "input_schema": entry.get("input_schema", {}),
                    "enabled": True if allowed is None else tool_name in allowed,
                    "provider": provider,
                    "provider_connected": (True if provider is None else provider in connected_providers),
                }
            )
        servers.append({"name": name, "tools": tools})
    return servers


async def handle_get_tools(request: web.Request) -> web.Response:
    """GET /api/colony/{colony_id}/tools."""
    colony_id = request.match_info["colony_id"]
    if not colony_metadata_path(colony_id).exists():
        return web.json_response({"error": f"Colony '{colony_id}' not found"}, status=404)

    manager = request.app.get("manager")
    # Allowlist now lives in a dedicated tools.json sidecar; helper
    # migrates any legacy metadata.json field on first read.
    enabled = load_colony_tools_config(colony_id)

    catalog = await _render_catalog(manager, colony_id)
    stale = not catalog

    # Snapshot live OAuth providers so disconnected credentialed tools
    # can be greyed out + offer a Connect button. Mirrors routes_queen_tools.
    from framework.server.routes_queen_tools import _connected_providers

    connected_providers = _connected_providers()

    return web.json_response(
        {
            "colony_id": colony_id,
            "enabled_mcp_tools": enabled,
            "stale": stale,
            "lifecycle": _lifecycle_entries_from_runtime(manager, colony_id),
            "synthetic": _synthetic_entries(),
            "mcp_servers": _render_servers(catalog, enabled, connected_providers),
            "connected_providers": sorted(connected_providers),
        }
    )


async def handle_patch_tools(request: web.Request) -> web.Response:
    """PATCH /api/colony/{colony_id}/tools."""
    colony_id = request.match_info["colony_id"]
    if not colony_metadata_path(colony_id).exists():
        return web.json_response({"error": f"Colony '{colony_id}' not found"}, status=404)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(body, dict) or "enabled_mcp_tools" not in body:
        return web.json_response(
            {"error": "Body must be an object with an 'enabled_mcp_tools' field"},
            status=400,
        )

    enabled = body["enabled_mcp_tools"]
    if enabled is not None:
        if not isinstance(enabled, list) or not all(isinstance(x, str) for x in enabled):
            return web.json_response(
                {"error": "'enabled_mcp_tools' must be null or a list of strings"},
                status=400,
            )

    manager = request.app.get("manager")

    # Validate names against the known MCP catalog — lifts the same
    # typo-catching guarantee we already offer on queen tools.
    catalog = await _render_catalog(manager, colony_id)
    known: set[str] = {e.get("name") for entries in catalog.values() for e in entries if e.get("name")}
    if enabled is not None and known:
        unknown = sorted(set(enabled) - known)
        if unknown:
            return web.json_response(
                {"error": "Unknown MCP tool name(s)", "unknown": unknown},
                status=400,
            )

    # Persist — tools.json sidecar, not metadata.json. Missing directory
    # is already guarded by the 404 check above.
    try:
        update_colony_tools_config(colony_id, enabled)
    except FileNotFoundError:
        return web.json_response({"error": f"Colony '{colony_id}' not found"}, status=404)

    # Update any live runtimes so the NEXT worker spawn reflects the change.
    # We do NOT rebuild in-flight workers' tool lists (see module docstring).
    refreshed = 0
    for rt in _colony_runtimes_for_name(manager, colony_id):
        setter = getattr(rt, "set_tool_allowlist", None)
        if callable(setter):
            try:
                setter(enabled)
                refreshed += 1
            except Exception:
                logger.debug(
                    "Colony tools: set_tool_allowlist failed on runtime for %s",
                    colony_id,
                    exc_info=True,
                )

    logger.info(
        "Colony tools: colony=%s allowlist=%s refreshed_runtimes=%d",
        colony_id,
        "null" if enabled is None else f"{len(enabled)} tool(s)",
        refreshed,
    )
    # Broadcast a TOOLS_CONFIG_CHANGED event so other Tool Library
    # tabs viewing this colony silently refetch.
    try:
        from framework.host.event_bus import AgentEvent, EventType, publish_global

        await publish_global(
            AgentEvent(
                type=EventType.TOOLS_CONFIG_CHANGED,
                stream_id="global",
                data={"scope": "colony", "scope_id": colony_id, "action": "update"},
            )
        )
    except Exception:
        logger.debug("Failed to publish TOOLS_CONFIG_CHANGED for colony", exc_info=True)
    return web.json_response(
        {
            "colony_id": colony_id,
            "enabled_mcp_tools": enabled,
            "refreshed_runtimes": refreshed,
            "note": "Changes apply to the next worker spawn. Running workers keep their booted tool list.",
        }
    )


async def handle_list_colonies(request: web.Request) -> web.Response:
    """GET /api/colonies — list colonies with their tool allowlist status.

    Powers the Tool Library page's colony picker.
    """
    from framework.host.colony_metadata import list_colony_ids, load_colony_metadata

    colonies: list[dict[str, Any]] = []
    for name in list_colony_ids():
        meta = load_colony_metadata(name)
        # Provenance stays in metadata.json; allowlist lives in tools.json.
        allowlist = load_colony_tools_config(name)
        colonies.append(
            {
                "name": name,
                "queen_name": meta.get("queen_name"),
                "created_at": meta.get("created_at"),
                "has_allowlist": allowlist is not None,
                "enabled_count": len(allowlist) if isinstance(allowlist, list) else None,
            }
        )
    return web.json_response({"colonies": colonies})


def register_routes(app: web.Application) -> None:
    """Register per-colony tool routes."""
    app.router.add_get("/api/colonies/tools-index", handle_list_colonies)
    app.router.add_get("/api/colony/{colony_id}/tools", handle_get_tools)
    app.router.add_patch("/api/colony/{colony_id}/tools", handle_patch_tools)
