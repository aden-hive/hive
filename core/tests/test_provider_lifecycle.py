"""Tests for LLMProvider lifecycle management."""

import pytest
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolUse, ToolResult
from framework.llm.litellm import LiteLLMProvider
from framework.llm.anthropic import AnthropicProvider
from framework.llm.mock import MockLLMProvider
from unittest.mock import AsyncMock, patch

class LifecycleTestProvider(LLMProvider):
    """Test provider to verify lifecycle methods."""
    
    def __init__(self):
        self.closed = False
        
    async def close(self):
        self.closed = True
        
    def complete(self, messages, **kwargs):
        pass
        
    def complete_with_tools(self, **kwargs):
        pass

@pytest.mark.asyncio
async def test_lifecycle_context_manager():
    """Test that context manager calls close()."""
    provider = LifecycleTestProvider()
    
    async with provider as p:
        assert p is provider
        assert not provider.closed
        
    assert provider.closed

@pytest.mark.asyncio
async def test_litellm_lifecycle():
    """Test LiteLLMProvider lifecycle."""
    provider = LiteLLMProvider(model="gpt-4o-mini", api_key="test")
    # Should not raise exception
    async with provider:
        pass
    
    # Verify close can be called manually
    await provider.close()

@pytest.mark.asyncio
async def test_anthropic_lifecycle():
    """Test AnthropicProvider delegates cleanup."""
    with patch("framework.llm.anthropic.LiteLLMProvider") as mock_litellm_cls:
        # returns an async mock instance
        mock_instance = AsyncMock(spec=LiteLLMProvider)
        mock_litellm_cls.return_value = mock_instance
        
        provider = AnthropicProvider(api_key="test")
        
        async with provider:
            pass
            
        # Verify result
        mock_instance.close.assert_awaited_once()

@pytest.mark.asyncio
async def test_mock_lifecycle():
    """Test MockLLMProvider lifecycle."""
    provider = MockLLMProvider()
    async with provider:
        pass
    await provider.close()
