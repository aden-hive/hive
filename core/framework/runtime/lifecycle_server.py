"""
Lifecycle HTTP Server - REST API for external agent lifecycle control.

Exposes AgentRuntime lifecycle operations over HTTP so agents can be
managed programmatically from external systems, CI pipelines, or
orchestration tools without requiring direct Python access.

Endpoints
---------
GET  /health                                 Liveness check
GET  /status                                 Full runtime status and stats
POST /trigger/{entry_point_id}               Trigger execution (non-blocking)
POST /trigger/{entry_point_id}/wait          Trigger and wait for result
GET  /executions/{entry_point_id}/{exec_id}  Fetch a completed execution result
POST /stop                                   Stop the runtime gracefully

Usage::

    from framework.runtime.lifecycle_server import LifecycleServer, LifecycleServerConfig

    server = LifecycleServer(runtime, LifecycleServerConfig(host="0.0.0.0", port=8090))
    await server.start()
    # ... runtime running ...
    await server.stop()

Or via AgentRuntimeConfig::

    config = AgentRuntimeConfig(
        lifecycle_host="0.0.0.0",
        lifecycle_port=8090,
        lifecycle_enabled=True,
    )
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aiohttp import web

if TYPE_CHECKING:
    from framework.runtime.agent_runtime import AgentRuntime

logger = logging.getLogger(__name__)


@dataclass
class LifecycleServerConfig:
    """Configuration for the lifecycle HTTP server."""

    host: str = "127.0.0.1"
    port: int = 8090


class LifecycleServer:
    """
    Embedded HTTP server exposing AgentRuntime lifecycle operations as REST endpoints.

    The server wraps ``AgentRuntime`` methods without duplicating lifecycle logic.
    All heavy lifting (state tracking, streams, storage) stays inside the runtime.

    Lifecycle::

        server = LifecycleServer(runtime, config)
        await server.start()
        # server is now accepting requests
        await server.stop()
    """

    def __init__(
        self,
        runtime: AgentRuntime,
        config: LifecycleServerConfig | None = None,
    ) -> None:
        self._runtime = runtime
        self._config = config or LifecycleServerConfig()
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the HTTP server."""
        self._app = web.Application()
        self._register_routes(self._app)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._config.host, self._config.port)
        await self._site.start()

        logger.info(
            "LifecycleServer started on %s:%d",
            self._config.host,
            self._config.port,
        )

    async def stop(self) -> None:
        """Stop the HTTP server gracefully."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._app = None
            self._site = None
            logger.info("LifecycleServer stopped")

    def _register_routes(self, app: web.Application) -> None:
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/status", self._handle_status)
        app.router.add_post("/trigger/{entry_point_id}", self._handle_trigger)
        app.router.add_post("/trigger/{entry_point_id}/wait", self._handle_trigger_wait)
        app.router.add_get(
            "/executions/{entry_point_id}/{execution_id}",
            self._handle_get_execution,
        )
        app.router.add_post("/stop", self._handle_stop)

    # ------------------------------------------------------------------
    # Request helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _json_ok(data: dict[str, Any], status: int = 200) -> web.Response:
        return web.Response(
            status=status,
            content_type="application/json",
            text=json.dumps(data),
        )

    @staticmethod
    def _json_error(message: str, status: int) -> web.Response:
        return web.Response(
            status=status,
            content_type="application/json",
            text=json.dumps({"error": message}),
        )

    async def _parse_body(self, request: web.Request) -> dict[str, Any]:
        """Read and parse JSON body; return empty dict on empty / non-JSON body."""
        try:
            body = await request.read()
            if body:
                return json.loads(body)
        except (json.JSONDecodeError, ValueError):
            pass
        return {}

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_health(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """GET /health — liveness check."""
        return self._json_ok(
            {
                "ok": True,
                "running": self._runtime.is_running,
            }
        )

    async def _handle_status(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """GET /status — full runtime statistics."""
        try:
            stats = self._runtime.get_stats()
        except Exception as exc:
            logger.exception("Error fetching runtime stats")
            return self._json_error(str(exc), 500)

        return self._json_ok(
            {
                "running": self._runtime.is_running,
                "graph_id": self._runtime.graph_id,
                "graphs": self._runtime.list_graphs(),
                "stats": stats,
            }
        )

    async def _handle_trigger(self, request: web.Request) -> web.Response:
        """POST /trigger/{entry_point_id} — trigger execution, return exec_id immediately."""
        entry_point_id = request.match_info["entry_point_id"]

        if not self._runtime.is_running:
            return self._json_error("Runtime is not running", 503)

        body = await self._parse_body(request)
        input_data: dict[str, Any] = body.get("input", body)
        correlation_id: str | None = body.get("correlation_id")

        try:
            exec_id = await self._runtime.trigger(
                entry_point_id,
                input_data,
                correlation_id=correlation_id,
            )
        except ValueError as exc:
            return self._json_error(str(exc), 404)
        except RuntimeError as exc:
            return self._json_error(str(exc), 503)
        except Exception as exc:
            logger.exception("Trigger failed for entry point '%s'", entry_point_id)
            return self._json_error(str(exc), 500)

        return self._json_ok(
            {
                "execution_id": exec_id,
                "entry_point_id": entry_point_id,
                "status": "accepted",
            },
            status=202,
        )

    async def _handle_trigger_wait(self, request: web.Request) -> web.Response:
        """POST /trigger/{entry_point_id}/wait — trigger and wait for result.

        Optional body fields:
        - ``input``   (dict)  Input data forwarded to the entry point
        - ``timeout`` (float) Max seconds to wait (default: no timeout)
        """
        entry_point_id = request.match_info["entry_point_id"]

        if not self._runtime.is_running:
            return self._json_error("Runtime is not running", 503)

        body = await self._parse_body(request)
        input_data: dict[str, Any] = body.get("input", {})
        timeout: float | None = body.get("timeout")
        if timeout is not None:
            timeout = float(timeout)

        try:
            result = await self._runtime.trigger_and_wait(
                entry_point_id,
                input_data,
                timeout=timeout,
            )
        except ValueError as exc:
            return self._json_error(str(exc), 404)
        except RuntimeError as exc:
            return self._json_error(str(exc), 503)
        except Exception as exc:
            logger.exception("Trigger-and-wait failed for entry point '%s'", entry_point_id)
            return self._json_error(str(exc), 500)

        if result is None:
            return self._json_ok({"status": "timeout"}, status=408)

        return self._json_ok(
            {
                "status": "completed",
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "node_path": result.node_path,
            }
        )

    async def _handle_get_execution(self, request: web.Request) -> web.Response:
        """GET /executions/{entry_point_id}/{execution_id} — fetch a completed result."""
        entry_point_id = request.match_info["entry_point_id"]
        execution_id = request.match_info["execution_id"]

        result = self._runtime.get_execution_result(entry_point_id, execution_id)
        if result is None:
            return self._json_error(
                f"Execution '{execution_id}' not found for entry point '{entry_point_id}'",
                404,
            )

        return self._json_ok(
            {
                "execution_id": execution_id,
                "entry_point_id": entry_point_id,
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "node_path": result.node_path,
            }
        )

    async def _handle_stop(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """POST /stop — gracefully stop the AgentRuntime.

        The runtime shutdown is scheduled as a background task so this
        handler can return a 202 before the shutdown completes (avoiding
        a deadlock where the server waits for itself to stop).
        """
        if not self._runtime.is_running:
            return self._json_ok({"status": "already_stopped"})

        import asyncio

        asyncio.get_event_loop().create_task(self._runtime.stop())
        return self._json_ok({"status": "stopping"}, status=202)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """True when the HTTP server is accepting requests."""
        return self._site is not None

    @property
    def port(self) -> int | None:
        """Actual listening port (useful when configured with port=0)."""
        if self._site and self._site._server and self._site._server.sockets:
            return self._site._server.sockets[0].getsockname()[1]
        return None
