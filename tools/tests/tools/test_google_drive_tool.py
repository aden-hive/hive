"""
Tests for Google Drive Tool.

These tests use mocked HTTP responses to verify the tool's behavior
without requiring actual Google Drive API credentials.
"""

from __future__ import annotations

from unittest.mock import MagicMock, mock_open, patch

import fastmcp
import pytest

from aden_tools.tools.google_drive_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance with Google Drive tools registered."""
    server = fastmcp.FastMCP("test")
    register_tools(server)
    return server


@pytest.fixture
def mcp_with_credentials():
    """Create a FastMCP instance with mocked credentials."""
    server = fastmcp.FastMCP("test")
    mock_credentials = MagicMock()
    mock_credentials.get.return_value = "test_access_token"
    register_tools(server, credentials=mock_credentials)
    return server


def get_tool_fn(mcp, tool_name: str):
    """Helper to get a tool function from the MCP server."""
    return mcp._tool_manager._tools[tool_name].fn

# --- _GoogleDriveMCPtools tests ---
class TestGoogleDriveMCPTools:
     # Test that calling a tool without credentials returns an error
    def test_no_credentials_returns_error(self, mcp):
        """Test that missing credentials returns a helpful error."""
        with patch.dict("os.environ", {}, clear=True):
            tool_fn = get_tool_fn(mcp, "google_drive_create_folder")
            result = tool_fn(filename="test environment")
            assert "error" in result
            assert "Google Drive credentials not configured" in result["error"]

    @patch("httpx.Client.get")
    def test_list_files(self, mock_get, mcp_with_credentials):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "files": [
                {
                    "parents": [
                        "1PGDp_zKKUs1EhZ7w1qWwNPFUcisFsZow",
                    ],
                    "id": "1mEf-E7n8ZsFbr7qHKZRkyyxU7rKJQkjUSf5s580DcVg",
                    "name": "test_file.md",
                    "mimeType": "application/vnd.google-apps.document",
                },
                {
                    "parents": ["0AM05_XeArecBUk9PVA"],
                    "id": "1maMPbExXHyup5i1LmoFHuSV0bRxdbkPt",
                    "name": "background.jpg",
                    "mimeType": "image/jpeg",
                },
            ]
        }
        mock_get.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_list_files")
        result = tool_fn(specifyfolder=None)

        assert result["files"][0]["name"] == "test_file.md"

    @patch("httpx.Client.get")
    def test_list_files_query_error(self, mock_get, mcp_with_credentials):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": {"message": "Bad request"}}
        mock_get.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_list_files")
        result = tool_fn(specifyfolder="")

        assert "error" in result
        assert "Bad request" in result["error"]

    @patch("httpx.Client.post")
    def test_create_folder(self, mock_post, mcp_with_credentials):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "kind": "drive#file",
            "id": "1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA",
            "name": "test_environment",
            "mimeType": "application/vnd.google-apps.folder",
        }
        mock_post.return_value = mock_response
        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_create_folder")
        result = tool_fn(filename="test environment")

        assert result["name"] == "test_environment"

    @patch("httpx.Client.post")
    @patch("builtins.open", new_callable=mock_open, read_data="dummy content")
    def test_upload_file(self, mock_file, mock_post, mcp_with_credentials):

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "kind": "drive#file",
            "id": "1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA",
            "name": "BUILDING_TOOLS.md",
            "mimeType": "text/markdown"
        }

        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_upload_file")

        result = tool_fn(filepath="fake/path/BUILDING_TOOLS.md")

        assert result["id"] == "1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA"

    @patch("httpx.Client.post")
    def test_upload_file_missing_file(self, mock_post, mcp_with_credentials):
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": { "message": " No such file or directory"}}
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_upload_file")
        result = tool_fn(filepath="")

        assert "error" in result
        assert "No such file or directory" in result["error"]

    @patch("httpx.Client.get")
    def test_search_files(self, mock_get, mcp_with_credentials):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "parents": ["1PGDp_zKKUs1EhZ7w1qWwNPFUcisFsZow"],
            "id": "1mEf-E7n8ZsFbr7qHKZRkyyxU7rKJQkjUSf5s580DcVg",
            "name": "test morn",
            "mimeType": "application/vnd.google-apps.document",
        }
        mock_get.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_search_file")
        result = tool_fn(filename="test morn", filetype=None, modified=None, people=None)


        assert result["name"] == "test morn"

    @patch("httpx.Client.get")
    def test_search_files_not_found(self, mock_get, mcp_with_credentials):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"error": {"message": "Not Found"}}
        mock_get.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_search_file")
        result = tool_fn(filename=" ", filetype=None, modified=None, people=None)

        assert "error" in result
        assert "Not Found" in result["error"]

    @patch("httpx.Client.get")
    def test_download_file(self, mock_get, mcp_with_credentials):
        # First response → search_files()
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            "files": [
                {
                    "parents": [
                        "1PGDp_zKKUs1EhZ7w1qWwNPFUcisFsZow",
                    ],
                    "id": "1mEf-E7n8ZsFbr7qHKZRkyyxU7rKJQkjUSf5s580DcVg",
                    "name": "test_file.md",
                    "mimeType": "text/markdown",
                }
            ]
        }
        # Second response → actual file download
        mock_download_response = MagicMock()
        mock_download_response.status_code = 200
        mock_download_response.content = b"A1 B1\nA2 B2"
        mock_download_response.json.return_value = {
            "filename": "test_file.md",
            "mimeType": "text/markdown",
            "content_base64": "QTEgQjEKQTIgQjI=",
            "size_bytes": 11,
        }

        mock_get.side_effect = [mock_search_response, mock_download_response]
        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_download_file")
        result = tool_fn(filename="test_file.md")

        assert result["filename"] == "test_file.md"
        assert result["size_bytes"] == 11

    @patch("httpx.Client.get")
    def test_download_file_not_supported(self, mock_get, mcp_with_credentials):
        # First response → search_files()
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            "files": [
                {
                    "parents": ["1PGDp_zKKUs1EhZ7w1qWwNPFUcisFsZow"],
                    "id": "1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA",
                    "name": "test_environment",
                    "mimeType": "application/vnd.google-apps.folder",
                }
            ]
        }
        # Second response → actual file download
        mock_download_response = MagicMock()
        mock_download_response.status_code = 403
        mock_download_response.json.return_value = {
            "error": "Insufficient permissions or not authorized."}

        mock_get.side_effect = [mock_search_response, mock_download_response]
        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_download_file")
        result = tool_fn(filename="test_environment")

        assert "error" in result
        assert "not authorized" in result["error"]

    @patch("httpx.Client.get")
    def test_download_file_missing_file(self, mock_get, mcp_with_credentials):
         # First response → search_files()
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {"files": []}

        mock_get.return_value = mock_search_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_download_file")
        result = tool_fn(filename="")

        assert "error" in result
        assert "File not found" in result["error"]

    @patch("httpx.Client.patch")
    @patch("httpx.Client.get")
    def test_move_file(self, mock_get, mock_patch, mcp_with_credentials):
        # First response → search_files()
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            "files": [
                {
                    "parents": ["1PGDp_zKKUs1EhZ7w1qWwNPFUcisFsZow"],
                    "id": "1mEf-E7n8ZsFbr7qHKZRkyyxU7rKJQkjUSf5s580DcVg",
                    "name": "test_file.md",
                    "mimeType": "text/markdown",
                }
            ]
        }
        # second response → search_files()
        mock_foldersearch_response = MagicMock()
        mock_foldersearch_response.status_code = 200
        mock_foldersearch_response.json.return_value = {
            "files": [{ "parents": ["1PGDp_zKKUs1EhZ7w1qWwNPFUcisFsZow"],
                       "id": "1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA","name":
                       "test_environment","mimeType": "application/vnd.google-apps.folder"}]
        }
        mock_get.side_effect = [mock_search_response, mock_foldersearch_response]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "1mEf-E7n8ZsFbr7qHKZRkyyxU7rKJQkjUSf5s580DcVg",
                                           "name": "test_file.md",
                                           "parents": ["1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA"]}

        mock_patch.return_value = mock_response
        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_move_file")
        result = tool_fn(filename="test_file.md", folder="test_environment")

        assert result["name"] == "test_file.md"
        assert result["parents"][0] == "1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA"

    @patch("httpx.Client.get")
    def test_move_file_folder_missing(self, mock_get, mcp_with_credentials):
        # First response → search_files()
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            "files": [{ "parents": ["1PGDp_zKKUs1EhZ7w1qWwNPFUcisFsZow"],
                        "id": "1mEf-E7n8ZsFbr7qHKZRkyyxU7rKJQkjUSf5s580DcVg",
                        "name": "test_file.md","mimeType": "text/markdown"}]}
        # second response → search_files()
        mock_foldersearch_response = MagicMock()
        mock_foldersearch_response.status_code = 200
        mock_foldersearch_response.json.return_value = {
            "files": []
        }
        mock_get.side_effect = [mock_search_response, mock_foldersearch_response]

        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_move_file")
        result = tool_fn(filename="test_file.md", folder="")

        assert "error" in result
        assert "Folder not found" in result["error"]

    @patch("httpx.Client.patch")
    @patch("httpx.Client.get")
    def test_delete_file(self, mock_get, mock_patch, mcp_with_credentials):
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            "files": [{ "parents": ["1PGDp_zKKUs1EhZ7w1qWwNPFUcisFsZow"],
                        "id": "1mEf-E7n8ZsFbr7qHKZRkyyxU7rKJQkjUSf5s580DcVg",
                        "name": "test_file.md","mimeType": "text/markdown"}]
        }
        mock_get.return_value = mock_search_response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"kind": "drive#file",
                                           "id": "1mEf-E7n8ZsFbr7qHKZRkyyxU7rKJQkjUSf5s580DcVg",
                                           "name": "test_file.md", "mimeType": "text/markdown"}
        mock_patch.return_value = mock_response
        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_delete_file")
        result = tool_fn(filename="test_file.md")

        assert result["name"] == "test_file.md"
        assert result["mimeType"] == "text/markdown"

    @patch("httpx.Client.delete")
    def test_empty_trash(self, mock_delete, mcp_with_credentials):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.json.return_value = {"status": "success", "message": "Trash emptied"}
        mock_delete.return_value = mock_response

        test_fn = get_tool_fn(mcp_with_credentials, "google_drive_empty_trash")
        result = test_fn()

        assert result["status"] == "success"
        assert result["message"] == "Trash emptied"

    @patch("httpx.Client.delete")
    def test_empty_trash_failed(self, mock_delete, mcp_with_credentials):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"status": "failed", "message": "Trash not emptied"}
        mock_delete.return_value = mock_response

        test_fn = get_tool_fn(mcp_with_credentials, "google_drive_empty_trash")
        result = test_fn()

        assert result["status"] == "failed"
        assert result["message"] == "Trash not emptied"

    @patch("httpx.Client.post")
    @patch("httpx.Client.get")
    def test_share_file_link(self, mock_get, mock_post, mcp_with_credentials):
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            "files": [{"parents": ["1PGDp_zKKUs1EhZ7w1qWwNPFUcisFsZow"],
                       "id": "1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA",
                "name": "BUILDING_TOOLS.md","mimeType": "text/markdown"}]
        }
        mock_permission_response = MagicMock()
        mock_permission_response.status_code = 200
        mock_permission_response.json.return_value = {
            "kind": "drive#permission",
            "id": "anyoneWithLink",
            "type": "anyone", "role": "reader", "allowFileDiscovery": False}
        mock_post.return_value = mock_permission_response

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA",
            "name": "BUILDING_TOOLS.md",
            "webViewLink": "https://drive.google.com/file/d/1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA/view?usp=sharing"
        }
        mock_get.side_effect =[mock_search_response, mock_response]

        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_share_file_link")
        result = tool_fn(filename="BUILDING_TOOLS.md")

        assert result["id"] == "1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA"
        assert result["webViewLink"] == "https://drive.google.com/file/d/1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA/view?usp=sharing"

    @patch("httpx.Client.post")
    @patch("httpx.Client.get")
    def test_share_file_link_denied(self, mock_get, mock_post, mcp_with_credentials):
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            "files": [{ "parents": ["1PGDp_zKKUs1EhZ7w1qWwNPFUcisFsZow"],
                        "id": "1odpddoUIIIUU_skssoosoPPPPKL",
                        "name": "Other_Owner.md","mimeType": "text/markdown"}]
        }
        mock_get.return_value = mock_search_response
        mock_permission_response = MagicMock()
        mock_permission_response.status_code = 403
        mock_permission_response.json.return_value = {
            "error":"Insufficient permissions or not authorized."}

        mock_post.return_value = mock_permission_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_share_file_link")
        result = tool_fn(filename="Other_Owner.md")

        assert "error" in result
        assert "not authorized" in result["error"]


    @patch("httpx.Client.post")
    @patch("httpx.Client.get")
    def test_update_permissions(self, mock_get, mock_post, mcp_with_credentials):
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            "files": [{ "parents": ["1PGDp_zKKUs1EhZ7w1qWwNPFUcisFsZow"],
                        "id": "1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA",
                        "name": "BUILDING_TOOLS.md","mimeType": "text/markdown"}]
        }
        mock_get.return_value = mock_search_response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"kind": "drive#permission", "id": "anyoneWithLink",
                                           "type": "anyone","role": "reader",
                                           "allowFileDiscovery": False}
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_update_permissions")
        result = tool_fn(filename="BUILDING_TOOLS.md", p_type=None, respondent=None, role=None)

        assert result["kind"] == "drive#permission"
        assert result["type"] == "anyone"
        assert result["role"] == "reader"

    @patch("httpx.Client.patch")
    @patch("httpx.Client.post")
    @patch("httpx.Client.get")
    def test_update_permissions_role(self, mock_get, mock_post, mock_patch, mcp_with_credentials):
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            "files": [{ "parents": ["1PGDp_zKKUs1EhZ7w1qWwNPFUcisFsZow"],
                        "id": "1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA",
                        "name": "BUILDING_TOOLS.md","mimeType": "text/markdown"}]}
        mock_get.return_value = mock_search_response

        mock_permission_response = MagicMock()
        mock_permission_response.status_code = 200
        mock_permission_response.json.return_value = {"kind": "drive#permission",
        "id": "16250840978345559332", "type": "user", "role": "reader"}
        mock_post.return_value = mock_permission_response

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"kind": "drive#permission",
                                           "id": "16250840978345559332",
                                           "type": "user", "role": "writer"}
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_update_permissions")
        result = tool_fn(filename="BUILDING_TOOLS.md", p_type="user"
                         , respondent="personX@gmail.com", role="writer")

        assert result["kind"] == "drive#permission"
        assert result["type"] == "user"
        assert result["role"] == "writer"

    @patch("httpx.Client.post")
    @patch("httpx.Client.get")
    def test_update_permissions_wrong_query(self, mock_get, mock_post, mcp_with_credentials):
        mock_search_response = MagicMock()
        mock_search_response.status_code = 200
        mock_search_response.json.return_value = {
            "files": [{ "parents": ["1PGDp_zKKUs1EhZ7w1qWwNPFUcisFsZow"],
                       "id": "1lxsJlm9ilBqqPkEwB9RQ852C3yVcCZFA",
                        "name": "BUILDING_TOOLS.md","mimeType": "text/markdown"}]
        }
        mock_get.return_value = mock_search_response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": { "message": "Bad Request"}}
        mock_post.return_value = mock_response

        tool_fn = get_tool_fn(mcp_with_credentials, "google_drive_update_permissions")
        result = tool_fn(filename="BUILDING_TOOLS.md", p_type="usr", respondent="p@gmail.com"
                         , role=" ")

        assert "error" in result
        assert "Bad Request" in result["error"]
