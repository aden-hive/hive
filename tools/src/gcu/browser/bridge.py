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


def _get_active_profile() -> str:
    """Get the current active profile from context variable."""
    try:
        from .session import _active_profile as ap

        return ap.get()
    except Exception:
        return "default"


class BeelineBridge:
    """WebSocket server that accepts a single connection from the Chrome extension."""

    def __init__(self) -> None:
        self._ws: object | None = None  # websockets.ServerConnection
        self._server: object | None = None  # websockets.Server
        self._pending: dict[str, asyncio.Future] = {}
        self._counter = 0
        self._cdp_attached: set[int] = set()  # Track tabs with CDP attached

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
                ready_state = eval_result.get("result", {}).get("result", {}).get("value", "")

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
            "url": url_result.get("result", {}).get("result", {}).get("value", ""),
            "title": title_result.get("result", {}).get("result", {}).get("value", ""),
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
            "url": result.get("result", {}).get("result", {}).get("value", ""),
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
            "url": result.get("result", {}).get("result", {}).get("value", ""),
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
            "url": result.get("result", {}).get("result", {}).get("value", ""),
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

        Uses DOM.getDocument + DOM.querySelector to find the element,
        then DOM.getBoxModel to get coordinates, then Input.dispatchMouseEvent.
        """
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "DOM.enable")
        await self._cdp(tab_id, "Input.enable")

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
            return {"ok": False, "error": f"Element not found: {selector}"}

        # Get box model for coordinates
        box = await self._cdp(tab_id, "DOM.getBoxModel", {"nodeId": node_id})
        content = box.get("content", [])
        if len(content) < 4:
            return {"ok": False, "error": f"Could not get element bounds: {selector}"}

        # Calculate center of element (content quad is [x1,y1, x2,y2, x3,y3, x4,y4])
        x = (content[0] + content[2] + content[4] + content[6]) / 4
        y = (content[1] + content[3] + content[5] + content[7]) / 4

        # Scroll into view first
        await self._cdp(
            tab_id,
            "DOM.scrollIntoViewIfNeeded",
            {"nodeId": node_id},
        )

        # Dispatch mouse events
        button_map = {"left": "left", "right": "right", "middle": "middle"}
        cdp_button = button_map.get(button, "left")

        await self._cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": cdp_button,
                "clickCount": click_count,
            },
        )
        await self._cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": cdp_button,
                "clickCount": click_count,
            },
        )

        return {"ok": True, "action": "click", "selector": selector, "x": x, "y": y}

    async def click_coordinate(self, tab_id: int, x: float, y: float, button: str = "left") -> dict:
        """Click at specific coordinates."""
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "Input.enable")

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
        """Type text into an element."""
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "DOM.enable")
        await self._cdp(tab_id, "Input.enable")

        # Get document and find element
        doc = await self._cdp(tab_id, "DOM.getDocument")
        root_id = doc.get("root", {}).get("nodeId")

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
            return {"ok": False, "error": f"Element not found: {selector}"}

        # Focus the element
        await self._cdp(tab_id, "DOM.focus", {"nodeId": node_id})

        # Clear if requested
        if clear_first:
            await self._cdp(
                tab_id,
                "Runtime.evaluate",
                {
                    "expression": f"document.querySelector({json.dumps(selector)}).value = ''",
                    "returnByValue": True,
                },
            )

        # Type each character
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

        return {"ok": True, "action": "type", "selector": selector, "length": len(text)}

    async def press_key(self, tab_id: int, key: str, selector: str | None = None) -> dict:
        """Press a keyboard key.

        Args:
            key: Key name like 'Enter', 'Tab', 'Escape', 'ArrowDown', etc.
            selector: Optional selector to focus first
        """
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "Input.enable")

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

    async def hover(self, tab_id: int, selector: str, timeout_ms: int = 30000) -> dict:
        """Hover over an element."""
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "DOM.enable")
        await self._cdp(tab_id, "Input.enable")

        doc = await self._cdp(tab_id, "DOM.getDocument")
        root_id = doc.get("root", {}).get("nodeId")

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
            return {"ok": False, "error": f"Element not found: {selector}"}

        box = await self._cdp(tab_id, "DOM.getBoxModel", {"nodeId": node_id})
        content = box.get("content", [])
        x = (content[0] + content[2] + content[4] + content[6]) / 4
        y = (content[1] + content[3] + content[5] + content[7]) / 4

        await self._cdp(
            tab_id,
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x, "y": y},
        )

        return {"ok": True, "action": "hover", "selector": selector}

    async def scroll(self, tab_id: int, direction: str = "down", amount: int = 500) -> dict:
        """Scroll the page."""
        await self.cdp_attach(tab_id)

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

        await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {
                "expression": f"window.scrollBy({delta_x}, {delta_y})",
                "returnByValue": True,
            },
        )

        return {"ok": True, "action": "scroll", "direction": direction, "amount": amount}

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

        return {"ok": True, "action": "select", "selector": selector, "selected": values}

    # ── Inspection ─────────────────────────────────────────────────────────────

    async def evaluate(self, tab_id: int, script: str) -> dict:
        """Execute JavaScript in the page."""
        await self.cdp_attach(tab_id)
        # Wrap in IIFE to allow return statements at top level
        wrapped_script = f"(function() {{ {script} }})()"
        result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": wrapped_script, "returnByValue": True, "awaitPromise": True},
        )

        if "exceptionDetails" in result:
            return {
                "ok": False,
                "error": result["exceptionDetails"].get("text", "Script error"),
            }

        return {
            "ok": True,
            "action": "evaluate",
            "result": result.get("result", {}).get("value"),
        }

    async def snapshot(self, tab_id: int) -> dict:
        """Get an accessibility snapshot of the page.

        Uses CDP Accessibility.getFullAXTree and formats it as a readable tree.
        """
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "Accessibility.enable")

        result = await self._cdp(tab_id, "Accessibility.getFullAXTree")
        nodes = result.get("nodes", [])

        # Format the tree
        snapshot = self._format_ax_tree(nodes)

        # Get URL
        url_result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        url = url_result.get("result", {}).get("result", {}).get("value", "")

        return {
            "ok": True,
            "tabId": tab_id,
            "url": url,
            "snapshot": snapshot,
        }

    def _format_ax_tree(self, nodes: list[dict]) -> str:
        """Format a CDP Accessibility.getFullAXTree result."""
        if not nodes:
            return "(empty tree)"

        by_id = {n["nodeId"]: n for n in nodes}
        children_map: dict[str, list[str]] = {}
        for n in nodes:
            for child_id in n.get("childIds", []):
                children_map.setdefault(n["nodeId"], []).append(child_id)

        lines: list[str] = []
        ref_counter = [0]  # Use list to allow mutation in nested function
        ref_map: dict[str, str] = {}

        def _walk(node_id: str, depth: int) -> None:
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
            text = result.get("result", {}).get("result", {}).get("value")
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
            value = result.get("result", {}).get("result", {}).get("value")
            if value is not None:
                return {"ok": True, "selector": selector, "attribute": attribute, "value": value}
            await asyncio.sleep(0.1)

        return {"ok": False, "error": f"Element not found: {selector}"}

    async def screenshot(
        self, tab_id: int, full_page: bool = False, selector: str | None = None
    ) -> dict:
        """Take a screenshot of the page or element.

        Returns {"ok": True, "data": base64_string, "mimeType": "image/png"}.
        """
        await self.cdp_attach(tab_id)
        await self._cdp(tab_id, "Page.enable")

        params: dict[str, Any] = {"format": "png"}
        if full_page:
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

        # Get URL for metadata
        url_result = await self._cdp(
            tab_id,
            "Runtime.evaluate",
            {"expression": "window.location.href", "returnByValue": True},
        )
        url = url_result.get("result", {}).get("result", {}).get("value", "")

        return {
            "ok": True,
            "tabId": tab_id,
            "url": url,
            "data": data,
            "mimeType": "image/png",
        }

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
            found = result.get("result", {}).get("result", {}).get("value", False)
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
            found = result.get("result", {}).get("result", {}).get("value", False)
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
