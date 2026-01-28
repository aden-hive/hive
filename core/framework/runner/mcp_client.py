"""MCP Client for connecting to Model Context Protocol servers.

This module provides a client for connecting to MCP servers and invoking their tools.
Supports both STDIO and HTTP transports using the official MCP Python SDK.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection."""

    name: str
    transport: Literal["stdio", "http"]

    # For STDIO transport
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None

    # For HTTP transport
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    # Optional metadata
    description: str = ""


@dataclass
class MCPTool:
    """A tool available from an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


class MCPClient:
    """
    Client for communicating with MCP servers.

    Supports both STDIO and HTTP transports using the official MCP SDK.
    Manages the connection lifecycle and provides methods to list and invoke tools.
    """

    def __init__(self, config: MCPServerConfig):
        """
        Initialize the MCP client.

        Args:
            config: Server configuration
        """
        self.config = config
        self._session = None
        self._read_stream = None
        self._write_stream = None
        self._stdio_context = None  # Context manager for stdio_client
        self._http_client: httpx.Client | None = None
        self._tools: dict[str, MCPTool] = {}
        self._connected = False

        # Background event loop for persistent STDIO connection
        self._loop = None
        self._loop_thread = None

    def _run_async(self, coro):
        """
        Run an async coroutine, handling both sync and async contexts.

        Args:
            coro: Coroutine to run

        Returns:
            Result of the coroutine
        """
        # If we have a persistent loop (for STDIO), use it
        if self._loop is not None:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result()

        # Otherwise, use the standard approach
        try:
            # Try to get the current event loop
            asyncio.get_running_loop()
            # If we're here, we're in an async context
            # Create a new thread to run the coroutine
            import threading

            result = None
            exception = None

            def run_in_thread():
                nonlocal result, exception
                try:
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        result = new_loop.run_until_complete(coro)
                    finally:
                        new_loop.close()
                except Exception as e:
                    exception = e

            thread = threading.Thread(target=run_in_thread)
            thread.start()
            thread.join()

            if exception:
                raise exception
            return result
        except RuntimeError:
            # No event loop running, we can use asyncio.run
            return asyncio.run(coro)

    def connect(self) -> None:
        """Connect to the MCP server."""
        if self._connected:
            return

        if self.config.transport == "stdio":
            self._connect_stdio()
        elif self.config.transport == "http":
            self._connect_http()
        else:
            raise ValueError(f"Unsupported transport: {self.config.transport}")

        # Discover tools
        self._discover_tools()
        self._connected = True

    def _connect_stdio(self) -> None:
        """Connect to MCP server via STDIO transport using MCP SDK with persistent connection."""
        if not self.config.command:
            raise ValueError("command is required for STDIO transport")

        try:
            import threading

            from mcp import StdioServerParameters

            # Create server parameters
            # Always inherit parent environment and merge with any custom env vars
            merged_env = {**os.environ, **(self.config.env or {})}
            server_params = StdioServerParameters(
                command=self.config.command,
                args=self.config.args,
                env=merged_env,
                cwd=self.config.cwd,
            )

            # Store for later use
            self._server_params = server_params

            # Start background event loop for persistent connection
            loop_started = threading.Event()
            connection_ready = threading.Event()
            connection_error = []

            def run_event_loop():
                """Run event loop in background thread."""
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                loop_started.set()

                # Initialize persistent connection
                async def init_connection():
                    try:
                        from mcp import ClientSession
                        from mcp.client.stdio import stdio_client

                        # Create persistent stdio client context
                        self._stdio_context = stdio_client(server_params)
                        (
                            self._read_stream,
                            self._write_stream,
                        ) = await self._stdio_context.__aenter__()

                        # Create persistent session
                        self._session = ClientSession(self._read_stream, self._write_stream)
                        await self._session.__aenter__()

                        # Initialize session
                        await self._session.initialize()

                        connection_ready.set()
                    except Exception as e:
                        connection_error.append(e)
                        connection_ready.set()

                # Schedule connection initialization
                self._loop.create_task(init_connection())

                # Run loop forever
                self._loop.run_forever()

            self._loop_thread = threading.Thread(target=run_event_loop, daemon=True)
            self._loop_thread.start()

            # Wait for loop to start
            loop_started.wait(timeout=5)
            if not loop_started.is_set():
                raise RuntimeError("Event loop failed to start")

            # Wait for connection to be ready
            connection_ready.wait(timeout=10)
            if connection_error:
                raise connection_error[0]

            logger.info(f"Connected to MCP server '{self.config.name}' via STDIO (persistent)")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to MCP server: {e}") from e

    def _connect_http(self) -> None:
        """Connect to MCP server via HTTP transport."""
        if not self.config.url:
            raise ValueError("url is required for HTTP transport")

        self._http_client = httpx.Client(
            base_url=self.config.url,
            headers=self.config.headers,
            timeout=30.0,
        )

        # Test connection
        try:
            response = self._http_client.get("/health")
            response.raise_for_status()
            logger.info(
                f"Connected to MCP server '{self.config.name}' via HTTP at {self.config.url}"
            )
        except Exception as e:
            logger.warning(f"Health check failed for MCP server '{self.config.name}': {e}")
            # Continue anyway, server might not have health endpoint

    def _discover_tools(self) -> None:
        """Discover available tools from the MCP server."""
        try:
            if self.config.transport == "stdio":
                tools_list = self._run_async(self._list_tools_stdio_async())
            else:
                tools_list = self._list_tools_http()

            self._tools = {}
            for tool_data in tools_list:
                tool = MCPTool(
                    name=tool_data["name"],
                    description=tool_data.get("description", ""),
                    input_schema=tool_data.get("inputSchema", {}),
                    server_name=self.config.name,
                )
                self._tools[tool.name] = tool

            tool_names = list(self._tools.keys())
            logger.info(
                f"Discovered {len(self._tools)} tools from '{self.config.name}': {tool_names}"
            )
        except Exception as e:
            logger.error(f"Failed to discover tools from '{self.config.name}': {e}")
            raise

    async def _list_tools_stdio_async(self) -> list[dict]:
        """List tools via STDIO protocol using persistent session."""
        if not self._session:
            raise RuntimeError("STDIO session not initialized")

        # List tools using persistent session
        response = await self._session.list_tools()

        # Convert tools to dict format
        tools_list = []
        for tool in response.tools:
            tools_list.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema,
                }
            )

        return tools_list

    def _list_tools_http(self) -> list[dict]:
        """List tools via HTTP protocol."""
        if not self._http_client:
            raise RuntimeError("HTTP client not initialized")

        try:
            # Use MCP over HTTP protocol
            response = self._http_client.post(
                "/mcp/v1",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {},
                },
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                raise RuntimeError(f"MCP error: {data['error']}")

            return data.get("result", {}).get("tools", [])
        except Exception as e:
            raise RuntimeError(f"Failed to list tools via HTTP: {e}") from e

    def list_tools(self) -> list[MCPTool]:
        """
        Get list of available tools.

        Returns:
            List of MCPTool objects
        """
        if not self._connected:
            self.connect()

        return list(self._tools.values())

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """
        Invoke a tool on the MCP server.

        Args:
            tool_name: Name of the tool to invoke
            arguments: Tool arguments

        Returns:
            Tool result
        """
        if not self._connected:
            self.connect()

        if tool_name not in self._tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        if self.config.transport == "stdio":
            return self._run_async(self._call_tool_stdio_async(tool_name, arguments))
        else:
            return self._call_tool_http(tool_name, arguments)

    async def _call_tool_stdio_async(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call tool via STDIO protocol using persistent session."""
        if not self._session:
            raise RuntimeError("STDIO session not initialized")

        # Call tool using persistent session
        result = await self._session.call_tool(tool_name, arguments=arguments)

        # Extract content
        if result.content:
            # MCP returns content as a list of content items
            if len(result.content) > 0:
                content_item = result.content[0]
                # Check if it's a text content item
                if hasattr(content_item, "text"):
                    return content_item.text
                elif hasattr(content_item, "data"):
                    return content_item.data
            return result.content

        return None

    def _call_tool_http(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call tool via HTTP protocol."""
        if not self._http_client:
            raise RuntimeError("HTTP client not initialized")

        try:
            response = self._http_client.post(
                "/mcp/v1",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                raise RuntimeError(f"Tool execution error: {data['error']}")

            return data.get("result", {}).get("content", [])
        except Exception as e:
            raise RuntimeError(f"Failed to call tool via HTTP: {e}") from e

    def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        # Clean up persistent STDIO connection
        if self._loop is not None:
            # Stop event loop - this will cause context managers to clean up naturally
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)

            # Wait for thread to finish
            if self._loop_thread and self._loop_thread.is_alive():
                self._loop_thread.join(timeout=2)

            # Clear references
            self._session = None
            self._stdio_context = None
            self._read_stream = None
            self._write_stream = None
            self._loop = None
            self._loop_thread = None

        # Clean up HTTP client
        if self._http_client:
            self._http_client.close()
            self._http_client = None

        self._connected = False
        logger.info(f"Disconnected from MCP server '{self.config.name}'")

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
