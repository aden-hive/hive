"""Tests for browser advanced tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from gcu.browser.tools.advanced import register_advanced_tools


@pytest.fixture
def mcp() -> FastMCP:
    """Create a fresh FastMCP instance for testing."""
    return FastMCP("test-browser-advanced")


@pytest.fixture
def browser_wait_fn(mcp):
    """Register browser tools and return the browser_wait function."""
    register_advanced_tools(mcp)
    return mcp._tool_manager._tools["browser_wait"].fn


@pytest.mark.asyncio
async def test_browser_wait_passes_text_as_function_argument(browser_wait_fn):
    """Quoted and multiline text should be passed as data, not JS source."""
    text = "O'Reilly\nMedia"
    page = MagicMock()
    page.wait_for_function = AsyncMock()

    session = MagicMock()
    session.get_page.return_value = page

    with patch("gcu.browser.tools.advanced.get_session", return_value=session):
        result = await browser_wait_fn(text=text, timeout_ms=1234)

    assert result == {"ok": True, "action": "wait", "condition": "text", "text": text}
    page.wait_for_function.assert_awaited_once_with(
        "(text) => document.body.innerText.includes(text)",
        arg=text,
        timeout=1234,
    )
