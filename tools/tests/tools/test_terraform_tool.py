"""Tests for terraform_tool - Terraform Cloud workspace and run management."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.terraform_tool.terraform_tool import register_tools

ENV = {"TFC_TOKEN": "test-token"}


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


class TestTerraformListWorkspaces:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["terraform_list_workspaces"](organization="my-org")
        assert "error" in result

    def test_missing_organization(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["terraform_list_workspaces"](organization="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "data": [
                {
                    "id": "ws-abc123",
                    "type": "workspaces",
                    "attributes": {
                        "name": "production",
                        "terraform-version": "1.9.0",
                        "execution-mode": "remote",
                        "auto-apply": False,
                        "locked": False,
                        "resource-count": 42,
                        "created-at": "2024-01-15T10:30:00Z",
                        "updated-at": "2024-01-15T10:30:00Z",
                    },
                }
            ],
            "meta": {
                "pagination": {
                    "total-count": 1,
                    "total-pages": 1,
                }
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.terraform_tool.terraform_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["terraform_list_workspaces"](organization="my-org")

        assert result["count"] == 1
        assert result["workspaces"][0]["name"] == "production"
        assert result["workspaces"][0]["id"] == "ws-abc123"
        assert result["workspaces"][0]["resource_count"] == 42


class TestTerraformGetWorkspace:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["terraform_get_workspace"](workspace_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "data": {
                "id": "ws-abc123",
                "type": "workspaces",
                "attributes": {
                    "name": "production",
                    "description": "Production infra",
                    "terraform-version": "1.9.0",
                    "execution-mode": "remote",
                    "auto-apply": True,
                    "locked": False,
                    "resource-count": 42,
                    "vcs-repo": {"identifier": "org/repo", "branch": "main"},
                    "working-directory": "infra/",
                    "created-at": "2024-01-15T10:30:00Z",
                    "updated-at": "2024-01-15T10:30:00Z",
                },
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.terraform_tool.terraform_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["terraform_get_workspace"](workspace_id="ws-abc123")

        assert result["name"] == "production"
        assert result["description"] == "Production infra"
        assert result["working_directory"] == "infra/"


class TestTerraformListRuns:
    def test_missing_workspace(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["terraform_list_runs"](workspace_id="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "data": [
                {
                    "id": "run-xyz789",
                    "type": "runs",
                    "attributes": {
                        "status": "applied",
                        "message": "Deploy v2",
                        "source": "tfe-api",
                        "trigger-reason": "manual",
                        "is-destroy": False,
                        "plan-only": False,
                        "has-changes": True,
                        "auto-apply": True,
                        "created-at": "2024-01-15T11:00:00Z",
                    },
                }
            ],
            "meta": {
                "pagination": {
                    "total-count": 1,
                    "total-pages": 1,
                }
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.terraform_tool.terraform_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["terraform_list_runs"](workspace_id="ws-abc123")

        assert result["count"] == 1
        assert result["runs"][0]["status"] == "applied"
        assert result["runs"][0]["message"] == "Deploy v2"


class TestTerraformGetRun:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["terraform_get_run"](run_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "data": {
                "id": "run-xyz789",
                "type": "runs",
                "attributes": {
                    "status": "planned",
                    "message": "Plan only",
                    "source": "tfe-ui",
                    "trigger-reason": "manual",
                    "is-destroy": False,
                    "plan-only": True,
                    "has-changes": True,
                    "auto-apply": False,
                    "created-at": "2024-01-15T11:00:00Z",
                    "status-timestamps": {"plan-queued-at": "2024-01-15T11:00:01Z"},
                    "permissions": {"can-apply": True},
                },
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.terraform_tool.terraform_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["terraform_get_run"](run_id="run-xyz789")

        assert result["status"] == "planned"
        assert result["plan_only"] is True


class TestTerraformCreateRun:
    def test_missing_workspace(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["terraform_create_run"](workspace_id="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        data = {
            "data": {
                "id": "run-new123",
                "type": "runs",
                "attributes": {
                    "status": "pending",
                    "message": "Deploy via API",
                    "source": "tfe-api",
                    "trigger-reason": "manual",
                    "is-destroy": False,
                    "plan-only": False,
                    "has-changes": None,
                    "auto-apply": True,
                    "created-at": "2024-01-15T12:00:00Z",
                },
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.terraform_tool.terraform_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["terraform_create_run"](
                workspace_id="ws-abc123",
                message="Deploy via API",
                auto_apply=True,
            )

        assert result["id"] == "run-new123"
        assert result["status"] == "pending"
