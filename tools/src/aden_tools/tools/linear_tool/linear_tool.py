"""
Linear Tool - Manage issues, projects, and teams via Linear GraphQL API.

Supports:
- Personal API Keys (LINEAR_API_KEY)
- OAuth2 tokens via the credential store

API Reference: https://developers.linear.app/docs/graphql/working-with-the-graphql-api
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

LINEAR_API_BASE = "https://api.linear.app/graphql"


class _LinearClient:
    """Internal client wrapping Linear GraphQL API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _execute_query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a GraphQL query against Linear API."""
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = httpx.post(
            LINEAR_API_BASE,
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP and GraphQL error codes."""
        if response.status_code == 401:
            return {"error": "Invalid or expired Linear API key"}
        if response.status_code == 403:
            return {"error": "Insufficient permissions. Check your Linear API key scopes."}
        if response.status_code == 429:
            return {"error": "Linear rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Linear API error (HTTP {response.status_code}): {detail}"}

        data = response.json()

        # Handle GraphQL errors
        if "errors" in data:
            errors = data["errors"]
            error_messages = [e.get("message", str(e)) for e in errors]
            return {"error": f"GraphQL error: {'; '.join(error_messages)}"}

        return data.get("data", data)

    # --- Issues ---

    def create_issue(
        self,
        title: str,
        team_id: str,
        description: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
        label_ids: list[str] | None = None,
        project_id: str | None = None,
        state_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new Linear issue."""
        mutation = """
        mutation IssueCreate($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue {
                    id
                    identifier
                    title
                    description
                    url
                    priority
                    state { id name }
                    assignee { id name }
                    labels { nodes { id name } }
                    project { id name }
                    createdAt
                }
            }
        }
        """
        input_data: dict[str, Any] = {"title": title, "teamId": team_id}
        if description:
            input_data["description"] = description
        if assignee_id:
            input_data["assigneeId"] = assignee_id
        if priority is not None:
            input_data["priority"] = priority
        if label_ids:
            input_data["labelIds"] = label_ids
        if project_id:
            input_data["projectId"] = project_id
        if state_id:
            input_data["stateId"] = state_id

        result = self._execute_query(mutation, {"input": input_data})
        if "error" in result:
            return result
        return result.get("issueCreate", result)

    def get_issue(self, issue_id: str) -> dict[str, Any]:
        """Get a Linear issue by ID or identifier (e.g., 'ENG-123')."""
        query = """
        query Issue($id: String!) {
            issue(id: $id) {
                id
                identifier
                title
                description
                url
                priority
                priorityLabel
                state { id name color }
                assignee { id name email }
                labels { nodes { id name color } }
                project { id name }
                team { id name key }
                comments { nodes { id body createdAt user { name } } }
                createdAt
                updatedAt
            }
        }
        """
        result = self._execute_query(query, {"id": issue_id})
        if "error" in result:
            return result
        return result.get("issue", result)

    def update_issue(
        self,
        issue_id: str,
        title: str | None = None,
        description: str | None = None,
        state_id: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
        label_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update an existing Linear issue."""
        mutation = """
        mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
                issue {
                    id
                    identifier
                    title
                    description
                    url
                    priority
                    state { id name }
                    assignee { id name }
                    labels { nodes { id name } }
                    updatedAt
                }
            }
        }
        """
        input_data: dict[str, Any] = {}
        if title is not None:
            input_data["title"] = title
        if description is not None:
            input_data["description"] = description
        if state_id is not None:
            input_data["stateId"] = state_id
        if assignee_id is not None:
            input_data["assigneeId"] = assignee_id
        if priority is not None:
            input_data["priority"] = priority
        if label_ids is not None:
            input_data["labelIds"] = label_ids

        result = self._execute_query(mutation, {"id": issue_id, "input": input_data})
        if "error" in result:
            return result
        return result.get("issueUpdate", result)

    def delete_issue(self, issue_id: str) -> dict[str, Any]:
        """Delete a Linear issue."""
        mutation = """
        mutation IssueDelete($id: String!) {
            issueDelete(id: $id) {
                success
            }
        }
        """
        result = self._execute_query(mutation, {"id": issue_id})
        if "error" in result:
            return result
        return result.get("issueDelete", result)

    def search_issues(
        self,
        query: str | None = None,
        team_id: str | None = None,
        assignee_id: str | None = None,
        state_id: str | None = None,
        label_ids: list[str] | None = None,
        project_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search Linear issues with filters."""
        gql_query = """
        query Issues($filter: IssueFilter, $first: Int) {
            issues(filter: $filter, first: $first) {
                nodes {
                    id
                    identifier
                    title
                    description
                    url
                    priority
                    priorityLabel
                    state { id name color }
                    assignee { id name }
                    labels { nodes { id name } }
                    project { id name }
                    team { id name key }
                    createdAt
                    updatedAt
                }
                pageInfo {
                    hasNextPage
                    endCursor
                }
            }
        }
        """
        filter_data: dict[str, Any] = {}
        if query:
            filter_data["or"] = [
                {"title": {"containsIgnoreCase": query}},
                {"description": {"containsIgnoreCase": query}},
            ]
        if team_id:
            filter_data["team"] = {"id": {"eq": team_id}}
        if assignee_id:
            filter_data["assignee"] = {"id": {"eq": assignee_id}}
        if state_id:
            filter_data["state"] = {"id": {"eq": state_id}}
        if label_ids:
            filter_data["labels"] = {"id": {"in": label_ids}}
        if project_id:
            filter_data["project"] = {"id": {"eq": project_id}}

        variables: dict[str, Any] = {"first": min(limit, 100)}
        if filter_data:
            variables["filter"] = filter_data

        result = self._execute_query(gql_query, variables)
        if "error" in result:
            return result
        issues_data = result.get("issues", {})
        return {
            "issues": issues_data.get("nodes", []),
            "total": len(issues_data.get("nodes", [])),
            "hasNextPage": issues_data.get("pageInfo", {}).get("hasNextPage", False),
        }

    def add_comment(self, issue_id: str, body: str) -> dict[str, Any]:
        """Add a comment to a Linear issue."""
        mutation = """
        mutation CommentCreate($input: CommentCreateInput!) {
            commentCreate(input: $input) {
                success
                comment {
                    id
                    body
                    createdAt
                    user { id name }
                }
            }
        }
        """
        result = self._execute_query(mutation, {"input": {"issueId": issue_id, "body": body}})
        if "error" in result:
            return result
        return result.get("commentCreate", result)

    # --- Projects ---

    def create_project(
        self,
        name: str,
        team_ids: list[str],
        description: str | None = None,
        state: str | None = None,
        target_date: str | None = None,
        lead_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new Linear project."""
        mutation = """
        mutation ProjectCreate($input: ProjectCreateInput!) {
            projectCreate(input: $input) {
                success
                project {
                    id
                    name
                    description
                    url
                    state
                    progress
                    targetDate
                    lead { id name }
                    teams { nodes { id name } }
                    createdAt
                }
            }
        }
        """
        input_data: dict[str, Any] = {"name": name, "teamIds": team_ids}
        if description:
            input_data["description"] = description
        if state:
            input_data["state"] = state
        if target_date:
            input_data["targetDate"] = target_date
        if lead_id:
            input_data["leadId"] = lead_id

        result = self._execute_query(mutation, {"input": input_data})
        if "error" in result:
            return result
        return result.get("projectCreate", result)

    def get_project(self, project_id: str) -> dict[str, Any]:
        """Get a Linear project by ID."""
        query = """
        query Project($id: String!) {
            project(id: $id) {
                id
                name
                description
                url
                state
                progress
                targetDate
                lead { id name email }
                teams { nodes { id name key } }
                issues { nodes { id identifier title state { name } } }
                createdAt
                updatedAt
            }
        }
        """
        result = self._execute_query(query, {"id": project_id})
        if "error" in result:
            return result
        return result.get("project", result)

    def update_project(
        self,
        project_id: str,
        name: str | None = None,
        description: str | None = None,
        state: str | None = None,
        target_date: str | None = None,
    ) -> dict[str, Any]:
        """Update a Linear project."""
        mutation = """
        mutation ProjectUpdate($id: String!, $input: ProjectUpdateInput!) {
            projectUpdate(id: $id, input: $input) {
                success
                project {
                    id
                    name
                    description
                    url
                    state
                    progress
                    targetDate
                    updatedAt
                }
            }
        }
        """
        input_data: dict[str, Any] = {}
        if name is not None:
            input_data["name"] = name
        if description is not None:
            input_data["description"] = description
        if state is not None:
            input_data["state"] = state
        if target_date is not None:
            input_data["targetDate"] = target_date

        result = self._execute_query(mutation, {"id": project_id, "input": input_data})
        if "error" in result:
            return result
        return result.get("projectUpdate", result)

    def list_projects(
        self,
        team_id: str | None = None,
        state: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List Linear projects with optional filters."""
        query = """
        query Projects($filter: ProjectFilter, $first: Int) {
            projects(filter: $filter, first: $first) {
                nodes {
                    id
                    name
                    description
                    url
                    state
                    progress
                    targetDate
                    lead { id name }
                    teams { nodes { id name } }
                }
                pageInfo {
                    hasNextPage
                    endCursor
                }
            }
        }
        """
        filter_data: dict[str, Any] = {}
        if team_id:
            filter_data["accessibleTeams"] = {"id": {"eq": team_id}}
        if state:
            filter_data["state"] = {"eq": state}

        variables: dict[str, Any] = {"first": min(limit, 100)}
        if filter_data:
            variables["filter"] = filter_data

        result = self._execute_query(query, variables)
        if "error" in result:
            return result
        projects_data = result.get("projects", {})
        return {
            "projects": projects_data.get("nodes", []),
            "total": len(projects_data.get("nodes", [])),
            "hasNextPage": projects_data.get("pageInfo", {}).get("hasNextPage", False),
        }

    # --- Teams ---

    def list_teams(self) -> dict[str, Any]:
        """List all teams in the workspace."""
        query = """
        query Teams {
            teams {
                nodes {
                    id
                    name
                    key
                    description
                    private
                    timezone
                }
            }
        }
        """
        result = self._execute_query(query)
        if "error" in result:
            return result
        teams_data = result.get("teams", {})
        return {
            "teams": teams_data.get("nodes", []),
            "total": len(teams_data.get("nodes", [])),
        }

    def get_team(self, team_id: str) -> dict[str, Any]:
        """Get team details by ID."""
        query = """
        query Team($id: String!) {
            team(id: $id) {
                id
                name
                key
                description
                private
                timezone
                states { nodes { id name color type position } }
                labels { nodes { id name color } }
                members { nodes { id name email } }
            }
        }
        """
        result = self._execute_query(query, {"id": team_id})
        if "error" in result:
            return result
        return result.get("team", result)

    def get_workflow_states(self, team_id: str) -> dict[str, Any]:
        """Get workflow states for a team."""
        query = """
        query WorkflowStates($teamId: String!) {
            workflowStates(filter: { team: { id: { eq: $teamId } } }) {
                nodes {
                    id
                    name
                    color
                    type
                    position
                    description
                }
            }
        }
        """
        result = self._execute_query(query, {"teamId": team_id})
        if "error" in result:
            return result
        states_data = result.get("workflowStates", {})
        return {
            "states": states_data.get("nodes", []),
            "total": len(states_data.get("nodes", [])),
        }

    # --- Labels ---

    def create_label(
        self,
        name: str,
        team_id: str,
        color: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new label for a team."""
        mutation = """
        mutation IssueLabelCreate($input: IssueLabelCreateInput!) {
            issueLabelCreate(input: $input) {
                success
                issueLabel {
                    id
                    name
                    color
                    description
                }
            }
        }
        """
        input_data: dict[str, Any] = {"name": name, "teamId": team_id}
        if color:
            input_data["color"] = color
        if description:
            input_data["description"] = description

        result = self._execute_query(mutation, {"input": input_data})
        if "error" in result:
            return result
        return result.get("issueLabelCreate", result)

    def list_labels(self, team_id: str | None = None) -> dict[str, Any]:
        """List all labels, optionally filtered by team."""
        query = """
        query IssueLabels($filter: IssueLabelFilter) {
            issueLabels(filter: $filter) {
                nodes {
                    id
                    name
                    color
                    description
                    team { id name }
                }
            }
        }
        """
        variables: dict[str, Any] = {}
        if team_id:
            variables["filter"] = {"team": {"id": {"eq": team_id}}}

        result = self._execute_query(query, variables if variables else None)
        if "error" in result:
            return result
        labels_data = result.get("issueLabels", {})
        return {
            "labels": labels_data.get("nodes", []),
            "total": len(labels_data.get("nodes", [])),
        }

    # --- Users ---

    def list_users(self) -> dict[str, Any]:
        """List all users in the workspace."""
        query = """
        query Users {
            users {
                nodes {
                    id
                    name
                    displayName
                    email
                    active
                    admin
                    avatarUrl
                }
            }
        }
        """
        result = self._execute_query(query)
        if "error" in result:
            return result
        users_data = result.get("users", {})
        return {
            "users": users_data.get("nodes", []),
            "total": len(users_data.get("nodes", [])),
        }

    def get_user(self, user_id: str) -> dict[str, Any]:
        """Get user details by ID."""
        query = """
        query User($id: String!) {
            user(id: $id) {
                id
                name
                displayName
                email
                active
                admin
                avatarUrl
                assignedIssues {
                    nodes {
                        id
                        identifier
                        title
                        state { name }
                    }
                }
            }
        }
        """
        result = self._execute_query(query, {"id": user_id})
        if "error" in result:
            return result
        return result.get("user", result)

    def get_viewer(self) -> dict[str, Any]:
        """Get details about the authenticated user."""
        query = """
        query Viewer {
            viewer {
                id
                name
                displayName
                email
                active
                admin
                avatarUrl
                assignedIssues {
                    nodes {
                        id
                        identifier
                        title
                        state { name }
                        priority
                    }
                }
            }
        }
        """
        result = self._execute_query(query)
        if "error" in result:
            return result
        return result.get("viewer", result)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Linear tools with the MCP server."""

    def _get_api_key() -> str | None:
        """Get Linear API key from credential manager or environment."""
        if credentials is not None:
            try:
                api_key = credentials.get("linear")
                # Defensive check: ensure we get a string, not a complex object
                if api_key is not None and not isinstance(api_key, str):
                    raise TypeError(
                        f"Expected string from credentials.get('linear'), got {type(api_key).__name__}"
                    )
                if api_key is not None:
                    return api_key
            except Exception:
                # Fall through to environment variable if credential store fails
                # (e.g., decryption error, corruption, etc.)
                pass
        return os.getenv("LINEAR_API_KEY")

    def _get_client() -> _LinearClient | dict[str, str]:
        """Get a Linear client, or return an error dict if no credentials."""
        api_key = _get_api_key()
        if not api_key:
            return {
                "error": "Linear credentials not configured",
                "help": (
                    "Set LINEAR_API_KEY environment variable "
                    "or configure via credential store. "
                    "Get an API key at https://linear.app/settings/api"
                ),
            }
        return _LinearClient(api_key)

    # --- Issues ---

    @mcp.tool()
    def linear_issue_create(
        title: str,
        team_id: str,
        description: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
        label_ids: list[str] | None = None,
        project_id: str | None = None,
        state_id: str | None = None,
    ) -> dict:
        """
        Create a new Linear issue.

        Args:
            title: Issue title (required)
            team_id: ID of the team to create issue in (required)
            description: Markdown description
            assignee_id: User ID to assign issue to
            priority: Priority level (0=None, 1=Urgent, 2=High, 3=Medium, 4=Low)
            label_ids: List of label IDs to attach
            project_id: Project ID to add issue to
            state_id: Workflow state ID (defaults to team's first Backlog state)

        Returns:
            Dict with created issue including id, identifier (e.g., "ENG-123"), url
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_issue(
                title=title,
                team_id=team_id,
                description=description,
                assignee_id=assignee_id,
                priority=priority,
                label_ids=label_ids,
                project_id=project_id,
                state_id=state_id,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def linear_issue_get(issue_id: str) -> dict:
        """
        Get a Linear issue by ID or identifier.

        Args:
            issue_id: Issue UUID or identifier (e.g., 'ENG-123')

        Returns:
            Dict with issue details including title, description, state, assignee, etc.
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_issue(issue_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def linear_issue_update(
        issue_id: str,
        title: str | None = None,
        description: str | None = None,
        state_id: str | None = None,
        assignee_id: str | None = None,
        priority: int | None = None,
        label_ids: list[str] | None = None,
    ) -> dict:
        """
        Update an existing Linear issue.

        Args:
            issue_id: Issue UUID or identifier (e.g., 'ENG-123')
            title: New title
            description: New description (markdown)
            state_id: Workflow state ID to transition to
            assignee_id: User ID to assign (or null to unassign)
            priority: Priority level (0=None, 1=Urgent, 2=High, 3=Medium, 4=Low)
            label_ids: New list of label IDs (replaces existing)

        Returns:
            Dict with updated issue details
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.update_issue(
                issue_id=issue_id,
                title=title,
                description=description,
                state_id=state_id,
                assignee_id=assignee_id,
                priority=priority,
                label_ids=label_ids,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def linear_issue_delete(issue_id: str) -> dict:
        """
        Delete a Linear issue.

        Args:
            issue_id: Issue UUID or identifier (e.g., 'ENG-123')

        Returns:
            Dict with success status
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.delete_issue(issue_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def linear_issue_search(
        query: str | None = None,
        team_id: str | None = None,
        assignee_id: str | None = None,
        state_id: str | None = None,
        label_ids: list[str] | None = None,
        project_id: str | None = None,
        limit: int = 50,
    ) -> dict:
        """
        Search Linear issues with filters.

        Args:
            query: Text search in title and description
            team_id: Filter by team ID
            assignee_id: Filter by assignee user ID
            state_id: Filter by workflow state ID
            label_ids: Filter by label IDs
            project_id: Filter by project ID
            limit: Maximum number of results (1-100, default 50)

        Returns:
            Dict with issues list and pagination info
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.search_issues(
                query=query,
                team_id=team_id,
                assignee_id=assignee_id,
                state_id=state_id,
                label_ids=label_ids,
                project_id=project_id,
                limit=limit,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def linear_issue_add_comment(issue_id: str, body: str) -> dict:
        """
        Add a comment to a Linear issue.

        Args:
            issue_id: Issue UUID or identifier (e.g., 'ENG-123')
            body: Comment body (supports markdown and @mentions)

        Returns:
            Dict with created comment details
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.add_comment(issue_id, body)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Projects ---

    @mcp.tool()
    def linear_project_create(
        name: str,
        team_ids: list[str],
        description: str | None = None,
        state: str | None = None,
        target_date: str | None = None,
        lead_id: str | None = None,
    ) -> dict:
        """
        Create a new Linear project.

        Args:
            name: Project name (required)
            team_ids: List of team IDs to associate with project (required)
            description: Project description (markdown)
            state: Project state (planned, started, paused, completed, canceled)
            target_date: Target completion date (ISO 8601, e.g., '2026-03-31')
            lead_id: User ID of project lead

        Returns:
            Dict with created project details
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_project(
                name=name,
                team_ids=team_ids,
                description=description,
                state=state,
                target_date=target_date,
                lead_id=lead_id,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def linear_project_get(project_id: str) -> dict:
        """
        Get a Linear project by ID.

        Args:
            project_id: Project UUID

        Returns:
            Dict with project details including issues, milestones, and progress
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_project(project_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def linear_project_update(
        project_id: str,
        name: str | None = None,
        description: str | None = None,
        state: str | None = None,
        target_date: str | None = None,
    ) -> dict:
        """
        Update a Linear project.

        Args:
            project_id: Project UUID
            name: New project name
            description: New description (markdown)
            state: New state (planned, started, paused, completed, canceled)
            target_date: New target date (ISO 8601)

        Returns:
            Dict with updated project details
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.update_project(
                project_id=project_id,
                name=name,
                description=description,
                state=state,
                target_date=target_date,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def linear_project_list(
        team_id: str | None = None,
        state: str | None = None,
        limit: int = 50,
    ) -> dict:
        """
        List Linear projects with optional filters.

        Args:
            team_id: Filter by team ID
            state: Filter by state (planned, started, paused, completed, canceled)
            limit: Maximum number of results (1-100, default 50)

        Returns:
            Dict with projects list and pagination info
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_projects(team_id=team_id, state=state, limit=limit)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Teams ---

    @mcp.tool()
    def linear_teams_list() -> dict:
        """
        List all teams in the Linear workspace.

        Returns:
            Dict with teams list including id, name, and key
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_teams()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def linear_team_get(team_id: str) -> dict:
        """
        Get team details including workflow states and members.

        Args:
            team_id: Team UUID

        Returns:
            Dict with team details, states, labels, and members
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_team(team_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def linear_workflow_states_get(team_id: str) -> dict:
        """
        Get workflow states for a team (e.g., Backlog, Todo, In Progress, Done).

        Args:
            team_id: Team UUID

        Returns:
            Dict with states list including id, name, color, and type
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_workflow_states(team_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Labels ---

    @mcp.tool()
    def linear_label_create(
        name: str,
        team_id: str,
        color: str | None = None,
        description: str | None = None,
    ) -> dict:
        """
        Create a new label for a team.

        Args:
            name: Label name (required)
            team_id: Team UUID (required)
            color: Hex color code (e.g., '#FF5733')
            description: Label description

        Returns:
            Dict with created label details
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_label(
                name=name,
                team_id=team_id,
                color=color,
                description=description,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def linear_labels_list(team_id: str | None = None) -> dict:
        """
        List all labels, optionally filtered by team.

        Args:
            team_id: Optional team UUID to filter labels

        Returns:
            Dict with labels list including id, name, color
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_labels(team_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Users ---

    @mcp.tool()
    def linear_users_list() -> dict:
        """
        List all users in the Linear workspace.

        Returns:
            Dict with users list including id, name, email
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_users()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def linear_user_get(user_id: str) -> dict:
        """
        Get user details and assigned issues.

        Args:
            user_id: User UUID

        Returns:
            Dict with user details and their assigned issues
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_user(user_id)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def linear_viewer() -> dict:
        """
        Get details about the authenticated user (viewer).

        Returns:
            Dict with viewer details including assigned issues
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.get_viewer()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
