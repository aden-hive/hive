"""Verify the tools inventory stays in sync with docs."""

from aden_tools.tools import register_all_tools

EXPECTED_TOOL_COUNT = 106


def test_tool_inventory_count(mcp, mock_credentials) -> None:
    tools = register_all_tools(mcp, credentials=mock_credentials)

    assert len(tools) == EXPECTED_TOOL_COUNT
    assert len(set(tools)) == len(tools)

    # Spot-check newer tool families
    assert "github_create_issue" in tools
    assert "slack_send_message" in tools
    assert "apollo_enrich_person" in tools
