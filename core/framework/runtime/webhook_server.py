"""
Webhook HTTP Server - Receives HTTP requests and publishes them as EventBus events.

Only starts if webhook-type entry points are registered. Uses aiohttp for
a lightweight embedded HTTP server that runs within the existing asyncio loop.
"""

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass

from aiohttp import web

from framework.runtime.event_bus import EventBus

logger = logging.getLogger(__name__)


@dataclass
class WebhookRoute:
    """A registered webhook route derived from an EntryPointSpec."""

    source_id: str
    path: str
    methods: list[str]
    secret: str | None = None  # For HMAC-SHA256 signature verification


@dataclass
class WebhookServerConfig:
    """Configuration for the webhook HTTP server."""

    host: str = "127.0.0.1"
    port: int = 8080


class WebhookServer:
    """
    Embedded HTTP server that receives webhook requests and publishes
    them as WEBHOOK_RECEIVED events on the EventBus.

    The server's only job is: receive HTTP -> publish AgentEvent.
    Subscribers decide what to do with the event.

    Lifecycle:
        server = WebhookServer(event_bus, config)
        server.add_route(WebhookRoute(...))
        await server.start()
        # ... server running ...
        await server.stop()
    """

    def __init__(
        self,
        event_bus: EventBus,
        config: WebhookServerConfig | None = None,
    ):
        self._event_bus = event_bus
        self._config = config or WebhookServerConfig()
        self._routes: dict[str, WebhookRoute] = {}  # path -> route
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    def add_route(self, route: WebhookRoute) -> None:
        """Register a webhook route."""
        self._routes[route.path] = route

    async def start(self) -> None:
        """Start the HTTP server. No-op if no routes registered."""
        if not self._routes:
            logger.debug("No webhook routes registered, skipping server start")
            return

        self._app = web.Application()

        for path, route in self._routes.items():
            for method in route.methods:
                self._app.router.add_route(method, path, self._handle_request)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            self._config.host,
            self._config.port,
        )
        await self._site.start()
        logger.info(
            f"Webhook server started on {self._config.host}:{self._config.port} "
            f"with {len(self._routes)} route(s)"
        )

    async def stop(self) -> None:
        """Stop the HTTP server gracefully."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._app = None
            self._site = None
            logger.info("Webhook server stopped")

    async def _handle_request(self, request: web.Request) -> web.Response:
        """Handle an incoming webhook request."""
        path = request.path
        route = self._routes.get(path)

        if route is None:
            return web.json_response({"error": "Not found"}, status=404)

        # Read body
        try:
            body = await request.read()
        except Exception:
            return web.json_response(
                {"error": "Failed to read request body"},
                status=400,
            )

        # Verify HMAC signature if secret is configured
        if route.secret:
            if not self._verify_signature(request, body, route.secret):
                return web.json_response({"error": "Invalid signature"}, status=401)

        # Parse body as JSON (fall back to raw text for non-JSON)
        try:
            payload = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            payload = {"raw_body": body.decode("utf-8", errors="replace")}

        # Publish event to bus
        await self._event_bus.emit_webhook_received(
            source_id=route.source_id,
            path=path,
            method=request.method,
            headers=dict(request.headers),
            payload=payload,
            query_params=dict(request.query),
        )

        return web.json_response({"status": "accepted"}, status=202)

    def _verify_signature(
        self,
        request: web.Request,
        body: bytes,
        secret: str,
    ) -> bool:
        """Verify HMAC-SHA256 signature from X-Hub-Signature-256 header."""
        signature_header = request.headers.get("X-Hub-Signature-256", "")
        if not signature_header.startswith("sha256="):
            return False

        expected_sig = signature_header[7:]  # strip "sha256="
        computed_sig = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_sig, computed_sig)

    @property
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._site is not None

    @property
    def port(self) -> int | None:
        """Return the actual listening port (useful when configured with port=0)."""
        if self._site and self._site._server and self._site._server.sockets:
            return self._site._server.sockets[0].getsockname()[1]
        return None
