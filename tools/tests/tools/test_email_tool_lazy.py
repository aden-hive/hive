import sys
from unittest.mock import patch

from fastmcp import FastMCP

from aden_tools.tools.email_tool.email_tool import register_tools


def test_resend_missing_package():
    with patch.dict(sys.modules, {"resend": None}):
        mcp = FastMCP("test")
        register_tools(mcp)

        send_email = mcp._tool_manager._tools["send_email"].fn

        # Mock credentials check
        import os

        with patch.dict(os.environ, {"RESEND_API_KEY": "test-key"}):
            result = send_email(
                to="t@e.com",
                subject="s",
                html="h",
                provider="resend",
                from_email="f@e.com",
            )

        assert "error" in result
        assert "resend not installed" in result["error"]
