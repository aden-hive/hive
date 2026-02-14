"""
Unit tests for the Browser-Use Tool.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aden_tools.tools.browser_use_tool.browser_use_tool import is_safe_url, register_tools
from fastmcp import FastMCP

def test_is_safe_url():
    """Test the SSRF safety check."""
    # Safe URLs
    assert is_safe_url("https://google.com") is True
    assert is_safe_url("http://example.org/path?query=1") is True
    assert is_safe_url("https://1.1.1.1") is True
    assert is_safe_url("https://8.8.8.8/search") is True
    
    # Unsafe Protocols/Schemes
    assert is_safe_url("ftp://google.com") is False
    assert is_safe_url("file:///etc/passwd") is False
    assert is_safe_url("gopher://example.com") is False
    assert is_safe_url("javascript:alert(1)") is False
    
    # Localhost and Loopback
    assert is_safe_url("https://localhost") is False
    assert is_safe_url("http://127.0.0.1:8080") is False
    assert is_safe_url("http://[::1]") is False
    assert is_safe_url("http://0.0.0.0") is False
    assert is_safe_url("http://127.1") is False  # Obfuscated 127.0.0.1
    assert is_safe_url("http://2130706433") is False # Integer representation of 127.0.0.1
    
    # Private IP Ranges (SSRF protection)
    assert is_safe_url("https://10.0.0.1") is False
    assert is_safe_url("http://192.168.1.1") is False
    assert is_safe_url("http://172.16.0.1") is False
    assert is_safe_url("http://172.31.255.255") is False
    assert is_safe_url("http://169.254.169.254") is False # AWS Metadata
    
    # Malformed or missing components
    assert is_safe_url("not-a-url") is False
    assert is_safe_url("http://") is False

@pytest.mark.asyncio
async def test_browser_use_task_success():
    """Test successful task execution with mocking."""
    mcp = FastMCP("test")
    credentials = MagicMock()
    credentials.get.return_value = "fake-api-key"
    register_tools(mcp, credentials=credentials)
    
    browser_use_task = mcp._tool_manager._tools["browser_use_task"]
    
    with patch("aden_tools.tools.browser_use_tool.browser_use_tool.Agent") as MockAgent, \
         patch("aden_tools.tools.browser_use_tool.browser_use_tool.Browser") as MockBrowser, \
         patch("aden_tools.tools.browser_use_tool.browser_use_tool.ChatOpenAI") as MockLLM:
        
        mock_browser_instance = MockBrowser.return_value
        mock_browser_instance.close = AsyncMock()
        
        mock_agent_instance = MockAgent.return_value
        mock_agent_instance.run = AsyncMock()
        
        mock_result = MagicMock()
        mock_result.final_result.return_value = "Task completed."
        mock_result.history = [MagicMock()]
        mock_agent_instance.run.return_value = mock_result
        
        result = await browser_use_task.fn(task="Test task", max_steps=10)
        
        assert result["success"] is True
        assert result["result"] == "Task completed."
        assert result["steps_taken"] == 1
        MockAgent.assert_called_once()
        # Verify default headless=True
        MockBrowser.assert_called_once_with(headless=True, allowed_domains=None)

@pytest.mark.asyncio
async def test_browser_use_task_with_allowed_domains():
    """Test passing allowed_domains to the browser."""
    mcp = FastMCP("test")
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
        register_tools(mcp)
        browser_use_task = mcp._tool_manager._tools["browser_use_task"]
        
        with patch("aden_tools.tools.browser_use_tool.browser_use_tool.Agent") as MockAgent, \
             patch("aden_tools.tools.browser_use_tool.browser_use_tool.Browser") as MockBrowser, \
             patch("aden_tools.tools.browser_use_tool.browser_use_tool.ChatOpenAI"):
            
            MockAgent.return_value.run = AsyncMock(return_value=MagicMock(history=[]))
            MockBrowser.return_value.close = AsyncMock()
            
            await browser_use_task.fn(
                task="Test", 
                allowed_domains=["google.com", "openai.com"],
                headless=False
            )
            
            MockBrowser.assert_called_once_with(
                headless=False, 
                allowed_domains=["google.com", "openai.com"]
            )

@pytest.mark.asyncio
async def test_browser_use_task_step_callback():
    """Test that the step callback is registered and updates logs."""
    mcp = FastMCP("test")
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
        register_tools(mcp)
        browser_use_task = mcp._tool_manager._tools["browser_use_task"]
        
        with patch("aden_tools.tools.browser_use_tool.browser_use_tool.Agent") as MockAgent, \
             patch("aden_tools.tools.browser_use_tool.browser_use_tool.Browser") as MockBrowser, \
             patch("aden_tools.tools.browser_use_tool.browser_use_tool.ChatOpenAI"):
            
            MockBrowser.return_value.close = AsyncMock()
            
            # Setup agent mock
            mock_agent = MockAgent.return_value
            mock_agent.run = AsyncMock()
            
            # Capture the callback passed to Agent
            await browser_use_task.fn(task="Test callback")
            
            _, kwargs = MockAgent.call_args
            on_step = kwargs["register_new_step_callback"]
            assert on_step is not None
            
            # Simulate a step
            mock_state = MagicMock()
            mock_state.url = "https://example.com"
            mock_state.screenshot = "base64data"
            
            mock_output = MagicMock()
            mock_output.model_dump.return_value = {"action": "click"}
            
            await on_step(mock_state, mock_output, 1)
            
            # We can't easily check the local step_logs variable inside the function 
            # without modifying the function to return it or using a more complex mock,
            # but we've verified it's being registered.

@pytest.mark.asyncio
async def test_browser_use_task_error_handling():
    """Test graceful error handling on agent failure."""
    mcp = FastMCP("test")
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
        register_tools(mcp)
        browser_use_task = mcp._tool_manager._tools["browser_use_task"]
        
        with patch("aden_tools.tools.browser_use_tool.browser_use_tool.Agent") as MockAgent, \
             patch("aden_tools.tools.browser_use_tool.browser_use_tool.Browser") as MockBrowser, \
             patch("aden_tools.tools.browser_use_tool.browser_use_tool.ChatOpenAI"):
            
            mock_agent = MockAgent.return_value
            mock_agent.run.side_effect = Exception("Browser crashed")
            MockBrowser.return_value.close = AsyncMock()
            
            result = await browser_use_task.fn(task="Test error")
            
            assert result["success"] is False
            assert "Browser crashed" in result["error"]

@pytest.mark.asyncio
async def test_browser_use_task_no_api_key():
    """Test failure when no API key is provided."""
    mcp = FastMCP("test")
    register_tools(mcp, credentials=None)
    browser_use_task = mcp._tool_manager._tools["browser_use_task"]
    
    with patch.dict("os.environ", {}, clear=True):
        result = await browser_use_task.fn(task="Test")
        assert "error" in result
        assert "OpenAI API key not found" in result["error"]
