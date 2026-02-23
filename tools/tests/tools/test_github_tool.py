"""
Tests for GitHub tool.

Covers:
- _GitHubClient methods (repositories, issues, PRs, search, branches)
- Error handling (API errors, timeout, network errors)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 15 MCP tool functions
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.github_tool.github_tool import (
    _GitHubClient,
    register_tools,
)

# --- _GitHubClient tests ---


class TestGitHubClient:
    def setup_method(self):
        self.client = _GitHubClient("ghp_test_token")

    def test_headers(self):
        headers = self.client._headers
        assert headers["Authorization"] == "Bearer ghp_test_token"
        assert "application/vnd.github+json" in headers["Accept"]

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"id": 123, "name": "test-repo"}
        result = self.client._handle_response(response)
        assert result["success"] is True
        assert result["data"]["name"] == "test-repo"

    def test_handle_response_401(self):
        response = MagicMock()
        response.status_code = 401
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Invalid or expired" in result["error"]

    def test_handle_response_403(self):
        response = MagicMock()
        response.status_code = 403
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Forbidden" in result["error"]

    def test_handle_response_404(self):
        response = MagicMock()
        response.status_code = 404
        result = self.client._handle_response(response)
        assert "error" in result
        assert "not found" in result["error"]

    def test_handle_response_422(self):
        response = MagicMock()
        response.status_code = 422
        response.json.return_value = {"message": "Validation failed"}
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Validation" in result["error"]

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_list_repos(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": 1, "name": "repo1", "full_name": "user/repo1"},
            {"id": 2, "name": "repo2", "full_name": "user/repo2"},
        ]
        mock_get.return_value = mock_response

        result = self.client.list_repos(username="testuser")

        mock_get.assert_called_once()
        assert result["success"] is True
        assert len(result["data"]) == 2

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_list_repos_authenticated_user(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        self.client.list_repos(username=None)

        call_url = mock_get.call_args.args[0]
        assert "/user/repos" in call_url

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_get_repo(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 123,
            "name": "test-repo",
            "full_name": "owner/test-repo",
            "description": "A test repository",
        }
        mock_get.return_value = mock_response

        result = self.client.get_repo("owner", "test-repo")

        assert result["success"] is True
        assert result["data"]["name"] == "test-repo"

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_search_repos(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total_count": 1,
            "items": [{"id": 123, "name": "test-repo"}],
        }
        mock_get.return_value = mock_response

        result = self.client.search_repos("language:python")

        assert result["success"] is True
        assert "items" in result["data"]

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_list_issues(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"number": 1, "title": "Issue 1", "state": "open"},
            {"number": 2, "title": "Issue 2", "state": "open"},
        ]
        mock_get.return_value = mock_response

        result = self.client.list_issues("owner", "repo", state="open")

        assert result["success"] is True
        assert len(result["data"]) == 2

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_get_issue(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "number": 1,
            "title": "Test Issue",
            "body": "This is a test",
        }
        mock_get.return_value = mock_response

        result = self.client.get_issue("owner", "repo", 1)

        assert result["success"] is True
        assert result["data"]["title"] == "Test Issue"

    @patch("aden_tools.tools.github_tool.github_tool.httpx.post")
    def test_create_issue(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "number": 42,
            "title": "New Issue",
            "body": "Description",
        }
        mock_post.return_value = mock_response

        result = self.client.create_issue(
            "owner", "repo", "New Issue", body="Description", labels=["bug"]
        )

        assert result["success"] is True
        assert result["data"]["number"] == 42
        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["labels"] == ["bug"]

    @patch("aden_tools.tools.github_tool.github_tool.httpx.patch")
    def test_update_issue(self, mock_patch):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "number": 1,
            "title": "Updated Title",
            "state": "closed",
        }
        mock_patch.return_value = mock_response

        result = self.client.update_issue("owner", "repo", 1, title="Updated Title", state="closed")

        assert result["success"] is True
        assert result["data"]["state"] == "closed"

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_list_pull_requests(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"number": 1, "title": "PR 1", "state": "open"},
        ]
        mock_get.return_value = mock_response

        result = self.client.list_pull_requests("owner", "repo")

        assert result["success"] is True
        assert len(result["data"]) == 1

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_get_pull_request(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "number": 1,
            "title": "Test PR",
            "head": {"ref": "feature"},
            "base": {"ref": "main"},
        }
        mock_get.return_value = mock_response

        result = self.client.get_pull_request("owner", "repo", 1)

        assert result["success"] is True
        assert result["data"]["title"] == "Test PR"

    @patch("aden_tools.tools.github_tool.github_tool.httpx.post")
    def test_create_pull_request(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "number": 10,
            "title": "New PR",
            "draft": False,
        }
        mock_post.return_value = mock_response

        result = self.client.create_pull_request(
            "owner", "repo", "New PR", "feature-branch", "main", body="PR description"
        )

        assert result["success"] is True
        assert result["data"]["number"] == 10

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_search_code(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total_count": 5,
            "items": [{"name": "file.py", "path": "src/file.py"}],
        }
        mock_get.return_value = mock_response

        result = self.client.search_code("addClass repo:jquery/jquery")

        assert result["success"] is True
        assert "items" in result["data"]

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_list_branches(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"name": "main", "protected": True},
            {"name": "develop", "protected": False},
        ]
        mock_get.return_value = mock_response

        result = self.client.list_branches("owner", "repo")

        assert result["success"] is True
        assert len(result["data"]) == 2

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_get_branch(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "name": "main",
            "protected": True,
            "commit": {"sha": "abc123"},
        }
        mock_get.return_value = mock_response

        result = self.client.get_branch("owner", "repo", "main")

        assert result["success"] is True
        assert result["data"]["name"] == "main"


# --- Credential retrieval tests ---


class TestCredentialRetrieval:
    @pytest.fixture
    def mcp(self):
        return FastMCP("test-server")

    def test_no_credentials_returns_error(self, mcp):
        """When no credentials are configured, tools return helpful error."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("os.getenv", return_value=None):
                register_tools(mcp, credentials=None)
                list_repos = mcp._tool_manager._tools["github_list_repos"].fn

                result = list_repos()

                assert "error" in result
                assert "not configured" in result["error"]
                assert "help" in result

    def test_env_var_token(self, mcp):
        """Token from GITHUB_TOKEN env var is used."""
        with patch("os.getenv", return_value="ghp_env_token"):
            with patch("aden_tools.tools.github_tool.github_tool.httpx.get") as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = []
                mock_get.return_value = mock_response

                register_tools(mcp, credentials=None)
                list_repos = mcp._tool_manager._tools["github_list_repos"].fn

                list_repos()

                call_headers = mock_get.call_args.kwargs["headers"]
                assert call_headers["Authorization"] == "Bearer ghp_env_token"

    def test_credential_store_token(self, mcp):
        """Token from CredentialStoreAdapter is preferred."""
        mock_credentials = MagicMock()
        mock_credentials.get.return_value = "ghp_store_token"

        with patch("aden_tools.tools.github_tool.github_tool.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = []
            mock_get.return_value = mock_response

            register_tools(mcp, credentials=mock_credentials)
            list_repos = mcp._tool_manager._tools["github_list_repos"].fn

            list_repos()

            mock_credentials.get.assert_called_with("github")
            call_headers = mock_get.call_args.kwargs["headers"]
            assert call_headers["Authorization"] == "Bearer ghp_store_token"


# --- MCP Tool function tests ---


class TestGitHubListRepos:
    @pytest.fixture
    def mcp(self):
        return FastMCP("test-server")

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_list_repos_success(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": 1, "name": "test-repo"}]
        mock_get.return_value = mock_response

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            list_repos = mcp._tool_manager._tools["github_list_repos"].fn

            result = list_repos(username="testuser")

            assert result["success"] is True

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_list_repos_timeout(self, mock_get, mcp):
        mock_get.side_effect = httpx.TimeoutException("Timeout")

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            list_repos = mcp._tool_manager._tools["github_list_repos"].fn

            result = list_repos()

            assert "error" in result
            assert "timed out" in result["error"]

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_list_repos_network_error(self, mock_get, mcp):
        mock_get.side_effect = httpx.RequestError("Network error")

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            list_repos = mcp._tool_manager._tools["github_list_repos"].fn

            result = list_repos()

            assert "error" in result
            assert "Network error" in result["error"]


class TestGitHubGetRepo:
    @pytest.fixture
    def mcp(self):
        return FastMCP("test-server")

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_get_repo_success(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 1, "name": "test-repo"}
        mock_get.return_value = mock_response

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            get_repo = mcp._tool_manager._tools["github_get_repo"].fn

            result = get_repo(owner="owner", repo="test-repo")

            assert result["success"] is True


class TestGitHubSearchRepos:
    @pytest.fixture
    def mcp(self):
        return FastMCP("test-server")

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_search_repos_success(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"total_count": 1, "items": []}
        mock_get.return_value = mock_response

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            search_repos = mcp._tool_manager._tools["github_search_repos"].fn

            result = search_repos(query="python")

            assert result["success"] is True


class TestGitHubIssues:
    @pytest.fixture
    def mcp(self):
        return FastMCP("test-server")

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_list_issues_success(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"number": 1, "title": "Test Issue"}]
        mock_get.return_value = mock_response

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            list_issues = mcp._tool_manager._tools["github_list_issues"].fn

            result = list_issues(owner="owner", repo="repo")

            assert result["success"] is True

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_get_issue_success(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"number": 1, "title": "Test"}
        mock_get.return_value = mock_response

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            get_issue = mcp._tool_manager._tools["github_get_issue"].fn

            result = get_issue(owner="owner", repo="repo", issue_number=1)

            assert result["success"] is True

    @patch("aden_tools.tools.github_tool.github_tool.httpx.post")
    def test_create_issue_success(self, mock_post, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"number": 1, "title": "New Issue"}
        mock_post.return_value = mock_response

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            create_issue = mcp._tool_manager._tools["github_create_issue"].fn

            result = create_issue(owner="owner", repo="repo", title="New Issue")

            assert result["success"] is True

    @patch("aden_tools.tools.github_tool.github_tool.httpx.patch")
    def test_update_issue_success(self, mock_patch, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"number": 1, "state": "closed"}
        mock_patch.return_value = mock_response

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            update_issue = mcp._tool_manager._tools["github_update_issue"].fn

            result = update_issue(owner="owner", repo="repo", issue_number=1, state="closed")

            assert result["success"] is True


class TestGitHubPullRequests:
    @pytest.fixture
    def mcp(self):
        return FastMCP("test-server")

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_list_pull_requests_success(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"number": 1, "title": "Test PR"}]
        mock_get.return_value = mock_response

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            list_prs = mcp._tool_manager._tools["github_list_pull_requests"].fn

            result = list_prs(owner="owner", repo="repo")

            assert result["success"] is True

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_get_pull_request_success(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"number": 1, "title": "PR"}
        mock_get.return_value = mock_response

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            get_pr = mcp._tool_manager._tools["github_get_pull_request"].fn

            result = get_pr(owner="owner", repo="repo", pull_number=1)

            assert result["success"] is True

    @patch("aden_tools.tools.github_tool.github_tool.httpx.post")
    def test_create_pull_request_success(self, mock_post, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"number": 1, "title": "New PR"}
        mock_post.return_value = mock_response

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            create_pr = mcp._tool_manager._tools["github_create_pull_request"].fn

            result = create_pr(
                owner="owner",
                repo="repo",
                title="New PR",
                head="feature",
                base="main",
            )

            assert result["success"] is True


class TestGitHubSearch:
    @pytest.fixture
    def mcp(self):
        return FastMCP("test-server")

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_search_code_success(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"total_count": 1, "items": []}
        mock_get.return_value = mock_response

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            search_code = mcp._tool_manager._tools["github_search_code"].fn

            result = search_code(query="addClass")

            assert result["success"] is True


class TestGitHubBranches:
    @pytest.fixture
    def mcp(self):
        return FastMCP("test-server")

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_list_branches_success(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"name": "main"}]
        mock_get.return_value = mock_response

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            list_branches = mcp._tool_manager._tools["github_list_branches"].fn

            result = list_branches(owner="owner", repo="repo")

            assert result["success"] is True

    @patch("aden_tools.tools.github_tool.github_tool.httpx.get")
    def test_get_branch_success(self, mock_get, mcp):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"name": "main", "protected": True}
        mock_get.return_value = mock_response

        with patch("os.getenv", return_value="ghp_test"):
            register_tools(mcp, credentials=None)
            get_branch = mcp._tool_manager._tools["github_get_branch"].fn

            result = get_branch(owner="owner", repo="repo", branch="main")

            assert result["success"] is True
