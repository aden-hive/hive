"""CLI commands for Hive — queens, colonies, sessions.

The new architecture has no exported agents, no graph execution.
Everything runs through the AgentLoop driven by SessionManager.

Commands:
    serve     Start the HTTP API server (the runtime hub)
    open      Start the server and open the dashboard
    queen     Manage queen profiles (list, show, sessions)
    colony    Manage colonies (list, info, delete)
    session   Manage live + cold sessions (list, stop)
    chat      Send a message to a live queen via the HTTP API
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from urllib import error as urlerror, parse as urlparse, request as urlrequest

# ---------------------------------------------------------------------------
# Public registration
# ---------------------------------------------------------------------------


def register_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register all runner commands with the main CLI parser."""
    _register_serve(subparsers)
    _register_open(subparsers)
    _register_queen(subparsers)
    _register_colony(subparsers)
    _register_session(subparsers)
    _register_chat(subparsers)


# ---------------------------------------------------------------------------
# serve / open
# ---------------------------------------------------------------------------


def _register_serve(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "serve",
        help="Start the HTTP API server",
        description="Start the aiohttp server exposing REST + SSE for queens, colonies, and sessions.",
    )
    p.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    p.add_argument("--port", "-p", type=int, default=8787, help="Port to listen on (default: 8787)")
    p.add_argument(
        "--colony",
        "-c",
        type=str,
        action="append",
        default=[],
        help="Colony path or name to preload (repeatable)",
    )
    p.add_argument("--model", "-m", type=str, default=None, help="LLM model for preloaded colonies")
    p.add_argument("--open", action="store_true", help="Open dashboard in browser after start")
    p.add_argument("--verbose", "-v", action="store_true", help="Enable INFO log level")
    p.add_argument("--debug", action="store_true", help="Enable DEBUG log level")
    p.set_defaults(func=cmd_serve)


def _register_open(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "open",
        help="Start the server and open the dashboard",
        description="Shortcut for 'hive serve --open'.",
    )
    p.add_argument("--host", type=str, default="127.0.0.1")
    p.add_argument("--port", "-p", type=int, default=8787)
    p.add_argument("--colony", "-c", type=str, action="append", default=[])
    p.add_argument("--model", "-m", type=str, default=None)
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=cmd_open)


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the HTTP API server (the runtime hub)."""
    import atexit
    import signal

    from aiohttp import web

    # Desktop-only fork: the web frontend is owned by the Electron renderer,
    # so we never build a Python-served frontend here.
    from framework.observability import configure_logging
    from framework.server.app import create_app

    if getattr(args, "debug", False):
        configure_logging(level="DEBUG")
    else:
        configure_logging(level="INFO")

    # Last-resort MCP cleanup. Runs on any process exit path, including
    # crashes — so hung MCP subprocesses don't outlive the server. The
    # graceful shutdown path below also disconnects clients; atexit is
    # belt-and-braces and no-ops if already cleaned.
    def _atexit_cleanup_mcp() -> None:
        try:
            from framework.loader.mcp_connection_manager import MCPConnectionManager

            MCPConnectionManager.get_instance().cleanup_all()
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).debug("atexit MCP cleanup failed: %s", exc)

    atexit.register(_atexit_cleanup_mcp)

    model = getattr(args, "model", None)
    app = create_app(model=model)

    # Browser-bridge startup is owned by _bridge_keepalive_loop (in run_server
    # below), NOT ensured here. That loop calls ensure_bridge_host_running on its
    # first iteration — off the event loop via asyncio.to_thread — so the bridge
    # comes up without gating site.start() on the up-to-8s cold-spawn poll (which
    # would otherwise add the full wait to the desktop's loading screen).
    #
    # We deliberately do NOT also ensure it here. ensure_bridge_host_running is
    # check-then-Popen with no cross-caller lock, and its spawned supervisor's
    # singleton guard only runs at entry — so two callers racing during the ~1-2s
    # window before the fresh worker binds the control port can each spawn a
    # supervisor. The loser's worker self-heals its bind failure and exits, but
    # its supervisor's respawn loop has no port re-check and crash-loops a doomed
    # worker for the session. Keeping the keepalive loop as the sole startup
    # ensurer makes that spawn single-owner and race-free. The side panel may
    # show "connecting" for a beat during boot — a window in which the desktop UI
    # is on its own loading screen anyway.

    # Advertise our port to every process we go on to spawn. The desktop picks a
    # random free port, so a child has no way to guess it — and the `hive-crm`
    # CLI needs to reach us to report a write it just landed, which is what keeps
    # an open CRM board live (framework.crm.notify). Inherited by MCP servers and,
    # through them, by the agent's shell commands.
    #
    # Set here rather than after site.start() so it is in place before ANYTHING
    # can spawn — the --colony preload below runs first. A bind failure exits the
    # process, so there is no window in which this names a port nobody is on.
    os.environ["HIVE_RUNTIME_PORT"] = str(args.port)

    async def run_server() -> None:
        manager = app["manager"]
        shutdown_event = asyncio.Event()
        signal_count = {"n": 0}

        def _request_shutdown(signame: str) -> None:
            signal_count["n"] += 1
            if signal_count["n"] == 1:
                print(f"\nReceived {signame}, shutting down gracefully… (press Ctrl+C again to force quit)")
                shutdown_event.set()
            else:
                # Second Ctrl+C (or SIGTERM) — the user is done waiting.
                # Skip the graceful teardown and exit immediately. os._exit
                # bypasses atexit handlers, so fire the MCP cleanup manually
                # first to avoid leaking subprocesses.
                print(f"\nReceived {signame} again — force quitting.")
                try:
                    from framework.loader.mcp_connection_manager import (
                        MCPConnectionManager,
                    )

                    MCPConnectionManager.get_instance().cleanup_all()
                except Exception:  # noqa: BLE001
                    pass
                os._exit(130)

        # Register SIGTERM (and explicit SIGINT) so container orchestrators
        # and plain Ctrl-C both route through the same graceful path —
        # manager.shutdown_all() flushes state and disconnects MCP clients.
        loop = asyncio.get_running_loop()
        for signame in ("SIGINT", "SIGTERM"):
            try:
                loop.add_signal_handler(
                    getattr(signal, signame),
                    _request_shutdown,
                    signame,
                )
            except (NotImplementedError, AttributeError):
                # Windows / restricted environments — fall back to default
                # handlers (KeyboardInterrupt for SIGINT; SIGTERM kills).
                pass

        # Desktop-mode keepalive: hold a single control-RPC connection
        # open to the bridge_host for the runtime's lifetime. Without
        # this, the bridge_host's idle watchdog self-exits 30s after
        # any window where no gcu MCP is connected — which is the steady
        # state immediately after app startup (user opened Hive but
        # hasn't triggered an agent yet). The Chrome extension then
        # tells the user "Hive isn't running" against a fully alive
        # runtime. Identifying via client_hello(electron_pid) lets the
        # bridge's reaper distinguish a healthy keepalive from a zombie
        # if this runtime ever crashes mid-connection.
        bridge_keepalive_task: asyncio.Task | None = None
        if os.environ.get("HIVE_DESKTOP_MODE") == "1":
            bridge_keepalive_task = asyncio.create_task(_bridge_keepalive_loop(manager))

        # Preload colonies specified via --colony
        for colony_arg in getattr(args, "colony", []) or []:
            colony_path = _resolve_colony_path(colony_arg)
            if colony_path is None:
                print(f"Colony not found: {colony_arg}")
                continue
            try:
                session = await manager.create_session(colony_id=Path(colony_path).name, model=model)
                print(f"Loaded colony: {session.colony_id} → session {session.id}")
            except Exception as e:  # noqa: BLE001
                print(f"Error loading colony {colony_arg}: {e}")

        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, args.host, args.port)
        await site.start()

        # Sentinel: colony-queen autopilot. The manager owns outbound
        # escalation delivery + the inbound Telegram/Slack listeners and
        # routes replies back into the parked queen. No-op unless the global
        # ``sentinel`` config enables it.
        sentinel_mgr = None
        try:
            from framework.sentinel.manager import SentinelManager, set_sentinel_manager

            sentinel_mgr = SentinelManager(session_manager=manager)
            set_sentinel_manager(sentinel_mgr)
            await sentinel_mgr.start()
        except Exception:  # noqa: BLE001 — never let Sentinel block server start
            logging.getLogger(__name__).warning("sentinel: failed to start (continuing without it)", exc_info=True)

        dashboard_url = f"http://{args.host}:{args.port}"
        has_frontend = _frontend_dist_exists()

        live_count = sum(1 for s in manager.list_sessions() if s.colony_id is not None)
        queen_only = sum(1 for s in manager.list_sessions() if s.colony_id is None)

        print()
        print(f"Hive API server running on {dashboard_url}")
        if has_frontend:
            print(f"Dashboard:  {dashboard_url}")
        print(f"Health:     {dashboard_url}/api/health")
        print(f"Sessions:   {live_count} colony, {queen_only} queen-only")
        print()
        print("Press Ctrl+C to stop")

        if getattr(args, "open", False) and has_frontend:
            _open_browser(dashboard_url)

        try:
            await shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            if bridge_keepalive_task is not None:
                bridge_keepalive_task.cancel()
                try:
                    await bridge_keepalive_task
                except (asyncio.CancelledError, Exception):
                    pass
            if sentinel_mgr is not None:
                try:
                    from framework.sentinel.manager import set_sentinel_manager

                    await sentinel_mgr.stop()
                    set_sentinel_manager(None)
                except Exception:  # noqa: BLE001
                    pass
            await manager.shutdown_all()
            await runner.cleanup()

    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        print("\nServer stopped.")
    return 0


async def _bridge_keepalive_loop(manager: Any = None) -> None:
    """Hold a control-RPC connection open to bridge_host for our lifetime.

    See call site in cmd_serve for the motivation. Reconnects with
    exponential backoff if the bridge restarts, re-issuing client_hello
    each time (the bridge's per-WS state is wiped on disconnect).

    When ``manager`` (the SessionManager) is supplied we additionally
    subscribe to server-initiated notify frames and route them into the
    right agent's inject_event — that's the delivery path for "user
    detached / handed over tab X" messages from the Chrome side panel.

    Cancelled cleanly by run_server's finally clause on shutdown — the
    WS close on our side triggers the bridge's idle-watchdog grace,
    which then exits the bridge_host process. That's the desktop-quit
    cleanup path now: runtime exits → keepalive WS closes → bridge_host
    sees zero alive clients → 30s grace → bridge_host exits.
    """
    try:
        from gcu.bridge_host import ensure_bridge_host_running
        from gcu.browser.bridge_rpc import BridgeClient, BridgeClientError
    except ImportError:
        return

    pid_str = os.environ.get("HIVE_DESKTOP_PARENT_PID")
    if not pid_str or not pid_str.isdigit():
        # No owner PID → we can't run the identified keepalive (client_hello
        # needs it). But this loop is also the sole startup bridge ensurer in
        # desktop mode, so bailing here without ensuring would leave the bridge
        # unspawned — narrowing parity with the old synchronous cmd_serve call
        # (which ensured whenever HIVE_DESKTOP_MODE==1, regardless of PARENT_PID).
        # Do a best-effort one-shot ensure before returning. Off-thread because
        # ensure_bridge_host_running blocks on Popen + an up-to-8s poll.
        try:
            await asyncio.to_thread(ensure_bridge_host_running)
        except Exception:  # noqa: BLE001
            pass
        return
    owner_pid = int(pid_str)

    logger = logging.getLogger(__name__)

    async def _on_notify(profile: str, text: str, extra: dict) -> None:
        """Route a side-panel notify frame to the matching agent.

        The bridge's ``profile`` is globally unique: it's the queen's
        session.id for queens (set in queen_orchestrator) and the
        worker's worker.id for workers (set in worker.py:run). So one of
        the two lookups below will match — first session.id (queen
        loop), then worker.id under each session's colony.
        """
        if manager is None:
            return
        for session in manager.list_sessions():
            # Queen match: session.id == profile.
            if session.id == profile:
                executor = getattr(session, "queen_executor", None)
                if executor is None:
                    continue
                node = executor.node_registry.get("queen") if hasattr(executor, "node_registry") else None
                if node is None or not hasattr(node, "inject_event"):
                    continue
                try:
                    await node.inject_event(text, is_client_input=True)
                except Exception:
                    logger.debug("notify: queen inject failed for session=%s", session.id, exc_info=True)
                return
            # Worker match: colony.inject_input is a worker_id lookup
            # and returns False on no match, so this is a cheap probe.
            colony = getattr(session, "colony", None)
            if colony is None:
                continue
            try:
                delivered = await colony.inject_input(profile, text, is_client_input=True)
            except Exception:
                logger.debug("notify: worker inject raised for profile=%s", profile, exc_info=True)
                continue
            if delivered:
                return
        logger.info("notify: no live agent matched profile=%s (extra=%s)", profile, extra)

    backoff = 1.0
    while True:
        # Make sure a bridge_host is running before we attempt to connect.
        # This loop is the SOLE startup ensurer — the first iteration here is
        # what spawns the bridge at boot (cmd_serve deliberately doesn't, to
        # keep the spawn single-owner; see the note there). If the bridge then
        # dies mid-session (e.g. it inherited a previous desktop's parent PID
        # and idle-exited 30s after the user closed that desktop) there's no
        # other respawn path until a gcu MCP happens to start — which leaves the
        # side panel stuck on "Hive isn't running" with a dead Reconnect button.
        # Calling ensure_bridge_host_running on every reconnect attempt covers
        # both: it's a cheap no-op when a bridge is already serving and spawns a
        # fresh supervisor (with the *current* desktop's PID baked in) when
        # nothing is. Runs in a thread because it blocks on subprocess.Popen +
        # a polling wait, which would otherwise stall this event loop for up to
        # 8s.
        try:
            await asyncio.to_thread(ensure_bridge_host_running)
        except Exception:  # noqa: BLE001
            # Spawn failure is non-fatal — fall through to the connect
            # attempt, which will raise BridgeClientError and back off
            # the same as any other unreachable-bridge case.
            pass

        client = BridgeClient()
        client.set_notify_handler(_on_notify)
        try:
            await client.connect()
            await client.call("client_hello", owner_pid)
            # Opt in to notify frames. Best-effort — old bridge builds
            # that don't speak the method get an "unknown_method" error
            # which we swallow; everything else still works without
            # the side-panel-message integration.
            try:
                await client.call("subscribe_notifications")
            except BridgeClientError as exc:
                logger.debug("bridge keepalive: subscribe_notifications failed (%s)", exc)
            backoff = 1.0
            # Hold the connection. BridgeClient's _read_loop runs in
            # background; we poll its is_connected flag (which it clears
            # when the socket drops) to detect bridge restart.
            while client.is_connected:
                await asyncio.sleep(5.0)
        except BridgeClientError as exc:
            # Bridge unreachable or call failed. Old bridge build that
            # doesn't speak client_hello: still keep the raw connection
            # open — even un-identified, it counts toward active clients
            # during the identify-grace window, which is enough to keep
            # the watchdog from firing until a fresh bridge is up.
            logger.debug("bridge keepalive: %s — retrying in %.1fs", exc, backoff)
        except asyncio.CancelledError:
            await client.close()
            return
        finally:
            # The connect-then-close roundtrip is harmless if connect
            # failed (close is idempotent). Don't await here on cancel —
            # the cancel-path above already closed.
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            return
        backoff = min(backoff * 2, 30.0)


def cmd_open(args: argparse.Namespace) -> int:
    """Start the HTTP server and open the dashboard in the browser."""
    # Don't block local startup on a best-effort analytics probe.
    threading.Thread(
        target=_ping_hive_gateway_availability,
        args=("hive-open",),
        daemon=True,
        name="hive-open-gateway-ping",
    ).start()
    args.open = True
    return cmd_serve(args)


# ---------------------------------------------------------------------------
# queen
# ---------------------------------------------------------------------------


def _register_queen(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "queen",
        help="Manage queen profiles",
        description="List, inspect, and explore queen identities.",
    )
    sub = p.add_subparsers(dest="subcommand", required=True)

    list_p = sub.add_parser("list", help="List all queen profiles")
    list_p.add_argument("--json", action="store_true", help="Output as JSON")
    list_p.set_defaults(func=cmd_queen_list)

    show_p = sub.add_parser("show", help="Show a queen profile")
    show_p.add_argument("queen_id", type=str, help="Queen identity (e.g. queen_technology)")
    show_p.add_argument("--json", action="store_true", help="Output as JSON")
    show_p.set_defaults(func=cmd_queen_show)

    sess_p = sub.add_parser("sessions", help="List sessions belonging to a queen")
    sess_p.add_argument("queen_id", type=str, help="Queen identity")
    sess_p.add_argument("--json", action="store_true")
    sess_p.set_defaults(func=cmd_queen_sessions)


def cmd_queen_list(args: argparse.Namespace) -> int:
    from framework.agents.queen.queen_profiles import ensure_default_queens, list_queens

    ensure_default_queens()
    queens = list_queens()
    if args.json:
        print(json.dumps(queens, indent=2))
        return 0

    if not queens:
        print("No queen profiles found.")
        return 0

    print(f"{'ID':<32}  {'NAME':<24}  TITLE")
    print("-" * 80)
    for q in queens:
        print(f"{q['id']:<32}  {q['name']:<24}  {q['title']}")
    return 0


def cmd_queen_show(args: argparse.Namespace) -> int:
    from framework.agents.queen.queen_profiles import load_queen_profile

    try:
        profile = load_queen_profile(args.queen_id)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    if args.json:
        print(json.dumps(profile, indent=2))
        return 0

    print(f"Queen ID:  {args.queen_id}")
    print(f"Name:      {profile.get('name', '')}")
    print(f"Title:     {profile.get('title', '')}")
    desc = profile.get("description") or profile.get("core_traits") or ""
    if isinstance(desc, list):
        desc = ", ".join(desc)
    if desc:
        print(f"Traits:    {desc}")
    skills = profile.get("skills") or []
    if skills:
        print(f"Skills:    {', '.join(skills) if isinstance(skills, list) else skills}")
    return 0


def cmd_queen_sessions(args: argparse.Namespace) -> int:
    from framework.config import QUEENS_DIR

    queen_dir = QUEENS_DIR / args.queen_id / "sessions"
    if not queen_dir.is_dir():
        print(f"No sessions for queen '{args.queen_id}'")
        return 0

    rows: list[dict[str, Any]] = []
    for session_dir in sorted(queen_dir.iterdir()):
        if not session_dir.is_dir():
            continue
        meta_path = session_dir / "meta.json"
        meta: dict = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        rows.append(
            {
                "session_id": session_dir.name,
                "phase": meta.get("phase", "?"),
                "agent_path": meta.get("agent_path", ""),
                "colony_fork": bool(meta.get("colony_fork")),
            }
        )

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    if not rows:
        print(f"No sessions for queen '{args.queen_id}'")
        return 0

    print(f"{'SESSION':<40}  {'PHASE':<10}  {'COLONY':<20}  FLAGS")
    print("-" * 90)
    for r in rows:
        flags = "fork" if r["colony_fork"] else ""
        colony = Path(r["agent_path"]).name if r["agent_path"] else ""
        print(f"{r['session_id']:<40}  {r['phase']:<10}  {colony:<20}  {flags}")
    return 0


# ---------------------------------------------------------------------------
# colony
# ---------------------------------------------------------------------------


def _register_colony(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "colony",
        help="Manage colonies",
        description="List, inspect, and delete colonies on disk.",
    )
    sub = p.add_subparsers(dest="subcommand", required=True)

    list_p = sub.add_parser("list", help="List all colonies")
    list_p.add_argument("--json", action="store_true")
    list_p.set_defaults(func=cmd_colony_list)

    info_p = sub.add_parser("info", help="Show colony details")
    info_p.add_argument("name", type=str, help="Colony name or path")
    info_p.add_argument("--json", action="store_true")
    info_p.set_defaults(func=cmd_colony_info)

    del_p = sub.add_parser("delete", help="Delete a colony from disk")
    del_p.add_argument("name", type=str, help="Colony name")
    del_p.add_argument(
        "--purge-storage",
        action="store_true",
        help="Also delete worker storage at ~/.hive/agents/{name}/",
    )
    del_p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    del_p.set_defaults(func=cmd_colony_delete)


def cmd_colony_list(args: argparse.Namespace) -> int:
    from framework.config import COLONIES_DIR

    if not COLONIES_DIR.is_dir():
        if args.json:
            print("[]")
        else:
            print("No colonies found.")
        return 0

    rows: list[dict[str, Any]] = []
    for path in sorted(COLONIES_DIR.iterdir()):
        if not path.is_dir():
            continue
        meta_path = path / "metadata.json"
        meta: dict = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        worker_count = sum(1 for f in path.iterdir() if f.is_file() and f.suffix == ".json" and f.stem not in _RESERVED_JSON_STEMS)
        rows.append(
            {
                "name": path.name,
                "queen_name": meta.get("queen_name", ""),
                "queen_session_id": meta.get("queen_session_id", ""),
                "workers": worker_count,
                "created_at": meta.get("created_at", ""),
                "path": str(path),
            }
        )

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    if not rows:
        print("No colonies found.")
        return 0

    print(f"{'NAME':<24}  {'QUEEN':<28}  {'WORKERS':<8}  CREATED")
    print("-" * 90)
    for r in rows:
        print(f"{r['name']:<24}  {r['queen_name']:<28}  {r['workers']:<8}  {r['created_at'][:19]}")
    return 0


def cmd_colony_info(args: argparse.Namespace) -> int:
    colony_path = _resolve_colony_path(args.name)
    if colony_path is None:
        print(f"Colony not found: {args.name}")
        return 1

    meta_path = colony_path / "metadata.json"
    metadata: dict = {}
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    workers: dict[str, dict] = {}
    for f in sorted(colony_path.iterdir()):
        if not (f.is_file() and f.suffix == ".json"):
            continue
        if f.stem in _RESERVED_JSON_STEMS:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                workers[f.stem] = {
                    "name": data.get("name", f.stem),
                    "description": data.get("description", ""),
                    "tools": len(data.get("tools", [])),
                    "goal": data.get("goal", {}).get("description", ""),
                    "spawned_from": data.get("spawned_from", ""),
                }
        except Exception:
            pass

    if args.json:
        print(json.dumps({"path": str(colony_path), "metadata": metadata, "workers": workers}, indent=2))
        return 0

    print(f"Colony:           {colony_path.name}")
    print(f"Path:             {colony_path}")
    print(f"Queen:            {metadata.get('queen_name', '?')}")
    print(f"Queen Session:    {metadata.get('queen_session_id', '?')}")
    print(f"Source Session:   {metadata.get('source_session_id', '?')}")
    print(f"Created:          {metadata.get('created_at', '?')}")
    print()
    print(f"Workers ({len(workers)}):")
    for wname, w in workers.items():
        print(f"  • {wname}")
        if w["goal"]:
            print(f"      goal:  {w['goal'][:80]}")
        print(f"      tools: {w['tools']}")
        if w["spawned_from"]:
            print(f"      from:  {w['spawned_from']}")
    return 0


def cmd_colony_delete(args: argparse.Namespace) -> int:
    from framework.config import COLONIES_DIR, HIVE_HOME

    colony_path = COLONIES_DIR / args.name
    if not colony_path.is_dir():
        print(f"Colony not found: {args.name}")
        return 1

    storage_path = HIVE_HOME / "agents" / args.name
    purge_storage = args.purge_storage and storage_path.is_dir()

    if not args.yes:
        print(f"This will permanently delete: {colony_path}")
        if purge_storage:
            print(f"And worker storage at:        {storage_path}")
        confirm = input("Type the colony name to confirm: ").strip()
        if confirm != args.name:
            print("Cancelled.")
            return 1

    shutil.rmtree(colony_path)
    print(f"Deleted {colony_path}")
    if purge_storage:
        shutil.rmtree(storage_path)
        print(f"Deleted {storage_path}")
    return 0


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------


def _register_session(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "session",
        help="Manage sessions",
        description="List live and cold sessions, stop running sessions.",
    )
    sub = p.add_subparsers(dest="subcommand", required=True)

    list_p = sub.add_parser("list", help="List sessions")
    list_p.add_argument("--cold", action="store_true", help="Include cold (on-disk) sessions")
    list_p.add_argument("--server", default="http://127.0.0.1:8787", help="Hive server URL")
    list_p.add_argument("--json", action="store_true")
    list_p.set_defaults(func=cmd_session_list)

    stop_p = sub.add_parser("stop", help="Stop a live session")
    stop_p.add_argument("session_id", type=str, help="Session ID to stop")
    stop_p.add_argument("--server", default="http://127.0.0.1:8787")
    stop_p.set_defaults(func=cmd_session_stop)


def cmd_session_list(args: argparse.Namespace) -> int:
    if args.cold:
        # Read directly from disk -- works without server
        from framework.server.session_manager import SessionManager

        rows = SessionManager.list_cold_sessions()
    else:
        # Hit the server's live session endpoint
        try:
            data = _http_get(f"{args.server}/api/sessions")
        except Exception as e:  # noqa: BLE001
            print(f"Could not reach server at {args.server}: {e}")
            print("Tip: pass --cold to read on-disk sessions, or start 'hive serve' first.")
            return 1
        rows = data.get("sessions", [])

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    if not rows:
        print("No sessions.")
        return 0

    print(f"{'SESSION':<40}  {'COLONY':<20}  {'PHASE':<12}  WORKER")
    print("-" * 90)
    for r in rows:
        sid = r.get("session_id", "?")
        colony = r.get("colony_id") or r.get("colony_id") or ""
        phase = r.get("queen_phase", "?")
        has_worker = "yes" if r.get("has_worker") else "no"
        print(f"{sid:<40}  {colony:<20}  {phase:<12}  {has_worker}")
    return 0


def cmd_session_stop(args: argparse.Namespace) -> int:
    try:
        data = _http_delete(f"{args.server}/api/sessions/{args.session_id}")
    except Exception as e:  # noqa: BLE001
        print(f"Could not reach server at {args.server}: {e}")
        return 1
    if data.get("stopped"):
        print(f"Stopped session {args.session_id}")
        return 0
    print(f"Failed to stop session: {data}")
    return 1


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------


def _register_chat(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "chat",
        help="Send a message to a live queen session",
        description="POST a chat message to a running session via the HTTP API.",
    )
    p.add_argument("session_id", type=str, help="Session ID")
    p.add_argument("message", type=str, help="Message text")
    p.add_argument("--server", default="http://127.0.0.1:8787", help="Hive server URL")
    p.set_defaults(func=cmd_chat)


def cmd_chat(args: argparse.Namespace) -> int:
    try:
        data = _http_post(
            f"{args.server}/api/sessions/{args.session_id}/chat",
            {"message": args.message},
        )
    except Exception as e:  # noqa: BLE001
        print(f"Could not reach server at {args.server}: {e}")
        return 1
    if "error" in data:
        print(f"Error: {data['error']}")
        return 1
    print(f"Sent. Tail the SSE stream at {args.server}/api/sessions/{args.session_id}/events")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# JSON files inside ~/.hive/colonies/{name}/ that are NOT worker configs.
_RESERVED_JSON_STEMS = {"agent", "flowchart", "triggers", "configuration", "metadata"}


def _resolve_colony_path(name_or_path: str) -> Path | None:
    """Resolve a colony argument to its on-disk Path.

    Accepts either an absolute/relative path to a colony directory or
    a bare colony name (looked up under ~/.hive/colonies/{name}/).
    """
    from framework.config import COLONIES_DIR

    candidate = Path(name_or_path).expanduser()
    if candidate.is_dir():
        return candidate
    by_name = COLONIES_DIR / name_or_path
    if by_name.is_dir():
        return by_name
    return None


def _http_get(url: str, timeout: float = 10.0) -> dict:
    req = urlrequest.Request(url, method="GET")
    with urlrequest.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_post(url: str, body: dict, timeout: float = 30.0) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urlrequest.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urlrequest.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_delete(url: str, timeout: float = 10.0) -> dict:
    req = urlrequest.Request(url, method="DELETE")
    with urlrequest.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _frontend_dist_exists() -> bool:
    candidates = [Path("frontend/dist"), Path("core/frontend/dist")]
    return any((c / "index.html").exists() for c in candidates if c.is_dir())


def _find_chrome_bin() -> str | None:
    """Return the path to a Chrome/Chromium binary, or None if not found."""
    for candidate in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        "microsoft-edge-stable",
    ):
        if shutil.which(candidate):
            return candidate

    mac_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for p in mac_paths:
        if Path(p).exists():
            return str(p)
    return None


def _open_browser(url: str) -> None:
    """Open URL in the browser (best-effort, non-blocking)."""
    chrome = _find_chrome_bin()
    try:
        if chrome:
            subprocess.Popen(
                [chrome, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
    except Exception:
        pass

    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            subprocess.Popen(
                ["cmd", "/c", "start", "", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "linux":
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _ping_hive_gateway_availability(from_source: str) -> None:
    """Best-effort reachability ping to the Hive gateway."""
    base_url = "https://api.adenhq.com/v1/gateway/availability"
    query = urlparse.urlencode({"from": from_source})
    url = f"{base_url}?{query}"
    try:
        with urlrequest.urlopen(url, timeout=5) as response:
            response.read()
    except (urlerror.URLError, TimeoutError, ValueError):
        pass


def _format_subprocess_output(output: str | bytes | None, limit: int = 2000) -> str:
    if not output:
        return ""
    text = output.decode(errors="replace") if isinstance(output, bytes) else output
    text = text.strip()
    return text if len(text) <= limit else text[-limit:]


def _build_frontend() -> bool:
    """Build the frontend if source is newer than dist. Returns True if dist exists."""
    candidates = [
        Path("core/frontend"),
        Path(__file__).resolve().parent.parent.parent / "frontend",
    ]
    frontend_dir: Path | None = None
    for c in candidates:
        if (c / "package.json").is_file():
            frontend_dir = c.resolve()
            break

    if frontend_dir is None:
        return False

    dist_dir = frontend_dir / "dist"
    src_dir = frontend_dir / "src"

    index_html = dist_dir / "index.html"
    if index_html.exists() and src_dir.is_dir():
        dist_mtime = index_html.stat().st_mtime
        needs_build = False
        for f in src_dir.rglob("*"):
            if f.is_file() and f.stat().st_mtime > dist_mtime:
                needs_build = True
                break
        if not needs_build:
            return True

    print("Building frontend...")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    try:
        for cache_file in frontend_dir.glob("tsconfig*.tsbuildinfo"):
            cache_file.unlink(missing_ok=True)

        subprocess.run(
            [npm_cmd, "install", "--no-fund", "--no-audit"],
            encoding="utf-8",
            errors="replace",
            cwd=frontend_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [npm_cmd, "run", "build"],
            encoding="utf-8",
            errors="replace",
            cwd=frontend_dir,
            check=True,
            capture_output=True,
        )
        print("Frontend built.")
        return True
    except FileNotFoundError:
        print("Node.js not found — skipping frontend build.")
        return dist_dir.is_dir()
    except subprocess.CalledProcessError as exc:
        stdout = _format_subprocess_output(exc.stdout)
        stderr = _format_subprocess_output(exc.stderr)
        cmd = " ".join(exc.cmd) if isinstance(exc.cmd, (list, tuple)) else str(exc.cmd)
        details = "\n".join(part for part in [stdout, stderr] if part).strip()
        if details:
            print(f"Frontend build failed while running {cmd}:\n{details}")
        else:
            print(f"Frontend build failed while running {cmd} (exit {exc.returncode}).")
        return dist_dir.is_dir()
