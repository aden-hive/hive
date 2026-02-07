"""
Tests for MCP client timeout protection.

Verifies that MCPClient enforces configurable timeouts on tool calls
for both STDIO and HTTP transports, preventing indefinite blocking
when tool servers hang.

Relates to: https://github.com/adenhq/hive/issues/3440
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from framework.runner.mcp_client import (
    DEFAULT_TOOL_TIMEOUT,
    MCPClient,
    MCPServerConfig,
    MCPTool,
    MCPToolTimeoutError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stdio_config():
    """STDIO server config with a short timeout for testing."""
    return MCPServerConfig(
        name="test-stdio",
        transport="stdio",
        command="python",
        args=["-m", "fake_server"],
        tool_timeout=0.5,
    )


@pytest.fixture
def http_config():
    """HTTP server config with a short timeout for testing."""
    return MCPServerConfig(
        name="test-http",
        transport="http",
        url="http://localhost:9999",
        tool_timeout=0.5,
    )


@pytest.fixture
def no_timeout_config():
    """STDIO server config with timeout disabled."""
    return MCPServerConfig(
        name="test-no-timeout",
        transport="stdio",
        command="python",
        args=["-m", "fake_server"],
        tool_timeout=None,
    )


# ---------------------------------------------------------------------------
# MCPToolTimeoutError tests
# ---------------------------------------------------------------------------


class TestMCPToolTimeoutError:
    """Tests for the MCPToolTimeoutError exception."""

    def test_inherits_from_timeout_error(self):
        err = MCPToolTimeoutError("my_tool", 30.0)
        assert isinstance(err, TimeoutError)

    def test_attributes(self):
        err = MCPToolTimeoutError("web_search", 15.0)
        assert err.tool_name == "web_search"
        assert err.timeout == 15.0
        assert err.error_type == "timeout"

    def test_message(self):
        err = MCPToolTimeoutError("slow_tool", 5.0)
        assert "slow_tool" in str(err)
        assert "5.0s" in str(err)


# ---------------------------------------------------------------------------
# MCPServerConfig default timeout
# ---------------------------------------------------------------------------


class TestMCPServerConfigTimeout:
    """Tests for the tool_timeout field on MCPServerConfig."""

    def test_default_timeout(self):
        config = MCPServerConfig(name="s", transport="stdio", command="echo")
        assert config.tool_timeout == DEFAULT_TOOL_TIMEOUT

    def test_custom_timeout(self):
        config = MCPServerConfig(name="s", transport="stdio", command="echo", tool_timeout=60.0)
        assert config.tool_timeout == 60.0

    def test_disable_timeout(self):
        config = MCPServerConfig(name="s", transport="stdio", command="echo", tool_timeout=None)
        assert config.tool_timeout is None


# ---------------------------------------------------------------------------
# STDIO timeout tests
# ---------------------------------------------------------------------------


class TestSTDIOToolTimeout:
    """Tests for timeout behaviour on STDIO transport."""

    def test_stdio_tool_call_timeout_raises(self, stdio_config):
        """A hanging STDIO tool call should raise MCPToolTimeoutError."""
        client = MCPClient(stdio_config)

        # Pretend we're connected with a known tool
        client._connected = True
        client._tools = {
            "slow_tool": MCPTool(
                name="slow_tool",
                description="a slow tool",
                input_schema={},
                server_name="test-stdio",
            )
        }

        # Simulate a hanging session.call_tool
        async def hang_forever(*args, **kwargs):
            await asyncio.sleep(999)

        mock_session = MagicMock()
        mock_session.call_tool = hang_forever
        client._session = mock_session

        # Set up a real event loop for the STDIO path
        import threading

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        client._loop = loop
        client._loop_thread = thread

        try:
            with pytest.raises(MCPToolTimeoutError) as exc_info:
                client.call_tool("slow_tool", {"query": "test"})

            assert exc_info.value.tool_name == "slow_tool"
            assert exc_info.value.error_type == "timeout"
            assert exc_info.value.timeout == 0.5
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)

    def test_stdio_tool_call_succeeds_within_timeout(self, stdio_config):
        """A fast STDIO tool call should return normally."""
        client = MCPClient(stdio_config)
        client._connected = True
        client._tools = {
            "fast_tool": MCPTool(
                name="fast_tool",
                description="a fast tool",
                input_schema={},
                server_name="test-stdio",
            )
        }

        # Build a mock result object
        mock_content = MagicMock()
        mock_content.text = "result_data"
        mock_result = MagicMock()
        mock_result.isError = False
        mock_result.content = [mock_content]

        async def fast_call(*args, **kwargs):
            return mock_result

        mock_session = MagicMock()
        mock_session.call_tool = fast_call
        client._session = mock_session

        import threading

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        client._loop = loop
        client._loop_thread = thread

        try:
            result = client.call_tool("fast_tool", {"query": "test"})
            assert result == "result_data"
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)

    def test_stdio_no_timeout_does_not_raise(self, no_timeout_config):
        """When tool_timeout is None, no timeout should be applied."""
        client = MCPClient(no_timeout_config)
        client._connected = True
        client._tools = {
            "tool": MCPTool(
                name="tool",
                description="",
                input_schema={},
                server_name="test-no-timeout",
            )
        }

        mock_content = MagicMock()
        mock_content.text = "ok"
        mock_result = MagicMock()
        mock_result.isError = False
        mock_result.content = [mock_content]

        async def slow_but_ok(*args, **kwargs):
            await asyncio.sleep(0.1)
            return mock_result

        mock_session = MagicMock()
        mock_session.call_tool = slow_but_ok
        client._session = mock_session

        import threading

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        client._loop = loop
        client._loop_thread = thread

        try:
            result = client.call_tool("tool", {})
            assert result == "ok"
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)


# ---------------------------------------------------------------------------
# HTTP timeout tests
# ---------------------------------------------------------------------------


class TestHTTPToolTimeout:
    """Tests for timeout behaviour on HTTP transport."""

    def test_http_tool_call_timeout_raises(self, http_config):
        """A hanging HTTP tool call should raise MCPToolTimeoutError."""
        client = MCPClient(http_config)
        client._connected = True
        client._tools = {
            "slow_http_tool": MCPTool(
                name="slow_http_tool",
                description="",
                input_schema={},
                server_name="test-http",
            )
        }

        import httpx

        mock_http = MagicMock()
        mock_http.post.side_effect = httpx.TimeoutException("read timed out")
        client._http_client = mock_http

        with pytest.raises(MCPToolTimeoutError) as exc_info:
            client.call_tool("slow_http_tool", {"key": "val"})

        assert exc_info.value.tool_name == "slow_http_tool"
        assert exc_info.value.error_type == "timeout"

    def test_http_tool_call_passes_timeout_to_request(self, http_config):
        """HTTP tool calls should forward the configured timeout to httpx."""
        client = MCPClient(http_config)
        client._connected = True
        client._tools = {
            "tool": MCPTool(
                name="tool",
                description="",
                input_schema={},
                server_name="test-http",
            )
        }

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"content": ["data"]}}
        mock_response.raise_for_status = MagicMock()

        mock_http = MagicMock()
        mock_http.post.return_value = mock_response
        client._http_client = mock_http

        client.call_tool("tool", {"a": 1})

        # Verify the timeout was passed to the post call
        call_kwargs = mock_http.post.call_args
        assert call_kwargs.kwargs.get("timeout") == 0.5

    def test_http_tool_call_succeeds_within_timeout(self, http_config):
        """A fast HTTP tool call should return normally."""
        client = MCPClient(http_config)
        client._connected = True
        client._tools = {
            "tool": MCPTool(
                name="tool",
                description="",
                input_schema={},
                server_name="test-http",
            )
        }

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"content": ["success"]}}
        mock_response.raise_for_status = MagicMock()

        mock_http = MagicMock()
        mock_http.post.return_value = mock_response
        client._http_client = mock_http

        result = client.call_tool("tool", {})
        assert result == ["success"]
