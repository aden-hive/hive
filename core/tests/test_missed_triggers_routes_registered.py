"""Smoke test: the missed-handshake HTTP route is registered.

The handler body delegates to ``resolve_missed`` — unit-tested in
``test_missed_triggers.py``. This test exists purely to catch a
router-registration regression: a renamed handler or missed
``add_post`` line.
"""

from __future__ import annotations

from aiohttp import web

from framework.server.routes_sessions import register_routes


def _route_table(app: web.Application) -> set[tuple[str, str]]:
    """Return the set of (method, path) tuples currently registered."""
    out: set[tuple[str, str]] = set()
    for resource in app.router.resources():
        info = resource.get_info()
        path = info.get("path") or info.get("formatter") or ""
        for route in resource:
            out.add((route.method, path))
    return out


def test_resolve_missed_route_is_registered() -> None:
    app = web.Application()
    register_routes(app)
    routes = _route_table(app)
    assert ("POST", "/api/sessions/{session_id}/colony/resolve_missed") in routes
