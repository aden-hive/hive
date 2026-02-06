"""
X (Twitter) Tool - Post tweets, reply, search, read mentions, and send DMs via X API v2.

Authentication:
- Bearer token (X_BEARER_TOKEN): read-only operations (search, mentions).
- OAuth 1.0a User Context: write operations (post, reply, delete, DM).
  Requires X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET.

API Reference: https://developer.x.com/en/docs/twitter-api
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import urllib.parse
import uuid
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


X_API_BASE = "https://api.x.com/2"


class _XClient:
    """Internal client wrapping X API v2 calls with Bearer token auth."""

    def __init__(self, bearer_token: str):
        self._bearer_token = bearer_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._bearer_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 401:
            return {"error": "Invalid or expired X access token"}
        if response.status_code == 403:
            return {
                "error": "Insufficient permissions — this operation may require OAuth 1.0a "
                "user context authentication (not just a Bearer token).",
                "help": "Set X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, and "
                "X_ACCESS_TOKEN_SECRET for write operations.",
            }
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            return {"error": f"X API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def get(self, endpoint: str, params: dict | None = None) -> dict[str, Any]:
        """Make a GET request with Bearer auth."""
        response = httpx.get(
            f"{X_API_BASE}{endpoint}",
            headers=self._headers,
            params=params,
            timeout=30.0,
        )
        return self._handle_response(response)


class _XOAuthClient:
    """Internal client wrapping X API v2 calls with OAuth 1.0a user context auth."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str,
        access_token_secret: str,
    ):
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_token = access_token
        self._access_token_secret = access_token_secret

    def _generate_oauth_signature(
        self,
        method: str,
        url: str,
        oauth_params: dict[str, str],
        body_params: dict[str, str] | None = None,
    ) -> str:
        """Generate OAuth 1.0a HMAC-SHA1 signature."""
        all_params = {**oauth_params}
        if body_params:
            all_params.update(body_params)

        # Sort and encode params
        sorted_params = sorted(all_params.items())
        param_string = "&".join(
            f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
            for k, v in sorted_params
        )

        # Create signature base string
        base_string = (
            f"{method.upper()}&"
            f"{urllib.parse.quote(url, safe='')}&"
            f"{urllib.parse.quote(param_string, safe='')}"
        )

        # Create signing key
        signing_key = (
            f"{urllib.parse.quote(self._api_secret, safe='')}&"
            f"{urllib.parse.quote(self._access_token_secret, safe='')}"
        )

        # HMAC-SHA1
        import base64

        signature = base64.b64encode(
            hmac.new(
                signing_key.encode("utf-8"),
                base_string.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("utf-8")

        return signature

    def _build_auth_header(self, method: str, url: str) -> str:
        """Build the OAuth 1.0a Authorization header."""
        oauth_params = {
            "oauth_consumer_key": self._api_key,
            "oauth_nonce": uuid.uuid4().hex,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": self._access_token,
            "oauth_version": "1.0",
        }

        signature = self._generate_oauth_signature(method, url, oauth_params)
        oauth_params["oauth_signature"] = signature

        header_parts = [
            f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
            for k, v in sorted(oauth_params.items())
        ]
        return "OAuth " + ", ".join(header_parts)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 401:
            return {
                "error": "OAuth 1.0a authentication failed — check your API keys and tokens",
                "help": "Verify X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, "
                "and X_ACCESS_TOKEN_SECRET are correct.",
            }
        if response.status_code == 403:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            return {
                "error": f"Insufficient permissions (HTTP 403): {detail}",
                "help": "Ensure your X app has Read+Write+Direct Message permissions "
                "and tokens were regenerated AFTER enabling them.",
            }
        if response.status_code == 404:
            return {"error": "Resource not found"}
        if response.status_code == 429:
            return {"error": "Rate limit exceeded. Try again later."}
        if response.status_code >= 400:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            return {"error": f"X API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def post(self, endpoint: str, json_body: dict | None = None) -> dict[str, Any]:
        """Make a POST request with OAuth 1.0a auth."""
        url = f"{X_API_BASE}{endpoint}"
        auth_header = self._build_auth_header("POST", url)
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        response = httpx.post(url, headers=headers, json=json_body, timeout=30.0)
        return self._handle_response(response)

    def delete(self, endpoint: str) -> dict[str, Any]:
        """Make a DELETE request with OAuth 1.0a auth."""
        url = f"{X_API_BASE}{endpoint}"
        auth_header = self._build_auth_header("DELETE", url)
        headers = {
            "Authorization": auth_header,
            "Accept": "application/json",
        }
        response = httpx.delete(url, headers=headers, timeout=30.0)
        return self._handle_response(response)


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register X (Twitter) tools with the MCP server."""

    def _get_credential(env_var: str, cred_name: str) -> str | None:
        """Get a credential from the credential manager or environment."""
        if credentials is not None:
            val = credentials.get(cred_name)
            if val is not None and not isinstance(val, str):
                raise TypeError(
                    f"Expected string for credential '{cred_name}', got {type(val).__name__}"
                )
            return val
        return os.getenv(env_var)

    def _get_bearer_client() -> _XClient | dict[str, str]:
        """Get a Bearer-token client for read-only operations."""
        token = _get_credential("X_BEARER_TOKEN", "x_bearer_token")
        if not token:
            return {
                "error": "X Bearer token not configured",
                "help": "Set X_BEARER_TOKEN environment variable. "
                "Get it from https://developer.x.com/ > Keys & Tokens.",
            }
        return _XClient(token)

    def _get_oauth_client() -> _XOAuthClient | dict[str, str]:
        """Get an OAuth 1.0a client for write operations."""
        api_key = _get_credential("X_API_KEY", "x_api_key")
        api_secret = _get_credential("X_API_SECRET", "x_api_secret")
        access_token = _get_credential("X_ACCESS_TOKEN", "x_access_token")
        access_secret = _get_credential("X_ACCESS_TOKEN_SECRET", "x_access_token_secret")

        if not all([api_key, api_secret, access_token, access_secret]):
            missing = []
            if not api_key:
                missing.append("X_API_KEY")
            if not api_secret:
                missing.append("X_API_SECRET")
            if not access_token:
                missing.append("X_ACCESS_TOKEN")
            if not access_secret:
                missing.append("X_ACCESS_TOKEN_SECRET")
            return {
                "error": f"X OAuth credentials not configured: {', '.join(missing)}",
                "help": "Write operations (post, reply, delete, DM) require OAuth 1.0a. "
                "Set all 4 env vars from https://developer.x.com/ > Keys & Tokens.",
            }
        return _XOAuthClient(api_key, api_secret, access_token, access_secret)

    # ── Read-only tools (Bearer token) ──────────────────────────────

    @mcp.tool()
    def x_search_tweets(query: str, max_results: int = 10) -> dict:
        """Search recent tweets by keyword or query.

        Uses Bearer token authentication (read-only).

        Args:
            query: Search query string (supports X search operators).
            max_results: Number of results to return (1-100, default 10).

        Returns:
            Dict with matching tweets or error details.
        """
        client = _get_bearer_client()
        if isinstance(client, dict):
            return client
        params = {"query": query, "max_results": min(max(max_results, 1), 100)}
        try:
            return client.get("/tweets/search/recent", params=params)
        except httpx.TimeoutException:
            return {"error": "X API request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def x_get_mentions(user_id: str, max_results: int = 10) -> dict:
        """Fetch recent mentions for a user.

        Uses Bearer token authentication (read-only).

        Args:
            user_id: The X user ID to fetch mentions for.
            max_results: Number of results to return (1-100, default 10).

        Returns:
            Dict with mention tweets or error details.
        """
        client = _get_bearer_client()
        if isinstance(client, dict):
            return client
        params = {"max_results": min(max(max_results, 1), 100)}
        try:
            return client.get(f"/users/{user_id}/mentions", params=params)
        except httpx.TimeoutException:
            return {"error": "X API request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # ── Write tools (OAuth 1.0a required) ───────────────────────────

    @mcp.tool()
    def x_post_tweet(text: str) -> dict:
        """Post a new tweet.

        Requires OAuth 1.0a authentication (X_API_KEY, X_API_SECRET,
        X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET).

        Args:
            text: Tweet text content (max 280 characters).

        Returns:
            Dict with created tweet data or error details.
        """
        if not text or not text.strip():
            return {"error": "Tweet text cannot be empty"}
        if len(text) > 280:
            return {"error": f"Tweet text exceeds 280 characters ({len(text)} chars)"}

        client = _get_oauth_client()
        if isinstance(client, dict):
            return client
        try:
            return client.post("/tweets", json_body={"text": text})
        except httpx.TimeoutException:
            return {"error": "X API request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def x_reply_tweet(tweet_id: str, text: str) -> dict:
        """Reply to an existing tweet.

        Requires OAuth 1.0a authentication (X_API_KEY, X_API_SECRET,
        X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET).

        Args:
            tweet_id: The ID of the tweet to reply to.
            text: Reply text content (max 280 characters).

        Returns:
            Dict with created reply data or error details.
        """
        if not text or not text.strip():
            return {"error": "Reply text cannot be empty"}
        if len(text) > 280:
            return {"error": f"Reply text exceeds 280 characters ({len(text)} chars)"}

        client = _get_oauth_client()
        if isinstance(client, dict):
            return client
        body = {"text": text, "reply": {"in_reply_to_tweet_id": tweet_id}}
        try:
            return client.post("/tweets", json_body=body)
        except httpx.TimeoutException:
            return {"error": "X API request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def x_delete_tweet(tweet_id: str) -> dict:
        """Delete a tweet.

        Requires OAuth 1.0a authentication (X_API_KEY, X_API_SECRET,
        X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET).

        Args:
            tweet_id: The ID of the tweet to delete.

        Returns:
            Dict with deletion confirmation or error details.
        """
        client = _get_oauth_client()
        if isinstance(client, dict):
            return client
        try:
            return client.delete(f"/tweets/{tweet_id}")
        except httpx.TimeoutException:
            return {"error": "X API request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def x_send_dm(participant_id: str, text: str) -> dict:
        """Send a direct message to a user on X.

        Requires OAuth 1.0a authentication (X_API_KEY, X_API_SECRET,
        X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET). Your X app must have
        Direct Message permissions enabled.

        Args:
            participant_id: The X user ID of the DM recipient.
            text: Message text content.

        Returns:
            Dict with DM event data or error details.
        """
        if not text or not text.strip():
            return {"error": "DM text cannot be empty"}

        client = _get_oauth_client()
        if isinstance(client, dict):
            return client

        body = {"text": text}
        try:
            return client.post(f"/dm_conversations/with/{participant_id}/messages", json_body=body)
        except httpx.TimeoutException:
            return {"error": "X API request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
