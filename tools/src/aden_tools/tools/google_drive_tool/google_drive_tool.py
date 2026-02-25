from __future__ import annotations

import base64
import mimetypes
import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


API_BASE = "https://www.googleapis.com/drive/v3"
API_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"

class _GoogleDriveClient:
    """Internal client wrapping Google Drive API v3 calls."""

    def __init__(self, access_token: str):
        self._token = access_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid or expired Google Drive access token"}
        if response.status_code == 403:
            return {"error": "Insufficient permissions or not authorized."}
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            return {"error": f"Google Drive API error (HTTP {response.status_code}): {detail}"}
        return response.json()

    def list_files(self, specifyfolder=None):
        if specifyfolder is None:
            params = {
                "fields": "files(id,name,mimeType,parents)"
            }
        else:
            params = {
                "q": f"'{specifyfolder}' in parents",
                "fields": "files(id,name,mimeType,parents)"
            }

        with httpx.Client() as client:
            r = client.get(
                f"{API_BASE}/files",
                headers=self._headers,
                params=params
            )
            return self._handle_response(r)

    def create_folder(self, filename=None):
        file_metadata = {
            "name": filename,
            "mimeType": "application/vnd.google-apps.folder"
        }
        with httpx.Client() as client:
            r = client.post(
                f"{API_BASE}/files",
                headers=self._headers,
                json=file_metadata
            )
            return self._handle_response(r)

    def upload_file(self, filepath):
        filename = os.path.basename(filepath)
        mime_type, _ = mimetypes.guess_type(filepath)
        if not mime_type:
            mime_type = "application/octet-stream"
        metadata = {
            "name": filename
        }
        with httpx.Client(timeout=None) as client:
            try:
                with open(filepath, "rb") as f:
                    files = {
                        "metadata": (None,httpx._content.json_dumps(metadata),
                                    "application/json; charset=UTF-8",),
                        "file": (filename,f,mime_type,),
                    }

                    r = client.post(API_UPLOAD,headers=self._headers,
                                    params={"uploadType": "multipart"},files=files)

                    return self._handle_response(r)
            except FileNotFoundError:
                return {"error": f"No such file or directory: {filepath}"}

    def search_files(self, filename=None, filetype=None, modified=None, people=None):
        file_type = "" if filetype is None else f"and mimeType contains '{filetype}'"
        file_name = "" if filename is None else f"and name = '{filename}'"
        modified_after = "" if modified is None else f"and modifiedTime >'{modified}'"
        owners = "" if people is None else f"and '{people}' in owners"
        params = {
            "q": f"mimeType contains '/' {file_type} {file_name} {modified_after} {owners}",
            "fields": "files(id,name,mimeType,parents)"
        }
        with httpx.Client() as client:
            r = client.get(
                f"{API_BASE}/files",
                headers=self._headers,
                params=params
            )
            return self._handle_response(r)

    def download_file(self, filename=None):
        result = self.search_files(filename=filename)
        if result["files"] == []:
            return {"error": f"File not found with name: {filename}"}
        meta = result["files"][0]
        file_id = meta["id"]
        mime_type = meta.get("mimeType")
        # Map Google types to common export formats
        export_map = {
            "application/vnd.google-apps.drawing": ("image/jpeg", ".jpg"),
            "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
            "application/vnd.google-apps.spreadsheet":
            ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
            "application/vnd.google-apps.presentation":
            ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx")
        }
        with httpx.Client() as client:
            if mime_type in export_map:
                target_mime, ext = export_map[mime_type]
                # Add extension if not already present
                if not filename.endswith(ext):
                    filename += ext
                url = f"{API_BASE}/files/{file_id}/export?mimeType={target_mime}"
            else:
                url = f"{API_BASE}/files/{file_id}?alt=media"
            r = client.get(url, headers=self._headers)
            if r.status_code == 200:
                with open(filename, "wb") as f:
                    f.write(r.content)
                # Return base64-encoded content for binary formats
                return {
                    "filename": filename,
                    "mime_type": mime_type,
                    "content_base64": base64.b64encode(r.content).decode("utf-8"),
                    "size_bytes": len(r.content),
                }
        return self._handle_response(r)

    def delete_file(self, filename=None):
        result = self.search_files(filename=filename)
        if result["files"] == []:
            return {"error": f"File not found with name: {filename}"}
        meta = result["files"][0]
        file_id = meta["id"]
        body_value = {"trashed": True}
        with httpx.Client() as client:
            r = client.patch(
                f"{API_BASE}/files/{file_id}", headers=self._headers, json=body_value
            )
            return self._handle_response(r)

    def empty_trash(self):
        with httpx.Client() as client:
            r = client.delete(f"{API_BASE}/files/trash", headers=self._headers)
            r.raise_for_status()
            if r.status_code == 204 or not r.text:
                return {"status": "success", "message": "Trash emptied"}
            return {"status": "failed", "message": "Trash not emptied"}

    def move_file(self, filename=None, folder=None):
        result = self.search_files(filename=filename)
        if result["files"] == []:
            return {"error": f"File not found with name: {filename}"}
        meta = result["files"][0]
        file_id = meta["id"]
        folder_data = self.search_files(filename=folder)
        if folder_data["files"] == []:
            return {"error": f"Folder not found with name: {folder}"}
        prop = folder_data["files"][0]
        folder_id = prop["id"]
        current_parent = ",".join(prop.get("parents", []))
        params = {
            "addParents": folder_id,
            "removeParents": current_parent,
            "fields": "id, name, parents"  # Ask for new state in response
        }
        with httpx.Client() as client:
            r = client.patch(
                f"{API_BASE}/files/{file_id}", headers=self._headers, params = params, json = {}
            )
            return self._handle_response(r)

    def share_file_as_link(self, filename=None):
        files_data = self.search_files(filename=filename)
        if files_data["files"] == []:
            return {"error": f"File not found with name: {filename}"}
        meta = files_data["files"][0]
        file_id = meta["id"]
        permissions_payload = {
            "role": "reader",
            "type": "anyone"
        }
        params = {
            "fields": "id, name, webViewLink"  # Ask for new state in response
        }
        with httpx.Client() as client:
            r = client.post(
                f"{API_BASE}/files/{file_id}/permissions", headers=self._headers,
                json = permissions_payload)
            if r.status_code != 200:
                return self._handle_response(r)
            resp = client.get(f"{API_BASE}/files/{file_id}", headers=self._headers,
                params = params)
        return self._handle_response(resp)

    def update_permissions(self, filename=None, p_type=None, respondent=None, role=None):
        files_data = self.search_files(filename=filename)
        if files_data["files"] == []:
            return {"error": f"File not found with name: {filename}"}
        meta = files_data["files"][0]
        file_id = meta["id"]
        if respondent is not None and p_type is not None and role is not None:
            if "@" in str(respondent):
                permissions_payload = {
                    "role": f"{role}",
                    "type": f"{p_type}",
                    "emailAddress": f"{respondent}"
                }
            else:
                permissions_payload = {
                    "role": f"{role}",
                    "type": f"{p_type}",
                    "domain": f"{respondent}"
                }
        else:
            permissions_payload = {
                "role": "reader",
                "type": "anyone",
            }
        with httpx.Client() as client:
            r = client.post(
                f"{API_BASE}/files/{file_id}/permissions", headers=self._headers,
                json = permissions_payload)
            permissions_found = r.json()
            if r.status_code == 200 and permissions_found["role"] != permissions_payload["role"]:
                role_load = {"role": permissions_payload["role"]}
                res = client.patch(f"{API_BASE}/files/{file_id}/"
                                   f"permissions/{permissions_found['id']}",
                                   headers=self._headers,json = role_load)
                return self._handle_response(res)
            else:
                return self._handle_response(r)

def register_tools(mcp: FastMCP, credentials: CredentialStoreAdapter | None = None) -> None:
    """Register Google Drive tools with the MCP server."""

    def _get_token() -> str | None:
        """Get Google drive access token from credential manager or environment."""
        if credentials is not None:
            token = credentials.get("google_drive")
            # Defensive check: ensure we get a string, not a complex object
            if token is not None and not isinstance(token, str):
                raise TypeError(f"Expected string from credentials.get('google_drive'),"
                    f" got {type(token).__name__}")
            return token
        return None

    def _get_client() -> _GoogleDriveClient | dict[str, str]:
        """Get GoogleDrive client, or return an error dict if no credentials are configured."""
        token = _get_token()
        if not token:
            return {
                "error": "Google Drive credentials not configured",
                "help": (
                    "Set GOOGLE SERVICE ACCOUNT "
                    "or configure via credential store"
                ),
            }
        return _GoogleDriveClient(token)

    # --- GoogleDrive Management ---
    @mcp.tool()
    def google_drive_create_folder(filename: str,) -> dict:
        """
        Get Google Drive file metadata.
        Args:
            folder_name:  used as file name metadata
        Returns:
            Dict with folder id and properties
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.create_folder(filename)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_drive_upload_file(filepath: str) -> dict:
        """
        Upload file to google drive.
        Args:
            filepath: The path to the file to upload
        Returns:
            Dict with file id
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.upload_file(filepath)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Search for files ---
    @mcp.tool()
    def google_drive_search_file(filename: str, filetype: str, modified: str, people: str) -> dict:
        """
        Search for files in Google Drive based on criteria.
        Args:
            filename: Exact file name to search for
            file_type: MIME type or partial type (e.g., "image", "application/pdf ")
            modified: ISO 8601 date string to find files modified after
            (e.g.,"2024-01-01T00:00:00Z")
            people: Email address of an owner to find files owned by that person

        Returns:
            Dict with values or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.search_files(filename, filetype, modified, people)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- download file ---

    @mcp.tool()
    def google_drive_download_file(filename: str, ) -> dict:
        """
        download file from google drive
        Args:
            filename: The name of the file to download
        Returns:
            Dict with download result or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.download_file(filename)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_drive_delete_file(filename: str,) -> dict:
        """
        Delete file from google drive
        Args:
            filename: The name of the file to delete
        Returns:
            Dict with delete result or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.delete_file(filename)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_drive_empty_trash() -> dict:
        """
        Clear files in google drive trash
        Returns:
            Dict with success or error message
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.empty_trash()
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- move file and folders ---

    @mcp.tool()
    def google_drive_move_file(filename: str, folder: str) -> dict:
        """
        Move a file to a specific folder in Google Drive.
        Args:
            filename: The name of the file to move
            folder: The name of the target folder
        Returns:
            Dict with filename parent or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.move_file(filename, folder)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_drive_list_files(specifyfolder: str) -> dict:
        """
        List files in Google Drive, optionally within a specific folder.

        Args:
            specifyfolder: Optional folder name to filter files by

        Returns:
            Dict with list of files or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.list_files(specifyfolder)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    # --- Permissions management ---

    @mcp.tool()
    def google_drive_update_permissions(filename: str,
                                         p_type: str, respondent: str, role: str) -> dict:
        """
        Update file permissions in Google Drive
        Args:
            filename: The name of the file to update permissions for
            p_type: The type of permission (e.g., "user", "group", "domain", "anyone")
            respondent user: The email address of the user or domain address
            role: The permission role to assign (e.g., "reader", "writer", "commenter")

        Returns:
            Dict with update permissions result or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.update_permissions(filename, p_type, respondent, role)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}

    @mcp.tool()
    def google_drive_share_file_link(filename: str) -> dict:
        """
        Share a file in Google Drive via link sharing.
        Args:
           filename: The name of the file to share
        Returns:
            Dict with share link or error
        """
        client = _get_client()
        if isinstance(client, dict):
            return client
        try:
            return client.share_file_as_link(filename)
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as e:
            return {"error": f"Network error: {e}"}
