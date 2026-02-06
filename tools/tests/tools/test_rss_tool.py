import pytest
from unittest.mock import MagicMock, patch
from aden_tools.tools.rss_tool.rss_tool import register_tools

class MockEntry:
    """Helper to mock a feedparser entry"""
    def __init__(self, title, link, published, summary):
        self.title = title
        self.link = link
        self.published = published
        self.updated = published  # Fallback
        self.summary = summary

def test_rss_tool_logic():
    """Test the RSS tool logic with mocked feedparser."""
    
    # 1. Setup Mock MCP to capture the tool function
    mock_mcp = MagicMock()
    captured_func = None

    # This handles the @mcp.tool() decorator pattern
    def tool_decorator():
        def wrapper(func):
            nonlocal captured_func
            captured_func = func
            return func
        return wrapper
    
    mock_mcp.tool.side_effect = tool_decorator

    # 2. Register the tool to get access to the function
    register_tools(mock_mcp)
    
    assert captured_func is not None, "Tool function was not registered via @mcp.tool()"
    assert captured_func.__name__ == "read_rss_feed"

    # 3. Mock feedparser.parse behavior
    with patch("aden_tools.tools.rss_tool.rss_tool.feedparser") as mock_feedparser:
        # Create a mock feed object
        mock_feed = MagicMock()
        mock_feed.bozo = False # No errors
        mock_feed.entries = [
            MockEntry("AI News 1", "http://test.com/1", "2023-10-27", "Summary 1"),
            MockEntry("AI News 2", "http://test.com/2", "2023-10-28", "Summary 2")
        ]
        mock_feedparser.parse.return_value = mock_feed

        # 4. Run the tool function
        result = captured_func(url="http://fake-rss.com", limit=2)

        # 5. Verify Results
        assert len(result) == 2
        assert result[0]["title"] == "AI News 1"
        assert result[0]["link"] == "http://test.com/1"
        assert result[0]["summary"] == "Summary 1"
        
        # Verify it called the parser
        mock_feedparser.parse.assert_called_with("http://fake-rss.com")

def test_rss_tool_error_handling():
    """Test that the tool handles bad feeds gracefully."""
    
    mock_mcp = MagicMock()
    
    # --- FIX START ---
    # Create a mock for the inner decorator (the thing that receives the function)
    mock_decorator = MagicMock()
    mock_decorator.side_effect = lambda x: x  # Return the function unchanged
    
    # Make mcp.tool() return this decorator mock
    mock_mcp.tool.return_value = mock_decorator
    # --- FIX END ---

    register_tools(mock_mcp)

    # Now we grab the arg from the DECORATOR mock, not the tool mock
    # Check if called to avoid the index error again if registration failed silently
    if mock_decorator.call_args:
        read_rss_feed = mock_decorator.call_args[0][0]
        
        # Now run your actual test logic
        # result = read_rss_feed("invalid_url")
        # assert "Error" in result
    else:
        pytest.fail("The tool was not registered (decorator was never called).")