"""Integration tests for the MCP client over HTTP transport.

These tests start a real FastMCP server in-process and connect to it
via the Streamable HTTP transport to verify end-to-end functionality.

Requires: mcp, fastmcp packages installed.
"""

import socket
import threading
import time

import pytest
import uvicorn
from anyio import ClosedResourceError

from framework.runner.mcp_client import MCPClient, MCPServerConfig


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mcp_http_server():
    """Start a FastMCP server with test tools on a random port.

    Yields the base URL (e.g. http://127.0.0.1:PORT).
    Server runs in a daemon thread and dies with the test process.
    """
    from fastmcp import FastMCP

    mcp = FastMCP("test-tools")

    @mcp.tool()
    def echo(message: str) -> str:
        """Echo a message back."""
        return f"echo: {message}"

    @mcp.tool()
    def add(a: int, b: int) -> str:
        """Add two numbers."""
        return str(a + b)

    port = _find_free_port()

    # Use uvicorn directly for more control over server lifecycle
    app = mcp.http_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to be ready
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    else:
        pytest.fail(f"Server failed to start on port {port}")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True


class TestHTTPRoundtrip:
    """Test full connect → discover → call → disconnect cycle over HTTP."""

    def test_connect_and_list_tools(self, mcp_http_server):
        """Connect to HTTP MCP server and discover tools."""
        config = MCPServerConfig(
            name="test",
            transport="http",
            url=mcp_http_server,
        )
        with MCPClient(config) as client:
            tools = client.list_tools()
            tool_names = {t.name for t in tools}
            assert "echo" in tool_names
            assert "add" in tool_names

    def test_call_echo_tool(self, mcp_http_server):
        """Call the echo tool and verify the response."""
        config = MCPServerConfig(
            name="test",
            transport="http",
            url=mcp_http_server,
        )
        with MCPClient(config) as client:
            result = client.call_tool("echo", {"message": "hello world"})
            assert result == "echo: hello world"

    def test_call_add_tool(self, mcp_http_server):
        """Call the add tool and verify the response."""
        config = MCPServerConfig(
            name="test",
            transport="http",
            url=mcp_http_server,
        )
        with MCPClient(config) as client:
            result = client.call_tool("add", {"a": 3, "b": 7})
            assert result == "10"

    def test_multiple_tool_calls(self, mcp_http_server):
        """Call multiple tools in sequence on the same persistent connection."""
        config = MCPServerConfig(
            name="test",
            transport="http",
            url=mcp_http_server,
        )
        with MCPClient(config) as client:
            r1 = client.call_tool("echo", {"message": "first"})
            r2 = client.call_tool("add", {"a": 1, "b": 2})
            r3 = client.call_tool("echo", {"message": "third"})

            assert r1 == "echo: first"
            assert r2 == "3"
            assert r3 == "echo: third"


class TestHTTPWithHeaders:
    """Test that custom headers are passed through."""

    def test_custom_headers_dont_break_connection(self, mcp_http_server):
        """Custom headers should be sent without breaking the connection."""
        config = MCPServerConfig(
            name="test",
            transport="http",
            url=mcp_http_server,
            headers={"X-Custom-Header": "test-value"},
        )
        with MCPClient(config) as client:
            tools = client.list_tools()
            assert len(tools) > 0


class TestHTTPDisconnectReconnect:
    """Test disconnect and reconnect cycle."""

    def test_disconnect_and_reconnect(self, mcp_http_server):
        """Client should be able to disconnect and reconnect."""
        config = MCPServerConfig(
            name="test",
            transport="http",
            url=mcp_http_server,
        )

        client = MCPClient(config)
        client.connect()
        tools_first = client.list_tools()
        assert len(tools_first) > 0

        client.disconnect()
        assert client._connected is False

        # Reconnect
        client.connect()
        tools_second = client.list_tools()
        assert len(tools_second) == len(tools_first)

        client.disconnect()


class TestHTTPConnectionFailure:
    """Test behavior when server is unreachable."""

    def test_connection_to_unreachable_server(self):
        """Connecting to unreachable server should raise an error."""
        port = _find_free_port()
        config = MCPServerConfig(
            name="test",
            transport="http",
            url=f"http://127.0.0.1:{port}",
        )
        client = MCPClient(config)

        # The error may surface during connection init or tool discovery,
        # depending on when the transport detects the unreachable server.
        with pytest.raises((RuntimeError, OSError, ClosedResourceError)):
            client.connect()
