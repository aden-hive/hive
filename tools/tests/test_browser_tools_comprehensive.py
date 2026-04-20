"""Comprehensive tests for browser tools with FastMCP fixtures.

Tests cover:
- Multiple subagents with multiple tab groups
- Complex script execution for LinkedIn, Twitter, YouTube
- Tab lifecycle management
- Navigation and interactions
- Error handling and edge cases
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from gcu.browser.bridge import BeelineBridge
from gcu.browser.tools.advanced import register_advanced_tools
from gcu.browser.tools.inspection import register_inspection_tools
from gcu.browser.tools.interactions import register_interaction_tools
from gcu.browser.tools.lifecycle import register_lifecycle_tools
from gcu.browser.tools.navigation import register_navigation_tools
from gcu.browser.tools.tabs import register_tab_tools

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mcp() -> FastMCP:
    """Create a fresh FastMCP instance for testing."""
    return FastMCP("test-browser-comprehensive")


@pytest.fixture
def mock_bridge() -> MagicMock:
    """Create a mock BeelineBridge with common methods pre-configured."""
    bridge = MagicMock(spec=BeelineBridge)
    bridge.is_connected = True
    bridge._cdp_attached = set()

    # Context management
    bridge.create_context = AsyncMock(return_value={"groupId": 1, "tabId": 100})
    bridge.destroy_context = AsyncMock(return_value={"ok": True})

    # Tab management
    bridge.create_tab = AsyncMock(return_value={"tabId": 101})
    bridge.close_tab = AsyncMock(return_value={"ok": True})
    bridge.list_tabs = AsyncMock(return_value={"tabs": []})
    bridge.activate_tab = AsyncMock(return_value={"ok": True})

    # Navigation
    bridge.navigate = AsyncMock(return_value={"ok": True, "url": "https://example.com"})
    bridge.go_back = AsyncMock(return_value={"ok": True})
    bridge.go_forward = AsyncMock(return_value={"ok": True})
    bridge.reload = AsyncMock(return_value={"ok": True})

    # Interactions
    bridge.click = AsyncMock(return_value={"ok": True})
    bridge.click_coordinate = AsyncMock(return_value={"ok": True})
    bridge.type_text = AsyncMock(return_value={"ok": True})
    bridge.press_key = AsyncMock(return_value={"ok": True})
    bridge.hover = AsyncMock(return_value={"ok": True})
    bridge.scroll = AsyncMock(return_value={"ok": True})
    bridge.select_option = AsyncMock(return_value={"ok": True, "selected": ["option1"]})
    bridge.drag = AsyncMock(return_value={"ok": True})

    # Inspection
    bridge.evaluate = AsyncMock(return_value={"result": {"value": True}})
    bridge.snapshot = AsyncMock(return_value={"tree": "mock_accessibility_tree"})
    bridge.screenshot = AsyncMock(return_value={"data": "base64imagedata"})
    bridge.get_text = AsyncMock(return_value={"text": "sample text"})
    bridge.get_attribute = AsyncMock(return_value={"value": "attribute_value"})

    # Advanced
    bridge.wait_for_selector = AsyncMock(return_value={"ok": True})
    bridge.wait_for_text = AsyncMock(return_value={"ok": True})
    bridge.resize = AsyncMock(return_value={"ok": True})
    bridge.upload_file = AsyncMock(return_value={"ok": True})
    bridge.handle_dialog = AsyncMock(return_value={"ok": True})
    bridge.cdp_attach = AsyncMock(return_value={"ok": True})
    bridge.cdp_detach = AsyncMock(return_value={"ok": True})

    return bridge


# ─────────────────────────────────────────────────────────────────────────────
# Test Classes
# ─────────────────────────────────────────────────────────────────────────────


class TestMultipleSubagentsTabGroups:
    """Tests for multiple subagents creating and managing multiple tab groups."""

    @pytest.mark.asyncio
    async def test_multiple_agents_create_separate_tab_groups(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Multiple subagents should each create their own tab group."""
        call_count = 0

        async def mock_create_context(agent_id: str) -> dict:
            nonlocal call_count
            call_count += 1
            return {"groupId": call_count, "tabId": 100 + call_count}

        mock_bridge.create_context = AsyncMock(side_effect=mock_create_context)

        # Register tools first
        register_lifecycle_tools(mcp)
        browser_start = mcp._tool_manager._tools["browser_start"].fn

        # Now patch for execution
        with patch("gcu.browser.tools.lifecycle.get_bridge", return_value=mock_bridge):
            # Simulate 3 different subagents starting browsers
            results = await asyncio.gather(
                browser_start(profile="agent_1"),
                browser_start(profile="agent_2"),
                browser_start(profile="agent_3"),
            )

        # Each should have created a separate context
        assert mock_bridge.create_context.call_count == 3
        assert all(r.get("ok") for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_tab_operations_different_groups(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Tab operations in different groups should not interfere."""
        group1_tabs = [
            {"id": 101, "url": "https://site1.com", "title": "Site 1"},
            {"id": 102, "url": "https://site2.com", "title": "Site 2"},
        ]
        group2_tabs = [
            {"id": 201, "url": "https://site3.com", "title": "Site 3"},
            {"id": 202, "url": "https://site4.com", "title": "Site 4"},
        ]

        def mock_list_tabs(group_id: int) -> dict:
            if group_id == 1:
                return {"tabs": group1_tabs}
            elif group_id == 2:
                return {"tabs": group2_tabs}
            return {"tabs": []}

        mock_bridge.list_tabs = AsyncMock(side_effect=mock_list_tabs)

        register_tab_tools(mcp)
        browser_tabs = mcp._tool_manager._tools["browser_tabs"].fn

        with patch("gcu.browser.tools.tabs.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.tabs._get_context",
                side_effect=lambda p: {
                    "groupId": 1 if p == "agent_1" else 2,
                    "activeTabId": 101 if p == "agent_1" else 201,
                },
            ):
                # Concurrent tab listing from different agents
                results = await asyncio.gather(
                    browser_tabs(profile="agent_1"),
                    browser_tabs(profile="agent_2"),
                )

        # Each should see only their own tabs
        assert len(results[0].get("tabs", [])) == 2
        assert len(results[1].get("tabs", [])) == 2
        assert results[0]["tabs"][0]["id"] == 101
        assert results[1]["tabs"][0]["id"] == 201

    @pytest.mark.asyncio
    async def test_tab_group_isolation(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Closing a tab in one group should not affect other groups."""
        closed_tabs = []

        async def mock_close_tab(tab_id: int) -> dict:
            closed_tabs.append(tab_id)
            return {"ok": True}

        mock_bridge.close_tab = AsyncMock(side_effect=mock_close_tab)

        register_tab_tools(mcp)
        browser_close = mcp._tool_manager._tools["browser_close"].fn

        with patch("gcu.browser.tools.tabs.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.tabs._get_context",
                return_value={"groupId": 1, "activeTabId": 101},
            ):
                result = await browser_close(tab_id=101, profile="agent_1")

        assert result.get("ok") is True
        assert 101 in closed_tabs


class TestComplexScriptExecution:
    """Tests for complex JavaScript execution patterns on real-world sites."""

    @pytest.mark.asyncio
    async def test_linkedin_scroll_infinite_feed(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test LinkedIn-style infinite feed scrolling with lazy loading."""
        scroll_calls = []

        async def mock_scroll(tab_id: int, direction: str, amount: int = 500) -> dict:
            scroll_calls.append((tab_id, direction, amount))
            return {"ok": True}

        mock_bridge.scroll = AsyncMock(side_effect=mock_scroll)

        register_interaction_tools(mcp)
        browser_scroll = mcp._tool_manager._tools["browser_scroll"].fn

        with patch("gcu.browser.tools.interactions.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.interactions._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                # Simulate infinite scroll - multiple scroll operations
                for _ in range(3):
                    await browser_scroll(direction="down", amount=500)

        assert len(scroll_calls) == 3

    @pytest.mark.asyncio
    async def test_linkedin_profile_data_extraction(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test extracting LinkedIn profile data using complex selectors."""
        profile_data = {
            "name": "John Doe",
            "title": "Software Engineer at Tech Corp",
        }

        mock_bridge.evaluate = AsyncMock(return_value={"result": {"value": profile_data}})

        register_advanced_tools(mcp)
        browser_evaluate = mcp._tool_manager._tools["browser_evaluate"].fn

        with patch("gcu.browser.tools.advanced.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.advanced._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                # Extract profile data via JavaScript
                extraction_script = """
                    const name = document.querySelector('.text-heading-xlarge')?.innerText;
                    const title = document.querySelector('.text-body-medium')?.innerText;
                    return { name, title };
                """
                result = await browser_evaluate(script=extraction_script)

        # browser_evaluate returns the raw result from bridge.evaluate
        assert "result" in result
        assert result["result"]["value"] == profile_data

    @pytest.mark.asyncio
    async def test_twitter_x_infinite_timeline(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test Twitter/X infinite timeline scrolling with tweet loading."""
        tweets_loaded = ["tweet_0", "tweet_1", "tweet_2", "tweet_3", "tweet_4"]

        mock_bridge.evaluate = AsyncMock(return_value={"result": {"value": tweets_loaded}})
        mock_bridge.scroll = AsyncMock(return_value={"ok": True})

        register_interaction_tools(mcp)
        register_advanced_tools(mcp)

        browser_scroll = mcp._tool_manager._tools["browser_scroll"].fn
        browser_evaluate = mcp._tool_manager._tools["browser_evaluate"].fn

        with patch("gcu.browser.tools.interactions.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.interactions._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                # Simulate Twitter timeline scroll
                await browser_scroll(direction="down", amount=800)

        with patch("gcu.browser.tools.advanced.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.advanced._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                extract_script = """
                    return Array.from(document.querySelectorAll('article[data-testid="tweet"]'))
                        .slice(0, 5)
                        .map(t => t.innerText);
                """
                result = await browser_evaluate(script=extract_script)

        # browser_evaluate returns raw result from bridge
        assert "result" in result
        assert result["result"]["value"] == tweets_loaded

    @pytest.mark.asyncio
    async def test_youtube_video_player_interaction(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test YouTube video player controls and state management."""
        player_state = {"playing": False, "currentTime": 0, "duration": 300}

        mock_bridge.evaluate = AsyncMock(return_value={"result": {"value": player_state}})
        mock_bridge.click = AsyncMock(return_value={"ok": True})

        register_advanced_tools(mcp)
        register_interaction_tools(mcp)

        browser_evaluate = mcp._tool_manager._tools["browser_evaluate"].fn

        with patch("gcu.browser.tools.advanced.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.advanced._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                # Interact with YouTube player
                play_script = """
                    document.querySelector('.ytp-play-button')?.click();
                    return true;
                """
                result = await browser_evaluate(script=play_script)

        # browser_evaluate returns raw result from bridge
        assert "result" in result

    @pytest.mark.asyncio
    async def test_youtube_comments_expansion(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test YouTube comments section expansion and loading."""
        comments = ["comment_1", "comment_2", "comment_3"]

        mock_bridge.evaluate = AsyncMock(return_value={"result": {"value": comments}})
        mock_bridge.scroll = AsyncMock(return_value={"ok": True})
        mock_bridge.click = AsyncMock(return_value={"ok": True})

        register_advanced_tools(mcp)

        browser_evaluate = mcp._tool_manager._tools["browser_evaluate"].fn

        with patch("gcu.browser.tools.advanced.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.advanced._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                # Scroll to comments and expand
                expand_script = """
                    const commentsSection = document.querySelector('ytd-comments#comments');
                    if (commentsSection) {
                        commentsSection.scrollIntoView();
                        return true;
                    }
                    return false;
                """
                result = await browser_evaluate(script=expand_script)

        # browser_evaluate returns raw result from bridge
        assert "result" in result

    @pytest.mark.asyncio
    async def test_complex_form_filling_linkedin(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test complex form filling on LinkedIn with dynamic fields."""
        filled_fields = {}

        async def mock_type_text(tab_id: int, selector: str, text: str, **kwargs) -> dict:
            filled_fields[selector] = text
            return {"ok": True}

        async def mock_select_option(tab_id: int, selector: str, values: list, **kwargs) -> dict:
            filled_fields[selector] = values
            return {"ok": True, "selected": values}

        mock_bridge.type_text = AsyncMock(side_effect=mock_type_text)
        mock_bridge.select_option = AsyncMock(side_effect=mock_select_option)

        register_interaction_tools(mcp)

        browser_type = mcp._tool_manager._tools["browser_type"].fn
        browser_select = mcp._tool_manager._tools["browser_select"].fn

        with patch("gcu.browser.tools.interactions.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.interactions._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                # Fill out a LinkedIn job application form
                await browser_type(selector="#first-name", text="John")
                await browser_type(selector="#last-name", text="Doe")
                await browser_type(selector="#email", text="john.doe@example.com")
                await browser_select(selector="#experience-level", values=["5-10 years"])

        assert filled_fields.get("#first-name") == "John"
        assert filled_fields.get("#last-name") == "Doe"
        assert filled_fields.get("#email") == "john.doe@example.com"


class TestTabLifecycle:
    """Tests for tab lifecycle management."""

    @pytest.mark.asyncio
    async def test_create_and_close_tab(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test creating and closing a tab."""
        mock_bridge.create_tab = AsyncMock(return_value={"tabId": 123})
        mock_bridge.close_tab = AsyncMock(return_value={"ok": True})

        register_tab_tools(mcp)
        browser_open = mcp._tool_manager._tools["browser_open"].fn
        browser_close = mcp._tool_manager._tools["browser_close"].fn

        with patch("gcu.browser.tools.tabs.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.tabs._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                open_result = await browser_open(url="https://example.com")
                assert open_result.get("ok") is True

                close_result = await browser_close(tab_id=123)
                assert close_result.get("ok") is True

    @pytest.mark.asyncio
    async def test_tab_activate_switching(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test switching the active tab."""
        mock_bridge.activate_tab = AsyncMock(return_value={"ok": True})

        register_tab_tools(mcp)
        browser_activate_tab = mcp._tool_manager._tools["browser_activate_tab"].fn

        with patch("gcu.browser.tools.tabs.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.tabs._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                result = await browser_activate_tab(tab_id=200)

        assert result.get("ok") is True
        mock_bridge.activate_tab.assert_awaited_once_with(200)


class TestNavigation:
    """Tests for navigation tools."""

    @pytest.mark.asyncio
    async def test_navigate_with_wait_until(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test navigation with different wait_until options."""
        mock_bridge.navigate = AsyncMock(return_value={"ok": True, "url": "https://example.com"})

        register_navigation_tools(mcp)
        browser_navigate = mcp._tool_manager._tools["browser_navigate"].fn

        with patch("gcu.browser.tools.navigation.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.navigation._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                result = await browser_navigate(url="https://example.com", wait_until="networkidle")

        assert result.get("ok") is True
        # The bridge.navigate is called with wait_until as keyword argument
        mock_bridge.navigate.assert_awaited_once_with(100, "https://example.com", wait_until="networkidle")

    @pytest.mark.asyncio
    async def test_navigation_history(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test back/forward navigation."""
        mock_bridge.go_back = AsyncMock(return_value={"ok": True})
        mock_bridge.go_forward = AsyncMock(return_value={"ok": True})

        register_navigation_tools(mcp)
        browser_go_back = mcp._tool_manager._tools["browser_go_back"].fn
        browser_go_forward = mcp._tool_manager._tools["browser_go_forward"].fn

        with patch("gcu.browser.tools.navigation.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.navigation._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                back_result = await browser_go_back()
                forward_result = await browser_go_forward()

        assert back_result.get("ok") is True
        assert forward_result.get("ok") is True


class TestInteractions:
    """Tests for interaction tools."""

    @pytest.mark.asyncio
    async def test_click_with_different_buttons(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test clicking with left, right, and middle buttons."""
        click_calls = []

        async def track_click(tab_id: int, selector: str, button: str = "left", **kwargs) -> dict:
            click_calls.append((tab_id, selector, button))
            return {"ok": True}

        mock_bridge.click = AsyncMock(side_effect=track_click)

        register_interaction_tools(mcp)
        browser_click = mcp._tool_manager._tools["browser_click"].fn

        with patch("gcu.browser.tools.interactions.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.interactions._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                await browser_click(selector="button", button="left")
                await browser_click(selector="button", button="right")
                await browser_click(selector="button", button="middle")

        assert len(click_calls) == 3
        assert [c[2] for c in click_calls] == ["left", "right", "middle"]

    @pytest.mark.asyncio
    async def test_type_with_special_characters(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test typing text with special characters and unicode."""
        typed_texts = []

        async def track_type(tab_id: int, selector: str, text: str, **kwargs) -> dict:
            typed_texts.append(text)
            return {"ok": True}

        mock_bridge.type_text = AsyncMock(side_effect=track_type)

        register_interaction_tools(mcp)
        browser_type = mcp._tool_manager._tools["browser_type"].fn

        with patch("gcu.browser.tools.interactions.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.interactions._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                # Test various special characters
                special_texts = [
                    "Hello, World!",  # Basic punctuation
                    "O'Reilly & Associates",  # Quotes and ampersands
                    "Price: $100 (20% off)",  # Currency and parentheses
                    "Email: user@example.com",  # Email format
                    "日本語テスト",  # Japanese characters
                    "Émojis: 🎉🚀💻",  # Emojis
                ]

                for text in special_texts:
                    result = await browser_type(selector="input", text=text)
                    assert result.get("ok") is True

        assert typed_texts == special_texts

    @pytest.mark.asyncio
    async def test_drag_and_drop(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test drag and drop operation."""
        # browser_drag uses _cdp directly for DOM queries and mouse events
        mock_bridge._cdp = AsyncMock(
            side_effect=lambda tab_id, method, params=None: {
                "DOM.getDocument": {"root": {"nodeId": 1}},
                "DOM.querySelector": {"nodeId": 2},
                "DOM.getBoxModel": {"content": [0, 0, 100, 0, 100, 50, 0, 50]},
                "Input.dispatchMouseEvent": {},
            }.get(method, {})
        )

        register_interaction_tools(mcp)
        browser_drag = mcp._tool_manager._tools["browser_drag"].fn

        with patch("gcu.browser.tools.interactions.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.interactions._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                result = await browser_drag(
                    start_selector="#draggable",
                    end_selector="#dropzone",
                )

        assert result.get("ok") is True


class TestInspection:
    """Tests for inspection tools."""

    @pytest.mark.asyncio
    async def test_snapshot_accessibility_tree(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test getting accessibility tree snapshot."""
        mock_snapshot = """
            [1] document "Page Title"
              [2] button "Submit"
              [3] textbox "Search"
        """
        mock_bridge.snapshot = AsyncMock(return_value={"tree": mock_snapshot})

        register_inspection_tools(mcp)
        browser_snapshot = mcp._tool_manager._tools["browser_snapshot"].fn

        with patch("gcu.browser.tools.inspection.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.inspection._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                result = await browser_snapshot()

        # browser_snapshot returns raw result from bridge
        assert "tree" in result

    @pytest.mark.asyncio
    async def test_screenshot_full_page(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test taking full page screenshot."""
        mock_bridge.screenshot = AsyncMock(
            return_value={
                "ok": True,
                "data": "base64encodedimagedata",
                "width": 1920,
                "height": 5000,
            }
        )

        register_inspection_tools(mcp)
        browser_screenshot = mcp._tool_manager._tools["browser_screenshot"].fn

        with patch("gcu.browser.tools.inspection.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.inspection._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                result = await browser_screenshot(full_page=True)

        # browser_screenshot returns list of content blocks
        assert isinstance(result, list)
        mock_bridge.screenshot.assert_awaited_once_with(100, full_page=True, selector=None)


class TestAdvancedTools:
    """Tests for advanced tools."""

    @pytest.mark.asyncio
    async def test_wait_for_selector_timeout(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test wait_for_selector timeout behavior."""
        mock_bridge.wait_for_selector = AsyncMock(side_effect=TimeoutError("Element not found within timeout"))

        register_advanced_tools(mcp)
        browser_wait = mcp._tool_manager._tools["browser_wait"].fn

        with patch("gcu.browser.tools.advanced.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.advanced._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                result = await browser_wait(selector=".nonexistent", timeout_ms=1000)

        # Should return error result, not raise
        assert result.get("ok") is False
        assert "error" in result or "timed out" in str(result).lower()

    @pytest.mark.asyncio
    async def test_evaluate_with_return_value(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test JavaScript evaluation with return value."""
        mock_bridge.evaluate = AsyncMock(return_value={"result": {"value": {"status": "success", "count": 42}}})

        register_advanced_tools(mcp)
        browser_evaluate = mcp._tool_manager._tools["browser_evaluate"].fn

        with patch("gcu.browser.tools.advanced.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.advanced._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                result = await browser_evaluate(script="return { status: 'success', count: 42 };")

        # browser_evaluate returns raw result from bridge
        assert "result" in result
        assert result["result"]["value"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_file_upload(self, mcp: FastMCP, mock_bridge: MagicMock, tmp_path):
        """Test file upload functionality."""
        # Create real files — browser_upload validates they exist on disk
        file1 = tmp_path / "file1.pdf"
        file2 = tmp_path / "file2.pdf"
        file1.write_bytes(b"fake pdf 1")
        file2.write_bytes(b"fake pdf 2")

        # Mock the CDP calls used by browser_upload
        mock_bridge.cdp_attach = AsyncMock(return_value={"ok": True})

        async def mock_cdp(tab_id, method, params=None):
            if method == "DOM.getDocument":
                return {"root": {"nodeId": 1}}
            if method == "DOM.querySelector":
                return {"nodeId": 42}
            if method == "DOM.setFileInputFiles":
                return {"ok": True}
            return {"ok": True}

        mock_bridge._cdp = AsyncMock(side_effect=mock_cdp)

        register_advanced_tools(mcp)
        browser_upload = mcp._tool_manager._tools["browser_upload"].fn

        with patch("gcu.browser.tools.advanced.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.advanced._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                result = await browser_upload(
                    selector="input[type='file']",
                    file_paths=[str(file1), str(file2)],
                )

        assert result.get("ok") is True
        assert result.get("count") == 2


class TestErrorHandling:
    """Tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_bridge_not_connected(self, mcp: FastMCP):
        """Test behavior when bridge is not connected."""
        mock_bridge = MagicMock(spec=BeelineBridge)
        mock_bridge.is_connected = False

        register_lifecycle_tools(mcp)
        browser_start = mcp._tool_manager._tools["browser_start"].fn

        with patch("gcu.browser.tools.lifecycle.get_bridge", return_value=mock_bridge):
            result = await browser_start(profile="test")

        assert result.get("ok") is False
        assert "not connected" in result.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_browser_not_started(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test behavior when browser is not started."""
        register_tab_tools(mcp)
        browser_tabs = mcp._tool_manager._tools["browser_tabs"].fn

        with patch("gcu.browser.tools.tabs.get_bridge", return_value=mock_bridge):
            with patch("gcu.browser.tools.tabs._get_context", return_value=None):
                result = await browser_tabs(profile="nonexistent")

        assert result.get("ok") is False
        assert "not started" in result.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_cdp_command_failure(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test handling of CDP command failures."""
        mock_bridge.click = AsyncMock(side_effect=RuntimeError("CDP error: Element not found"))

        register_interaction_tools(mcp)
        browser_click = mcp._tool_manager._tools["browser_click"].fn

        with patch("gcu.browser.tools.interactions.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.interactions._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                result = await browser_click(selector=".nonexistent")

        assert result.get("ok") is False
        assert "error" in result


class TestIFWrapping:
    """Tests for JavaScript IIFE wrapping to handle return statements."""

    @pytest.mark.asyncio
    async def test_evaluate_passes_script_through_to_bridge(self, mcp: FastMCP, mock_bridge: MagicMock):
        """browser_evaluate should pass the script through to bridge.evaluate unchanged.

        IIFE wrapping happens inside bridge.evaluate (see bridge.py), not in
        the tool layer. The tool's job is just to forward the script.
        """
        call_args = []

        async def mock_evaluate_capture(tab_id: int, script: str) -> dict:
            call_args.append(script)
            return {"result": {"value": 42}}

        mock_bridge.evaluate = AsyncMock(side_effect=mock_evaluate_capture)

        register_advanced_tools(mcp)
        browser_evaluate = mcp._tool_manager._tools["browser_evaluate"].fn

        with patch("gcu.browser.tools.advanced.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.advanced._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                result = await browser_evaluate(script="return 42;")

        # Tool may issue a toast call then the actual script call
        assert len(call_args) >= 1
        assert any("return 42;" in arg for arg in call_args)
        # Tool returns bridge's raw result
        assert result == {"result": {"value": 42}}

    @pytest.mark.asyncio
    async def test_evaluate_complex_script(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test complex multi-line script execution."""
        mock_bridge.evaluate = AsyncMock(return_value={"result": {"value": {"total": 100, "filtered": 50}}})

        register_advanced_tools(mcp)
        browser_evaluate = mcp._tool_manager._tools["browser_evaluate"].fn

        with patch("gcu.browser.tools.advanced.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.advanced._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                complex_script = """
                    const items = document.querySelectorAll('.item');
                    const filtered = Array.from(items).filter(i => i.classList.contains('active'));
                    return {
                        total: items.length,
                        filtered: filtered.length
                    };
                """
                result = await browser_evaluate(script=complex_script)

        # browser_evaluate returns bridge.evaluate's raw result
        assert "result" in result
        assert result["result"]["value"] == {"total": 100, "filtered": 50}


class TestConcurrentOperations:
    """Tests for concurrent browser operations."""

    @pytest.mark.asyncio
    async def test_concurrent_clicks_different_tabs(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test clicking on multiple tabs concurrently."""
        click_order = []

        async def mock_click(tab_id: int, selector: str, **kwargs) -> dict:
            click_order.append(tab_id)
            await asyncio.sleep(0.01)  # Simulate async operation
            return {"ok": True}

        mock_bridge.click = AsyncMock(side_effect=mock_click)

        register_interaction_tools(mcp)
        browser_click = mcp._tool_manager._tools["browser_click"].fn

        with patch("gcu.browser.tools.interactions.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.interactions._get_context",
                side_effect=lambda p: {
                    "groupId": 1 if p == "agent_1" else 2 if p == "agent_2" else 3,
                    "activeTabId": 101 if p == "agent_1" else 201 if p == "agent_2" else 301,
                },
            ):
                # Concurrent clicks from different agents
                await asyncio.gather(
                    browser_click(selector="button", profile="agent_1"),
                    browser_click(selector="button", profile="agent_2"),
                    browser_click(selector="button", profile="agent_3"),
                )

        # All clicks should have been executed
        assert len(click_order) == 3
        assert set(click_order) == {101, 201, 301}

    @pytest.mark.asyncio
    async def test_mixed_operations_same_tab(self, mcp: FastMCP, mock_bridge: MagicMock):
        """Test mixed operations (click, type, scroll) on same tab."""
        operations = []

        async def track_click(tab_id: int, selector: str, **kwargs) -> dict:
            operations.append("click")
            return {"ok": True}

        async def track_type(tab_id: int, selector: str, text: str, **kwargs) -> dict:
            operations.append("type")
            return {"ok": True}

        async def track_scroll(tab_id: int, direction: str, **kwargs) -> dict:
            operations.append("scroll")
            return {"ok": True}

        mock_bridge.click = AsyncMock(side_effect=track_click)
        mock_bridge.type_text = AsyncMock(side_effect=track_type)
        mock_bridge.scroll = AsyncMock(side_effect=track_scroll)

        register_interaction_tools(mcp)
        browser_click = mcp._tool_manager._tools["browser_click"].fn
        browser_type = mcp._tool_manager._tools["browser_type"].fn
        browser_scroll = mcp._tool_manager._tools["browser_scroll"].fn

        with patch("gcu.browser.tools.interactions.get_bridge", return_value=mock_bridge):
            with patch(
                "gcu.browser.tools.interactions._get_context",
                return_value={"groupId": 1, "activeTabId": 100},
            ):
                # Mix of operations
                await browser_click(selector="button")
                await browser_type(selector="input", text="hello")
                await browser_scroll(direction="down")

        assert "click" in operations
        assert "type" in operations
        assert "scroll" in operations
