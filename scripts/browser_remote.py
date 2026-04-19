"""
Browser Remote Control — act as an agent to call browser tools via a UI.

Spawns its own GCU MCP server subprocess (same way a real agent does),
connects as an MCP client, and exposes the tools over HTTP for the web UI.

Usage:
    uv run scripts/browser_remote.py          # starts server + opens UI
    uv run scripts/browser_remote.py --no-ui  # API only, no browser open

Then use the UI at http://localhost:9250/ui or curl directly:
    curl -X POST http://localhost:9250/browser_click \
         -H 'Content-Type: application/json' \
         -d '{"selector": "#login-btn"}'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import webbrowser
from pathlib import Path
from typing import Any

from aiohttp import web

# Add framework to path so we can use the existing MCPClient
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "src"))

from framework.loader.mcp_client import MCPClient, MCPServerConfig

logger = logging.getLogger("browser_remote")

DEFAULT_PORT = 9250
TOOLS_DIR = str((Path(__file__).parent.parent / "tools").resolve())


# ---------------------------------------------------------------------------
# MCP client — connects to GCU server exactly like an agent would
# ---------------------------------------------------------------------------

_mcp_client: MCPClient | None = None


def get_mcp_client() -> MCPClient:
    """Get or create the MCP client connected to the GCU server."""
    global _mcp_client
    if _mcp_client is None:
        bridge_port = os.environ.get("HIVE_BRIDGE_PORT", "9229")
        config = MCPServerConfig(
            name="gcu-tools",
            transport="stdio",
            command="uv",
            args=["run", "python", "-m", "gcu.server", "--stdio", "--capabilities", "browser"],
            cwd=TOOLS_DIR,
            env={"HIVE_BRIDGE_PORT": bridge_port},
        )
        _mcp_client = MCPClient(config)
        _mcp_client.connect()
        tools = _mcp_client.list_tools()
        logger.info(
            "Connected to GCU server, %d tools available: %s",
            len(tools),
            [t.name for t in tools],
        )
    return _mcp_client


# ---------------------------------------------------------------------------
# HTTP Handlers
# ---------------------------------------------------------------------------


async def handle_ui(request: web.Request) -> web.Response:
    """GET /ui — serve the web UI."""
    ui_path = Path(__file__).parent / "browser_remote_ui.html"
    return web.FileResponse(ui_path)


async def handle_index(request: web.Request) -> web.Response:
    """GET / — redirect to UI."""
    raise web.HTTPFound("/ui")


async def handle_status(request: web.Request) -> web.Response:
    """GET /status — connection status."""
    try:
        client = get_mcp_client()
        tools = client.list_tools()
        return web.json_response(
            {
                "connected": True,
                "tools_count": len(tools),
            }
        )
    except Exception as e:
        return web.json_response({"connected": False, "error": str(e)})


async def handle_tools(request: web.Request) -> web.Response:
    """GET /tools — list available tools with their schemas."""
    try:
        client = get_mcp_client()
        tools = client.list_tools()
        schemas = {}
        for tool in tools:
            props = tool.input_schema.get("properties", {})
            required = tool.input_schema.get("required", [])
            params = {}
            for pname, pspec in props.items():
                param_def: dict[str, Any] = {"type": pspec.get("type", "string")}
                if pname in required:
                    param_def["required"] = True
                if "default" in pspec:
                    param_def["default"] = pspec["default"]
                if "enum" in pspec:
                    param_def["enum"] = pspec["enum"]
                if pspec.get("type") == "array" and "items" in pspec:
                    param_def["items"] = pspec["items"].get("type", "string")
                params[pname] = param_def
            schemas[tool.name] = {
                "description": tool.description.split("\n")[0].strip() if tool.description else "",
                "params": params,
            }
        return web.json_response(schemas)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_tool_call(request: web.Request) -> web.Response:
    """POST /<tool_name> — call a browser tool."""
    tool_name = request.match_info["tool"]

    try:
        body = await request.read()
        params = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    logger.info("=> %s %s", tool_name, json.dumps(params, default=str)[:200])

    try:
        client = get_mcp_client()
        # call_tool is synchronous (blocks on the stdio subprocess)
        # Run it in a thread so we don't block the event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, client.call_tool, tool_name, params)

        # MCP returns a list of content blocks — extract text/image
        response = _format_mcp_result(result)
        logger.info("<= %s ok=%s", tool_name, response.get("ok", True))
        return web.json_response(response)
    except Exception as e:
        logger.error("<= %s error: %s", tool_name, e)
        return web.json_response({"ok": False, "error": str(e)}, status=500)


def _format_mcp_result(result: Any) -> dict:
    """Convert MCP tool result into a JSON-friendly dict."""
    if result is None:
        return {"ok": True}

    # MCPClient.call_tool returns the raw result from the MCP SDK
    # which could be a list of content blocks, a dict, or a string
    if isinstance(result, dict):
        return result

    if isinstance(result, str):
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return {"ok": True, "text": result}

    if isinstance(result, list):
        # List of MCP content blocks (TextContent, ImageContent, etc.)
        texts = []
        images = []
        for item in result:
            if hasattr(item, "text"):
                try:
                    parsed = json.loads(item.text)
                    if isinstance(parsed, dict):
                        return parsed  # Tool returned structured JSON
                except (json.JSONDecodeError, TypeError):
                    pass
                texts.append(item.text)
            elif hasattr(item, "data"):
                images.append({"mime_type": getattr(item, "mime_type", "image/png"), "data": item.data})

        response: dict[str, Any] = {"ok": True}
        if texts:
            response["text"] = "\n".join(texts)
        if images:
            response["images"] = images
        return response

    return {"ok": True, "result": str(result)}


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def create_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", handle_index)
    app.router.add_get("/ui", handle_ui)
    app.router.add_get("/tools", handle_tools)
    app.router.add_get("/status", handle_status)
    app.router.add_post("/{tool}", handle_tool_call)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Browser Remote Control")
    parser.add_argument("--port", type=int, default=int(os.environ.get("BROWSER_REMOTE_PORT", DEFAULT_PORT)))
    parser.add_argument("--no-ui", action="store_true", help="Don't auto-open the browser")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    # Connect to GCU server eagerly so we fail fast if something is wrong
    try:
        client = get_mcp_client()
    except Exception as e:
        logger.error("Failed to connect to GCU server: %s", e)
        sys.exit(1)

    # Auto-start browser context so tools work immediately
    try:
        result = client.call_tool("browser_start", {})
        logger.info("browser_start: %s", result)
    except Exception as e:
        logger.warning("browser_start failed (may already be started): %s", e)

    app = create_app()

    async def on_startup(app: web.Application) -> None:
        if not args.no_ui:
            webbrowser.open(f"http://localhost:{args.port}/ui")

    app.on_startup.append(on_startup)

    print(f"Browser Remote Control on http://localhost:{args.port}")
    print(f"  UI:    http://localhost:{args.port}/ui")
    print(f"  API:   POST http://localhost:{args.port}/<tool>")
    print()
    web.run_app(app, host="127.0.0.1", port=args.port, print=None)


if __name__ == "__main__":
    main()
