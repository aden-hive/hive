"""
Google Drive Tool — list, search, read, upload, and manage files via Drive API v3.

Supports OAuth 2.0 access token from the credential store (``google_drive``) or
``GOOGLE_DRIVE_ACCESS_TOKEN`` in the environment.

API reference: https://developers.google.com/drive/api/reference/rest/v3
"""

from __future__ import annotations

import base64
import json
import os
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"

_GOOGLE_APPS_PREFIX = "application/vnd.google-apps."

_DEFAULT_EXPORT: dict[str, str] = {
    "document": "text/plain",
    "spreadsheet": "text/csv",
    "presentation": "application/pdf",
    "drawing": "image/png",
}


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        token = credentials.get("google_drive")
        if token is not None and not isinstance(token, str):
            raise TypeError(
                f"Expected string from credentials.get('google_drive'), got {type(token).__name__}"
            )
        return token
    return os.getenv("GOOGLE_DRIVE_ACCESS_TOKEN")


def _auth_error() -> dict[str, Any]:
    return {
        "error": "GOOGLE_DRIVE_ACCESS_TOKEN not set",
        "help": "Set GOOGLE_DRIVE_ACCESS_TOKEN or connect google_drive in the credential store.",
    }


def _headers_json(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _safe_file_id(file_id: str) -> str | None:
    if not file_id or "/" in file_id or ".." in file_id:
        return None
    return file_id


def _drive_q_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _error_from_response(resp: httpx.Response) -> dict[str, Any]:
    try:
        payload = resp.json()
        msg = payload.get("error", {})
        if isinstance(msg, dict):
            detail = msg.get("message", resp.text)
        else:
            detail = str(msg)
    except Exception:
        detail = resp.text[:500]
    return {"error": f"Google Drive API error (HTTP {resp.status_code}): {detail}"}


def _multipart_related_upload(
    metadata: dict[str, Any],
    body: bytes,
    mime_type: str,
) -> tuple[bytes, str]:
    boundary = "adenDriveUploadBoundary"
    meta_json = json.dumps(metadata).encode("utf-8")
    crlf = b"\r\n"
    parts: list[bytes] = [
        b"--" + boundary.encode() + crlf,
        b"Content-Type: application/json; charset=UTF-8" + crlf + crlf,
        meta_json + crlf,
        b"--" + boundary.encode() + crlf,
        f"Content-Type: {mime_type}".encode() + crlf + crlf,
        body + crlf,
        b"--" + boundary.encode() + b"--" + crlf,
    ]
    return b"".join(parts), boundary


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Google Drive tools with the MCP server."""

    def _request_json(
        method: str,
        url: str,
        token: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        try:
            resp = httpx.request(
                method,
                url,
                headers=_headers_json(token),
                params=params,
                json=json_body,
                timeout=timeout,
            )
        except httpx.TimeoutException:
            return {"error": "Google Drive API request timed out"}
        except Exception as e:
            return {"error": f"Google Drive API request failed: {e!s}"}

        if resp.status_code == 401:
            return {"error": "Unauthorized. Access token may be expired or invalid."}
        if resp.status_code == 403:
            return {
                "error": f"Forbidden. Check Drive API scopes and sharing. {resp.text[:300]}",
            }
        if resp.status_code == 204:
            return {"status": "success"}
        if resp.status_code >= 400:
            return _error_from_response(resp)
        if not resp.content:
            return {"status": "success"}
        try:
            return resp.json()
        except Exception:
            return {"error": "Invalid JSON in Google Drive API response"}

    def _get_metadata(token: str, file_id: str, fields: str | None = None) -> dict[str, Any]:
        fid = _safe_file_id(file_id)
        if not fid:
            return {"error": "file_id is required and must be a valid Drive file id"}
        params: dict[str, Any] = {}
        if fields:
            params["fields"] = fields
        return _request_json(
            "GET",
            f"{DRIVE_API_BASE}/files/{fid}",
            token,
            params=params or None,
        )

    def _download_or_export(
        token: str,
        file_id: str,
        *,
        export_mime_type: str | None,
        binary_only: bool,
    ) -> dict[str, Any]:
        fid = _safe_file_id(file_id)
        if not fid:
            return {"error": "file_id is required and must be a valid Drive file id"}

        meta = _get_metadata(
            token,
            fid,
            fields="id,name,mimeType,size",
        )
        if "error" in meta:
            return meta

        mime = meta.get("mimeType", "")
        is_google_app = mime.startswith(_GOOGLE_APPS_PREFIX)

        if is_google_app:
            if binary_only and not export_mime_type:
                return {
                    "error": (
                        "This file is a Google Workspace document. "
                        "Pass export_mime_type (e.g. application/pdf, text/plain, text/csv)."
                    ),
                    "mimeType": mime,
                }
            app_kind = mime.removeprefix(_GOOGLE_APPS_PREFIX)
            export_mime = export_mime_type or _DEFAULT_EXPORT.get(app_kind, "application/pdf")
            url = f"{DRIVE_API_BASE}/files/{quote(fid)}/export"
            try:
                resp = httpx.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params={"mimeType": export_mime},
                    timeout=120.0,
                )
            except httpx.TimeoutException:
                return {"error": "Export request timed out"}
            except Exception as e:
                return {"error": f"Export failed: {e!s}"}
            if resp.status_code != 200:
                return _error_from_response(resp)
            content_type = export_mime
        else:
            url = f"{DRIVE_API_BASE}/files/{quote(fid)}"
            try:
                resp = httpx.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params={"alt": "media"},
                    timeout=120.0,
                )
            except httpx.TimeoutException:
                return {"error": "Download request timed out"}
            except Exception as e:
                return {"error": f"Download failed: {e!s}"}
            if resp.status_code != 200:
                return _error_from_response(resp)
            content_type = mime or "application/octet-stream"

        is_text = content_type.startswith("text/") or content_type in (
            "application/json",
            "application/xml",
            "application/javascript",
        )

        raw = resp.content
        return {
            "file_id": fid,
            "name": meta.get("name", ""),
            "size": meta.get("size"),
            "content_type": content_type,
            "content": raw.decode("utf-8") if is_text else base64.b64encode(raw).decode("ascii"),
            "encoding": "text" if is_text else "base64",
        }

    @mcp.tool()
    def drive_list_files(
        folder_id: str = "",
        page_size: int = 50,
    ) -> dict[str, Any]:
        """
        List files and folders in a Drive directory.

        Args:
            folder_id: Parent folder id (empty string for the root of My Drive)
            page_size: Max items to return (1–100)

        Returns:
            Dict with ``items`` (id, name, mimeType, size, modifiedTime, webViewLink)
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()

        page_size = max(1, min(page_size, 100))
        parent = folder_id.strip() if folder_id.strip() else "root"
        q = f"'{_drive_q_escape(parent)}' in parents and trashed=false"

        data = _request_json(
            "GET",
            f"{DRIVE_API_BASE}/files",
            token,
            params={
                "q": q,
                "pageSize": page_size,
                "fields": (
                    "files(id,name,mimeType,size,modifiedTime,webViewLink),"
                    "nextPageToken,incompleteSearch"
                ),
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
        )
        if "error" in data:
            return data

        items = []
        for f in data.get("files", []):
            items.append(
                {
                    "id": f.get("id", ""),
                    "name": f.get("name", ""),
                    "mimeType": f.get("mimeType", ""),
                    "size": f.get("size"),
                    "modifiedTime": f.get("modifiedTime", ""),
                    "webViewLink": f.get("webViewLink", ""),
                }
            )
        return {
            "folder_id": parent,
            "items": items,
            "next_page_token": data.get("nextPageToken"),
        }

    @mcp.tool()
    def drive_search_files(
        query: str,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """
        Search Drive files by full-text and name (Drive query API).

        Args:
            query: Search text (matched against file content and name where supported)
            page_size: Max results (1–100)

        Returns:
            Dict with ``query`` and ``files`` list
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not query.strip():
            return {"error": "query is required"}

        page_size = max(1, min(page_size, 100))
        escaped = _drive_q_escape(query.strip())
        q = f"fullText contains '{escaped}' and trashed=false"

        data = _request_json(
            "GET",
            f"{DRIVE_API_BASE}/files",
            token,
            params={
                "q": q,
                "pageSize": page_size,
                "fields": ("files(id,name,mimeType,size,modifiedTime,webViewLink),nextPageToken"),
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
        )
        if "error" in data:
            return data

        files = []
        for f in data.get("files", []):
            files.append(
                {
                    "id": f.get("id", ""),
                    "name": f.get("name", ""),
                    "mimeType": f.get("mimeType", ""),
                    "size": f.get("size"),
                    "modifiedTime": f.get("modifiedTime", ""),
                    "webViewLink": f.get("webViewLink", ""),
                }
            )
        return {
            "query": query.strip(),
            "files": files,
            "next_page_token": data.get("nextPageToken"),
        }

    @mcp.tool()
    def drive_get_file_metadata(file_id: str) -> dict[str, Any]:
        """
        Get metadata for a Drive file or folder.

        Args:
            file_id: Drive file id

        Returns:
            File metadata fields from the Drive API
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        return _get_metadata(
            token,
            file_id,
            fields=(
                "id,name,mimeType,size,createdTime,modifiedTime,parents,webViewLink,"
                "webContentLink,owners,shared,permissions"
            ),
        )

    @mcp.tool()
    def drive_get_file(
        file_id: str,
        export_mime_type: str = "",
    ) -> dict[str, Any]:
        """
        Read file content from Drive. Binary files return base64; text exports return text.

        For Google Docs, Sheets, and Slides, exports using a default format unless
        ``export_mime_type`` is set (e.g. ``application/pdf``, ``text/plain``, ``text/csv``).

        Args:
            file_id: Drive file id
            export_mime_type: Optional export MIME type for Google Workspace files

        Returns:
            Dict with name, content_type, encoding (text or base64), and content
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        return _download_or_export(
            token,
            file_id,
            export_mime_type=export_mime_type.strip() or None,
            binary_only=False,
        )

    @mcp.tool()
    def drive_download_file(
        file_id: str,
        export_mime_type: str = "",
    ) -> dict[str, Any]:
        """
        Download a non–Google Workspace file (``alt=media``). Google Docs/Sheets/Slides
        require ``export_mime_type`` (e.g. ``application/pdf``).

        Args:
            file_id: Drive file id
            export_mime_type: Required MIME type for exporting Google Workspace files

        Returns:
            Dict with name, content_type, encoding, and content
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        return _download_or_export(
            token,
            file_id,
            export_mime_type=export_mime_type.strip() or None,
            binary_only=True,
        )

    @mcp.tool()
    def drive_upload_file(
        name: str,
        content: str,
        folder_id: str = "",
        mime_type: str = "text/plain",
    ) -> dict[str, Any]:
        """
        Upload a small file with multipart upload (about 5 MiB or less).

        Args:
            name: File name in Drive
            content: File body as text (encoded UTF-8)
            folder_id: Optional parent folder id
            mime_type: Media MIME type

        Returns:
            Dict with id, name, webViewLink, and mimeType for the new file
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not name.strip() or content is None:
            return {"error": "name and content are required"}

        metadata: dict[str, Any] = {"name": name.strip()}
        if folder_id.strip():
            metadata["parents"] = [folder_id.strip()]

        body_bytes = content.encode("utf-8")
        if len(body_bytes) > 5 * 1024 * 1024:
            return {
                "error": (
                    "File exceeds simple upload size (~5 MiB). "
                    "Use resumable upload (not implemented)."
                ),
            }

        raw_body, boundary = _multipart_related_upload(metadata, body_bytes, mime_type)
        url = f"{DRIVE_UPLOAD_BASE}/files?uploadType=multipart&supportsAllDrives=true"
        try:
            resp = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": f"multipart/related; boundary={boundary}",
                },
                content=raw_body,
                timeout=120.0,
            )
        except httpx.TimeoutException:
            return {"error": "Upload timed out"}
        except Exception as e:
            return {"error": f"Upload failed: {e!s}"}

        if resp.status_code not in (200, 201):
            return _error_from_response(resp)
        try:
            data = resp.json()
        except Exception:
            return {"error": "Invalid JSON in upload response"}
        return {
            "status": "uploaded",
            "id": data.get("id", ""),
            "name": data.get("name", ""),
            "mimeType": data.get("mimeType", ""),
            "webViewLink": data.get("webViewLink", ""),
        }

    @mcp.tool()
    def drive_create_folder(
        name: str,
        folder_id: str = "",
    ) -> dict[str, Any]:
        """
        Create a folder in Drive.

        Args:
            name: Folder name
            folder_id: Optional parent folder id (empty for root of My Drive)

        Returns:
            New folder id, name, and webViewLink
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        if not name.strip():
            return {"error": "name is required"}

        body: dict[str, Any] = {
            "name": name.strip(),
            "mimeType": "application/vnd.google-apps.folder",
        }
        if folder_id.strip():
            body["parents"] = [folder_id.strip()]

        data = _request_json("POST", f"{DRIVE_API_BASE}/files", token, json_body=body)
        if "error" in data:
            return data
        return {
            "status": "created",
            "id": data.get("id", ""),
            "name": data.get("name", ""),
            "webViewLink": data.get("webViewLink", ""),
        }

    @mcp.tool()
    def drive_delete_file(file_id: str) -> dict[str, Any]:
        """
        Permanently delete a file or move it to trash depending on account settings;
        Drive API ``files.delete`` removes the file (see API docs for shared drives).

        Args:
            file_id: Drive file id

        Returns:
            Status dict or error
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        fid = _safe_file_id(file_id)
        if not fid:
            return {"error": "file_id is required and must be a valid Drive file id"}

        result = _request_json(
            "DELETE",
            f"{DRIVE_API_BASE}/files/{fid}",
            token,
            params={"supportsAllDrives": "true"},
        )
        if "error" in result:
            return result
        return {"status": "deleted", "file_id": fid}

    @mcp.tool()
    def drive_share_file(
        file_id: str,
        role: str,
        share_type: str,
        email_address: str = "",
    ) -> dict[str, Any]:
        """
        Add a permission so others can access a file.

        Args:
            file_id: Drive file id
            role: One of: reader, writer, commenter, organizer, fileOrganizer
            share_type: user, group, domain, or anyone
            email_address: Required for user/group (email); domain for domain type

        Returns:
            Permission id and details
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        fid = _safe_file_id(file_id)
        if not fid:
            return {"error": "file_id is required and must be a valid Drive file id"}

        valid_roles = frozenset(
            {"reader", "writer", "commenter", "organizer", "fileOrganizer"},
        )
        if role not in valid_roles:
            return {"error": f"role must be one of: {', '.join(sorted(valid_roles))}"}

        st = share_type.strip().lower()
        if st not in {"user", "group", "domain", "anyone"}:
            return {"error": "share_type must be user, group, domain, or anyone"}

        body: dict[str, Any] = {"role": role, "type": st}
        if st in {"user", "group"}:
            if not email_address.strip():
                return {"error": "email_address is required for user and group shares"}
            body["emailAddress"] = email_address.strip()
        elif st == "domain":
            if not email_address.strip():
                return {"error": "domain is required when share_type is domain"}
            body["domain"] = email_address.strip()

        return _request_json(
            "POST",
            f"{DRIVE_API_BASE}/files/{fid}/permissions",
            token,
            params={"supportsAllDrives": "true", "sendNotificationEmail": "false"},
            json_body=body,
        )

    @mcp.tool()
    def drive_copy_file(
        file_id: str,
        name: str = "",
        folder_id: str = "",
    ) -> dict[str, Any]:
        """
        Copy a Drive file.

        Args:
            file_id: Source file id
            name: Optional new name (default: copy of original)
            folder_id: Optional parent folder for the copy

        Returns:
            New file id and metadata
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        fid = _safe_file_id(file_id)
        if not fid:
            return {"error": "file_id is required and must be a valid Drive file id"}

        body: dict[str, Any] = {}
        if name.strip():
            body["name"] = name.strip()
        if folder_id.strip():
            body["parents"] = [folder_id.strip()]

        return _request_json(
            "POST",
            f"{DRIVE_API_BASE}/files/{quote(fid)}/copy",
            token,
            params={"supportsAllDrives": "true"},
            json_body=body if body else {},
        )

    @mcp.tool()
    def drive_move_file(
        file_id: str,
        new_parent_id: str,
        previous_parent_id: str,
    ) -> dict[str, Any]:
        """
        Move a file to another folder by updating parents.

        Args:
            file_id: File to move
            new_parent_id: Destination folder id
            previous_parent_id: Current parent folder id to remove

        Returns:
            Updated file metadata
        """
        token = _get_token(credentials)
        if not token:
            return _auth_error()
        fid = _safe_file_id(file_id)
        if not fid:
            return {"error": "file_id is required and must be a valid Drive file id"}
        if not new_parent_id.strip() or not previous_parent_id.strip():
            return {"error": "new_parent_id and previous_parent_id are required"}

        return _request_json(
            "PATCH",
            f"{DRIVE_API_BASE}/files/{fid}",
            token,
            params={
                "addParents": new_parent_id.strip(),
                "removeParents": previous_parent_id.strip(),
                "supportsAllDrives": "true",
            },
            json_body={},
        )
