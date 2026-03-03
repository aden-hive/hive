"""
Linear Tool - Issue tracking and project management via GraphQL API.

Supports:
- Linear API key (LINEAR_API_KEY)
- Issues, Projects, Teams, Cycles
- GraphQL queries and mutations

API Reference: https://developers.linear.app/docs
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

LINEAR_API = "https://api.linear.app/graphql"


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("linear")
    return os.getenv("LINEAR_API_KEY")


def _gql(token: str, query: str, variables: dict | None = None) -> dict[str, Any]:
    """Execute a GraphQL query against Linear API."""
    try:
        resp = httpx.post(
            LINEAR_API,
            headers={"Authorization": token, "Content-Type": "application/json"},
            json={"query": query, "variables": variables or {}},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your LINEAR_API_KEY."}
        if resp.status_code != 200:
            return {"error": f"Linear API error {resp.status_code}: {resp.text[:500]}"}
        data = resp.json()
        if data.get("errors"):
            return {"error": data["errors"][0].get("message", "GraphQL error")}
        return data.get("data", {})
    except httpx.TimeoutException:
        return {"error": "Request to Linear timed out"}
    except Exception as e:
        return {"error": f"Linear request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "LINEAR_API_KEY not set",
        "help": "Create an API key at Linear Settings > Account > Security & Access",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Linear tools with the MCP server."""

    @mcp.tool()
    def linear_list_issues(
        team_key: str = "",
        state: str = "",
        assignee_name: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        List issues from Linear, optionally filtered by team, state, or assignee.

        Args:
            team_key: Team key to filter by (e.g. "ENG") (optional)
            state: Filter by state name (e.g. "In Progress", "Done") (optional)
            assignee_name: Filter by assignee display name (optional)
            limit: Number of results (1-250, default 50)

        Returns:
            Dict with issues list (id, identifier, title, state, priority, assignee, createdAt)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        filters = []
        if team_key:
            filters.append(f'team: {{ key: {{ eq: "{team_key}" }} }}')
        if state:
            filters.append(f'state: {{ name: {{ eq: "{state}" }} }}')
        if assignee_name:
            filters.append(f'assignee: {{ displayName: {{ eq: "{assignee_name}" }} }}')

        filter_str = ", ".join(filters)
        filter_arg = f", filter: {{ {filter_str} }}" if filter_str else ""

        query = f"""
        query {{
          issues(first: {max(1, min(limit, 250))}{filter_arg}) {{
            nodes {{
              id
              identifier
              title
              state {{ name }}
              priority
              assignee {{ displayName }}
              createdAt
              updatedAt
            }}
          }}
        }}
        """
        data = _gql(token, query)
        if "error" in data:
            return data

        issues = []
        for i in data.get("issues", {}).get("nodes", []):
            issues.append({
                "id": i.get("id", ""),
                "identifier": i.get("identifier", ""),
                "title": i.get("title", ""),
                "state": (i.get("state") or {}).get("name", ""),
                "priority": i.get("priority", 0),
                "assignee": (i.get("assignee") or {}).get("displayName", ""),
                "created_at": i.get("createdAt", ""),
            })
        return {"issues": issues, "count": len(issues)}

    @mcp.tool()
    def linear_get_issue(issue_id: str) -> dict[str, Any]:
        """
        Get details of a specific Linear issue by ID or identifier.

        Args:
            issue_id: Issue ID (UUID) or identifier (e.g. "ENG-123")

        Returns:
            Dict with issue details including description, labels, comments count
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not issue_id:
            return {"error": "issue_id is required"}

        query = """
        query($id: String!) {
          issue(id: $id) {
            id
            identifier
            title
            description
            state { name }
            priority
            assignee { displayName }
            project { name }
            labels { nodes { name } }
            estimate
            dueDate
            createdAt
            updatedAt
          }
        }
        """
        data = _gql(token, query, {"id": issue_id})
        if "error" in data:
            return data

        i = data.get("issue") or {}
        if not i:
            return {"error": f"Issue '{issue_id}' not found"}

        desc = i.get("description", "") or ""
        if len(desc) > 1000:
            desc = desc[:1000] + "..."

        return {
            "id": i.get("id", ""),
            "identifier": i.get("identifier", ""),
            "title": i.get("title", ""),
            "description": desc,
            "state": (i.get("state") or {}).get("name", ""),
            "priority": i.get("priority", 0),
            "assignee": (i.get("assignee") or {}).get("displayName", ""),
            "project": (i.get("project") or {}).get("name", ""),
            "labels": [l.get("name", "") for l in (i.get("labels") or {}).get("nodes", [])],
            "estimate": i.get("estimate"),
            "due_date": i.get("dueDate", ""),
            "created_at": i.get("createdAt", ""),
        }

    @mcp.tool()
    def linear_create_issue(
        team_id: str,
        title: str,
        description: str = "",
        priority: int = 0,
        assignee_id: str = "",
    ) -> dict[str, Any]:
        """
        Create a new issue in Linear.

        Args:
            team_id: Team ID (UUID) to create the issue in (required)
            title: Issue title (required)
            description: Issue description in markdown (optional)
            priority: Priority level 0-4 (0=none, 1=urgent, 2=high, 3=medium, 4=low)
            assignee_id: Assignee user ID (optional)

        Returns:
            Dict with created issue id, identifier, and status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not team_id or not title:
            return {"error": "team_id and title are required"}

        mutation = """
        mutation($input: IssueCreateInput!) {
          issueCreate(input: $input) {
            success
            issue {
              id
              identifier
              title
            }
          }
        }
        """
        input_data: dict[str, Any] = {"teamId": team_id, "title": title}
        if description:
            input_data["description"] = description
        if priority:
            input_data["priority"] = priority
        if assignee_id:
            input_data["assigneeId"] = assignee_id

        data = _gql(token, mutation, {"input": input_data})
        if "error" in data:
            return data

        result = data.get("issueCreate", {})
        if not result.get("success"):
            return {"error": "Failed to create issue"}

        issue = result.get("issue", {})
        return {
            "id": issue.get("id", ""),
            "identifier": issue.get("identifier", ""),
            "title": issue.get("title", ""),
            "status": "created",
        }

    @mcp.tool()
    def linear_list_teams() -> dict[str, Any]:
        """
        List all teams in the Linear workspace.

        Returns:
            Dict with teams list (id, name, key, description)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        query = """
        query {
          teams {
            nodes {
              id
              name
              key
              description
            }
          }
        }
        """
        data = _gql(token, query)
        if "error" in data:
            return data

        teams = []
        for t in data.get("teams", {}).get("nodes", []):
            teams.append({
                "id": t.get("id", ""),
                "name": t.get("name", ""),
                "key": t.get("key", ""),
                "description": (t.get("description", "") or "")[:200],
            })
        return {"teams": teams}

    @mcp.tool()
    def linear_list_projects(limit: int = 50) -> dict[str, Any]:
        """
        List projects in the Linear workspace.

        Args:
            limit: Number of results (1-250, default 50)

        Returns:
            Dict with projects list (id, name, state, progress, lead, targetDate)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        query = f"""
        query {{
          projects(first: {max(1, min(limit, 250))}) {{
            nodes {{
              id
              name
              state
              progress
              lead {{ displayName }}
              targetDate
              startDate
            }}
          }}
        }}
        """
        data = _gql(token, query)
        if "error" in data:
            return data

        projects = []
        for p in data.get("projects", {}).get("nodes", []):
            projects.append({
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "state": p.get("state", ""),
                "progress": round(p.get("progress", 0), 2),
                "lead": (p.get("lead") or {}).get("displayName", ""),
                "target_date": p.get("targetDate", ""),
            })
        return {"projects": projects}

    @mcp.tool()
    def linear_search_issues(
        query: str,
        limit: int = 25,
    ) -> dict[str, Any]:
        """
        Search for issues in Linear by text.

        Args:
            query: Search text (matches title, description, comments)
            limit: Number of results (1-250, default 25)

        Returns:
            Dict with matching issues (id, identifier, title, state)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not query:
            return {"error": "query is required"}

        gql = """
        query($term: String!, $first: Int!) {
          searchIssues(term: $term, first: $first) {
            nodes {
              id
              identifier
              title
              state { name }
              assignee { displayName }
            }
          }
        }
        """
        data = _gql(token, gql, {"term": query, "first": max(1, min(limit, 250))})
        if "error" in data:
            return data

        issues = []
        for i in data.get("searchIssues", {}).get("nodes", []):
            issues.append({
                "id": i.get("id", ""),
                "identifier": i.get("identifier", ""),
                "title": i.get("title", ""),
                "state": (i.get("state") or {}).get("name", ""),
                "assignee": (i.get("assignee") or {}).get("displayName", ""),
            })
        return {"query": query, "results": issues}
