"""Tests for vercel_tool - Vercel deployment and hosting management."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.vercel_tool.vercel_tool import register_tools

ENV = {"VERCEL_TOKEN": "test-token"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestVercelListDeployments:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["vercel_list_deployments"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {
            "deployments": [
                {
                    "uid": "dpl_1",
                    "name": "my-app",
                    "url": "my-app-abc.vercel.app",
                    "state": "READY",
                    "created": 1700000000000,
                    "target": "production",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.vercel_tool.vercel_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["vercel_list_deployments"]()

        assert len(result["deployments"]) == 1
        assert result["deployments"][0]["state"] == "READY"


class TestVercelGetDeployment:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["vercel_get_deployment"](deployment_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = {
            "id": "dpl_1",
            "name": "my-app",
            "url": "my-app-abc.vercel.app",
            "readyState": "READY",
            "target": "production",
            "createdAt": 1700000000000,
            "ready": 1700000001000,
            "creator": {"username": "admin"},
            "meta": {"githubCommitRef": "main"},
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.vercel_tool.vercel_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["vercel_get_deployment"](deployment_id="dpl_1")

        assert result["state"] == "READY"
        assert result["creator"] == "admin"


class TestVercelListProjects:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "projects": [
                {
                    "id": "prj_1",
                    "name": "my-app",
                    "framework": "nextjs",
                    "updatedAt": 1700000000000,
                    "latestDeployments": [{"url": "my-app-abc.vercel.app"}],
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.vercel_tool.vercel_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["vercel_list_projects"]()

        assert len(result["projects"]) == 1
        assert result["projects"][0]["framework"] == "nextjs"


class TestVercelListProjectDomains:
    def test_missing_project_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["vercel_list_project_domains"](project_id="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {
            "domains": [{"name": "example.com", "redirect": "", "gitBranch": "", "verified": True}]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.vercel_tool.vercel_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["vercel_list_project_domains"](project_id="prj_1")

        assert result["domains"][0]["name"] == "example.com"


class TestVercelEnvVars:
    def test_list_env_vars(self, tool_fns):
        mock_resp = {
            "envs": [
                {"id": "env_1", "key": "API_KEY", "target": ["production"], "type": "encrypted"}
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.vercel_tool.vercel_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["vercel_list_env_vars"](project_id="prj_1")

        assert len(result["env_vars"]) == 1
        assert result["env_vars"][0]["key"] == "API_KEY"

    def test_create_env_var_missing_fields(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["vercel_create_env_var"](project_id="", key="", value="")
        assert "error" in result

    def test_create_env_var_success(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.vercel_tool.vercel_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"id": "env_2", "key": "DB_URL"}
            result = tool_fns["vercel_create_env_var"](
                project_id="prj_1", key="DB_URL", value="postgres://..."
            )

        assert result["status"] == "created"
        assert result["key"] == "DB_URL"
