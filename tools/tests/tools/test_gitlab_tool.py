"""
Tests for GitLab tool (FastMCP).

Tests cover:
- GitLabClient methods (list_projects, list_issues, get_merge_request,
  create_issue, trigger_pipeline)
- Credential integration
- Error handling
"""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.credentials import CREDENTIAL_SPECS, CredentialManager
from aden_tools.tools.gitlab_tool.gitlab import (
    DEFAULT_GITLAB_URL,
    GitLabClient,
    _get_client,
    register_tools,
)


@pytest.fixture
def mcp():
    """Create a FastMCP server for testing."""
    return FastMCP("test-gitlab")


@pytest.fixture
def mock_client():
    """Create a GitLabClient with mock credentials."""
    return GitLabClient(access_token="test-token")


class TestGitLabClient:
    """Tests for GitLabClient class."""

    @patch("aden_tools.tools.gitlab_tool.gitlab.httpx.Client")
    def test_list_projects_success(self, mock_client_class, mock_client):
        """Test successful project listing."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"id": 123, "name": "my-project", "path_with_namespace": "mygroup/my-project"},
            {"id": 456, "name": "other-project", "path_with_namespace": "mygroup/other-project"},
        ]
        mock_response.raise_for_status = MagicMock()

        mock_http_client = MagicMock()
        mock_http_client.request.return_value = mock_response
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_http_client

        projects = mock_client.list_projects()

        assert len(projects) == 2
        assert projects[0]["name"] == "my-project"
        assert projects[1]["id"] == 456

    @patch("aden_tools.tools.gitlab_tool.gitlab.httpx.Client")
    def test_list_projects_with_search(self, mock_client_class, mock_client):
        """Test project listing with search filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"id": 123, "name": "search-result"}
        ]
        mock_response.raise_for_status = MagicMock()

        mock_http_client = MagicMock()
        mock_http_client.request.return_value = mock_response
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_http_client

        projects = mock_client.list_projects(search="search-result", owned=True)

        assert len(projects) == 1
        # Verify search param was passed
        call_args = mock_http_client.request.call_args
        assert call_args[1]["params"]["search"] == "search-result"
        assert call_args[1]["params"]["owned"] == "true"

    @patch("aden_tools.tools.gitlab_tool.gitlab.httpx.Client")
    def test_list_issues_success(self, mock_client_class, mock_client):
        """Test successful issue listing."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"iid": 1, "title": "Bug report", "state": "opened"},
            {"iid": 2, "title": "Feature request", "state": "opened"},
        ]
        mock_response.raise_for_status = MagicMock()

        mock_http_client = MagicMock()
        mock_http_client.request.return_value = mock_response
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_http_client

        issues = mock_client.list_issues(project_id="123", state="opened")

        assert len(issues) == 2
        assert issues[0]["title"] == "Bug report"

    @patch("aden_tools.tools.gitlab_tool.gitlab.httpx.Client")
    def test_list_issues_with_labels(self, mock_client_class, mock_client):
        """Test issue listing with label filter."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"iid": 1, "title": "Bug", "labels": ["bug", "critical"]}
        ]
        mock_response.raise_for_status = MagicMock()

        mock_http_client = MagicMock()
        mock_http_client.request.return_value = mock_response
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_http_client

        issues = mock_client.list_issues(
            project_id="mygroup/myproject",
            labels=["bug", "critical"]
        )

        assert len(issues) == 1
        # Verify labels are passed as comma-separated
        call_args = mock_http_client.request.call_args
        assert call_args[1]["params"]["labels"] == "bug,critical"
        # Verify project ID is URL-encoded
        assert "%2F" in call_args[1]["url"]

    @patch("aden_tools.tools.gitlab_tool.gitlab.httpx.Client")
    def test_get_merge_request_success(self, mock_client_class, mock_client):
        """Test successful merge request retrieval."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "iid": 42,
            "title": "Add new feature",
            "state": "merged",
            "author": {"username": "developer"},
            "web_url": "https://gitlab.com/mygroup/myproject/-/merge_requests/42",
        }
        mock_response.raise_for_status = MagicMock()

        mock_http_client = MagicMock()
        mock_http_client.request.return_value = mock_response
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_http_client

        mr = mock_client.get_merge_request(project_id="123", mr_iid=42)

        assert mr["iid"] == 42
        assert mr["state"] == "merged"
        assert "web_url" in mr

    @patch("aden_tools.tools.gitlab_tool.gitlab.httpx.Client")
    def test_create_issue_success(self, mock_client_class, mock_client):
        """Test successful issue creation."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "iid": 10,
            "title": "New Bug Report",
            "description": "Description of the bug",
            "labels": ["bug"],
            "web_url": "https://gitlab.com/mygroup/myproject/-/issues/10",
        }
        mock_response.raise_for_status = MagicMock()

        mock_http_client = MagicMock()
        mock_http_client.request.return_value = mock_response
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_http_client

        issue = mock_client.create_issue(
            project_id="123",
            title="New Bug Report",
            description="Description of the bug",
            labels=["bug"]
        )

        assert issue["iid"] == 10
        assert issue["title"] == "New Bug Report"
        # Verify POST method was used
        call_args = mock_http_client.request.call_args
        assert call_args[1]["method"] == "POST"

    @patch("aden_tools.tools.gitlab_tool.gitlab.httpx.Client")
    def test_trigger_pipeline_success(self, mock_client_class, mock_client):
        """Test successful pipeline trigger."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 999,
            "status": "pending",
            "ref": "main",
            "web_url": "https://gitlab.com/mygroup/myproject/-/pipelines/999",
        }
        mock_response.raise_for_status = MagicMock()

        mock_http_client = MagicMock()
        mock_http_client.request.return_value = mock_response
        mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
        mock_http_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_http_client

        pipeline = mock_client.trigger_pipeline(project_id="123", ref="main")

        assert pipeline["id"] == 999
        assert pipeline["status"] == "pending"
        assert pipeline["ref"] == "main"


class TestGetClient:
    """Tests for _get_client function."""

    def test_get_client_with_valid_credentials(self):
        """Test client creation with valid credentials."""
        creds = CredentialManager.for_testing({
            "gitlab_access_token": "test-token",
            "gitlab_url": "https://gitlab.mycompany.com",
        })
        client = _get_client(creds)

        assert client is not None
        assert client._base_url == "https://gitlab.mycompany.com"

    def test_get_client_without_credentials(self):
        """Test client creation without credentials."""
        client = _get_client(None)
        assert client is None

    def test_get_client_with_missing_token(self):
        """Test client creation with missing access token."""
        creds = CredentialManager.for_testing({})
        client = _get_client(creds)
        assert client is None

    def test_get_client_defaults_to_gitlab_com(self):
        """Test client defaults to gitlab.com when GITLAB_URL not set."""
        creds = CredentialManager.for_testing({
            "gitlab_access_token": "test-token",
        })
        client = _get_client(creds)

        assert client is not None
        assert client._base_url == DEFAULT_GITLAB_URL


class TestCredentialIntegration:
    """Tests for credential integration."""

    def test_credential_spec_exists(self):
        """Test that GitLab credentials are in CREDENTIAL_SPECS."""
        assert "gitlab_access_token" in CREDENTIAL_SPECS
        assert "gitlab_url" in CREDENTIAL_SPECS

    def test_access_token_spec_tools(self):
        """Test that access token spec lists all tools."""
        spec = CREDENTIAL_SPECS["gitlab_access_token"]
        expected_tools = [
            "gitlab_list_projects",
            "gitlab_list_issues",
            "gitlab_get_merge_request",
            "gitlab_create_issue",
            "gitlab_trigger_pipeline",
        ]
        for tool in expected_tools:
            assert tool in spec.tools

    def test_gitlab_url_is_optional(self):
        """Test that GITLAB_URL is marked as optional."""
        spec = CREDENTIAL_SPECS["gitlab_url"]
        assert spec.required is False

    def test_tool_flow_with_credentials(self, mcp):
        """Test the full tool registration flow."""
        creds = CredentialManager.for_testing({"gitlab_access_token": "test-key"})
        register_tools(mcp, credentials=creds)

        # Verify tools are registered
        tools = mcp._tool_manager._tools
        assert "gitlab_list_projects" in tools
        assert "gitlab_list_issues" in tools
        assert "gitlab_get_merge_request" in tools
        assert "gitlab_create_issue" in tools
        assert "gitlab_trigger_pipeline" in tools


class TestGitLabToolResponses:
    """Tests for tool response formatting."""

    def test_missing_credentials_error_format(self, mcp):
        """Test error message when credentials are missing."""
        register_tools(mcp, credentials=None)

        fn = mcp._tool_manager._tools["gitlab_list_projects"].fn
        result = fn()

        assert "error" in result
        assert "Missing GitLab credentials" in result
        assert "GITLAB_ACCESS_TOKEN" in result


class TestSelfHostedGitLab:
    """Tests for self-hosted GitLab instance support."""

    def test_custom_base_url(self):
        """Test client uses custom base URL."""
        client = GitLabClient(
            access_token="token",
            base_url="https://gitlab.mycompany.com"
        )
        assert client._base_url == "https://gitlab.mycompany.com"
        assert client._api_url == "https://gitlab.mycompany.com/api/v4"

    def test_trailing_slash_stripped(self):
        """Test trailing slash is stripped from base URL."""
        client = GitLabClient(
            access_token="token",
            base_url="https://gitlab.mycompany.com/"
        )
        assert client._base_url == "https://gitlab.mycompany.com"
