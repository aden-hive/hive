from typing import Any, Dict, List, Optional, Union
import asana
from asana.rest import ApiException
from fastmcp import FastMCP

def get_client(credentials) -> asana.ApiClient:
    token = credentials.get("asana_access_token")
    if not token:
        raise ValueError("ASANA_ACCESS_TOKEN is not set")
    
    configuration = asana.Configuration()
    configuration.access_token = token
    return asana.ApiClient(configuration)

def to_dict(obj: Any) -> Any:
    """Helper to convert API response objects to dicts."""
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    if isinstance(obj, list):
        return [to_dict(x) for x in obj]
    return obj

def get_workspace_gid(client: asana.ApiClient, workspace_name_or_gid: Optional[str] = None) -> str:
    """Helper to resolve workspace GID from name or ID, or return default."""
    workspaces_api = asana.WorkspacesApi(client)
    
    try:
        # get_workspaces returns response with data
        # We request name,gid to be efficient
        # Opt fields are passed as kwargs usually in v5
        response = workspaces_api.get_workspaces(opt_fields="name,gid")
        
        # In v5, response from get_workspaces is usually a collection object, iterating yields items
        # Or it has a 'data' attribute.
        # Let's handle both.
        workspaces = []
        if hasattr(response, 'data'):
            workspaces = response.data
        else:
            # Maybe it's directly iterable
            workspaces = list(response)
            
        if not workspace_name_or_gid:
            if not workspaces:
                raise ValueError("No workspaces found")
            first = workspaces[0]
            return first['gid'] if isinstance(first, dict) else first.gid
        
        # Search by name or GID
        for ws in workspaces:
            gid = ws['gid'] if isinstance(ws, dict) else ws.gid
            name = ws['name'] if isinstance(ws, dict) else ws.name
            if gid == workspace_name_or_gid or name == workspace_name_or_gid:
                return gid
                
    except ApiException as e:
        # If we can't list workspaces, and provided a GID, maybe just try using it?
        if workspace_name_or_gid:
             return workspace_name_or_gid
        raise ValueError(f"Failed to list workspaces: {e}")

    # If we didn't find it in the list, but it looks like a GID, use it.
    if workspace_name_or_gid and workspace_name_or_gid.isdigit():
        return workspace_name_or_gid
        
    raise ValueError(f"Workspace '{workspace_name_or_gid}' not found")

def register_tools(mcp: FastMCP, credentials=None) -> None:
    """Register Asana tools with the MCP server."""

    @mcp.tool()
    def asana_create_task(
        name: str,
        workspace: Optional[str] = None,
        notes: Optional[str] = None,
        assignee: Optional[str] = None,
        projects: Optional[List[str]] = None,
        due_on: Optional[str] = None,
        start_on: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new task in Asana."""
        try:
            client = get_client(credentials)
            tasks_api = asana.TasksApi(client)
            workspace_gid = get_workspace_gid(client, workspace)
            
            task_data = {
                'workspace': workspace_gid,
                'name': name,
            }
            if notes: task_data['notes'] = notes
            if assignee: task_data['assignee'] = assignee
            if projects: task_data['projects'] = projects
            if due_on: task_data['due_on'] = due_on
            if start_on: task_data['start_on'] = start_on
            if tags: task_data['tags'] = tags

            body = {"data": task_data}
            result = tasks_api.create_task(body)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_update_task(
        task_gid: str,
        name: Optional[str] = None,
        notes: Optional[str] = None,
        assignee: Optional[str] = None,
        due_on: Optional[str] = None,
        completed: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Update an existing task."""
        try:
            client = get_client(credentials)
            tasks_api = asana.TasksApi(client)
            
            task_data = {}
            if name: task_data['name'] = name
            if notes: task_data['notes'] = notes
            if assignee: task_data['assignee'] = assignee
            if due_on: task_data['due_on'] = due_on
            if completed is not None: task_data['completed'] = completed
            
            if not task_data:
                return {"error": "No fields to update"}

            body = {"data": task_data}
            result = tasks_api.update_task(body, task_gid)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_get_task(task_gid: str) -> Dict[str, Any]:
        """Get details of a task."""
        try:
            client = get_client(credentials)
            tasks_api = asana.TasksApi(client)
            result = tasks_api.get_task(task_gid)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_search_tasks(
        workspace: Optional[str] = None,
        text: Optional[str] = None,
        assignee: Optional[str] = None,
        project: Optional[str] = None,
        completed: Optional[bool] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search for tasks in a workspace."""
        try:
            client = get_client(credentials)
            tasks_api = asana.TasksApi(client)
            workspace_gid = get_workspace_gid(client, workspace)
            
            # v5 search_tasks_for_workspace(workspace_gid, opts=...)
            opts = {
                'limit': limit,
                'opt_fields': 'name,gid,completed,assignee.name,projects.name'
            }
            if text: opts['text'] = text
            if assignee: opts['assignee.any'] = assignee
            if project: opts['projects.any'] = project
            if completed is not None: opts['completed'] = str(completed).lower()

            # For generic listing without text, we might use get_tasks if filters allow
            # But search is more flexible.
            result = tasks_api.search_tasks_for_workspace(workspace_gid, **opts)
            
            # search result is iterable
            return to_dict(list(result.data) if hasattr(result, 'data') else list(result))
        except ApiException as e:
            return [{"error": str(e)}]

    @mcp.tool()
    def asana_delete_task(task_gid: str) -> Dict[str, Any]:
        """Delete a task."""
        try:
            client = get_client(credentials)
            tasks_api = asana.TasksApi(client)
            result = tasks_api.delete_task(task_gid)
            return {"success": True, "result": to_dict(result)}
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_add_task_comment(task_gid: str, text: str) -> Dict[str, Any]:
        """Add a comment to a task."""
        try:
            client = get_client(credentials)
            stories_api = asana.StoriesApi(client)
            body = {"data": {"text": text}}
            result = stories_api.create_story_for_task(body, task_gid)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_complete_task(task_gid: str) -> Dict[str, Any]:
        """Mark a task as complete."""
        return asana_update_task(task_gid, completed=True)

    @mcp.tool()
    def asana_add_subtask(
        parent_task_gid: str,
        name: str,
        notes: Optional[str] = None,
        assignee: Optional[str] = None,
        due_on: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a subtask."""
        try:
            client = get_client(credentials)
            tasks_api = asana.TasksApi(client)
            
            task_data = {'name': name}
            if notes: task_data['notes'] = notes
            if assignee: task_data['assignee'] = assignee
            if due_on: task_data['due_on'] = due_on
            
            body = {"data": task_data}
            result = tasks_api.create_subtask_for_task(body, parent_task_gid)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_create_project(
        name: str,
        workspace: Optional[str] = None,
        team: Optional[str] = None,
        notes: Optional[str] = None,
        public: bool = True,
    ) -> Dict[str, Any]:
        """Create a new project."""
        try:
            client = get_client(credentials)
            projects_api = asana.ProjectsApi(client)
            workspace_gid = get_workspace_gid(client, workspace)
            
            project_data = {
                'name': name,
                'workspace': workspace_gid,
                'public': public
            }
            if team: project_data['team'] = team
            if notes: project_data['notes'] = notes
            
            body = {"data": project_data}
            result = projects_api.create_project(body)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_update_project(
        project_gid: str,
        name: Optional[str] = None,
        notes: Optional[str] = None,
        public: Optional[bool] = None,
        owner: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update a project."""
        try:
            client = get_client(credentials)
            projects_api = asana.ProjectsApi(client)
            
            project_data = {}
            if name: project_data['name'] = name
            if notes: project_data['notes'] = notes
            if public is not None: project_data['public'] = public
            if owner: project_data['owner'] = owner
            
            if not project_data:
                return {"error": "No fields to update"}
                
            body = {"data": project_data}
            result = projects_api.update_project(body, project_gid)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_get_project(project_gid: str) -> Dict[str, Any]:
        """Get project details."""
        try:
            client = get_client(credentials)
            projects_api = asana.ProjectsApi(client)
            result = projects_api.get_project(project_gid)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_list_projects(
        workspace: Optional[str] = None,
        team: Optional[str] = None,
        archived: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """List projects in a workspace or team."""
        try:
            client = get_client(credentials)
            projects_api = asana.ProjectsApi(client)
            workspace_gid = get_workspace_gid(client, workspace)
            
            opts = {'workspace': workspace_gid}
            if team: opts['team'] = team
            if archived is not None: opts['archived'] = archived
            
            result = projects_api.get_projects(**opts)
            return to_dict(list(result.data) if hasattr(result, 'data') else list(result))
        except ApiException as e:
            return [{"error": str(e)}]

    @mcp.tool()
    def asana_get_project_tasks(
        project_gid: str,
        completed_since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get tasks in a project."""
        try:
            client = get_client(credentials)
            tasks_api = asana.TasksApi(client)
            
            opts = {'project': project_gid}
            if completed_since: opts['completed_since'] = completed_since
            
            # In v5, get_tasks often requires workspace or project filter
            # There is get_tasks_for_project
            result = tasks_api.get_tasks_for_project(project_gid, **opts)
            return to_dict(list(result.data) if hasattr(result, 'data') else list(result))
        except ApiException as e:
            return [{"error": str(e)}]

    @mcp.tool()
    def asana_add_task_to_project(
        task_gid: str,
        project_gid: str,
        section_gid: Optional[str] = None,
        insert_after: Optional[str] = None,
        insert_before: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a task to a project."""
        try:
            client = get_client(credentials)
            tasks_api = asana.TasksApi(client)
            
            data = {'project': project_gid}
            if section_gid: data['section'] = section_gid
            if insert_after: data['insert_after'] = insert_after
            if insert_before: data['insert_before'] = insert_before
            
            body = {"data": data}
            result = tasks_api.add_project_for_task(body, task_gid)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_get_workspace(workspace_gid: Optional[str] = None) -> Dict[str, Any]:
        """Get workspace details."""
        try:
            client = get_client(credentials)
            workspaces_api = asana.WorkspacesApi(client)
            gid = get_workspace_gid(client, workspace_gid)
            result = workspaces_api.get_workspace(gid)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_list_workspaces() -> List[Dict[str, Any]]:
        """List all accessible workspaces."""
        try:
            client = get_client(credentials)
            workspaces_api = asana.WorkspacesApi(client)
            result = workspaces_api.get_workspaces()
            return to_dict(list(result.data) if hasattr(result, 'data') else list(result))
        except ApiException as e:
            return [{"error": str(e)}]

    @mcp.tool()
    def asana_get_user(user_gid: str) -> Dict[str, Any]:
        """Get user information."""
        try:
            client = get_client(credentials)
            users_api = asana.UsersApi(client)
            result = users_api.get_user(user_gid)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_list_team_members(
        workspace: Optional[str] = None,
        team_gid: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List users in a workspace or team."""
        try:
            client = get_client(credentials)
            users_api = asana.UsersApi(client)
            workspace_gid = get_workspace_gid(client, workspace)
            
            opts = {'workspace': workspace_gid}
            if team_gid: opts['team'] = team_gid
            
            result = users_api.get_users(**opts)
            return to_dict(list(result.data) if hasattr(result, 'data') else list(result))
        except ApiException as e:
            return [{"error": str(e)}]

    @mcp.tool()
    def asana_create_section(
        project_gid: str,
        name: str,
    ) -> Dict[str, Any]:
        """Create a section in a project."""
        try:
            client = get_client(credentials)
            sections_api = asana.SectionsApi(client)
            body = {"data": {"name": name}}
            result = sections_api.create_section_for_project(body, project_gid)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_list_sections(project_gid: str) -> List[Dict[str, Any]]:
        """List sections in a project."""
        try:
            client = get_client(credentials)
            sections_api = asana.SectionsApi(client)
            result = sections_api.get_sections_for_project(project_gid)
            return to_dict(list(result.data) if hasattr(result, 'data') else list(result))
        except ApiException as e:
            return [{"error": str(e)}]

    @mcp.tool()
    def asana_move_task_to_section(
        task_gid: str,
        section_gid: str,
    ) -> Dict[str, Any]:
        """Move a task to a specific section."""
        try:
            client = get_client(credentials)
            sections_api = asana.SectionsApi(client)
            body = {"data": {"task": task_gid}}
            result = sections_api.add_task_for_section(body, section_gid)
            return to_dict(result)
        except ApiException as e:
             return {"error": str(e)}

    @mcp.tool()
    def asana_create_tag(
        name: str,
        workspace: Optional[str] = None,
        color: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new tag."""
        try:
            client = get_client(credentials)
            tags_api = asana.TagsApi(client)
            workspace_gid = get_workspace_gid(client, workspace)
            
            data = {'workspace': workspace_gid, 'name': name}
            if color: data['color'] = color
            if notes: data['notes'] = notes
            
            body = {"data": data}
            result = tags_api.create_tag(body)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_add_tag_to_task(
        task_gid: str,
        tag_gid: str,
    ) -> Dict[str, Any]:
        """Add a tag to a task."""
        try:
            client = get_client(credentials)
            tasks_api = asana.TasksApi(client)
            body = {"data": {"tag": tag_gid}}
            result = tasks_api.add_tag_for_task(body, task_gid)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}

    @mcp.tool()
    def asana_list_tags(workspace: Optional[str] = None) -> List[Dict[str, Any]]:
        """List tags in a workspace."""
        try:
            client = get_client(credentials)
            tags_api = asana.TagsApi(client)
            workspace_gid = get_workspace_gid(client, workspace)
            result = tags_api.get_tags(workspace=workspace_gid)
            return to_dict(list(result.data) if hasattr(result, 'data') else list(result))
        except ApiException as e:
            return [{"error": str(e)}]
    
    @mcp.tool()
    def asana_update_custom_field(
        task_gid: str,
        custom_field_gid: str,
        value: Union[str, float, int],
    ) -> Dict[str, Any]:
        """Update a custom field value on a task."""
        try:
            client = get_client(credentials)
            tasks_api = asana.TasksApi(client)
            
            params = {
                'custom_fields': {
                    custom_field_gid: value
                }
            }
            body = {"data": params}
            result = tasks_api.update_task(body, task_gid)
            return to_dict(result)
        except ApiException as e:
            return {"error": str(e)}
