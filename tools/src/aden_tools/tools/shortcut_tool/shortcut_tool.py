from typing import Any

from fastmcp import FastMCP
import httpx

from aden_tools.credentials import CredentialStoreAdapter
from aden_tools.utils import logger


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Shortcut (formerly Clubhouse) tools."""

    @mcp.tool()
    async def create_shortcut_story(
        name: str,
        description: str = "",
        project_id: int | None = None,
        workflow_state_id: int | None = None,
        story_type: str = "feature",
    ) -> dict[str, Any]:
        """
        Create a new story in Shortcut.

        Args:
            name: The name/title of the story
            description: The description of the story (supports Markdown)
            project_id: Optional ID of the project to assign the story to
            workflow_state_id: Optional ID of the workflow state (e.g., To Do)
            story_type: Type of story ('feature', 'bug', 'chore')

        Returns:
            Dict containing the created story details
        """
        api_token = _get_api_token(credentials)
        if not api_token:
            return {"error": "SHORTCUT_API_TOKEN not found"}

        url = "https://api.app.shortcut.com/api/v3/stories"
        headers = {"Shortcut-Token": api_token, "Content-Type": "application/json"}
        
        payload = {
            "name": name,
            "description": description,
            "story_type": story_type,
        }
        if project_id:
            payload["project_id"] = project_id
        if workflow_state_id:
            payload["workflow_state_id"] = workflow_state_id

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Shortcut API error: {e.response.text}")
                return {"error": f"Shortcut API error: {e.response.text}"}
            except Exception as e:
                logger.error(f"Failed to create story: {e}")
                return {"error": str(e)}

    @mcp.tool()
    async def search_shortcut_stories(
        query: str,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """
        Search for stories in Shortcut.

        Args:
            query: Search query (e.g., 'state:started owner:me')
            page_size: Number of results to return (max 25)

        Returns:
            Dict containing search results
        """
        api_token = _get_api_token(credentials)
        if not api_token:
            return {"error": "SHORTCUT_API_TOKEN not found"}

        url = "https://api.app.shortcut.com/api/v3/search/stories"
        headers = {"Shortcut-Token": api_token, "Content-Type": "application/json"}
        
        params = {
            "query": query,
            "page_size": min(page_size, 25),
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                return {"error": f"Shortcut API error: {e.response.text}"}
            except Exception as e:
                return {"error": str(e)}

def _get_api_token(credentials: CredentialStoreAdapter | None) -> str | None:
    import os
    if credentials:
        return credentials.get("shortcut_api")
    return os.getenv("SHORTCUT_API_TOKEN")
