import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from framework.llm.litellm import LiteLLMProvider, _LLM_CIRCUIT_BREAKERS
from framework.loader.mcp_client import MCPClient, MCPServerConfig, _MCP_CIRCUIT_BREAKERS
from framework.utils.circuit_breaker import CircuitOpenError, CircuitState, CircuitBreaker
import httpx

try:
    import litellm
    from litellm.exceptions import InternalServerError, BadRequestError, ServiceUnavailableError
except ImportError:
    # Mock exceptions for integration testing if litellm is not installed
    class MockLiteLLMException(Exception):
        def __init__(self, message=None, model=None, llm_provider=None):
            super().__init__(message)
            self.model = model
            self.llm_provider = llm_provider

    InternalServerError = type("InternalServerError", (MockLiteLLMException,), {})
    BadRequestError = type("BadRequestError", (MockLiteLLMException,), {})
    ServiceUnavailableError = type("ServiceUnavailableError", (MockLiteLLMException,), {})
    litellm = MagicMock()

@pytest.fixture(autouse=True)
def clear_breakers():
    """Clear global breaker registries before each test."""
    _LLM_CIRCUIT_BREAKERS.clear()
    _MCP_CIRCUIT_BREAKERS.clear()

class TestLiteLLMIntegration:
    @patch("framework.llm.litellm.litellm")
    def test_litellm_provider_trips_breaker(self, mock_litellm):
        """Verify that LiteLLMProvider trips the breaker after 5 errors."""
        # Use ConnectionError as it's always in _get_transient_types()
        mock_litellm.completion.side_effect = ConnectionError("Connection reset by peer")
        
        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test")
        
        # Default failure_threshold is 5
        for _ in range(5):
            with pytest.raises(ConnectionError):
                provider.complete(messages=[{"role": "user", "content": "hi"}])
        
        # 6th call should fail immediately with CircuitOpenError
        with pytest.raises(CircuitOpenError) as excinfo:
            provider.complete(messages=[{"role": "user", "content": "hi"}])
        
        assert excinfo.value.breaker_name == "llm:gpt-4o-mini"
        assert mock_litellm.completion.call_count == 5

    @patch("framework.llm.litellm.litellm")
    def test_litellm_provider_ignores_unmonitored_exception(self, mock_litellm):
        """Verify that exceptions NOT in transient types do NOT trip the breaker."""
        # ValueError is not in (TimeoutError, ConnectionError, OSError) when litellm is missing
        mock_litellm.completion.side_effect = ValueError("Invalid prompt")
        
        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test")
        
        # 10 failures should NOT trip it
        for _ in range(10):
            with pytest.raises(ValueError):
                provider.complete(messages=[{"role": "user", "content": "hi"}])
        
        # 11th call still reaches litellm (mock_litellm.completion)
        with pytest.raises(ValueError):
            provider.complete(messages=[{"role": "user", "content": "hi"}])
        
        assert mock_litellm.completion.call_count == 11

    @pytest.mark.asyncio
    @patch("framework.llm.litellm.litellm")
    async def test_litellm_provider_async_trips_breaker(self, mock_litellm):
        """Verify async acompletion also trips the breaker."""
        mock_litellm.acompletion = AsyncMock(side_effect=TimeoutError("Request timed out"))
        
        provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test")
        
        for _ in range(5):
            with pytest.raises(TimeoutError):
                await provider.acomplete(messages=[{"role": "user", "content": "hi"}])
                
        with pytest.raises(CircuitOpenError):
            await provider.acomplete(messages=[{"role": "user", "content": "hi"}])

class TestMCPIntegration:
    def test_mcp_client_trips_breaker(self):
        """Verify MCPClient trips its breaker on transport errors."""
        config = MCPServerConfig(name="MockServer", transport="stdio", command="node")
        client = MCPClient(config)
        client._connected = True
        # Mock tool list
        client._tools = {"test_tool": MagicMock()}
        
        # Mock the tool call to fail with ConnectionError (monitored for MCP)
        with patch.object(client, "_run_async") as mock_run, \
             patch.object(client, "_reconnect") as mock_reconn:
            mock_run.side_effect = ConnectionError("Broken Pipe")
            
            for _ in range(5):
                with pytest.raises(ConnectionError):
                    client.call_tool("test_tool", {})
            
            # 6th call
            with pytest.raises(CircuitOpenError) as excinfo:
                client.call_tool("test_tool", {})
            
            assert excinfo.value.breaker_name == "mcp:mockserver"

    def test_mcp_client_different_servers_separate_breakers(self):
        """Verify each MCP server has its own isolated breaker."""
        c1 = MCPServerConfig(name="ServerA", transport="stdio", command="node")
        c2 = MCPServerConfig(name="ServerB", transport="stdio", command="node")
        
        client1 = MCPClient(c1)
        client1._connected = True
        client1._tools = {"t1": MagicMock()}
        
        client2 = MCPClient(c2)
        client2._connected = True
        client2._tools = {"t2": MagicMock()}

        with patch.object(client1, "_run_async", side_effect=ConnectionError("Fail A")), \
             patch.object(client1, "_reconnect"):
            for _ in range(5):
                with pytest.raises(ConnectionError):
                    client1.call_tool("t1", {})
        
        # Breaker A is OPEN
        with pytest.raises(CircuitOpenError):
            client1.call_tool("t1", {})
            
        # Breaker B should still be CLOSED (isolated)
        with patch.object(client2, "_run_async", return_value="success B"):
            result = client2.call_tool("t2", {})
            assert result == "success B"
