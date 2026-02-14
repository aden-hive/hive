"""
Tests for Attio CRM tool.

Covers:
- _AttioClient methods (records, lists, tasks, members)
- REST request construction and response handling
- Error handling (401, 403, 429, 204, generic errors)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 15 MCP tool functions
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aden_tools.tools.attio_tool.attio_tool import (
    ATTIO_API_BASE,
    _AttioClient,
    register_tools,
)

# --- _AttioClient tests ---


class TestAttioClient:
    def setup_method(self):
        self.client = _AttioClient("test_api_key")

    def test_headers(self):
        headers = self.client._headers
        assert headers["Authorization"] == "Bearer test_api_key"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": [{"id": "rec-123"}]}
        result = self.client._handle_response(response)
        assert result == {"data": [{"id": "rec-123"}]}

    def test_handle_response_204_no_content(self):
        response = MagicMock()
        response.status_code = 204
        result = self.client._handle_response(response)
        assert result == {"success": True}

    @pytest.mark.parametrize(
        "status_code,expected_substring",
        [
            (401, "Invalid or expired"),
            (403, "Insufficient permissions"),
            (429, "rate limit"),
        ],
    )
    def test_handle_response_errors(self, status_code, expected_substring):
        response = MagicMock()
        response.status_code = status_code
        result = self.client._handle_response(response)
        assert "error" in result
        assert expected_substring in result["error"]

    def test_handle_response_generic_error(self):
        response = MagicMock()
        response.status_code = 500
        response.json.return_value = {"message": "Internal Server Error"}
        result = self.client._handle_response(response)
        assert "error" in result
        assert "500" in result["error"]

    def test_handle_response_generic_error_no_json(self):
        response = MagicMock()
        response.status_code = 502
        response.json.side_effect = Exception("not json")
        response.text = "Bad Gateway"
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Bad Gateway" in result["error"]

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_request_get(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        result = self.client._request("GET", "/workspace_members")

        mock_request.assert_called_once_with(
            "GET",
            f"{ATTIO_API_BASE}/workspace_members",
            headers=self.client._headers,
            json=None,
            params=None,
            timeout=30.0,
        )
        assert result == {"data": []}

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_request_post_with_body(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "rec-1"}]}
        mock_request.return_value = mock_response

        body = {"limit": 10, "offset": 0}
        result = self.client._request("POST", "/objects/people/records/query", json_body=body)

        call_kwargs = mock_request.call_args.kwargs
        assert call_kwargs["json"] == body
        assert result == {"data": [{"id": "rec-1"}]}

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_request_with_params(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"id": "rec-1"}}
        mock_request.return_value = mock_response

        params = {"matching_attribute": "email_addresses"}
        result = self.client._request(
            "PUT", "/objects/people/records", json_body={}, params=params
        )

        call_kwargs = mock_request.call_args.kwargs
        assert call_kwargs["params"] == params

    # --- Record Operations ---

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_list_records(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": {"record_id": "rec-1"}},
                {"id": {"record_id": "rec-2"}},
            ]
        }
        mock_request.return_value = mock_response

        result = self.client.list_records("people", limit=10)

        assert result["total"] == 2
        assert len(result["records"]) == 2

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_list_records_with_filter(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        filter_data = {"email_addresses": {"contains": "example.com"}}
        self.client.list_records("people", filter_data=filter_data)

        call_kwargs = mock_request.call_args.kwargs
        body = call_kwargs["json"]
        assert body["filter"] == filter_data

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_list_records_error(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_request.return_value = mock_response

        result = self.client.list_records("people")
        assert "error" in result

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_get_record(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "id": {"record_id": "rec-123"},
                "values": {"name": [{"first_name": "Jane"}]},
            }
        }
        mock_request.return_value = mock_response

        result = self.client.get_record("people", "rec-123")

        assert result["id"]["record_id"] == "rec-123"

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_create_record(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "id": {"record_id": "rec-new"},
                "values": {"name": [{"first_name": "John"}]},
            }
        }
        mock_request.return_value = mock_response

        values = {"name": [{"first_name": "John", "last_name": "Doe"}]}
        result = self.client.create_record("people", values)

        assert result["id"]["record_id"] == "rec-new"
        call_kwargs = mock_request.call_args.kwargs
        assert call_kwargs["json"] == {"data": {"values": values}}

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_update_record(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"id": {"record_id": "rec-123"}, "values": {"name": [{"first_name": "Updated"}]}}
        }
        mock_request.return_value = mock_response

        values = {"name": [{"first_name": "Updated"}]}
        result = self.client.update_record("people", "rec-123", values)

        assert result["values"]["name"][0]["first_name"] == "Updated"

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_assert_record(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"id": {"record_id": "rec-upserted"}}
        }
        mock_request.return_value = mock_response

        values = {"email_addresses": [{"email_address": "test@example.com"}]}
        result = self.client.assert_record("people", "email_addresses", values)

        assert result["id"]["record_id"] == "rec-upserted"
        call_kwargs = mock_request.call_args.kwargs
        assert call_kwargs["params"] == {"matching_attribute": "email_addresses"}

    # --- List Operations ---

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_list_lists(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "list-1", "name": "Sales Pipeline"}]
        }
        mock_request.return_value = mock_response

        result = self.client.list_lists()

        assert result["total"] == 1
        assert result["lists"][0]["name"] == "Sales Pipeline"

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_get_entries(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "entry-1"}, {"id": "entry-2"}]
        }
        mock_request.return_value = mock_response

        result = self.client.get_entries("list-1")

        assert result["total"] == 2
        assert len(result["entries"]) == 2

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_create_entry(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"id": "entry-new"}}
        mock_request.return_value = mock_response

        result = self.client.create_entry("list-1", "rec-123", "people")

        assert result["id"] == "entry-new"
        call_kwargs = mock_request.call_args.kwargs
        body = call_kwargs["json"]
        assert body["data"]["parent_record_id"] == "rec-123"
        assert body["data"]["parent_object"] == "people"

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_create_entry_with_values(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"id": "entry-new"}}
        mock_request.return_value = mock_response

        entry_values = {"stage": "qualified"}
        result = self.client.create_entry("list-1", "rec-123", entry_values=entry_values)

        call_kwargs = mock_request.call_args.kwargs
        body = call_kwargs["json"]
        assert body["data"]["entry_values"] == entry_values

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_delete_entry(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_request.return_value = mock_response

        result = self.client.delete_entry("list-1", "entry-1")

        assert result == {"success": True}

    # --- Task Operations ---

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_create_task(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "id": "task-new",
                "content": "Follow up with Jane",
                "is_completed": False,
            }
        }
        mock_request.return_value = mock_response

        result = self.client.create_task(
            content="Follow up with Jane",
            linked_records=[{"target_object": "people", "target_record_id": "rec-123"}],
            deadline_at="2026-03-15T00:00:00Z",
        )

        assert result["id"] == "task-new"
        assert result["content"] == "Follow up with Jane"

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_list_tasks(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"id": "task-1"}, {"id": "task-2"}]
        }
        mock_request.return_value = mock_response

        result = self.client.list_tasks()

        assert result["total"] == 2
        assert len(result["tasks"]) == 2

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_get_task(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"id": "task-1", "content": "Call back"}
        }
        mock_request.return_value = mock_response

        result = self.client.get_task("task-1")

        assert result["id"] == "task-1"

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_delete_task(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_request.return_value = mock_response

        result = self.client.delete_task("task-1")

        assert result == {"success": True}

    # --- Workspace Members ---

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_list_members(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "member-1", "first_name": "Alice"},
                {"id": "member-2", "first_name": "Bob"},
            ]
        }
        mock_request.return_value = mock_response

        result = self.client.list_members()

        assert result["total"] == 2
        assert result["members"][0]["first_name"] == "Alice"

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_get_member(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"id": "member-1", "first_name": "Alice", "email_address": "alice@co.com"}
        }
        mock_request.return_value = mock_response

        result = self.client.get_member("member-1")

        assert result["first_name"] == "Alice"


# --- Tool Registration tests ---


class TestToolRegistration:
    def setup_method(self):
        from fastmcp import FastMCP

        self.mcp = FastMCP("test")
        register_tools(self.mcp, credentials=None)

    def test_tool_count(self):
        """All 15 Attio tools should be registered."""
        tools = self.mcp._tool_manager._tools
        attio_tools = [name for name in tools if name.startswith("attio_")]
        assert len(attio_tools) == 15

    def test_all_tool_names_registered(self):
        """Every expected tool name is registered."""
        expected = [
            "attio_record_list",
            "attio_record_get",
            "attio_record_create",
            "attio_record_update",
            "attio_record_assert",
            "attio_list_lists",
            "attio_list_entries_get",
            "attio_list_entry_create",
            "attio_list_entry_delete",
            "attio_task_create",
            "attio_task_list",
            "attio_task_get",
            "attio_task_delete",
            "attio_members_list",
            "attio_member_get",
        ]
        tools = self.mcp._tool_manager._tools
        for name in expected:
            assert name in tools, f"Tool '{name}' not registered"


class TestCredentialRetrieval:
    def test_credential_from_env(self, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "env-test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        # Should not return error when env var is set
        tool_fn = mcp._tool_manager._tools["attio_members_list"].fn
        with patch("aden_tools.tools.attio_tool.attio_tool.httpx.request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"data": []}
            mock_req.return_value = mock_resp
            result = tool_fn()
            assert "error" not in result

    def test_no_credentials_returns_error(self, monkeypatch):
        monkeypatch.delenv("ATTIO_API_KEY", raising=False)
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        tool_fn = mcp._tool_manager._tools["attio_members_list"].fn
        result = tool_fn()
        assert "error" in result
        assert "not configured" in result["error"]
        assert "help" in result

    def test_credential_from_store(self, monkeypatch):
        monkeypatch.delenv("ATTIO_API_KEY", raising=False)
        from fastmcp import FastMCP

        mock_creds = MagicMock()
        mock_creds.get.return_value = "store-test-key"

        mcp = FastMCP("test")
        register_tools(mcp, credentials=mock_creds)

        tool_fn = mcp._tool_manager._tools["attio_members_list"].fn
        with patch("aden_tools.tools.attio_tool.attio_tool.httpx.request") as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"data": []}
            mock_req.return_value = mock_resp
            result = tool_fn()
            assert "error" not in result
            mock_creds.get.assert_called_with("attio")


# --- MCP Tool Error Handling ---


class TestToolErrorHandling:
    def setup_method(self):
        from fastmcp import FastMCP

        self.mcp = FastMCP("test")
        register_tools(self.mcp, credentials=None)

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_timeout_error(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")

        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_request.side_effect = httpx.TimeoutException("timed out")
        tool_fn = mcp._tool_manager._tools["attio_members_list"].fn
        result = tool_fn()
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_network_error(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")

        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_request.side_effect = httpx.RequestError("connection refused")
        tool_fn = mcp._tool_manager._tools["attio_members_list"].fn
        result = tool_fn()
        assert "error" in result
        assert "Network error" in result["error"]


# --- Record Tool tests ---


class TestRecordTools:
    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_record_list(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": {"record_id": "r1"}}]}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_record_list"].fn
        result = tool_fn(object_handle="people", limit=10)
        assert result["total"] == 1

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_record_list_with_filter_json(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_record_list"].fn
        result = tool_fn(
            object_handle="people",
            filter_json='{"name": {"contains": "Jane"}}',
        )
        assert "error" not in result

    def test_record_list_invalid_filter_json(self, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        tool_fn = mcp._tool_manager._tools["attio_record_list"].fn
        result = tool_fn(object_handle="people", filter_json="not valid json")
        assert "error" in result
        assert "Invalid filter_json" in result["error"]

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_record_get(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"id": {"record_id": "r1"}}}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_record_get"].fn
        result = tool_fn(object_handle="people", record_id="r1")
        assert result["id"]["record_id"] == "r1"

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_record_create(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"id": {"record_id": "r-new"}}}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_record_create"].fn
        result = tool_fn(
            object_handle="people",
            values={"name": [{"first_name": "John"}]},
        )
        assert result["id"]["record_id"] == "r-new"

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_record_update(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"id": {"record_id": "r1"}}}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_record_update"].fn
        result = tool_fn(
            object_handle="people",
            record_id="r1",
            values={"name": [{"first_name": "Updated"}]},
        )
        assert "error" not in result

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_record_assert(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"id": {"record_id": "r-upserted"}}}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_record_assert"].fn
        result = tool_fn(
            object_handle="people",
            matching_attribute="email_addresses",
            values={"email_addresses": [{"email_address": "test@example.com"}]},
        )
        assert result["id"]["record_id"] == "r-upserted"


# --- List Tool tests ---


class TestListTools:
    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_list_lists(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "list-1"}]}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_list_lists"].fn
        result = tool_fn()
        assert result["total"] == 1

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_list_entries_get(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "e1"}, {"id": "e2"}]}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_list_entries_get"].fn
        result = tool_fn(list_id="list-1")
        assert result["total"] == 2

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_list_entry_create(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"id": "entry-new"}}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_list_entry_create"].fn
        result = tool_fn(list_id="list-1", parent_record_id="rec-123")
        assert result["id"] == "entry-new"

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_list_entry_delete(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_list_entry_delete"].fn
        result = tool_fn(list_id="list-1", entry_id="entry-1")
        assert result == {"success": True}


# --- Task Tool tests ---


class TestTaskTools:
    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_task_create(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"id": "task-new", "content": "Follow up"}}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_task_create"].fn
        result = tool_fn(content="Follow up")
        assert result["id"] == "task-new"

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_task_list(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "t1"}, {"id": "t2"}]}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_task_list"].fn
        result = tool_fn()
        assert result["total"] == 2

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_task_get(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"id": "t1", "content": "Review"}}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_task_get"].fn
        result = tool_fn(task_id="t1")
        assert result["id"] == "t1"

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_task_delete(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_task_delete"].fn
        result = tool_fn(task_id="t1")
        assert result == {"success": True}


# --- Member Tool tests ---


class TestMemberTools:
    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_members_list(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"id": "m1"}]}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_members_list"].fn
        result = tool_fn()
        assert result["total"] == 1

    @patch("aden_tools.tools.attio_tool.attio_tool.httpx.request")
    def test_member_get(self, mock_request, monkeypatch):
        monkeypatch.setenv("ATTIO_API_KEY", "test-key")
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_tools(mcp, credentials=None)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"id": "m1", "first_name": "Alice"}}
        mock_request.return_value = mock_resp

        tool_fn = mcp._tool_manager._tools["attio_member_get"].fn
        result = tool_fn(member_id="m1")
        assert result["first_name"] == "Alice"
