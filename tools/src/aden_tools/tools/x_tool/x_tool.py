"""
X (Twitter) Tool - Post tweets, reply, search, and read mentions via X API v2.

Supports:
- Bearer tokens (X_BEARER_TOKEN)
- OAuth2 tokens via credential store

API Reference: https://developer.x.com/en/docs/twitter-api
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


X_API_BASE = "https://api.twitter.com/2"

# Internal Client
class _XClient:
    """Internal client wrapping X API v2 calls."""

    def __init__(self, token: str):
        self._token = token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 401:
            return {"error": "Invalid or expired X access token"}
        if response.status_code == 403:
            return {"error": "Insufficient permissions. Check your X app scopes."}
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later"}
        if response.status_code >= 400:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            return {"error": f"X API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def request(self, method: str, endpoint: str, **kwargs) -> dict[str, Any]:
        response = httpx.request(
            method,
            f"{X_API_BASE}{endpoint}",
            headers=self._headers,
            timeout=30.0,
            **kwargs,
        )
        return self._handle_response(response)

# Tool Registration
def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register X tools with MCP server."""

    def _get_token() -> str | None:
        if credentials is not None:
            token = credentials.get("x")
            if token is not None and not isinstance(token, str):
                raise TypeError("Expected string from credentials.get('x')")
            return token
        return os.getenv("X_BEARER_TOKEN")

    def _get_client() -> _XClient | dict[str, str]:
        token = _get_token()
        if not token:
            return {
                "error": "X credentials not configured",
                "help": "Set X_BEARER_TOKEN or configure via credential store",
            }
        return _XClient(token)


    # Tools

    @mcp.tool()
    def x_post_tweet(text: str) -> dict:
        """Post a tweet."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.request("POST", "/tweets", json={"text": text})
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def x_reply_tweet(tweet_id: str, text: str) -> dict:
        """Reply to an existing tweet."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        body = {"text": text, "reply": {"in_reply_to_tweet_id": tweet_id}}
        try:
            return client.request("POST", "/tweets", json=body)
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def x_delete_tweet(tweet_id: str) -> dict:
        """Delete a tweet."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.request("DELETE", f"/tweets/{tweet_id}")
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def x_search_tweets(query: str, max_results: int = 10) -> dict:
        """Search recent tweets."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        params = {"query": query, "max_results": min(max_results, 100)}
        try:
            return client.request("GET", "/tweets/search/recent", params=params)
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def x_get_mentions(user_id: str, max_results: int = 10) -> dict:
        """Fetch mentions for a user."""
        client = _get_client()
        if isinstance(client, dict):
            return client
        params = {"max_results": min(max_results, 100)}
        try:
            return client.request("GET", f"/users/{user_id}/mentions", params=params)
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
