"""
Tests for fix to issue #6234.

#6234 — browser_wait(text=...) breaks on quotes and newlines because text was
embedded directly into a JavaScript f-string. Fix: pass text as `arg` to
page.wait_for_function() so it is treated as data, not code.
"""

import pytest


class TestBrowserWaitTextInjectionFix:
    """Issue #6234 — text must be passed as arg, not embedded in JS string."""

    def _get_wait_for_function_calls(self, text_value):
        """
        Run browser_wait with the given text and capture how
        page.wait_for_function() was called.
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_page = AsyncMock()
        mock_page.wait_for_function = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get_page.return_value = mock_page

        with patch(
            "gcu.browser.tools.advanced.get_session", return_value=mock_session
        ):
            import asyncio

            # Import the module to get the registered tool function.
            # register_advanced_tools patches mcp, so we drive it directly.
            from fastmcp import FastMCP

            mcp = FastMCP("test")

            from gcu.browser.tools.advanced import register_advanced_tools

            register_advanced_tools(mcp)

            # Find the browser_wait tool
            tool_fn = None
            for name, tool in mcp._tool_manager._tools.items():
                if name == "browser_wait":
                    tool_fn = tool.fn
                    break

            assert tool_fn is not None, "browser_wait tool not registered"

            asyncio.run(tool_fn(text=text_value))

        return mock_page.wait_for_function.call_args

    def test_text_passed_as_arg_not_embedded(self):
        """The JS string must NOT contain the literal text value."""
        call = self._get_wait_for_function_calls("hello world")
        js_string = call.args[0] if call.args else call.kwargs.get("expression", "")
        assert "hello world" not in js_string, (
            "Text value should not be embedded in the JS string — it should be passed as arg"
        )

    def test_arg_parameter_is_passed(self):
        """page.wait_for_function must receive arg= with the text value."""
        call = self._get_wait_for_function_calls("hello world")
        assert call.kwargs.get("arg") == "hello world", (
            "text must be forwarded as the arg= parameter to wait_for_function"
        )

    def test_single_quote_in_text_does_not_break(self):
        """Text with single quotes must not cause any exception."""
        call = self._get_wait_for_function_calls("O'Reilly")
        assert call.kwargs.get("arg") == "O'Reilly"

    def test_backslash_in_text_does_not_break(self):
        """Text with backslashes must not cause any exception."""
        call = self._get_wait_for_function_calls("C:\\Users\\foo")
        assert call.kwargs.get("arg") == "C:\\Users\\foo"

    def test_newline_in_text_does_not_break(self):
        """Text with newlines must not cause any exception."""
        call = self._get_wait_for_function_calls("line1\nline2")
        assert call.kwargs.get("arg") == "line1\nline2"

    def test_js_expression_uses_arrow_function(self):
        """The JS expression should use an arrow function that receives text as param."""
        call = self._get_wait_for_function_calls("test")
        js_string = call.args[0] if call.args else call.kwargs.get("expression", "")
        # The pattern should be an arrow function like: text => ...includes(text)
        assert "=>" in js_string, "JS expression should be an arrow function"
        assert "includes" in js_string
