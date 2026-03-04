"""Tests for supabase_tool - Supabase database, auth, and edge functions."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.supabase_tool.supabase_tool import register_tools

ENV = {"SUPABASE_ANON_KEY": "test-key", "SUPABASE_URL": "https://test.supabase.co"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    """Register and return all Supabase tool functions."""
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestSupabaseSelect:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["supabase_select"](table="users")
        assert "error" in result

    def test_missing_table(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["supabase_select"](table="")
        assert "error" in result

    def test_successful_select(self, tool_fns):
        rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = rows
            result = tool_fns["supabase_select"](table="users")

        assert result["table"] == "users"
        assert result["count"] == 2
        assert result["rows"][0]["name"] == "Alice"

    def test_with_filters(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = []
            tool_fns["supabase_select"](table="users", filters="status=eq.active&age=gt.18")
            call_params = mock_get.call_args[1]["params"]
            assert call_params["status"] == "eq.active"
            assert call_params["age"] == "gt.18"


class TestSupabaseInsert:
    def test_missing_fields(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["supabase_insert"](table="", rows="")
        assert "error" in result

    def test_invalid_json(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["supabase_insert"](table="users", rows="not json")
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    def test_successful_insert(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = [{"id": 1, "name": "Alice"}]
            result = tool_fns["supabase_insert"](table="users", rows='{"name": "Alice"}')

        assert result["table"] == "users"
        assert len(result["inserted"]) == 1


class TestSupabaseUpdate:
    def test_missing_filters(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["supabase_update"](table="users", filters="", data='{"x": 1}')
        assert "error" in result

    def test_successful_update(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.patch") as mock_patch,
        ):
            mock_patch.return_value.status_code = 200
            mock_patch.return_value.json.return_value = [{"id": 1, "status": "done"}]
            result = tool_fns["supabase_update"](
                table="tasks", filters="id=eq.1", data='{"status": "done"}'
            )

        assert result["table"] == "tasks"
        assert result["updated"][0]["status"] == "done"


class TestSupabaseDelete:
    def test_missing_filters(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["supabase_delete"](table="users", filters="")
        assert "error" in result

    def test_successful_delete(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.delete") as mock_del,
        ):
            mock_del.return_value.status_code = 200
            mock_del.return_value.json.return_value = [{"id": 1}]
            result = tool_fns["supabase_delete"](table="users", filters="id=eq.1")

        assert result["table"] == "users"
        assert len(result["deleted"]) == 1


class TestSupabaseAuth:
    def test_signup_missing_fields(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["supabase_auth_signup"](email="", password="")
        assert "error" in result

    def test_signup_short_password(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["supabase_auth_signup"](email="a@b.com", password="123")
        assert "error" in result
        assert "6 characters" in result["error"]

    def test_successful_signup(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "user": {"id": "u-1", "email": "a@b.com", "confirmed_at": None}
            }
            result = tool_fns["supabase_auth_signup"](email="a@b.com", password="password123")

        assert result["user_id"] == "u-1"
        assert result["confirmed"] is False

    def test_signin_missing_fields(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["supabase_auth_signin"](email="", password="")
        assert "error" in result

    def test_successful_signin(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "access_token": "jwt-token",
                "expires_in": 3600,
                "user": {"id": "u-1", "email": "a@b.com"},
            }
            result = tool_fns["supabase_auth_signin"](email="a@b.com", password="password123")

        assert result["access_token"] == "jwt-token"
        assert result["expires_in"] == 3600


class TestSupabaseEdgeInvoke:
    def test_missing_function_name(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["supabase_edge_invoke"](function_name="")
        assert "error" in result

    def test_invalid_body_json(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["supabase_edge_invoke"](function_name="test", body="not json")
        assert "error" in result

    def test_successful_invoke(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.headers = {"content-type": "application/json"}
            mock_post.return_value.json.return_value = {"result": "ok"}
            result = tool_fns["supabase_edge_invoke"](
                function_name="process", body='{"input": "data"}'
            )

        assert result["status_code"] == 200
        assert result["response"]["result"] == "ok"
