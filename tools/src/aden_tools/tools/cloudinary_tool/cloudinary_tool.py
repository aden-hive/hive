"""
Cloudinary Tool - Image/video upload, management, and search.

Supports:
- Cloudinary API key + secret (Basic auth)
- Upload, list, get, delete resources
- Search with Lucene-like expressions

API Reference: https://cloudinary.com/documentation/admin_api
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_credentials(
    credentials: CredentialStoreAdapter | None,
) -> tuple[str | None, str | None, str | None]:
    """Return (cloud_name, api_key, api_secret)."""
    if credentials is not None:
        cloud = credentials.get("cloudinary_cloud_name")
        key = credentials.get("cloudinary_key")
        secret = credentials.get("cloudinary_secret")
        return cloud, key, secret
    return (
        os.getenv("CLOUDINARY_CLOUD_NAME"),
        os.getenv("CLOUDINARY_API_KEY"),
        os.getenv("CLOUDINARY_API_SECRET"),
    )


def _base_url(cloud_name: str) -> str:
    return f"https://api.cloudinary.com/v1_1/{cloud_name}"


def _auth_header(api_key: str, api_secret: str) -> str:
    encoded = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
    return f"Basic {encoded}"


def _request(method: str, url: str, api_key: str, api_secret: str, **kwargs: Any) -> dict[str, Any]:
    """Make a request to the Cloudinary API."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = _auth_header(api_key, api_secret)
    try:
        resp = getattr(httpx, method)(
            url,
            headers=headers,
            timeout=60.0,
            **kwargs,
        )
        if resp.status_code == 401:
            return {"error": "Unauthorized. Check your Cloudinary credentials."}
        if resp.status_code not in (200, 201):
            return {"error": f"Cloudinary API error {resp.status_code}: {resp.text[:500]}"}
        return resp.json()
    except httpx.TimeoutException:
        return {"error": "Request to Cloudinary timed out"}
    except Exception as e:
        return {"error": f"Cloudinary request failed: {e!s}"}


def _auth_error() -> dict[str, Any]:
    return {
        "error": "CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET not set",
        "help": "Get credentials from your Cloudinary dashboard at https://console.cloudinary.com/",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Cloudinary tools with the MCP server."""

    @mcp.tool()
    def cloudinary_upload(
        file_url: str,
        public_id: str = "",
        folder: str = "",
        tags: str = "",
        resource_type: str = "auto",
    ) -> dict[str, Any]:
        """
        Upload an image, video, or file to Cloudinary from a URL.

        Args:
            file_url: URL of the file to upload (required)
            public_id: Custom public ID for the asset (optional)
            folder: Folder path (optional)
            tags: Comma-separated tags (optional)
            resource_type: Type: image, video, raw, auto (default auto)

        Returns:
            Dict with uploaded asset details (public_id, url, format, bytes)
        """
        cloud, key, secret = _get_credentials(credentials)
        if not cloud or not key or not secret:
            return _auth_error()
        if not file_url:
            return {"error": "file_url is required"}

        url = f"{_base_url(cloud)}/{resource_type}/upload"
        data: dict[str, Any] = {"file": file_url}
        if public_id:
            data["public_id"] = public_id
        if folder:
            data["folder"] = folder
        if tags:
            data["tags"] = tags

        result = _request("post", url, key, secret, data=data)
        if "error" in result:
            return result

        return {
            "public_id": result.get("public_id", ""),
            "secure_url": result.get("secure_url", ""),
            "format": result.get("format", ""),
            "resource_type": result.get("resource_type", ""),
            "bytes": result.get("bytes", 0),
            "width": result.get("width"),
            "height": result.get("height"),
            "created_at": result.get("created_at", ""),
        }

    @mcp.tool()
    def cloudinary_list_resources(
        resource_type: str = "image",
        max_results: int = 30,
        prefix: str = "",
    ) -> dict[str, Any]:
        """
        List resources in your Cloudinary account.

        Args:
            resource_type: Type: image, video, raw (default image)
            max_results: Max results (1-500, default 30)
            prefix: Filter by public_id prefix / folder (optional)

        Returns:
            Dict with resources list (public_id, url, format, bytes)
        """
        cloud, key, secret = _get_credentials(credentials)
        if not cloud or not key or not secret:
            return _auth_error()

        url = f"{_base_url(cloud)}/resources/{resource_type}"
        params: dict[str, Any] = {"max_results": max(1, min(max_results, 500))}
        if prefix:
            params["prefix"] = prefix

        data = _request("get", url, key, secret, params=params)
        if "error" in data:
            return data

        resources = []
        for r in data.get("resources", []):
            resources.append(
                {
                    "public_id": r.get("public_id", ""),
                    "secure_url": r.get("secure_url", ""),
                    "format": r.get("format", ""),
                    "bytes": r.get("bytes", 0),
                    "width": r.get("width"),
                    "height": r.get("height"),
                    "created_at": r.get("created_at", ""),
                }
            )
        return {"resources": resources, "count": len(resources)}

    @mcp.tool()
    def cloudinary_get_resource(
        public_id: str,
        resource_type: str = "image",
    ) -> dict[str, Any]:
        """
        Get details about a specific Cloudinary resource.

        Args:
            public_id: Public ID of the resource (required)
            resource_type: Type: image, video, raw (default image)

        Returns:
            Dict with resource details including tags and metadata
        """
        cloud, key, secret = _get_credentials(credentials)
        if not cloud or not key or not secret:
            return _auth_error()
        if not public_id:
            return {"error": "public_id is required"}

        url = f"{_base_url(cloud)}/resources/{resource_type}/upload/{public_id}"
        data = _request("get", url, key, secret)
        if "error" in data:
            return data

        return {
            "public_id": data.get("public_id", ""),
            "secure_url": data.get("secure_url", ""),
            "format": data.get("format", ""),
            "resource_type": data.get("resource_type", ""),
            "bytes": data.get("bytes", 0),
            "width": data.get("width"),
            "height": data.get("height"),
            "tags": data.get("tags", []),
            "created_at": data.get("created_at", ""),
            "status": data.get("status", ""),
        }

    @mcp.tool()
    def cloudinary_delete_resource(
        public_id: str,
        resource_type: str = "image",
    ) -> dict[str, Any]:
        """
        Delete a resource from Cloudinary.

        Args:
            public_id: Public ID of the resource to delete (required)
            resource_type: Type: image, video, raw (default image)

        Returns:
            Dict with deletion result
        """
        cloud, key, secret = _get_credentials(credentials)
        if not cloud or not key or not secret:
            return _auth_error()
        if not public_id:
            return {"error": "public_id is required"}

        url = f"{_base_url(cloud)}/{resource_type}/destroy"
        data = _request("post", url, key, secret, data={"public_id": public_id})
        if "error" in data:
            return data

        return {"public_id": public_id, "result": data.get("result", "unknown")}

    @mcp.tool()
    def cloudinary_search(
        expression: str,
        max_results: int = 30,
    ) -> dict[str, Any]:
        """
        Search for resources using Cloudinary's search API.

        Args:
            expression: Lucene-like search expression (e.g. "resource_type:image AND tags=nature")
            max_results: Max results (1-500, default 30)

        Returns:
            Dict with matching resources and total count
        """
        cloud, key, secret = _get_credentials(credentials)
        if not cloud or not key or not secret:
            return _auth_error()
        if not expression:
            return {"error": "expression is required"}

        url = f"{_base_url(cloud)}/resources/search"
        body = {
            "expression": expression,
            "max_results": max(1, min(max_results, 500)),
        }
        data = _request(
            "post", url, key, secret, json=body, headers={"Content-Type": "application/json"}
        )
        if "error" in data:
            return data

        resources = []
        for r in data.get("resources", []):
            resources.append(
                {
                    "public_id": r.get("public_id", ""),
                    "secure_url": r.get("secure_url", ""),
                    "format": r.get("format", ""),
                    "resource_type": r.get("resource_type", ""),
                    "bytes": r.get("bytes", 0),
                    "created_at": r.get("created_at", ""),
                }
            )
        return {
            "resources": resources,
            "total_count": data.get("total_count", 0),
        }
