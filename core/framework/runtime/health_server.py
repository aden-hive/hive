"""
Health Server - Lightweight HTTP server for Kubernetes health probes.

Provides HTTP endpoints for liveness and readiness probes,
compatible with Kubernetes, Docker health checks, and load balancers.

Endpoints:
    GET /health       → Full health status (JSON)
    GET /health/live  → Liveness probe (200 OK or 503)
    GET /health/ready → Readiness probe (200 OK or 503)

Usage:
    from framework.runtime.health_server import HealthServer

    # Create and start health server
    server = HealthServer(runtime, port=8080)
    await server.start()

    # Later, stop the server
    await server.stop()

    # Or use as context manager
    async with HealthServer(runtime, port=8080) as server:
        # Server is running
        await some_long_running_task()
    # Server is stopped
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from framework.runtime.agent_runtime import AgentRuntime
    from framework.runtime.health import HealthChecker

logger = logging.getLogger(__name__)


class HealthServer:
    """
    Lightweight async HTTP server for health endpoints.

    Designed to be minimal with no external dependencies beyond asyncio.
    Provides Kubernetes-compatible health probe endpoints.

    Example:
        runtime = AgentRuntime(...)
        await runtime.start()

        # Start health server on port 8080
        server = HealthServer(runtime, port=8080)
        await server.start()

        # Server responds to:
        # - GET /health       → {"status": "healthy", "state": "ready", ...}
        # - GET /health/live  → 200 OK or 503 Service Unavailable
        # - GET /health/ready → 200 OK or 503 Service Unavailable

    Kubernetes Configuration:
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10

        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
    """

    def __init__(
        self,
        runtime: AgentRuntime,
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        """
        Initialize health server.

        Args:
            runtime: The AgentRuntime to expose health for
            host: Host to bind to (default: 0.0.0.0)
            port: Port to listen on (default: 8080)
        """
        self._runtime = runtime
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None
        self._health_checker: HealthChecker | None = None

    async def start(self) -> None:
        """
        Start the health server.

        The server will listen for HTTP requests on the configured host:port.
        """
        from framework.runtime.health import HealthChecker

        self._health_checker = HealthChecker(self._runtime)

        self._server = await asyncio.start_server(
            self._handle_connection,
            self._host,
            self._port,
        )

        addrs = ", ".join(str(sock.getsockname()) for sock in self._server.sockets)
        logger.info(f"Health server listening on {addrs}")

    async def stop(self) -> None:
        """Stop the health server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("Health server stopped")

    async def __aenter__(self) -> HealthServer:
        """Context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        await self.stop()

    @property
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._server is not None and self._server.is_serving()

    @property
    def port(self) -> int:
        """Get the server port."""
        return self._port

    @property
    def url(self) -> str:
        """Get the base URL for the health server."""
        host = "localhost" if self._host == "0.0.0.0" else self._host
        return f"http://{host}:{self._port}"

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle an incoming HTTP connection."""
        try:
            # Read the request line
            request_line = await asyncio.wait_for(
                reader.readline(),
                timeout=5.0,
            )

            if not request_line:
                return

            # Parse request
            try:
                request_str = request_line.decode("utf-8").strip()
                parts = request_str.split(" ")
                if len(parts) < 2:
                    await self._send_response(writer, 400, "Bad Request")
                    return

                method = parts[0]
                path = parts[1]
            except (UnicodeDecodeError, IndexError):
                await self._send_response(writer, 400, "Bad Request")
                return

            # Only handle GET requests
            if method != "GET":
                await self._send_response(writer, 405, "Method Not Allowed")
                return

            # Read and discard headers
            while True:
                header_line = await asyncio.wait_for(
                    reader.readline(),
                    timeout=5.0,
                )
                if header_line in (b"\r\n", b"\n", b""):
                    break

            # Route request
            await self._route_request(writer, path)

        except TimeoutError:
            logger.debug("Connection timed out")
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            try:
                await self._send_response(writer, 500, "Internal Server Error")
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _route_request(
        self,
        writer: asyncio.StreamWriter,
        path: str,
    ) -> None:
        """Route request to appropriate handler."""
        if self._health_checker is None:
            await self._send_response(writer, 503, "Service Unavailable")
            return

        # Strip query string if present
        path = path.split("?")[0]

        if path == "/health":
            await self._handle_health(writer)
        elif path == "/health/live":
            await self._handle_liveness(writer)
        elif path == "/health/ready":
            await self._handle_readiness(writer)
        elif path == "/":
            # Root path redirects to health
            await self._handle_health(writer)
        else:
            await self._send_response(writer, 404, "Not Found")

    async def _handle_health(self, writer: asyncio.StreamWriter) -> None:
        """Handle GET /health - full health status."""
        assert self._health_checker is not None

        status = self._health_checker.health()
        body = json.dumps(status.to_dict(), indent=2)

        http_status = 200 if status.status == "healthy" else 503
        await self._send_json_response(writer, http_status, body)

    async def _handle_liveness(self, writer: asyncio.StreamWriter) -> None:
        """Handle GET /health/live - liveness probe."""
        assert self._health_checker is not None

        is_alive = self._health_checker.liveness()

        if is_alive:
            await self._send_response(writer, 200, "OK")
        else:
            await self._send_response(writer, 503, "Service Unavailable")

    async def _handle_readiness(self, writer: asyncio.StreamWriter) -> None:
        """Handle GET /health/ready - readiness probe."""
        assert self._health_checker is not None

        is_ready = self._health_checker.readiness()

        if is_ready:
            await self._send_response(writer, 200, "OK")
        else:
            await self._send_response(writer, 503, "Service Unavailable")

    async def _send_response(
        self,
        writer: asyncio.StreamWriter,
        status_code: int,
        body: str,
    ) -> None:
        """Send a plain text HTTP response."""
        status_text = self._get_status_text(status_code)
        response = (
            f"HTTP/1.1 {status_code} {status_text}\r\n"
            f"Content-Type: text/plain\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
            f"{body}"
        )
        writer.write(response.encode("utf-8"))
        await writer.drain()

    async def _send_json_response(
        self,
        writer: asyncio.StreamWriter,
        status_code: int,
        body: str,
    ) -> None:
        """Send a JSON HTTP response."""
        status_text = self._get_status_text(status_code)
        response = (
            f"HTTP/1.1 {status_code} {status_text}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
            f"{body}"
        )
        writer.write(response.encode("utf-8"))
        await writer.drain()

    def _get_status_text(self, status_code: int) -> str:
        """Get HTTP status text for a status code."""
        status_texts = {
            200: "OK",
            400: "Bad Request",
            404: "Not Found",
            405: "Method Not Allowed",
            500: "Internal Server Error",
            503: "Service Unavailable",
        }
        return status_texts.get(status_code, "Unknown")


async def create_health_server(
    runtime: AgentRuntime,
    port: int = 8080,
    host: str = "0.0.0.0",
) -> HealthServer:
    """
    Factory function to create and start a health server.

    Args:
        runtime: The AgentRuntime to expose
        port: Port to listen on (default: 8080)
        host: Host to bind to (default: 0.0.0.0)

    Returns:
        Started HealthServer instance
    """
    server = HealthServer(runtime, host=host, port=port)
    await server.start()
    return server
