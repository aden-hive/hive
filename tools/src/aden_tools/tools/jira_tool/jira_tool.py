"""
Jira Tool - Issue tracking and project management via Jira Cloud REST API v3.

Supports:
- Jira Cloud (Basic auth with email + API token)
- Issue search (JQL), CRUD, comments, projects

API Reference: https://developer.atlassian.com/cloud/jira/platform/rest/v3/
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_credentials(
    credentials: CredentialStoreAdapter | None,
) -> tuple[str | None, str | None, str | None]:
    """Return (domain, email, api_token)."""
    if credentials is not None:
        domain = credentials.get("jira_domain")
        email = credentials.get("jira_email")
        token = credentials.get("jira_token")
        return domain, email, token
    return (
        os.getenv("JIRA_DOMAIN"),
        os.getenv("JIRA_EMAIL"),
        os.getenv("JIRA_API_TOKEN"),
    )


def _base_url(domain: str) -> str:
    return f"https://{domain}/rest/api/3"


def _auth_header(email: str, token: str) -> str:
    encoded = base64.b64encode(f"{email}:{token}".encode()).decode()
    return f"Basic {encoded}"


def _request(method: str, url: str, email: str, token: str, **kwargs: Any) -> dict[str, Any]:
    """Make a request to the Jira API."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = _auth_header(email, token)
    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "application/json")
    try:
        resp = getattr(httpx, method)(
            url,
            headers=headers,
            timeout=30.0,
            **kwargs,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your Jira credentials."}
        if resp.status_code == 403:
            return {"error": "Forbidden. Check your Jira permissions."}
        if resp.status_code == 404:
            return {"error": "Not found."}
        if resp.status_code == 429:
            return {"error": "Rate limited. Try again shortly."}
        if resp.status_code not in (200, 201, 204):
            return {"error": f"Jira API error {resp.status_code}: {resp.text[:500]}"}
        if resp.status_code == 204:
            return {"status": "success"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Jira timed out"}
    except Exception as e:
        return {"error": f"Jira request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "JIRA_DOMAIN, JIRA_EMAIL, and JIRA_API_TOKEN not set",
        "help": "Create an API token at https://id.atlassian.com/manage/api-tokens",
    }


def _text_to_adf(text: str) -> dict[str, Any]:
    """Convert plain text to Atlassian Document Format."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _adf_to_text(adf: dict | None) -> str:
    """Extract plain text from ADF document."""
    if not adf or not isinstance(adf, dict):
        return ""
    parts = []
    for block in adf.get("content", []):
        for inline in block.get("content", []):
            if inline.get("type") == "text":
                parts.append(inline.get("text", ""))
        parts.append("\n")
    return "".join(parts).strip()


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Jira tools with the MCP server."""

    @mcp.tool()
    def jira_search_issues(
        jql: str,
        max_results: int = 25,
        fields: str = "summary,status,assignee,priority,issuetype",
    ) -> dict[str, Any]:
        """
        Search Jira issues using JQL.

        Args:
            jql: JQL query string e.g. "project = PROJ AND status = 'In Progress'" (required)
            max_results: Max results (1-100, default 25)
            fields: Comma-separated field names (default summary,status,assignee,priority,issuetype)

        Returns:
            Dict with matching issues (key, summary, status, assignee)
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()
        if not jql:
            return {"error": "jql is required"}

        url = f"{_base_url(domain)}/search/jql"
        params = {
            "jql": jql,
            "maxResults": max(1, min(max_results, 100)),
            "fields": fields,
        }

        data = _request("get", url, email, token, params=params)
        if isinstance(data, dict) and "error" in data:
            return data

        issues = []
        for issue in data.get("issues", []):
            f = issue.get("fields", {})
            status = f.get("status") or {}
            assignee = f.get("assignee") or {}
            priority = f.get("priority") or {}
            issuetype = f.get("issuetype") or {}
            issues.append(
                {
                    "key": issue.get("key", ""),
                    "summary": f.get("summary", ""),
                    "status": status.get("name", ""),
                    "assignee": assignee.get("displayName", ""),
                    "priority": priority.get("name", ""),
                    "issuetype": issuetype.get("name", ""),
                }
            )
        return {"issues": issues, "count": len(issues)}

    @mcp.tool()
    def jira_get_issue(issue_key: str) -> dict[str, Any]:
        """
        Get details about a Jira issue.

        Args:
            issue_key: Issue key e.g. "PROJ-123" (required)

        Returns:
            Dict with issue details (key, summary, description, status, assignee, etc.)
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()
        if not issue_key:
            return {"error": "issue_key is required"}

        url = f"{_base_url(domain)}/issue/{issue_key}"
        data = _request("get", url, email, token)
        if isinstance(data, dict) and "error" in data:
            return data

        f = data.get("fields", {})
        status = f.get("status") or {}
        assignee = f.get("assignee") or {}
        reporter = f.get("reporter") or {}
        priority = f.get("priority") or {}
        issuetype = f.get("issuetype") or {}
        project = f.get("project") or {}

        return {
            "key": data.get("key", ""),
            "summary": f.get("summary", ""),
            "description": _adf_to_text(f.get("description")),
            "status": status.get("name", ""),
            "assignee": assignee.get("displayName", ""),
            "reporter": reporter.get("displayName", ""),
            "priority": priority.get("name", ""),
            "issuetype": issuetype.get("name", ""),
            "project": project.get("name", ""),
            "labels": f.get("labels", []),
            "created": f.get("created", ""),
            "updated": f.get("updated", ""),
        }

    @mcp.tool()
    def jira_create_issue(
        project_key: str,
        summary: str,
        issue_type: str = "Task",
        description: str = "",
        priority: str = "",
        labels: str = "",
    ) -> dict[str, Any]:
        """
        Create a new Jira issue.

        Args:
            project_key: Project key e.g. "PROJ" (required)
            summary: Issue summary/title (required)
            issue_type: Issue type: Task, Bug, Story, Epic (default Task)
            description: Plain text description (optional)
            priority: Priority name e.g. High, Medium, Low (optional)
            labels: Comma-separated labels (optional)

        Returns:
            Dict with created issue (key, id, url)
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()
        if not project_key or not summary:
            return {"error": "project_key and summary are required"}

        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        if description:
            fields["description"] = _text_to_adf(description)
        if priority:
            fields["priority"] = {"name": priority}
        if labels:
            fields["labels"] = [item.strip() for item in labels.split(",") if item.strip()]

        url = f"{_base_url(domain)}/issue"
        data = _request("post", url, email, token, json={"fields": fields})
        if isinstance(data, dict) and "error" in data:
            return data

        return {
            "key": data.get("key", ""),
            "id": data.get("id", ""),
            "url": f"https://{domain}/browse/{data.get('key', '')}",
            "status": "created",
        }

    @mcp.tool()
    def jira_list_projects(
        max_results: int = 50,
        query: str = "",
    ) -> dict[str, Any]:
        """
        List Jira projects.

        Args:
            max_results: Max results (1-100, default 50)
            query: Filter by project name/key (optional)

        Returns:
            Dict with projects list (key, name, type)
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()

        url = f"{_base_url(domain)}/project/search"
        params: dict[str, Any] = {
            "maxResults": max(1, min(max_results, 100)),
        }
        if query:
            params["query"] = query

        data = _request("get", url, email, token, params=params)
        if isinstance(data, dict) and "error" in data:
            return data

        projects = []
        for p in data.get("values", []):
            projects.append(
                {
                    "key": p.get("key", ""),
                    "name": p.get("name", ""),
                    "id": p.get("id", ""),
                    "project_type": p.get("projectTypeKey", ""),
                }
            )
        return {"projects": projects, "count": len(projects)}

    @mcp.tool()
    def jira_get_project(project_key: str) -> dict[str, Any]:
        """
        Get details about a Jira project.

        Args:
            project_key: Project key e.g. "PROJ" (required)

        Returns:
            Dict with project details (key, name, lead, issue types)
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()
        if not project_key:
            return {"error": "project_key is required"}

        url = f"{_base_url(domain)}/project/{project_key}"
        params = {"expand": "description,lead,issueTypes"}
        data = _request("get", url, email, token, params=params)
        if isinstance(data, dict) and "error" in data:
            return data

        lead = data.get("lead") or {}
        issue_types = [
            {"name": it.get("name", ""), "subtask": it.get("subtask", False)}
            for it in data.get("issueTypes", [])
        ]

        return {
            "key": data.get("key", ""),
            "name": data.get("name", ""),
            "id": data.get("id", ""),
            "description": data.get("description", ""),
            "lead": lead.get("displayName", ""),
            "project_type": data.get("projectTypeKey", ""),
            "issue_types": issue_types,
        }

    @mcp.tool()
    def jira_add_comment(
        issue_key: str,
        body: str,
    ) -> dict[str, Any]:
        """
        Add a comment to a Jira issue.

        Args:
            issue_key: Issue key e.g. "PROJ-123" (required)
            body: Comment text (required)

        Returns:
            Dict with comment details (id, author, created)
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()
        if not issue_key or not body:
            return {"error": "issue_key and body are required"}

        url = f"{_base_url(domain)}/issue/{issue_key}/comment"
        data = _request("post", url, email, token, json={"body": _text_to_adf(body)})
        if isinstance(data, dict) and "error" in data:
            return data

        author = data.get("author") or {}
        return {
            "id": data.get("id", ""),
            "author": author.get("displayName", ""),
            "created": data.get("created", ""),
            "status": "created",
        }

    @mcp.tool()
    def jira_update_issue(
        issue_key: str,
        summary: str = "",
        description: str = "",
        priority: str = "",
        labels: str = "",
        assignee_account_id: str = "",
    ) -> dict[str, Any]:
        """
        Update fields on an existing Jira issue.

        Args:
            issue_key: Issue key e.g. "PROJ-123" (required)
            summary: New summary/title (optional)
            description: New plain text description (optional)
            priority: New priority name e.g. High, Medium, Low (optional)
            labels: Comma-separated labels to replace existing labels (optional)
            assignee_account_id: Atlassian account ID to reassign to (optional)

        Returns:
            Dict with update status or error
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()
        if not issue_key:
            return {"error": "issue_key is required"}

        fields: dict[str, Any] = {}
        if summary:
            fields["summary"] = summary
        if description:
            fields["description"] = _text_to_adf(description)
        if priority:
            fields["priority"] = {"name": priority}
        if labels:
            fields["labels"] = [item.strip() for item in labels.split(",") if item.strip()]
        if assignee_account_id:
            fields["assignee"] = {"accountId": assignee_account_id}

        if not fields:
            return {"error": "At least one field to update is required"}

        url = f"{_base_url(domain)}/issue/{issue_key}"
        data = _request("put", url, email, token, json={"fields": fields})
        if isinstance(data, dict) and "error" in data:
            return data

        return {
            "key": issue_key,
            "status": "updated",
            "url": f"https://{domain}/browse/{issue_key}",
        }

    @mcp.tool()
    def jira_list_transitions(
        issue_key: str,
    ) -> dict[str, Any]:
        """
        List available status transitions for a Jira issue.

        Use this to discover which statuses an issue can move to before
        calling jira_transition_issue.

        Args:
            issue_key: Issue key e.g. "PROJ-123" (required)

        Returns:
            Dict with available transitions (id, name, to status)
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()
        if not issue_key:
            return {"error": "issue_key is required"}

        url = f"{_base_url(domain)}/issue/{issue_key}/transitions"
        data = _request("get", url, email, token)
        if isinstance(data, dict) and "error" in data:
            return data

        transitions = []
        for t in data.get("transitions", []):
            to_status = t.get("to") or {}
            transitions.append(
                {
                    "id": t.get("id", ""),
                    "name": t.get("name", ""),
                    "to_status": to_status.get("name", ""),
                }
            )
        return {"transitions": transitions, "count": len(transitions)}

    @mcp.tool()
    def jira_transition_issue(
        issue_key: str,
        transition_id: str,
        comment: str = "",
    ) -> dict[str, Any]:
        """
        Transition a Jira issue to a new status.

        Use jira_list_transitions first to find the correct transition_id.

        Args:
            issue_key: Issue key e.g. "PROJ-123" (required)
            transition_id: Transition ID from jira_list_transitions (required)
            comment: Optional comment to add with the transition

        Returns:
            Dict with transition status or error
        """
        domain, email, token = _get_credentials(credentials)
        if not domain or not email or not token:
            return _auth_error()
        if not issue_key or not transition_id:
            return {"error": "issue_key and transition_id are required"}

        body: dict[str, Any] = {"transition": {"id": transition_id}}
        if comment:
            body["update"] = {
                "comment": [{"add": {"body": _text_to_adf(comment)}}]
            }

        url = f"{_base_url(domain)}/issue/{issue_key}/transitions"
        data = _request("post", url, email, token, json=body)
        if isinstance(data, dict) and "error" in data:
            return data

        return {
            "key": issue_key,
            "status": "transitioned",
            "url": f"https://{domain}/browse/{issue_key}",
        }
