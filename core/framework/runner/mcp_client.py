"""MCP Client for connecting to Model Context Protocol servers.

This module provides a client for connecting to MCP servers and invoking their tools.
Supports both STDIO and HTTP transports using the official MCP Python SDK.

STDIO uses the SDK's stdio_client, HTTP uses the SDK's streamable_http_client.
Both transports share the same ClientSession-based tool listing and invocation.
"""

import asyncio
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

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
        self._transport_context = None  # Context manager for transport (stdio or http)
        self._http_async_client = None  # httpx.AsyncClient for HTTP transport
        self._get_session_id = None  # Session ID callback from streamable_http_client
        self._tools: dict[str, MCPTool] = {}
        self._connected = False

        # Background event loop for persistent connection (both transports)
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
        # If we have a persistent loop (for STDIO or HTTP), use it
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
                        self._transport_context = stdio_client(server_params)
                        (
                            self._read_stream,
                            self._write_stream,
                        ) = await self._transport_context.__aenter__()

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
        """Connect to MCP server via HTTP transport using MCP SDK with persistent connection.

        Uses the SDK's streamable_http_client for spec-compliant Streamable HTTP transport.
        This follows the same background event loop pattern as _connect_stdio().
        """
        if not self.config.url:
            raise ValueError("url is required for HTTP transport")

        # Ensure URL includes the MCP endpoint path.
        # FastMCP defaults to /mcp for Streamable HTTP transport.
        parsed = urlparse(self.config.url)
        if not parsed.path or parsed.path == "/":
            url = self.config.url.rstrip("/") + "/mcp"
        else:
            url = self.config.url

        # Start background event loop for persistent connection
        loop_started = threading.Event()
        connection_ready = threading.Event()
        connection_error = []

        def run_event_loop():
            """Run event loop in background thread."""
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            loop_started.set()

            async def init_connection():
                try:
                    from mcp import ClientSession
                    from mcp.client.streamable_http import streamable_http_client
                    from mcp.shared._httpx_utils import create_mcp_http_client

                    # Create httpx.AsyncClient with custom headers for auth
                    self._http_async_client = create_mcp_http_client(
                        headers=self.config.headers or None,
                    )

                    # Create persistent Streamable HTTP client context
                    self._transport_context = streamable_http_client(
                        url,
                        http_client=self._http_async_client,
                    )
                    (
                        self._read_stream,
                        self._write_stream,
                        self._get_session_id,
                    ) = await self._transport_context.__aenter__()

                    # Create persistent session
                    self._session = ClientSession(self._read_stream, self._write_stream)
                    await self._session.__aenter__()

                    # Initialize session (MCP spec handshake)
                    await self._session.initialize()

                    connection_ready.set()
                except Exception as e:
                    connection_error.append(e)
                    connection_ready.set()

            self._loop.create_task(init_connection())
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=run_event_loop, daemon=True)
        self._loop_thread.start()

        # Wait for loop to start
        loop_started.wait(timeout=5)
        if not loop_started.is_set():
            raise RuntimeError("Event loop failed to start")

        # Wait for connection to be ready (HTTP may need longer than STDIO)
        connection_ready.wait(timeout=30)
        if connection_error:
            raise RuntimeError(
                f"Failed to connect to MCP server '{self.config.name}' "
                f"via HTTP at {url}: {connection_error[0]}"
            ) from connection_error[0]

        logger.info(f"Connected to MCP server '{self.config.name}' via HTTP at {url} (persistent)")

    def _discover_tools(self) -> None:
        """Discover available tools from the MCP server."""
        try:
            tools_list = self._run_async(self._list_tools_async())

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

    async def _list_tools_async(self) -> list[dict]:
        """List tools via persistent MCP session (works for both transports)."""
        if not self._session:
            raise RuntimeError("MCP session not initialized")

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

        return self._run_async(self._call_tool_async(tool_name, arguments))

    async def _call_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call tool via persistent MCP session (works for both transports)."""
        if not self._session:
            raise RuntimeError("MCP session not initialized")

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

    _CLEANUP_TIMEOUT = 10
    _THREAD_JOIN_TIMEOUT = 12

    async def _cleanup_async(self) -> None:
        """Async cleanup for MCP session and transport context managers.

        Cleanup order is critical:
        - The session must be closed BEFORE the transport_context because the session
          depends on the streams provided by the transport context.
        - This mirrors the initialization order in _connect_stdio()/_connect_http(),
          where the transport context is entered first (providing streams), then the
          session is created with those streams and entered.
        - Do not change this ordering without carefully considering these dependencies.
        """
        # First: close session (depends on transport_context streams)
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

        # Second: close transport context (provides the underlying streams)
        try:
            if self._transport_context:
                await self._transport_context.__aexit__(None, None, None)
        except asyncio.CancelledError:
            logger.warning(
                "Transport context cleanup was cancelled; proceeding with best-effort shutdown"
            )
        except Exception as e:
            logger.warning(f"Error closing transport context: {e}")
        finally:
            self._transport_context = None

        # Third: close the httpx.AsyncClient if it was created for HTTP transport
        # The SDK does NOT auto-close a provided http_client, so we must do it.
        try:
            if self._http_async_client:
                await self._http_async_client.aclose()
        except Exception as e:
            logger.warning(f"Error closing HTTP async client: {e}")
        finally:
            self._http_async_client = None

    def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        # Clean up persistent connection (both STDIO and HTTP use background event loop)
        if self._loop is not None:
            cleanup_attempted = False

            # Properly close session and context managers before stopping loop
            # Note: There's an inherent race condition between checking is_running()
            # and calling run_coroutine_threadsafe(). We handle this by catching
            # any exceptions that may occur if the loop stops between these calls.
            if self._loop.is_running():
                try:
                    cleanup_future = asyncio.run_coroutine_threadsafe(
                        self._cleanup_async(), self._loop
                    )
                    cleanup_future.result(timeout=self._CLEANUP_TIMEOUT)
                    cleanup_attempted = True
                except TimeoutError:
                    # Cleanup took too long - may indicate stuck resources or slow MCP server
                    cleanup_attempted = True
                    logger.warning(f"Async cleanup timed out after {self._CLEANUP_TIMEOUT} seconds")
                except RuntimeError as e:
                    # Likely: loop stopped between is_running() check and run_coroutine_threadsafe()
                    cleanup_attempted = True
                    logger.debug(f"Event loop stopped during async cleanup: {e}")
                except Exception as e:
                    # Cleanup was attempted but failed (e.g., error in _cleanup_async())
                    cleanup_attempted = True
                    logger.warning(f"Error during async cleanup: {e}")

                # Now stop the event loop
                try:
                    self._loop.call_soon_threadsafe(self._loop.stop)
                except RuntimeError:
                    # Loop may have already stopped
                    pass

            if not cleanup_attempted:
                # Fallback: loop exists but is not running (e.g., crashed or stopped externally).
                # At this point the loop and associated resources are in an undefined state.
                # The context managers (_session, _transport_context) were created in the loop's
                # thread and may not be safely cleanable from here. Just log and proceed
                # with reference clearing - the OS will reclaim resources on process exit.
                logger.warning(
                    "Event loop for MCP connection exists but is not running; "
                    "skipping async cleanup. Resources may not be fully released."
                )

            # Wait for thread to finish (timeout proportional to cleanup timeout)
            if self._loop_thread and self._loop_thread.is_alive():
                self._loop_thread.join(timeout=self._THREAD_JOIN_TIMEOUT)
                if self._loop_thread.is_alive():
                    logger.warning(
                        "Event loop thread for MCP connection did not terminate "
                        f"within {self._THREAD_JOIN_TIMEOUT}s; thread may still be running."
                    )

            # Clear remaining references
            # Note: _session and _transport_context may already be None if _cleanup_async()
            # succeeded. This redundant assignment is intentional for safety in cases where:
            # 1. Cleanup timed out or failed
            # 2. Cleanup was skipped (loop not running)
            # 3. CancelledError interrupted cleanup
            # Setting None to None is safe and ensures clean state.
            self._session = None
            self._transport_context = None
            self._http_async_client = None
            self._get_session_id = None
            self._read_stream = None
            self._write_stream = None
            self._loop = None
            self._loop_thread = None

        self._connected = False
        logger.info(f"Disconnected from MCP server '{self.config.name}'")

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
