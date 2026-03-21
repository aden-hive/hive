"""
Docker Hub Tool - Search repositories, list tags, and inspect images.

Supports:
- Docker Hub API v2 with personal access token (DOCKER_HUB_TOKEN)
- Also requires DOCKER_HUB_USERNAME for authenticated endpoints
- Public repos can be queried without auth for some endpoints

API Reference: https://docs.docker.com/reference/api/hub/latest/
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

HUB_API = "https://hub.docker.com/v2"


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("docker_hub")
    return os.getenv("DOCKER_HUB_TOKEN")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get(endpoint: str, token: str, params: dict | None = None) -> dict[str, Any]:
    try:
        resp = httpx.get(
            f"{HUB_API}/{endpoint}", headers=_headers(token), params=params, timeout=30.0
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your DOCKER_HUB_TOKEN."}
        if resp.status_code == 404:
            return {"error": "Not found"}
        if resp.status_code != 200:
            return {"error": f"Docker Hub API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Docker Hub timed out"}
    except Exception as e:
        return {"error": f"Docker Hub request failed: {e!s}"}


def _delete(endpoint: str, token: str) -> dict[str, Any]:
    try:
        resp = httpx.delete(f"{HUB_API}/{endpoint}", headers=_headers(token), timeout=30.0)
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your DOCKER_HUB_TOKEN."}
        if resp.status_code == 404:
            return {"error": "Not found"}
        if resp.status_code == 204 or not resp.content:
            return {"status": "deleted"}
        if resp.status_code >= 400:
            return {"error": f"Docker Hub API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Docker Hub timed out"}
    except Exception as e:
        return {"error": f"Docker Hub request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "DOCKER_HUB_TOKEN not set",
        "help": "Create a PAT at https://hub.docker.com/settings/security",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Docker Hub tools with the MCP server."""

    @mcp.tool()
    def docker_hub_search(
        query: str,
        max_results: int = 25,
    ) -> dict[str, Any]:
        """
        Search Docker Hub for repositories.

        Args:
            query: Search query string
            max_results: Number of results (1-100, default 25)

        Returns:
            Dict with query and results list (repo_name, short_description, star_count,
            is_official, is_automated, pull_count)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not query:
            return {"error": "query is required"}

        max_results = max(1, min(max_results, 100))
        data = _get("search/repositories", token, {"query": query, "page_size": max_results})
        if "error" in data:
            return data

        results = []
        for r in data.get("results", []):
            results.append(
                {
                    "repo_name": r.get("repo_name", ""),
                    "short_description": r.get("short_description", ""),
                    "star_count": r.get("star_count", 0),
                    "is_official": r.get("is_official", False),
                    "is_automated": r.get("is_automated", False),
                    "pull_count": r.get("pull_count", 0),
                }
            )
        return {"query": query, "results": results}

    @mcp.tool()
    def docker_hub_list_repos(
        namespace: str = "",
        max_results: int = 25,
    ) -> dict[str, Any]:
        """
        List repositories for a Docker Hub user or organization.

        Args:
            namespace: Docker Hub username or organization (defaults to authenticated user)
            max_results: Number of results (1-100, default 25)

        Returns:
            Dict with namespace and repos list (name, namespace, description,
            star_count, pull_count, last_updated, is_private)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        if not namespace:
            namespace = os.getenv("DOCKER_HUB_USERNAME", "")
        if not namespace:
            return {"error": "namespace is required (or set DOCKER_HUB_USERNAME)"}

        max_results = max(1, min(max_results, 100))
        data = _get(f"repositories/{namespace}", token, {"page_size": max_results})
        if "error" in data:
            return data

        repos = []
        for r in data.get("results", []):
            repos.append(
                {
                    "name": r.get("name", ""),
                    "namespace": r.get("namespace", ""),
                    "description": r.get("description", ""),
                    "star_count": r.get("star_count", 0),
                    "pull_count": r.get("pull_count", 0),
                    "last_updated": r.get("last_updated", ""),
                    "is_private": r.get("is_private", False),
                }
            )
        return {"namespace": namespace, "repos": repos}

    @mcp.tool()
    def docker_hub_list_tags(
        repository: str,
        max_results: int = 25,
    ) -> dict[str, Any]:
        """
        List tags for a Docker Hub repository.

        Args:
            repository: Full repository name (e.g. "library/nginx" or "myuser/myapp")
            max_results: Number of tags (1-100, default 25)

        Returns:
            Dict with repository and tags list (name, full_size, last_updated, digest)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not repository:
            return {"error": "repository is required"}

        max_results = max(1, min(max_results, 100))
        data = _get(
            f"repositories/{repository}/tags",
            token,
            {"page_size": max_results, "ordering": "-last_updated"},
        )
        if "error" in data:
            return data

        tags = []
        for t in data.get("results", []):
            images = t.get("images", [])
            digest = images[0].get("digest", "") if images else ""
            tags.append(
                {
                    "name": t.get("name", ""),
                    "full_size": t.get("full_size", 0),
                    "last_updated": t.get("last_updated", ""),
                    "digest": digest,
                }
            )
        return {"repository": repository, "tags": tags}

    @mcp.tool()
    def docker_hub_get_repo(repository: str) -> dict[str, Any]:
        """
        Get detailed information about a Docker Hub repository.

        Args:
            repository: Full repository name (e.g. "library/nginx" or "myuser/myapp")

        Returns:
            Dict with name, namespace, description, star_count, pull_count,
            last_updated, is_private, full_description (README)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not repository:
            return {"error": "repository is required"}

        data = _get(f"repositories/{repository}", token)
        if "error" in data:
            return data

        full_desc = data.get("full_description", "")
        if len(full_desc) > 2000:
            full_desc = full_desc[:2000] + "..."

        return {
            "name": data.get("name", ""),
            "namespace": data.get("namespace", ""),
            "description": data.get("description", ""),
            "star_count": data.get("star_count", 0),
            "pull_count": data.get("pull_count", 0),
            "last_updated": data.get("last_updated", ""),
            "is_private": data.get("is_private", False),
            "full_description": full_desc,
        }

    @mcp.tool()
    def docker_hub_get_tag_detail(
        repository: str,
        tag: str,
    ) -> dict[str, Any]:
        """
        Get detailed information about a specific image tag.

        Args:
            repository: Full repository name (e.g. "library/nginx" or "myuser/myapp")
            tag: Tag name (e.g. "latest", "v1.0")

        Returns:
            Dict with tag details including images with architecture, OS, size, digest
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not repository or not tag:
            return {"error": "repository and tag are required"}

        data = _get(f"repositories/{repository}/tags/{tag}", token)
        if "error" in data:
            return data

        images = []
        for img in data.get("images", []):
            images.append(
                {
                    "architecture": img.get("architecture", ""),
                    "os": img.get("os", ""),
                    "size": img.get("size", 0),
                    "digest": img.get("digest", ""),
                    "status": img.get("status", ""),
                    "last_pushed": img.get("last_pushed", ""),
                }
            )
        return {
            "repository": repository,
            "tag": data.get("name", tag),
            "full_size": data.get("full_size", 0),
            "last_updated": data.get("last_updated", ""),
            "last_updater_username": data.get("last_updater_username", ""),
            "images": images,
            "image_count": len(images),
        }

    @mcp.tool()
    def docker_hub_delete_tag(
        repository: str,
        tag: str,
    ) -> dict[str, Any]:
        """
        Delete a specific tag from a Docker Hub repository.

        Args:
            repository: Full repository name (e.g. "myuser/myapp")
            tag: Tag name to delete (e.g. "old-version")

        Returns:
            Dict with deletion status
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not repository or not tag:
            return {"error": "repository and tag are required"}

        data = _delete(f"repositories/{repository}/tags/{tag}", token)
        if "error" in data:
            return data

        return {"repository": repository, "tag": tag, "status": "deleted"}

    @mcp.tool()
    def docker_hub_list_webhooks(
        repository: str,
    ) -> dict[str, Any]:
        """
        List webhooks configured for a Docker Hub repository.

        Args:
            repository: Full repository name (e.g. "myuser/myapp")

        Returns:
            Dict with webhooks list (name, hook_url, active, expect_final_callback)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not repository:
            return {"error": "repository is required"}

        data = _get(f"repositories/{repository}/webhooks", token)
        if "error" in data:
            return data

        webhooks = []
        for wh in data.get("results", []):
            hooks = wh.get("webhooks", [])
            webhook_urls = [h.get("hook_url", "") for h in hooks]
            webhooks.append(
                {
                    "id": wh.get("id", ""),
                    "name": wh.get("name", ""),
                    "active": wh.get("active", False),
                    "expect_final_callback": wh.get("expect_final_callback", False),
                    "hook_urls": webhook_urls,
                    "created_at": wh.get("created_date", ""),
                }
            )
        return {"repository": repository, "webhooks": webhooks, "count": len(webhooks)}
