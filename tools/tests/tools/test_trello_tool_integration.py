"""Skippable integration test for Trello tools."""

import os

import pytest
from fastmcp import FastMCP

from aden_tools.tools.trello_tool import register_tools


@pytest.mark.skipif(
    not os.getenv("TRELLO_API_KEY") or not os.getenv("TRELLO_API_TOKEN"),
    reason="TRELLO_API_KEY/TRELLO_API_TOKEN not set",
)
def test_list_boards_integration():
    mcp = FastMCP("trello-test")
    register_tools(mcp)
    fn = mcp._tool_manager._tools["trello_list_boards"].fn

    result = fn()

    assert isinstance(result, dict)
    assert "boards" in result


@pytest.mark.skipif(
    not os.getenv("TRELLO_API_KEY") or not os.getenv("TRELLO_API_TOKEN"),
    reason="TRELLO_API_KEY/TRELLO_API_TOKEN not set",
)
def test_get_member_integration():
    mcp = FastMCP("trello-test")
    register_tools(mcp)
    fn = mcp._tool_manager._tools["trello_get_member"].fn

    result = fn()

    assert isinstance(result, dict)
    assert "id" in result


@pytest.mark.skipif(
    not os.getenv("TRELLO_API_KEY") or not os.getenv("TRELLO_API_TOKEN"),
    reason="TRELLO_API_KEY/TRELLO_API_TOKEN not set",
)
def test_list_lists_and_cards_integration():
    mcp = FastMCP("trello-test")
    register_tools(mcp)
    list_boards = mcp._tool_manager._tools["trello_list_boards"].fn
    list_lists = mcp._tool_manager._tools["trello_list_lists"].fn
    list_cards = mcp._tool_manager._tools["trello_list_cards"].fn

    boards_result = list_boards()
    boards = boards_result.get("boards", [])
    if not boards:
        pytest.skip("No boards available for integration test.")

    board_id = boards[0]["id"]
    lists_result = list_lists(board_id=board_id)
    lists = lists_result.get("lists", [])
    if not lists:
        pytest.skip("No lists available for integration test.")

    list_id = lists[0]["id"]
    cards_result = list_cards(list_id=list_id, limit=5)

    assert isinstance(lists_result, dict)
    assert "lists" in lists_result
    assert isinstance(cards_result, dict)
    assert "cards" in cards_result
