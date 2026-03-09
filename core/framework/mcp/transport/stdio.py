"""STDIO MCP transport implementation using official SDK session primitives."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
from typing import Any

from framework.mcp.errors import MCPTransportError
from framework.mcp.models import MCPServerConfig
from framework.mcp.transport.base import MCPTransport

logger = logging.getLogger(__name__)


class StdioMCPTransport(MCPTransport):
    """Persistent STDIO transport for MCP servers."""

    _CLEANUP_TIMEOUT = 10
    _THREAD_JOIN_TIMEOUT = 12

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._session = None
        self._read_stream = None
        self._write_stream = None
        self._stdio_context = None
        self._loop = None
        self._loop_thread = None
        self._stdio_call_lock = threading.Lock()

    def _run_async(self, coro):
        if self._loop is not None and self._loop.is_running() and not self._loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result()

        try:
            asyncio.get_running_loop()
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
            return asyncio.run(coro)

    def connect(self) -> None:
        if not self.config.command:
            raise ValueError("command is required for STDIO transport")

        try:
            from mcp import StdioServerParameters

            merged_env = {**os.environ, **(self.config.env or {})}
            cwd = self.config.cwd
            if os.name == "nt" and cwd is not None:
                cwd = None
            server_params = StdioServerParameters(
                command=self.config.command,
                args=self.config.args,
                env=merged_env,
                cwd=cwd,
            )

            loop_started = threading.Event()
            connection_ready = threading.Event()
            connection_error: list[Exception] = []

            def run_event_loop():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                loop_started.set()

                async def init_connection():
                    try:
                        from mcp import ClientSession
                        from mcp.client.stdio import stdio_client

                        errlog = (
                            sys.stderr
                            if os.name == "nt"
                            else open(os.devnull, "w")  # noqa: SIM115
                        )
                        self._stdio_context = stdio_client(server_params, errlog=errlog)
                        self._read_stream, self._write_stream = (
                            await self._stdio_context.__aenter__()
                        )
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
                raise MCPTransportError("Event loop failed to start")

            connection_ready.wait(timeout=10)
            if connection_error:
                raise connection_error[0]

            logger.info("Connected to MCP server '%s' via STDIO (persistent)", self.config.name)
        except Exception as e:
            raise MCPTransportError(f"Failed to connect to MCP server: {e}") from e

    async def _list_tools_async(self) -> list[dict[str, Any]]:
        if not self._session:
            raise MCPTransportError("STDIO session not initialized")

        response = await self._session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
            }
            for tool in response.tools
        ]

    def list_tools(self) -> list[dict[str, Any]]:
        return self._run_async(self._list_tools_async())

    async def _call_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if not self._session:
            raise MCPTransportError("STDIO session not initialized")

        result = await self._session.call_tool(tool_name, arguments=arguments)
        if getattr(result, "isError", False):
            error_text = ""
            if result.content:
                content_item = result.content[0]
                if hasattr(content_item, "text"):
                    error_text = content_item.text
            raise MCPTransportError(f"MCP tool '{tool_name}' failed: {error_text}")

        if result.content:
            if len(result.content) > 0:
                item = result.content[0]
                if hasattr(item, "text"):
                    return item.text
                if hasattr(item, "data"):
                    return item.data
            return result.content
        return None

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        with self._stdio_call_lock:
            return self._run_async(self._call_tool_async(tool_name, arguments))

    async def _cleanup_stdio_async(self) -> None:
        try:
            if self._session:
                await self._session.__aexit__(None, None, None)
        except asyncio.CancelledError:
            logger.warning(
                "MCP session cleanup was cancelled; proceeding with best-effort shutdown"
            )
        except Exception as e:
            logger.warning("Error closing MCP session: %s", e)
        finally:
            self._session = None

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
                logger.warning("Error closing STDIO context: %s", e)
        finally:
            self._stdio_context = None

    def disconnect(self) -> None:
        if self._loop is not None:
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
                    logger.warning(
                        "Async cleanup timed out after %s seconds",
                        self._CLEANUP_TIMEOUT,
                    )
                except RuntimeError as e:
                    cleanup_attempted = True
                    logger.debug("Event loop stopped during async cleanup: %s", e)
                except Exception as e:
                    cleanup_attempted = True
                    logger.warning("Error during async cleanup: %s", e)

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
                        "within %ss; thread may still be running.",
                        self._THREAD_JOIN_TIMEOUT,
                    )

            self._session = None
            self._stdio_context = None
            self._read_stream = None
            self._write_stream = None
            self._loop = None
            self._loop_thread = None
