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
import shutil
import subprocess
import sys
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
    from aiohttp import web

    _build_frontend()

    from framework.observability import configure_logging
    from framework.server.app import create_app

    if getattr(args, "debug", False):
        configure_logging(level="DEBUG")
    else:
        configure_logging(level="INFO")

    model = getattr(args, "model", None)
    app = create_app(model=model)

    async def run_server() -> None:
        manager = app["manager"]

        # Preload colonies specified via --colony
        for colony_arg in getattr(args, "colony", []) or []:
            colony_path = _resolve_colony_path(colony_arg)
            if colony_path is None:
                print(f"Colony not found: {colony_arg}")
                continue
            try:
                session = await manager.create_session_with_worker_colony(
                    str(colony_path), model=model
                )
                info = session.worker_info
                name = info.name if info else session.colony_id
                print(f"Loaded colony: {session.colony_id} ({name}) → session {session.id}")
            except Exception as e:  # noqa: BLE001
                print(f"Error loading colony {colony_arg}: {e}")

        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, args.host, args.port)
        await site.start()

        dashboard_url = f"http://{args.host}:{args.port}"
        has_frontend = _frontend_dist_exists()

        live_count = sum(1 for s in manager.list_sessions() if s.colony_runtime is not None)
        queen_only = sum(1 for s in manager.list_sessions() if s.colony_runtime is None)

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
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            await manager.shutdown_all()
            await runner.cleanup()

    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        print("\nServer stopped.")
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    """Start the HTTP server and open the dashboard in the browser."""
    _ping_hive_gateway_availability("hive-open")
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
        rows.append({
            "session_id": session_dir.name,
            "phase": meta.get("phase", "?"),
            "agent_path": meta.get("agent_path", ""),
            "colony_fork": bool(meta.get("colony_fork")),
        })

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
        worker_count = sum(
            1
            for f in path.iterdir()
            if f.is_file() and f.suffix == ".json" and f.stem not in _RESERVED_JSON_STEMS
        )
        rows.append({
            "name": path.name,
            "queen_name": meta.get("queen_name", ""),
            "queen_session_id": meta.get("queen_session_id", ""),
            "workers": worker_count,
            "created_at": meta.get("created_at", ""),
            "path": str(path),
        })

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    if not rows:
        print("No colonies found.")
        return 0

    print(f"{'NAME':<24}  {'QUEEN':<28}  {'WORKERS':<8}  CREATED")
    print("-" * 90)
    for r in rows:
        print(
            f"{r['name']:<24}  {r['queen_name']:<28}  {r['workers']:<8}  {r['created_at'][:19]}"
        )
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
        colony = r.get("colony_name") or r.get("colony_id") or ""
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
    req = urlrequest.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
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
            subprocess.Popen(
                ["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        elif sys.platform == "win32":
            subprocess.Popen(
                ["cmd", "/c", "start", "", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "linux":
            subprocess.Popen(
                ["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
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
