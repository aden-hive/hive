"""Tests for the MCP Client module.

Tests for transport extensions including Unix socket, SSE, and retry/reconnect logic.
"""

from unittest.mock import patch

import pytest

from framework.runner.mcp_client import MCPClient, MCPServerConfig, MCPTool


class TestMCPServerConfig:
    """Tests for MCPServerConfig dataclass."""

    def test_stdio_transport_config(self):
        """Test STDIO transport configuration."""
        config = MCPServerConfig(
            name="test-stdio",
            transport="stdio",
            command="python",
            args=["-m", "mcp_server"],
        )
        assert config.transport == "stdio"
        assert config.command == "python"
        assert config.args == ["-m", "mcp_server"]

    def test_http_transport_config(self):
        """Test HTTP transport configuration."""
        config = MCPServerConfig(
            name="test-http",
            transport="http",
            url="http://localhost:8080",
        )
        assert config.transport == "http"
        assert config.url == "http://localhost:8080"

    def test_unix_transport_config(self):
        """Test Unix socket transport configuration."""
        config = MCPServerConfig(
            name="test-unix",
            transport="unix",
            socket_path="/tmp/mcp.sock",
            headers={"Authorization": "Bearer token"},
        )
        assert config.transport == "unix"
        assert config.socket_path == "/tmp/mcp.sock"
        assert config.headers == {"Authorization": "Bearer token"}

    def test_sse_transport_config(self):
        """Test SSE transport configuration."""
        config = MCPServerConfig(
            name="test-sse",
            transport="sse",
            url="http://localhost:8080/sse",
            sse_read_timeout=600.0,
        )
        assert config.transport == "sse"
        assert config.url == "http://localhost:8080/sse"
        assert config.sse_read_timeout == 600.0

    def test_sse_read_timeout_default(self):
        """Test SSE read timeout default value."""
        config = MCPServerConfig(
            name="test-sse-default",
            transport="sse",
            url="http://localhost:8080/sse",
        )
        assert config.sse_read_timeout == 300.0

    def test_headers_default_empty_dict(self):
        """Test that headers default to empty dict."""
        config = MCPServerConfig(
            name="test",
            transport="http",
            url="http://localhost:8080",
        )
        assert config.headers == {}


class TestMCPTool:
    """Tests for MCPTool dataclass."""

    def test_mcp_tool_creation(self):
        """Test MCPTool creation."""
        tool = MCPTool(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object"},
            server_name="test-server",
        )
        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert tool.input_schema == {"type": "object"}
        assert tool.server_name == "test-server"


class TestMCPClient:
    """Tests for MCPClient class."""

    def test_client_initialization_stdio(self):
        """Test MCPClient initialization with STDIO transport."""
        config = MCPServerConfig(
            name="test-stdio",
            transport="stdio",
            command="python",
        )
        client = MCPClient(config)
        assert client.config == config
        assert client._connected is False
        assert client._session is None
        assert client._http_client is None

    def test_client_initialization_http(self):
        """Test MCPClient initialization with HTTP transport."""
        config = MCPServerConfig(
            name="test-http",
            transport="http",
            url="http://localhost:8080",
        )
        client = MCPClient(config)
        assert client.config == config
        assert client._connected is False

    def test_client_initialization_unix(self):
        """Test MCPClient initialization with Unix socket transport."""
        config = MCPServerConfig(
            name="test-unix",
            transport="unix",
            socket_path="/tmp/mcp.sock",
        )
        client = MCPClient(config)
        assert client.config == config
        assert client._connected is False
        assert client._sse_context is None

    def test_client_initialization_sse(self):
        """Test MCPClient initialization with SSE transport."""
        config = MCPServerConfig(
            name="test-sse",
            transport="sse",
            url="http://localhost:8080/sse",
        )
        client = MCPClient(config)
        assert client.config == config
        assert client._connected is False
        assert client._sse_context is None
        assert client._sse_endpoint_url is None

    def test_connect_unsupported_transport_raises_error(self):
        """Test that unsupported transport raises ValueError."""
        config = MCPServerConfig(
            name="test",
            transport="stdio",
            command="python",
        )
        client = MCPClient(config)
        client.config.transport = "invalid"  # type: ignore

        with pytest.raises(ValueError, match="Unsupported transport"):
            client.connect()


class TestMCPClientUnixTransport:
    """Tests for Unix socket transport in MCPClient."""

    def test_connect_unix_missing_socket_path_raises_error(self):
        """Test that missing socket_path raises ValueError."""
        config = MCPServerConfig(
            name="test-unix",
            transport="unix",
            socket_path=None,
        )
        client = MCPClient(config)

        with pytest.raises(ValueError, match="socket_path is required"):
            client._connect_unix()


class TestMCPClientSSETransport:
    """Tests for SSE transport in MCPClient."""

    def test_connect_sse_missing_url_raises_error(self):
        """Test that missing URL raises ValueError for SSE transport."""
        config = MCPServerConfig(
            name="test-sse",
            transport="sse",
            url=None,
        )
        client = MCPClient(config)

        with pytest.raises(ValueError, match="url is required"):
            client._connect_sse()


class TestMCPClientRetryLogic:
    """Tests for retry/reconnect logic in MCPClient."""

    def test_call_tool_unknown_raises_error(self):
        """Test that calling unknown tool raises ValueError."""
        config = MCPServerConfig(
            name="test-http",
            transport="http",
            url="http://localhost:8080",
        )
        client = MCPClient(config)
        client._connected = True
        client._tools = {}

        with pytest.raises(ValueError, match="Unknown tool"):
            client.call_tool("unknown_tool", {})

    def test_reconnect_http(self):
        """Test reconnect method for HTTP transport."""
        config = MCPServerConfig(
            name="test-http",
            transport="http",
            url="http://localhost:8080",
        )
        client = MCPClient(config)
        client._connected = True
        client._http_client = None

        with patch.object(client, "_connect_http") as mock_connect:
            with patch.object(client, "_discover_tools"):
                client._reconnect()

        mock_connect.assert_called_once()
        assert client._connected is True

    def test_reconnect_unix(self):
        """Test reconnect method for Unix transport."""
        config = MCPServerConfig(
            name="test-unix",
            transport="unix",
            socket_path="/tmp/mcp.sock",
        )
        client = MCPClient(config)
        client._connected = True
        client._http_client = None

        with patch.object(client, "_connect_unix") as mock_connect:
            with patch.object(client, "_discover_tools"):
                client._reconnect()

        mock_connect.assert_called_once()
        assert client._connected is True

    def test_reconnect_sse(self):
        """Test reconnect method for SSE transport."""
        config = MCPServerConfig(
            name="test-sse",
            transport="sse",
            url="http://localhost:8080/sse",
        )
        client = MCPClient(config)
        client._connected = True

        with patch.object(client, "_cleanup_sse") as mock_cleanup:
            with patch.object(client, "_connect_sse") as mock_connect:
                with patch.object(client, "_discover_tools"):
                    client._reconnect()

        mock_cleanup.assert_called_once()
        mock_connect.assert_called_once()
        assert client._connected is True


class TestMCPClientDisconnect:
    """Tests for disconnect behavior."""

    def test_disconnect_http_client(self):
        """Test that HTTP client is properly closed on disconnect."""
        import httpx

        config = MCPServerConfig(
            name="test-http",
            transport="http",
            url="http://localhost:8080",
        )
        client = MCPClient(config)
        client._http_client = httpx.Client()
        client._connected = True

        client.disconnect()

        assert client._http_client is None
        assert client._connected is False

    def test_disconnect_clears_state(self):
        """Test that disconnect clears client state."""
        config = MCPServerConfig(
            name="test-http",
            transport="http",
            url="http://localhost:8080",
        )
        client = MCPClient(config)
        client._connected = True

        client.disconnect()

        assert client._connected is False


class TestMCPClientContextManager:
    """Tests for context manager protocol."""

    def test_context_manager_enter_connects(self):
        """Test that entering context manager connects."""
        config = MCPServerConfig(
            name="test-http",
            transport="http",
            url="http://localhost:8080",
        )
        client = MCPClient(config)

        with patch.object(client, "connect") as mock_connect:
            with patch.object(client, "disconnect"):
                with client as c:
                    assert c is client
                    mock_connect.assert_called_once()

    def test_context_manager_exit_disconnects(self):
        """Test that exiting context manager disconnects."""
        config = MCPServerConfig(
            name="test-http",
            transport="http",
            url="http://localhost:8080",
        )
        client = MCPClient(config)

        with patch.object(client, "connect"):
            with patch.object(client, "disconnect") as mock_disconnect:
                with client:
                    pass
                mock_disconnect.assert_called_once()
