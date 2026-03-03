"""Tests for attio_tool - Attio CRM record, list, and task management."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.attio_tool.attio_tool import register_tools

ENV = {"ATTIO_API_KEY": "test-token"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestAttioListObjects:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["attio_list_objects"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {
            "data": [
                {"api_slug": "people", "singular_noun": "Person", "plural_noun": "People"},
                {"api_slug": "companies", "singular_noun": "Company", "plural_noun": "Companies"},
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.attio_tool.attio_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["attio_list_objects"]()

        assert len(result["objects"]) == 2
        assert result["objects"][0]["api_slug"] == "people"


class TestAttioListRecords:
    def test_missing_slug(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["attio_list_records"](object_slug="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {
            "data": [
                {
                    "id": {"record_id": "rec-1", "object_id": "obj-1"},
                    "created_at": "2024-01-01T00:00:00Z",
                    "web_url": "https://app.attio.com/record/rec-1",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.attio_tool.attio_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["attio_list_records"](object_slug="people")

        assert result["object"] == "people"
        assert len(result["records"]) == 1
        assert result["records"][0]["record_id"] == "rec-1"


class TestAttioSearchRecords:
    def test_empty_query(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["attio_search_records"](object_slug="people", query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_resp = {
            "data": [
                {
                    "id": {"record_id": "rec-1"},
                    "created_at": "2024-01-01T00:00:00Z",
                    "web_url": "https://app.attio.com/record/rec-1",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.attio_tool.attio_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["attio_search_records"](object_slug="people", query="Ada")

        assert result["query"] == "Ada"
        assert len(result["results"]) == 1


class TestAttioCreateRecord:
    def test_missing_values(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["attio_create_record"](object_slug="people")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        mock_resp = {
            "data": {
                "id": {"record_id": "rec-new"},
                "web_url": "https://app.attio.com/record/rec-new",
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.attio_tool.attio_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["attio_create_record"](
                object_slug="people", values={"name": "Ada Lovelace"}
            )

        assert result["status"] == "created"
        assert result["record_id"] == "rec-new"


class TestAttioListLists:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "data": [
                {
                    "id": {"list_id": "lst-1"},
                    "name": "Pipeline",
                    "api_slug": "pipeline",
                    "parent_object": "deals",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.attio_tool.attio_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["attio_list_lists"]()

        assert len(result["lists"]) == 1
        assert result["lists"][0]["name"] == "Pipeline"


class TestAttioListEntries:
    def test_missing_slug(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["attio_list_entries"](list_slug="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {
            "data": [
                {
                    "id": {"entry_id": "ent-1", "list_id": "lst-1"},
                    "parent_record_id": "rec-1",
                    "created_at": "2024-01-01T00:00:00Z",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.attio_tool.attio_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["attio_list_entries"](list_slug="pipeline")

        assert len(result["entries"]) == 1
        assert result["entries"][0]["entry_id"] == "ent-1"


class TestAttioCreateNote:
    def test_missing_fields(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["attio_create_note"](
                parent_object="", parent_record_id="", title="", content=""
            )
        assert "error" in result

    def test_successful_create(self, tool_fns):
        mock_resp = {"data": {"id": {"note_id": "note-1"}}}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.attio_tool.attio_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["attio_create_note"](
                parent_object="people",
                parent_record_id="rec-1",
                title="Meeting notes",
                content="Discussed Q4 plans",
            )

        assert result["status"] == "created"
        assert result["note_id"] == "note-1"


class TestAttioListTasks:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "data": [
                {
                    "id": {"task_id": "task-1"},
                    "content_plaintext": "Follow up with prospect",
                    "is_completed": False,
                    "deadline_at": "2024-06-15T00:00:00Z",
                    "assignees": [{"referenced_actor_id": "user-1"}],
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.attio_tool.attio_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["attio_list_tasks"]()

        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["content"] == "Follow up with prospect"
