"""
Tests for Notion workspace tool.

Covers:
- _NotionClient methods (all page, database, block, search, user,
  and comment operations)
- Error handling (API errors, invalid credentials, missing credentials)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 17 MCP tool functions
- Input validation (UUID format checks, required fields)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aden_tools.tools.notion_tool.notion_tool import (
    _NotionClient,
    _is_valid_id,
    register_tools,
)

# ---------------------------------------------------------------------------
# Test data constants
# ---------------------------------------------------------------------------

_VALID_UUID = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
_VALID_UUID_DASHES = "a1b2c3d4-e5f6-a1b2-c3d4-e5f6a1b2c3d4"
_INVALID_ID = "not-a-valid-id"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _page(**kwargs):
    defaults = {
        "id": _VALID_UUID,
        "object": "page",
        "created_time": "2024-01-01T00:00:00.000Z",
        "last_edited_time": "2024-01-02T00:00:00.000Z",
        "archived": False,
        "url": "https://www.notion.so/Test-Page-abc123",
        "properties": {"Name": {"title": [{"text": {"content": "Test Page"}}]}},
        "parent": {"type": "database_id", "database_id": _VALID_UUID},
        "icon": None,
        "cover": None,
    }
    defaults.update(kwargs)
    return defaults


def _database(**kwargs):
    defaults = {
        "id": _VALID_UUID,
        "object": "database",
        "created_time": "2024-01-01T00:00:00.000Z",
        "last_edited_time": "2024-01-02T00:00:00.000Z",
        "title": [{"type": "text", "text": {"content": "Test DB"}}],
        "url": "https://www.notion.so/Test-DB-abc123",
        "properties": {"Name": {"id": "title", "type": "title", "title": {}}},
        "parent": {"type": "page_id", "page_id": _VALID_UUID},
        "archived": False,
    }
    defaults.update(kwargs)
    return defaults


def _block(**kwargs):
    defaults = {
        "id": _VALID_UUID,
        "object": "block",
        "type": "paragraph",
        "created_time": "2024-01-01T00:00:00.000Z",
        "last_edited_time": "2024-01-02T00:00:00.000Z",
        "has_children": False,
        "archived": False,
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": "Hello"}}]
        },
    }
    defaults.update(kwargs)
    return defaults


def _user(**kwargs):
    defaults = {
        "id": _VALID_UUID,
        "object": "user",
        "type": "person",
        "name": "Test User",
        "avatar_url": "https://example.com/avatar.png",
        "person": {"email": "test@example.com"},
        "bot": None,
    }
    defaults.update(kwargs)
    return defaults


def _comment(**kwargs):
    defaults = {
        "id": _VALID_UUID,
        "object": "comment",
        "parent": {"type": "page_id", "page_id": _VALID_UUID},
        "discussion_id": _VALID_UUID,
        "rich_text": [{"type": "text", "text": {"content": "Nice!"}}],
        "created_time": "2024-01-01T00:00:00.000Z",
        "created_by": {"id": _VALID_UUID, "object": "user"},
    }
    defaults.update(kwargs)
    return defaults


def _list_response(results, has_more=False, next_cursor=None):
    return {
        "object": "list",
        "results": results,
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


def _error_response(code="object_not_found", message="Not found", status=404):
    return {"object": "error", "code": code, "message": message, "status": status}


def _mock_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


# ---------------------------------------------------------------------------
# UUID validation tests
# ---------------------------------------------------------------------------


class TestUUIDValidation:
    def test_valid_uuid_no_dashes(self):
        assert _is_valid_id(_VALID_UUID) is True

    def test_valid_uuid_with_dashes(self):
        assert _is_valid_id(_VALID_UUID_DASHES) is True

    def test_invalid_short_string(self):
        assert _is_valid_id("abc123") is False

    def test_invalid_empty(self):
        assert _is_valid_id("") is False

    def test_invalid_non_hex(self):
        assert _is_valid_id("z" * 32) is False


# ---------------------------------------------------------------------------
# _NotionClient unit tests
# ---------------------------------------------------------------------------


class TestNotionClientPages:
    def setup_method(self):
        self.client = _NotionClient("ntn_test_key123")

    def test_create_page(self):
        with patch.object(self.client._client, "request", return_value=_mock_response(_page())):
            result = self.client.create_page(
                parent={"database_id": _VALID_UUID},
                properties={"Name": {"title": [{"text": {"content": "New"}}]}},
            )
        assert result["id"] == _VALID_UUID
        assert result["object"] == "page"

    def test_get_page(self):
        with patch.object(self.client._client, "request", return_value=_mock_response(_page())):
            result = self.client.get_page(_VALID_UUID)
        assert result["id"] == _VALID_UUID
        assert result["url"] == "https://www.notion.so/Test-Page-abc123"

    def test_update_page(self):
        updated = _page(archived=True)
        with patch.object(self.client._client, "request", return_value=_mock_response(updated)):
            result = self.client.update_page(_VALID_UUID, archived=True)
        assert result["archived"] is True

    def test_archive_page(self):
        archived = _page(archived=True)
        with patch.object(self.client._client, "request", return_value=_mock_response(archived)):
            result = self.client.archive_page(_VALID_UUID)
        assert result["archived"] is True

    def test_get_page_api_error(self):
        err = _error_response()
        with patch.object(self.client._client, "request", return_value=_mock_response(err, 404)):
            result = self.client.get_page(_VALID_UUID)
        assert "error" in result
        assert "object_not_found" in result["error"]


class TestNotionClientDatabases:
    def setup_method(self):
        self.client = _NotionClient("ntn_test_key123")

    def test_query_database(self):
        resp = _list_response([_page(), _page(id="b" * 32)])
        with patch.object(self.client._client, "request", return_value=_mock_response(resp)):
            result = self.client.query_database(_VALID_UUID)
        assert len(result["results"]) == 2
        assert result["has_more"] is False

    def test_query_database_with_filter(self):
        resp = _list_response([_page()])
        with patch.object(self.client._client, "request", return_value=_mock_response(resp)) as m:
            self.client.query_database(
                _VALID_UUID,
                filter={"property": "Status", "select": {"equals": "Done"}},
                sorts=[{"property": "Name", "direction": "ascending"}],
            )
        # Verify the request was made (filter passed through to API)
        m.assert_called_once()

    def test_query_database_page_size_capped(self):
        resp = _list_response([])
        with patch.object(self.client._client, "request", return_value=_mock_response(resp)):
            result = self.client.query_database(_VALID_UUID, page_size=500)
        assert result["results"] == []

    def test_get_database(self):
        with patch.object(self.client._client, "request", return_value=_mock_response(_database())):
            result = self.client.get_database(_VALID_UUID)
        assert result["id"] == _VALID_UUID
        assert result["object"] == "database"

    def test_create_database(self):
        with patch.object(self.client._client, "request", return_value=_mock_response(_database())):
            result = self.client.create_database(
                parent={"type": "page_id", "page_id": _VALID_UUID},
                title=[{"type": "text", "text": {"content": "New DB"}}],
                properties={"Name": {"title": {}}},
            )
        assert result["id"] == _VALID_UUID

    def test_update_database(self):
        updated = _database(title=[{"type": "text", "text": {"content": "Updated"}}])
        with patch.object(self.client._client, "request", return_value=_mock_response(updated)):
            result = self.client.update_database(
                _VALID_UUID,
                title=[{"type": "text", "text": {"content": "Updated"}}],
            )
        assert result["id"] == _VALID_UUID


class TestNotionClientBlocks:
    def setup_method(self):
        self.client = _NotionClient("ntn_test_key123")

    def test_get_block(self):
        with patch.object(self.client._client, "request", return_value=_mock_response(_block())):
            result = self.client.get_block(_VALID_UUID)
        assert result["id"] == _VALID_UUID
        assert result["type"] == "paragraph"

    def test_get_block_children(self):
        resp = _list_response([_block(), _block(id="b" * 32)])
        with patch.object(self.client._client, "request", return_value=_mock_response(resp)):
            result = self.client.get_block_children(_VALID_UUID)
        assert len(result["results"]) == 2

    def test_append_block_children(self):
        resp = _list_response([_block()])
        with patch.object(self.client._client, "request", return_value=_mock_response(resp)):
            result = self.client.append_block_children(
                _VALID_UUID,
                children=[{"object": "block", "type": "paragraph", "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": "New"}}]
                }}],
            )
        assert len(result["results"]) == 1

    def test_delete_block(self):
        deleted = _block(archived=True)
        with patch.object(self.client._client, "request", return_value=_mock_response(deleted)):
            result = self.client.delete_block(_VALID_UUID)
        assert result["archived"] is True


class TestNotionClientSearch:
    def setup_method(self):
        self.client = _NotionClient("ntn_test_key123")

    def test_search_pages(self):
        resp = _list_response([_page()])
        with patch.object(self.client._client, "request", return_value=_mock_response(resp)):
            result = self.client.search(query="Meeting", filter_object="page")
        assert len(result["results"]) == 1
        assert result["results"][0]["object"] == "page"

    def test_search_databases(self):
        resp = _list_response([_database()])
        with patch.object(self.client._client, "request", return_value=_mock_response(resp)):
            result = self.client.search(query="Tracker", filter_object="database")
        assert len(result["results"]) == 1
        assert result["results"][0]["object"] == "database"

    def test_search_empty_query(self):
        resp = _list_response([_page(), _database()])
        with patch.object(self.client._client, "request", return_value=_mock_response(resp)):
            result = self.client.search()
        assert len(result["results"]) == 2

    def test_search_with_pagination(self):
        resp = _list_response([_page()], has_more=True, next_cursor="cursor_abc")
        with patch.object(self.client._client, "request", return_value=_mock_response(resp)):
            result = self.client.search(query="test")
        assert result["has_more"] is True
        assert result["next_cursor"] == "cursor_abc"


class TestNotionClientUsers:
    def setup_method(self):
        self.client = _NotionClient("ntn_test_key123")

    def test_list_users(self):
        resp = _list_response([_user(), _user(id="b" * 32, name="User 2")])
        with patch.object(self.client._client, "request", return_value=_mock_response(resp)):
            result = self.client.list_users()
        assert len(result["users"]) == 2
        assert result["users"][0]["name"] == "Test User"

    def test_get_user(self):
        with patch.object(self.client._client, "request", return_value=_mock_response(_user())):
            result = self.client.get_user(_VALID_UUID)
        assert result["name"] == "Test User"
        assert result["type"] == "person"


class TestNotionClientComments:
    def setup_method(self):
        self.client = _NotionClient("ntn_test_key123")

    def test_create_comment(self):
        with patch.object(self.client._client, "request", return_value=_mock_response(_comment())):
            result = self.client.create_comment(
                parent={"page_id": _VALID_UUID},
                rich_text=[{"type": "text", "text": {"content": "Nice!"}}],
            )
        assert result["id"] == _VALID_UUID
        assert result["discussion_id"] == _VALID_UUID

    def test_list_comments(self):
        resp = _list_response([_comment(), _comment(id="b" * 32)])
        with patch.object(self.client._client, "request", return_value=_mock_response(resp)):
            result = self.client.list_comments(_VALID_UUID)
        assert len(result["comments"]) == 2


# ---------------------------------------------------------------------------
# MCP tool registration and credential tests
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_register_tools_registers_all_tools(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == 17

    def test_no_credentials_returns_error(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        with patch.dict("os.environ", {}, clear=True):
            register_tools(mcp, credentials=None)
            search_fn = next(f for f in registered_fns if f.__name__ == "notion_search")
            result = search_fn()

        assert "error" in result
        assert "not configured" in result["error"]

    def test_credentials_from_credential_manager(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        cred_manager = MagicMock()
        cred_manager.get.return_value = "ntn_test_fromcredstore"

        register_tools(mcp, credentials=cred_manager)

        fn = next(f for f in registered_fns if f.__name__ == "notion_list_users")

        with patch("aden_tools.tools.notion_tool.notion_tool._NotionClient") as MockClient:
            instance = MockClient.return_value
            instance.list_users.return_value = {"users": [], "has_more": False, "next_cursor": None}
            fn()

        MockClient.assert_called_once_with("ntn_test_fromcredstore")
        cred_manager.get.assert_called_with("notion")

    def test_credentials_from_env_vars(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        register_tools(mcp, credentials=None)

        fn = next(f for f in registered_fns if f.__name__ == "notion_list_users")

        with (
            patch.dict("os.environ", {"NOTION_API_KEY": "ntn_test_fromenv"}),
            patch("aden_tools.tools.notion_tool.notion_tool._NotionClient") as MockClient,
        ):
            instance = MockClient.return_value
            instance.list_users.return_value = {"users": [], "has_more": False, "next_cursor": None}
            fn()

        MockClient.assert_called_once_with("ntn_test_fromenv")

    def test_http_error_is_caught(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        cred_manager = MagicMock()
        cred_manager.get.return_value = "ntn_test_key"

        register_tools(mcp, credentials=cred_manager)

        fn = next(f for f in registered_fns if f.__name__ == "notion_list_users")

        with patch("aden_tools.tools.notion_tool.notion_tool._NotionClient") as MockClient:
            instance = MockClient.return_value
            instance.list_users.side_effect = httpx.ConnectError("Network error")
            result = fn()

        assert "error" in result


# ---------------------------------------------------------------------------
# Individual MCP tool validation tests
# ---------------------------------------------------------------------------


def _setup_tools():
    """Helper to register tools with a mock credential manager."""
    mcp = MagicMock()
    fns = []
    mcp.tool.return_value = lambda fn: fns.append(fn) or fn
    cred = MagicMock()
    cred.get.return_value = "ntn_test_key"
    register_tools(mcp, credentials=cred)
    fn_map = {f.__name__: f for f in fns}
    return fn_map


class TestPageToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_create_page_invalid_parent_type(self):
        result = self.fns["notion_create_page"](
            parent_type="invalid", parent_id=_VALID_UUID, properties={}
        )
        assert "error" in result
        assert "parent_type" in result["error"]

    def test_create_page_invalid_parent_id(self):
        result = self.fns["notion_create_page"](
            parent_type="database_id", parent_id=_INVALID_ID, properties={}
        )
        assert "error" in result
        assert "UUID" in result["error"]

    def test_get_page_invalid_id(self):
        result = self.fns["notion_get_page"](page_id=_INVALID_ID)
        assert "error" in result
        assert "UUID" in result["error"]

    def test_update_page_invalid_id(self):
        result = self.fns["notion_update_page"](page_id=_INVALID_ID)
        assert "error" in result
        assert "UUID" in result["error"]

    def test_archive_page_invalid_id(self):
        result = self.fns["notion_archive_page"](page_id=_INVALID_ID)
        assert "error" in result
        assert "UUID" in result["error"]

    def test_get_page_success(self):
        with patch("aden_tools.tools.notion_tool.notion_tool._NotionClient") as MockClient:
            MockClient.return_value.get_page.return_value = _page()
            result = self.fns["notion_get_page"](page_id=_VALID_UUID)
        assert result["id"] == _VALID_UUID

    def test_create_page_success(self):
        with patch("aden_tools.tools.notion_tool.notion_tool._NotionClient") as MockClient:
            MockClient.return_value.create_page.return_value = _page()
            result = self.fns["notion_create_page"](
                parent_type="database_id",
                parent_id=_VALID_UUID,
                properties={"Name": {"title": [{"text": {"content": "Test"}}]}},
            )
        assert result["id"] == _VALID_UUID


class TestDatabaseToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_query_database_invalid_id(self):
        result = self.fns["notion_query_database"](database_id=_INVALID_ID)
        assert "error" in result
        assert "UUID" in result["error"]

    def test_query_database_invalid_page_size(self):
        result = self.fns["notion_query_database"](database_id=_VALID_UUID, page_size=0)
        assert "error" in result
        assert "page_size" in result["error"]

    def test_get_database_invalid_id(self):
        result = self.fns["notion_get_database"](database_id=_INVALID_ID)
        assert "error" in result
        assert "UUID" in result["error"]

    def test_create_database_invalid_parent(self):
        result = self.fns["notion_create_database"](
            parent_id=_INVALID_ID, title="Test", properties={}
        )
        assert "error" in result
        assert "UUID" in result["error"]

    def test_create_database_empty_title(self):
        result = self.fns["notion_create_database"](
            parent_id=_VALID_UUID, title="", properties={}
        )
        assert "error" in result
        assert "title" in result["error"]

    def test_update_database_invalid_id(self):
        result = self.fns["notion_update_database"](database_id=_INVALID_ID)
        assert "error" in result
        assert "UUID" in result["error"]

    def test_query_database_success(self):
        with patch("aden_tools.tools.notion_tool.notion_tool._NotionClient") as MockClient:
            MockClient.return_value.query_database.return_value = {
                "results": [], "has_more": False, "next_cursor": None
            }
            result = self.fns["notion_query_database"](database_id=_VALID_UUID)
        assert "results" in result


class TestBlockToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_get_block_invalid_id(self):
        result = self.fns["notion_get_block"](block_id=_INVALID_ID)
        assert "error" in result
        assert "UUID" in result["error"]

    def test_get_block_children_invalid_id(self):
        result = self.fns["notion_get_block_children"](block_id=_INVALID_ID)
        assert "error" in result
        assert "UUID" in result["error"]

    def test_get_block_children_invalid_page_size(self):
        result = self.fns["notion_get_block_children"](block_id=_VALID_UUID, page_size=0)
        assert "error" in result
        assert "page_size" in result["error"]

    def test_append_block_children_invalid_id(self):
        result = self.fns["notion_append_block_children"](block_id=_INVALID_ID, children=[{}])
        assert "error" in result
        assert "UUID" in result["error"]

    def test_append_block_children_empty(self):
        result = self.fns["notion_append_block_children"](block_id=_VALID_UUID, children=[])
        assert "error" in result
        assert "empty" in result["error"]

    def test_delete_block_invalid_id(self):
        result = self.fns["notion_delete_block"](block_id=_INVALID_ID)
        assert "error" in result
        assert "UUID" in result["error"]


class TestSearchToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_search_invalid_filter_object(self):
        result = self.fns["notion_search"](filter_object="invalid")
        assert "error" in result
        assert "filter_object" in result["error"]

    def test_search_invalid_sort_direction(self):
        result = self.fns["notion_search"](sort_direction="invalid")
        assert "error" in result
        assert "sort_direction" in result["error"]

    def test_search_invalid_page_size(self):
        result = self.fns["notion_search"](page_size=0)
        assert "error" in result
        assert "page_size" in result["error"]

    def test_search_success(self):
        with patch("aden_tools.tools.notion_tool.notion_tool._NotionClient") as MockClient:
            MockClient.return_value.search.return_value = {
                "results": [], "has_more": False, "next_cursor": None
            }
            result = self.fns["notion_search"](query="test")
        assert "results" in result


class TestUserToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_list_users_invalid_page_size(self):
        result = self.fns["notion_list_users"](page_size=0)
        assert "error" in result
        assert "page_size" in result["error"]

    def test_get_user_invalid_id(self):
        result = self.fns["notion_get_user"](user_id=_INVALID_ID)
        assert "error" in result
        assert "UUID" in result["error"]

    def test_list_users_success(self):
        with patch("aden_tools.tools.notion_tool.notion_tool._NotionClient") as MockClient:
            MockClient.return_value.list_users.return_value = {
                "users": [], "has_more": False, "next_cursor": None
            }
            result = self.fns["notion_list_users"]()
        assert "users" in result


class TestCommentToolValidation:
    def setup_method(self):
        self.fns = _setup_tools()

    def test_create_comment_invalid_page_id(self):
        result = self.fns["notion_create_comment"](page_id=_INVALID_ID, text="Hello")
        assert "error" in result
        assert "UUID" in result["error"]

    def test_create_comment_empty_text(self):
        result = self.fns["notion_create_comment"](page_id=_VALID_UUID, text="")
        assert "error" in result
        assert "empty" in result["error"]

    def test_list_comments_invalid_id(self):
        result = self.fns["notion_list_comments"](block_id=_INVALID_ID)
        assert "error" in result
        assert "UUID" in result["error"]

    def test_list_comments_invalid_page_size(self):
        result = self.fns["notion_list_comments"](block_id=_VALID_UUID, page_size=0)
        assert "error" in result
        assert "page_size" in result["error"]

    def test_create_comment_success(self):
        with patch("aden_tools.tools.notion_tool.notion_tool._NotionClient") as MockClient:
            MockClient.return_value.create_comment.return_value = _comment()
            result = self.fns["notion_create_comment"](page_id=_VALID_UUID, text="Looks good")
        assert result["id"] == _VALID_UUID


# ---------------------------------------------------------------------------
# HTTP error propagation across tool categories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_name,kwargs",
    [
        ("notion_get_page", {"page_id": _VALID_UUID}),
        ("notion_get_database", {"database_id": _VALID_UUID}),
        ("notion_get_block", {"block_id": _VALID_UUID}),
        ("notion_search", {}),
        ("notion_get_user", {"user_id": _VALID_UUID}),
        ("notion_list_users", {}),
        ("notion_list_comments", {"block_id": _VALID_UUID}),
    ],
)
def test_http_error_propagation(tool_name, kwargs):
    fns = _setup_tools()
    with patch("aden_tools.tools.notion_tool.notion_tool._NotionClient") as MockClient:
        method_name = tool_name.replace("notion_", "")
        getattr(MockClient.return_value, method_name).side_effect = httpx.ConnectError(
            "Network error"
        )
        result = fns[tool_name](**kwargs)
    assert "error" in result


# ---------------------------------------------------------------------------
# Credential spec tests
# ---------------------------------------------------------------------------


class TestCredentialSpec:
    def test_notion_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "notion" in CREDENTIAL_SPECS

    def test_notion_spec_env_var(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["notion"]
        assert spec.env_var == "NOTION_API_KEY"

    def test_notion_spec_tool_count(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["notion"]
        assert len(spec.tools) == 17

    def test_notion_spec_tools_include_core_methods(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["notion"]
        expected = [
            "notion_create_page",
            "notion_get_page",
            "notion_update_page",
            "notion_archive_page",
            "notion_query_database",
            "notion_get_database",
            "notion_create_database",
            "notion_update_database",
            "notion_get_block",
            "notion_get_block_children",
            "notion_append_block_children",
            "notion_delete_block",
            "notion_search",
            "notion_list_users",
            "notion_get_user",
            "notion_create_comment",
            "notion_list_comments",
        ]
        for tool in expected:
            assert tool in spec.tools, f"Missing tool in credential spec: {tool}"

    def test_notion_spec_health_check(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["notion"]
        assert spec.health_check_endpoint == "https://api.notion.com/v1/users/me"
        assert spec.health_check_method == "GET"

    def test_notion_spec_auth_support(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["notion"]
        assert spec.aden_supported is False
        assert spec.direct_api_key_supported is True
        assert "notion.so/my-integrations" in spec.api_key_instructions

    def test_notion_spec_credential_store_fields(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["notion"]
        assert spec.credential_id == "notion"
        assert spec.credential_key == "api_key"
        assert spec.credential_group == ""

    def test_notion_spec_required_not_startup(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["notion"]
        assert spec.required is True
        assert spec.startup_required is False
