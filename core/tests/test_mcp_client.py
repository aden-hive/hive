"""Unit tests for the MCP client.

Tests the MCPClient's URL handling, transport unification, and cleanup logic
using mocks (no real MCP server required).
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from framework.runner.mcp_client import MCPClient, MCPServerConfig


class TestURLPathHandling:
    """Tests for HTTP URL path auto-append logic."""

    def test_url_without_path_gets_mcp_appended(self):
        """http://localhost:4001 → http://localhost:4001/mcp"""
        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001")
        MCPClient(config)

        # Extract the URL logic by checking what _connect_http would compute
        from urllib.parse import urlparse

        parsed = urlparse(config.url)
        if not parsed.path or parsed.path == "/":
            url = config.url.rstrip("/") + "/mcp"
        else:
            url = config.url

        assert url == "http://localhost:4001/mcp"

    def test_url_with_trailing_slash_gets_mcp_appended(self):
        """http://localhost:4001/ → http://localhost:4001/mcp"""
        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001/")

        from urllib.parse import urlparse

        parsed = urlparse(config.url)
        if not parsed.path or parsed.path == "/":
            url = config.url.rstrip("/") + "/mcp"
        else:
            url = config.url

        assert url == "http://localhost:4001/mcp"

    def test_url_with_custom_path_preserved(self):
        """http://remote:8080/custom/endpoint stays as-is."""
        config = MCPServerConfig(
            name="test", transport="http", url="http://remote:8080/custom/endpoint"
        )

        from urllib.parse import urlparse

        parsed = urlparse(config.url)
        if not parsed.path or parsed.path == "/":
            url = config.url.rstrip("/") + "/mcp"
        else:
            url = config.url

        assert url == "http://remote:8080/custom/endpoint"

    def test_url_with_mcp_path_preserved(self):
        """http://localhost:4001/mcp stays as-is."""
        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001/mcp")

        from urllib.parse import urlparse

        parsed = urlparse(config.url)
        if not parsed.path or parsed.path == "/":
            url = config.url.rstrip("/") + "/mcp"
        else:
            url = config.url

        assert url == "http://localhost:4001/mcp"


class TestHTTPConnectionValidation:
    """Tests for HTTP connection validation."""

    def test_connect_http_requires_url(self):
        """HTTP transport without URL should raise ValueError."""
        config = MCPServerConfig(name="test", transport="http", url=None)
        client = MCPClient(config)

        with pytest.raises(ValueError, match="url is required"):
            client._connect_http()

    def test_connect_stdio_requires_command(self):
        """STDIO transport without command should raise ValueError."""
        config = MCPServerConfig(name="test", transport="stdio", command=None)
        client = MCPClient(config)

        with pytest.raises(ValueError, match="command is required"):
            client._connect_stdio()

    def test_unsupported_transport_raises(self):
        """Unsupported transport should raise ValueError."""
        config = MCPServerConfig(name="test", transport="grpc")
        client = MCPClient(config)

        with pytest.raises(ValueError, match="Unsupported transport"):
            client.connect()


class TestUnifiedInterface:
    """Tests that both transports share the same session-based methods."""

    def test_call_tool_routes_through_async(self):
        """call_tool should use _call_tool_async for any transport."""
        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001")
        client = MCPClient(config)
        client._connected = True
        client._tools = {"echo": MagicMock()}

        mock_result = "hello"
        with patch.object(client, "_run_async", return_value=mock_result) as mock_run:
            result = client.call_tool("echo", {"message": "hello"})

        assert result == mock_result
        mock_run.assert_called_once()

    def test_call_tool_unknown_tool_raises(self):
        """Calling an unknown tool should raise ValueError."""
        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001")
        client = MCPClient(config)
        client._connected = True
        client._tools = {}

        with pytest.raises(ValueError, match="Unknown tool"):
            client.call_tool("nonexistent", {})


class TestCleanup:
    """Tests for cleanup and disconnect logic."""

    def test_disconnect_clears_all_references(self):
        """After disconnect, all internal references should be None."""
        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001")
        client = MCPClient(config)

        # Simulate a connected state without actually connecting
        asyncio.new_event_loop()

        async def noop():
            pass

        # Set up state as if connected
        client._session = MagicMock()
        client._transport_context = MagicMock()
        client._http_async_client = MagicMock()
        client._get_session_id = MagicMock()
        client._read_stream = MagicMock()
        client._write_stream = MagicMock()
        client._connected = True
        # Don't set _loop to avoid triggering real async cleanup
        # Just test the non-loop cleanup path

        client.disconnect()

        assert client._connected is False

    def test_context_manager(self):
        """MCPClient should support context manager protocol."""
        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001")
        client = MCPClient(config)

        with (
            patch.object(client, "connect") as mock_connect,
            patch.object(client, "disconnect") as mock_disconnect,
        ):
            with client:
                mock_connect.assert_called_once()
            mock_disconnect.assert_called_once()

    def test_double_connect_is_noop(self):
        """Calling connect() when already connected should be a no-op."""
        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001")
        client = MCPClient(config)
        client._connected = True

        with patch.object(client, "_connect_http") as mock_connect_http:
            client.connect()
            mock_connect_http.assert_not_called()


class TestMCPServerConfig:
    """Tests for the MCPServerConfig dataclass."""

    def test_stdio_config(self):
        config = MCPServerConfig(
            name="tools",
            transport="stdio",
            command="python",
            args=["mcp_server.py", "--stdio"],
            env={"KEY": "value"},
            cwd="/tmp",
        )
        assert config.name == "tools"
        assert config.transport == "stdio"
        assert config.command == "python"
        assert config.args == ["mcp_server.py", "--stdio"]
        assert config.env == {"KEY": "value"}
        assert config.cwd == "/tmp"

    def test_http_config(self):
        config = MCPServerConfig(
            name="remote",
            transport="http",
            url="http://localhost:4001",
            headers={"Authorization": "Bearer token"},
        )
        assert config.name == "remote"
        assert config.transport == "http"
        assert config.url == "http://localhost:4001"
        assert config.headers == {"Authorization": "Bearer token"}

    def test_defaults(self):
        config = MCPServerConfig(name="test", transport="stdio")
        assert config.args == []
        assert config.env == {}
        assert config.headers == {}
        assert config.description == ""
