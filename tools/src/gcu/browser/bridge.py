"""
Beeline Bridge - WebSocket server that the Chrome extension connects to.

Lets Python code create/destroy tab groups in the user's existing Chrome and
move Playwright-managed tabs into those groups for visual isolation.

Usage:
    bridge = init_bridge()
    await bridge.start()          # at GCU server startup
    await bridge.stop()           # at GCU server shutdown

    # Per-subagent:
    result = await bridge.create_context("my-agent")   # {groupId, tabId}
    await bridge.group_tab_by_target(cdp_target_id, result["groupId"])
    await bridge.destroy_context(result["groupId"])

The bridge is optional — all callers check ``bridge.is_connected`` and no-op
when the extension is not present.
"""

from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

BRIDGE_PORT = 9229


class BeelineBridge:
    """WebSocket server that accepts a single connection from the Chrome extension."""

    def __init__(self) -> None:
        self._ws: object | None = None  # websockets.ServerConnection
        self._server: object | None = None  # websockets.Server
        self._pending: dict[str, asyncio.Future] = {}
        self._counter = 0

    @property
    def is_connected(self) -> bool:
        return self._ws is not None

    async def start(self, port: int = BRIDGE_PORT) -> None:
        """Start the WebSocket server."""
        try:
            import websockets
        except ImportError:
            logger.warning(
                "websockets not installed — Chrome extension bridge disabled. "
                "Install with: uv pip install websockets"
            )
            return

        try:
            self._server = await websockets.serve(self._handle_connection, "127.0.0.1", port)
            logger.info("Beeline bridge listening on ws://127.0.0.1:%d/bridge", port)
        except OSError as e:
            logger.warning("Beeline bridge could not start on port %d: %s", port, e)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None

    async def _handle_connection(self, ws) -> None:
        logger.info("Chrome extension connected")
        self._ws = ws
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if msg.get("type") == "hello":
                    logger.info("Extension hello: version=%s", msg.get("version"))
                    continue

                msg_id = msg.get("id")
                if msg_id and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if not fut.done():
                        if "error" in msg:
                            fut.set_exception(RuntimeError(msg["error"]))
                        else:
                            fut.set_result(msg.get("result", {}))
        except Exception:
            pass
        finally:
            logger.info("Chrome extension disconnected")
            self._ws = None
            # Cancel any pending requests
            for fut in self._pending.values():
                if not fut.done():
                    fut.cancel()
            self._pending.clear()

    async def _send(self, type_: str, **params) -> dict:
        """Send a command to the extension and wait for the result."""
        if not self._ws:
            raise RuntimeError("Extension not connected")
        self._counter += 1
        msg_id = str(self._counter)
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        try:
            await self._ws.send(json.dumps({"id": msg_id, "type": type_, **params}))
            return await asyncio.wait_for(fut, timeout=10.0)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise RuntimeError(f"Bridge command '{type_}' timed out")

    # ── Public API ────────────────────────────────────────────────────────────

    async def create_context(self, agent_id: str) -> dict:
        """Create a labelled tab group for this agent.

        Returns ``{"groupId": int, "tabId": int}``.
        """
        return await self._send("context.create", agentId=agent_id)

    async def destroy_context(self, group_id: int) -> dict:
        """Close all tabs in the group and remove it."""
        return await self._send("context.destroy", groupId=group_id)

    async def group_tab_by_target(self, cdp_target_id: str, group_id: int) -> dict:
        """Move a tab (identified by CDP target ID) into an existing group."""
        return await self._send("tab.group_by_target", targetId=cdp_target_id, groupId=group_id)

    async def create_tab(self, group_id: int, url: str) -> dict:
        """Create a new tab in the specified group and navigate to URL.

        Returns ``{"tabId": int}``.
        """
        return await self._send("tab.create", groupId=group_id, url=url)

    async def close_tab(self, tab_id: int) -> dict:
        """Close a tab by ID."""
        return await self._send("tab.close", tabId=tab_id)

    async def list_tabs(self, group_id: int | None = None) -> dict:
        """List tabs, optionally filtered by group.

        Returns ``{"tabs": [{"id": int, "url": str, "title": str}, ...]}``.
        """
        params = {"groupId": group_id} if group_id is not None else {}
        return await self._send("tab.list", **params)

    async def cdp_attach(self, tab_id: int) -> dict:
        """Attach CDP session to a tab for automation.

        Returns ``{"ok": bool}``.
        """
        return await self._send("cdp.attach", tabId=tab_id)

    async def cdp_send(self, tab_id: int, method: str, params: dict | None = None) -> dict:
        """Send a CDP command to a tab.

        Returns the CDP result.
        """
        return await self._send("cdp", tabId=tab_id, method=method, params=params or {})


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bridge: BeelineBridge | None = None


def get_bridge() -> BeelineBridge | None:
    """Return the bridge singleton, or None if not initialised."""
    return _bridge


def init_bridge() -> BeelineBridge:
    """Create (or return) the bridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = BeelineBridge()
    return _bridge
