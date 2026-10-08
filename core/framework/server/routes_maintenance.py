"""Maintenance endpoints: manual janitor trigger + last report.

POST /api/maintenance/janitor/run   {"execute": false, "tiers": [1,2,3],
                                     "legacy": false, "junk": false}
GET  /api/maintenance/janitor/report

The run executes in a worker thread; the live-session SafetyContext is
snapshotted on the event loop BEFORE dispatch so in-flight queens and
workers are hard-blocked from pruning. ``execute`` defaults to false —
a bare POST is always a dry-run measurement.
"""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web

logger = logging.getLogger(__name__)

_RUN_GUARD_KEY = "janitor_running"


async def handle_janitor_run(request: web.Request) -> web.Response:
    from framework import config
    from framework.maintenance.janitor import run_once
    from framework.maintenance.retention import SafetyContext

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    execute = bool(body.get("execute", False))
    raw_tiers = body.get("tiers", [1, 2, 3])
    try:
        tiers = {int(t) for t in raw_tiers}
    except (TypeError, ValueError):
        return web.json_response({"error": f"invalid tiers: {raw_tiers!r}"}, status=400)
    if not tiers or not tiers <= {1, 2, 3}:
        return web.json_response({"error": f"invalid tiers: {raw_tiers!r}"}, status=400)

    app = request.app
    if app.get(_RUN_GUARD_KEY):
        return web.json_response({"error": "a janitor run is already in progress"}, status=409)

    manager = app["manager"]
    cfg = config.get_retention_config()
    # Snapshot live sessions/workers on the loop thread, before the
    # blocking pass starts — this is what makes an in-app run safe.
    safety = SafetyContext.from_manager(manager, cfg)
    process_start_ts = app.get("started_at")

    # Sessions can resume DURING a long run; give the pass a refresher
    # that re-snapshots the live set on the loop thread right before each
    # destructive tier-3 step (run_once itself runs in an executor).
    loop = asyncio.get_running_loop()

    async def _snapshot() -> tuple[frozenset[str], frozenset[str]]:
        fresh = SafetyContext.from_manager(manager, cfg)
        return fresh.protected_session_ids, fresh.live_session_dirs

    def _refresher() -> tuple[frozenset[str], frozenset[str]]:
        return asyncio.run_coroutine_threadsafe(_snapshot(), loop).result(timeout=10)

    safety.refresher = _refresher

    app[_RUN_GUARD_KEY] = True
    try:
        report = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: run_once(
                safety,
                cfg,
                tiers=tiers,
                execute=execute,
                include_legacy=bool(body.get("legacy", False)),
                include_junk=bool(body.get("junk", False)),
                process_start_ts=process_start_ts,
            ),
        )
    finally:
        app[_RUN_GUARD_KEY] = False

    return web.json_response({"report": report.to_dict()})


async def handle_janitor_report(request: web.Request) -> web.Response:
    from framework.maintenance.janitor import load_last_report

    report = load_last_report()
    if report is None:
        return web.json_response({"report": None})
    return web.json_response({"report": report})


def register_routes(app: web.Application) -> None:
    app.router.add_post("/api/maintenance/janitor/run", handle_janitor_run)
    app.router.add_get("/api/maintenance/janitor/report", handle_janitor_report)
