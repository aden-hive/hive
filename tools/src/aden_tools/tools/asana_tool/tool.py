"""
Asana Tool - Manage tasks, projects, and workspaces via Asana API.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import asana  # type: ignore
from asana.rest import ApiException  # type: ignore
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def to_dict(obj: Any) -> Any:
    """Helper to convert API response objects to dicts."""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, list):
        return [to_dict(x) for x in obj]
    return obj


def get_workspace_gid(
    client: asana.ApiClient, workspace_name_or_gid: str | None = None
) -> str:
    """Helper to resolve workspace GID from name or ID, or return default."""
    workspaces_api = asana.WorkspacesApi(client)

    try:
        # Request name,gid to be efficient
        # Note: In Asana python-asana v5+, opt_fields are kwargs
        response = workspaces_api.get_workspaces(opt_fields="name,gid")

        # Handle response format (v5/data collection)
        workspaces = []
        if hasattr(response, "data"):
            workspaces = response.data
        else:
            workspaces = list(response)

        if not workspaces:
            # If we successfully listed but found nothing
            raise ValueError("No accessible workspaces found for this token")

        # If no specific workspace requested, return the first one
        if not workspace_name_or_gid:
            first = workspaces[0]
            return str(first["gid"] if isinstance(first, dict) else first.gid)

        # Search by name or GID in the accessible list
        search_target = str(workspace_name_or_gid)
        for ws in workspaces:
            gid = str(ws["gid"] if isinstance(ws, dict) else ws.gid)
            name = ws["name"] if isinstance(ws, dict) else ws.name
            if gid == search_target or name == search_target:
                return gid

    except ApiException as e:
        # Don't swallow auth errors
        if e.status in (401, 403):
            raise ValueError(f"Asana authentication failed: {e}") from e
        
        # For other errors, if a GID was provided, we might try to blindly use it
        # (e.g. if listing workspaces is restricted but accessing a specific one isn't)
        if workspace_name_or_gid and str(workspace_name_or_gid).isdigit():
             return str(workspace_name_or_gid)
        
        raise ValueError(f"Failed to resolve workspace: {e}") from e

    # If we looked through the list and didn't find it
    # Fallback: if it looks like a GID, trust it (maybe it's a hidden workspace)
    if workspace_name_or_gid and str(workspace_name_or_gid).isdigit():
        return str(workspace_name_or_gid)

    raise ValueError(f"Workspace '{workspace_name_or_gid}' not found")


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Asana tools with the MCP server."""

    def _get_token() -> str | None:
        """Get Asana access token from credential manager or environment."""
        if credentials is not None:
            token = credentials.get("asana")
            # Defensive check: ensure we get a string
            if token is not None and not isinstance(token, str):
                return None
            return token
        return os.getenv("ASANA_ACCESS_TOKEN")

    def _get_client() -> asana.ApiClient | dict[str, str]:
        """Get an Asana client, or return an error dict if no credentials."""
        token = _get_token()
        if not token:
            return {
                "error": "Asana credentials not configured",
                "help": (
                    "Set ASANA_ACCESS_TOKEN environment variable "
                    "or configure via credential store"
                ),
            }

        configuration = asana.Configuration()
        configuration.access_token = token
        return asana.ApiClient(configuration)

    # --- Task Tools ---

    @mcp.tool()
    def asana_create_task(
        name: str,
        workspace: str | None = None,
        notes: str | None = None,
        assignee: str | None = None,
        projects: list[str] | None = None,
        due_on: str | None = None,
        start_on: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new task in Asana."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            tasks_api = asana.TasksApi(client)
            workspace_gid = get_workspace_gid(client, workspace)

            task_data: dict[str, Any] = {
                "workspace": workspace_gid,
                "name": name,
            }
            if notes:
                task_data["notes"] = notes
            if assignee:
                task_data["assignee"] = assignee
            if projects:
                task_data["projects"] = projects
            if due_on:
                task_data["due_on"] = due_on
            if start_on:
                task_data["start_on"] = start_on
            if tags:
                task_data["tags"] = tags

            body = {"data": task_data}
            result = tasks_api.create_task(body)
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_update_task(
        task_gid: str,
        name: str | None = None,
        notes: str | None = None,
        assignee: str | None = None,
        due_on: str | None = None,
        completed: bool | None = None,
    ) -> dict[str, Any]:
        """Update an existing task."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            tasks_api = asana.TasksApi(client)

            task_data: dict[str, Any] = {}
            if name:
                task_data["name"] = name
            if notes:
                task_data["notes"] = notes
            if assignee:
                task_data["assignee"] = assignee
            if due_on:
                task_data["due_on"] = due_on
            if completed is not None:
                task_data["completed"] = completed

            if not task_data:
                return {"error": "No fields to update"}

            # Note: task_gid must be string
            body = {"data": task_data}
            result = tasks_api.update_task(body, str(task_gid))
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_get_task(task_gid: str) -> dict[str, Any]:
        """Get details of a task."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            tasks_api = asana.TasksApi(client)
            result = tasks_api.get_task(str(task_gid))
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_search_tasks(
        workspace: str | None = None,
        text: str | None = None,
        assignee: str | None = None,
        project: str | None = None,
        completed: bool | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search for tasks in a workspace."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            tasks_api = asana.TasksApi(client)
            workspace_gid = get_workspace_gid(client, workspace)

            opts = {
                "limit": limit,
                "opt_fields": "name,gid,completed,assignee.name,projects.name",
            }
            if text:
                opts["text"] = text
            if assignee:
                opts["assignee.any"] = assignee
            if project:
                opts["projects.any"] = project
            if completed is not None:
                opts["completed"] = str(completed).lower()

            result = tasks_api.search_tasks_for_workspace(workspace_gid, **opts)
            data = list(result.data) if hasattr(result, "data") else list(result)
            return {"data": to_dict(data)}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_delete_task(task_gid: str) -> dict[str, Any]:
        """Delete a task."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            tasks_api = asana.TasksApi(client)
            result = tasks_api.delete_task(str(task_gid))
            return {"success": True, "result": to_dict(result)}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_add_task_comment(task_gid: str, text: str) -> dict[str, Any]:
        """Add a comment to a task."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            stories_api = asana.StoriesApi(client)
            body = {"data": {"text": text}}
            result = stories_api.create_story_for_task(body, str(task_gid))
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_complete_task(task_gid: str) -> dict[str, Any]:
        """Mark a task as complete."""
        # Reuse update logic
        return asana_update_task(task_gid, completed=True)

    @mcp.tool()
    def asana_add_subtask(
        parent_task_gid: str,
        name: str,
        notes: str | None = None,
        assignee: str | None = None,
        due_on: str | None = None,
    ) -> dict[str, Any]:
        """Create a subtask."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            tasks_api = asana.TasksApi(client)

            task_data: dict[str, Any] = {"name": name}
            if notes:
                task_data["notes"] = notes
            if assignee:
                task_data["assignee"] = assignee
            if due_on:
                task_data["due_on"] = due_on

            body = {"data": task_data}
            result = tasks_api.create_subtask_for_task(body, str(parent_task_gid))
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    # --- Project Tools ---

    @mcp.tool()
    def asana_create_project(
        name: str,
        workspace: str | None = None,
        team: str | None = None,
        notes: str | None = None,
        public: bool = True,
    ) -> dict[str, Any]:
        """Create a new project."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            projects_api = asana.ProjectsApi(client)
            workspace_gid = get_workspace_gid(client, workspace)

            project_data: dict[str, Any] = {
                "name": name,
                "workspace": workspace_gid,
                "public": public,
            }
            if team:
                project_data["team"] = team
            if notes:
                project_data["notes"] = notes

            body = {"data": project_data}
            result = projects_api.create_project(body)
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_update_project(
        project_gid: str,
        name: str | None = None,
        notes: str | None = None,
        public: bool | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        """Update a project."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            projects_api = asana.ProjectsApi(client)

            project_data: dict[str, Any] = {}
            if name:
                project_data["name"] = name
            if notes:
                project_data["notes"] = notes
            if public is not None:
                project_data["public"] = public
            if owner:
                project_data["owner"] = owner

            if not project_data:
                return {"error": "No fields to update"}

            body = {"data": project_data}
            result = projects_api.update_project(body, str(project_gid))
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_get_project(project_gid: str) -> dict[str, Any]:
        """Get project details."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            projects_api = asana.ProjectsApi(client)
            result = projects_api.get_project(str(project_gid))
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_list_projects(
        workspace: str | None = None,
        team: str | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any]:
        """List projects in a workspace or team."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            projects_api = asana.ProjectsApi(client)
            workspace_gid = get_workspace_gid(client, workspace)

            opts: dict[str, Any] = {"workspace": workspace_gid}
            if team:
                opts["team"] = team
            if archived is not None:
                opts["archived"] = archived

            result = projects_api.get_projects(**opts)
            data = list(result.data) if hasattr(result, "data") else list(result)
            return {"data": to_dict(data)}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_get_project_tasks(
        project_gid: str,
        completed_since: str | None = None,
    ) -> dict[str, Any]:
        """Get tasks in a project."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client
            
            tasks_api = asana.TasksApi(client)

            opts = {"project": str(project_gid)}
            if completed_since:
                opts["completed_since"] = completed_since

            # get_tasks_for_project is cleaner than get_tasks with project filter
            result = tasks_api.get_tasks_for_project(str(project_gid), **opts)
            data = list(result.data) if hasattr(result, "data") else list(result)
            return {"data": to_dict(data)}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_add_task_to_project(
        task_gid: str,
        project_gid: str,
        section_gid: str | None = None,
        insert_after: str | None = None,
        insert_before: str | None = None,
    ) -> dict[str, Any]:
        """Add a task to a project."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            tasks_api = asana.TasksApi(client)

            data: dict[str, Any] = {"project": project_gid}
            if section_gid:
                data["section"] = section_gid
            if insert_after:
                data["insert_after"] = insert_after
            if insert_before:
                data["insert_before"] = insert_before

            body = {"data": data}
            result = tasks_api.add_project_for_task(body, str(task_gid))
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    # --- Workspace / User Tools ---

    @mcp.tool()
    def asana_get_workspace(workspace_gid: str | None = None) -> dict[str, Any]:
        """Get workspace details."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            workspaces_api = asana.WorkspacesApi(client)
            gid = get_workspace_gid(client, workspace_gid)
            result = workspaces_api.get_workspace(gid)
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_list_workspaces() -> dict[str, Any]:
        """List all accessible workspaces."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            workspaces_api = asana.WorkspacesApi(client)
            result = workspaces_api.get_workspaces()
            data = list(result.data) if hasattr(result, "data") else list(result)
            return {"data": to_dict(data)}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_get_user(user_gid: str) -> dict[str, Any]:
        """Get user information."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            users_api = asana.UsersApi(client)
            result = users_api.get_user(user_gid)
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_list_team_members(
        workspace: str | None = None,
        team_gid: str | None = None,
    ) -> dict[str, Any]:
        """List users in a workspace or team."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            users_api = asana.UsersApi(client)
            workspace_gid = get_workspace_gid(client, workspace)

            opts = {"workspace": workspace_gid}
            if team_gid:
                opts["team"] = team_gid

            result = users_api.get_users(**opts)
            data = list(result.data) if hasattr(result, "data") else list(result)
            return {"data": to_dict(data)}
        except Exception as e:
            return {"error": str(e)}

    # --- Section Tools ---

    @mcp.tool()
    def asana_create_section(
        project_gid: str,
        name: str,
    ) -> dict[str, Any]:
        """Create a section in a project."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            sections_api = asana.SectionsApi(client)
            body = {"data": {"name": name}}
            result = sections_api.create_section_for_project(body, str(project_gid))
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_list_sections(project_gid: str) -> dict[str, Any]:
        """List sections in a project."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            sections_api = asana.SectionsApi(client)
            result = sections_api.get_sections_for_project(str(project_gid))
            data = list(result.data) if hasattr(result, "data") else list(result)
            return {"data": to_dict(data)}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_move_task_to_section(
        task_gid: str,
        section_gid: str,
    ) -> dict[str, Any]:
        """Move a task to a specific section."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            sections_api = asana.SectionsApi(client)
            body = {"data": {"task": str(task_gid)}}
            result = sections_api.add_task_for_section(body, str(section_gid))
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    # --- Tag / Custom Field Tools ---

    @mcp.tool()
    def asana_create_tag(
        name: str,
        workspace: str | None = None,
        color: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Create a new tag."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            tags_api = asana.TagsApi(client)
            workspace_gid = get_workspace_gid(client, workspace)

            data: dict[str, Any] = {"workspace": workspace_gid, "name": name}
            if color:
                data["color"] = color
            if notes:
                data["notes"] = notes

            body = {"data": data}
            result = tags_api.create_tag(body)
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_add_tag_to_task(
        task_gid: str,
        tag_gid: str,
    ) -> dict[str, Any]:
        """Add a tag to a task."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            tasks_api = asana.TasksApi(client)
            body = {"data": {"tag": tag_gid}}
            result = tasks_api.add_tag_for_task(body, str(task_gid))
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_list_tags(workspace: str | None = None) -> dict[str, Any]:
        """List tags in a workspace."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            tags_api = asana.TagsApi(client)
            workspace_gid = get_workspace_gid(client, workspace)
            
            # Note: tags API often requires workspace filter
            result = tags_api.get_tags(workspace=workspace_gid)
            data = list(result.data) if hasattr(result, "data") else list(result)
            return {"data": to_dict(data)}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_update_custom_field(
        task_gid: str,
        custom_field_gid: str,
        value: str | float | int,
    ) -> dict[str, Any]:
        """Update a custom field value on a task."""
        try:
            client = _get_client()
            if isinstance(client, dict):
                return client

            tasks_api = asana.TasksApi(client)

            params = {"custom_fields": {custom_field_gid: value}}
            body = {"data": params}
            result = tasks_api.update_task(body, str(task_gid))
            return to_dict(result)
        except Exception as e:
            return {"error": str(e)}
