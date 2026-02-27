"""aiohttp Application factory for the Hive HTTP API server."""

import logging
import os
from pathlib import Path

from aiohttp import web

from framework.server.session_manager import Session, SessionManager

logger = logging.getLogger(__name__)


def safe_path_segment(value: str) -> str:
    """Validate a URL path parameter is a safe filesystem name.

    Raises HTTPBadRequest if the value contains path separators or
    traversal sequences.  aiohttp decodes ``%2F`` inside route params,
    so a raw ``{session_id}`` can contain ``/`` or ``..`` after decoding.
    """
    if "/" in value or "\\" in value or ".." in value:
        raise web.HTTPBadRequest(reason="Invalid path parameter")
    return value


def resolve_session(request: web.Request):
    """Resolve a Session from {session_id} in the URL.

    Returns (session, None) on success or (None, error_response) on failure.
    """
    manager: SessionManager = request.app["manager"]
    sid = request.match_info["session_id"]
    session = manager.get_session(sid)
    if not session:
        return None, web.json_response({"error": f"Session '{sid}' not found"}, status=404)
    return session, None


def sessions_dir(session: Session) -> Path:
    """Resolve the worker sessions directory for a session.

    Storage layout: ~/.hive/agents/{agent_name}/sessions/
    Requires a worker to be loaded (worker_path must be set).
    """
    if session.worker_path is None:
        raise ValueError("No worker loaded — no worker sessions directory")
    agent_name = session.worker_path.name
    return Path.home() / ".hive" / "agents" / agent_name / "sessions"


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
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Max-Age"] = "3600"

    return response


@web.middleware
async def error_middleware(request: web.Request, handler):
    """Catch exceptions and return JSON error responses."""
    try:
        return await handler(request)
    except web.HTTPException:
        raise  # Let aiohttp handle its own HTTP exceptions
    except Exception as e:
        logger.exception(f"Unhandled error: {e}")
        return web.json_response(
            {"error": str(e), "type": type(e).__name__},
            status=500,
        )


async def _on_shutdown(app: web.Application) -> None:
    """Gracefully unload all agents on server shutdown."""
    manager: SessionManager = app["manager"]
    await manager.shutdown_all()


async def handle_health(request: web.Request) -> web.Response:
    """GET /api/health — simple health check."""
    manager: SessionManager = request.app["manager"]
    sessions = manager.list_sessions()
    return web.json_response(
        {
            "status": "ok",
            "sessions": len(sessions),
            "agents_loaded": sum(1 for s in sessions if s.worker_runtime is not None),
        }
    )


def create_app(model: str | None = None) -> web.Application:
    """Create and configure the aiohttp Application.

    Args:
        model: Default LLM model for agent loading.

    Returns:
        Configured aiohttp Application ready to run.
    """
    app = web.Application(middlewares=[cors_middleware, error_middleware])

    # Store manager on app for handlers
    app["manager"] = SessionManager(model=model)

    # Initialize credential store
    from framework.credentials.store import CredentialStore

    try:
        from framework.credentials.validation import ensure_credential_key_env

        ensure_credential_key_env()

        # Ensure HIVE_CREDENTIAL_KEY exists and is persisted (same as TUI setup flow).
        # ensure_credential_key_env() loads from shell config but won't generate a new
        # key. Web-only users who never ran the TUI need one auto-generated + persisted
        # so credentials survive server restarts.
        if not os.environ.get("HIVE_CREDENTIAL_KEY"):
            try:
                from aden_tools.credentials.shell_config import add_env_var_to_shell_config
                from cryptography.fernet import Fernet

                generated_key = Fernet.generate_key().decode()
                os.environ["HIVE_CREDENTIAL_KEY"] = generated_key
                add_env_var_to_shell_config(
                    "HIVE_CREDENTIAL_KEY",
                    generated_key,
                    comment="Encryption key for Hive credential store",
                )
                logger.info("Generated and persisted HIVE_CREDENTIAL_KEY to shell config")
            except Exception as exc:
                logger.warning("Could not auto-persist HIVE_CREDENTIAL_KEY: %s", exc)

        app["credential_store"] = CredentialStore.with_aden_sync()
    except Exception:
        logger.debug("Encrypted credential store unavailable, using in-memory fallback")
        app["credential_store"] = CredentialStore.for_testing({})

    # Register shutdown hook
    app.on_shutdown.append(_on_shutdown)

    # Health check
    app.router.add_get("/api/health", handle_health)

    # Register route modules
    from framework.server.routes_credentials import register_routes as register_credential_routes
    from framework.server.routes_events import register_routes as register_event_routes
    from framework.server.routes_execution import register_routes as register_execution_routes
    from framework.server.routes_graphs import register_routes as register_graph_routes
    from framework.server.routes_logs import register_routes as register_log_routes
    from framework.server.routes_sessions import register_routes as register_session_routes

    register_credential_routes(app)
    register_execution_routes(app)
    register_event_routes(app)
    register_session_routes(app)
    register_graph_routes(app)
    register_log_routes(app)

    # Static file serving — Option C production mode
    # If frontend/dist/ exists, serve built frontend files on /
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
