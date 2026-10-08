"""Server-Sent Events helper wrapping aiohttp StreamResponse."""

import json
import logging

from aiohttp import web

logger = logging.getLogger(__name__)


class SSEResponse:
    """Thin wrapper around aiohttp StreamResponse for SSE streaming.

    Usage:
        sse = SSEResponse()
        await sse.prepare(request)
        await sse.send_event({"key": "value"}, event="update")
        await sse.send_keepalive()
    """

    def __init__(self) -> None:
        self._response: web.StreamResponse | None = None

    async def prepare(self, request: web.Request) -> web.StreamResponse:
        """Prepare the SSE response with correct headers."""
        self._response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await self._response.prepare(request)
        return self._response

    async def send_event(
        self,
        data: dict,
        event: str | None = None,
        id: str | None = None,
    ) -> None:
        """Serialize and send an SSE event.

        Args:
            data: JSON-serializable dict to send as the data field.
            event: Optional SSE event type.
            id: Optional SSE event id.
        """
        if self._response is None:
            raise RuntimeError("SSEResponse not prepared; call prepare() first")

        parts: list[str] = []
        if id is not None:
            parts.append(f"id: {id}\n")
        if event is not None:
            parts.append(f"event: {event}\n")
        payload = json.dumps(data, default=str)
        parts.append(f"data: {payload}\n")
        parts.append("\n")

        await self._response.write("".join(parts).encode("utf-8"))

    async def send_keepalive(self) -> None:
        """Send an SSE comment as a keepalive heartbeat."""
        if self._response is None:
            raise RuntimeError("SSEResponse not prepared; call prepare() first")
        await self._response.write(b": keepalive\n\n")

    @property
    def response(self) -> web.StreamResponse | None:
        return self._response
