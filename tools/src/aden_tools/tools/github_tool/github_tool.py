"""
GitHub Tool - Interact with GitHub repositories, issues, and pull requests.

Supports:
- Personal Access Tokens (GITHUB_TOKEN / ghp_...)
- OAuth tokens via the credential store

API Reference: https://docs.github.com/en/rest
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

GITHUB_API_BASE = "https://api.github.com"


def _sanitize_path_param(param: str, param_name: str = "parameter") -> str:
    """
    Sanitize URL path parameters to prevent path traversal.

    Args:
        param: The parameter value to sanitize
        param_name: Name of the parameter (for error messages)

    Returns:
        The sanitized parameter

    Raises:
        ValueError: If parameter contains invalid characters
    """
    if "/" in param or ".." in param:
        raise ValueError(f"Invalid {param_name}: cannot contain '/' or '..'")
    return param


def _sanitize_error_message(error: Exception) -> str:
    """
    Sanitize error messages to prevent token leaks.

    httpx.RequestError can include headers in the exception message,
    which may expose the Bearer token.

    Args:
        error: The exception to sanitize

    Returns:
        A safe error message without sensitive information
    """
    error_str = str(error)
    # Remove any Authorization headers or Bearer tokens
    if "Authorization" in error_str or "Bearer" in error_str:
        return "Network error occurred"
    return f"Network error: {error_str}"


class _GitHubClient:
    """Internal client wrapping GitHub REST API v3 calls."""

    def __init__(self, token: str):
        self._token = token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle GitHub API response format."""
        if response.status_code == 401:
            return {"error": "Invalid or expired GitHub token"}
        if response.status_code == 403:
            return {"error": "Forbidden - check token permissions or rate limit"}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 422:
            try:
                detail = response.json().get("message", "Validation failed")
            except Exception:
                detail = "Validation failed"
            return {"error": f"Validation error: {detail}"}
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"GitHub API error (HTTP {response.status_code}): {detail}"}

        try:
            return {"success": True, "data": response.json()}
        except Exception:
            return {"success": True, "data": {}}

    # --- Repositories ---

    def list_repos(
        self,
        username: str | None = None,
        visibility: str = "all",
        sort: str = "updated",
        limit: int = 30,
    ) -> dict[str, Any]:
        """List repositories for a user or authenticated user."""
        if username:
            username = _sanitize_path_param(username, "username")
            url = f"{GITHUB_API_BASE}/users/{username}/repos"
        else:
            url = f"{GITHUB_API_BASE}/user/repos"

        params = {
            "visibility": visibility,
            "sort": sort,
            "per_page": min(limit, 100),
        }

        response = httpx.get(
            url,
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_repo(
        self,
        owner: str,
        repo: str,
    ) -> dict[str, Any]:
        """Get repository information."""
        owner = _sanitize_path_param(owner, "owner")
        repo = _sanitize_path_param(repo, "repo")
        response = httpx.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def search_repos(
        self,
        query: str,
        sort: str | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        """Search for repositories."""
        params: dict[str, Any] = {
            "q": query,
            "per_page": min(limit, 100),
        }
        if sort:
            params["sort"] = sort

        response = httpx.get(
            f"{GITHUB_API_BASE}/search/repositories",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    # --- Issues ---

    def list_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        page: int = 1,
        limit: int = 30,
    ) -> dict[str, Any]:
        """List issues for a repository."""
        owner = _sanitize_path_param(owner, "owner")
        repo = _sanitize_path_param(repo, "repo")
        params = {
            "state": state,
            "per_page": min(limit, 100),
            "page": max(1, page),
        }

        response = httpx.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> dict[str, Any]:
        """Get a specific issue."""
        owner = _sanitize_path_param(owner, "owner")
        repo = _sanitize_path_param(repo, "repo")
        response = httpx.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{issue_number}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new issue."""
        owner = _sanitize_path_param(owner, "owner")
        repo = _sanitize_path_param(repo, "repo")
        payload: dict[str, Any] = {"title": title}
        if body:
            payload["body"] = body
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees

        response = httpx.post(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def update_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update an existing issue."""
        owner = _sanitize_path_param(owner, "owner")
        repo = _sanitize_path_param(repo, "repo")
        payload: dict[str, Any] = {}
        if title:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state:
            payload["state"] = state
        if labels is not None:
            payload["labels"] = labels

        response = httpx.patch(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{issue_number}",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    # --- Pull Requests ---

    def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        page: int = 1,
        limit: int = 30,
    ) -> dict[str, Any]:
        """List pull requests for a repository."""
        owner = _sanitize_path_param(owner, "owner")
        repo = _sanitize_path_param(repo, "repo")
        params = {
            "state": state,
            "per_page": min(limit, 100),
            "page": max(1, page),
        }

        response = httpx.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> dict[str, Any]:
        """Get a specific pull request."""
        owner = _sanitize_path_param(owner, "owner")
        repo = _sanitize_path_param(repo, "repo")
        response = httpx.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pull_number}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str | None = None,
        draft: bool = False,
    ) -> dict[str, Any]:
        """Create a new pull request."""
        owner = _sanitize_path_param(owner, "owner")
        repo = _sanitize_path_param(repo, "repo")
        payload: dict[str, Any] = {
            "title": title,
            "head": head,
            "base": base,
            "draft": draft,
        }
        if body:
            payload["body"] = body

        response = httpx.post(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    # --- Search ---

    def search_code(
        self,
        query: str,
        limit: int = 30,
    ) -> dict[str, Any]:
        """Search code across GitHub."""
        params = {
            "q": query,
            "per_page": min(limit, 100),
        }

        response = httpx.get(
            f"{GITHUB_API_BASE}/search/code",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    # --- Branches ---

    def list_branches(
        self,
        owner: str,
        repo: str,
        limit: int = 30,
    ) -> dict[str, Any]:
        """List branches for a repository."""
        owner = _sanitize_path_param(owner, "owner")
        repo = _sanitize_path_param(repo, "repo")
        params = {
            "per_page": min(limit, 100),
        }

        response = httpx.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/branches",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_branch(
        self,
        owner: str,
        repo: str,
        branch: str,
    ) -> dict[str, Any]:
        """Get a specific branch."""
        owner = _sanitize_path_param(owner, "owner")
        repo = _sanitize_path_param(repo, "repo")
        branch = _sanitize_path_param(branch, "branch")
        response = httpx.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/branches/{branch}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    # --- Stargazers ---

    def list_stargazers(
        self,
        owner: str,
        repo: str,
        page: int = 1,
        limit: int = 30,
    ) -> dict[str, Any]:
        """List users who starred a repository."""
        owner = _sanitize_path_param(owner, "owner")
        repo = _sanitize_path_param(repo, "repo")
        params = {
            "per_page": min(limit, 100),
            "page": max(1, page),
        }

        response = httpx.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/stargazers",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)

    # --- Users ---

    def get_user_profile(
        self,
        username: str,
    ) -> dict[str, Any]:
        """Get a user's public profile."""
        username = _sanitize_path_param(username, "username")
        response = httpx.get(
            f"{GITHUB_API_BASE}/users/{username}",
            headers=self._headers,
            timeout=30.0,
        )
        return self._handle_response(response)

    def get_user_emails(
        self,
        username: str,
    ) -> dict[str, Any]:
        """Find a user's email addresses from their public activity.

        The /users/{username} endpoint only returns the public email
        (which most users leave blank). This method also checks the
        user's recent public events for commit-author emails.
        """
        username = _sanitize_path_param(username, "username")

        emails: dict[str, str] = {}  # email -> source

        # 1. Check profile for public email
        profile = self.get_user_profile(username)
        if isinstance(profile, dict) and "error" not in profile:
            if profile.get("email"):
                emails[profile["email"]] = "profile"

        # 2. Check recent public events for commit emails
        response = httpx.get(
            f"{GITHUB_API_BASE}/users/{username}/events/public",
            headers=self._headers,
            params={"per_page": 30},
            timeout=30.0,
        )
        if response.status_code == 200:
            for event in response.json():
                if event.get("type") != "PushEvent":
                    continue
                for commit in event.get("payload", {}).get("commits", []):
                    author = commit.get("author", {})
                    email = author.get("email", "")
                    if email and "@" in email and "noreply" not in email.lower():
                        emails[email] = "commit"

        return {
            "username": username,
            "emails": [{"email": e, "source": s} for e, s in emails.items()],
            "total": len(emails),
        }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register GitHub tools with the MCP server."""

    def _get_token(account: str = "") -> str | None:
        """Get GitHub token from credential manager or environment."""
        if credentials is not None:
            if account:
                return credentials.get_by_alias("github", account)
            token = credentials.get("github")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    f"Expected string from credentials.get('github'), got {type(token).__name__}"
                )
            return token
        return os.getenv("GITHUB_TOKEN")

    def _get_client(account: str = "") -> _GitHubClient | dict[str, str]:
        """Get a GitHub client, or return an error dict if no credentials."""
        token = _get_token(account)
        if not token:
            return {
                "error": "GitHub credentials not configured",
                "help": (
                    "Set GITHUB_TOKEN environment variable "
                    "or configure via credential store. "
                    "Get a token at https://github.com/settings/tokens"
                ),
            }
        return _GitHubClient(token)

    # --- Repositories ---

    @mcp.tool()
    def github_list_repos(
        username: str | None = None,
        visibility: str = "all",
        sort: str = "updated",
        limit: int = 30,
        account: str = "",
    ) -> dict:
        """
        List repositories for a user or the authenticated user.

        Args:
            username: GitHub username (if None, lists authenticated user's repos)
            visibility: Repository visibility filter ("all", "public", "private")
            sort: Sort order ("created", "updated", "pushed", "full_name")
            limit: Maximum number of repositories to return (1-100, default 30)

        Returns:
            Dict with list of repositories or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.list_repos(username, visibility, sort, limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def github_get_repo(
        owner: str,
        repo: str,
        account: str = "",
    ) -> dict:
        """
        Get information about a specific repository.

        Args:
            owner: Repository owner (username or organization)
            repo: Repository name

        Returns:
            Dict with repository information or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_repo(owner, repo)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def github_search_repos(
        query: str,
        sort: str | None = None,
        limit: int = 30,
        account: str = "",
    ) -> dict:
        """
        Search for repositories on GitHub.

        Args:
            query: Search query (e.g., "language:python stars:>1000")
            sort: Sort field ("stars", "forks", "updated")
            limit: Maximum number of results (1-100, default 30)

        Returns:
            Dict with search results or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.search_repos(query, sort, limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    # --- Issues ---

    @mcp.tool()
    def github_list_issues(
        owner: str,
        repo: str,
        state: str = "open",
        page: int = 1,
        limit: int = 30,
        account: str = "",
    ) -> dict:
        """
        List issues for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            state: Issue state ("open", "closed", "all")
            page: Page number for pagination (1-based, default 1)
            limit: Maximum number of issues per page (1-100, default 30)

        Returns:
            Dict with list of issues or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.list_issues(owner, repo, state, page, limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def github_get_issue(
        owner: str,
        repo: str,
        issue_number: int,
        account: str = "",
    ) -> dict:
        """
        Get a specific issue.

        Args:
            owner: Repository owner
            repo: Repository name
            issue_number: Issue number

        Returns:
            Dict with issue information or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_issue(owner, repo, issue_number)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def github_create_issue(
        owner: str,
        repo: str,
        title: str,
        body: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
        account: str = "",
    ) -> dict:
        """
        Create a new issue in a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            title: Issue title
            body: Issue body/description (supports Markdown)
            labels: List of label names to apply
            assignees: List of usernames to assign

        Returns:
            Dict with created issue information or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.create_issue(owner, repo, title, body, labels, assignees)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def github_update_issue(
        owner: str,
        repo: str,
        issue_number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
        account: str = "",
    ) -> dict:
        """
        Update an existing issue.

        Args:
            owner: Repository owner
            repo: Repository name
            issue_number: Issue number
            title: New issue title
            body: New issue body
            state: New state ("open" or "closed")
            labels: New list of label names

        Returns:
            Dict with updated issue information or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.update_issue(owner, repo, issue_number, title, body, state, labels)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    # --- Pull Requests ---

    @mcp.tool()
    def github_list_pull_requests(
        owner: str,
        repo: str,
        state: str = "open",
        page: int = 1,
        limit: int = 30,
        account: str = "",
    ) -> dict:
        """
        List pull requests for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            state: PR state ("open", "closed", "all")
            page: Page number for pagination (1-based, default 1)
            limit: Maximum number of PRs per page (1-100, default 30)

        Returns:
            Dict with list of pull requests or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.list_pull_requests(owner, repo, state, page, limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def github_get_pull_request(
        owner: str,
        repo: str,
        pull_number: int,
        account: str = "",
    ) -> dict:
        """
        Get a specific pull request.

        Args:
            owner: Repository owner
            repo: Repository name
            pull_number: Pull request number

        Returns:
            Dict with pull request information or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_pull_request(owner, repo, pull_number)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def github_create_pull_request(
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str | None = None,
        draft: bool = False,
        account: str = "",
    ) -> dict:
        """
        Create a new pull request.

        Args:
            owner: Repository owner
            repo: Repository name
            title: Pull request title
            head: The name of the branch where your changes are (e.g., "my-feature")
            base: The name of the branch you want to merge into (e.g., "main")
            body: Pull request description (supports Markdown)
            draft: Whether to create as a draft PR

        Returns:
            Dict with created pull request information or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.create_pull_request(owner, repo, title, head, base, body, draft)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    # --- Search ---

    @mcp.tool()
    def github_search_code(
        query: str,
        limit: int = 30,
        account: str = "",
    ) -> dict:
        """
        Search code across GitHub.

        Args:
            query: Search query (e.g., "addClass repo:jquery/jquery")
            limit: Maximum number of results (1-100, default 30)

        Returns:
            Dict with search results or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.search_code(query, limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    # --- Branches ---

    @mcp.tool()
    def github_list_branches(
        owner: str,
        repo: str,
        limit: int = 30,
        account: str = "",
    ) -> dict:
        """
        List branches for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            limit: Maximum number of branches to return (1-100, default 30)

        Returns:
            Dict with list of branches or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.list_branches(owner, repo, limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def github_get_branch(
        owner: str,
        repo: str,
        branch: str,
        account: str = "",
    ) -> dict:
        """
        Get information about a specific branch.

        Args:
            owner: Repository owner
            repo: Repository name
            branch: Branch name

        Returns:
            Dict with branch information or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_branch(owner, repo, branch)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    # --- Stargazers ---

    @mcp.tool()
    def github_list_stargazers(
        owner: str,
        repo: str,
        page: int = 1,
        limit: int = 30,
        account: str = "",
    ) -> dict:
        """
        List users who starred a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            page: Page number for pagination (1-based, default 1)
            limit: Maximum number of stargazers per page (1-100, default 30)

        Returns:
            Dict with list of stargazers or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.list_stargazers(owner, repo, page, limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    # --- Users ---

    @mcp.tool()
    def github_get_user_profile(
        username: str,
        account: str = "",
    ) -> dict:
        """
        Get a GitHub user's public profile including name, bio, company, location, and email.

        Args:
            username: GitHub username

        Returns:
            Dict with user profile information or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_user_profile(username)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}

    @mcp.tool()
    def github_get_user_emails(
        username: str,
        account: str = "",
    ) -> dict:
        """
        Find a GitHub user's email addresses from their public activity.

        Checks both the user's profile (public email) and their recent
        push events for commit-author emails. Filters out noreply addresses.

        Args:
            username: GitHub username

        Returns:
            Dict with emails list (each with email and source), total count
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            return client.get_user_emails(username)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": _sanitize_error_message(e)}
