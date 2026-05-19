"""Tests for notion_tool - Pages, databases, and search."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.notion_tool.notion_tool import register_tools

ENV = {"NOTION_API_TOKEN": "test-token"}
PATCH_BASE = "aden_tools.tools.notion_tool.notion_tool"


def _mock_resp(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = ""
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


# ---------------------------------------------------------------------------
# _request error handling (applies to all tools via shared helper)
# ---------------------------------------------------------------------------


class TestRequestErrors:
    """Test HTTP error codes, timeouts, and exceptions in _request."""

    @pytest.mark.parametrize(
        ("status_code", "expected_fragment"),
        [
            (401, "Unauthorized"),
            (403, "Forbidden"),
            (404, "Not found"),
            (429, "Rate limited"),
            (500, "Notion API error 500"),
        ],
    )
    def test_http_error_codes(self, tool_fns, status_code, expected_fragment):
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.post",
                return_value=_mock_resp({}, status_code),
            ),
        ):
            result = tool_fns["notion_search"](query="test")
        assert "error" in result
        assert expected_fragment in result["error"]

    def test_timeout_exception(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.post",
                side_effect=httpx.TimeoutException("timed out"),
            ),
        ):
            result = tool_fns["notion_search"](query="test")
        assert "error" in result
        assert "timed out" in result["error"]

    def test_generic_exception(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.post",
                side_effect=ConnectionError("connection refused"),
            ),
        ):
            result = tool_fns["notion_search"](query="test")
        assert "error" in result
        assert "connection refused" in result["error"]


# ---------------------------------------------------------------------------
# Credential store adapter
# ---------------------------------------------------------------------------


class TestCredentialStoreAdapter:
    def test_credential_store_used_when_provided(self, mcp: FastMCP):
        mock_creds = MagicMock()
        mock_creds.get.return_value = "store-token"
        register_tools(mcp, credentials=mock_creds)
        tools = mcp._tool_manager._tools
        fn = tools["notion_search"].fn

        data = {"results": [], "has_more": False}
        with patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data)) as mock_post:
            result = fn(query="test")

        mock_creds.get.assert_called_with("notion_token")
        assert result["count"] == 0
        # Verify the token from the store was used in the Authorization header
        call_kwargs = mock_post.call_args
        assert "Bearer store-token" in call_kwargs.kwargs.get("headers", {}).get(
            "Authorization", call_kwargs[1].get("headers", {}).get("Authorization", "")
        )


# ---------------------------------------------------------------------------
# notion_search
# ---------------------------------------------------------------------------


class TestNotionSearch:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["notion_search"]()
        assert "error" in result

    def test_successful_search(self, tool_fns):
        data = {
            "results": [
                {
                    "object": "page",
                    "id": "page-1",
                    "url": "https://notion.so/page-1",
                    "created_time": "2024-01-01T00:00:00Z",
                    "last_edited_time": "2024-01-15T00:00:00Z",
                    "properties": {
                        "Name": {
                            "type": "title",
                            "title": [{"text": {"content": "My Page"}}],
                        }
                    },
                }
            ],
            "has_more": False,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data)),
        ):
            result = tool_fns["notion_search"](query="My Page")

        assert result["count"] == 1
        assert result["results"][0]["title"] == "My Page"

    def test_filter_type_page(self, tool_fns):
        data = {"results": [], "has_more": False}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data)) as mock_post,
        ):
            tool_fns["notion_search"](filter_type="page")

        body = mock_post.call_args.kwargs["json"]
        assert body["filter"] == {"property": "object", "value": "page"}

    def test_filter_type_database(self, tool_fns):
        data = {
            "results": [
                {
                    "object": "database",
                    "id": "db-1",
                    "url": "https://notion.so/db-1",
                    "created_time": "2024-01-01T00:00:00Z",
                    "last_edited_time": "2024-01-15T00:00:00Z",
                    "title": [{"text": {"content": "My DB"}}],
                }
            ],
            "has_more": True,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data)),
        ):
            result = tool_fns["notion_search"](filter_type="database")

        assert result["results"][0]["title"] == "My DB"
        assert result["has_more"] is True

    def test_filter_type_invalid_ignored(self, tool_fns):
        data = {"results": [], "has_more": False}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data)) as mock_post,
        ):
            tool_fns["notion_search"](filter_type="invalid")

        body = mock_post.call_args.kwargs["json"]
        assert "filter" not in body

    def test_page_size_clamped(self, tool_fns):
        data = {"results": [], "has_more": False}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data)) as mock_post,
        ):
            tool_fns["notion_search"](page_size=0)
        assert mock_post.call_args.kwargs["json"]["page_size"] == 1

        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data)) as mock_post,
        ):
            tool_fns["notion_search"](page_size=200)
        assert mock_post.call_args.kwargs["json"]["page_size"] == 100


# ---------------------------------------------------------------------------
# notion_get_page
# ---------------------------------------------------------------------------


class TestNotionGetPage:
    def test_missing_page_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_get_page"](page_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "id": "page-1",
            "url": "https://notion.so/page-1",
            "archived": False,
            "created_time": "2024-01-01T00:00:00Z",
            "last_edited_time": "2024-01-15T00:00:00Z",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"text": {"content": "Test Page"}}],
                },
                "Status": {
                    "type": "select",
                    "select": {"name": "Done"},
                },
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["notion_get_page"](page_id="page-1")

        assert result["title"] == "Test Page"
        assert result["properties"]["Status"] == "Done"

    def test_all_property_types(self, tool_fns):
        data = {
            "id": "page-1",
            "url": "https://notion.so/page-1",
            "archived": False,
            "created_time": "2024-01-01T00:00:00Z",
            "last_edited_time": "2024-01-15T00:00:00Z",
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"text": {"content": "Test"}}],
                },
                "Description": {
                    "type": "rich_text",
                    "rich_text": [
                        {"text": {"content": "Hello "}},
                        {"text": {"content": "World"}},
                    ],
                },
                "Tags": {
                    "type": "multi_select",
                    "multi_select": [{"name": "bug"}, {"name": "urgent"}],
                },
                "Priority": {
                    "type": "number",
                    "number": 5,
                },
                "Done": {
                    "type": "checkbox",
                    "checkbox": True,
                },
                "Due": {
                    "type": "date",
                    "date": {"start": "2024-06-01"},
                },
                "Progress": {
                    "type": "status",
                    "status": {"name": "In Progress"},
                },
                "EmptySelect": {
                    "type": "select",
                    "select": None,
                },
                "EmptyDate": {
                    "type": "date",
                    "date": None,
                },
                "EmptyStatus": {
                    "type": "status",
                    "status": None,
                },
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["notion_get_page"](page_id="page-1")

        props = result["properties"]
        assert props["Description"] == "Hello World"
        assert props["Tags"] == ["bug", "urgent"]
        assert props["Priority"] == 5
        assert props["Done"] is True
        assert props["Due"] == "2024-06-01"
        assert props["Progress"] == "In Progress"
        assert props["EmptySelect"] == ""
        assert props["EmptyDate"] == ""
        assert props["EmptyStatus"] == ""


# ---------------------------------------------------------------------------
# notion_create_page
# ---------------------------------------------------------------------------


class TestNotionCreatePage:
    def test_missing_title(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_create_page"](title="")
        assert "error" in result
        assert "title is required" in result["error"]

    def test_missing_parent(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_create_page"](title="Test")
        assert "error" in result
        assert "parent_database_id or parent_page_id" in result["error"]

    def test_both_parents(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_create_page"](
                title="Test",
                parent_database_id="db-1",
                parent_page_id="page-1",
            )
        assert "error" in result
        assert "not both" in result["error"]

    def test_successful_create(self, tool_fns):
        data = {"id": "new-page", "url": "https://notion.so/new-page"}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data, 201)),
        ):
            result = tool_fns["notion_create_page"](
                parent_database_id="db-1",
                title="New Page",
                title_property="Name",
            )

        assert result["status"] == "created"
        assert result["id"] == "new-page"

    def test_missing_title_property_for_database(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_create_page"](
                parent_database_id="db-1",
                title="New Page",
            )

        assert "error" in result
        assert "title_property is required" in result["error"]

    def test_with_properties_json(self, tool_fns):
        data = {"id": "new-page", "url": "https://notion.so/new-page"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.post",
                return_value=_mock_resp(data, 201),
            ) as mock_post,
        ):
            result = tool_fns["notion_create_page"](
                parent_database_id="db-1",
                title="New Page",
                title_property="Name",
                properties_json='{"Status": {"select": {"name": "Open"}}}',
            )

        assert result["status"] == "created"
        body = mock_post.call_args.kwargs["json"]
        assert body["properties"]["Status"] == {"select": {"name": "Open"}}

    def test_with_content(self, tool_fns):
        data = {"id": "new-page", "url": "https://notion.so/new-page"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.post",
                return_value=_mock_resp(data, 201),
            ) as mock_post,
        ):
            result = tool_fns["notion_create_page"](
                parent_database_id="db-1",
                title="New Page",
                title_property="Name",
                content="Some body text",
            )

        assert result["status"] == "created"
        body = mock_post.call_args.kwargs["json"]
        assert len(body["children"]) == 1
        assert body["children"][0]["type"] == "paragraph"

    def test_custom_title_property(self, tool_fns):
        data = {"id": "new-page", "url": "https://notion.so/new-page"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.post",
                return_value=_mock_resp(data, 201),
            ) as mock_post,
        ):
            result = tool_fns["notion_create_page"](
                parent_database_id="db-1",
                title="My Task",
                title_property="Task name",
            )

        assert result["status"] == "created"
        body = mock_post.call_args.kwargs["json"]
        assert "Task name" in body["properties"]
        assert "Name" not in body["properties"]

    def test_invalid_properties_json(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_create_page"](
                parent_database_id="db-1",
                title="New Page",
                title_property="Name",
                properties_json="not valid json{{{",
            )
        assert "error" in result
        assert "not valid JSON" in result["error"]

    def test_create_under_parent_page(self, tool_fns):
        data = {"id": "child-page", "url": "https://notion.so/child-page"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.post",
                return_value=_mock_resp(data, 201),
            ) as mock_post,
        ):
            result = tool_fns["notion_create_page"](
                parent_page_id="parent-page-1",
                title="Child Page",
                content="Some content",
            )

        assert result["status"] == "created"
        assert result["id"] == "child-page"
        body = mock_post.call_args.kwargs["json"]
        assert body["parent"] == {"page_id": "parent-page-1"}
        assert body["properties"]["title"]["title"][0]["text"]["content"] == "Child Page"
        assert len(body["children"]) == 1

    def test_create_under_parent_page_ignores_properties_json(self, tool_fns):
        data = {"id": "child-page", "url": "https://notion.so/child-page"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.post",
                return_value=_mock_resp(data, 201),
            ) as mock_post,
        ):
            result = tool_fns["notion_create_page"](
                parent_page_id="parent-page-1",
                title="Child Page",
                properties_json='{"Status": {"select": {"name": "Open"}}}',
            )

        assert result["status"] == "created"
        body = mock_post.call_args.kwargs["json"]
        # properties_json is ignored for page parents
        assert "Status" not in body.get("properties", {})


# ---------------------------------------------------------------------------
# notion_update_page
# ---------------------------------------------------------------------------


class TestNotionUpdatePage:
    def test_missing_page_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_update_page"](page_id="")
        assert "error" in result

    def test_no_updates_provided(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_update_page"](page_id="page-1")
        assert "error" in result
        assert "No updates" in result["error"]

    def test_successful_update_properties(self, tool_fns):
        data = {"id": "page-1", "url": "https://notion.so/page-1"}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.patch", return_value=_mock_resp(data)) as mock_patch,
        ):
            result = tool_fns["notion_update_page"](
                page_id="page-1",
                properties_json='{"Status": {"select": {"name": "Done"}}}',
            )

        assert result["status"] == "updated"
        body = mock_patch.call_args.kwargs["json"]
        assert body["properties"]["Status"] == {"select": {"name": "Done"}}

    def test_archive_page(self, tool_fns):
        data = {"id": "page-1", "url": "https://notion.so/page-1"}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.patch", return_value=_mock_resp(data)) as mock_patch,
        ):
            result = tool_fns["notion_update_page"](page_id="page-1", archived=True)

        assert result["status"] == "updated"
        body = mock_patch.call_args.kwargs["json"]
        assert body["archived"] is True

    def test_invalid_properties_json(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_update_page"](
                page_id="page-1",
                properties_json="{bad json",
            )
        assert "error" in result
        assert "not valid JSON" in result["error"]

    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["notion_update_page"](
                page_id="page-1",
                properties_json='{"Status": {"select": {"name": "Done"}}}',
            )
        assert "error" in result


# ---------------------------------------------------------------------------
# notion_query_database
# ---------------------------------------------------------------------------


class TestNotionQueryDatabase:
    def test_missing_database_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_query_database"](database_id="")
        assert "error" in result

    def test_successful_query(self, tool_fns):
        data = {
            "results": [
                {
                    "id": "row-1",
                    "url": "https://notion.so/row-1",
                    "created_time": "2024-01-01T00:00:00Z",
                    "last_edited_time": "2024-01-15T00:00:00Z",
                    "properties": {
                        "Name": {
                            "type": "title",
                            "title": [{"text": {"content": "Task 1"}}],
                        }
                    },
                }
            ],
            "has_more": False,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data)),
        ):
            result = tool_fns["notion_query_database"](database_id="db-1")

        assert result["count"] == 1
        assert result["pages"][0]["title"] == "Task 1"

    def test_with_filter_json(self, tool_fns):
        data = {"results": [], "has_more": False}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data)) as mock_post,
        ):
            tool_fns["notion_query_database"](
                database_id="db-1",
                filter_json='{"property": "Status", "select": {"equals": "Done"}}',
            )

        body = mock_post.call_args.kwargs["json"]
        assert body["filter"]["property"] == "Status"

    def test_invalid_filter_json(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_query_database"](
                database_id="db-1",
                filter_json="not json!!!",
            )
        assert "error" in result
        assert "not valid JSON" in result["error"]

    def test_page_size_clamped(self, tool_fns):
        data = {"results": [], "has_more": False}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data)) as mock_post,
        ):
            tool_fns["notion_query_database"](database_id="db-1", page_size=0)
        assert mock_post.call_args.kwargs["json"]["page_size"] == 1

    def test_with_sorts_json(self, tool_fns):
        data = {"results": [], "has_more": False}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data)) as mock_post,
        ):
            tool_fns["notion_query_database"](
                database_id="db-1",
                sorts_json='[{"property": "Created", "direction": "descending"}]',
            )

        body = mock_post.call_args.kwargs["json"]
        assert body["sorts"][0]["property"] == "Created"
        assert body["sorts"][0]["direction"] == "descending"

    def test_invalid_sorts_json(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_query_database"](
                database_id="db-1",
                sorts_json="not json!!!",
            )
        assert "error" in result
        assert "not valid JSON" in result["error"]

    def test_with_start_cursor(self, tool_fns):
        data = {"results": [], "has_more": False}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data)) as mock_post,
        ):
            tool_fns["notion_query_database"](
                database_id="db-1",
                start_cursor="cursor-abc-123",
            )

        body = mock_post.call_args.kwargs["json"]
        assert body["start_cursor"] == "cursor-abc-123"

    def test_next_cursor_returned(self, tool_fns):
        data = {"results": [], "has_more": True, "next_cursor": "cursor-next-456"}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(data)),
        ):
            result = tool_fns["notion_query_database"](database_id="db-1")

        assert result["has_more"] is True
        assert result["next_cursor"] == "cursor-next-456"


# ---------------------------------------------------------------------------
# notion_get_database
# ---------------------------------------------------------------------------


class TestNotionGetDatabase:
    def test_missing_database_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_get_database"](database_id="")
        assert "error" in result

    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["notion_get_database"](database_id="db-1")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "id": "db-1",
            "title": [{"text": {"content": "Tasks"}}],
            "url": "https://notion.so/db-1",
            "created_time": "2024-01-01T00:00:00Z",
            "last_edited_time": "2024-01-15T00:00:00Z",
            "properties": {
                "Name": {"type": "title", "id": "title"},
                "Status": {"type": "select", "id": "abc"},
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["notion_get_database"](database_id="db-1")

        assert result["title"] == "Tasks"
        assert "Name" in result["properties"]


# ---------------------------------------------------------------------------
# notion_create_database
# ---------------------------------------------------------------------------


class TestNotionCreateDatabase:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_create_database"](parent_page_id="", title="")
        assert "error" in result

    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["notion_create_database"](parent_page_id="page-1", title="My DB")
        assert "error" in result

    def test_successful_create_default_properties(self, tool_fns):
        data = {"id": "db-new", "url": "https://notion.so/db-new"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.post",
                return_value=_mock_resp(data, 201),
            ) as mock_post,
        ):
            result = tool_fns["notion_create_database"](parent_page_id="page-1", title="Tasks")

        assert result["status"] == "created"
        assert result["id"] == "db-new"
        body = mock_post.call_args.kwargs["json"]
        assert body["parent"]["page_id"] == "page-1"
        assert "Name" in body["properties"]
        assert body["properties"]["Name"] == {"title": {}}

    def test_with_extra_properties(self, tool_fns):
        data = {"id": "db-new", "url": "https://notion.so/db-new"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.post",
                return_value=_mock_resp(data, 201),
            ) as mock_post,
        ):
            result = tool_fns["notion_create_database"](
                parent_page_id="page-1",
                title="Tasks",
                properties_json='{"Priority": {"number": {}}}',
            )

        assert result["status"] == "created"
        body = mock_post.call_args.kwargs["json"]
        assert "Priority" in body["properties"]
        assert "Name" in body["properties"]

    def test_invalid_properties_json(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_create_database"](
                parent_page_id="page-1",
                title="Tasks",
                properties_json="{bad",
            )
        assert "error" in result
        assert "not valid JSON" in result["error"]


# ---------------------------------------------------------------------------
# notion_update_database
# ---------------------------------------------------------------------------


class TestNotionUpdateDatabase:
    def test_missing_database_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_update_database"](database_id="")
        assert "error" in result

    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["notion_update_database"](database_id="db-1", title="New Title")
        assert "error" in result

    def test_no_updates_provided(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_update_database"](database_id="db-1")
        assert "error" in result
        assert "No updates" in result["error"]

    def test_update_title(self, tool_fns):
        data = {"id": "db-1", "url": "https://notion.so/db-1"}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.patch", return_value=_mock_resp(data)) as mock_patch,
        ):
            result = tool_fns["notion_update_database"](database_id="db-1", title="Renamed DB")

        assert result["status"] == "updated"
        body = mock_patch.call_args.kwargs["json"]
        assert body["title"][0]["text"]["content"] == "Renamed DB"

    def test_update_properties(self, tool_fns):
        data = {"id": "db-1", "url": "https://notion.so/db-1"}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.patch", return_value=_mock_resp(data)) as mock_patch,
        ):
            result = tool_fns["notion_update_database"](
                database_id="db-1",
                properties_json='{"Priority": {"number": {}}}',
            )

        assert result["status"] == "updated"
        body = mock_patch.call_args.kwargs["json"]
        assert body["properties"]["Priority"] == {"number": {}}

    def test_archive_database(self, tool_fns):
        data = {"id": "db-1", "url": "https://notion.so/db-1"}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.patch", return_value=_mock_resp(data)) as mock_patch,
        ):
            result = tool_fns["notion_update_database"](database_id="db-1", archived=True)

        assert result["status"] == "updated"
        body = mock_patch.call_args.kwargs["json"]
        assert body["archived"] is True

    def test_invalid_properties_json(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_update_database"](
                database_id="db-1",
                properties_json="not json",
            )
        assert "error" in result
        assert "not valid JSON" in result["error"]


# ---------------------------------------------------------------------------
# notion_get_block_children
# ---------------------------------------------------------------------------


class TestNotionGetBlockChildren:
    def test_missing_block_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_get_block_children"](block_id="")
        assert "error" in result

    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["notion_get_block_children"](block_id="page-1")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "results": [
                {
                    "id": "block-1",
                    "type": "paragraph",
                    "has_children": False,
                    "paragraph": {
                        "rich_text": [{"text": {"content": "Hello world"}}],
                    },
                },
                {
                    "id": "block-2",
                    "type": "heading_2",
                    "has_children": False,
                    "heading_2": {
                        "rich_text": [{"text": {"content": "Section"}}],
                    },
                },
                {
                    "id": "block-3",
                    "type": "divider",
                    "has_children": False,
                    "divider": {},
                },
            ],
            "has_more": False,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["notion_get_block_children"](block_id="page-1")

        assert result["count"] == 3
        assert result["blocks"][0]["text"] == "Hello world"
        assert result["blocks"][1]["text"] == "Section"
        # divider has no rich_text, so no "text" key
        assert "text" not in result["blocks"][2]


# ---------------------------------------------------------------------------
# notion_get_block
# ---------------------------------------------------------------------------


class TestNotionGetBlock:
    def test_missing_block_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_get_block"](block_id="")
        assert "error" in result

    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["notion_get_block"](block_id="block-1")
        assert "error" in result

    def test_successful_get_paragraph(self, tool_fns):
        data = {
            "id": "block-1",
            "type": "paragraph",
            "has_children": False,
            "archived": False,
            "created_time": "2024-01-01T00:00:00Z",
            "last_edited_time": "2024-01-15T00:00:00Z",
            "paragraph": {
                "rich_text": [{"text": {"content": "Hello world"}}],
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["notion_get_block"](block_id="block-1")

        assert result["id"] == "block-1"
        assert result["type"] == "paragraph"
        assert result["text"] == "Hello world"
        assert result["archived"] is False

    def test_block_without_text(self, tool_fns):
        data = {
            "id": "block-2",
            "type": "divider",
            "has_children": False,
            "archived": False,
            "created_time": "2024-01-01T00:00:00Z",
            "last_edited_time": "2024-01-15T00:00:00Z",
            "divider": {},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["notion_get_block"](block_id="block-2")

        assert result["type"] == "divider"
        assert "text" not in result


# ---------------------------------------------------------------------------
# notion_update_block
# ---------------------------------------------------------------------------


class TestNotionUpdateBlock:
    def test_missing_block_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_update_block"](block_id="")
        assert "error" in result

    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["notion_update_block"](
                block_id="block-1", content="text", block_type="paragraph"
            )
        assert "error" in result

    def test_no_updates_provided(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_update_block"](block_id="block-1")
        assert "error" in result
        assert "No updates" in result["error"]

    def test_content_without_block_type(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_update_block"](block_id="block-1", content="new text")
        assert "error" in result
        assert "block_type is required" in result["error"]

    def test_successful_content_update(self, tool_fns):
        data = {"id": "block-1", "type": "paragraph"}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.patch", return_value=_mock_resp(data)) as mock_patch,
        ):
            result = tool_fns["notion_update_block"](
                block_id="block-1", content="Updated text", block_type="paragraph"
            )

        assert result["status"] == "updated"
        body = mock_patch.call_args.kwargs["json"]
        assert body["paragraph"]["rich_text"][0]["text"]["content"] == "Updated text"

    def test_invalid_block_type(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_update_block"](
                block_id="block-1", content="text", block_type="invalid_type"
            )
        assert "error" in result
        assert "Invalid block_type" in result["error"]

    def test_archive_block(self, tool_fns):
        data = {"id": "block-1", "type": "paragraph"}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.patch", return_value=_mock_resp(data)) as mock_patch,
        ):
            result = tool_fns["notion_update_block"](block_id="block-1", archived=True)

        assert result["status"] == "updated"
        body = mock_patch.call_args.kwargs["json"]
        assert body["archived"] is True


# ---------------------------------------------------------------------------
# notion_delete_block
# ---------------------------------------------------------------------------


class TestNotionDeleteBlock:
    def test_missing_block_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_delete_block"](block_id="")
        assert "error" in result

    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["notion_delete_block"](block_id="block-1")
        assert "error" in result

    def test_successful_delete(self, tool_fns):
        data = {"id": "block-1", "archived": True}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.delete", return_value=_mock_resp(data)),
        ):
            result = tool_fns["notion_delete_block"](block_id="block-1")

        assert result["status"] == "deleted"
        assert result["id"] == "block-1"


# ---------------------------------------------------------------------------
# notion_append_blocks
# ---------------------------------------------------------------------------


class TestNotionAppendBlocks:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_append_blocks"](block_id="", content="")
        assert "error" in result

    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["notion_append_blocks"](block_id="page-1", content="text")
        assert "error" in result

    def test_successful_append(self, tool_fns):
        data = {"results": []}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.patch", return_value=_mock_resp(data)) as mock_patch,
        ):
            result = tool_fns["notion_append_blocks"](
                block_id="page-1",
                content="First paragraph\nSecond paragraph",
            )

        assert result["status"] == "appended"
        assert result["blocks_added"] == 2
        assert result["block_id"] == "page-1"
        body = mock_patch.call_args.kwargs["json"]
        assert len(body["children"]) == 2
        assert body["children"][0]["type"] == "paragraph"

    def test_blank_lines_stripped(self, tool_fns):
        data = {"results": []}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.patch", return_value=_mock_resp(data)) as mock_patch,
        ):
            result = tool_fns["notion_append_blocks"](
                block_id="page-1",
                content="Line one\n\n\nLine two",
            )

        assert result["blocks_added"] == 2
        body = mock_patch.call_args.kwargs["json"]
        assert len(body["children"]) == 2

    def test_only_blank_lines(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_append_blocks"](
                block_id="page-1",
                content="\n\n\n",
            )
        assert "error" in result
        assert "empty" in result["error"]

    def test_block_type_heading(self, tool_fns):
        data = {"results": []}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.patch", return_value=_mock_resp(data)) as mock_patch,
        ):
            result = tool_fns["notion_append_blocks"](
                block_id="page-1",
                content="Section Title",
                block_type="heading_1",
            )

        assert result["blocks_added"] == 1
        body = mock_patch.call_args.kwargs["json"]
        assert body["children"][0]["type"] == "heading_1"

    def test_block_type_to_do(self, tool_fns):
        data = {"results": []}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.patch", return_value=_mock_resp(data)) as mock_patch,
        ):
            result = tool_fns["notion_append_blocks"](
                block_id="page-1",
                content="Buy milk\nWalk the dog",
                block_type="to_do",
            )

        assert result["blocks_added"] == 2
        body = mock_patch.call_args.kwargs["json"]
        assert body["children"][0]["type"] == "to_do"
        assert body["children"][0]["to_do"]["checked"] is False

    def test_invalid_block_type(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_append_blocks"](
                block_id="page-1",
                content="text",
                block_type="invalid_type",
            )
        assert "error" in result
        assert "Invalid block_type" in result["error"]

    def test_exceeds_100_block_limit(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["notion_append_blocks"](
                block_id="page-1",
                content="\n".join(f"line {i}" for i in range(101)),
            )
        assert "error" in result
        assert "100" in result["error"]
