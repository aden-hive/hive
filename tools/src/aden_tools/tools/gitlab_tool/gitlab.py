"""
GitLab integration tool for MCP Server.

Provides comprehensive GitLab API functionality for DevOps automation:
- List and search projects
- List and create issues
- Get merge request details
- Trigger CI/CD pipelines

Authentication: Personal Access Token (PAT) or Project Access Token.
Supports self-hosted GitLab instances via GITLAB_URL.

API Reference: https://docs.gitlab.com/ee/api/rest/
"""

import json
import logging
from typing import Any

import httpx
from fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)

# Constants
DEFAULT_GITLAB_URL = "https://gitlab.com"
DEFAULT_TIMEOUT = 30.0
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class GitLabClient:
    """
    GitLab API client.

    Handles authentication and provides methods for all GitLab operations.
    Supports both gitlab.com and self-hosted instances.
    """

    def __init__(
        self,
        access_token: str,
        base_url: str = DEFAULT_GITLAB_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """
        Initialize the GitLab client.

        Args:
            access_token: Personal Access Token or Project Access Token.
            base_url: Base URL for GitLab (default: https://gitlab.com).
            timeout: Request timeout in seconds.
        """
        self._access_token = access_token
        self._base_url = base_url.rstrip("/")
        self._api_url = f"{self._base_url}/api/v4"
        self._timeout = timeout
        self._headers = {
            "PRIVATE-TOKEN": access_token,
            "Content-Type": "application/json",
        }

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Make an HTTP request to the GitLab API.

        Args:
            method: HTTP method (GET, POST).
            endpoint: API endpoint (e.g., '/projects').
            params: Query parameters.
            json_data: JSON body data.

        Returns:
            Response JSON as a dictionary or list.

        Raises:
            httpx.HTTPStatusError: If request fails with non-2xx status.
        """
        url = f"{self._api_url}{endpoint}"

        with httpx.Client(timeout=self._timeout) as client:
            response = client.request(
                method=method,
                url=url,
                headers=self._headers,
                params=params,
                json=json_data,
            )
            response.raise_for_status()
            return response.json()

    def list_projects(
        self,
        search: str | None = None,
        owned: bool | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        """
        List accessible projects.

        Args:
            search: Search term to filter projects by name.
            owned: If True, only return projects owned by authenticated user.
            limit: Maximum number of projects to return.

        Returns:
            List of project objects with 'id', 'name', 'path_with_namespace', etc.
        """
        params: dict[str, Any] = {
            "per_page": min(limit, MAX_LIMIT),
            "simple": True,  # Return limited fields for performance
        }

        if search:
            params["search"] = search
        if owned is not None:
            params["owned"] = str(owned).lower()

        result = self._make_request("GET", "/projects", params=params)
        return result if isinstance(result, list) else []

    def list_issues(
        self,
        project_id: str,
        state: str | None = None,
        labels: list[str] | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        """
        List issues for a project.

        Args:
            project_id: Project ID or URL-encoded path.
            state: Filter by state ('opened', 'closed', 'all').
            labels: Filter by labels.
            limit: Maximum number of issues to return.

        Returns:
            List of issue objects.
        """
        # URL-encode the project ID if it contains slashes
        encoded_project_id = project_id.replace("/", "%2F")

        params: dict[str, Any] = {
            "per_page": min(limit, MAX_LIMIT),
        }

        if state:
            params["state"] = state
        if labels:
            params["labels"] = ",".join(labels)

        result = self._make_request(
            "GET", f"/projects/{encoded_project_id}/issues", params=params
        )
        return result if isinstance(result, list) else []

    def get_merge_request(
        self,
        project_id: str,
        mr_iid: int,
    ) -> dict[str, Any]:
        """
        Get details of a merge request.

        Args:
            project_id: Project ID or URL-encoded path.
            mr_iid: Merge request internal ID (IID).

        Returns:
            Merge request object with full details.
        """
        encoded_project_id = project_id.replace("/", "%2F")

        result = self._make_request(
            "GET", f"/projects/{encoded_project_id}/merge_requests/{mr_iid}"
        )
        return result if isinstance(result, dict) else {}

    def create_issue(
        self,
        project_id: str,
        title: str,
        description: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new issue in a project.

        Args:
            project_id: Project ID or URL-encoded path.
            title: Issue title.
            description: Issue description (markdown supported).
            labels: List of label names to apply.

        Returns:
            Created issue object.
        """
        encoded_project_id = project_id.replace("/", "%2F")

        data: dict[str, Any] = {"title": title}
        if description:
            data["description"] = description
        if labels:
            data["labels"] = ",".join(labels)

        result = self._make_request(
            "POST", f"/projects/{encoded_project_id}/issues", json_data=data
        )
        return result if isinstance(result, dict) else {}

    def trigger_pipeline(
        self,
        project_id: str,
        ref: str,
    ) -> dict[str, Any]:
        """
        Trigger a new CI/CD pipeline.

        Args:
            project_id: Project ID or URL-encoded path.
            ref: Branch name or tag to run the pipeline for.

        Returns:
            Pipeline object with 'id', 'status', 'web_url', etc.
        """
        encoded_project_id = project_id.replace("/", "%2F")

        data: dict[str, Any] = {"ref": ref}

        result = self._make_request(
            "POST", f"/projects/{encoded_project_id}/pipeline", json_data=data
        )
        return result if isinstance(result, dict) else {}


def _get_client(credentials) -> GitLabClient | None:
    """
    Create a GitLabClient from credentials.

    Args:
        credentials: CredentialManager instance.

    Returns:
        GitLabClient if credentials are available, None otherwise.
    """
    if not credentials:
        return None

    try:
        credentials.validate_for_tools(["gitlab_list_projects"])
        access_token = credentials.get("gitlab_access_token")
        if not access_token:
            return None

        # Get optional gitlab URL (defaults to gitlab.com)
        gitlab_url = credentials.get("gitlab_url") or DEFAULT_GITLAB_URL

        return GitLabClient(access_token, base_url=gitlab_url)
    except Exception as e:
        logger.error(f"Failed to get GitLab credentials: {e}")
        return None


def register_tools(mcp: FastMCP, credentials=None):
    """
    Register GitLab tools with the MCP server.

    Args:
        mcp: FastMCP server instance.
        credentials: Optional CredentialManager for API token access.
    """

    @mcp.tool(
        name="gitlab_list_projects",
        description=(
            "List accessible GitLab projects. Can search by name and filter "
            "to show only projects owned by the authenticated user."
        ),
    )
    def gitlab_list_projects(
        search: str | None = None,
        owned: bool | None = None,
        limit: int = DEFAULT_LIMIT,
        ctx: Context = None,
    ) -> str:
        """
        List accessible GitLab projects.

        Args:
            search: Search term to filter projects by name.
            owned: If True, only return projects owned by authenticated user.
            limit: Maximum number of projects to return (default: 20, max: 100).

        Returns:
            JSON string containing list of projects.
        """
        client = _get_client(credentials)
        if not client:
            return json.dumps({
                "error": "Missing GitLab credentials. "
                "Set GITLAB_ACCESS_TOKEN environment variable."
            })

        try:
            projects = client.list_projects(search=search, owned=owned, limit=limit)
            return json.dumps({"projects": projects}, indent=2, default=str)
        except httpx.HTTPStatusError as e:
            logger.error(f"GitLab API error: {e.response.status_code} - {e.response.text}")
            return json.dumps({
                "error": f"GitLab API error: {e.response.status_code}",
                "details": e.response.text,
            })
        except Exception as e:
            logger.error(f"Error listing projects: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="gitlab_list_issues",
        description=(
            "List issues for a GitLab project. Can filter by state "
            "(opened/closed) and labels."
        ),
    )
    def gitlab_list_issues(
        project_id: str,
        state: str | None = None,
        labels: str | None = None,
        limit: int = DEFAULT_LIMIT,
        ctx: Context = None,
    ) -> str:
        """
        List issues for a project.

        Args:
            project_id: Project ID (number) or path (e.g., 'mygroup/myproject').
            state: Filter by state ('opened', 'closed', 'all').
            labels: Comma-separated list of label names to filter by.
            limit: Maximum number of issues to return (default: 20, max: 100).

        Returns:
            JSON string containing list of issues.
        """
        client = _get_client(credentials)
        if not client:
            return json.dumps({
                "error": "Missing GitLab credentials. "
                "Set GITLAB_ACCESS_TOKEN environment variable."
            })

        try:
            label_list = None
            if labels:
                label_list = [label.strip() for label in labels.split(",")]

            issues = client.list_issues(
                project_id=project_id,
                state=state,
                labels=label_list,
                limit=limit,
            )
            return json.dumps({"issues": issues}, indent=2, default=str)
        except httpx.HTTPStatusError as e:
            logger.error(f"GitLab API error: {e.response.status_code} - {e.response.text}")
            return json.dumps({
                "error": f"GitLab API error: {e.response.status_code}",
                "details": e.response.text,
            })
        except Exception as e:
            logger.error(f"Error listing issues: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="gitlab_get_merge_request",
        description=(
            "Get details of a specific merge request including status, "
            "description, author, and reviewers."
        ),
    )
    def gitlab_get_merge_request(
        project_id: str,
        mr_iid: int,
        ctx: Context = None,
    ) -> str:
        """
        Get merge request details.

        Args:
            project_id: Project ID (number) or path (e.g., 'mygroup/myproject').
            mr_iid: Merge request internal ID (the number shown in the UI).

        Returns:
            JSON string containing merge request details.
        """
        client = _get_client(credentials)
        if not client:
            return json.dumps({
                "error": "Missing GitLab credentials. "
                "Set GITLAB_ACCESS_TOKEN environment variable."
            })

        try:
            mr = client.get_merge_request(project_id=project_id, mr_iid=mr_iid)
            return json.dumps(mr, indent=2, default=str)
        except httpx.HTTPStatusError as e:
            logger.error(f"GitLab API error: {e.response.status_code} - {e.response.text}")
            return json.dumps({
                "error": f"GitLab API error: {e.response.status_code}",
                "details": e.response.text,
            })
        except Exception as e:
            logger.error(f"Error getting merge request: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="gitlab_create_issue",
        description=(
            "Create a new issue in a GitLab project. Supports markdown "
            "in description and can assign labels."
        ),
    )
    def gitlab_create_issue(
        project_id: str,
        title: str,
        description: str | None = None,
        labels: str | None = None,
        ctx: Context = None,
    ) -> str:
        """
        Create a new issue.

        Args:
            project_id: Project ID (number) or path (e.g., 'mygroup/myproject').
            title: Issue title.
            description: Issue description (markdown supported).
            labels: Comma-separated list of label names to apply.

        Returns:
            JSON string containing created issue details.
        """
        client = _get_client(credentials)
        if not client:
            return json.dumps({
                "error": "Missing GitLab credentials. "
                "Set GITLAB_ACCESS_TOKEN environment variable."
            })

        try:
            label_list = None
            if labels:
                label_list = [label.strip() for label in labels.split(",")]

            issue = client.create_issue(
                project_id=project_id,
                title=title,
                description=description,
                labels=label_list,
            )
            return json.dumps(issue, indent=2, default=str)
        except httpx.HTTPStatusError as e:
            logger.error(f"GitLab API error: {e.response.status_code} - {e.response.text}")
            return json.dumps({
                "error": f"GitLab API error: {e.response.status_code}",
                "details": e.response.text,
            })
        except Exception as e:
            logger.error(f"Error creating issue: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="gitlab_trigger_pipeline",
        description=(
            "Trigger a new CI/CD pipeline run for a specific branch or tag. "
            "Useful for automating builds and deployments."
        ),
    )
    def gitlab_trigger_pipeline(
        project_id: str,
        ref: str,
        ctx: Context = None,
    ) -> str:
        """
        Trigger a CI/CD pipeline.

        Args:
            project_id: Project ID (number) or path (e.g., 'mygroup/myproject').
            ref: Branch name or tag to run the pipeline for (e.g., 'main', 'v1.0.0').

        Returns:
            JSON string containing pipeline details including status and web_url.
        """
        client = _get_client(credentials)
        if not client:
            return json.dumps({
                "error": "Missing GitLab credentials. "
                "Set GITLAB_ACCESS_TOKEN environment variable."
            })

        try:
            pipeline = client.trigger_pipeline(project_id=project_id, ref=ref)
            return json.dumps(pipeline, indent=2, default=str)
        except httpx.HTTPStatusError as e:
            logger.error(f"GitLab API error: {e.response.status_code} - {e.response.text}")
            return json.dumps({
                "error": f"GitLab API error: {e.response.status_code}",
                "details": e.response.text,
            })
        except Exception as e:
            logger.error(f"Error triggering pipeline: {e}")
            return json.dumps({"error": str(e)})
