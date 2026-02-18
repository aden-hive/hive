"""Tests for browser automation tool (FastMCP)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
)

from aden_tools.tools.browser_automation_tool import register_tools

_PW_PATH = "aden_tools.tools.browser_automation_tool.browser_automation_tool.async_playwright"


def _make_playwright_mocks(
    html="<html><body>Test</body></html>", title="Test Page", final_url="https://example.com"
):
    """Build a full playwright mock chain and return (context_manager, page)."""
    mock_page = AsyncMock()
    mock_page.goto.return_value = MagicMock(status=200, url=final_url)
    mock_page.content.return_value = html
    mock_page.title.return_value = title
    mock_page.url = final_url
    mock_page.viewport_size = {"width": 1920, "height": 1080}
    mock_page.inner_text.return_value = "Test content"
    mock_page.query_selector.return_value = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.click = AsyncMock()
    mock_page.fill = AsyncMock()
    mock_page.select_option = AsyncMock()
    mock_page.press = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_page.is_checked = AsyncMock(return_value=False)
    mock_page.get_attribute = AsyncMock(return_value="text")
    mock_page.evaluate = AsyncMock(return_value="input")

    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = AsyncMock()
    mock_browser.new_context.return_value = mock_context
    mock_browser.close = AsyncMock()

    mock_pw = MagicMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

    # async context manager for async_playwright()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    return mock_cm, mock_page


def _make_inspect_form_mocks(
    forms_data,
    title="Test Page",
    final_url="https://example.com",
    submit_counts=None,
):
    """Build playwright mocks for browser_inspect_form tests.

    Args:
        forms_data: Dict that page.evaluate() returns.
            Must match actual JS output: {"forms": [...], "forms_found": N}
        title: Page title.
        final_url: Final URL after navigation.
        submit_counts: List of ints, one per form, for locator.count() returns.
            Defaults to [0] * forms_found (no submit buttons).
    """
    mock_cm, mock_page = _make_playwright_mocks(title=title, final_url=final_url)
    mock_page.evaluate.return_value = forms_data

    forms_found = forms_data.get("forms_found", 0)
    if submit_counts is None:
        submit_counts = [0] * forms_found

    form_nth_mocks = []
    for count in submit_counts:
        form_nth = MagicMock()
        submit_loc = MagicMock()
        submit_loc.count = AsyncMock(return_value=count)
        form_nth.locator = MagicMock(return_value=submit_loc)
        form_nth_mocks.append(form_nth)

    mock_form_locator = MagicMock()
    mock_form_locator.nth = MagicMock(side_effect=form_nth_mocks)
    mock_page.locator = MagicMock(return_value=mock_form_locator)

    return mock_cm, mock_page


@pytest.fixture
def browser_get_page_content_fn(mcp: FastMCP):
    """Register and return the browser_get_page_content tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["browser_get_page_content"].fn


@pytest.fixture
def browser_screenshot_fn(mcp: FastMCP):
    """Register and return the browser_screenshot tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["browser_screenshot"].fn


@pytest.fixture
def browser_extract_text_fn(mcp: FastMCP):
    """Register and return the browser_extract_text tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["browser_extract_text"].fn


@pytest.fixture
def browser_click_and_extract_fn(mcp: FastMCP):
    """Register and return the browser_click_and_extract tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["browser_click_and_extract"].fn


@pytest.fixture
def browser_inspect_form_fn(mcp: FastMCP):
    """Register and return the browser_inspect_form tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["browser_inspect_form"].fn


@pytest.fixture
def browser_fill_form_fn(mcp: FastMCP):
    """Register and return the browser_fill_form tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["browser_fill_form"].fn


class TestBrowserGetPageContent:
    """Tests for browser_get_page_content tool."""

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_url_auto_prefixed_with_https(self, mock_pw, browser_get_page_content_fn):
        """URLs without scheme get https:// prefix."""
        mock_cm, _ = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        result = await browser_get_page_content_fn(url="example.com")

        assert isinstance(result, dict)
        assert "error" not in result
        assert "html" in result

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_returns_html_title_url(self, mock_pw, browser_get_page_content_fn):
        """Function returns html, title, and url."""
        html = "<html><body>Content</body></html>"
        title = "Test Page"
        url = "https://example.com"
        mock_cm, _ = _make_playwright_mocks(html=html, title=title, final_url=url)
        mock_pw.return_value = mock_cm

        result = await browser_get_page_content_fn(url=url)

        assert result["html"] == html
        assert result["title"] == title
        assert result["url"] == url

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_wait_for_selector(self, mock_pw, browser_get_page_content_fn):
        """wait_for parameter waits for selector."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        await browser_get_page_content_fn(url="https://example.com", wait_for=".content")

        mock_page.wait_for_selector.assert_called_once()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_timeout_clamped(self, mock_pw, browser_get_page_content_fn):
        """Timeout values are clamped to valid range."""
        mock_cm, _ = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        # Test low timeout (should be clamped to 5000)
        result = await browser_get_page_content_fn(url="https://example.com", timeout=1000)
        assert "error" not in result

        # Test high timeout (should be clamped to 300000)
        result = await browser_get_page_content_fn(url="https://example.com", timeout=500000)
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_http_url_not_double_prefixed(self, mock_pw, browser_get_page_content_fn):
        """URLs with http:// scheme are not double-prefixed."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        result = await browser_get_page_content_fn(url="http://example.com")

        assert "error" not in result
        call_url = mock_page.goto.call_args[0][0]
        assert call_url == "http://example.com"

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_playwright_timeout_returns_error(self, mock_pw, browser_get_page_content_fn):
        """Returns error dict on PlaywrightTimeout."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = PlaywrightTimeout("Timeout")
        mock_pw.return_value = mock_cm

        result = await browser_get_page_content_fn(url="https://example.com")

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_playwright_error_returns_error(self, mock_pw, browser_get_page_content_fn):
        """Returns error dict on PlaywrightError."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = PlaywrightError("Connection refused")
        mock_pw.return_value = mock_cm

        result = await browser_get_page_content_fn(url="https://example.com")

        assert "error" in result
        assert "browser error" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_generic_exception_returns_error(self, mock_pw, browser_get_page_content_fn):
        """Returns error dict on generic Exception."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = RuntimeError("Unexpected error")
        mock_pw.return_value = mock_cm

        result = await browser_get_page_content_fn(url="https://example.com")

        assert "error" in result
        assert "failed to get page content" in result["error"].lower()


class TestBrowserScreenshot:
    """Tests for browser_screenshot tool."""

    @pytest.fixture(autouse=True)
    def _chdir_to_tmp(self, tmp_path, monkeypatch):
        """Set CWD to tmp_path so the path-traversal guard accepts test paths."""
        monkeypatch.chdir(tmp_path)

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, browser_screenshot_fn):
        """Paths outside CWD are rejected by the path-traversal guard."""
        result = await browser_screenshot_fn(
            url="https://example.com", output_path="/etc/evil/screenshot.png"
        )
        assert result == {"error": "output_path must be within the working directory"}

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_screenshot_saved(self, mock_pw, browser_screenshot_fn, tmp_path):
        """Screenshot is saved to specified path."""
        output_path = str(tmp_path / "screenshot.png")
        mock_cm, mock_page = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        result = await browser_screenshot_fn(url="https://example.com", output_path=output_path)

        assert "error" not in result
        assert result["path"] == output_path
        mock_page.screenshot.assert_called_once()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_full_page_option(self, mock_pw, browser_screenshot_fn, tmp_path):
        """full_page parameter is respected."""
        output_path = str(tmp_path / "screenshot.png")
        mock_cm, mock_page = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        await browser_screenshot_fn(
            url="https://example.com", output_path=output_path, full_page=True
        )

        call_args = mock_page.screenshot.call_args
        assert call_args.kwargs["full_page"] is True

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_viewport_only_screenshot(self, mock_pw, browser_screenshot_fn, tmp_path):
        """full_page=False captures viewport only."""
        output_path = str(tmp_path / "screenshot.png")
        mock_cm, mock_page = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        await browser_screenshot_fn(
            url="https://example.com", output_path=output_path, full_page=False
        )

        call_args = mock_page.screenshot.call_args
        assert call_args.kwargs["full_page"] is False

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_url_auto_prefixed_with_https(self, mock_pw, browser_screenshot_fn, tmp_path):
        """URLs without scheme get https:// prefix."""
        output_path = str(tmp_path / "screenshot.png")
        mock_cm, _ = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        result = await browser_screenshot_fn(url="example.com", output_path=output_path)

        assert isinstance(result, dict)
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_timeout_clamped(self, mock_pw, browser_screenshot_fn, tmp_path):
        """Timeout values are clamped to valid range."""
        output_path = str(tmp_path / "screenshot.png")
        mock_cm, _ = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        result = await browser_screenshot_fn(
            url="https://example.com", output_path=output_path, timeout=1000
        )
        assert "error" not in result

        mock_pw.return_value = mock_cm
        result = await browser_screenshot_fn(
            url="https://example.com", output_path=output_path, timeout=500000
        )
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_returns_width_and_height(self, mock_pw, browser_screenshot_fn, tmp_path):
        """Returns viewport width and height."""
        output_path = str(tmp_path / "screenshot.png")
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.viewport_size = {"width": 1920, "height": 1080}
        mock_pw.return_value = mock_cm

        result = await browser_screenshot_fn(url="https://example.com", output_path=output_path)

        assert result["width"] == 1920
        assert result["height"] == 1080

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_viewport_none_returns_none_dimensions(
        self, mock_pw, browser_screenshot_fn, tmp_path
    ):
        """Returns None dimensions when viewport_size is None."""
        output_path = str(tmp_path / "screenshot.png")
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.viewport_size = None
        mock_pw.return_value = mock_cm

        result = await browser_screenshot_fn(url="https://example.com", output_path=output_path)

        assert result["width"] is None
        assert result["height"] is None

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_playwright_timeout_returns_error(self, mock_pw, browser_screenshot_fn, tmp_path):
        """Returns error dict on PlaywrightTimeout."""
        output_path = str(tmp_path / "screenshot.png")
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = PlaywrightTimeout("Timeout")
        mock_pw.return_value = mock_cm

        result = await browser_screenshot_fn(url="https://example.com", output_path=output_path)

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_playwright_error_returns_error(self, mock_pw, browser_screenshot_fn, tmp_path):
        """Returns error dict on PlaywrightError."""
        output_path = str(tmp_path / "screenshot.png")
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = PlaywrightError("Connection refused")
        mock_pw.return_value = mock_cm

        result = await browser_screenshot_fn(url="https://example.com", output_path=output_path)

        assert "error" in result
        assert "browser error" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_generic_exception_returns_error(self, mock_pw, browser_screenshot_fn, tmp_path):
        """Returns error dict on generic Exception."""
        output_path = str(tmp_path / "screenshot.png")
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = RuntimeError("Unexpected error")
        mock_pw.return_value = mock_cm

        result = await browser_screenshot_fn(url="https://example.com", output_path=output_path)

        assert "error" in result
        assert "failed to capture screenshot" in result["error"].lower()


class TestBrowserExtractText:
    """Tests for browser_extract_text tool."""

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_extracts_text_from_body(self, mock_pw, browser_extract_text_fn):
        """Extracts text from body when no selector provided."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.inner_text.return_value = "Body text content"
        mock_pw.return_value = mock_cm

        result = await browser_extract_text_fn(url="https://example.com")

        assert "error" not in result
        assert result["text"] == "Body text content"
        mock_page.inner_text.assert_called_with("body")

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_extracts_text_from_selector(self, mock_pw, browser_extract_text_fn):
        """Extracts text from specified selector."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.inner_text.return_value = "Selector text"
        mock_page.query_selector.return_value = mock_element
        mock_pw.return_value = mock_cm

        result = await browser_extract_text_fn(url="https://example.com", selector=".content")

        assert "error" not in result
        assert result["text"] == "Selector text"
        mock_page.query_selector.assert_called_with(".content")

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_error_when_selector_not_found(self, mock_pw, browser_extract_text_fn):
        """Returns error when selector not found."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.query_selector.return_value = None
        mock_pw.return_value = mock_cm

        result = await browser_extract_text_fn(url="https://example.com", selector=".nonexistent")

        assert "error" in result
        assert "no element found matching selector" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_url_auto_prefixed_with_https(self, mock_pw, browser_extract_text_fn):
        """URLs without scheme get https:// prefix."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.inner_text.return_value = "Text"
        mock_pw.return_value = mock_cm

        result = await browser_extract_text_fn(url="example.com")

        assert isinstance(result, dict)
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_timeout_clamped(self, mock_pw, browser_extract_text_fn):
        """Timeout values are clamped to valid range."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.inner_text.return_value = "Text"
        mock_pw.return_value = mock_cm

        result = await browser_extract_text_fn(url="https://example.com", timeout=1000)
        assert "error" not in result

        mock_pw.return_value = mock_cm
        result = await browser_extract_text_fn(url="https://example.com", timeout=500000)
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_playwright_timeout_returns_error(self, mock_pw, browser_extract_text_fn):
        """Returns error dict on PlaywrightTimeout."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = PlaywrightTimeout("Timeout")
        mock_pw.return_value = mock_cm

        result = await browser_extract_text_fn(url="https://example.com")

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_playwright_error_returns_error(self, mock_pw, browser_extract_text_fn):
        """Returns error dict on PlaywrightError."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = PlaywrightError("Connection refused")
        mock_pw.return_value = mock_cm

        result = await browser_extract_text_fn(url="https://example.com")

        assert "error" in result
        assert "browser error" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_generic_exception_returns_error(self, mock_pw, browser_extract_text_fn):
        """Returns error dict on generic Exception."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = RuntimeError("Unexpected error")
        mock_pw.return_value = mock_cm

        result = await browser_extract_text_fn(url="https://example.com")

        assert "error" in result
        assert "failed to extract text" in result["error"].lower()


class TestBrowserClickAndExtract:
    """Tests for browser_click_and_extract tool."""

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_clicks_element_and_extracts(self, mock_pw, browser_click_and_extract_fn):
        """Clicks element and extracts resulting content."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        result = await browser_click_and_extract_fn(
            url="https://example.com",
            click_selector=".button",
        )

        assert "error" not in result
        assert "html" in result
        assert result["clicked_element"] == ".button"
        mock_page.click.assert_called_once_with(".button")

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_waits_for_selector_after_click(self, mock_pw, browser_click_and_extract_fn):
        """Waits for selector after clicking if provided."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        await browser_click_and_extract_fn(
            url="https://example.com",
            click_selector=".button",
            wait_for_selector=".result",
        )

        # Should wait for click selector first, then result selector
        assert mock_page.wait_for_selector.call_count >= 1

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_error_when_click_selector_missing(self, mock_pw, browser_click_and_extract_fn):
        """Returns error when click_selector is empty."""
        result = await browser_click_and_extract_fn(url="https://example.com", click_selector="")

        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_url_auto_prefixed_with_https(self, mock_pw, browser_click_and_extract_fn):
        """URLs without scheme get https:// prefix."""
        mock_cm, _ = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        result = await browser_click_and_extract_fn(url="example.com", click_selector=".btn")

        assert isinstance(result, dict)
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_timeout_clamped(self, mock_pw, browser_click_and_extract_fn):
        """Timeout values are clamped to valid range."""
        mock_cm, _ = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        result = await browser_click_and_extract_fn(
            url="https://example.com", click_selector=".btn", timeout=1000
        )
        assert "error" not in result

        mock_pw.return_value = mock_cm
        result = await browser_click_and_extract_fn(
            url="https://example.com", click_selector=".btn", timeout=500000
        )
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_network_idle_fallback_when_no_wait_selector(
        self, mock_pw, browser_click_and_extract_fn
    ):
        """Waits for networkidle when wait_for_selector is not provided."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_pw.return_value = mock_cm

        await browser_click_and_extract_fn(url="https://example.com", click_selector=".btn")

        mock_page.wait_for_load_state.assert_called_once()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_playwright_timeout_returns_error(self, mock_pw, browser_click_and_extract_fn):
        """Returns error dict on PlaywrightTimeout."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = PlaywrightTimeout("Timeout")
        mock_pw.return_value = mock_cm

        result = await browser_click_and_extract_fn(
            url="https://example.com", click_selector=".btn"
        )

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_playwright_error_returns_error(self, mock_pw, browser_click_and_extract_fn):
        """Returns error dict on PlaywrightError."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = PlaywrightError("Connection refused")
        mock_pw.return_value = mock_cm

        result = await browser_click_and_extract_fn(
            url="https://example.com", click_selector=".btn"
        )

        assert "error" in result
        assert "browser error" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_generic_exception_returns_error(self, mock_pw, browser_click_and_extract_fn):
        """Returns error dict on generic Exception."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = RuntimeError("Unexpected error")
        mock_pw.return_value = mock_cm

        result = await browser_click_and_extract_fn(
            url="https://example.com", click_selector=".btn"
        )

        assert "error" in result
        assert "failed to click and extract" in result["error"].lower()


class TestBrowserInspectForm:
    """Tests for browser_inspect_form tool."""

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_inspects_form_fields(self, mock_pw, browser_inspect_form_fn):
        """Inspects form and returns field information."""
        forms_data = {
            "forms": [
                {
                    "form_index": 0,
                    "form_selector": "form:nth-of-type(1)",
                    "fields": [
                        {
                            "label": "Email",
                            "name": "email",
                            "type": "email",
                            "selector": "#email",
                            "required": True,
                            "placeholder": "Enter email",
                        },
                        {
                            "label": "Password",
                            "name": "password",
                            "type": "password",
                            "selector": "#password",
                            "required": True,
                            "placeholder": "",
                        },
                    ],
                }
            ],
            "forms_found": 1,
        }
        mock_cm, mock_page = _make_inspect_form_mocks(forms_data)
        mock_pw.return_value = mock_cm

        result = await browser_inspect_form_fn(url="https://example.com/login")

        assert "error" not in result
        assert "forms" in result
        assert len(result["forms"]) == 1
        assert result["forms_found"] == 1
        assert result["forms"][0]["fields"][0]["selector"] == "#email"
        assert result["forms"][0]["fields"][0]["label"] == "Email"
        mock_page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_inspects_specific_form_selector(self, mock_pw, browser_inspect_form_fn):
        """Inspects form using specific form selector."""
        forms_data = {
            "forms": [
                {
                    "form_index": 0,
                    "form_selector": "form#login-form",
                    "fields": [
                        {
                            "label": "Username",
                            "name": "username",
                            "type": "text",
                            "selector": "#username",
                            "required": False,
                            "placeholder": "",
                        },
                    ],
                }
            ],
            "forms_found": 1,
        }
        mock_cm, mock_page = _make_inspect_form_mocks(forms_data)
        mock_pw.return_value = mock_cm

        result = await browser_inspect_form_fn(
            url="https://example.com/login", form_selector="form#login-form"
        )

        assert "error" not in result
        assert len(result["forms"]) == 1
        call_args = mock_page.evaluate.call_args[0][0]
        assert call_args is not None

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_handles_select_fields_with_options(self, mock_pw, browser_inspect_form_fn):
        """Returns options for select dropdown fields."""
        forms_data = {
            "forms": [
                {
                    "form_index": 0,
                    "form_selector": "form:nth-of-type(1)",
                    "fields": [
                        {
                            "label": "Country",
                            "name": "country",
                            "type": "select",
                            "selector": "#country",
                            "required": False,
                            "placeholder": "",
                            "options": [
                                {"value": "us", "text": "United States"},
                                {"value": "uk", "text": "United Kingdom"},
                            ],
                        },
                    ],
                }
            ],
            "forms_found": 1,
        }
        mock_cm, mock_page = _make_inspect_form_mocks(forms_data)
        mock_pw.return_value = mock_cm

        result = await browser_inspect_form_fn(url="https://example.com/form")

        assert "error" not in result
        assert "options" in result["forms"][0]["fields"][0]
        assert len(result["forms"][0]["fields"][0]["options"]) == 2

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_handles_checkbox_fields(self, mock_pw, browser_inspect_form_fn):
        """Returns checked state for checkbox fields."""
        forms_data = {
            "forms": [
                {
                    "form_index": 0,
                    "form_selector": "form:nth-of-type(1)",
                    "fields": [
                        {
                            "label": "Remember me",
                            "name": "remember",
                            "type": "checkbox",
                            "selector": "#remember",
                            "required": False,
                            "placeholder": "",
                            "checked": False,
                            "value": "",
                        },
                    ],
                }
            ],
            "forms_found": 1,
        }
        mock_cm, mock_page = _make_inspect_form_mocks(forms_data)
        mock_pw.return_value = mock_cm

        result = await browser_inspect_form_fn(url="https://example.com/form")

        assert "error" not in result
        assert result["forms"][0]["fields"][0]["checked"] is False

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_handles_no_forms_on_page(self, mock_pw, browser_inspect_form_fn):
        """Handles pages with no forms gracefully."""
        forms_data = {"forms": [], "forms_found": 0}
        mock_cm, mock_page = _make_inspect_form_mocks(forms_data)
        mock_pw.return_value = mock_cm

        result = await browser_inspect_form_fn(url="https://example.com")

        assert "error" not in result
        assert result["forms"] == []
        assert result["forms_found"] == 0

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_returns_title_and_url(self, mock_pw, browser_inspect_form_fn):
        """Returns page title and final URL."""
        forms_data = {"forms": [], "forms_found": 0}
        mock_cm, mock_page = _make_inspect_form_mocks(
            forms_data, title="Login Page", final_url="https://example.com/login"
        )
        mock_pw.return_value = mock_cm

        result = await browser_inspect_form_fn(url="https://example.com/login")

        assert "error" not in result
        assert result["title"] == "Login Page"
        assert result["url"] == "https://example.com/login"

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_submit_button_detected(self, mock_pw, browser_inspect_form_fn):
        """Detects submit button and returns selector."""
        forms_data = {
            "forms": [
                {
                    "form_index": 0,
                    "form_selector": "form:nth-of-type(1)",
                    "fields": [
                        {
                            "label": "Email",
                            "name": "email",
                            "type": "email",
                            "selector": "#email",
                            "required": True,
                            "placeholder": "",
                        },
                    ],
                }
            ],
            "forms_found": 1,
        }
        mock_cm, mock_page = _make_inspect_form_mocks(forms_data, submit_counts=[1])
        mock_pw.return_value = mock_cm

        result = await browser_inspect_form_fn(url="https://example.com/form")

        assert "error" not in result
        assert result["forms"][0]["submit_selector"] is not None

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_no_submit_button_returns_none(self, mock_pw, browser_inspect_form_fn):
        """Returns None for submit_selector when no submit button exists."""
        forms_data = {
            "forms": [
                {
                    "form_index": 0,
                    "form_selector": "form:nth-of-type(1)",
                    "fields": [
                        {
                            "label": "Search",
                            "name": "q",
                            "type": "text",
                            "selector": "#q",
                            "required": False,
                            "placeholder": "Search...",
                        },
                    ],
                }
            ],
            "forms_found": 1,
        }
        mock_cm, mock_page = _make_inspect_form_mocks(forms_data, submit_counts=[0])
        mock_pw.return_value = mock_cm

        result = await browser_inspect_form_fn(url="https://example.com/search")

        assert "error" not in result
        assert result["forms"][0]["submit_selector"] is None

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_url_auto_prefixed_with_https(self, mock_pw, browser_inspect_form_fn):
        """URLs without scheme get https:// prefix."""
        forms_data = {"forms": [], "forms_found": 0}
        mock_cm, mock_page = _make_inspect_form_mocks(forms_data)
        mock_pw.return_value = mock_cm

        result = await browser_inspect_form_fn(url="example.com/form")

        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_timeout_clamped(self, mock_pw, browser_inspect_form_fn):
        """Timeout values are clamped to valid range."""
        forms_data = {"forms": [], "forms_found": 0}
        mock_cm, _ = _make_inspect_form_mocks(forms_data)
        mock_pw.return_value = mock_cm

        result = await browser_inspect_form_fn(url="https://example.com", timeout=1000)
        assert "error" not in result

        mock_pw.return_value = mock_cm
        result = await browser_inspect_form_fn(url="https://example.com", timeout=500000)
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_playwright_timeout_returns_error(self, mock_pw, browser_inspect_form_fn):
        """Returns error dict on PlaywrightTimeout."""
        mock_cm, mock_page = _make_inspect_form_mocks({"forms": [], "forms_found": 0})
        mock_page.goto.side_effect = PlaywrightTimeout("Timeout")
        mock_pw.return_value = mock_cm

        result = await browser_inspect_form_fn(url="https://example.com")

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_playwright_error_returns_error(self, mock_pw, browser_inspect_form_fn):
        """Returns error dict on PlaywrightError."""
        mock_cm, mock_page = _make_inspect_form_mocks({"forms": [], "forms_found": 0})
        mock_page.goto.side_effect = PlaywrightError("Connection refused")
        mock_pw.return_value = mock_cm

        result = await browser_inspect_form_fn(url="https://example.com")

        assert "error" in result
        assert "browser error" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_generic_exception_returns_error(self, mock_pw, browser_inspect_form_fn):
        """Returns error dict on generic Exception."""
        mock_cm, mock_page = _make_inspect_form_mocks({"forms": [], "forms_found": 0})
        mock_page.goto.side_effect = RuntimeError("Unexpected error")
        mock_pw.return_value = mock_cm

        result = await browser_inspect_form_fn(url="https://example.com")

        assert "error" in result
        assert "failed to inspect form" in result["error"].lower()


class TestBrowserFillForm:
    """Tests for browser_fill_form tool."""

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_fills_text_input(self, mock_pw, browser_fill_form_fn):
        """Fills text input fields."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "input"
        mock_element.get_attribute.return_value = "text"
        mock_page.query_selector.return_value = mock_element
        mock_pw.return_value = mock_cm

        form_fields = '{"#username": "user@example.com"}'
        result = await browser_fill_form_fn(url="https://example.com", form_fields=form_fields)

        assert "error" not in result
        assert result["filled_fields"]["#username"] == "user@example.com"
        mock_page.fill.assert_called_once()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_fills_multiple_fields(self, mock_pw, browser_fill_form_fn):
        """Fills multiple form fields."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "input"
        mock_element.get_attribute.return_value = "text"
        mock_page.query_selector.return_value = mock_element
        mock_pw.return_value = mock_cm

        form_fields = '{"#username": "user@example.com", "#password": "secret123"}'
        result = await browser_fill_form_fn(url="https://example.com", form_fields=form_fields)

        assert "error" not in result
        assert len(result["filled_fields"]) == 2
        assert mock_page.fill.call_count == 2

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_submits_form(self, mock_pw, browser_fill_form_fn):
        """Submits form when submit=True."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "input"
        mock_element.get_attribute.return_value = "text"
        mock_submit_button = AsyncMock()
        mock_page.query_selector.side_effect = [mock_element, mock_submit_button]
        mock_pw.return_value = mock_cm

        form_fields = '{"#username": "user@example.com"}'
        result = await browser_fill_form_fn(
            url="https://example.com",
            form_fields=form_fields,
            submit=True,
        )

        assert "error" not in result
        assert result["submitted"] is True
        mock_submit_button.click.assert_called_once()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_error_invalid_json(self, mock_pw, browser_fill_form_fn):
        """Returns error for invalid JSON in form_fields."""
        result = await browser_fill_form_fn(url="https://example.com", form_fields="invalid json")

        assert "error" in result
        assert "json" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_error_empty_form_fields(self, mock_pw, browser_fill_form_fn):
        """Returns error when form_fields is empty."""
        result = await browser_fill_form_fn(url="https://example.com", form_fields="{}")

        assert "error" in result
        assert "empty" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_fills_select_dropdown(self, mock_pw, browser_fill_form_fn):
        """Fills select dropdown fields."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "select"
        mock_page.query_selector.return_value = mock_element
        mock_pw.return_value = mock_cm

        form_fields = '{"#country": "US"}'
        result = await browser_fill_form_fn(url="https://example.com", form_fields=form_fields)

        assert "error" not in result
        mock_page.select_option.assert_called_once()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_fills_checkbox(self, mock_pw, browser_fill_form_fn):
        """Fills checkbox fields."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "input"
        mock_element.get_attribute.return_value = "checkbox"
        mock_element.is_checked.return_value = False
        mock_page.query_selector.return_value = mock_element
        mock_pw.return_value = mock_cm

        form_fields = '{"#remember": "true"}'
        result = await browser_fill_form_fn(url="https://example.com", form_fields=form_fields)

        assert "error" not in result
        mock_page.click.assert_called_once()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_url_auto_prefixed_with_https(self, mock_pw, browser_fill_form_fn):
        """URLs without scheme get https:// prefix."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "input"
        mock_element.get_attribute.return_value = "text"
        mock_page.query_selector.return_value = mock_element
        mock_pw.return_value = mock_cm

        form_fields = '{"#field": "value"}'
        result = await browser_fill_form_fn(url="example.com", form_fields=form_fields)

        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_timeout_clamped(self, mock_pw, browser_fill_form_fn):
        """Timeout values are clamped to valid range."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "input"
        mock_element.get_attribute.return_value = "text"
        mock_page.query_selector.return_value = mock_element
        mock_pw.return_value = mock_cm

        form_fields = '{"#field": "value"}'
        result = await browser_fill_form_fn(
            url="https://example.com", form_fields=form_fields, timeout=1000
        )
        assert "error" not in result

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_checkbox_uncheck(self, mock_pw, browser_fill_form_fn):
        """Unchecks a checked checkbox when value is false."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "input"
        mock_element.get_attribute.return_value = "checkbox"
        mock_element.is_checked.return_value = True
        mock_page.query_selector.return_value = mock_element
        mock_pw.return_value = mock_cm

        form_fields = '{"#remember": "false"}'
        result = await browser_fill_form_fn(url="https://example.com", form_fields=form_fields)

        assert "error" not in result
        mock_page.click.assert_called_once_with("#remember")

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_radio_button(self, mock_pw, browser_fill_form_fn):
        """Fills radio button fields."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "input"
        mock_element.get_attribute.return_value = "radio"
        mock_element.is_checked.return_value = False
        mock_page.query_selector.return_value = mock_element
        mock_pw.return_value = mock_cm

        form_fields = '{"#option-a": "true"}'
        result = await browser_fill_form_fn(url="https://example.com", form_fields=form_fields)

        assert "error" not in result
        mock_page.click.assert_called_once_with("#option-a")

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_react_fallback_for_fill(self, mock_pw, browser_fill_form_fn):
        """Falls back to click+type when page.fill raises."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "input"
        mock_element.get_attribute.return_value = "text"
        mock_page.query_selector.return_value = mock_element
        mock_page.fill.side_effect = Exception("fill failed for React input")
        mock_pw.return_value = mock_cm

        form_fields = '{"#react-input": "value"}'
        result = await browser_fill_form_fn(url="https://example.com", form_fields=form_fields)

        assert "error" not in result
        mock_page.click.assert_called_with("#react-input")
        mock_page.type.assert_called_once_with("#react-input", "value", delay=20)

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_submit_with_custom_selector(self, mock_pw, browser_fill_form_fn):
        """Uses custom submit_selector when provided."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "input"
        mock_element.get_attribute.return_value = "text"
        mock_page.query_selector.return_value = mock_element
        mock_pw.return_value = mock_cm

        form_fields = '{"#field": "value"}'
        result = await browser_fill_form_fn(
            url="https://example.com",
            form_fields=form_fields,
            submit=True,
            submit_selector="#custom-submit",
        )

        assert "error" not in result
        assert result["submitted"] is True

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_submit_enter_key_fallback(self, mock_pw, browser_fill_form_fn):
        """Falls back to pressing Enter when no submit button found."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "input"
        mock_element.get_attribute.return_value = "text"
        mock_page.query_selector.side_effect = [mock_element, None, None]
        mock_pw.return_value = mock_cm

        form_fields = '{"#username": "user"}'
        result = await browser_fill_form_fn(
            url="https://example.com",
            form_fields=form_fields,
            submit=True,
        )

        assert "error" not in result
        assert result["submitted"] is True
        mock_page.press.assert_called_once_with("#username", "Enter")

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_wait_for_selector_after_submit(self, mock_pw, browser_fill_form_fn):
        """Waits for specified selector after form submission."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "input"
        mock_element.get_attribute.return_value = "text"
        mock_submit_button = AsyncMock()
        mock_page.query_selector.side_effect = [mock_element, mock_submit_button]
        mock_pw.return_value = mock_cm

        form_fields = '{"#username": "user"}'
        result = await browser_fill_form_fn(
            url="https://example.com",
            form_fields=form_fields,
            submit=True,
            wait_for_selector=".dashboard",
        )

        assert "error" not in result
        mock_page.wait_for_selector.assert_any_call(".dashboard", timeout=30000)

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_element_not_found_returns_error(self, mock_pw, browser_fill_form_fn):
        """Returns error when element not found after wait."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.query_selector.return_value = None
        mock_pw.return_value = mock_cm

        form_fields = '{"#nonexistent": "value"}'
        result = await browser_fill_form_fn(url="https://example.com", form_fields=form_fields)

        assert "error" in result
        assert "element not found" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_non_dict_json_returns_error(self, mock_pw, browser_fill_form_fn):
        """Returns error when form_fields JSON is not a dict."""
        result = await browser_fill_form_fn(url="https://example.com", form_fields="[1, 2, 3]")

        assert "error" in result

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_not_submitted_when_submit_false(self, mock_pw, browser_fill_form_fn):
        """submitted is False when submit parameter is False."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_element = AsyncMock()
        mock_element.evaluate.return_value = "input"
        mock_element.get_attribute.return_value = "text"
        mock_page.query_selector.return_value = mock_element
        mock_pw.return_value = mock_cm

        form_fields = '{"#field": "value"}'
        result = await browser_fill_form_fn(
            url="https://example.com",
            form_fields=form_fields,
            submit=False,
        )

        assert "error" not in result
        assert result["submitted"] is False

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_playwright_timeout_returns_error(self, mock_pw, browser_fill_form_fn):
        """Returns error dict on PlaywrightTimeout."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = PlaywrightTimeout("Timeout")
        mock_pw.return_value = mock_cm

        form_fields = '{"#field": "value"}'
        result = await browser_fill_form_fn(url="https://example.com", form_fields=form_fields)

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_playwright_error_returns_error(self, mock_pw, browser_fill_form_fn):
        """Returns error dict on PlaywrightError."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = PlaywrightError("Connection refused")
        mock_pw.return_value = mock_cm

        form_fields = '{"#field": "value"}'
        result = await browser_fill_form_fn(url="https://example.com", form_fields=form_fields)

        assert "error" in result
        assert "browser error" in result["error"].lower()

    @pytest.mark.asyncio
    @patch(_PW_PATH)
    async def test_generic_exception_returns_error(self, mock_pw, browser_fill_form_fn):
        """Returns error dict on generic Exception."""
        mock_cm, mock_page = _make_playwright_mocks()
        mock_page.goto.side_effect = RuntimeError("Unexpected error")
        mock_pw.return_value = mock_cm

        form_fields = '{"#field": "value"}'
        result = await browser_fill_form_fn(url="https://example.com", form_fields=form_fields)

        assert "error" in result
        assert "failed to fill form" in result["error"].lower()
