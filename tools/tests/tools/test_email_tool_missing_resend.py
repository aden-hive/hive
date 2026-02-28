import sys
from unittest.mock import MagicMock, patch

# We need to mock the import failure before importing the module that uses it
# if it was already imported at the top level. But in our fix it's NOT.


def test_resend_missing_package():
    """Test that email_tool returns a helpful error when resend is not installed."""

    # Mock sys.modules to simulate resend not being installed
    with patch.dict(sys.modules, {"resend": None}):
        from aden_tools.tools.email_tool.email_tool import register_tools

        mcp = MagicMock()
        registered_fns = {}
        mcp.tool.return_value = (
            lambda fn: registered_fns.update({fn.__name__: fn}) or fn
        )

        # This should NOT crash now
        register_tools(mcp)

        assert "send_email" in registered_fns

        # Set dummy key so it doesn't fail on credential check
        import os

        with patch.dict(os.environ, {"RESEND_API_KEY": "test-key"}):
            # Calling the tool with resend provider should return error
            result = registered_fns["send_email"](
                to="test@example.com",
                subject="Test",
                html="<p>Hello</p>",
                provider="resend",
                from_email="sender@example.com",
            )

            assert "error" in result
            assert "resend not installed" in result["error"]
            assert "pip install resend" in result["error"]


def test_resend_api_error_handling():
    """Test that Resend API errors are caught even with lazy import."""

    mock_resend = MagicMock()
    mock_resend.Emails.send.side_effect = Exception("Mocked Resend Error")

    with patch.dict(sys.modules, {"resend": mock_resend}):
        from aden_tools.tools.email_tool.email_tool import register_tools

        mcp = MagicMock()
        registered_fns = {}
        mcp.tool.return_value = (
            lambda fn: registered_fns.update({fn.__name__: fn}) or fn
        )

        register_tools(mcp)

        # Set dummy key so it doesn't fail on credential check
        import os

        with patch.dict(os.environ, {"RESEND_API_KEY": "test-key"}):
            result = registered_fns["send_email"](
                to="test@example.com",
                subject="Test",
                html="<p>Hello</p>",
                provider="resend",
                from_email="sender@example.com",
            )

            assert "error" in result
            assert "Resend API error: Mocked Resend Error" in result["error"]
