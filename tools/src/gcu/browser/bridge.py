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
import base64
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

# Fast-fail polling default for element / text waits. 5 seconds is long
# enough to cover normal SPA render latency on loaded pages, short enough
# that a bad selector or hallucinated element fails fast instead of
# burning 30 wall-clock seconds per miss (the old behavior — see the
# 2026-04-14 gemini-3-flash x.com session where 7 of 14 browser_click
# calls each hit the 30s deadline for ~210s wasted total).
#
# navigate() keeps a longer default (30s) because real page loads can
# legitimately take that long.
DEFAULT_WAIT_TIMEOUT_MS: int = 5000

# Longer default for bridge _send calls that wrap genuinely slow ops
# (full-page screenshot, accessibility tree, navigate). Individual
# callers can pass their own value via _send(..., timeout=...).
_LONG_SEND_TIMEOUT_S: float = 60.0


async def _adaptive_poll_sleep(elapsed_s: float) -> None:
    """Sleep between DOM polls with an adaptive backoff.

    Early polls are snappy (50ms) so a quickly-appearing element is
    reported in ~100ms. Later polls back off (200ms, 500ms) so a
    missing element doesn't thrash CDP with 300+ querySelector calls
    before the deadline fires.
    """
    if elapsed_s < 1.0:
        await asyncio.sleep(0.05)
    elif elapsed_s < 5.0:
        await asyncio.sleep(0.2)
    else:
        await asyncio.sleep(0.5)


# Last interaction highlight per tab_id: {x, y, w, h, label, kind}
# kind: "rect" (element) or "point" (coordinate)
_interaction_highlights: dict[int, dict] = {}


# Compact descriptor of the focused element. Returned by both click()
# and click_coordinate() so the agent can verify it focused what it
# intended. When the outer document's activeElement is an <iframe>,
# we recurse into the iframe's document (same-origin only) so the
# response describes the real inner element — otherwise the agent
# always sees {tag: "iframe"} and can't tell whether it hit the
# composer or something else inside the frame (e.g. a sidebar item
# in LinkedIn's #interop-outlet messaging overlay).
_FOCUSED_ELEMENT_JS = """
(function() {
    function describe(el) {
        var rect = el.getBoundingClientRect();
        var attrs = {};
        for (var i = 0; i < el.attributes.length && i < 10; i++) {
            attrs[el.attributes[i].name] = el.attributes[i].value.substring(0, 200);
        }
        return {
            tag: el.tagName.toLowerCase(),
            id: el.id || null,
            className: el.className || null,
            name: el.getAttribute('name') || null,
            type: el.getAttribute('type') || null,
            role: el.getAttribute('role') || null,
            contenteditable: el.getAttribute('contenteditable') || null,
            text: (el.innerText || '').substring(0, 200),
            value: (el.value !== undefined ? String(el.value).substring(0, 200) : null),
            attributes: attrs,
            rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
        };
    }
    var el = document.activeElement;
    if (!el || el === document.body) return null;
    // Descend into same-origin iframes. Capped at 5 levels of
    // nesting to bound cost. Cross-origin frames throw on
    // contentDocument access → we catch and report the outermost
    // iframe instead.
    var framePath = [];
    var depth = 0;
    while (el && (el.tagName === 'IFRAME' || el.tagName === 'FRAME') && depth < 5) {
        framePath.push(el.id || el.getAttribute('data-testid') || el.tagName.toLowerCase());
        var innerDoc = null;
        try { innerDoc = el.contentDocument; } catch (e) { innerDoc = null; }
        if (!innerDoc) break;
        var innerActive = innerDoc.activeElement;
        if (!innerActive || innerActive === innerDoc.body) break;
        el = innerActive;
        depth++;
    }
    var out = describe(el);
    if (framePath.length) out.inFrame = framePath;
    return out;
})()
"""


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
                "websockets not installed — Chrome extension bridge disabled. Install with: uv pip install websockets"
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
                max_size=50 * 1024 * 1024,  # 50 MB — CDP responses (AX tree, screenshots) can be large
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
        # Cancel in-flight bridge requests so any caller stuck in _send
        # sees CancelledError immediately instead of waiting the full
        # 30s timeout. Mirrors the cleanup in _handle_connection's
        # disconnect branch so both exit paths behave the same.
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        # Drop CDP attach cache — next run must re-attach fresh.
        self._cdp_attached.clear()
        # Drop highlight state — stale entries would otherwise carry
        # over into a subsequent run and confuse screenshot annotation.
        _interaction_highlights.clear()
        self._ws = None

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

    async def _http_status_handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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
                response = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
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
                            log_bridge_message("recv", "response", msg_id=msg_id, error=msg["error"])
                            fut.set_exception(RuntimeError(msg["error"]))
                        else:
                            log_bridge_message("recv", "response", msg_id=msg_id, result=msg.get("result"))
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

    # Default wait on a bridge command. Callers with known-slow ops
    # (full-page screenshots on slow networks, AX tree on huge pages)
    # can pass a longer value via _send(..., timeout=...). Using the
    # same default as the old hard-coded value so existing call sites
    # don't regress.
    _DEFAULT_SEND_TIMEOUT_S: float = 30.0

    async def _send(self, type_: str, *, timeout: float | None = None, **params) -> dict:
        """Send a command to the extension and wait for the result."""
        if not self._ws:
            raise RuntimeError("Extension not connected")
        self._counter += 1
        msg_id = str(self._counter)
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        start = time.perf_counter()
        effective_timeout = timeout if timeout is not None else self._DEFAULT_SEND_TIMEOUT_S

        log_bridge_message("send", type_, msg_id=msg_id, params=params)

        try:
            await self._ws.send(json.dumps({"id": msg_id, "type": type_, **params}))
            result = await asyncio.wait_for(fut, timeout=effective_timeout)
            duration_ms = (time.perf_counter() - start) * 1000
            log_bridge_message("send", type_, msg_id=msg_id, result=result, duration_ms=duration_ms)
            return result
        except TimeoutError:
            self._pending.pop(msg_id, None)
            log_bridge_message("send", type_, msg_id=msg_id, error="timeout")
            # Include which CDP method (if any) so the caller can see
            # what actually hung — the generic 'cdp' type is useless
            # when ten different CDP calls use the same type.
            detail = f" method={params.get('method')}" if params.get("method") else ""
            raise RuntimeError(f"Bridge command '{type_}'{detail} timed out after {effective_timeout:.0f}s") from None
        except BaseException:
            # CancelledError or any other exception — remove stale future so a late
            # response from the extension doesn't try to resolve a cancelled future.
            self._pending.pop(msg_id, None)
            raise

    # Substrings that indicate Chrome detached the debugger out from
    # under us (tab closed, user opened DevTools, cross-origin nav).
    # Our in-memory _cdp_attached set is now stale; next call should
    # re-attach rather than reporting a cryptic "Target not found".
    _CDP_DEAD_SESSION_MARKERS = (
        "target closed",
        "target not found",
        "not attached",
        "session closed",
        "inspector already attached",
        "no target with given id",
    )

    def _is_cdp_dead_session(self, exc: BaseException) -> bool:
        msg = str(exc).lower()
        return any(m in msg for m in self._CDP_DEAD_SESSION_MARKERS)

    async def _cdp(
        self,
        tab_id: int,
        method: str,
        params: dict | None = None,
        *,
        timeout: float | None = None,
    ) -> dict:
        """Send a CDP command to a tab.

        ``timeout`` (seconds) overrides the default bridge send timeout.
        Pass a larger value for genuinely slow operations (full-page
        screenshots over slow networks, accessibility tree on huge
        pages) so they don't spuriously fail at the 30s floor. Pass a
        smaller value for fast probes ("is this element present right
        now") to fail fast.

        On a dead-session error (Chrome detached externally — tab closed,
        DevTools opened, cross-origin nav), evict the stale attach
        cache entry, reattach, and retry once. Without this the Python
        side would keep assuming it's attached and every subsequent call
        would hit the same error until someone restarted the bridge.
        """
        start = time.perf_counter()
        try:
            result = await self._send(
                "cdp",
                tabId=tab_id,
                method=method,
                params=params or {},
                timeout=timeout,
            )
            duration_ms = (time.perf_counter() - start) * 1000
            log_cdp_command(tab_id, method, params, result, duration_ms=duration_ms)
            return result
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            log_cdp_command(tab_id, method, params, error=str(e), duration_ms=duration_ms)
            if self._is_cdp_dead_session(e):
                logger.info(
                    "CDP session for tab %d looks dead (%s) — re-attaching and retrying",
                    tab_id,
                    str(e)[:120],
                )
                self._cdp_attached.discard(tab_id)
                try:
                    reattach = await self._send("cdp.attach", tabId=tab_id)
                    if reattach.get("ok"):
                        self._cdp_attached.add(tab_id)
                        retry_start = time.perf_counter()
                        result = await self._send(
                            "cdp",
                            tabId=tab_id,
                            method=method,
                            params=params or {},
                            timeout=timeout,
                        )
                        log_cdp_command(
                            tab_id,
                            method,
                            params,
                            result,
                            duration_ms=(time.perf_counter() - retry_start) * 1000,
                        )
                        return result
                except Exception as retry_exc:
                    logger.debug("CDP reattach+retry for tab %d failed: %s", tab_id, retry_exc)
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
        log_context_event("create", agent_id, group_id=result.get("groupId"), tab_id=result.get("tabId"))
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
        result = await self._send("tab.close", tabId=tab_id)
        # Drop per-tab state — the id may be reused by Chrome much
        # later, and carrying a stale highlight or "attached" flag
        # forward would misannotate screenshots or skip a needed
        # reattach on the reused id.
        self._cdp_attached.discard(tab_id)
        _interaction_highlights.pop(tab_id, None)
        return result

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

        # Drop the stale interaction highlight before loading a new
        # page — otherwise the next screenshot will annotate the new
        # page with a rect from the previous page's coordinate system.
        _interaction_highlights.pop(tab_id, None)

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
                # _cdp returns the CDP response body; Runtime.evaluate shape
                # is {"result": {"type": ..., "value": ...}} — one "result"
                # hop, not two. The extra hop was always returning "" and
                # this entire lifecycle loop was running until the deadline.
                ready_state = (eval_result or {}).get("result", {}).get("value", "")

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
            "url": (url_result or {}).get("result", {}).get("value", ""),
            "title": (title_result or {}).get("result", {}).get("value", ""),
        }

    async def go_back(self, tab_id: int) -> dict:
        """Navigate back in history.

        Uses ``history.back()`` via Runtime.evaluate — modern Chrome CDP
        no longer exposes ``Page.goBack`` / ``Page.goForward`` (removed
        in favour of ``Page.navigateToHistoryEntry``, which requires
        first fetching the history list). ``history.back()`` is simpler,
        works across every Chrome version, and matches what the user
        expects when they call ``browser_go_back``.
        """
        _interaction_highlights.pop(tab_id, None)
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "Page.enable")
        await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "history.back()", "returnByValue": True},
        )
        # Give the browser a beat to commit the navigation before we
        # read the new URL.
        await asyncio.sleep(0.3)
        result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        return {
            "ok": True,
            "action": "back",
            "url": (result or {}).get("result", {}).get("value", ""),
        }

    async def go_forward(self, tab_id: int) -> dict:
        """Navigate forward in history. See go_back() for why we use JS."""
        _interaction_highlights.pop(tab_id, None)
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "Page.enable")
        await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "history.forward()", "returnByValue": True},
        )
        await asyncio.sleep(0.3)
        result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        return {
            "ok": True,
            "action": "forward",
            "url": (result or {}).get("result", {}).get("value", ""),
        }

    async def reload(self, tab_id: int) -> dict:
        """Reload the page."""
        _interaction_highlights.pop(tab_id, None)
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
            "url": (result or {}).get("result", {}).get("value", ""),
        }

    # ── Interaction ────────────────────────────────────────────────────────────

    async def click(
        self,
        tab_id: int,
        selector: str,
        button: str = "left",
        click_count: int = 1,
        timeout_ms: int = DEFAULT_WAIT_TIMEOUT_MS,
    ) -> dict:
        """Click an element by selector.

        ``timeout_ms`` controls how long we poll for the element to
        appear in the DOM. Defaults to :data:`DEFAULT_WAIT_TIMEOUT_MS`
        (5 s) so a missing or hallucinated selector fails fast. Pass a
        larger value when the target genuinely needs longer to render
        (e.g. post-navigation SPA hydration).

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

        # Wait for element to appear. Adaptive polling:
        # - first 1 s at 50 ms intervals (responsive on fast pages)
        # - next 4 s at 200 ms
        # - rest at 500 ms
        poll_start = asyncio.get_event_loop().time()
        deadline = poll_start + timeout_ms / 1000
        node_id = None
        while asyncio.get_event_loop().time() < deadline:
            result = await self._cdp(tab_id, "DOM.querySelector", {"nodeId": root_id, "selector": selector})
            node_id = result.get("nodeId")
            if node_id:
                break
            await _adaptive_poll_sleep(asyncio.get_event_loop().time() - poll_start)

        if not node_id:
            # Check if the element might be inside a Shadow DOM container
            shadow_hint = ""
            try:
                shadow_check = await self.evaluate(
                    tab_id,
                    """
                    (function() {
                        var hosts = document.querySelectorAll('[id]');
                        for (var h of hosts) {
                            if (h.shadowRoot) return h.id;
                        }
                        return null;
                    })()
                """,
                )
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
                await self.highlight_rect(tab_id, rx, ry, value.get("width", 0), value.get("height", 0), label=selector)
                focused_info = await self._read_focused_element(tab_id)
                resp = {
                    "ok": True,
                    "action": "click",
                    "selector": selector,
                    "x": value.get("x", 0),
                    "y": value.get("y", 0),
                    "method": "javascript",
                }
                if focused_info:
                    resp["focused_element"] = focused_info
                return resp

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

            # Mouse down — if this hangs past the short wait budget we
            # CANNOT claim success. The prior code swallowed TimeoutError
            # with `pass` and returned ok=true further down, which is why
            # the 2026-04-14 gemini session saw 7 clicks land at exactly
            # 30s with status=ok even though the click had not landed.
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
                    timeout=2.0,
                )
            except TimeoutError:
                return {
                    "ok": False,
                    "error": (
                        f"CDP mousePressed timed out for '{selector}' — "
                        "the click did not land. Consider browser_click_coordinate "
                        "with an explicit rect from browser_get_rect."
                    ),
                }

            await asyncio.sleep(0.08)

            # Mouse up — same non-silent failure handling. A stuck
            # mouseReleased means the press is still "held down" in
            # Chrome's input state; we must surface the failure so the
            # caller can retry or switch strategy.
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
                return {
                    "ok": False,
                    "error": (
                        f"CDP mouseReleased timed out for '{selector}' — "
                        "the press event fired but release did not. The page "
                        "may be in a stuck input state; try browser_click_coordinate."
                    ),
                }

            w = bounds_value.get("width", 0)
            h = bounds_value.get("height", 0)
            await self.highlight_rect(tab_id, x - w / 2, y - h / 2, w, h, label=selector)
            focused_info = await self._read_focused_element(tab_id)
            resp = {
                "ok": True,
                "action": "click",
                "selector": selector,
                "x": x,
                "y": y,
                "method": "cdp",
            }
            if focused_info:
                resp["focused_element"] = focused_info
            return resp

        except Exception as e:
            return {"ok": False, "error": f"Click failed: {e}"}

    async def _read_focused_element(self, tab_id: int) -> dict | None:
        """Read document.activeElement and return a compact descriptor.

        The JS returns ``rect`` fields in CSS px (they come straight
        from ``getBoundingClientRect``). We convert them to fractions
        of the viewport here so the agent sees a rect in the same
        coord space it passed to click / hover / press_at.

        Returns None on any failure — never raises.
        """
        try:
            await self._try_enable_domain(tab_id, "Runtime")
            result = await self.evaluate(tab_id, _FOCUSED_ELEMENT_JS)
            info = (result or {}).get("result")
            if info and isinstance(info, dict) and isinstance(info.get("rect"), dict):
                from .tools.inspection import _viewport_sizes

                vp = _viewport_sizes.get(tab_id)
                if vp and vp[0] > 0 and vp[1] > 0:
                    cw, ch = float(vp[0]), float(vp[1])
                    r = info["rect"]
                    info["rect"] = {
                        "x": round(r.get("x", 0) / cw, 4),
                        "y": round(r.get("y", 0) / ch, 4),
                        "width": round(r.get("width", 0) / cw, 4),
                        "height": round(r.get("height", 0) / ch, 4),
                    }
                else:
                    # Degraded: cache missing (no screenshot taken
                    # yet). Leave rect in CSS px and flag it so the
                    # agent can tell.
                    info["rectSpace"] = "css"
            return info
        except Exception:
            return None

    async def click_coordinate(self, tab_id: int, x: float, y: float, button: str = "left") -> dict:
        """Click at specific coordinates."""
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")

        button_map = {"left": "left", "right": "right", "middle": "middle"}
        cdp_button = button_map.get(button, "left")

        logger.info(
            "click_coordinate tab=%d: x=%.1f, y=%.1f → CDP Input.dispatchMouseEvent",
            tab_id,
            x,
            y,
        )

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

        focused_info = await self._read_focused_element(tab_id)
        resp = {"ok": True, "action": "click_coordinate", "x": x, "y": y}
        if focused_info:
            resp["focused_element"] = focused_info
        return resp

    async def type_text(
        self,
        tab_id: int,
        selector: str | None,
        text: str,
        clear_first: bool = True,
        delay_ms: int = 1,
        timeout_ms: int = 30000,
        use_insert_text: bool = True,
    ) -> dict:
        """Type text into an element.

        Routes through a real CDP pointer click on the target rect BEFORE
        inserting text. This is critical for rich-text editors (Draft.js,
        Lexical, ProseMirror, React-controlled contenteditable): those
        frameworks only register input as "real" after seeing a native
        focus event sourced from a real pointer interaction — a
        JS-sourced ``el.focus()`` is ignored, and the submit button
        stays disabled because the framework's internal state never
        updates. Sending a CDP click first fires the real
        pointerdown/pointerup/click/focus sequence that every modern
        framework listens to.

        After clicking, we insert text via ``Input.insertText`` by
        default (``use_insert_text=True``). insertText is a dedicated
        CDP method that asks the browser to commit text into the
        focused element as if IME just committed it — it works
        cleanly on rich editors where per-character keyDown events
        would otherwise be eaten or mis-timed (empirically verified
        against LinkedIn's Lexical message composer 2026-04-11).
        Playwright uses the same approach under the hood.

        Set ``use_insert_text=False`` to get the old per-character
        keyDown/keyUp path when an editor needs precise keystroke
        timing (autocomplete triggers, code editors that fire on
        specific chars, ``delay_ms`` typing animations).
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "DOM")
        await self._try_enable_domain(tab_id, "Input")
        await self._try_enable_domain(tab_id, "Runtime")

        if selector is not None:
            # Find + scroll + (optionally) clear via JS. We still need the
            # rect, and clearing via `.value = ''` / `.textContent = ''`
            # is the most reliable way to reset pre-existing content.
            focus_script = f"""
                (function() {{
                    const el = document.querySelector({json.dumps(selector)});
                    if (!el) return null;

                    // Scroll into view so the click lands in-viewport.
                    el.scrollIntoView({{ block: 'center' }});

                    // Clear if requested.
                    if ({str(clear_first).lower()}) {{
                        if (el.value !== undefined) {{
                            el.value = '';
                            // Nudge React's onChange — the framework reads
                            // .value via a setter hook, and without firing
                            // an input event the component state remains
                            // stale after our value assignment.
                            el.dispatchEvent(new Event('input', {{bubbles: true}}));
                        }} else if (el.isContentEditable) {{
                            el.textContent = '';
                            el.dispatchEvent(new Event('input', {{bubbles: true}}));
                        }}
                    }}

                    const r = el.getBoundingClientRect();
                    return {{
                        x: r.left + r.width / 2,
                        y: r.top + r.height / 2,
                        w: r.width,
                        h: r.height,
                    }};
                }})();
            """

            focus_result = await self.evaluate(tab_id, focus_script)
            rect = (focus_result or {}).get("result")

            if not rect:
                # Element not found — wait + retry until timeout.
                deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
                while asyncio.get_event_loop().time() < deadline:
                    result = await self.evaluate(tab_id, focus_script)
                    rect = (result or {}).get("result") if result else None
                    if rect:
                        break
                    await asyncio.sleep(0.1)

                if not rect:
                    return {"ok": False, "error": f"Element not found: {selector}"}

            if not rect.get("w") or not rect.get("h"):
                return {
                    "ok": False,
                    "error": f"Element has zero dimensions, can't click to focus: {selector}",
                }

            # Fire a real CDP pointer click at the element's center. This is
            # what unblocks rich-text editors — JS el.focus() is not enough.
            click_x = rect["x"]
            click_y = rect["y"]
            await self._cdp(
                tab_id,
                "Input.dispatchMouseEvent",
                {"type": "mousePressed", "x": click_x, "y": click_y, "button": "left", "clickCount": 1},
            )
            await self._cdp(
                tab_id,
                "Input.dispatchMouseEvent",
                {"type": "mouseReleased", "x": click_x, "y": click_y, "button": "left", "clickCount": 1},
            )
            await asyncio.sleep(0.15)  # Let focus / editor-init animations settle.
        else:
            # No selector — assume the caller already focused the target
            # element (e.g. via browser_click_coordinate). Just clear the
            # active element if requested, then insert text directly.
            if clear_first:
                await self.evaluate(tab_id, """
                    (function() {
                        const el = document.activeElement;
                        if (!el) return;
                        if (el.value !== undefined) {
                            el.value = '';
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                        } else if (el.isContentEditable) {
                            el.textContent = '';
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                        }
                    })();
                """)

        if use_insert_text and delay_ms <= 0:
            # CDP Input.insertText is the most reliable way to insert
            # text into a rich-text editor. It bypasses the keyboard
            # event pipeline entirely and commits text into the focused
            # element as if IME just committed it. Works on plain
            # <input>/<textarea>, contenteditable, Lexical, Draft.js,
            # ProseMirror, Monaco textarea buffers — verified empirically
            # against LinkedIn's message composer (Lexical) on 2026-04-11
            # where the per-char keyDown path left the editor empty.
            await self._cdp(tab_id, "Input.insertText", {"text": text})
        else:
            # Fallback path: per-character keyDown/keyUp with full key,
            # code, and text fields. Used when the caller explicitly
            # wants per-keystroke dispatch (autocomplete testing, code
            # editors that fire on specific chars, animated typing
            # with ``delay_ms``). Populating ``code`` for ASCII is
            # needed so frameworks that branch on ``event.code`` see
            # the right values.
            for char in text:
                key_params: dict[str, Any] = {
                    "type": "keyDown",
                    "text": char,
                    "key": char,
                }
                if len(char) == 1 and char.isalpha():
                    key_params["code"] = f"Key{char.upper()}"
                elif len(char) == 1 and char.isdigit():
                    key_params["code"] = f"Digit{char}"
                await self._cdp(tab_id, "Input.dispatchKeyEvent", key_params)

                key_up = {"type": "keyUp", "key": char}
                if "code" in key_params:
                    key_up["code"] = key_params["code"]
                await self._cdp(tab_id, "Input.dispatchKeyEvent", key_up)
                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000)

        # Highlight the element that was typed into
        if selector is not None:
            rect_result = await self.evaluate(
                tab_id,
                f"(function(){{const el=document.querySelector("
                f"{json.dumps(selector)});if(!el)return null;"
                f"const r=el.getBoundingClientRect();"
                f"return{{x:r.left,y:r.top,w:r.width,h:r.height}};}})()",
            )
            rect = (rect_result or {}).get("result")
            if rect:
                await self.highlight_rect(tab_id, rect["x"], rect["y"], rect["w"], rect["h"], label=selector)
        else:
            # Highlight the active element when no selector was provided.
            # Drill into same-origin iframes to find the real focused
            # element — the top-level activeElement may be a full-screen
            # iframe whose rect covers the entire viewport.
            rect_result = await self.evaluate(
                tab_id,
                "(function(){"
                "var el=document.activeElement;"
                "try{while(el&&el.tagName==='IFRAME'&&el.contentDocument){"
                "el=el.contentDocument.activeElement;"
                "}}catch(e){}"
                "if(!el||el===document.body||el===document.documentElement)return null;"
                "const r=el.getBoundingClientRect();"
                "return{x:r.left,y:r.top,w:r.width,h:r.height};})()",
            )
            rect = (rect_result or {}).get("result")
            if rect:
                await self.highlight_rect(tab_id, rect["x"], rect["y"], rect["w"], rect["h"], label="active element", border_style="dashed")
        return {"ok": True, "action": "type", "selector": selector, "length": len(text)}

    # CDP Input.dispatchKeyEvent modifiers bitmask.
    _CDP_MODIFIERS = {"alt": 1, "ctrl": 2, "control": 2, "meta": 4, "cmd": 4, "shift": 8}

    # How Chrome expects each modifier key as its OWN keyDown event —
    # name, code, and Windows virtual key code. Dispatched before the
    # main key so Chrome sees the modifier as "held" during the main
    # event, which is what actually triggers browser shortcuts like
    # Ctrl+A, Cmd+L, Shift+Tab.
    _MODIFIER_KEYS = {
        "alt": {"key": "Alt", "code": "AltLeft", "windowsVirtualKeyCode": 18},
        "ctrl": {"key": "Control", "code": "ControlLeft", "windowsVirtualKeyCode": 17},
        "control": {"key": "Control", "code": "ControlLeft", "windowsVirtualKeyCode": 17},
        "meta": {"key": "Meta", "code": "MetaLeft", "windowsVirtualKeyCode": 91},
        "cmd": {"key": "Meta", "code": "MetaLeft", "windowsVirtualKeyCode": 91},
        "shift": {"key": "Shift", "code": "ShiftLeft", "windowsVirtualKeyCode": 16},
    }

    def _cdp_modifier_mask(self, modifiers: list[str] | None) -> int:
        if not modifiers:
            return 0
        mask = 0
        for m in modifiers:
            mask |= self._CDP_MODIFIERS.get(m.lower(), 0)
        return mask

    async def press_key(
        self,
        tab_id: int,
        key: str,
        selector: str | None = None,
        modifiers: list[str] | None = None,
    ) -> dict:
        """Press a keyboard key, optionally with modifier keys held.

        Args:
            key: Key name like 'Enter', 'Tab', 'Escape', 'ArrowDown', etc.
            selector: Optional selector to focus first
            modifiers: Optional list of modifier keys to hold while pressing
                ``key``. Accepted values: "alt", "ctrl"/"control", "meta"/"cmd",
                "shift". Example: ``modifiers=["ctrl"]`` → Ctrl+key, which
                enables shortcuts like Ctrl+A, Ctrl+L, Cmd+Enter, Shift+Tab.
        """
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "Input")

        if selector:
            doc = await self._cdp(tab_id, "DOM.getDocument")
            root_id = doc.get("root", {}).get("nodeId")
            result = await self._cdp(tab_id, "DOM.querySelector", {"nodeId": root_id, "selector": selector})
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
        mod_mask = self._cdp_modifier_mask(modifiers)

        # With modifiers held, suppress the printable text so that
        # e.g. Ctrl+A doesn't also type the character "a" into the
        # focused field (CDP will still fire the shortcut).
        effective_text = text if (text and mod_mask == 0) else None

        # Compute ``code`` and ``windowsVirtualKeyCode`` for the main
        # key. These are MANDATORY for Chrome's shortcut dispatcher —
        # without them, Ctrl+A etc. reach the DOM with ``code=""`` and
        # ``which=0`` and Chrome doesn't recognise them as shortcuts.
        # Verified empirically on chrome 131 against a real input.
        main_code: str | None = None
        main_vk: int | None = None
        special_vk = {
            "Enter": (13, "Enter"),
            "Tab": (9, "Tab"),
            "Escape": (27, "Escape"),
            "Backspace": (8, "Backspace"),
            "Delete": (46, "Delete"),
            "ArrowUp": (38, "ArrowUp"),
            "ArrowDown": (40, "ArrowDown"),
            "ArrowLeft": (37, "ArrowLeft"),
            "ArrowRight": (39, "ArrowRight"),
            "Home": (36, "Home"),
            "End": (35, "End"),
            "PageUp": (33, "PageUp"),
            "PageDown": (34, "PageDown"),
        }
        if key_name in special_vk:
            main_vk, main_code = special_vk[key_name]
        elif len(key_name) == 1 and key_name.isalpha():
            main_code = f"Key{key_name.upper()}"
            main_vk = ord(key_name.upper())  # 'A' = 65 ... 'Z' = 90
        elif len(key_name) == 1 and key_name.isdigit():
            main_code = f"Digit{key_name}"
            main_vk = ord(key_name)  # '0' = 48 ... '9' = 57

        # Press each modifier as a separate keyDown BEFORE the main
        # key. Sending ``modifiers: mask`` on the main key alone isn't
        # enough — Chrome's shortcut dispatcher looks for a held
        # modifier event, not just a flag. Matches the Playwright /
        # Puppeteer sequence. Release modifiers in reverse order after
        # the main key so the "held" state is correct throughout.
        pressed_mods: list[dict] = []
        if modifiers:
            for m in modifiers:
                spec = self._MODIFIER_KEYS.get(m.lower())
                if spec is None:
                    continue
                await self._cdp(
                    tab_id,
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyDown",
                        "key": spec["key"],
                        "code": spec["code"],
                        "windowsVirtualKeyCode": spec["windowsVirtualKeyCode"],
                        "modifiers": mod_mask,
                    },
                )
                pressed_mods.append(spec)

        main_down: dict[str, Any] = {
            # Use rawKeyDown when a modifier is held so Chrome skips
            # text insertion and routes the event to the shortcut
            # dispatcher. For plain press_key without modifiers we can
            # use regular keyDown.
            "type": "rawKeyDown" if mod_mask else "keyDown",
            "key": key_name,
            "text": effective_text,
            "modifiers": mod_mask,
        }
        main_up: dict[str, Any] = {
            "type": "keyUp",
            "key": key_name,
            "text": effective_text,
            "modifiers": mod_mask,
        }
        if main_code is not None:
            main_down["code"] = main_code
            main_up["code"] = main_code
        if main_vk is not None:
            main_down["windowsVirtualKeyCode"] = main_vk
            main_up["windowsVirtualKeyCode"] = main_vk

        await self._cdp(tab_id, "Input.dispatchKeyEvent", main_down)
        await self._cdp(tab_id, "Input.dispatchKeyEvent", main_up)

        # Release modifiers in reverse order.
        for spec in reversed(pressed_mods):
            await self._cdp(
                tab_id,
                "Input.dispatchKeyEvent",
                {
                    "type": "keyUp",
                    "key": spec["key"],
                    "code": spec["code"],
                    "windowsVirtualKeyCode": spec["windowsVirtualKeyCode"],
                    "modifiers": 0,
                },
            )

        return {"ok": True, "action": "press", "key": key, "modifiers": modifiers or []}

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
        # IMPORTANT: the whole script must be a single IIFE so that
        # bridge.evaluate() detects it as "already wrapped" and returns
        # its value. If you let evaluate() re-wrap a script that
        # starts with a function declaration, the outer wrapper
        # discards the inner IIFE's return and you always get None —
        # which is exactly the bug this code had until 2026-04-11.
        script = (
            f"(function(){{"
            f"{self._SHADOW_QUERY_JS}"
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

    # Duration (ms) that injected highlights stay visible before fading.
    # Bumped from 1500 → 10000 so the overlay outlives typical agent turn
    # latency (LLM streaming + tool batching often runs 3-8s). With the
    # old 1.5s lifetime the overlay was already gone by the time the
    # next ``browser_screenshot`` fired, which is why it looked "flaky".
    _HIGHLIGHT_DURATION_MS = 10000

    async def highlight_rect(
        self,
        tab_id: int,
        x: float,
        y: float,
        w: float,
        h: float,
        label: str = "",
        color: dict | None = None,
        border_style: str = "solid",
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
          // Remove any previous hive highlight (including its observer).
          var prev = document.getElementById('__hive_hl');
          if (prev) {{
            try {{ prev.__hiveStop && prev.__hiveStop(); }} catch(e) {{}}
            prev.remove();
          }}

          var box = document.createElement('div');
          box.id = '__hive_hl';
          box.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;'
            + 'left:{int(x)}px;top:{int(y)}px;width:{max(1, int(w))}px;height:{max(1, int(h))}px;'
            + 'border:2px {border_style} {border_rgb};background:{bg_rgba};'
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

          var parent = document.documentElement;
          parent.appendChild(box);

          // SPA re-mount protection: some frameworks (React/Vue/etc.) and
          // some host pages run MutationObservers that strip unknown
          // children from documentElement. Watch for our box being
          // removed and re-attach it — but cap the retries so we don't
          // get into a DOM-thrash loop with a hostile host observer.
          var stopped = false;
          var retries = 0;
          var MAX_RETRIES = 5;
          var obs = new MutationObserver(function() {{
            if (stopped) return;
            if (!document.getElementById('__hive_hl')) {{
              if (retries >= MAX_RETRIES) {{
                stopped = true;
                try {{ obs.disconnect(); }} catch(e) {{}}
                return;
              }}
              retries++;
              try {{ parent.appendChild(box); }} catch(e) {{}}
            }}
          }});
          try {{ obs.observe(parent, {{childList:true, subtree:false}}); }} catch(e) {{}}
          box.__hiveStop = function() {{
            stopped = true;
            try {{ obs.disconnect(); }} catch(e) {{}}
          }};

          setTimeout(function() {{
            if (box.isConnected) box.style.opacity = '0';
          }}, {duration});
          setTimeout(function() {{
            stopped = true;
            try {{ obs.disconnect(); }} catch(e) {{}}
            box.remove();
          }}, {duration + 500});
        }})();
        """
        try:
            await self.cdp_attach(tab_id)
            await self.evaluate(tab_id, js)
        except Exception as exc:
            # Best-effort visual feedback, but log rather than silently
            # swallow so we can diagnose CSP / mid-navigation failures.
            logger.debug("highlight_rect injection failed on tab %d: %s", tab_id, exc)

        _interaction_highlights[tab_id] = {
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "label": label,
            "kind": "rect",
        }

    async def highlight_point(self, tab_id: int, x: float, y: float, label: str = "") -> None:
        """Highlight a coordinate with a pulsing dot and crosshair."""
        duration = self._HIGHLIGHT_DURATION_MS
        safe_label = json.dumps(label[:60]) if label else '""'

        js = f"""
        (function() {{
          var prev = document.getElementById('__hive_hl');
          if (prev) {{
            try {{ prev.__hiveStop && prev.__hiveStop(); }} catch(e) {{}}
            prev.remove();
          }}

          var dot = document.createElement('div');
          dot.id = '__hive_hl';
          dot.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;'
            + 'left:{int(x) - 8}px;top:{int(y) - 8}px;width:16px;height:16px;'
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

          var parent = document.documentElement;
          parent.appendChild(dot);

          // SPA re-mount protection — see highlight_rect comment.
          var stopped = false;
          var retries = 0;
          var MAX_RETRIES = 5;
          var obs = new MutationObserver(function() {{
            if (stopped) return;
            if (!document.getElementById('__hive_hl')) {{
              if (retries >= MAX_RETRIES) {{
                stopped = true;
                try {{ obs.disconnect(); }} catch(e) {{}}
                return;
              }}
              retries++;
              try {{ parent.appendChild(dot); }} catch(e) {{}}
            }}
          }});
          try {{ obs.observe(parent, {{childList:true, subtree:false}}); }} catch(e) {{}}
          dot.__hiveStop = function() {{
            stopped = true;
            try {{ obs.disconnect(); }} catch(e) {{}}
          }};

          setTimeout(function() {{
            if (dot.isConnected) dot.style.opacity = '0';
          }}, {duration});
          setTimeout(function() {{
            stopped = true;
            try {{ obs.disconnect(); }} catch(e) {{}}
            dot.remove();
          }}, {duration + 500});
        }})();
        """
        try:
            await self.cdp_attach(tab_id)
            await self.evaluate(tab_id, js)
        except Exception as exc:
            logger.debug("highlight_point injection failed on tab %d: %s", tab_id, exc)

        _interaction_highlights[tab_id] = {
            "x": x,
            "y": y,
            "w": 0,
            "h": 0,
            "label": label,
            "kind": "point",
        }

    async def clear_highlight(self, tab_id: int) -> None:
        """Remove the injected highlight from the page."""
        try:
            await self.evaluate(
                tab_id,
                """
                var el = document.getElementById('__hive_hl');
                if (el) el.remove();
            """,
            )
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
            await self.highlight_rect(tab_id, rect["x"], rect["y"], rect["w"], rect["h"], label=selector)

        return {"ok": True, "action": "select", "selector": selector, "selected": values}

    # ── Inspection ─────────────────────────────────────────────────────────────

    async def evaluate(self, tab_id: int, script: str) -> dict:
        """Execute JavaScript in the page."""
        await self.cdp_attach(tab_id)
        await self._try_enable_domain(tab_id, "Runtime")

        stripped = script.strip()

        # Already a complete IIFE — run as-is, no re-wrapping
        is_iife = stripped.startswith("(function") and (stripped.endswith("})()") or stripped.endswith("})();"))
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
            ex_value = (ex.get("exception") or {}).get("description") or ex.get("text", "Script error")
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

    async def snapshot(self, tab_id: int, timeout_s: float = 30.0, mode: str = "default") -> dict:
        """Get an accessibility snapshot of the page.

        Uses a hybrid approach:
        1. CDP Accessibility.getFullAXTree for semantic structure
        2. DOM queries for visibility and computed styles
        3. Falls back to DOM tree if accessibility returns mostly ignored

        Args:
            tab_id: The tab ID to snapshot
            timeout_s: Maximum time to spend building snapshot (default 10s)
            mode: Filtering mode — "default", "simple", or "interactive"
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

            # Clean redundant InlineTextBox children before formatting
            nodes = self._clean_inline_text_boxes(nodes)

            # Format the accessibility tree (with node limit)
            snapshot = self._format_ax_tree(nodes, max_nodes=2000, mode=mode)

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

    @staticmethod
    def _clean_inline_text_boxes(nodes: list[dict]) -> list[dict]:
        """Remove redundant InlineTextBox children from StaticText nodes.

        If a StaticText node has 3+ InlineTextBox children and ALL their
        text is already contained in the StaticText's name, remove all
        the InlineTextBox children (they add no information).
        """
        by_id = {n["nodeId"]: n for n in nodes}
        children_map: dict[str, list[str]] = {}
        for n in nodes:
            for child_id in n.get("childIds", []):
                children_map.setdefault(n["nodeId"], []).append(child_id)

        ids_to_remove: set[str] = set()

        for n in nodes:
            role_info = n.get("role", {})
            role = role_info.get("value", "") if isinstance(role_info, dict) else str(role_info)
            if role != "StaticText":
                continue

            child_ids = children_map.get(n["nodeId"], [])
            if len(child_ids) < 3:
                continue

            name_info = n.get("name", {})
            parent_name = name_info.get("value", "") if isinstance(name_info, dict) else str(name_info)
            if not parent_name:
                continue

            all_inline = True
            for cid in child_ids:
                child = by_id.get(cid)
                if not child:
                    all_inline = False
                    break
                child_role_info = child.get("role", {})
                child_role = (
                    child_role_info.get("value", "") if isinstance(child_role_info, dict) else str(child_role_info)
                )
                if child_role != "InlineTextBox":
                    all_inline = False
                    break
                child_name_info = child.get("name", {})
                child_name = (
                    child_name_info.get("value", "") if isinstance(child_name_info, dict) else str(child_name_info)
                )
                if child_name and child_name not in parent_name:
                    all_inline = False
                    break

            if all_inline:
                ids_to_remove.update(child_ids)
                n["childIds"] = []

        if not ids_to_remove:
            return nodes

        return [n for n in nodes if n["nodeId"] not in ids_to_remove]

    def _format_ax_tree(self, nodes: list[dict], max_nodes: int = 2000, mode: str = "default") -> str:
        """Format a CDP Accessibility.getFullAXTree result.

        Args:
            nodes: List of accessibility tree nodes
            max_nodes: Maximum number of nodes to process (prevents hangs on huge trees)
            mode: Filtering mode — "default" (full tree), "simple" (interactive +
                  content, skip unnamed structural), "interactive" (interactive only)
        """
        from .refs import INTERACTIVE_ROLES, STRUCTURAL_ROLES

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

            name_info = node.get("name", {})
            name = name_info.get("value", "") if isinstance(name_info, dict) else str(name_info)

            # Mode-based filtering — skip node but walk children at same depth
            if mode == "interactive" and role not in INTERACTIVE_ROLES:
                for cid in children_map.get(node_id, []):
                    _walk(cid, depth)
                return
            if mode == "simple" and role in STRUCTURAL_ROLES and not name:
                for cid in children_map.get(node_id, []):
                    _walk(cid, depth)
                return

            node_counter[0] += 1

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
            if role in INTERACTIVE_ROLES or name:
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
            # _cdp returns the raw CDP response {"result":{"type":...,"value":...}}.
            # The extra .get("result") hop was dropping the value — every
            # successful lookup was silently misreported as "not found" until
            # the deadline fired.
            text = (result or {}).get("result", {}).get("value")
            if text is not None:
                return {"ok": True, "selector": selector, "text": text}
            await asyncio.sleep(0.1)

        return {"ok": False, "error": f"Element not found: {selector}"}

    async def get_attribute(self, tab_id: int, selector: str, attribute: str, timeout_ms: int = 30000) -> dict:
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
            # Same unwrap bug as get_text_by_selector — the response shape
            # is {"result":{"type":...,"value":...}}, one "result", not two.
            value = (result or {}).get("result", {}).get("value")
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
                    # One "result" hop — see comment in the meta fetch below.
                    rect = (rect_result or {}).get("result", {}).get("value")
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

                # Pass the outer screenshot timeout budget to the
                # underlying CDP call. Full-page screenshots over slow
                # networks can legitimately take 20-40s; the default 30s
                # _send floor used to make them fail spuriously right at
                # the boundary. We give the CDP call the full timeout_s
                # budget so the outer `asyncio.timeout(timeout_s)` is
                # the only authority on how long we wait.
                result = await self._cdp(
                    tab_id,
                    "Page.captureScreenshot",
                    params,
                    timeout=timeout_s,
                )
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
                # _cdp returns the raw CDP response body, which for Runtime.evaluate
                # is {"result": {"type": ..., "value": <our returned object>}}. The
                # previous code did .get("result").get("result").get("value") —
                # that extra hop dropped everything, so cssWidth always defaulted
                # to 0 and devicePixelRatio to 1.0. Which in turn collapsed
                # physical_scale and css_scale into the same number and made
                # post-screenshot clicks land at DPR× the intended coordinate.
                meta = (meta_result or {}).get("result", {}).get("value") or {}

                dpr = meta.get("dpr", 1.0)
                css_w = meta.get("cssWidth", 0)
                css_h = meta.get("cssHeight", 0)

                import struct as _struct

                raw_bytes = base64.b64decode(data) if data else b""
                png_w = _struct.unpack(">I", raw_bytes[16:20])[0] if len(raw_bytes) >= 24 else 0
                png_h = _struct.unpack(">I", raw_bytes[20:24])[0] if len(raw_bytes) >= 24 else 0
                logger.info(
                    "CDP screenshot raw: png=%dx%d, css=%dx%d, dpr=%s, implied_dpr=%.2f",
                    png_w,
                    png_h,
                    css_w,
                    css_h,
                    dpr,
                    (png_w / css_w) if css_w else 0.0,
                )

                return {
                    "ok": True,
                    "tabId": tab_id,
                    "url": meta.get("url", ""),
                    "devicePixelRatio": dpr,
                    "cssWidth": css_w,
                    "cssHeight": css_h,
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

    async def wait_for_selector(
        self,
        tab_id: int,
        selector: str,
        timeout_ms: int = DEFAULT_WAIT_TIMEOUT_MS,
    ) -> dict:
        """Wait for an element to appear.

        Default 5 s fast-fail. Callers that need to wait longer (e.g.
        a known slow post-navigation render) should pass an explicit
        ``timeout_ms``.
        """
        await self.cdp_attach(tab_id)

        script = f"""
            (function() {{
                return document.querySelector({json.dumps(selector)}) !== null;
            }})()
        """

        poll_start = asyncio.get_event_loop().time()
        deadline = poll_start + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": script, "returnByValue": True},
            )
            # One "result" hop — see navigate() comment. This was silently
            # returning False on every poll, so wait_for_selector always
            # reported "not found" after the full timeout.
            found = (result or {}).get("result", {}).get("value", False)
            if found:
                return {"ok": True, "selector": selector}
            await _adaptive_poll_sleep(asyncio.get_event_loop().time() - poll_start)

        return {"ok": False, "error": f"Element not found within timeout: {selector}"}

    async def wait_for_text(
        self,
        tab_id: int,
        text: str,
        timeout_ms: int = DEFAULT_WAIT_TIMEOUT_MS,
    ) -> dict:
        """Wait for text to appear on the page.

        Default 5 s fast-fail. Same fast-fail rationale as
        :meth:`wait_for_selector`.
        """
        await self.cdp_attach(tab_id)

        script = f"""
            (function() {{
                return document.body.innerText.includes({json.dumps(text)});
            }})()
        """

        poll_start = asyncio.get_event_loop().time()
        deadline = poll_start + timeout_ms / 1000
        while asyncio.get_event_loop().time() < deadline:
            result = await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {"expression": script, "returnByValue": True},
            )
            # Same unwrap bug as wait_for_selector.
            found = (result or {}).get("result", {}).get("value", False)
            if found:
                return {"ok": True, "text": text}
            await _adaptive_poll_sleep(asyncio.get_event_loop().time() - poll_start)

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
