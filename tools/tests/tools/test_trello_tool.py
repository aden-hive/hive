"""Tests for trello_tool - Trello board, list, and card management."""

from unittest.mock import patch, MagicMock

import pytest
from fastmcp import FastMCP

from aden_tools.tools.trello_tool.trello_tool import register_tools

ENV = {"TRELLO_API_KEY": "test-key", "TRELLO_TOKEN": "test-token"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestTrelloListBoards:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["trello_list_boards"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"[]"
        mock_resp.json.return_value = [
            {"id": "board-1", "name": "Sprint Board", "url": "https://trello.com/b/abc", "closed": False, "dateLastActivity": "2024-01-01T00:00:00Z"}
        ]
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.trello_tool.trello_tool.httpx.get", return_value=mock_resp),
        ):
            result = tool_fns["trello_list_boards"]()

        assert len(result["boards"]) == 1
        assert result["boards"][0]["name"] == "Sprint Board"


class TestTrelloGetBoard:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["trello_get_board"](board_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = {
            "id": "board-1", "name": "Sprint Board", "desc": "Main board",
            "url": "https://trello.com/b/abc", "closed": False,
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.trello_tool.trello_tool.httpx.get", return_value=mock_resp),
        ):
            result = tool_fns["trello_get_board"](board_id="board-1")

        assert result["name"] == "Sprint Board"


class TestTrelloGetLists:
    def test_successful_get(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"[]"
        mock_resp.json.return_value = [
            {"id": "list-1", "name": "To Do", "closed": False, "pos": 1},
            {"id": "list-2", "name": "Done", "closed": False, "pos": 2},
        ]
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.trello_tool.trello_tool.httpx.get", return_value=mock_resp),
        ):
            result = tool_fns["trello_get_lists"](board_id="board-1")

        assert len(result["lists"]) == 2


class TestTrelloGetCards:
    def test_missing_ids(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["trello_get_cards"]()
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"[]"
        mock_resp.json.return_value = [
            {
                "id": "card-1", "name": "Fix bug", "desc": "Important",
                "closed": False, "due": "2024-06-15T00:00:00Z", "dueComplete": False,
                "idList": "list-1", "labels": [{"name": "bug"}],
            }
        ]
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.trello_tool.trello_tool.httpx.get", return_value=mock_resp),
        ):
            result = tool_fns["trello_get_cards"](list_id="list-1")

        assert len(result["cards"]) == 1
        assert result["cards"][0]["labels"] == ["bug"]


class TestTrelloCreateCard:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["trello_create_card"](list_id="", name="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = {
            "id": "card-new", "name": "New task", "url": "https://trello.com/c/xyz",
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.trello_tool.trello_tool.httpx.post", return_value=mock_resp),
        ):
            result = tool_fns["trello_create_card"](list_id="list-1", name="New task")

        assert result["status"] == "created"


class TestTrelloUpdateCard:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["trello_update_card"](card_id="")
        assert "error" in result

    def test_successful_update(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = {"id": "card-1", "name": "Updated", "closed": False}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.trello_tool.trello_tool.httpx.put", return_value=mock_resp),
        ):
            result = tool_fns["trello_update_card"](card_id="card-1", name="Updated")

        assert result["status"] == "updated"
