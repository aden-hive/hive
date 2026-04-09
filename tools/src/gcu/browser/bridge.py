"""
Beeline Bridge - WebSocket server that the Chrome extension connects to.

Lets Python code control the user's Chrome directly via the extension's
chrome.debugger CDP access. No Playwright needed.

Usage:
    bridge = init_bridge()
    await bridge.start()          # at GCU server startup
    await bridge.stop()           # at GCU server shutdown

    # Per-subagent:
    result = await bridge.create_context("my-agent")   # {groupId, tabId}
    await bridge.navigate(tab_id, "https://example.com")
    await bridge.click(tab_id, "button")
    await bridge.type(tab_id, "input", "hello")
    snapshot = await bridge.snapshot(tab_id)

The bridge requires the Beeline Chrome extension to be installed and connected.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from .telemetry import (
    log_bridge_message,
    log_cdp_command,
    log_connection_event,
    log_context_event,
)

logger = logging.getLogger(__name__)

BRIDGE_PORT = 9229

# CDP wait_until values
VALID_WAIT_UNTIL = {"commit", "domcontentloaded", "load", "networkidle"}

# Last interaction highlight per tab_id: {x, y, w, h, label, kind}
# kind: "rect" (element) or "point" (coordinate)
_interaction_highlights: dict[int, dict] = {}


def _get_active_profile() -> str:
    """Get the current active profile from context variable."""
    try:
        from .session import _active_profile as ap

        return ap.get()
    except Exception:
        return "default"


STATUS_PORT = BRIDGE_PORT + 1  # 9230 — plain HTTP status endpoint


class BeelineBridge:
    """WebSocket server that accepts a single connection from the Chrome extension."""

    def __init__(self) -> None:
        self._ws: object | None = None  # websockets.ServerConnection
        self._server: object | None = None  # websockets.Server
        self._status_server: object | None = None  # asyncio.Server (HTTP)
        self._pending: dict[str, asyncio.Future] = {}
        self._counter = 0
        self._cdp_attached: set[int] = set()  # Track tabs with CDP attached

    @property
    def is_connected(self) -> bool:
        return self._ws is not None

    async def start(self, port: int = BRIDGE_PORT) -> None:
        """Start the WebSocket server and the HTTP status server."""
        try:
            import websockets
        except ImportError:
            logger.warning(
                "websockets not installed — Chrome extension bridge disabled. "
                "Install with: uv pip install websockets"
            )
            return

        try:
            # Suppress noisy websockets logging for invalid upgrade attempts
            # by providing a null logger
            import logging

            null_logger = logging.getLogger("websockets.null")
            null_logger.setLevel(logging.CRITICAL)
            null_logger.addHandler(logging.NullHandler())

            self._server = await websockets.serve(
                self._handle_connection,
                "127.0.0.1",
                port,
                logger=null_logger,
                max_size=50
                * 1024
                * 1024,  # 50 MB — CDP responses (AX tree, screenshots) can be large
            )
            logger.info("Beeline bridge listening on ws://127.0.0.1:%d", port)
        except OSError as e:
            logger.warning("Beeline bridge could not start on port %d: %s", port, e)

        # Start a tiny HTTP server on port+1 for status polling.
        # websockets 16 rejects plain HTTP before process_request is called, so
        # we need a separate server.
        status_port = port + 1
        try:
            self._status_server = await asyncio.start_server(
                self._http_status_handler,
                "127.0.0.1",
                status_port,
            )
            logger.info("Bridge status endpoint on http://127.0.0.1:%d/status", status_port)
        except OSError as e:
            logger.warning("Bridge status server could not start on port %d: %s", status_port, e)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None
        if self._status_server:
            self._status_server.close()
            try:
                await self._status_server.wait_closed()
            except Exception:
                pass
            self._status_server = None

    async def _http_status_handler(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Minimal asyncio TCP handler serving HTTP GET /status on the status port."""
        try:
            raw = await asyncio.wait_for(reader.read(512), timeout=2.0)
            first_line = raw.split(b"\r\n", 1)[0].decode(errors="replace")
            if first_line.startswith("GET /status"):
                body = json.dumps({"connected": self.is_connected, "bridge": "running"}).encode()
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Access-Control-Allow-Origin: *\r\n"
                    b"Access-Control-Allow-Headers: *\r\n"
                    + b"Content-Length: "
                    + str(len(body)).encode()
                    + b"\r\n"
                    + b"Connection: close\r\n"
                    b"\r\n" + body
                )
            elif first_line.startswith("OPTIONS "):
                response = (
                    b"HTTP/1.1 204 No Content\r\n"
                    b"Access-Control-Allow-Origin: *\r\n"
                    b"Access-Control-Allow-Headers: *\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n"
                    b"\r\n"
                )
            else:
                response = (
                    b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
            writer.write(response)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    async def _handle_connection(self, ws) -> None:
        logger.info("Chrome extension connected")
        log_connection_event("connect")
        self._ws = ws
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if msg.get("type") == "hello":
                    logger.info("Extension hello: version=%s", msg.get("version"))
                    log_connection_event("hello", {"version": msg.get("version")})
                    continue

                msg_id = msg.get("id")
                if msg_id and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if not fut.done():
                        if "error" in msg:
                            log_bridge_message(
                                "recv", "response", msg_id=msg_id, error=msg["error"]
                            )
                            fut.set_exception(RuntimeError(msg["error"]))
                        else:
                            log_bridge_message(
                                "recv", "response", msg_id=msg_id, result=msg.get("result")
                            )
                            fut.set_result(msg.get("result", {}))
        except Exception:
            pass
        finally:
            # Only clear self._ws if this handler still owns it.
            if self._ws is ws:
                logger.info("Chrome extension disconnected")
                log_connection_event("disconnect")
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
        start = time.perf_counter()

        log_bridge_message("send", type_, msg_id=msg_id, params=params)

        try:
            await self._ws.send(json.dumps({"id": msg_id, "type": type_, **params}))
            result = await asyncio.wait_for(fut, timeout=30.0)
            duration_ms = (time.perf_counter() - start) * 1000
            log_bridge_message("send", type_, msg_id=msg_id, result=result, duration_ms=duration_ms)
            return result
        except TimeoutError:
            self._pending.pop(msg_id, None)
            log_bridge_message("send", type_, msg_id=msg_id, error="timeout")
            raise RuntimeError(f"Bridge command '{type_}' timed out") from None
        except BaseException:
            # CancelledError or any other exception — remove stale future so a late
            # response from the extension doesn't try to resolve a cancelled future.
            self._pending.pop(msg_id, None)
            raise

    async def _cdp(self, tab_id: int, method: str, params: dict | None = None) -> dict:
        """Send a CDP command to a tab."""
        start = time.perf_counter()
        try:
            result = await self._send("cdp", tabId=tab_id, method=method, params=params or {})
            duration_ms = (time.perf_counter() - start) * 1000
            log_cdp_command(tab_id, method, params, result, duration_ms=duration_ms)
            return result
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            log_cdp_command(tab_id, method, params, error=str(e), duration_ms=duration_ms)
            raise

    async def _try_enable_domain(self, tab_id: int, domain: str) -> None:
        """Try to enable a CDP domain, ignoring errors if not available.

        Some domains (like Input) may not be available on certain page types
        (e.g., chrome:// URLs, extension pages, or restricted sites).
        """
        try:
            await self._cdp(tab_id, f"{domain}.enable")
        except RuntimeError as e:
            # Log but don't fail - domain may not be available on all pages
            if "wasn't found" in str(e) or "not found" in str(e).lower():
                logger.debug("CDP domain %s.enable not available for tab %s", domain, tab_id)
            else:
                raise

    # ── Context (Tab Group) Management ─────────────────────────────────────────

    async def create_context(self, agent_id: str) -> dict:
        """Create a labelled tab group for this agent.

        Returns {"groupId": int, "tabId": int}.
        """
        result = await self._send("context.create", agentId=agent_id)
        log_context_event(
            "create", agent_id, group_id=result.get("groupId"), tab_id=result.get("tabId")
        )
        return result

    async def destroy_context(self, group_id: int) -> dict:
        """Close all tabs in the group and remove it."""
        result = await self._send("context.destroy", groupId=group_id)
        log_context_event("destroy", _get_active_profile(), group_id=group_id, details=result)
        return result

    # ── Tab Management ─────────────────────────────────────────────────────────

    async def create_tab(self, url: str = "about:blank", group_id: int | None = None) -> dict:
        """Create a new tab and optionally add it to a group.

        Returns {"tabId": int}.
        """
        params = {"url": url}
        if group_id is not None:
            params["groupId"] = group_id
        return await self._send("tab.create", **params)

    async def close_tab(self, tab_id: int) -> dict:
        """Close a tab by ID."""
        return await self._send("tab.close", tabId=tab_id)

    async def list_tabs(self, group_id: int | None = None) -> dict:
        """List tabs, optionally filtered by group.

        Returns {"tabs": [{"id": int, "url": str, "title": str, "groupId": int}, ...]}.
        """
        params = {"groupId": group_id} if group_id is not None else {}
        return await self._send("tab.list", **params)

    async def activate_tab(self, tab_id: int) -> dict:
        """Activate (focus) a tab."""
        return await self._send("tab.activate", tabId=tab_id)

    # ── CDP Attachment ─────────────────────────────────────────────────────────

    async def cdp_attach(self, tab_id: int) -> dict:
        """Attach CDP debugger to a tab.

        Returns {"ok": bool}.
        """
        if tab_id in self._cdp_attached:
            return {"ok": True, "attached": False, "message": "Already attached"}
        result = await self._send("cdp.attach", tabId=tab_id)
        if result.get("ok"):
            self._cdp_attached.add(tab_id)
        return result

    async def cdp_detach(self, tab_id: int) -> dict:
        """Detach CDP debugger from a tab."""
        result = await self._send("cdp.detach", tabId=tab_id)
        self._cdp_attached.discard(tab_id)
        return result

    # ── Navigation ─────────────────────────────────────────────────────────────

    async def navigate(
        self,
        tab_id: int,
        url: str,
        wait_until: str = "load",
        timeout_ms: int = 30000,
    ) -> dict:
        """Navigate a tab to a URL.

        Uses CDP Page.navigate with lifecycle wait.
        """
        if wait_until not in VALID_WAIT_UNTIL:
            wait_until = "load"

        # Attach debugger if needed
        await self.cdp_attach(tab_id)

        # Enable Page domain
        await self._cdp(tab_id, "Page.enable")

        # Navigate
        result = await self._cdp(tab_id, "Page.navigate", {"url": url})
        loader_id = result.get("loaderId")

        # Wait for lifecycle event
        if wait_until != "commit" and loader_id:
            # Poll for the event with timeout
            deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
            while asyncio.get_event_loop().time() < deadline:
                # Check if we've reached the desired state
                eval_result = await self._cdp(
                    tab_id,
                    "Runtime.evaluate",
                    {"expression": "document.readyState", "returnByValue": True},
                )
                ready_state = (
                    (eval_result or {}).get("result", {}).get("result", {}).get("value", "")
                )

                if wait_until == "domcontentloaded" and ready_state in ("interactive", "complete"):
                    break
                elif wait_until == "load" and ready_state == "complete":
                    break
                elif wait_until == "networkidle":
                    # For networkidle, wait a bit and check again
                    await asyncio.sleep(0.1)
                    # Simple heuristic: wait until no outstanding network requests
                    # This is approximate - true network idle needs Network domain monitoring
                    if ready_state == "complete":
                        await asyncio.sleep(0.5)
                        break
                else:
                    await asyncio.sleep(0.05)

        # Get current URL and title
        url_result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        title_result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "document.title", "returnByValue": True},
        )

        return {
            "ok": True,
            "tabId": tab_id,
            "url": (url_result or {}).get("result", {}).get("result", {}).get("value", ""),
            "title": (title_result or {}).get("result", {}).get("result", {}).get("value", ""),
        }

    async def go_back(self, tab_id: int) -> dict:
        """Navigate back in history."""
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "Page.enable")
        await self._cdp(tab_id, "Page.goBack")

        # Get current URL
        result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        return {
            "ok": True,
            "action": "back",
            "url": (result or {}).get("result", {}).get("result", {}).get("value", ""),
        }

    async def go_forward(self, tab_id: int) -> dict:
        """Navigate forward in history."""
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "Page.enable")
        await self._cdp(tab_id, "Page.goForward")

        result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        return {
            "ok": True,
            "action": "forward",
            "url": (result or {}).get("result", {}).get("result", {}).get("value", ""),
        }

    async def reload(self, tab_id: int) -> dict:
        """Reload the page."""
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "Page.enable")
        await self._cdp(tab_id, "Page.reload")

        result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        return {
            "ok": True,
            "action": "reload",
            "url": (result or {}).get("result", {}).get("result", {}).get("value", ""),
        }

    # ── Interaction ────────────────────────────────────────────────────────────

    async def click(
        self,
        tab_id: int,
        selector: str,
        button: str = "left",
        click_count: int = 1,
        timeout_ms: int = 30000,
    ) -> dict:
        """Click an element by selector.

        Uses multiple fallback methods for robustness:
        1. CDP mouse events with JavaScript bounds
        2. JavaScript click() as fallback

        Inspired by browser-use's robust click implementation.
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")

        # Get document and find element
        doc = await self._cdp(tab_id, "DOM.getDocument")
        root_id = doc.get("root", {}).get("nodeId")

        # Wait for element to appear
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        node_id = None
        while asyncio.get_event_loop().time() < deadline:
            result = await self._cdp(
                tab_id, "DOM.querySelector", {"nodeId": root_id, "selector": selector}
            )
            node_id = result.get("nodeId")
            if node_id:
                break
            await asyncio.sleep(0.1)

        if not node_id:
            # Check if the element might be inside a Shadow DOM container
            shadow_hint = ""
            try:
                shadow_check = await self.evaluate(tab_id, """
                    (function() {
                        var hosts = document.querySelectorAll('[id]');
                        for (var h of hosts) {
                            if (h.shadowRoot) return h.id;
                        }
                        return null;
                    })()
                """)
                shadow_host = (shadow_check or {}).get("result")
                if shadow_host:
                    shadow_hint = (
                        f" The page has Shadow DOM (host: #{shadow_host}). "
                        f"Use browser_shadow_query('#{shadow_host} >>> {selector}') "
                        f"to pierce shadow roots, or browser_evaluate with manual JS traversal."
                    )
            except Exception:
                pass
            return {"ok": False, "error": f"Element not found: {selector}{shadow_hint}"}

        # Scroll into view FIRST to ensure element is rendered
        try:
            await self._cdp(
                tab_id,
                "DOM.scrollIntoViewIfNeeded",
                {"nodeId": node_id},
            )
            await asyncio.sleep(0.05)  # Wait for scroll to complete
        except Exception:
            pass  # Best effort - continue even if scroll fails

        # Get viewport dimensions for bounds checking
        viewport_script = """
            (function() {
                return {
                    width: window.innerWidth,
                    height: window.innerHeight
                };
            })();
        """
        viewport_result = await self.evaluate(tab_id, viewport_script)
        viewport = (viewport_result or {}).get("result") or {}
        viewport_width = viewport.get("width", 1920)
        viewport_height = viewport.get("height", 1080)

        # Method 1: Use JavaScript to get element bounds and click
        # This is more reliable than CDP for complex layouts
        click_script = f"""
            (function() {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return {{ error: 'Element not found' }};

                // Check if element is visible
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) {{
                    return {{ error: 'Element has zero dimensions' }};
                }}

                // Check if element is within viewport
                if (rect.bottom < 0 || rect.top > {viewport_height} ||
                    rect.right < 0 || rect.left > {viewport_width}) {{
                    return {{ error: 'Element not in viewport' }};
                }}

                // Get center for metadata
                const x = rect.x + rect.width / 2;
                const y = rect.y + rect.height / 2;

                // Perform the click
                el.click();

                return {{ x: x, y: y, width: rect.width, height: rect.height }};
            }})();
        """

        try:
            result = await self.evaluate(tab_id, click_script)
            value = (result or {}).get("result")

            if isinstance(value, dict) and "error" not in value:
                # JavaScript click succeeded — highlight element
                rx = value.get("x", 0) - value.get("width", 0) / 2
                ry = value.get("y", 0) - value.get("height", 0) / 2
                await self.highlight_rect(
                    tab_id, rx, ry, value.get("width", 0), value.get("height", 0), label=selector
                )
                return {
                    "ok": True,
                    "action": "click",
                    "selector": selector,
                    "x": value.get("x", 0),
                    "y": value.get("y", 0),
                    "method": "javascript",
                }

            # If JavaScript click failed, try CDP approach
            if isinstance(value, dict) and value.get("error"):
                logger.debug("JS click failed: %s, trying CDP", value["error"])
        except Exception as e:
            logger.debug("JS click exception: %s, trying CDP", e)

        # Method 2: CDP mouse events (fallback)
        # Get element bounds via JavaScript (more reliable than CDP getBoxModel)
        bounds_script = f"""
            (function() {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {{
                    x: rect.x + rect.width / 2,
                    y: rect.y + rect.height / 2,
                    width: rect.width,
                    height: rect.height
                }};
            }})();
        """
        bounds_result = await self.evaluate(tab_id, bounds_script)
        bounds_value = (bounds_result or {}).get("result")

        if not bounds_value:
            return {"ok": False, "error": f"Could not get element bounds: {selector}"}

        x = bounds_value.get("x", 0)
        y = bounds_value.get("y", 0)

        # Clamp coordinates to viewport bounds
        x = max(0, min(viewport_width - 1, x))
        y = max(0, min(viewport_height - 1, y))

        # Dispatch mouse events with proper timing
        button_map = {"left": "left", "right": "right", "middle": "middle"}
        cdp_button = button_map.get(button, "left")

        try:
            # Move mouse to element first
            await self._cdp(
                tab_id,
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": x, "y": y},
            )
            await asyncio.sleep(0.05)

            # Mouse down
            try:
                await asyncio.wait_for(
                    self._cdp(
                        tab_id,
                        "Input.dispatchMouseEvent",
                        {
                            "type": "mousePressed",
                            "x": x,
                            "y": y,
                            "button": cdp_button,
                            "clickCount": click_count,
                        },
                    ),
                    timeout=1.0,
                )
            except TimeoutError:
                pass  # Continue even if timeout

            await asyncio.sleep(0.08)

            # Mouse up
            try:
                await asyncio.wait_for(
                    self._cdp(
                        tab_id,
                        "Input.dispatchMouseEvent",
                        {
                            "type": "mouseReleased",
                            "x": x,
                            "y": y,
                            "button": cdp_button,
                            "clickCount": click_count,
                        },
                    ),
                    timeout=3.0,
                )
            except TimeoutError:
                pass  # Continue even if timeout

            w = bounds_value.get("width", 0)
            h = bounds_value.get("height", 0)
            await self.highlight_rect(tab_id, x - w / 2, y - h / 2, w, h, label=selector)
            return {
                "ok": True,
                "action": "click",
                "selector": selector,
                "x": x,
                "y": y,
                "method": "cdp",
            }

        except Exception as e:
            return {"ok": False, "error": f"Click failed: {e}"}

    async def click_coordinate(self, tab_id: int, x: float, y: float, button: str = "left") -> dict:
        """Click at specific coordinates."""
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")

        button_map = {"left": "left", "right": "right", "middle": "middle"}
        cdp_button = button_map.get(button, "left")

        await self._cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": cdp_button, "clickCount": 1},
        )
        await self._cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": cdp_button, "clickCount": 1},
        )

        await self.highlight_point(tab_id, x, y, label=f"click ({x},{y})")
        return {"ok": True, "action": "click_coordinate", "x": x, "y": y}

    async def type_text(
        self,
        tab_id: int,
        selector: str,
        text: str,
        clear_first: bool = True,
        delay_ms: int = 0,
        timeout_ms: int = 30000,
    ) -> dict:
        """Type text into an element.

        Uses JavaScript focus for reliability, then CDP key events.
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")
        await self._try_enable_domain(tab_id, "Runtime")

        # First, scroll into view and focus via JavaScript (more reliable than CDP)
        focus_script = f"""
            (function() {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return false;

                // Scroll into view
                el.scrollIntoView({{ block: 'center' }});

                // Focus the element
                el.focus();

                // Clear if requested
                if ({str(clear_first).lower()}) {{
                    if (el.value !== undefined) {{
                        el.value = '';
                    }} else if (el.isContentEditable) {{
                        el.textContent = '';
                    }}
                }}

                return true;
            }})();
        """

        focus_result = await self.evaluate(tab_id, focus_script)
        success = (focus_result or {}).get("result", False)

        if not success:
            # Element not found - wait and retry
            deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
            while asyncio.get_event_loop().time() < deadline:
                result = await self.evaluate(tab_id, focus_script)
                if result and (result or {}).get("result", False):
                    success = True
                    break
                await asyncio.sleep(0.1)

            if not success:
                return {"ok": False, "error": f"Element not found: {selector}"}

        await asyncio.sleep(0.05)  # Wait for focus to take effect

        # Type each character using CDP key events
        for char in text:
            # Dispatch key down
            await self._cdp(
                tab_id,
                "Input.dispatchKeyEvent",
                {"type": "keyDown", "text": char},
            )
            # Dispatch key up
            await self._cdp(
                tab_id,
                "Input.dispatchKeyEvent",
                {"type": "keyUp", "text": char},
            )
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)

        # Highlight the element that was typed into
        rect_result = await self.evaluate(
            tab_id,
            f"(function(){{const el=document.querySelector("
            f"{json.dumps(selector)});if(!el)return null;"
            f"const r=el.getBoundingClientRect();"
            f"return{{x:r.left,y:r.top,w:r.width,h:r.height}};}})()",
        )
        rect = (rect_result or {}).get("result")
        if rect:
            await self.highlight_rect(
                tab_id, rect["x"], rect["y"], rect["w"], rect["h"], label=selector
            )
        return {"ok": True, "action": "type", "selector": selector, "length": len(text)}

    async def press_key(self, tab_id: int, key: str, selector: str | None = None) -> dict:
        """Press a keyboard key.

        Args:
            key: Key name like 'Enter', 'Tab', 'Escape', 'ArrowDown', etc.
            selector: Optional selector to focus first
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "Input")

        if selector:
            doc = await self._cdp(tab_id, "DOM.getDocument")
            root_id = doc.get("root", {}).get("nodeId")
            result = await self._cdp(
                tab_id, "DOM.querySelector", {"nodeId": root_id, "selector": selector}
            )
            node_id = result.get("nodeId")
            if node_id:
                await self._cdp(tab_id, "DOM.focus", {"nodeId": node_id})

        # Key definitions for special keys
        key_map = {
            "Enter": ("\r", "Enter"),
            "Tab": ("\t", "Tab"),
            "Escape": ("\x1b", "Escape"),
            "Backspace": ("\b", "Backspace"),
            "Delete": ("\x7f", "Delete"),
            "ArrowUp": ("", "ArrowUp"),
            "ArrowDown": ("", "ArrowDown"),
            "ArrowLeft": ("", "ArrowLeft"),
            "ArrowRight": ("", "ArrowRight"),
            "Home": ("", "Home"),
            "End": ("", "End"),
            "PageUp": ("", "PageUp"),
            "PageDown": ("", "PageDown"),
        }

        text, key_name = key_map.get(key, (key, key))

        await self._cdp(
            tab_id,
            "Input.dispatchKeyEvent",
            {"type": "keyDown", "key": key_name, "text": text if text else None},
        )
        await self._cdp(
            tab_id,
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": key_name, "text": text if text else None},
        )

        return {"ok": True, "action": "press", "key": key}

    # Shared JS snippet: shadow-piercing querySelector via ">>>" separator
    _SHADOW_QUERY_JS = """
        function _shadowQuery(sel) {
            const parts = sel.split('>>>').map(s => s.trim());
            let node = document;
            for (const part of parts) {
                if (!node) return null;
                node = (node.shadowRoot || node).querySelector(part);
            }
            return node;
        }
    """

    async def shadow_query(self, tab_id: int, selector: str) -> dict:
        """querySelector that pierces shadow roots using '>>>' separator.

        Returns CSS-pixel getBoundingClientRect of the matched element.
        Example: '#interop-outlet >>> #ember37 >>> p'
        """
        await self.cdp_attach(tab_id)
        script = (
            f"{self._SHADOW_QUERY_JS}"
            f"(function(){{"
            f"const el=_shadowQuery({json.dumps(selector)});"
            f"if(!el)return null;"
            f"const r=el.getBoundingClientRect();"
            f"return{{found:true,tag:el.tagName,x:r.left,y:r.top,w:r.width,h:r.height,"
            f"cx:r.left+r.width/2,cy:r.top+r.height/2}};"
            f"}})()"
        )
        result = await self.evaluate(tab_id, script)
        rect = (result or {}).get("result")
        if not rect:
            return {"ok": False, "error": f"Element not found: {selector}"}
        return {"ok": True, "selector": selector, "rect": rect}

    async def hover(self, tab_id: int, selector: str, timeout_ms: int = 30000) -> dict:
        """Hover over an element. Supports '>>>' shadow-piercing selectors.

        Uses JavaScript for bounds (more reliable than CDP getBoxModel).
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")
        await self._try_enable_domain(tab_id, "Runtime")

        # Use JavaScript to scroll into view and get bounds
        # Supports ">>>" shadow-piercing selectors
        if ">>>" in selector:
            query_fn = f"{self._SHADOW_QUERY_JS} _shadowQuery({json.dumps(selector)})"
        else:
            query_fn = f"document.querySelector({json.dumps(selector)})"

        hover_script = f"""
            (function() {{
                const el = {query_fn};
                if (!el) return null;
                el.scrollIntoView({{ block: 'center' }});
                const rect = el.getBoundingClientRect();
                return {{
                    x: rect.x + rect.width / 2,
                    y: rect.y + rect.height / 2,
                    width: rect.width,
                    height: rect.height
                }};
            }})();
        """

        # Wait for element and get bounds
        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        bounds_value = None

        while asyncio.get_event_loop().time() < deadline:
            result = await self.evaluate(tab_id, hover_script)
            bounds_value = (result or {}).get("result")
            if bounds_value:
                break
            await asyncio.sleep(0.1)

        if not bounds_value:
            return {"ok": False, "error": f"Element not found: {selector}"}

        x = bounds_value.get("x", 0)
        y = bounds_value.get("y", 0)

        if x == 0 and y == 0:
            return {"ok": False, "error": f"Element has zero dimensions: {selector}"}

        await asyncio.sleep(0.05)  # Wait for scroll

        # Dispatch mouse moved event
        await self._cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x, "y": y},
        )

        w = bounds_value.get("width", 0)
        h = bounds_value.get("height", 0)
        await self.highlight_rect(tab_id, x - w / 2, y - h / 2, w, h, label=selector)
        return {"ok": True, "action": "hover", "selector": selector, "x": x, "y": y}

    async def hover_coordinate(self, tab_id: int, x: float, y: float) -> dict:
        """Hover at CSS pixel coordinates.

        Works for overlay/virtual-rendered content where CSS selectors fail.
        Dispatches a mouseMoved event at (x, y) without needing a DOM element.
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")
        await self._cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x, "y": y, "buttons": 0},
        )
        await self.highlight_point(tab_id, x, y, label=f"hover ({x},{y})")
        return {"ok": True, "action": "hover_coordinate", "x": x, "y": y}

    async def press_key_at(self, tab_id: int, x: float, y: float, key: str) -> dict:
        """Move mouse to (x, y) then dispatch a key event.

        Useful for overlays where browser_press misses because document.activeElement
        is in the regular DOM while the focused element is in virtual/overlay rendering.
        Moving the mouse first routes the key event through the browser's native
        hit-testing rather than the DOM focus chain.
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")

        # Move mouse into position so the browser's native focus follows
        await self._cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x, "y": y, "buttons": 0},
        )

        key_map = {
            "Enter": ("\r", "Enter"),
            "Tab": ("\t", "Tab"),
            "Escape": ("\x1b", "Escape"),
            "Backspace": ("\b", "Backspace"),
            "Delete": ("\x7f", "Delete"),
            "ArrowUp": ("", "ArrowUp"),
            "ArrowDown": ("", "ArrowDown"),
            "ArrowLeft": ("", "ArrowLeft"),
            "ArrowRight": ("", "ArrowRight"),
            "Home": ("", "Home"),
            "End": ("", "End"),
            "Space": (" ", " "),
            " ": (" ", " "),
        }
        text, key_name = key_map.get(key, (key, key))

        await self._cdp(
            tab_id,
            "Input.dispatchKeyEvent",
            {"type": "keyDown", "key": key_name, "text": text or None},
        )
        await self._cdp(
            tab_id,
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": key_name, "text": text or None},
        )

        await self.highlight_point(tab_id, x, y, label=f"{key} ({x},{y})")
        return {"ok": True, "action": "press_at", "x": x, "y": y, "key": key}

    # Duration (ms) that injected highlights stay visible before fading out.
    _HIGHLIGHT_DURATION_MS = 1500

    async def highlight_rect(
        self,
        tab_id: int,
        x: float,
        y: float,
        w: float,
        h: float,
        label: str = "",
        color: dict | None = None,
    ) -> None:
        """Inject a visible highlight overlay into the page DOM.

        Creates a fixed-position div with border, background tint, and an
        optional label tag.  The element fades out after ``_HIGHLIGHT_DURATION_MS``
        and removes itself.  Much more visible than the CDP Overlay API.
        """
        fill = color or {"r": 59, "g": 130, "b": 246, "a": 0.18}
        border_rgb = f"rgb({fill['r']},{fill['g']},{fill['b']})"
        bg_rgba = f"rgba({fill['r']},{fill['g']},{fill['b']},{fill.get('a', 0.18)})"
        duration = self._HIGHLIGHT_DURATION_MS

        # Escape label for safe injection
        safe_label = json.dumps(label[:60]) if label else '""'

        js = f"""
        (function() {{
          // Remove any previous hive highlight
          var old = document.getElementById('__hive_hl');
          if (old) old.remove();

          var box = document.createElement('div');
          box.id = '__hive_hl';
          box.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;'
            + 'left:{int(x)}px;top:{int(y)}px;width:{max(1,int(w))}px;height:{max(1,int(h))}px;'
            + 'border:2px solid {border_rgb};background:{bg_rgba};'
            + 'border-radius:3px;transition:opacity 0.4s ease;opacity:1;'
            + 'box-shadow:0 0 8px {bg_rgba};';

          var lbl = {safe_label};
          if (lbl) {{
            var tag = document.createElement('span');
            tag.textContent = lbl;
            tag.style.cssText = 'position:absolute;left:0;top:-20px;'
              + 'background:{border_rgb};color:#fff;font:bold 11px/16px system-ui;'
              + 'padding:1px 6px;border-radius:3px;white-space:nowrap;max-width:200px;'
              + 'overflow:hidden;text-overflow:ellipsis;';
            box.appendChild(tag);
          }}

          document.documentElement.appendChild(box);
          setTimeout(function() {{ box.style.opacity = '0'; }}, {duration});
          setTimeout(function() {{ box.remove(); }}, {duration + 500});
        }})();
        """
        try:
            await self.cdp_attach(tab_id)
            await self.evaluate(tab_id, js)
        except Exception:
            pass  # best-effort visual feedback

        _interaction_highlights[tab_id] = {
            "x": x, "y": y, "w": w, "h": h,
            "label": label, "kind": "rect",
        }

    async def highlight_point(self, tab_id: int, x: float, y: float, label: str = "") -> None:
        """Highlight a coordinate with a pulsing dot and crosshair."""
        duration = self._HIGHLIGHT_DURATION_MS
        safe_label = json.dumps(label[:60]) if label else '""'

        js = f"""
        (function() {{
          var old = document.getElementById('__hive_hl');
          if (old) old.remove();

          var dot = document.createElement('div');
          dot.id = '__hive_hl';
          dot.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;'
            + 'left:{int(x)-8}px;top:{int(y)-8}px;width:16px;height:16px;'
            + 'border-radius:50%;background:rgba(239,68,68,0.7);'
            + 'box-shadow:0 0 0 4px rgba(239,68,68,0.25),0 0 12px rgba(239,68,68,0.4);'
            + 'transition:opacity 0.4s ease;opacity:1;';

          var lbl = {safe_label};
          if (lbl) {{
            var tag = document.createElement('span');
            tag.textContent = lbl;
            tag.style.cssText = 'position:absolute;left:20px;top:-4px;'
              + 'background:rgba(239,68,68,0.9);color:#fff;font:bold 11px/16px system-ui;'
              + 'padding:1px 6px;border-radius:3px;white-space:nowrap;';
            dot.appendChild(tag);
          }}

          document.documentElement.appendChild(dot);
          setTimeout(function() {{ dot.style.opacity = '0'; }}, {duration});
          setTimeout(function() {{ dot.remove(); }}, {duration + 500});
        }})();
        """
        try:
            await self.cdp_attach(tab_id)
            await self.evaluate(tab_id, js)
        except Exception:
            pass

        _interaction_highlights[tab_id] = {
            "x": x, "y": y, "w": 0, "h": 0,
            "label": label, "kind": "point",
        }

    async def clear_highlight(self, tab_id: int) -> None:
        """Remove the injected highlight from the page."""
        try:
            await self.evaluate(tab_id, """
                var el = document.getElementById('__hive_hl');
                if (el) el.remove();
            """)
        except Exception:
            pass
        _interaction_highlights.pop(tab_id, None)

    async def scroll(self, tab_id: int, direction: str = "down", amount: int = 500) -> dict:
        """Scroll the page.

        Uses JavaScript to find and scroll the appropriate container.
        Handles SPAs like LinkedIn where content is in a nested scrollable div.
        """
        delta_x = 0
        delta_y = 0
        if direction == "down":
            delta_y = amount
        elif direction == "up":
            delta_y = -amount
        elif direction == "right":
            delta_x = amount
        elif direction == "left":
            delta_x = -amount

        # JavaScript scroll that finds the largest scrollable container
        # NOTE: Do NOT wrap in IIFE - evaluate() already wraps scripts
        scroll_script = f"""
            // Find the largest scrollable container
            const candidates = [];
            const allElements = document.querySelectorAll('*');

            for (const el of allElements) {{
                const style = getComputedStyle(el);
                const overflow = style.overflow + style.overflowY;

                if (overflow.includes('scroll') || overflow.includes('auto')) {{
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 100 && rect.height > 100 &&
                        el.scrollHeight > el.clientHeight + 100) {{
                        candidates.push({{el: el, area: rect.width * rect.height}});
                    }}
                }}
            }}

            candidates.sort((a, b) => b.area - a.area);
            const container = candidates.length > 0 ? candidates[0].el : null;

            if (container) {{
                container.scrollBy({{ top: {delta_y}, left: {delta_x}, behavior: 'smooth' }});
                return {{
                    success: true,
                    method: 'container',
                    tag: container.tagName,
                    scrolled: true
                }};
            }}

            // Fallback to window scroll
            window.scrollBy({{ top: {delta_y}, left: {delta_x}, behavior: 'smooth' }});
            return {{
                success: true,
                method: 'window',
                tag: 'WINDOW',
                scrolled: true
            }};
        """

        try:
            result = await asyncio.wait_for(self.evaluate(tab_id, scroll_script), timeout=5.0)
            value = (result or {}).get("result") or {}

            if value.get("success"):
                return {
                    "ok": True,
                    "action": "scroll",
                    "direction": direction,
                    "amount": amount,
                    "method": value.get("method", "js"),
                    "container": value.get("tag", "unknown"),
                }
            else:
                return {"ok": False, "error": "scroll script returned failure"}

        except TimeoutError:
            return {"ok": False, "error": "scroll timed out"}
        except Exception as e:
            logger.warning("Scroll failed: %s", e)
            return {"ok": False, "error": str(e)}

    async def select_option(self, tab_id: int, selector: str, values: list[str]) -> dict:
        """Select options in a select element."""
        await self.cdp_attach(tab_id)

        values_json = json.dumps(values)
        await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {
                "expression": f"""
                    const sel = document.querySelector({json.dumps(selector)});
                    if (!sel) throw new Error('Element not found');
                    Array.from(sel.options).forEach(opt => {{
                        opt.selected = {values_json}.includes(opt.value);
                    }});
                    sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                    Array.from(sel.selectedOptions).map(o => o.value);
                """,
                "returnByValue": True,
            },
        )

        # Highlight the select element
        rect_result = await self.evaluate(
            tab_id,
            f"(function(){{const el=document.querySelector("
            f"{json.dumps(selector)});if(!el)return null;"
            f"const r=el.getBoundingClientRect();"
            f"return{{x:r.left,y:r.top,w:r.width,h:r.height}};}})()",
        )
        rect = (rect_result or {}).get("result")
        if rect:
            await self.highlight_rect(
                tab_id, rect["x"], rect["y"], rect["w"], rect["h"], label=selector
            )

        return {"ok": True, "action": "select", "selector": selector, "selected": values}

    # ── Inspection ─────────────────────────────────────────────────────────────

    async def evaluate(self, tab_id: int, script: str) -> dict:
        """Execute JavaScript in the page."""
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "Runtime")

        stripped = script.strip()

        # Already a complete IIFE — run as-is, no re-wrapping
        is_iife = stripped.startswith("(function") and (
            stripped.endswith("})()") or stripped.endswith("})();")
        )
        # Arrow-function IIFE: (() => { ... })()
        is_arrow_iife = stripped.startswith("(()") and (
            stripped.endswith("})()")
            or stripped.endswith("})();")
            or stripped.endswith(")()")
            or stripped.endswith(")()")
        )

        if is_iife or is_arrow_iife:
            # Already self-contained — just run it
            wrapped_script = stripped
        elif stripped.startswith("return "):
            # Single return statement — wrap in IIFE
            wrapped_script = f"(function() {{ {stripped} }})()"
        elif "\n" in stripped or ";" in stripped:
            # Multi-statement block — wrap without prepending return
            # (caller should use explicit return if they want a value)
            wrapped_script = f"(function() {{ {stripped} }})()"
        else:
            # Single expression — wrap with return to capture value
            wrapped_script = f"(function() {{ return {stripped} }})()"

        result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": wrapped_script, "returnByValue": True, "awaitPromise": True},
        )

        if result is None:
            return {"ok": False, "error": "CDP returned no result"}

        if "exceptionDetails" in result:
            ex = result["exceptionDetails"]
            # Extract the actual exception message from the nested structure
            ex_value = (ex.get("exception") or {}).get("description") or ex.get(
                "text", "Script error"
            )
            return {"ok": False, "error": ex_value}

        # The CDP response structure is {result: {type: ..., value: ...}}
        # But our bridge returns just the inner result object
        inner_result = result.get("result", {})
        value = inner_result.get("value") if isinstance(inner_result, dict) else None

        return {
            "ok": True,
            "action": "evaluate",
            "result": value,
        }

    async def snapshot(self, tab_id: int, timeout_s: float = 30.0) -> dict:
        """Get an accessibility snapshot of the page.

        Uses a hybrid approach:
        1. CDP Accessibility.getFullAXTree for semantic structure
        2. DOM queries for visibility and computed styles
        3. Falls back to DOM tree if accessibility returns mostly ignored

        Args:
            tab_id: The tab ID to snapshot
            timeout_s: Maximum time to spend building snapshot (default 10s)
        """
        try:
            async with asyncio.timeout(timeout_s):
                await self.cdp_attach(tab_id)
                await self._try_enable_domain(tab_id, "Accessibility")
                await self._try_enable_domain(tab_id, "DOM")
                await self._try_enable_domain(tab_id, "Runtime")

                # Try accessibility tree first
                result = await self._cdp(tab_id, "Accessibility.getFullAXTree")
                nodes = result.get("nodes", [])

            # Count non-ignored nodes
            visible_count = sum(1 for n in nodes if not n.get("ignored", False))

            # If tree is too large or mostly ignored, use DOM-based snapshot
            if len(nodes) > 5000:
                logger.debug(
                    "Accessibility tree too large (%d nodes), using DOM snapshot",
                    len(nodes),
                )
                return await self._dom_snapshot(tab_id)

            if visible_count < 10 and len(nodes) > 50:
                logger.debug(
                    "Accessibility tree has only %d/%d visible nodes, falling back to DOM snapshot",
                    visible_count,
                    len(nodes),
                )
                return await self._dom_snapshot(tab_id)

            # Format the accessibility tree (with node limit)
            snapshot = self._format_ax_tree(nodes, max_nodes=2000)

            # Get URL
            url_result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": "window.location.href", "returnByValue": True},
            )
            url = (url_result or {}).get("result", {}).get("value", "")

            return {
                "ok": True,
                "tabId": tab_id,
                "url": url,
                "tree": snapshot,
            }
        except TimeoutError:
            logger.warning("Snapshot timed out after %ss", timeout_s)
            return {"ok": False, "error": f"snapshot timed out after {timeout_s}s"}
        except asyncio.CancelledError:
            logger.warning("Snapshot cancelled (timeout or task cancellation)")
            return {"ok": False, "error": f"snapshot timed out or cancelled (limit: {timeout_s}s)"}
        except Exception as e:
            logger.error("Snapshot failed: %s", e)
            return {"ok": False, "error": str(e)}

    async def _dom_snapshot(self, tab_id: int) -> dict:
        """Fallback: build snapshot from DOM tree with visibility info."""
        # Get all interactive elements using DOM queries
        script = """
            (function() {
                const interactiveSelectors = [
                    'a', 'button', 'input', 'textarea', 'select', 'option',
                    '[onclick]', '[role="button"]', '[role="link"]',
                    '[contenteditable="true"]', 'summary', 'details',
                    'a[href]', 'button[type]', 'input[type]',
                    'label', 'form', 'nav', 'nav a', 'nav button',
                    '[aria-label]', '[aria-labelledby]', '[tabindex]',
                    'h1', 'h2', 'h3', 'h4', 'h5', 'h6'
                ].join(', ');

                const elements = document.querySelectorAll(interactiveSelectors);
                const results = [];

                for (const el of elements) {
                    const rect = el.getBoundingClientRect();
                    const styles = window.getComputedStyle(el);

                    // Skip invisible elements
                    if (rect.width === 0 || rect.height === 1 ||
                        styles.display === 'none' ||
                        styles.visibility === 'hidden' ||
                        styles.opacity === '0') {
                        continue;
                    }

                    // Skip elements outside viewport
                    if (rect.bottom < 0 || rect.top > window.innerHeight ||
                        rect.right < 0 || rect.left > window.innerWidth) {
                        continue;
                    }

                    const tag = el.tagName.toLowerCase();
                    const text = (el.innerText || el.value || el.placeholder
                        || el.getAttribute('aria-label') || '').substring(0, 80);
                    const type = el.type || tag;
                    const role = el.getAttribute('role') || tag;
                    const name = el.name || el.id || '';
                    const href = el.href || '';
                    const className = el.className || '';

                    results.push({
                        tag,
                        type,
                        role,
                        text: text.trim(),
                        name,
                        href,
                        className: className.split(' ').slice(0, 3).join(' '),
                        rect: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height)
                        }
                    });
                }

                return results;
            })();
        """

        result = await self.evaluate(tab_id, script)
        elements = result.get("result", [])

        if not elements:
            return {
                "ok": True,
                "tabId": tab_id,
                "tree": "(no visible interactive elements found)",
            }

        # Format as tree
        lines = []
        for i in range(0, min(100, len(elements))):
            el = elements[i]
            ref = f"e{i}"
            tag = el.get("tag", "unknown")
            text = el.get("text", "")
            role = el.get("role", tag)

            desc = f"{role}"
            if text:
                desc += f' "{text[:40]}"'
            if el.get("href"):
                desc += " [href]"
            desc += f" [ref={ref}]"
            lines.append(f"  - {desc}")

        # Get URL
        url_result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        url = (url_result or {}).get("result", {}).get("value", "")

        return {
            "ok": True,
            "tabId": tab_id,
            "url": url,
            "tree": "\n".join(lines),
        }

    def _format_ax_tree(self, nodes: list[dict], max_nodes: int = 2000) -> str:
        """Format a CDP Accessibility.getFullAXTree result.

        Args:
            nodes: List of accessibility tree nodes
            max_nodes: Maximum number of nodes to process (prevents hangs on huge trees)
        """
        if not nodes:
            return "(empty tree)"

        by_id = {n["nodeId"]: n for n in nodes}
        children_map: dict[str, list[str]] = {}
        for n in nodes:
            for child_id in n.get("childIds", []):
                children_map.setdefault(n["nodeId"], []).append(child_id)

        lines: list[str] = []
        ref_counter = [0]  # Use list to allow mutation in nested function
        node_counter = [0]  # Track total nodes processed
        ref_map: dict[str, str] = {}

        def _walk(node_id: str, depth: int) -> None:
            # Stop if we've processed enough nodes
            if node_counter[0] >= max_nodes:
                return

            node = by_id.get(node_id)
            if not node:
                return

            if node.get("ignored", False):
                for cid in children_map.get(node_id, []):
                    _walk(cid, depth)
                return

            role_info = node.get("role", {})
            if isinstance(role_info, dict):
                role = role_info.get("value", "unknown")
            else:
                role = str(role_info)

            if role in ("none", "Ignored"):
                for cid in children_map.get(node_id, []):
                    _walk(cid, depth)
                return

            node_counter[0] += 1

            name_info = node.get("name", {})
            name = name_info.get("value", "") if isinstance(name_info, dict) else str(name_info)

            # Build property annotations
            props: list[str] = []
            for prop in node.get("properties", []):
                pname = prop.get("name", "")
                pval = prop.get("value", {})
                val = pval.get("value") if isinstance(pval, dict) else pval
                if pname in ("focused", "disabled", "checked", "expanded", "selected", "required"):
                    if val is True:
                        props.append(pname)
                elif pname == "level" and val:
                    props.append(f"level={val}")

            indent = "  " * depth
            label = f"- {role}"

            # Add ref for interactive elements
            interactive_roles = {
                "button",
                "link",
                "textbox",
                "checkbox",
                "radio",
                "combobox",
                "menuitem",
                "tab",
                "searchbox",
            }
            if role in interactive_roles or name:
                ref_counter[0] += 1
                ref_id = f"e{ref_counter[0]}"
                ref_map[ref_id] = f"[{role}]{name}"
                label += f" [ref={ref_id}]"

            if name:
                label += f' "{name}"'
            if props:
                label += f" [{', '.join(props)}]"

            lines.append(f"{indent}{label}")

            for cid in children_map.get(node_id, []):
                _walk(cid, depth + 1)

        _walk(nodes[0]["nodeId"], 0)

        # Add truncation notice if we hit the limit
        if node_counter[0] >= max_nodes:
            lines.append("... (tree truncated, too many nodes)")

        return "\n".join(lines) if lines else "(empty tree)"

    async def get_text(self, tab_id: int, selector: str, timeout_ms: int = 30000) -> dict:
        """Get text content of an element."""
        await self.cdp_attach(tab_id)

        script = f"""
            (function() {{
                const el = document.querySelector({json.dumps(selector)});
                return el ? el.textContent : null;
            }})()
        """

        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": script, "returnByValue": True},
            )
            text = (result or {}).get("result", {}).get("result", {}).get("value")
            if text is not None:
                return {"ok": True, "selector": selector, "text": text}
            await asyncio.sleep(0.1)

        return {"ok": False, "error": f"Element not found: {selector}"}

    async def get_attribute(
        self, tab_id: int, selector: str, attribute: str, timeout_ms: int = 30000
    ) -> dict:
        """Get an attribute value of an element."""
        await self.cdp_attach(tab_id)

        script = f"""
            (function() {{
                const el = document.querySelector({json.dumps(selector)});
                return el ? el.getAttribute({json.dumps(attribute)}) : null;
            }})()
        """

        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": script, "returnByValue": True},
            )
            value = (result or {}).get("result", {}).get("result", {}).get("value")
            if value is not None:
                return {"ok": True, "selector": selector, "attribute": attribute, "value": value}
            await asyncio.sleep(0.1)

        return {"ok": False, "error": f"Element not found: {selector}"}

    async def screenshot(
        self,
        tab_id: int,
        full_page: bool = False,
        selector: str | None = None,
        timeout_s: float = 30.0,
    ) -> dict:
        """Take a screenshot of the page or element.

        Returns {"ok": True, "data": base64_string, "mimeType": "image/png"}.
        """
        try:
            async with asyncio.timeout(timeout_s):
                await self.cdp_attach(tab_id)
                await self._cdp(tab_id, "Page.enable")

                params: dict[str, Any] = {"format": "png"}
                if selector:
                    # Clip to the element's bounding rect (viewport-relative)
                    rect_result = await self._cdp(
                        tab_id,
                        "Runtime.evaluate",
                        {
                            "expression": (
                                f"(function(){{"
                                f"const el=document.querySelector({json.dumps(selector)});"
                                f"if(!el)return null;"
                                f"const r=el.getBoundingClientRect();"
                                f"return{{x:r.left,y:r.top,width:r.width,height:r.height}};"
                                f"}})()"
                            ),
                            "returnByValue": True,
                        },
                    )
                    rect = (rect_result or {}).get("result", {}).get("result", {}).get("value")
                    if rect and rect.get("width") and rect.get("height"):
                        params["clip"] = {
                            "x": rect["x"],
                            "y": rect["y"],
                            "width": rect["width"],
                            "height": rect["height"],
                            "scale": 1,
                        }
                    else:
                        return {"ok": False, "error": f"Selector not found: {selector}"}
                elif full_page:
                    # Get layout metrics for full page
                    metrics = await self._cdp(tab_id, "Page.getLayoutMetrics")
                    content_size = metrics.get("contentSize", {})
                    params["clip"] = {
                        "x": 0,
                        "y": 0,
                        "width": content_size.get("width", 1280),
                        "height": content_size.get("height", 720),
                        "scale": 1,
                    }

                result = await self._cdp(tab_id, "Page.captureScreenshot", params)
                data = result.get("data")

                if not data:
                    return {"ok": False, "error": "Screenshot failed"}

                # Get URL and viewport metadata in one evaluate call
                meta_result = await self._cdp(
                    tab_id,
                    "Runtime.evaluate",
                    {
                        "expression": (
                            "(function(){"
                            "return{"
                            "url:window.location.href,"
                            "dpr:window.devicePixelRatio,"
                            "cssWidth:window.innerWidth,"
                            "cssHeight:window.innerHeight"
                            "};"
                            "})()"
                        ),
                        "returnByValue": True,
                    },
                )
                meta = (meta_result or {}).get("result", {}).get("result", {}).get("value") or {}

                return {
                    "ok": True,
                    "tabId": tab_id,
                    "url": meta.get("url", ""),
                    "devicePixelRatio": meta.get("dpr", 1.0),
                    "cssWidth": meta.get("cssWidth", 0),
                    "cssHeight": meta.get("cssHeight", 0),
                    "data": data,
                    "mimeType": "image/png",
                }
        except TimeoutError:
            logger.warning("Screenshot timed out after %ss", timeout_s)
            return {"ok": False, "error": f"screenshot timed out after {timeout_s}s"}
        except asyncio.CancelledError:
            logger.warning("Screenshot cancelled (timeout or task cancellation)")
            return {
                "ok": False,
                "error": f"screenshot timed out or cancelled (limit: {timeout_s}s)",
            }
        except Exception as e:
            logger.error("Screenshot failed: %s", e)
            return {"ok": False, "error": str(e)}

    async def wait_for_selector(self, tab_id: int, selector: str, timeout_ms: int = 30000) -> dict:
        """Wait for an element to appear."""
        await self.cdp_attach(tab_id)

        script = f"""
            (function() {{
                return document.querySelector({json.dumps(selector)}) !== null;
            }})()
        """

        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": script, "returnByValue": True},
            )
            found = (result or {}).get("result", {}).get("result", {}).get("value", False)
            if found:
                return {"ok": True, "selector": selector}
            await asyncio.sleep(0.1)

        return {"ok": False, "error": f"Element not found within timeout: {selector}"}

    async def wait_for_text(self, tab_id: int, text: str, timeout_ms: int = 30000) -> dict:
        """Wait for text to appear on the page."""
        await self.cdp_attach(tab_id)

        script = f"""
            (function() {{
                return document.body.innerText.includes({json.dumps(text)});
            }})()
        """

        deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": script, "returnByValue": True},
            )
            found = (result or {}).get("result", {}).get("result", {}).get("value", False)
            if found:
                return {"ok": True, "text": text}
            await asyncio.sleep(0.1)

        return {"ok": False, "error": f"Text not found within timeout: {text}"}

    async def resize(self, tab_id: int, width: int, height: int) -> dict:
        """Resize the browser viewport."""
        await self.cdp_attach(tab_id)

        # Use Runtime.evaluate to set up resize, then Emulation.setDeviceMetricsOverride
        await self._cdp(
            tab_id,
            "Emulation.setDeviceMetricsOverride",
            {
                "width": width,
                "height": height,
                "deviceScaleFactor": 0,
                "mobile": False,
            },
        )

        return {"ok": True, "action": "resize", "width": width, "height": height}


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
