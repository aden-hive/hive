"""Tests for greenhouse_tool - ATS & recruiting workflow."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.greenhouse_tool.greenhouse_tool import register_tools

ENV = {"GREENHOUSE_API_TOKEN": "test-token"}


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


class TestGreenhouseListJobs:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["greenhouse_list_jobs"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        jobs = [
            {
                "id": 1,
                "name": "Software Engineer",
                "status": "open",
                "departments": [{"name": "Engineering"}],
                "offices": [{"name": "SF"}],
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-15T00:00:00Z",
            }
        ]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.greenhouse_tool.greenhouse_tool.httpx.get",
                return_value=_mock_resp(jobs),
            ),
        ):
            result = tool_fns["greenhouse_list_jobs"]()

        assert result["count"] == 1
        assert result["jobs"][0]["name"] == "Software Engineer"
        assert result["jobs"][0]["departments"] == ["Engineering"]


class TestGreenhouseGetJob:
    def test_missing_job_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["greenhouse_get_job"](job_id=0)
        assert "error" in result

    def test_successful_get(self, tool_fns):
        job = {
            "id": 1,
            "name": "Software Engineer",
            "status": "open",
            "confidential": False,
            "departments": [{"name": "Engineering"}],
            "offices": [{"name": "SF"}],
            "openings": [{"id": 10, "status": "open"}],
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-15T00:00:00Z",
            "notes": "Expanding team",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.greenhouse_tool.greenhouse_tool.httpx.get",
                return_value=_mock_resp(job),
            ),
        ):
            result = tool_fns["greenhouse_get_job"](job_id=1)

        assert result["name"] == "Software Engineer"
        assert result["openings"][0]["status"] == "open"


class TestGreenhouseListCandidates:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["greenhouse_list_candidates"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        candidates = [
            {
                "id": 100,
                "first_name": "John",
                "last_name": "Smith",
                "company": "Acme",
                "title": "Developer",
                "tags": ["senior"],
                "application_ids": [200],
                "created_at": "2024-03-01T00:00:00Z",
            }
        ]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.greenhouse_tool.greenhouse_tool.httpx.get",
                return_value=_mock_resp(candidates),
            ),
        ):
            result = tool_fns["greenhouse_list_candidates"]()

        assert result["count"] == 1
        assert result["candidates"][0]["first_name"] == "John"


class TestGreenhouseGetCandidate:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["greenhouse_get_candidate"](candidate_id=0)
        assert "error" in result

    def test_successful_get(self, tool_fns):
        candidate = {
            "id": 100,
            "first_name": "John",
            "last_name": "Smith",
            "company": "Acme",
            "title": "Developer",
            "email_addresses": [{"value": "john@example.com", "type": "personal"}],
            "phone_numbers": [{"value": "555-1234", "type": "mobile"}],
            "tags": ["senior"],
            "application_ids": [200],
            "created_at": "2024-03-01T00:00:00Z",
            "updated_at": "2024-03-10T00:00:00Z",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.greenhouse_tool.greenhouse_tool.httpx.get",
                return_value=_mock_resp(candidate),
            ),
        ):
            result = tool_fns["greenhouse_get_candidate"](candidate_id=100)

        assert result["first_name"] == "John"
        assert result["emails"] == ["john@example.com"]


class TestGreenhouseListApplications:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["greenhouse_list_applications"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        apps = [
            {
                "id": 200,
                "candidate_id": 100,
                "status": "active",
                "current_stage": {"id": 3, "name": "Technical Interview"},
                "jobs": [{"id": 1, "name": "Software Engineer"}],
                "applied_at": "2024-03-01T00:00:00Z",
                "last_activity_at": "2024-03-10T00:00:00Z",
            }
        ]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.greenhouse_tool.greenhouse_tool.httpx.get",
                return_value=_mock_resp(apps),
            ),
        ):
            result = tool_fns["greenhouse_list_applications"]()

        assert result["count"] == 1
        assert result["applications"][0]["current_stage"] == "Technical Interview"


class TestGreenhouseGetApplication:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["greenhouse_get_application"](application_id=0)
        assert "error" in result

    def test_successful_get(self, tool_fns):
        app = {
            "id": 200,
            "candidate_id": 100,
            "status": "active",
            "current_stage": {"id": 3, "name": "Technical Interview"},
            "source": {"id": 5, "public_name": "LinkedIn"},
            "jobs": [{"id": 1, "name": "Software Engineer"}],
            "answers": [{"question": "Work authorized?", "answer": "Yes"}],
            "applied_at": "2024-03-01T00:00:00Z",
            "rejected_at": None,
            "last_activity_at": "2024-03-10T00:00:00Z",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.greenhouse_tool.greenhouse_tool.httpx.get",
                return_value=_mock_resp(app),
            ),
        ):
            result = tool_fns["greenhouse_get_application"](application_id=200)

        assert result["source"] == "LinkedIn"
        assert result["answers"][0]["answer"] == "Yes"
