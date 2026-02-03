"""Tests for Trello tools (FastMCP)."""

from unittest.mock import MagicMock

import pytest
from fastmcp import FastMCP

from aden_tools.tools.trello_tool import register_tools


@pytest.fixture
def trello_tools(mcp: FastMCP, monkeypatch):
    monkeypatch.setenv("TRELLO_API_KEY", "test-key")
    monkeypatch.setenv("TRELLO_API_TOKEN", "test-token")
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools if name.startswith("trello_")}


class TestTrelloTools:
    def test_missing_credentials_returns_error(self, mcp: FastMCP, monkeypatch):
        monkeypatch.delenv("TRELLO_API_KEY", raising=False)
        monkeypatch.delenv("TRELLO_API_TOKEN", raising=False)
        register_tools(mcp)

        fn = mcp._tool_manager._tools["trello_list_boards"].fn
        result = fn()

        assert "error" in result
        assert "Trello credentials not configured" in result["error"]

    def test_list_boards_success(self, trello_tools, monkeypatch):
        def fake_request(method, url, params=None, timeout=None):
            assert method == "GET"
            assert url.endswith("/members/me/boards")
            return MagicMock(status_code=200, json=lambda: [{"id": "b1"}])

        monkeypatch.setattr("httpx.request", fake_request)

        result = trello_tools["trello_list_boards"]()
        assert "boards" in result
        assert result["boards"][0]["id"] == "b1"

    def test_list_boards_limit_out_of_range(self, trello_tools):
        result = trello_tools["trello_list_boards"](limit=0)
        assert "error" in result
        assert "limit" in result["error"].lower()

    def test_create_card_requires_name(self, trello_tools):
        result = trello_tools["trello_create_card"](list_id="l1", name="")
        assert "error" in result

    def test_create_card_desc_too_long(self, trello_tools):
        desc = "x" * 16385
        result = trello_tools["trello_create_card"](list_id="l1", name="ok", desc=desc)
        assert "error" in result
        assert "desc" in result["error"].lower()

    def test_add_comment_requires_text(self, trello_tools):
        result = trello_tools["trello_add_comment"](card_id="c1", text="")
        assert "error" in result

    def test_list_cards_limit_out_of_range(self, trello_tools):
        result = trello_tools["trello_list_cards"](list_id="l1", limit=1001)
        assert "error" in result
        assert "limit" in result["error"].lower()

    def test_rate_limit_error(self, trello_tools, monkeypatch):
        def fake_request(method, url, params=None, timeout=None):
            return MagicMock(status_code=429, json=lambda: {"message": "rate"}, text="rate")

        monkeypatch.setattr("httpx.request", fake_request)

        result = trello_tools["trello_list_boards"]()
        assert "error" in result
        assert "rate limit" in result["error"].lower()

    def test_get_member_success(self, trello_tools, monkeypatch):
        def fake_request(method, url, params=None, timeout=None):
            assert method == "GET"
            assert url.endswith("/members/me")
            return MagicMock(status_code=200, json=lambda: {"id": "m1"})

        monkeypatch.setattr("httpx.request", fake_request)

        result = trello_tools["trello_get_member"]()
        assert result["id"] == "m1"


class TestTrelloClientErrorHandling:
    def test_not_found(self, trello_tools, monkeypatch):
        def fake_request(method, url, params=None, timeout=None):
            return MagicMock(status_code=404, json=lambda: {"message": "nope"}, text="nope")

        monkeypatch.setattr("httpx.request", fake_request)

        result = trello_tools["trello_list_lists"](board_id="missing")
        assert "error" in result
        assert "not found" in result["error"].lower()
