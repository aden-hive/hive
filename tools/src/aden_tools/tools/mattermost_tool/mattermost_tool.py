"""
Mattermost Tool - Send messages and interact with Mattermost servers via Mattermost API.

Supports:
- Personal access tokens (MATTERMOST_ACCESS_TOKEN)
- Self-hosted and cloud Mattermost instances (MATTERMOST_URL)

API Reference: https://api.mattermost.com/
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

MAX_MESSAGE_LENGTH = 16383  # Mattermost API limit
MAX_RETRIES = 2  # 3 total attempts on 429
MAX_RETRY_WAIT = 60  # cap wait at 60s


class _MattermostClient:
    """Internal client wrapping Mattermost API calls."""

    def __init__(self, access_token: str, base_url: str):
        # Strip trailing slash and ensure /api/v4 suffix
        base_url = base_url.rstrip("/")
        if not base_url.endswith("/api/v4"):
            base_url = f"{base_url}/api/v4"
        self._base_url = base_url
        self._token = access_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make HTTP request with retry on 429 rate limit."""
        request_kwargs = {"headers": self._headers, "timeout": 30.0, **kwargs}
        for attempt in range(MAX_RETRIES + 1):
            response = httpx.request(method, url, **request_kwargs)
            if response.status_code == 429 and attempt < MAX_RETRIES:
                try:
                    wait = min(float(response.headers.get("Retry-After", 1)), MAX_RETRY_WAIT)
                except (ValueError, TypeError):
                    wait = min(2**attempt, MAX_RETRY_WAIT)
                time.sleep(wait)
                continue
            return self._handle_response(response)
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle Mattermost API response format."""
        if response.status_code == 204:
            return {"success": True}

        if response.status_code == 429:
            try:
                retry_after = float(response.headers.get("Retry-After", 60))
            except (ValueError, TypeError):
                retry_after = 60
            return {
                "error": f"Mattermost rate limit exceeded. Retry after {retry_after}s",
                "retry_after": retry_after,
            }

        if response.status_code not in (200, 201):
            try:
                data = response.json()
                message = data.get("message", response.text)
            except Exception:
                message = response.text
            return {"error": f"HTTP {response.status_code}: {message}"}

        return response.json()

    def get_me(self) -> dict[str, Any]:
        """Get the authenticated user's info (health check)."""
        return self._request_with_retry("GET", f"{self._base_url}/users/me")

    def list_teams(self) -> dict[str, Any]:
        """List teams the authenticated user belongs to."""
        return self._request_with_retry("GET", f"{self._base_url}/users/me/teams")

    def list_channels(self, team_id: str, per_page: int = 100) -> dict[str, Any]:
        """List public channels for a team."""
        return self._request_with_retry(
            "GET",
            f"{self._base_url}/teams/{team_id}/channels",
            params={"per_page": min(per_page, 200)},
        )

    def get_channel(self, channel_id: str) -> dict[str, Any]:
        """Get detailed information about a channel."""
        return self._request_with_retry("GET", f"{self._base_url}/channels/{channel_id}")

    def send_message(
        self,
        channel_id: str,
        message: str,
        *,
        root_id: str = "",
    ) -> dict[str, Any]:
        """Create a post in a channel."""
        body: dict[str, Any] = {
            "channel_id": channel_id,
            "message": message,
        }
        if root_id:
            body["root_id"] = root_id
        return self._request_with_retry(
            "POST",
            f"{self._base_url}/posts",
            json=body,
        )

    def get_posts(
        self,
        channel_id: str,
        per_page: int = 60,
        page: int = 0,
        before: str = "",
        after: str = "",
    ) -> dict[str, Any]:
        """Get posts from a channel."""
        params: dict[str, Any] = {
            "per_page": min(per_page, 200),
            "page": page,
        }
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        return self._request_with_retry(
            "GET",
            f"{self._base_url}/channels/{channel_id}/posts",
            params=params,
        )

    def create_reaction(
        self,
        post_id: str,
        emoji_name: str,
    ) -> dict[str, Any]:
        """Add a reaction to a post.

        API ref: POST /reactions
        """
        # Need user_id for the reaction; fetch from /users/me
        me = self.get_me()
        if isinstance(me, dict) and "error" in me:
            return me
        user_id = me.get("id", "")
        return self._request_with_retry(
            "POST",
            f"{self._base_url}/reactions",
            json={
                "user_id": user_id,
                "post_id": post_id,
                "emoji_name": emoji_name,
            },
        )

    def delete_post(self, post_id: str) -> dict[str, Any]:
        """Delete a post."""
        return self._request_with_retry("DELETE", f"{self._base_url}/posts/{post_id}")


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Mattermost tools with the MCP server."""

    def _get_token(account: str = "") -> str | None:
        """Get Mattermost access token from credential manager or environment."""
        if credentials is not None:
            if account:
                return credentials.get_by_alias("mattermost", account)
            token = credentials.get("mattermost")
            if token is not None and not isinstance(token, str):
                raise TypeError(
                    "Expected string from credentials.get('mattermost'), "
                    f"got {type(token).__name__}"
                )
            return token
        return os.getenv("MATTERMOST_ACCESS_TOKEN")

    def _get_url() -> str | None:
        """Get Mattermost server URL from credential manager or environment."""
        if credentials is not None:
            url = credentials.get("mattermost_url")
            if url is not None and not isinstance(url, str):
                raise TypeError(
                    "Expected string from credentials.get('mattermost_url'), "
                    f"got {type(url).__name__}"
                )
            if url:
                return url
        return os.getenv("MATTERMOST_URL")

    def _get_client(account: str = "") -> _MattermostClient | dict[str, str]:
        """Get a Mattermost client, or return an error dict if no credentials."""
        token = _get_token(account)
        if not token:
            return {
                "error": "Mattermost credentials not configured",
                "help": (
                    "Set MATTERMOST_ACCESS_TOKEN and MATTERMOST_URL environment variables "
                    "or configure via credential store"
                ),
            }
        url = _get_url()
        if not url:
            return {
                "error": "Mattermost server URL not configured",
                "help": (
                    "Set MATTERMOST_URL environment variable (e.g. https://mattermost.example.com) "
                    "or configure via credential store"
                ),
            }
        return _MattermostClient(token, url)

    @mcp.tool()
    def mattermost_list_teams(account: str = "") -> dict:
        """
        List Mattermost teams the authenticated user belongs to.

        Returns team IDs and names. Use team IDs with mattermost_list_channels.

        Returns:
            Dict with list of teams or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_teams()
            if isinstance(result, dict) and "error" in result:
                return result
            return {"teams": result, "success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mattermost_list_channels(team_id: str, per_page: int = 100, account: str = "") -> dict:
        """
        List public channels for a Mattermost team.

        Args:
            team_id: Team ID. Use mattermost_list_teams to find team IDs.
            per_page: Max channels to return (1-200, default 100).

        Returns:
            Dict with list of channels or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.list_channels(team_id, per_page=per_page)
            if isinstance(result, dict) and "error" in result:
                return result
            return {"channels": result, "success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mattermost_get_channel(channel_id: str, account: str = "") -> dict:
        """
        Get detailed information about a Mattermost channel.

        Returns channel metadata including name, display name, header, purpose,
        and type.

        Args:
            channel_id: Channel ID

        Returns:
            Dict with channel details or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.get_channel(channel_id)
            if isinstance(result, dict) and "error" in result:
                return result
            return {"channel": result, "success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mattermost_send_message(
        channel_id: str,
        message: str,
        root_id: str = "",
        account: str = "",
    ) -> dict:
        """
        Send a message (post) to a Mattermost channel.

        Args:
            channel_id: Channel ID to post in
            message: Message text (max 16383 characters). Supports Markdown.
            root_id: Optional post ID to reply to (creates a thread)

        Returns:
            Dict with post details or error
        """
        if len(message) > MAX_MESSAGE_LENGTH:
            return {
                "error": f"Message exceeds {MAX_MESSAGE_LENGTH} character limit",
                "max_length": MAX_MESSAGE_LENGTH,
                "provided": len(message),
            }
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.send_message(channel_id, message, root_id=root_id)
            if isinstance(result, dict) and "error" in result:
                return result
            return {"success": True, "post": result}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mattermost_get_posts(
        channel_id: str,
        per_page: int = 60,
        page: int = 0,
        before: str = "",
        after: str = "",
        account: str = "",
    ) -> dict:
        """
        Get posts from a Mattermost channel.

        Args:
            channel_id: Channel ID
            per_page: Max posts to return (1-200, default 60)
            page: Page number for pagination (default 0)
            before: Post ID to get posts before (for pagination)
            after: Post ID to get posts after (for pagination)

        Returns:
            Dict with posts or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.get_posts(
                channel_id,
                per_page=per_page,
                page=page,
                before=before,
                after=after,
            )
            if isinstance(result, dict) and "error" in result:
                return result
            return {"posts": result, "success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mattermost_create_reaction(
        post_id: str,
        emoji_name: str,
        account: str = "",
    ) -> dict:
        """
        Add a reaction to a Mattermost post.

        Args:
            post_id: ID of the post to react to
            emoji_name: Emoji name without colons (e.g. "thumbsup", "heart")

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.create_reaction(post_id, emoji_name)
            if isinstance(result, dict) and "error" in result:
                return result
            return {"success": True}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def mattermost_delete_post(
        post_id: str,
        account: str = "",
    ) -> dict:
        """
        Delete a post from Mattermost.

        Requires appropriate permissions (post author or admin).

        Args:
            post_id: ID of the post to delete

        Returns:
            Dict with success status or error
        """
        client = _get_client(account)
        if isinstance(client, dict):
            return client
        try:
            result = client.delete_post(post_id)
            if isinstance(result, dict) and "error" in result:
                return result
            return {"success": True, "deleted_post_id": post_id}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
