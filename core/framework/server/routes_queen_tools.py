"""Per-queen MCP tool allowlist routes.

- GET   /api/queen/{queen_id}/tools  -- enumerate the queen's tool surface
- PATCH /api/queen/{queen_id}/tools  -- set or clear the MCP tool allowlist

Lifecycle and synthetic tools (``ask_user``) are always part of the queen's
surface in INDEPENDENT mode and are returned with ``editable: false``. MCP
tools are grouped by origin server and carry per-tool ``enabled`` flags.

The allowlist is persisted in a dedicated ``tools.json`` sidecar at
``~/.hive/agents/queens/{queen_id}/tools.json``:

- ``null`` / missing file -> "allow every MCP tool" (default)
- ``[]``                  -> explicitly disable every MCP tool
- ``["foo", "bar"]``      -> only these MCP tools pass through to the LLM

Filtering happens in ``QueenPhaseState.rebuild_independent_filter`` so the
LLM prompt cache stays warm between saves.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from framework.agents.queen.queen_profiles import (
    ensure_default_queens,
    load_queen_profile,
)
from framework.agents.queen.queen_tools_config import (
    delete_queen_tools_config,
    load_queen_tools_config,
    tools_config_exists,
    update_queen_tools_config,
)
from framework.agents.queen.queen_tools_defaults import (
    configured_always_enabled_categories,
    list_category_names,
    queen_role_categories,
    resolve_category_tools,
)
from framework.cloud_sync_hooks import schedule_push

logger = logging.getLogger(__name__)


_SYNTHETIC_NAMES = {"ask_user"}


async def _ensure_manager_catalog(manager: Any) -> dict[str, list[dict[str, Any]]]:
    """Return a fresh MCP tool catalog from the manager's bootstrap registry.

    Critically, this reads through the registry's
    ``get_full_mcp_catalog()`` accessor on every call rather than
    caching a dict snapshot. The registry rebuilds its own
    ``_mcp_full_catalog`` whenever ``resync_mcp_servers_if_needed``
    fires (credential save, env-var change), so reading through the
    registry guarantees the response reflects the current credential
    state without needing any explicit invalidation step.

    On the first call after a fresh backend process — when no queen
    has booted yet — we lazily build the registry via
    ``build_queen_tool_registry_bare``. That spawns MCP subprocesses
    once and stashes the registry on the manager for subsequent calls.
    """
    if manager is None:
        return {}

    registry = getattr(manager, "_bootstrap_tool_registry", None)
    if registry is not None:
        return _normalize_catalog(registry.get_full_mcp_catalog())

    # Legacy dict snapshot (still used by some tests). Production
    # writes ``_bootstrap_tool_registry`` so this branch is rarely
    # exercised at runtime.
    legacy = getattr(manager, "_mcp_tool_catalog", None)
    if isinstance(legacy, dict) and legacy:
        return _normalize_catalog(legacy)

    from framework.server.queen_orchestrator import ensure_bootstrap_tool_registry

    registry = await ensure_bootstrap_tool_registry(manager)
    return _normalize_catalog(registry.get_full_mcp_catalog() if registry is not None else {})


def _normalize_catalog(
    catalog: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Sort each per-server tool list by name for stable rendering."""
    return {server: sorted((dict(e) for e in entries), key=lambda e: e.get("name", "")) for server, entries in catalog.items()}


def _lifecycle_entries_without_session(
    manager: Any,
    mcp_names: set[str],
) -> list[dict[str, Any]]:
    """Derive lifecycle tool names from the registry even without a session.

    We register queen lifecycle tools against a temporary registry using a
    minimal stub, then subtract the MCP-origin set and the synthetic set.
    The result matches what the queen sees at runtime (minus context-
    specific variants).
    """
    registry = getattr(manager, "_bootstrap_tool_registry", None)
    # If the bootstrap registry exists but doesn't carry lifecycle tools
    # yet, register them now.
    if registry is not None and not getattr(registry, "_lifecycle_bootstrap_done", False):
        try:
            from types import SimpleNamespace

            from framework.tools.queen_lifecycle_tools import register_queen_lifecycle_tools

            stub_session = SimpleNamespace(
                id="tool-library-bootstrap",
                colony_runtime=None,
                event_bus=None,
                worker_path=None,
                phase_state=None,
                llm=None,
            )
            register_queen_lifecycle_tools(
                registry,
                session=stub_session,
                session_id=stub_session.id,
                session_manager=None,
                manager_session_id=stub_session.id,
                phase_state=None,
            )
            registry._lifecycle_bootstrap_done = True  # type: ignore[attr-defined]
        except Exception:
            logger.debug("lifecycle bootstrap failed", exc_info=True)

    if registry is None:
        return []

    out: list[dict[str, Any]] = []
    for name, tool in sorted(registry.get_tools().items()):
        if name in mcp_names or name in _SYNTHETIC_NAMES:
            continue
        out.append(
            {
                "name": tool.name,
                "description": tool.description,
                "editable": False,
            }
        )
    return out


def _synthetic_entries() -> list[dict[str, Any]]:
    """Return display metadata for synthetic tools injected by the agent loop.

    Kept behind a lazy import so test harnesses that don't wire the agent
    loop can still hit this route without blowing up.
    """
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


def _live_queen_session(manager: Any, queen_id: str) -> Any:
    """Return a live session owned by this queen, preferring DM over colony."""
    sessions = getattr(manager, "_sessions", None) or {}
    colony_fallback = None
    for session in sessions.values():
        if getattr(session, "queen_name", None) != queen_id:
            continue
        if getattr(session, "colony_runtime", None) is None:
            return session
        colony_fallback = session
    return colony_fallback


def _render_mcp_servers(
    *,
    mcp_tool_names_by_server: dict[str, list[dict[str, Any]]],
    enabled_mcp_tools: list[str] | None,
    connected_providers: set[str],
) -> list[dict[str, Any]]:
    """Shape the mcp_tool_catalog entries for the API response.

    Each tool carries an optional ``provider`` and ``provider_connected``
    flag so the Tool Library can render greyed-out rows + a Connect
    button for credentialed tools whose OAuth provider hasn't been
    authorized yet.
    """
    allowed: set[str] | None = None if enabled_mcp_tools is None else set(enabled_mcp_tools)
    servers: list[dict[str, Any]] = []
    for server_name in sorted(mcp_tool_names_by_server):
        entries = mcp_tool_names_by_server[server_name]
        tools = []
        for entry in entries:
            name = entry.get("name")
            enabled = True if allowed is None else name in allowed
            provider = entry.get("provider") or None
            tools.append(
                {
                    "name": name,
                    "description": entry.get("description", ""),
                    "input_schema": entry.get("input_schema", {}),
                    "enabled": enabled,
                    "provider": provider,
                    "provider_connected": (True if provider is None else provider in connected_providers),
                }
            )
        servers.append({"name": server_name, "tools": tools})
    return servers


def _catalog_from_live_session(session: Any) -> dict[str, list[dict[str, Any]]]:
    """Rebuild a per-server tool catalog from a live queen session.

    The session's registry is authoritative — this reflects any hot-added
    MCP servers since the manager-level snapshot was cached. We source
    from the registry's full pre-credential-gate catalog so the Tool
    Library can list credentialed tools whose provider hasn't been
    authorized yet (the UI greys them out and offers a Connect button).
    """
    registry = getattr(session, "_queen_tool_registry", None)
    if registry is None:
        # session._queen_tools_by_name is a stash from create_queen; we
        # only have registry via the tools list, so reconstruct from the
        # phase state instead. (No provider info available in this
        # fallback — used only when the registry handle is absent.)
        phase_state = getattr(session, "phase_state", None)
        if phase_state is None:
            return {}
        mcp_names = getattr(phase_state, "mcp_tool_names_all", set()) or set()
        phase_tools = (
            phase_state.get_current_tools()
            if callable(getattr(phase_state, "get_current_tools", None))
            else getattr(phase_state, "independent_tools", []) or []
        )
        result: dict[str, list[dict[str, Any]]] = {"MCP Tools": []}
        for tool in phase_tools:
            if tool.name not in mcp_names:
                continue
            result["MCP Tools"].append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                    "provider": None,
                }
            )
        return result if result["MCP Tools"] else {}

    full_catalog = registry.get_full_mcp_catalog() if hasattr(registry, "get_full_mcp_catalog") else {}
    if full_catalog:
        return {
            server: sorted(
                (dict(entry) for entry in entries),
                key=lambda e: e.get("name", ""),
            )
            for server, entries in full_catalog.items()
        }

    # Legacy fallback for registries that pre-date `_mcp_full_catalog`.
    # Same admission-filtered shape as before; the UI will still work,
    # it just won't show provider-disconnected tools.
    server_map = getattr(registry, "_mcp_server_tools", {}) or {}
    tools_by_name = {t.name: t for t in registry.get_tools().values()}
    catalog: dict[str, list[dict[str, Any]]] = {}
    for server_name, tool_names in server_map.items():
        entries: list[dict[str, Any]] = []
        for name in sorted(tool_names):
            tool = tools_by_name.get(name)
            if tool is None:
                continue
            entries.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                    "provider": None,
                }
            )
        catalog[server_name] = entries
    return catalog


def _lifecycle_entries(
    *,
    session: Any,
    mcp_tool_names_all: set[str],
) -> list[dict[str, Any]]:
    """Lifecycle tools = current-phase tools minus MCP-origin minus synthetic.

    We compute this from a live session when available so the list exactly
    matches what the queen actually sees on her next turn. Uses
    ``get_current_tools()`` so the correct phase (independent / colony)
    is reflected.
    """
    if session is None:
        return []
    phase_state = getattr(session, "phase_state", None)
    if phase_state is None:
        return []
    current_tools = (
        phase_state.get_current_tools()
        if callable(getattr(phase_state, "get_current_tools", None))
        else getattr(phase_state, "independent_tools", []) or []
    )
    result: list[dict[str, Any]] = []
    for tool in current_tools:
        if tool.name in mcp_tool_names_all:
            continue
        if tool.name in _SYNTHETIC_NAMES:
            continue
        result.append(
            {
                "name": tool.name,
                "description": tool.description,
                "editable": False,
            }
        )
    return sorted(result, key=lambda x: x["name"])


async def _build_tools_snapshot(manager: Any, queen_id: str) -> dict[str, Any]:
    """Build the same response shape returned by GET /api/queen/{id}/tools.

    Factored out so PATCH/DELETE can return the post-mutation snapshot
    in their response body — saves the editor a round-trip and keeps
    its local state from drifting against a catalog that may have
    changed concurrently (e.g. the user authorised a provider in
    another tab between the GET and the save).
    """
    session = _live_queen_session(manager, queen_id) if manager is not None else None

    if session is not None:
        catalog = _catalog_from_live_session(session)
    else:
        catalog = await _ensure_manager_catalog(manager)
    stale = not catalog

    mcp_tool_names_all: set[str] = set()
    for entries in catalog.values():
        for entry in entries:
            if entry.get("name"):
                mcp_tool_names_all.add(entry["name"])

    if session is not None:
        lifecycle = _lifecycle_entries(
            session=session,
            mcp_tool_names_all=mcp_tool_names_all,
        )
    else:
        lifecycle = _lifecycle_entries_without_session(manager, mcp_tool_names_all)

    # Default-on for OAuth: when the queen is on the role-based default
    # (no tools.json saved), ``load_queen_tools_config`` augments the
    # allowlist with every tool whose provider is currently authorised.
    # That augmentation lives in ``queen_tools_config`` so the queen
    # orchestrator's boot path (which calls the same loader) gets the
    # same answer — without that, the UI promised tools the runtime
    # didn't actually expose to the queen. Once the user saves an
    # explicit allowlist, the sidecar exists and the augmentation
    # branch isn't taken — their explicit unticks survive.
    enabled_mcp_tools = load_queen_tools_config(queen_id, mcp_catalog=catalog)
    is_role_default = not tools_config_exists(queen_id)
    connected_providers = _connected_providers()

    return {
        "queen_id": queen_id,
        "enabled_mcp_tools": enabled_mcp_tools,
        "is_role_default": is_role_default,
        "stale": stale,
        "lifecycle": lifecycle,
        "synthetic": _synthetic_entries(),
        "mcp_servers": _render_mcp_servers(
            mcp_tool_names_by_server=catalog,
            enabled_mcp_tools=enabled_mcp_tools,
            connected_providers=connected_providers,
        ),
        "categories": _render_categories(queen_id, catalog),
        "connected_providers": sorted(connected_providers),
    }


async def handle_get_tools(request: web.Request) -> web.Response:
    """GET /api/queen/{queen_id}/tools — enumerate tool surface for the UI."""
    queen_id = request.match_info["queen_id"]
    ensure_default_queens()
    try:
        load_queen_profile(queen_id)
    except FileNotFoundError:
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)

    manager = request.app.get("manager")
    snapshot = await _build_tools_snapshot(manager, queen_id)
    return web.json_response(snapshot)


def _connected_providers() -> set[str]:
    """Return the set of OAuth providers with at least one live account.

    Reads the credential store directly so the answer is always fresh
    (no cache to invalidate after a Connect/Disconnect round trip).
    Returns an empty set if ``aden_tools`` is unavailable.
    """
    try:
        from aden_tools.credentials.store_adapter import CredentialStoreAdapter

        adapter = CredentialStoreAdapter.default()
        return {(a.get("provider") or "") for a in adapter.get_all_account_info() if a.get("provider")}
    except Exception:
        logger.debug("Connected-providers snapshot unavailable", exc_info=True)
        return set()


def _render_categories(
    queen_id: str,
    mcp_catalog: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Expose the role-default category table to the frontend.

    Each entry carries the category name, the resolved member tool names
    (after ``@server:NAME`` shorthand expansion against the live catalog),
    ``in_role_default`` to flag categories that contribute to this queen's
    role-based default, and ``always_enabled`` to flag categories whose tools
    are loaded up front and bypass the allowlist (locked on in the UI — the
    queen always has them; the rest are searchable / loaded on demand). Lets
    the Tool Library group tools by tier and by category.

    ``email_senders`` is omitted while the senders feature is off (Settings →
    Developer): its tools aren't registered with the MCP server then, so the
    category would render as an empty, un-tickable shell. The category stays
    in the role-default table regardless — the names simply match nothing
    while off, and light up the moment the feature is enabled.
    """
    from framework.config import get_email_senders_enabled

    hidden = set() if get_email_senders_enabled() else {"email_senders"}
    applied = set(queen_role_categories(queen_id))
    out: list[dict[str, Any]] = []
    for name in list_category_names():
        if name in hidden:
            continue
        out.append(
            {
                "name": name,
                "tools": resolve_category_tools(name, mcp_catalog),
                "in_role_default": name in applied,
                "always_enabled": name in configured_always_enabled_categories(),
            }
        )
    return out


async def handle_patch_tools(request: web.Request) -> web.Response:
    """PATCH /api/queen/{queen_id}/tools — persist the MCP tool allowlist.

    Body: ``{"enabled_mcp_tools": null | string[]}``.

    - ``null`` resets to "allow every MCP tool" (default).
    - A list is validated against the known MCP catalog; unknown names
      are rejected with 400 so the frontend catches typos.
    """
    queen_id = request.match_info["queen_id"]
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

    ensure_default_queens()
    try:
        load_queen_profile(queen_id)
    except FileNotFoundError:
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)

    # Validate names against the known MCP tool catalog. We prefer a live
    # session's registry for the most up-to-date set, then fall back to
    # the manager-level snapshot (building it on demand if absent).
    manager = request.app.get("manager")
    session = _live_queen_session(manager, queen_id) if manager is not None else None
    if session is not None:
        catalog = _catalog_from_live_session(session)
    else:
        catalog = await _ensure_manager_catalog(manager)
    known_names: set[str] = set()
    for entries in catalog.values():
        for entry in entries:
            if entry.get("name"):
                known_names.add(entry["name"])

    if enabled is not None and known_names:
        unknown = sorted(set(enabled) - known_names)
        if unknown:
            return web.json_response(
                {"error": "Unknown MCP tool name(s)", "unknown": unknown},
                status=400,
            )

    # Persist — tools.json sidecar, not profile.yaml.
    try:
        update_queen_tools_config(queen_id, enabled)
    except FileNotFoundError:
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)

    # Hot-reload every live DM session for this queen. The filter memo is
    # rebuilt so the very next turn sees the new allowlist without a
    # session restart, and the prompt cache is invalidated exactly once.
    refreshed = 0
    sessions = getattr(manager, "_sessions", None) or {}
    for sess in sessions.values():
        if getattr(sess, "queen_name", None) != queen_id:
            continue
        phase_state = getattr(sess, "phase_state", None)
        if phase_state is None:
            continue
        phase_state.enabled_mcp_tools = enabled
        rebuild = getattr(phase_state, "rebuild_independent_filter", None)
        if callable(rebuild):
            try:
                rebuild()
                refreshed += 1
            except Exception:
                logger.debug(
                    "Queen tools: rebuild_independent_filter failed for session %s",
                    getattr(sess, "id", "?"),
                    exc_info=True,
                )

    logger.info(
        "Queen tools: queen_id=%s allowlist=%s refreshed_sessions=%d",
        queen_id,
        "null" if enabled is None else f"{len(enabled)} tool(s)",
        refreshed,
    )

    # Build the post-mutation snapshot so the editor can replace its
    # local state without a follow-up GET — and broadcast a cross-tab
    # event so any other Tool Library window viewing the same queen
    # silently refetches.
    snapshot = await _build_tools_snapshot(manager, queen_id)
    snapshot["refreshed_sessions"] = refreshed
    await _publish_tools_config_changed(
        scope="queen",
        scope_id=queen_id,
        action="update",
    )
    schedule_push("tool_allowlist", f"queen:{queen_id}")
    return web.json_response(snapshot)


async def _publish_tools_config_changed(
    *,
    scope: str,
    scope_id: str,
    action: str,
) -> None:
    """Broadcast a TOOLS_CONFIG_CHANGED event on the global bus.

    Subscribers (Tool Library tabs) that are viewing the same scope
    use this to refetch silently. ``scope`` is ``"queen"`` or
    ``"colony"``; ``action`` is ``"update"`` (PATCH) or ``"reset"``
    (DELETE → fall back to role default).
    """
    from framework.host.event_bus import AgentEvent, EventType, publish_global

    await publish_global(
        AgentEvent(
            type=EventType.TOOLS_CONFIG_CHANGED,
            stream_id="global",
            data={"scope": scope, "scope_id": scope_id, "action": action},
        )
    )


async def handle_delete_tools(request: web.Request) -> web.Response:
    """DELETE /api/queen/{queen_id}/tools — drop the sidecar, fall back to role defaults.

    Users click "Reset to role default" in the Tool Library. That
    removes ``tools.json`` so the queen's effective allowlist becomes
    the role-based default (or allow-all if the queen has no role
    entry). Live sessions are refreshed so the next turn reflects the
    change without a restart.
    """
    queen_id = request.match_info["queen_id"]
    ensure_default_queens()
    try:
        load_queen_profile(queen_id)
    except FileNotFoundError:
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)

    removed = delete_queen_tools_config(queen_id)

    # Recompute the queen's effective allowlist from the role defaults
    # so we can hot-reload live sessions in one pass (same shape as
    # PATCH).
    manager = request.app.get("manager")
    session = _live_queen_session(manager, queen_id) if manager is not None else None
    if session is not None:
        catalog = _catalog_from_live_session(session)
    else:
        catalog = await _ensure_manager_catalog(manager)
    new_enabled = load_queen_tools_config(queen_id, mcp_catalog=catalog)

    refreshed = 0
    sessions = getattr(manager, "_sessions", None) or {}
    for sess in sessions.values():
        if getattr(sess, "queen_name", None) != queen_id:
            continue
        phase_state = getattr(sess, "phase_state", None)
        if phase_state is None:
            continue
        phase_state.enabled_mcp_tools = new_enabled
        rebuild = getattr(phase_state, "rebuild_independent_filter", None)
        if callable(rebuild):
            try:
                rebuild()
                refreshed += 1
            except Exception:
                logger.debug(
                    "Queen tools: rebuild_independent_filter failed for session %s",
                    getattr(sess, "id", "?"),
                    exc_info=True,
                )

    logger.info(
        "Queen tools: queen_id=%s reset-to-default removed=%s refreshed_sessions=%d",
        queen_id,
        removed,
        refreshed,
    )

    # Return the same shape PATCH does + the removed flag, so the
    # editor replaces its local state in one shot. Also broadcast on
    # the global bus so other tabs refetch.
    snapshot = await _build_tools_snapshot(manager, queen_id)
    snapshot["removed"] = removed
    snapshot["refreshed_sessions"] = refreshed
    await _publish_tools_config_changed(
        scope="queen",
        scope_id=queen_id,
        action="reset",
    )
    schedule_push("tool_allowlist", f"queen:{queen_id}")
    return web.json_response(snapshot)


def register_routes(app: web.Application) -> None:
    """Register queen-tools routes."""
    app.router.add_get("/api/queen/{queen_id}/tools", handle_get_tools)
    app.router.add_patch("/api/queen/{queen_id}/tools", handle_patch_tools)
    app.router.add_delete("/api/queen/{queen_id}/tools", handle_delete_tools)
