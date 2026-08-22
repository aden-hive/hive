"""MCP Client for connecting to Model Context Protocol servers.

This module provides a client for connecting to MCP servers and invoking their tools.
Supports STDIO, HTTP, UNIX socket, and SSE transports using the official MCP Python SDK.
"""

import asyncio
import concurrent.futures
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

from framework.loader.mcp_errors import MCPToolNotFoundError

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection."""

    name: str
    transport: Literal["stdio", "http", "unix", "sse"]

    # For STDIO transport
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None

    # For HTTP transport
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    socket_path: str | None = None

    # Optional metadata
    description: str = ""


@dataclass
class MCPTool:
    """A tool available from an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


@dataclass
class _StdioConnection:
    """One GENERATION of a persistent STDIO/SSE connection.

    All loop/session/teardown state lives on this record, not on the
    client. The owner coroutine closes over ITS OWN record, so a stale
    generation's teardown can never observe — let alone clobber — the
    primitives of a newer connection. That cross-generation clobbering
    (old owner nulling the new session, old loop waiting on an Event
    created in the new loop) is what permanently wedged the shared
    gcu-tools client after a force-disconnect: "Event is bound to a
    different event loop" / "STDIO session not initialized".
    """

    generation: int
    loop: Any = None  # asyncio.AbstractEventLoop, created in loop_thread
    loop_thread: Any = None  # threading.Thread
    session: Any = None  # mcp.ClientSession
    read_stream: Any = None
    write_stream: Any = None
    stdio_context: Any = None  # stdio_client context manager
    sse_context: Any = None  # sse_client context manager
    stop_event: Any = None  # asyncio.Event, created INSIDE the loop thread
    cleanup_done: Any = None  # threading.Event
    errlog_handle: Any = None


def _split_mcp_content(items: list[Any]) -> tuple[str, list[dict[str, Any]]]:
    """Split an MCP tool's content list into joined text + image-content blocks.

    MCP results carry a heterogeneous list of `TextContent` (``.text``)
    and `ImageContent` (``.data`` + ``.mimeType``). We forward text
    verbatim and translate binary items into the OpenAI-style content
    blocks the agent loop's `ToolResult.image_content` expects.

    Special case: when ``mimeType == "application/pdf"`` we emit an
    OpenAI ``file`` block instead of ``image_url``. LiteLLM only
    auto-remaps PDFs to each provider's native shape (Anthropic
    ``document``, Gemini ``inline_data``) from the ``file`` block; an
    ``image_url`` with ``media_type=application/pdf`` gets emitted as
    ``{"type":"image",...}`` which Anthropic rejects (Layer B probe,
    `/tmp/litellm_pdf_probe2.py`).

    Returns (joined_text, image_parts).
    """
    text_parts: list[str] = []
    image_parts: list[dict[str, Any]] = []
    for item in items:
        if hasattr(item, "text"):
            text_parts.append(item.text)
        elif hasattr(item, "data") and hasattr(item, "mimeType"):
            mime = (item.mimeType or "").lower()
            if mime == "application/pdf":
                filename = "document.pdf"
                meta = getattr(item, "_meta", None)
                if isinstance(meta, dict) and isinstance(meta.get("filename"), str):
                    filename = meta["filename"]
                image_parts.append(
                    {
                        "type": "file",
                        "file": {
                            "file_data": f"data:application/pdf;base64,{item.data}",
                            "filename": filename,
                        },
                    }
                )
            else:
                image_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{item.mimeType};base64,{item.data}",
                        },
                    }
                )
        elif hasattr(item, "data"):
            text_parts.append(str(item.data))
    return ("\n".join(text_parts) if text_parts else ""), image_parts


class MCPClient:
    """
    Client for communicating with MCP servers.

    Supports STDIO, HTTP, UNIX socket, and SSE transports using the official MCP SDK.
    Manages the connection lifecycle and provides methods to list and invoke tools.
    """

    def __init__(self, config: MCPServerConfig):
        """
        Initialize the MCP client.

        Args:
            config: Server configuration
        """
        self.config = config
        self._http_client: httpx.Client | None = None
        self._tools: dict[str, MCPTool] = {}
        self._connected = False

        # Current persistent-connection generation (STDIO/SSE). All
        # loop/session state lives on the record — see _StdioConnection.
        self._conn: _StdioConnection | None = None
        self._generation = 0
        # Serializes connect/disconnect/_reconnect across worker threads.
        # This client is SHARED by every worker using the server (pooled in
        # MCPConnectionManager); N workers timing out at once must not
        # interleave teardowns and reconnects on the same instance.
        self._lifecycle_lock = threading.RLock()
        # After a failed reconnect, fail fast for a window instead of
        # letting queued workers stampede connect() against a dead server.
        self._reconnect_block_until = 0.0
        # Liveness bookkeeping for probe_liveness() and the agent-side
        # timeout policy (probe before force-disconnecting a shared client).
        self._inflight_calls = 0
        self._inflight_lock = threading.Lock()
        self._consecutive_probe_failures = 0
        # Generation the CURRENT thread's last call ran on. _reconnect uses
        # it to collapse retries: a worker whose call failed on gen N must
        # not tear down gen N+1 that another worker already built.
        self._thread_call_gen = threading.local()
        # Serialize STDIO tool calls on Windows only, where concurrent
        # writers have raced on the pipe transport. MCP multiplexes
        # concurrent requests over one session, so POSIX runs calls
        # concurrently — otherwise one slow browser call convoys every
        # other worker's calls into spurious 60s timeouts.
        self._stdio_call_lock: threading.Lock | None = threading.Lock() if os.name == "nt" else None

    def _run_async(self, coro, conn: "_StdioConnection | None" = None):
        """
        Run an async coroutine, handling both sync and async contexts.

        Args:
            coro: Coroutine to run
            conn: Connection generation to run on. Callers that already
                snapshotted ``self._conn`` pass it so a mid-call reconnect
                can't route an old-generation coroutine onto a new loop.

        Returns:
            Result of the coroutine
        """
        # If we have a persistent loop (for STDIO/SSE), use it
        conn = conn if conn is not None else self._conn
        if conn is not None and conn.loop is not None:
            loop = conn.loop
            # Check if loop is running AND not closed
            if loop.is_running() and not loop.is_closed():
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                with self._inflight_lock:
                    self._inflight_calls += 1
                try:
                    return self._wait_for_future(future, loop)
                except concurrent.futures.TimeoutError:
                    # The coroutine is wedged — e.g. a hung MCP STDIO/browser
                    # call whose force-disconnect also failed to tear it down.
                    # Stop blocking this worker thread *forever*: an un-timed
                    # result() leaks one tool-pool thread per wedged call until
                    # the pool is exhausted and the swarm dies. Cancel, mark the
                    # transport dead, and raise a dead-session error so the
                    # caller's retry path reconnects (_is_stdio_dead_session_error).
                    # NB: "transport closed" is a classification needle for that
                    # retry path — keep it if you reword this message.
                    future.cancel()
                    self._connected = False
                    raise RuntimeError(
                        f"MCP call exceeded {self._CALL_RESULT_TIMEOUT}s and was "
                        f"abandoned (transport closed): server={self.config.name}. "
                        "This is a TRANSPORT-LEVEL timeout inside the runtime, not an "
                        "application or browser crash — the runtime reconnects "
                        "automatically. Do NOT kill, restart, or launch any processes "
                        "to 'fix' this; retry the tool once after ~30s, then report "
                        "the failure and move on."
                    ) from None
                except concurrent.futures.CancelledError:
                    # The connection this call ran on was torn down (e.g. a
                    # justified force-disconnect) and _teardown_conn cancelled
                    # the in-flight task. Surface it as a dead-session error
                    # so _call_tool_with_retry transparently retries on the
                    # fresh generation.
                    self._connected = False
                    raise RuntimeError(
                        f"MCP call was cancelled by a connection reset (transport closed): "
                        f"server={self.config.name}. The runtime reconnects automatically; "
                        "retry the tool once after ~30s if needed."
                    ) from None
                finally:
                    with self._inflight_lock:
                        self._inflight_calls -= 1
            # else: fall through to the standard approach below
            # This handles the case when STDIO loop exists but is stopped/closed

        # Standard approach: handle both sync and async contexts
        return self._run_async_fallback(coro)

    def _wait_for_future(self, future: "concurrent.futures.Future", loop) -> Any:
        """Block on a cross-thread future, but stay LOOP-AWARE.

        If the connection's loop stops mid-call (force-disconnect tore the
        generation down), a cancelled task that re-suspends during its anyio
        cleanup can leave the future unresolved forever — and the worker
        thread would then block until the full call-result ceiling. Poll in
        small slices and bail as soon as the loop is gone; raises
        concurrent.futures.CancelledError so the caller's reset branch runs.
        """
        deadline = time.monotonic() + self._CALL_RESULT_TIMEOUT
        while True:
            try:
                return future.result(timeout=1.0)
            except concurrent.futures.TimeoutError:
                if time.monotonic() >= deadline:
                    raise
                if not loop.is_running() or loop.is_closed():
                    future.cancel()
                    raise concurrent.futures.CancelledError() from None

    def _run_async_fallback(self, coro):
        """Run *coro* without a persistent loop (sync or async context)."""
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
        with self._lifecycle_lock:
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
            # On Windows, passing cwd can cause WinError 267 ("invalid directory name").
            # tool_registry passes cwd=None and uses absolute script paths when applicable.
            cwd = self.config.cwd
            args = list(self.config.args or [])
            if os.name == "nt" and cwd is not None:
                # Registry-loaded server configs (mcp_registry._manifest_to_config)
                # bypass tool_registry._resolve_mcp_server_config, so they arrive
                # here with cwd set and relative ``.py`` script names. Resolve any
                # such script against cwd to an absolute path before discarding
                # cwd, so the inherited parent cwd doesn't break the lookup.
                cwd_path = Path(cwd)
                for i, arg in enumerate(args):
                    if isinstance(arg, str) and arg.endswith(".py") and not Path(arg).is_absolute():
                        candidate = cwd_path / arg
                        if candidate.exists():
                            args[i] = str(candidate.resolve())
                # Same fix as tool_registry._resolve_mcp_server_config: the
                # child can no longer see cwd, so hand it over via env.
                # files_server.py reads HIVE_MCP_SERVER_CWD to anchor its
                # relative-path fallback instead of inheriting this
                # process's cwd (a config-supplied env value wins).
                merged_env.setdefault("HIVE_MCP_SERVER_CWD", str(cwd_path))
                cwd = None
            server_params = StdioServerParameters(
                command=self.config.command,
                args=args,
                env=merged_env,
                cwd=cwd,
            )

            # Store for later use
            self._server_params = server_params

            # Start background event loop for a NEW connection generation.
            # Everything mutable lives on the record; the owner coroutine
            # below closes over it and never touches ``self.*`` state.
            self._generation += 1
            conn = _StdioConnection(generation=self._generation)
            conn.cleanup_done = threading.Event()

            loop_started = threading.Event()
            connection_ready = threading.Event()
            connection_error = []

            def run_event_loop():
                """Run event loop in background thread."""
                conn.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(conn.loop)
                loop_started.set()

                # Owner coroutine. anyio binds each context manager's cancel
                # scope to the task that ENTERS it; exiting from a different task
                # raises "exit cancel scope in a different task" and leaks the
                # subprocess + sockets. So ONE task enters the stdio_client /
                # ClientSession contexts, stays alive until disconnect sets
                # the record's stop_event, then exits them itself.
                async def init_connection():
                    # Created inside the loop that waits on it, bound to the
                    # record — invisible to every other generation.
                    conn.stop_event = asyncio.Event()
                    try:
                        from mcp import ClientSession
                        from mcp.client.stdio import stdio_client

                        # Create persistent stdio client context.
                        # On Windows, use stderr so subprocess startup errors are visible.
                        if os.name == "nt":
                            errlog = sys.stderr
                        else:
                            conn.errlog_handle = open(os.devnull, "w")
                            errlog = conn.errlog_handle
                        conn.stdio_context = stdio_client(server_params, errlog=errlog)
                        (
                            conn.read_stream,
                            conn.write_stream,
                        ) = await conn.stdio_context.__aenter__()

                        # Create persistent session
                        conn.session = ClientSession(conn.read_stream, conn.write_stream)
                        await conn.session.__aenter__()

                        # Initialize session
                        await conn.session.initialize()

                        connection_ready.set()
                        # Stay alive owning the contexts until disconnect().
                        await conn.stop_event.wait()
                    except Exception as e:
                        connection_error.append(e)
                        connection_ready.set()
                    finally:
                        # Exit the contexts in THIS task (the one that entered
                        # them), then report teardown complete to disconnect().
                        await self._cleanup_conn_async(conn)
                        conn.cleanup_done.set()

                # Schedule connection initialization
                conn.loop.create_task(init_connection())

                # Run loop forever
                conn.loop.run_forever()

            conn.loop_thread = threading.Thread(target=run_event_loop, daemon=True)
            conn.loop_thread.start()

            # Wait for loop to start
            loop_started.wait(timeout=5)
            if not loop_started.is_set():
                self._teardown_conn(conn)
                raise RuntimeError("Event loop failed to start")

            # Wait for connection to be ready
            connection_ready.wait(timeout=10)
            if connection_error:
                # The owner's finally already cleaned its contexts; stop the
                # loop and reap the thread so a failed connect leaks nothing.
                self._teardown_conn(conn)
                raise connection_error[0]

            # Publish only a fully-initialized connection.
            self._conn = conn
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
            logger.info(f"Connected to MCP server '{self.config.name}' via HTTP at {self.config.url}")
        except Exception as e:
            logger.warning(f"Health check failed for MCP server '{self.config.name}': {e}")
            # Continue anyway, server might not have health endpoint

    def _connect_unix(self) -> None:
        """Connect to MCP server via UNIX domain socket transport."""
        if not self.config.url:
            raise ValueError("url is required for UNIX transport")
        if not self.config.socket_path:
            raise ValueError("socket_path is required for UNIX transport")

        self._http_client = httpx.Client(
            base_url=self.config.url,
            headers=self.config.headers,
            timeout=30.0,
            transport=httpx.HTTPTransport(uds=self.config.socket_path),
        )

        try:
            response = self._http_client.get("/health")
            response.raise_for_status()
            logger.info(
                "Connected to MCP server '%s' via UNIX socket at %s",
                self.config.name,
                self.config.socket_path,
            )
        except Exception as e:
            logger.warning(f"Health check failed for MCP server '{self.config.name}': {e}")
            # Continue anyway, server might not have health endpoint

    def _connect_sse(self) -> None:
        """Connect to MCP server via SSE transport using MCP SDK with persistent session."""
        if not self.config.url:
            raise ValueError("url is required for SSE transport")

        try:
            self._generation += 1
            conn = _StdioConnection(generation=self._generation)
            conn.cleanup_done = threading.Event()

            loop_started = threading.Event()
            connection_ready = threading.Event()
            connection_error = []

            def run_event_loop():
                """Run event loop in background thread."""
                conn.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(conn.loop)
                loop_started.set()

                # Same owner-coroutine pattern as STDIO: one task enters AND
                # exits the anyio-backed contexts (correct task affinity).
                async def init_connection():
                    conn.stop_event = asyncio.Event()
                    try:
                        from mcp import ClientSession
                        from mcp.client.sse import sse_client

                        conn.sse_context = sse_client(
                            self.config.url,
                            headers=self.config.headers,
                            timeout=30.0,
                        )
                        (
                            conn.read_stream,
                            conn.write_stream,
                        ) = await conn.sse_context.__aenter__()

                        conn.session = ClientSession(conn.read_stream, conn.write_stream)
                        await conn.session.__aenter__()
                        await conn.session.initialize()

                        connection_ready.set()
                        await conn.stop_event.wait()
                    except Exception as e:
                        connection_error.append(e)
                        connection_ready.set()
                    finally:
                        await self._cleanup_conn_async(conn)
                        conn.cleanup_done.set()

                conn.loop.create_task(init_connection())
                conn.loop.run_forever()

            conn.loop_thread = threading.Thread(target=run_event_loop, daemon=True)
            conn.loop_thread.start()

            loop_started.wait(timeout=5)
            if not loop_started.is_set():
                self._teardown_conn(conn)
                raise RuntimeError("Event loop failed to start")

            connection_ready.wait(timeout=10)
            if connection_error:
                self._teardown_conn(conn)
                raise connection_error[0]

            self._conn = conn
            logger.info(f"Connected to MCP server '{self.config.name}' via SSE")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to MCP server: {e}") from e

    def _discover_tools(self) -> None:
        """Discover available tools from the MCP server."""
        try:
            if self.config.transport in {"stdio", "sse"}:
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
            logger.info(f"Discovered {len(self._tools)} tools from '{self.config.name}'")
            logger.debug(f"Discovered tools from '{self.config.name}': {tool_names}")
        except Exception as e:
            logger.error(f"Failed to discover tools from '{self.config.name}': {e}")
            raise

    async def _list_tools_stdio_async(self, conn: _StdioConnection | None = None) -> list[dict]:
        """List tools via STDIO protocol using persistent session."""
        conn = conn if conn is not None else self._conn
        session = conn.session if conn is not None else None
        if not session:
            raise RuntimeError("STDIO session not initialized")

        # List tools using persistent session
        response = await session.list_tools()

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
            raise MCPToolNotFoundError(
                server=self.config.name,
                tool_name=tool_name,
            )

        if self.config.transport == "stdio":

            def _stdio_call() -> Any:
                # Snapshot the generation once per attempt: a mid-call
                # reconnect must not route this coroutine onto a new loop
                # or hand an old-loop coroutine a new-loop session. The
                # retry path re-invokes this closure, re-snapshotting.
                conn = self._conn
                self._thread_call_gen.gen = conn.generation if conn is not None else -1
                if self._stdio_call_lock is not None:  # Windows serialization only
                    with self._stdio_call_lock:
                        return self._run_async(self._call_tool_stdio_async(tool_name, arguments, conn), conn)
                return self._run_async(self._call_tool_stdio_async(tool_name, arguments, conn), conn)

            return self._call_tool_with_retry(_stdio_call)
        elif self.config.transport == "sse":

            def _sse_call() -> Any:
                conn = self._conn
                self._thread_call_gen.gen = conn.generation if conn is not None else -1
                return self._run_async(self._call_tool_stdio_async(tool_name, arguments, conn), conn)

            return self._call_tool_with_retry(_sse_call)
        elif self.config.transport == "unix":
            return self._call_tool_with_retry(lambda: self._call_tool_http(tool_name, arguments))
        else:
            return self._call_tool_http(tool_name, arguments)

    # Exceptions that indicate the STDIO session/subprocess is dead and
    # needs a fresh connect(). Keep this narrow — we don't want to mask
    # tool-level errors as transport errors.
    _STDIO_DEAD_SESSION_ERRORS = (
        BrokenPipeError,
        ConnectionError,
        ConnectionResetError,
        EOFError,
    )

    def _is_stdio_dead_session_error(self, exc: BaseException) -> bool:
        if isinstance(exc, self._STDIO_DEAD_SESSION_ERRORS):
            return True
        # anyio raises these when the streams close under an in-flight call
        # (e.g. the session torn down by a force-disconnect). Matched by
        # name to avoid importing anyio here.
        if type(exc).__name__ in ("ClosedResourceError", "BrokenResourceError", "EndOfStream"):
            return True
        # mcp SDK frequently wraps transport errors in RuntimeError with a
        # readable message — match on the common signals.
        if isinstance(exc, RuntimeError):
            msg = str(exc).lower()
            for needle in (
                "broken pipe",
                "connection closed",
                "connection reset",
                "stream closed",
                "session not initialized",
                "transport closed",
                "anyio.closedresourceerror",
                "read operation was cancelled",
            ):
                if needle in msg:
                    return True
        return False

    def _call_tool_with_retry(self, call: Any) -> Any:
        """Retry once after reconnecting when the transport looks dead.

        Applies to all transports:
        - **stdio**: if the subprocess died (broken pipe, closed stream,
          session not initialized), tear it down and start a fresh one.
        - **sse / unix / http** (httpx-backed): same treatment for
          ``httpx.ConnectError`` / ``httpx.ReadTimeout``.
        """
        if self.config.transport == "stdio":
            try:
                return call()
            except BaseException as original_error:
                if not self._is_stdio_dead_session_error(original_error):
                    raise
                logger.warning(
                    "Retrying MCP STDIO tool call after dead-session signal from '%s': %s",
                    self.config.name,
                    original_error,
                )
                try:
                    self._reconnect()
                except Exception as reconnect_error:
                    logger.warning(
                        "Reconnect failed for MCP STDIO server '%s': %s",
                        self.config.name,
                        reconnect_error,
                    )
                    raise original_error from reconnect_error
                try:
                    return call()
                except BaseException as retry_error:
                    raise original_error from retry_error

        if self.config.transport not in {"unix", "sse"}:
            return call()

        try:
            return call()
        except (httpx.ConnectError, httpx.ReadTimeout) as original_error:
            logger.warning(
                "Retrying MCP tool call after transport error from '%s': %s",
                self.config.name,
                original_error,
            )
            self._reconnect()
            try:
                return call()
            except (httpx.ConnectError, httpx.ReadTimeout) as retry_error:
                raise original_error from retry_error

    async def _call_tool_stdio_async(self, tool_name: str, arguments: dict[str, Any], conn: _StdioConnection | None = None) -> Any:
        """Call tool via STDIO protocol using persistent session."""
        conn = conn if conn is not None else self._conn
        session = conn.session if conn is not None else None
        if not session:
            raise RuntimeError("STDIO session not initialized")

        # Call tool using persistent session
        result = await session.call_tool(tool_name, arguments=arguments)

        # Check for server-side errors (validation failures, tool exceptions, etc.)
        if getattr(result, "isError", False):
            error_text = ""
            if result.content:
                content_item = result.content[0]
                if hasattr(content_item, "text"):
                    error_text = content_item.text
            raise RuntimeError(f"[Server: {self.config.name}] [Transport: {self.config.transport}] Tool '{tool_name}' failed: {error_text}")

        # Extract content — preserve image blocks alongside text
        if result.content:
            text, image_parts = _split_mcp_content(result.content)
            if image_parts:
                return {"_text": text, "_images": image_parts}
            return text if text else None

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
                raise RuntimeError(f"[Server: {self.config.name}] [Transport: {self.config.transport}] Tool '{tool_name}' failed: {data['error']}")

            return data.get("result", {}).get("content", [])
        except Exception as e:
            raise RuntimeError(
                f"[Server: {self.config.name}] [Transport: {self.config.transport}] Failed to call tool via HTTP: Tool '{tool_name}' failed: {e}"
            ) from e

    def _reconnect(self) -> None:
        """Reconnect to the configured MCP server.

        Safe under concurrency: N workers whose calls all failed on the same
        dead generation will race here. The first one through the lifecycle
        lock reconnects; the rest observe the generation bump and no-op (their
        retry then runs on the fresh connection). A failed reconnect arms a
        cooldown so a dead server yields fast, honest failures instead of a
        connect storm.
        """
        # Prefer the generation this thread's failed call actually ran on
        # (stamped in call_tool); fall back to the current snapshot.
        observed_gen = getattr(self._thread_call_gen, "gen", None)
        if observed_gen is None:
            observed_gen = self._conn.generation if self._conn is not None else -1
        with self._lifecycle_lock:
            current_gen = self._conn.generation if self._conn is not None else -1
            if self._connected and current_gen != observed_gen:
                # Another worker already swapped in a fresh generation while
                # we waited on the lock (or before we got here) — nothing to
                # do; the caller's retry runs on the fresh connection.
                return
            now = time.monotonic()
            if now < self._reconnect_block_until:
                raise RuntimeError(
                    f"MCP server '{self.config.name}' reconnect is in cooldown after a "
                    f"recent failure ({self._reconnect_block_until - now:.0f}s left); "
                    "transport closed. The runtime retries automatically — do not "
                    "attempt manual recovery."
                )
            logger.info(f"Reconnecting to MCP server '{self.config.name}'...")
            self.disconnect()
            try:
                self.connect()
            except Exception:
                self._reconnect_block_until = time.monotonic() + self._RECONNECT_COOLDOWN
                raise
            self._consecutive_probe_failures = 0

    _CLEANUP_TIMEOUT = 10
    _THREAD_JOIN_TIMEOUT = 12
    _RECONNECT_COOLDOWN = 30
    # Last-resort ceiling on a single blocking MCP call run via the persistent
    # STDIO loop. INVARIANT: must stay above the largest agent-side per-tool
    # timeout (LoopConfig.tool_call_timeout_seconds AND every entry in
    # LoopConfig.tool_timeout_overrides — browser_* runs at 180s) plus margin,
    # so the agent-side timeout is always the primary path; this only catches
    # a call that truly wedged, reclaiming its worker thread instead of
    # leaking it. Override via env if needed.
    _CALL_RESULT_TIMEOUT = int(os.environ.get("HIVE_MCP_CALL_RESULT_TIMEOUT", "240"))

    async def _cleanup_conn_async(self, conn: _StdioConnection) -> None:
        """Async cleanup for one connection generation's session and contexts.

        Operates ONLY on the record — never on ``self`` — so a stale
        generation finishing its teardown late cannot null out a newer
        generation's session (the post-force-disconnect wedge).

        Cleanup order is critical:
        - The session must be closed BEFORE the transport context manager because the
          session depends on the streams provided by that context.
        - This mirrors the initialization order in _connect_stdio() / _connect_sse(),
          where the transport context is entered first (providing streams), then the
          session is created with those streams and entered.
        - Do not change this ordering without carefully considering these dependencies.
        """
        # First: close session (depends on stdio_context streams)
        try:
            if conn.session:
                await conn.session.__aexit__(None, None, None)
        except asyncio.CancelledError:
            logger.warning("MCP session cleanup was cancelled; proceeding with best-effort shutdown")
        except Exception as e:
            logger.warning(f"Error closing MCP session: {e}")
        finally:
            conn.session = None

        # Second: close stdio_context (provides the underlying streams)
        try:
            if conn.stdio_context:
                await conn.stdio_context.__aexit__(None, None, None)
        except asyncio.CancelledError:
            logger.debug("STDIO context cleanup was cancelled; proceeding with best-effort shutdown")
        except Exception as e:
            msg = str(e).lower()
            if "cancel scope" in msg or "different task" in msg:
                logger.debug("STDIO context teardown (known anyio quirk): %s", e)
            else:
                logger.warning(f"Error closing STDIO context: {e}")
        finally:
            conn.stdio_context = None

        try:
            if conn.sse_context:
                await conn.sse_context.__aexit__(None, None, None)
        except asyncio.CancelledError:
            logger.debug("SSE context cleanup was cancelled; proceeding with best-effort shutdown")
        except Exception as e:
            logger.warning(f"Error closing SSE context: {e}")
        finally:
            conn.sse_context = None

        # Third: close errlog file handle if we opened one
        if conn.errlog_handle is not None:
            try:
                conn.errlog_handle.close()
            except Exception as e:
                logger.debug(f"Error closing errlog handle: {e}")
            finally:
                conn.errlog_handle = None

    def disconnect(self) -> None:
        """Disconnect from the MCP server.

        DETACH-then-teardown: the current connection record is unpublished
        from ``self._conn`` first (under the lifecycle lock), then torn down
        as a free-standing object. Even if its loop thread outlives the join
        timeout, nothing shared remains for it to corrupt — a subsequent
        connect() builds a brand-new generation.
        """
        with self._lifecycle_lock:
            conn = self._conn
            self._conn = None
            self._connected = False

            if conn is not None:
                self._teardown_conn(conn)

            # Clean up HTTP client
            if self._http_client:
                self._http_client.close()
                self._http_client = None

        logger.info(f"Disconnected from MCP server '{self.config.name}'")

    def _teardown_conn(self, conn: _StdioConnection) -> None:
        """Tear down a DETACHED connection record (best effort).

        Also used to reap a generation whose connect() failed before it was
        ever published. Never raises.
        """
        loop = conn.loop
        if loop is not None:
            # Properly close session and context managers before stopping loop
            # Note: There's an inherent race condition between checking is_running()
            # and calling run_coroutine_threadsafe(). We handle this by catching
            # any exceptions that may occur if the loop stops between these calls.
            if loop.is_running():
                if conn.stop_event is not None and conn.cleanup_done is not None:
                    # Owner-coroutine teardown: signal the owner task to exit
                    # its OWN contexts (correct anyio task affinity), then
                    # wait for it to finish. This is the fix for the cross-task
                    # "exit cancel scope in a different task" leak.
                    try:
                        loop.call_soon_threadsafe(conn.stop_event.set)
                    except RuntimeError:
                        # Loop may have stopped between is_running() and here.
                        pass
                    if not conn.cleanup_done.wait(timeout=self._CLEANUP_TIMEOUT):
                        logger.warning(f"MCP STDIO owner teardown did not finish within {self._CLEANUP_TIMEOUT}s")
                else:
                    # Owner never reached its wait (startup raced/failed before
                    # stop_event existed): run cleanup as a one-shot coroutine.
                    try:
                        cleanup_future = asyncio.run_coroutine_threadsafe(self._cleanup_conn_async(conn), loop)
                        cleanup_future.result(timeout=self._CLEANUP_TIMEOUT)
                    except TimeoutError:
                        # Cleanup took too long - may indicate stuck resources or slow MCP server
                        logger.warning(f"Async cleanup timed out after {self._CLEANUP_TIMEOUT} seconds")
                    except RuntimeError as e:
                        # Likely: loop stopped between is_running() check and run_coroutine_threadsafe()
                        logger.debug(f"Event loop stopped during async cleanup: {e}")
                    except Exception as e:
                        # Cleanup was attempted but failed (e.g., error in _cleanup_conn_async())
                        logger.warning(f"Error during async cleanup: {e}")

                # Cancel any abandoned in-flight tasks BEFORE stopping the
                # loop, and stop only on the next pass so the cancellations
                # are actually delivered — otherwise their futures never
                # resolve and the worker threads blocked on future.result()
                # hang until the call-result ceiling.
                def _cancel_then_stop() -> None:
                    for task in asyncio.all_tasks(loop):
                        task.cancel()
                    loop.call_soon(loop.stop)

                try:
                    loop.call_soon_threadsafe(_cancel_then_stop)
                except RuntimeError:
                    # Loop may have already stopped
                    pass
            else:
                # Loop exists but is not running (e.g., crashed or stopped
                # externally). The contexts were created in the loop's thread
                # and may not be safely cleanable from here; the OS reclaims
                # the subprocess on exit.
                logger.warning(
                    "Event loop for STDIO MCP connection exists but is not running; skipping async cleanup. Resources may not be fully released."
                )

            # Wait for thread to finish (timeout proportional to cleanup timeout)
            if conn.loop_thread and conn.loop_thread.is_alive():
                conn.loop_thread.join(timeout=self._THREAD_JOIN_TIMEOUT)
                if conn.loop_thread.is_alive():
                    # Safe to abandon: the record is detached, so the straggler
                    # daemon thread can only touch its own generation's state.
                    logger.warning(
                        "Event loop thread for STDIO MCP connection did not terminate "
                        f"within {self._THREAD_JOIN_TIMEOUT}s; abandoning detached "
                        "connection record (daemon thread will drain on its own)."
                    )

    def probe_liveness(self, timeout: float = 5.0) -> bool:
        """Ping the server over the live session — is it actually dead?

        Used by the agent-side tool-timeout policy: a single slow call must
        not get the SHARED client force-disconnected (killing every other
        worker's tools) when the server is merely busy. MCP multiplexes
        requests over one session, and the gcu/FastMCP servers are async, so
        a ping is answered even while a slow tool runs; this deliberately
        bypasses the Windows call lock for the same reason.

        Returns True if the server answered the ping within ``timeout``.
        Tracks consecutive failures in ``consecutive_probe_failures`` so the
        caller can require two strikes before declaring death.
        """
        conn = self._conn
        if conn is None or conn.loop is None or conn.session is None:
            return False
        loop = conn.loop
        if not loop.is_running() or loop.is_closed():
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(conn.session.send_ping(), loop)
            future.result(timeout=timeout)
        except Exception:
            self._consecutive_probe_failures += 1
            return False
        self._consecutive_probe_failures = 0
        return True

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def inflight_calls(self) -> int:
        """Number of MCP calls currently blocked on this client's loop."""
        with self._inflight_lock:
            return self._inflight_calls

    @property
    def consecutive_probe_failures(self) -> int:
        return self._consecutive_probe_failures

    def lifecycle_busy(self) -> bool:
        """True while another thread holds connect/disconnect/reconnect."""
        acquired = self._lifecycle_lock.acquire(blocking=False)
        if acquired:
            self._lifecycle_lock.release()
            return False
        return True

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
