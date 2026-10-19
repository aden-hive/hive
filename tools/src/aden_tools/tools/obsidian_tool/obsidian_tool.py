"""
Obsidian Knowledge Management Tool - Notes, search, and vault browsing.

Supports:
- Obsidian Local REST API plugin (Bearer token auth)
- Local or remote instances (OBSIDIAN_REST_BASE_URL)

API Reference: https://coddingtonbear.github.io/obsidian-local-rest-api/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

DEFAULT_BASE_URL = "https://127.0.0.1:27124"


def _get_creds(
    credentials: CredentialStoreAdapter | None,
) -> tuple[str, str] | dict[str, str]:
    """Return (api_key, base_url) or an error dict."""
    if credentials is not None:
        api_key = credentials.get("obsidian")
        base_url = credentials.get("obsidian_base_url") or DEFAULT_BASE_URL
    else:
        api_key = os.getenv("OBSIDIAN_REST_API_KEY")
        base_url = os.getenv("OBSIDIAN_REST_BASE_URL", DEFAULT_BASE_URL)

    if not api_key:
        return {
            "error": "Obsidian credentials not configured",
            "help": (
                "Set OBSIDIAN_REST_API_KEY environment variable "
                "or configure via credential store. "
                "Install the 'Local REST API' plugin in Obsidian first."
            ),
        }
    base_url = base_url.rstrip("/")
    return api_key, base_url


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _handle_response(resp: httpx.Response) -> dict[str, Any] | list | str:
    if resp.status_code == 204:
        return {"success": True}
    if resp.status_code == 401:
        return {"error": "Invalid Obsidian REST API key"}
    if resp.status_code == 404:
        return {"error": "File or resource not found in Obsidian vault"}
    if resp.status_code == 405:
        return {"error": "No active file open in Obsidian"}
    if resp.status_code >= 400:
        try:
            body = resp.json()
            detail = body.get("message", resp.text)
        except Exception:
            detail = resp.text
        return {"error": f"Obsidian API error (HTTP {resp.status_code}): {detail}"}
    content_type = resp.headers.get("content-type", "")
    if "json" in content_type:
        return resp.json()
    return resp.text


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Obsidian knowledge management tools with the MCP server."""

    @mcp.tool()
    def obsidian_read_note(path: str) -> dict:
        """
        Read a note from the Obsidian vault with metadata.

        Args:
            path: Path to the note relative to vault root (e.g. "Notes/meeting.md").

        Returns:
            Dict with content, path, tags, frontmatter, and file stats.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, base_url = creds

        if not path:
            return {"error": "path is required"}

        try:
            resp = httpx.get(
                f"{base_url}/vault/{path}",
                headers={
                    **_headers(api_key),
                    "Accept": "application/vnd.olrapi.note+json",
                },
                verify=False,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if isinstance(result, dict) and "error" in result:
                return result
            if isinstance(result, dict):
                return {
                    "path": result.get("path", path),
                    "content": result.get("content", ""),
                    "tags": result.get("tags", []),
                    "frontmatter": result.get("frontmatter"),
                    "stat": result.get("stat"),
                }
            return {"path": path, "content": str(result)}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def obsidian_write_note(path: str, content: str) -> dict:
        """
        Create or overwrite a note in the Obsidian vault.

        Args:
            path: Path for the note relative to vault root (e.g. "Daily/2025-03-03.md").
                  Parent directories are created automatically.
            content: Full markdown content for the note.

        Returns:
            Dict with success status.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, base_url = creds

        if not path:
            return {"error": "path is required"}

        try:
            resp = httpx.put(
                f"{base_url}/vault/{path}",
                headers={**_headers(api_key), "Content-Type": "text/markdown"},
                content=content,
                verify=False,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if isinstance(result, dict) and "error" in result:
                return result
            return {"success": True, "path": path}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def obsidian_append_note(path: str, content: str) -> dict:
        """
        Append content to an existing note, or create it if it doesn't exist.

        Args:
            path: Path to the note relative to vault root.
            content: Markdown content to append.

        Returns:
            Dict with success status.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, base_url = creds

        if not path:
            return {"error": "path is required"}

        try:
            resp = httpx.post(
                f"{base_url}/vault/{path}",
                headers={**_headers(api_key), "Content-Type": "text/markdown"},
                content=content,
                verify=False,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if isinstance(result, dict) and "error" in result:
                return result
            return {"success": True, "path": path}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def obsidian_search(
        query: str,
        context_length: int = 100,
    ) -> dict:
        """
        Search for text across all notes in the Obsidian vault.

        Args:
            query: Search text to find in notes.
            context_length: Characters of context around each match (default 100).

        Returns:
            Dict with list of matching files, scores, and match contexts.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, base_url = creds

        if not query:
            return {"error": "query is required"}

        try:
            resp = httpx.post(
                f"{base_url}/search/simple/",
                headers={
                    **_headers(api_key),
                    "Accept": "application/json",
                },
                params={"query": query, "contextLength": context_length},
                verify=False,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if isinstance(result, dict) and "error" in result:
                return result

            if isinstance(result, list):
                matches = []
                for item in result:
                    contexts = []
                    for m in item.get("matches", []):
                        contexts.append(m.get("context", ""))
                    matches.append(
                        {
                            "filename": item.get("filename"),
                            "score": item.get("score"),
                            "match_count": len(item.get("matches", [])),
                            "contexts": contexts[:5],
                        }
                    )
                return {"count": len(matches), "results": matches}
            return {"count": 0, "results": []}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def obsidian_list_files(path: str = "") -> dict:
        """
        List files and directories in the Obsidian vault.

        Args:
            path: Directory path relative to vault root (empty for root).
                  E.g. "Projects" to list files in the Projects folder.

        Returns:
            Dict with list of file/directory names.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, base_url = creds

        try:
            # Trailing slash signals a directory listing
            url_path = f"{base_url}/vault/"
            if path:
                url_path = f"{base_url}/vault/{path.rstrip('/')}/"

            resp = httpx.get(
                url_path,
                headers=_headers(api_key),
                verify=False,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if isinstance(result, dict) and "error" in result:
                return result

            # Response may be a flat list or a dict with "files" key
            if isinstance(result, list):
                files = result
            elif isinstance(result, dict) and "files" in result:
                files = result["files"]
            else:
                files = []

            return {"path": path or "/", "count": len(files), "files": files}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def obsidian_get_active() -> dict:
        """
        Get the currently active (open) file in Obsidian.

        Returns:
            Dict with the active file's content, path, tags, and frontmatter.
        """
        creds = _get_creds(credentials)
        if isinstance(creds, dict):
            return creds
        api_key, base_url = creds

        try:
            resp = httpx.get(
                f"{base_url}/active/",
                headers={
                    **_headers(api_key),
                    "Accept": "application/vnd.olrapi.note+json",
                },
                verify=False,
                timeout=30.0,
            )
            result = _handle_response(resp)
            if isinstance(result, dict) and "error" in result:
                return result
            if isinstance(result, dict):
                return {
                    "path": result.get("path", ""),
                    "content": result.get("content", ""),
                    "tags": result.get("tags", []),
                    "frontmatter": result.get("frontmatter"),
                }
            return {"content": str(result)}
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
