"""aiohttp Application factory for the Hive HTTP API server."""

import hmac
import logging
import os
from pathlib import Path

from aiohttp import web

from framework.server.session_manager import Session, SessionManager

logger = logging.getLogger(__name__)

MANAGER_KEY = web.AppKey("manager", SessionManager)
CREDENTIAL_STORE_KEY = web.AppKey("credential_store", object)
QUEEN_TOOL_REGISTRY_KEY = web.AppKey("queen_tool_registry", object)


# Anchor to the repository root so allowed roots are independent of CWD.
# app.py lives at core/framework/server/app.py, so four .parent calls
# reach the repo root where exports/ and examples/ live.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_ALLOWED_AGENT_ROOTS: tuple[Path, ...] | None = None


def _has_encrypted_credentials() -> bool:
    """Return True when an encrypted credential store already exists on disk."""
    from framework.config import HIVE_HOME

    cred_dir = HIVE_HOME / "credentials" / "credentials"
    return cred_dir.is_dir() and any(cred_dir.glob("*.enc"))


def _get_allowed_agent_roots() -> tuple[Path, ...]:
    """Return resolved allowed root directories for agent loading.

    Roots are anchored to the repository root (derived from ``__file__``)
    so the allowlist is correct regardless of the process's working
    directory. The hive-home subtrees honour ``HIVE_HOME`` so the desktop's
    per-user root is allowed in addition to (or instead of) ``~/.hive``.
    """
    global _ALLOWED_AGENT_ROOTS
    if _ALLOWED_AGENT_ROOTS is None:
        from framework.config import COLONIES_DIR, HIVE_HOME

        _ALLOWED_AGENT_ROOTS = (
            COLONIES_DIR.resolve(),  # $HIVE_HOME/colonies/
            (_REPO_ROOT / "exports").resolve(),  # compat fallback
            (_REPO_ROOT / "examples").resolve(),
            (HIVE_HOME / "agents").resolve(),
        )
    return _ALLOWED_AGENT_ROOTS


def validate_agent_path(agent_path: str | Path) -> Path:
    """Validate that an agent path resolves inside an allowed directory.

    Prevents arbitrary code execution via ``importlib.import_module`` by
    restricting agent loading to known safe directories: ``exports/``,
    ``examples/``, and ``~/.hive/agents/``.

    Returns the resolved ``Path`` on success.

    Raises:
        ValueError: If the path is outside all allowed roots.
    """
    resolved = Path(agent_path).expanduser().resolve()
    for root in _get_allowed_agent_roots():
        if resolved.is_relative_to(root) and resolved != root:
            return resolved
    raise ValueError(
        "agent_path must be inside an allowed directory "
        "($HIVE_HOME/colonies/, exports/, examples/, or $HIVE_HOME/agents/)"
    )


def safe_path_segment(value: str) -> str:
    """Validate a URL path parameter is a safe filesystem name.

    Raises HTTPBadRequest if the value contains path separators or
    traversal sequences.  aiohttp decodes ``%2F`` inside route params,
    so a raw ``{session_id}`` can contain ``/`` or ``..`` after decoding.
    """
    if not value or value == "." or "/" in value or "\\" in value or ".." in value:
        raise web.HTTPBadRequest(reason="Invalid path parameter")
    return value


def resolve_session(request: web.Request):
    """Resolve a Session from {session_id} in the URL.

    Returns (session, None) on success or (None, error_response) on failure.
    """
    manager: SessionManager = request.app[MANAGER_KEY]
    sid = request.match_info["session_id"]
    session = manager.get_session(sid)
    if not session:
        return None, web.json_response({"error": f"Session '{sid}' not found"}, status=404)
    return session, None


def sessions_dir(session: Session) -> Path:
    """Resolve the worker sessions directory for a session.

    Storage layout: $HIVE_HOME/agents/{agent_name}/sessions/
    Requires a worker to be loaded (worker_path must be set).
    """
    if session.worker_path is None:
        raise ValueError("No worker loaded — no worker sessions directory")
    from framework.config import HIVE_HOME

    agent_name = session.worker_path.name
    return HIVE_HOME / "agents" / agent_name / "sessions"


# Allowed CORS origins (localhost on any port)
_CORS_ORIGINS = {"http://localhost", "http://127.0.0.1"}


def _is_cors_allowed(origin: str) -> bool:
    """Check if origin is localhost/127.0.0.1 on any port."""
    if not origin:
        return False
    for base in _CORS_ORIGINS:
        if origin == base or origin.startswith(base + ":"):
            return True
    return False


@web.middleware
async def cors_middleware(request: web.Request, handler):
    """CORS middleware scoped to localhost origins."""
    origin = request.headers.get("Origin", "")

    # Handle preflight
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            response = exc

    if _is_cors_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Max-Age"] = "3600"

    return response


@web.middleware
async def no_cache_api_middleware(request: web.Request, handler):
    """Prevent browsers from caching API responses.

    Without this, a one-off bad response (e.g. the SPA catch-all leaking
    index.html for an /api/* URL before a route was registered) can get
    pinned in the browser's disk cache and replayed forever, since our
    JSON handlers don't emit ETag/Last-Modified and browsers fall back
    to heuristic freshness.
    """
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = exc
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ---------------------------------------------------------------------------
# Desktop shared-secret auth middleware.
#
# When the runtime is spawned by the Electron main process, a fresh random
# token is passed via ``HIVE_DESKTOP_TOKEN``. Every request from main must
# carry the matching ``X-Hive-Token`` header. If the env var is unset (e.g.
# running ``hive serve`` directly from a terminal), the check is skipped —
# OSS behaviour is preserved.
# ---------------------------------------------------------------------------
_EXPECTED_DESKTOP_TOKEN: str | None = os.environ.get("HIVE_DESKTOP_TOKEN") or None


@web.middleware
async def desktop_auth_middleware(request: web.Request, handler):
    if _EXPECTED_DESKTOP_TOKEN is None:
        return await handler(request)
    provided = request.headers.get("X-Hive-Token", "")
    if not hmac.compare_digest(provided, _EXPECTED_DESKTOP_TOKEN):
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


@web.middleware
async def error_middleware(request: web.Request, handler):
    """Catch exceptions and return JSON error responses.

    Returns a generic error message to the client to avoid leaking
    internal details (file paths, config values, stack traces).
    The full exception is still logged server-side.
    """
    try:
        return await handler(request)
    except web.HTTPException:
        raise  # Let aiohttp handle its own HTTP exceptions
    except Exception:
        logger.exception("Unhandled error on %s %s", request.method, request.path)
        return web.json_response(
            {"error": "Internal server error"},
            status=500,
        )


async def _on_shutdown(app: web.Application) -> None:
    """Gracefully unload all agents on server shutdown."""
    manager: SessionManager = app[MANAGER_KEY]
    await manager.shutdown_all()


async def handle_health(request: web.Request) -> web.Response:
    """GET /api/health — simple health check."""
    manager: SessionManager = request.app[MANAGER_KEY]
    sessions = manager.list_sessions()
    return web.json_response(
        {
            "status": "ok",
            "sessions": len(sessions),
            "agents_loaded": sum(1 for s in sessions if s.colony_runtime is not None),
        }
    )


async def _probe_browser_bridge() -> dict:
    """Probe the local GCU bridge and return ``{bridge, connected}``.

    Shared by the one-shot ``GET /api/browser/status`` handler and the
    ``/api/browser/status/stream`` SSE feed so both see the same data
    source.
    """
    import asyncio

    bridge_port = int(os.environ.get("HIVE_BRIDGE_PORT", "9229"))
    status_port = bridge_port + 1

    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", status_port), timeout=0.5)
        writer.write(b"GET /status HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(512), timeout=0.5)
        writer.close()
        if b"\r\n\r\n" in raw:
            body = raw.split(b"\r\n\r\n", 1)[1]
            import json as _json

            data = _json.loads(body)
            return {"bridge": True, "connected": bool(data.get("connected", False))}
    except Exception:
        pass
    return {"bridge": False, "connected": False}


async def handle_browser_status(request: web.Request) -> web.Response:
    """GET /api/browser/status — proxy the GCU bridge status check server-side.

    Checks http://127.0.0.1:9230/status so the browser never makes a
    cross-origin request that would log ERR_CONNECTION_REFUSED in the console.
    """
    return web.json_response(await _probe_browser_bridge())


async def handle_browser_status_stream(request: web.Request) -> web.StreamResponse:
    """GET /api/browser/status/stream — SSE feed of bridge status.

    Emits a ``status`` event immediately, then again only when the
    probe result changes. Polls the local bridge every 3s; that's the
    same cadence the frontend used before, but we absorb it
    server-side instead of the browser burning a request.
    """
    import asyncio
    import json as _json

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await resp.prepare(request)

    async def _send(event: str, data: dict) -> None:
        payload = f"event: {event}\ndata: {_json.dumps(data)}\n\n"
        await resp.write(payload.encode("utf-8"))

    last: tuple | None = None
    try:
        while True:
            status = await _probe_browser_bridge()
            signature = (status["bridge"], status["connected"])
            if signature != last:
                await _send("status", status)
                last = signature
            await asyncio.sleep(3.0)
    except (asyncio.CancelledError, ConnectionResetError):
        raise
    except Exception as exc:
        logger.warning("browser status stream error: %s", exc, exc_info=True)
    return resp


def create_app(model: str | None = None) -> web.Application:
    """Create and configure the aiohttp Application.

    Args:
        model: Default LLM model for agent loading.

    Returns:
        Configured aiohttp Application ready to run.
    """
    # Desktop mode: the runtime is always a subprocess of the Electron main
    # process, which reaches it via IPC and the `hive://` custom protocol.
    # There is no browser origin to authorize, so CORS is unnecessary.
    # The auth middleware enforces the shared-secret token when the env var
    # is set (i.e. when Electron spawned us); it is a no-op otherwise.
    app = web.Application(middlewares=[desktop_auth_middleware, no_cache_api_middleware, error_middleware])

    # Initialize credential store (before SessionManager so it can be shared)
    from framework.credentials.store import CredentialStore

    try:
        from framework.credentials.validation import ensure_credential_key_env

        # Load ALL credentials: HIVE_CREDENTIAL_KEY, ADEN_API_KEY, and LLM keys
        ensure_credential_key_env()

        # Auto-generate credential key for web-only users who never ran the TUI
        if not os.environ.get("HIVE_CREDENTIAL_KEY"):
            if _has_encrypted_credentials():
                logger.warning(
                    "HIVE_CREDENTIAL_KEY is missing but encrypted credentials already exist; "
                    "not generating a replacement key because it would not decrypt existing credentials"
                )
            else:
                try:
                    from framework.credentials.key_storage import generate_and_save_credential_key

                    generate_and_save_credential_key()
                    logger.info("Generated and persisted HIVE_CREDENTIAL_KEY to ~/.hive/secrets/credential_key")
                except Exception as exc:
                    logger.warning("Could not auto-persist HIVE_CREDENTIAL_KEY: %s", exc)

        # Local server startup should not wait on an eager Aden sync.
        # The store can still fetch/refresh credentials on demand.
        if not os.environ.get("HIVE_CREDENTIAL_KEY") and _has_encrypted_credentials():
            credential_store = CredentialStore.with_env_storage()
        else:
            credential_store = CredentialStore.with_aden_sync(auto_sync=False)
    except Exception:
        logger.debug("Encrypted credential store unavailable, using in-memory fallback")
        credential_store = CredentialStore.for_testing({})

    app[CREDENTIAL_STORE_KEY] = credential_store

    # Let queen sessions build their registry lazily on first use instead of
    # paying the MCP discovery cost during `hive open`.
    app[QUEEN_TOOL_REGISTRY_KEY] = None
    app[MANAGER_KEY] = SessionManager(
        model=model,
        credential_store=credential_store,
        queen_tool_registry=None,
    )

    # Clear orphaned compaction markers from prior server crashes. Without
    # this, any session whose compaction was interrupted would block the
    # next colony cold-load for the full await_completion timeout (180s)
    # before falling through. See compaction_status.sweep_stale_in_progress.
    try:
        from framework.config import QUEENS_DIR
        from framework.server import compaction_status

        compaction_status.sweep_stale_in_progress(QUEENS_DIR)
    except Exception:
        logger.debug("compaction_status: startup sweep skipped", exc_info=True)

    # Register shutdown hook
    app.on_shutdown.append(_on_shutdown)

    # Health check
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/browser/status", handle_browser_status)
    app.router.add_get("/api/browser/status/stream", handle_browser_status_stream)

    # Register route modules
    from framework.server.routes_colonies import register_routes as register_colonies_routes
    from framework.server.routes_colony_tools import register_routes as register_colony_tools_routes
    from framework.server.routes_colony_workers import register_routes as register_colony_worker_routes
    from framework.server.routes_config import register_routes as register_config_routes
    from framework.server.routes_credentials import register_routes as register_credential_routes
    from framework.server.routes_events import register_routes as register_event_routes
    from framework.server.routes_execution import register_routes as register_execution_routes
    from framework.server.routes_logs import register_routes as register_log_routes
    from framework.server.routes_mcp import register_routes as register_mcp_routes
    from framework.server.routes_messages import register_routes as register_message_routes
    from framework.server.routes_prompts import register_routes as register_prompt_routes
    from framework.server.routes_queen_tools import register_routes as register_queen_tools_routes
    from framework.server.routes_queens import register_routes as register_queen_routes
    from framework.server.routes_sessions import register_routes as register_session_routes
    from framework.server.routes_skills import register_routes as register_skills_routes
    from framework.server.routes_tasks import register_routes as register_task_routes
    from framework.server.routes_workers import register_routes as register_worker_routes

    register_config_routes(app)
    register_credential_routes(app)
    register_execution_routes(app)
    register_event_routes(app)
    register_message_routes(app)
    register_session_routes(app)
    register_worker_routes(app)
    register_log_routes(app)
    register_queen_routes(app)
    register_queen_tools_routes(app)
    register_colonies_routes(app)
    register_colony_tools_routes(app)
    register_mcp_routes(app)
    register_colony_worker_routes(app)
    register_prompt_routes(app)
    register_skills_routes(app)
    register_task_routes(app)

    # Commercial extensions (optional — only present in hive-desktop-runtime).
    # Imports lazily so an OSS install without the `commercial` package keeps
    # working unchanged.
    try:
        from commercial.middleware import setup_commercial_middleware
        from commercial.routes import register_routes as register_commercial_routes

        setup_commercial_middleware(app)
        register_commercial_routes(app)
        logger.info("Commercial extensions loaded")
    except ImportError:
        pass

    # Serve the built frontend SPA (if frontend/dist exists) so hitting the
    # API host in a browser loads the dashboard instead of 404'ing. In
    # Electron/desktop mode the renderer still loads from file:// and
    # ignores this; in dev mode Vite is used instead.
    _setup_static_serving(app)

    return app


def _setup_static_serving(app: web.Application) -> None:
    """Serve frontend static files if the dist directory exists."""
    # Try: CWD/frontend/dist, core/frontend/dist, repo_root/frontend/dist
    _here = Path(__file__).resolve().parent  # core/framework/server/
    candidates = [
        Path("frontend/dist"),
        _here.parent.parent / "frontend" / "dist",  # core/frontend/dist
        _here.parent.parent.parent / "frontend" / "dist",  # repo_root/frontend/dist
    ]

    dist_dir: Path | None = None
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "index.html").exists():
            dist_dir = candidate.resolve()
            break

    if dist_dir is None:
        logger.debug("No frontend/dist found — skipping static file serving")
        return

    logger.info(f"Serving frontend from {dist_dir}")

    async def handle_spa(request: web.Request) -> web.FileResponse:
        """Serve static files with SPA fallback to index.html."""
        rel_path = request.match_info.get("path", "")
        file_path = (dist_dir / rel_path).resolve()

        if file_path.is_file() and file_path.is_relative_to(dist_dir):
            return web.FileResponse(file_path)

        # SPA fallback
        return web.FileResponse(dist_dir / "index.html")

    # Catch-all for SPA — must be registered LAST so /api routes take priority
    app.router.add_get("/{path:.*}", handle_spa)
