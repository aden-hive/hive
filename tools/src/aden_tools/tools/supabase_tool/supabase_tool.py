"""Supabase tool implementation."""

from __future__ import annotations

import mimetypes
import os
from typing import Any

import httpx

DEFAULT_TIMEOUT = 30.0


class SupabaseClient:
    """Client for Supabase interaction."""

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """
        Initialize Supabase client.

        Args:
            url: Supabase URL (e.g., https://xyz.supabase.co)
            key: Service Role Key or Anon Key
            timeout: Request timeout
        """
        self.url = (url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        # Prioritize Service Role Key for backend agents, fallback to Anon Key
        self.key = (
            key
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_ANON_KEY")
        )
        self.timeout = timeout

        if not self.url or not self.key:
            raise ValueError(
                "Supabase URL and Key are required. Set SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_ANON_KEY) environment variables."
            )

        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    def _make_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: Any | None = None,
        content: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        """Execute HTTP request."""
        url = f"{self.url}{path}"
        headers = self.headers.copy()
        if extra_headers:
            headers.update(extra_headers)

        try:
            response = httpx.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_data,
                content=content,
                timeout=self.timeout,
            )

            if response.status_code == 401:
                raise PermissionError("Unauthorized: Invalid Supabase credentials")

            response.raise_for_status()

            # Return JSON if present, else plain text or empty
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return response.content

        except httpx.HTTPStatusError as e:
            # Try to return detailed error from Supabase if available
            try:
                error_body = e.response.json()
                return {"error": error_body.get("message", str(e)), "code": e.response.status_code}
            except Exception:
                return {"error": str(e), "code": e.response.status_code}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}"}
        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}

    def select(
        self,
        table: str,
        columns: str = "*",
        filters: dict[str, str] | None = None,
        limit: int = 100,
        order: str | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """
        Select rows from a table.

        Using PostgREST query syntax.
        """
        params = {"select": columns}
        if filters:
            # filters should be key=val strings or handle special ops
            # Simple assumption: keys are column names, values include operator (e.g., eq.10)
            # OR keys are columns, values are strict equalities if no op specified.
            # PostgREST style: ?col=eq.val.
            # We assume user passes full operator string in value (e.g. "eq.5")
            # or we enforce simple "eq" if just value.
            # To be flexible, we trust caller passes valid PostgREST values or we map simple dict.
            params.update(filters)

        if limit:
            params["limit"] = limit
        if order:
            params["order"] = order

        return self._make_request("GET", f"/rest/v1/{table}", params=params)

    def insert(
        self,
        table: str,
        data: dict[str, Any] | list[dict[str, Any]],
        upsert: bool = False,
    ) -> Any:
        """Insert rows."""
        headers = {"Prefer": "return=representation"}
        if upsert:
            headers["Prefer"] += ",resolution=merge-duplicates"

        return self._make_request(
            "POST",
            f"/rest/v1/{table}",
            json_data=data,
            extra_headers=headers
        )

    def update(
        self,
        table: str,
        data: dict[str, Any],
        filters: dict[str, str],
    ) -> Any:
        """Update rows matching filters."""
        headers = {"Prefer": "return=representation"}
        return self._make_request(
            "PATCH",
            f"/rest/v1/{table}",
            params=filters,
            json_data=data,
            extra_headers=headers
        )

    def delete(
        self,
        table: str,
        filters: dict[str, str],
    ) -> Any:
        """Delete rows matching filters."""
        headers = {"Prefer": "return=representation"}
        return self._make_request(
            "DELETE",
            f"/rest/v1/{table}",
            params=filters,
            extra_headers=headers
        )

    def upload_file(
        self,
        bucket: str,
        path: str,
        file_path: str,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """Upload a file to Storage."""
        path = path.lstrip("/")
        if not os.path.exists(file_path):
             return {"error": f"File not found: {file_path}"}

        if not content_type:
            content_type, _ = mimetypes.guess_type(file_path)
            content_type = content_type or "application/octet-stream"

        with open(file_path, "rb") as f:
            content = f.read()

        # Supabase Storage Upload: POST /storage/v1/object/bucket/path
        # Requires Authorization header and Content-Type

        headers = {"Content-Type": content_type}

        response = self._make_request(
            "POST",
            f"/storage/v1/object/{bucket}/{path}",
            content=content,
            extra_headers=headers
        )
        return response

    def download_file(
        self,
        bucket: str,
        path: str,
        destination: str,
    ) -> dict[str, str]:
        """Download a file from Storage."""
        path = path.lstrip("/")
        content = self._make_request("GET", f"/storage/v1/object/{bucket}/{path}")

        if isinstance(content, dict) and "error" in content:
            return content  # type: ignore

        # Write to destination
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
            with open(destination, "wb") as f:
                if isinstance(content, bytes):
                    f.write(content)
                else:
                    f.write(str(content).encode())
            return {"status": "success", "path": destination}
        except Exception as e:
            return {"error": f"Failed to write file: {str(e)}"}
