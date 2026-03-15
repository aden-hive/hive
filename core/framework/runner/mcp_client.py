"""MCP Client for connecting to Model Context Protocol servers.

This module provides a client for connecting to MCP servers and invoking their tools.
Supports STDIO, HTTP, Unix socket, and SSE transports using the official MCP Python SDK.
"""

import asyncio
import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection.

    Attributes:
        name: Unique name for this server connection.
        transport: Transport type - "stdio", "http", "unix", or "sse".
        command: Command to run for STDIO transport.
        args: Arguments for STDIO command.
        env: Environment variables for STDIO process.
        cwd: Working directory for STDIO process.
        url: URL for HTTP or SSE transport.
        headers: HTTP headers for HTTP, Unix, or SSE transport.
        socket_path: Unix domain socket path for Unix transport.
        sse_read_timeout: Timeout in seconds for SSE read operations.
        description: Optional description of this server.
    """

    name: str
    transport: Literal["stdio", "http", "unix", "sse"]

    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None

    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    socket_path: str | None = None
    sse_read_timeout: float = 300.0

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

    Supports STDIO, HTTP, Unix socket, and SSE transports using the official MCP SDK.
    Manages the connection lifecycle and provides methods to list and invoke tools.
    Includes automatic retry logic for transient connection failures.
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
        self._stdio_context = None
        self._errlog_handle = None
        self._http_client: httpx.Client | None = None
        self._tools: dict[str, MCPTool] = {}
        self._connected = False

        self._loop = None
        self._loop_thread = None
        self._stdio_call_lock = threading.Lock()

        self._sse_context = None
        self._sse_endpoint_url: str | None = None

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
            # Check if loop is running AND not closed
            if self._loop.is_running() and not self._loop.is_closed():
                future = asyncio.run_coroutine_threadsafe(coro, self._loop)
                return future.result()
            # else: fall through to the standard approach below
            # This handles the case when STDIO loop exists but is stopped/closed

        # Standard approach: handle both sync and async contexts
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
        elif self.config.transport == "unix":
            self._connect_unix()
        elif self.config.transport == "sse":
            self._connect_sse()
        else:
            raise ValueError(f"Unsupported transport: {self.config.transport}")

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
            # On Windows, passing cwd can cause WinError 267 ("invalid directory name").
            # tool_registry passes cwd=None and uses absolute script paths when applicable.
            cwd = self.config.cwd
            if os.name == "nt" and cwd is not None:
                # Avoid passing cwd on Windows; tool_registry should have set cwd=None
                # and absolute script paths for tools-dir servers. If cwd is still set,
                # pass None to prevent WinError 267 (caller should use absolute paths).
                cwd = None
            server_params = StdioServerParameters(
                command=self.config.command,
                args=self.config.args,
                env=merged_env,
                cwd=cwd,
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

                        # Create persistent stdio client context.
                        # On Windows, use stderr so subprocess startup errors are visible.
                        if os.name == "nt":
                            errlog = sys.stderr
                        else:
                            self._errlog_handle = open(os.devnull, "w")
                            errlog = self._errlog_handle
                        self._stdio_context = stdio_client(server_params, errlog=errlog)
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

        try:
            response = self._http_client.get("/health")
            response.raise_for_status()
            logger.info(
                f"Connected to MCP server '{self.config.name}' via HTTP at {self.config.url}"
            )
        except Exception as e:
            logger.warning(f"Health check failed for MCP server '{self.config.name}': {e}")

    def _connect_unix(self) -> None:
        """Connect to MCP server via Unix domain socket transport.

        Uses httpx with UDS (Unix Domain Socket) support for connections
        to MCP servers listening on a Unix socket.
        """
        if not self.config.socket_path:
            raise ValueError("socket_path is required for Unix transport")

        transport = httpx.HTTPTransport(uds=self.config.socket_path)
        self._http_client = httpx.Client(
            transport=transport,
            headers=self.config.headers,
            timeout=30.0,
        )

        try:
            response = self._http_client.get("/health")
            response.raise_for_status()
            logger.info(
                f"Connected to MCP server '{self.config.name}' via Unix socket at "
                f"{self.config.socket_path}"
            )
        except Exception as e:
            logger.warning(f"Health check failed for MCP server '{self.config.name}': {e}")

    def _connect_sse(self) -> None:
        """Connect to MCP server via SSE transport using MCP SDK.

        Uses the official MCP Python SDK's sse_client for Server-Sent Events
        connections. This transport is commonly used for browser-based and
        long-running MCP connections.
        """
        if not self.config.url:
            raise ValueError("url is required for SSE transport")

        url = self.config.url
        headers = self.config.headers
        sse_read_timeout = self.config.sse_read_timeout

        loop_started = threading.Event()
        connection_ready = threading.Event()
        connection_error = []

        def run_event_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            loop_started.set()

            async def init_connection():
                try:
                    from mcp import ClientSession
                    from mcp.client.sse import sse_client

                    self._sse_context = sse_client(
                        url=url,
                        headers=headers,
                        timeout=30.0,
                        sse_read_timeout=sse_read_timeout,
                    )
                    (
                        self._read_stream,
                        self._write_stream,
                    ) = await self._sse_context.__aenter__()

                    self._session = ClientSession(self._read_stream, self._write_stream)
                    await self._session.__aenter__()
                    await self._session.initialize()

                    connection_ready.set()
                except Exception as e:
                    connection_error.append(e)
                    connection_ready.set()

            self._loop.create_task(init_connection())
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=run_event_loop, daemon=True)
        self._loop_thread.start()

        loop_started.wait(timeout=5)
        if not loop_started.is_set():
            raise RuntimeError("Event loop failed to start")

        connection_ready.wait(timeout=30)
        if connection_error:
            raise connection_error[0]

        logger.info(f"Connected to MCP server '{self.config.name}' via SSE at {self.config.url}")

    def _discover_tools(self) -> None:
        """Discover available tools from the MCP server."""
        try:
            if self.config.transport == "stdio":
                tools_list = self._run_async(self._list_tools_stdio_async())
            elif self.config.transport == "sse":
                tools_list = self._run_async(self._list_tools_sse_async())
            else:
                tools_list = self._list_tools_http()

            if tools_list is None:
                tools_list = []

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

    async def _list_tools_sse_async(self) -> list[dict]:
        """List tools via SSE protocol using persistent session."""
        if not self._session:
            raise RuntimeError("SSE session not initialized")

        response = await self._session.list_tools()

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

        try:
            return self._call_tool_internal(tool_name, arguments)
        except (httpx.ConnectError, httpx.ReadTimeout) as e:
            if self.config.transport in ("http", "unix", "sse"):
                logger.warning(
                    f"Transient connection error for '{self.config.name}': {e}. "
                    "Attempting reconnect and retry..."
                )
                self._reconnect()
                return self._call_tool_internal(tool_name, arguments)
            raise

    def _call_tool_internal(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Internal method to call tool without retry logic."""
        if self.config.transport == "stdio":
            with self._stdio_call_lock:
                return self._run_async(self._call_tool_stdio_async(tool_name, arguments))
        elif self.config.transport == "sse":
            return self._run_async(self._call_tool_sse_async(tool_name, arguments))
        else:
            return self._call_tool_http(tool_name, arguments)

    def _reconnect(self) -> None:
        """Reconnect to the MCP server after a transient failure.

        Tears down the existing connection and re-establishes it.
        Used for retry logic on HTTP, Unix, and SSE transports.
        """
        logger.info(f"Reconnecting to MCP server '{self.config.name}'...")
        self._connected = False

        if self.config.transport == "http":
            if self._http_client:
                self._http_client.close()
                self._http_client = None
            self._connect_http()
        elif self.config.transport == "unix":
            if self._http_client:
                self._http_client.close()
                self._http_client = None
            self._connect_unix()
        elif self.config.transport == "sse":
            self._cleanup_sse()
            self._connect_sse()

        self._discover_tools()
        self._connected = True
        logger.info(f"Successfully reconnected to MCP server '{self.config.name}'")

    async def _call_tool_stdio_async(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call tool via STDIO protocol using persistent session."""
        if not self._session:
            raise RuntimeError("STDIO session not initialized")

        # Call tool using persistent session
        result = await self._session.call_tool(tool_name, arguments=arguments)

        # Check for server-side errors (validation failures, tool exceptions, etc.)
        if getattr(result, "isError", False):
            error_text = ""
            if result.content:
                content_item = result.content[0]
                if hasattr(content_item, "text"):
                    error_text = content_item.text
            raise RuntimeError(f"MCP tool '{tool_name}' failed: {error_text}")

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

    async def _call_tool_sse_async(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call tool via SSE protocol using persistent session."""
        if not self._session:
            raise RuntimeError("SSE session not initialized")

        result = await self._session.call_tool(tool_name, arguments=arguments)

        if getattr(result, "isError", False):
            error_text = ""
            if result.content:
                content_item = result.content[0]
                if hasattr(content_item, "text"):
                    error_text = content_item.text
            raise RuntimeError(f"MCP tool '{tool_name}' failed: {error_text}")

        if result.content:
            if len(result.content) > 0:
                content_item = result.content[0]
                if hasattr(content_item, "text"):
                    return content_item.text
                elif hasattr(content_item, "data"):
                    return content_item.data
            return result.content

        return None

    _CLEANUP_TIMEOUT = 10
    _THREAD_JOIN_TIMEOUT = 12

    async def _cleanup_sse_async(self) -> None:
        """Async cleanup for SSE session and context managers."""
        try:
            if self._session:
                await self._session.__aexit__(None, None, None)
        except asyncio.CancelledError:
            logger.warning(
                "SSE session cleanup was cancelled; proceeding with best-effort shutdown"
            )
        except Exception as e:
            logger.warning(f"Error closing SSE session: {e}")
        finally:
            self._session = None

        try:
            if self._sse_context:
                await self._sse_context.__aexit__(None, None, None)
        except asyncio.CancelledError:
            logger.debug("SSE context cleanup was cancelled")
        except Exception as e:
            logger.warning(f"Error closing SSE context: {e}")
        finally:
            self._sse_context = None

    def _cleanup_sse(self) -> None:
        """Synchronous cleanup for SSE connection."""
        if self._loop is not None and self._loop.is_running():
            try:
                cleanup_future = asyncio.run_coroutine_threadsafe(
                    self._cleanup_sse_async(), self._loop
                )
                cleanup_future.result(timeout=self._CLEANUP_TIMEOUT)
            except TimeoutError:
                logger.warning(f"SSE cleanup timed out after {self._CLEANUP_TIMEOUT} seconds")
            except Exception as e:
                logger.warning(f"Error during SSE cleanup: {e}")

            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except RuntimeError:
                pass

        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=self._THREAD_JOIN_TIMEOUT)

        self._session = None
        self._sse_context = None
        self._read_stream = None
        self._write_stream = None
        self._loop = None
        self._loop_thread = None

    async def _cleanup_stdio_async(self) -> None:
        """Async cleanup for STDIO session and context managers.

        Cleanup order is critical:
        - The session must be closed BEFORE the stdio_context because the session
          depends on the streams provided by stdio_context.
        - This mirrors the initialization order in _connect_stdio(), where
          stdio_context is entered first (providing streams), then the session is
          created with those streams and entered.
        - Do not change this ordering without carefully considering these dependencies.
        """
        # First: close session (depends on stdio_context streams)
        try:
            if self._session:
                await self._session.__aexit__(None, None, None)
        except asyncio.CancelledError:
            logger.warning(
                "MCP session cleanup was cancelled; proceeding with best-effort shutdown"
            )
        except Exception as e:
            logger.warning(f"Error closing MCP session: {e}")
        finally:
            self._session = None

        # Second: close stdio_context (provides the underlying streams)
        try:
            if self._stdio_context:
                await self._stdio_context.__aexit__(None, None, None)
        except asyncio.CancelledError:
            logger.debug(
                "STDIO context cleanup was cancelled; proceeding with best-effort shutdown"
            )
        except Exception as e:
            msg = str(e).lower()
            if "cancel scope" in msg or "different task" in msg:
                logger.debug("STDIO context teardown (known anyio quirk): %s", e)
            else:
                logger.warning(f"Error closing STDIO context: {e}")
        finally:
            self._stdio_context = None

        # Third: close errlog file handle if we opened one
        if self._errlog_handle is not None:
            try:
                self._errlog_handle.close()
            except Exception as e:
                logger.debug(f"Error closing errlog handle: {e}")
            finally:
                self._errlog_handle = None

    def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self.config.transport == "stdio":
            self._disconnect_stdio()
        elif self.config.transport == "sse":
            self._cleanup_sse()
        elif self._loop is not None:
            self._disconnect_stdio()

        if self._http_client:
            self._http_client.close()
            self._http_client = None

        self._connected = False
        logger.info(f"Disconnected from MCP server '{self.config.name}'")

    def _disconnect_stdio(self) -> None:
        """Clean up persistent STDIO connection."""
        if self._loop is None:
            return

        cleanup_attempted = False

        if self._loop.is_running():
            try:
                cleanup_future = asyncio.run_coroutine_threadsafe(
                    self._cleanup_stdio_async(), self._loop
                )
                cleanup_future.result(timeout=self._CLEANUP_TIMEOUT)
                cleanup_attempted = True
            except TimeoutError:
                cleanup_attempted = True
                logger.warning(f"Async cleanup timed out after {self._CLEANUP_TIMEOUT} seconds")
            except RuntimeError as e:
                cleanup_attempted = True
                logger.debug(f"Event loop stopped during async cleanup: {e}")
            except Exception as e:
                cleanup_attempted = True
                logger.warning(f"Error during async cleanup: {e}")

            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except RuntimeError:
                pass

        if not cleanup_attempted:
            logger.warning(
                "Event loop for STDIO MCP connection exists but is not running; "
                "skipping async cleanup. Resources may not be fully released."
            )

        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=self._THREAD_JOIN_TIMEOUT)
            if self._loop_thread.is_alive():
                logger.warning(
                    "Event loop thread for STDIO MCP connection did not terminate "
                    f"within {self._THREAD_JOIN_TIMEOUT}s; thread may still be running."
                )

        self._session = None
        self._stdio_context = None
        self._read_stream = None
        self._write_stream = None
        self._loop = None
        self._loop_thread = None
        self._errlog_handle = None

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
