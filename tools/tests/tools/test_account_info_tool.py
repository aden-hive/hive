"""Tests for account_info_tool - Account listing and filtering."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.account_info_tool.account_info_tool import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestAccountInfoTool:
    def test_list_accounts(self, tool_fns):
        mock_accounts = [
            {"id": "acc1", "provider": "aws", "name": "AWS Account"},
            {"id": "acc2", "provider": "gcp", "name": "GCP Account"},
        ]

        with patch(
            "aden_tools.tools.account_info_tool.account_info_tool.get_accounts",
            return_value=mock_accounts,
        ):
            result = tool_fns["account_info_tool"]()

        assert result["count"] == 2
        assert result["accounts"][0]["provider"] == "aws"

    def test_filter_by_provider(self, tool_fns):
        mock_accounts = [
            {"id": "acc1", "provider": "aws"},
            {"id": "acc2", "provider": "gcp"},
        ]

        with patch(
            "aden_tools.tools.account_info_tool.account_info_tool.get_accounts",
            return_value=mock_accounts,
        ):
            result = tool_fns["account_info_tool"](provider="aws")

        assert result["count"] == 1
        assert result["accounts"][0]["provider"] == "aws"

    def test_no_accounts(self, tool_fns):
        with patch(
            "aden_tools.tools.account_info_tool.account_info_tool.get_accounts",
            return_value=[],
        ):
            result = tool_fns["account_info_tool"]()

        assert result["count"] == 0
        assert result["accounts"] == []