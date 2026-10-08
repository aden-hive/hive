"""Tests for docker_hub_tool - Docker Hub repository and tag management."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.docker_hub_tool.docker_hub_tool import register_tools

ENV = {"DOCKER_HUB_TOKEN": "test-token"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestDockerHubSearch:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["docker_hub_search"](query="nginx")
        assert "error" in result

    def test_empty_query(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["docker_hub_search"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_resp = {
            "results": [
                {
                    "repo_name": "library/nginx",
                    "short_description": "Official NGINX image",
                    "star_count": 18000,
                    "is_official": True,
                    "is_automated": False,
                    "pull_count": 1000000000,
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.docker_hub_tool.docker_hub_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["docker_hub_search"](query="nginx")

        assert result["query"] == "nginx"
        assert len(result["results"]) == 1
        assert result["results"][0]["is_official"] is True


class TestDockerHubListTags:
    def test_missing_repository(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["docker_hub_list_tags"](repository="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {
            "results": [
                {
                    "name": "latest",
                    "full_size": 50000000,
                    "last_updated": "2024-01-01T00:00:00Z",
                    "images": [{"digest": "sha256:abc123"}],
                },
                {
                    "name": "1.25",
                    "full_size": 48000000,
                    "last_updated": "2024-01-01T00:00:00Z",
                    "images": [{"digest": "sha256:def456"}],
                },
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.docker_hub_tool.docker_hub_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["docker_hub_list_tags"](repository="library/nginx")

        assert result["repository"] == "library/nginx"
        assert len(result["tags"]) == 2
        assert result["tags"][0]["name"] == "latest"


class TestDockerHubGetRepo:
    def test_missing_repository(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["docker_hub_get_repo"](repository="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = {
            "name": "nginx",
            "namespace": "library",
            "description": "Official NGINX image",
            "star_count": 18000,
            "pull_count": 1000000000,
            "last_updated": "2024-01-01T00:00:00Z",
            "is_private": False,
            "full_description": "# NGINX\nOfficial image for NGINX.",
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.docker_hub_tool.docker_hub_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["docker_hub_get_repo"](repository="library/nginx")

        assert result["name"] == "nginx"
        assert result["star_count"] == 18000


class TestDockerHubListRepos:
    def test_missing_namespace(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["docker_hub_list_repos"](namespace="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {
            "results": [
                {
                    "name": "myapp",
                    "namespace": "myuser",
                    "description": "My app",
                    "star_count": 5,
                    "pull_count": 1000,
                    "last_updated": "2024-06-01T00:00:00Z",
                    "is_private": False,
                }
            ]
        }
        with (
            patch.dict("os.environ", {**ENV, "DOCKER_HUB_USERNAME": "myuser"}),
            patch("aden_tools.tools.docker_hub_tool.docker_hub_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["docker_hub_list_repos"](namespace="myuser")

        assert result["namespace"] == "myuser"
        assert len(result["repos"]) == 1
