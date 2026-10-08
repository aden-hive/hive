"""Tests for pipedrive_tool - Pipedrive CRM deal, contact, and pipeline management."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.pipedrive_tool.pipedrive_tool import register_tools

ENV = {"PIPEDRIVE_API_TOKEN": "test-token"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestPipedriveListDeals:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["pipedrive_list_deals"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {
            "success": True,
            "data": [
                {
                    "id": 1,
                    "title": "Big Deal",
                    "value": 10000,
                    "currency": "USD",
                    "status": "open",
                    "person_id": {"name": "John Doe"},
                    "org_id": {"name": "Acme Corp"},
                    "stage_id": 1,
                    "add_time": "2024-01-01",
                }
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pipedrive_tool.pipedrive_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["pipedrive_list_deals"]()

        assert len(result["deals"]) == 1
        assert result["deals"][0]["title"] == "Big Deal"
        assert result["deals"][0]["person_name"] == "John Doe"


class TestPipedriveGetDeal:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pipedrive_get_deal"](deal_id=0)
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = {
            "success": True,
            "data": {
                "id": 1,
                "title": "Big Deal",
                "value": 10000,
                "currency": "USD",
                "status": "open",
                "person_id": {"name": "John Doe"},
                "org_id": {"name": "Acme Corp"},
                "stage_id": 1,
                "pipeline_id": 1,
                "add_time": "2024-01-01",
                "expected_close_date": "2024-06-01",
                "probability": 75,
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pipedrive_tool.pipedrive_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["pipedrive_get_deal"](deal_id=1)

        assert result["title"] == "Big Deal"
        assert result["probability"] == 75


class TestPipedriveCreateDeal:
    def test_missing_title(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pipedrive_create_deal"](title="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        mock_resp = {"success": True, "data": {"id": 42, "title": "New Deal"}}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pipedrive_tool.pipedrive_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["pipedrive_create_deal"](title="New Deal", value=5000)

        assert result["status"] == "created"
        assert result["id"] == 42


class TestPipedriveListPersons:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "success": True,
            "data": [
                {
                    "id": 10,
                    "name": "Jane Smith",
                    "email": [{"value": "jane@example.com"}],
                    "phone": [{"value": "+1234567890"}],
                    "org_id": {"name": "Acme Corp"},
                    "open_deals_count": 2,
                }
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pipedrive_tool.pipedrive_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["pipedrive_list_persons"]()

        assert len(result["persons"]) == 1
        assert result["persons"][0]["name"] == "Jane Smith"
        assert result["persons"][0]["email"] == "jane@example.com"


class TestPipedriveSearchPersons:
    def test_empty_query(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pipedrive_search_persons"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_resp = {
            "success": True,
            "data": {
                "items": [
                    {
                        "item": {
                            "id": 10,
                            "name": "Jane Smith",
                            "emails": ["jane@example.com"],
                            "phones": ["+1234567890"],
                            "organization": {"name": "Acme Corp"},
                        }
                    }
                ]
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pipedrive_tool.pipedrive_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["pipedrive_search_persons"](query="Jane")

        assert len(result["results"]) == 1
        assert result["results"][0]["name"] == "Jane Smith"


class TestPipedriveListOrganizations:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "success": True,
            "data": [
                {
                    "id": 5,
                    "name": "Acme Corp",
                    "address": "123 Main St",
                    "open_deals_count": 3,
                    "people_count": 5,
                }
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pipedrive_tool.pipedrive_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["pipedrive_list_organizations"]()

        assert len(result["organizations"]) == 1
        assert result["organizations"][0]["name"] == "Acme Corp"


class TestPipedriveListActivities:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "success": True,
            "data": [
                {
                    "id": 100,
                    "subject": "Follow-up call",
                    "type": "call",
                    "done": False,
                    "due_date": "2024-06-15",
                    "due_time": "14:00",
                    "deal_title": "Big Deal",
                    "person_name": "John Doe",
                    "org_name": "Acme Corp",
                    "note": "Discuss pricing",
                }
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pipedrive_tool.pipedrive_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["pipedrive_list_activities"]()

        assert len(result["activities"]) == 1
        assert result["activities"][0]["subject"] == "Follow-up call"
        assert result["activities"][0]["type"] == "call"


class TestPipedriveListPipelines:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "success": True,
            "data": [
                {
                    "id": 1,
                    "name": "Sales Pipeline",
                    "active": True,
                    "deal_probability": True,
                    "order_nr": 1,
                }
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pipedrive_tool.pipedrive_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["pipedrive_list_pipelines"]()

        assert len(result["pipelines"]) == 1
        assert result["pipelines"][0]["name"] == "Sales Pipeline"


class TestPipedriveListStages:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "success": True,
            "data": [
                {
                    "id": 1,
                    "name": "Qualified",
                    "pipeline_id": 1,
                    "order_nr": 1,
                    "active_flag": True,
                }
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pipedrive_tool.pipedrive_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["pipedrive_list_stages"](pipeline_id=1)

        assert len(result["stages"]) == 1
        assert result["stages"][0]["name"] == "Qualified"


class TestPipedriveAddNote:
    def test_missing_content(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pipedrive_add_note"](content="")
        assert "error" in result

    def test_missing_target(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pipedrive_add_note"](content="A note")
        assert "error" in result

    def test_successful_add(self, tool_fns):
        mock_resp = {"success": True, "data": {"id": 200}}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pipedrive_tool.pipedrive_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["pipedrive_add_note"](content="Follow up", deal_id=1)

        assert result["status"] == "created"
        assert result["id"] == 200
