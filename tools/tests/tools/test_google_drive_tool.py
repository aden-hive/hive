"""Tests for google_drive_tool — Google Drive API v3 integration."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.google_drive_tool.google_drive_tool import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    """Register and return all Google Drive tool functions."""
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestDriveListFiles:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["drive_list_files"]()
        assert "error" in result
        assert "GOOGLE_DRIVE_ACCESS_TOKEN" in result["error"]

    def test_success(self, tool_fns):
        mock_json = {
            "files": [
                {
                    "id": "f1",
                    "name": "a.txt",
                    "mimeType": "text/plain",
                    "size": "10",
                    "modifiedTime": "2024-01-01T00:00:00Z",
                    "webViewLink": "https://docs.google.com/...",
                }
            ],
            "nextPageToken": None,
        }
        with (
            patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}),
            patch(
                "aden_tools.tools.google_drive_tool.google_drive_tool.httpx.request",
            ) as mock_req,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"{}"
            mock_resp.json.return_value = mock_json
            mock_req.return_value = mock_resp
            result = tool_fns["drive_list_files"](folder_id="", page_size=10)

        assert result["folder_id"] == "root"
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "a.txt"


class TestDriveSearchFiles:
    def test_empty_query(self, tool_fns):
        with patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}):
            result = tool_fns["drive_search_files"](query="  ")
        assert "error" in result

    def test_success(self, tool_fns):
        mock_json = {
            "files": [{"id": "x", "name": "doc", "mimeType": "application/pdf"}],
        }
        with (
            patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}),
            patch(
                "aden_tools.tools.google_drive_tool.google_drive_tool.httpx.request",
            ) as mock_req,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_json
            mock_req.return_value = mock_resp
            result = tool_fns["drive_search_files"](query="budget")

        assert result["query"] == "budget"
        assert len(result["files"]) == 1


class TestDriveGetFileMetadata:
    def test_invalid_file_id(self, tool_fns):
        with patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}):
            result = tool_fns["drive_get_file_metadata"](file_id="bad/id")
        assert "error" in result


class TestDriveUploadFile:
    def test_missing_name(self, tool_fns):
        with patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}):
            result = tool_fns["drive_upload_file"](name="  ", content="hi")
        assert "error" in result

    def test_multipart_success(self, tool_fns):
        with (
            patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}),
            patch(
                "aden_tools.tools.google_drive_tool.google_drive_tool.httpx.post",
            ) as mock_post,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "id": "newid",
                "name": "n.txt",
                "mimeType": "text/plain",
                "webViewLink": "https://drive.google.com/...",
            }
            mock_post.return_value = mock_resp
            result = tool_fns["drive_upload_file"](
                name="n.txt",
                content="body",
                folder_id="parent1",
            )

        assert result.get("status") == "uploaded"
        assert result["id"] == "newid"
        mock_post.assert_called_once()
        call_kw = mock_post.call_args.kwargs
        assert "multipart/related" in call_kw["headers"]["Content-Type"]


class TestDriveCreateFolder:
    def test_success(self, tool_fns):
        with (
            patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}),
            patch(
                "aden_tools.tools.google_drive_tool.google_drive_tool.httpx.request",
            ) as mock_req,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "id": "fold",
                "name": "Reports",
                "webViewLink": "https://...",
            }
            mock_req.return_value = mock_resp
            result = tool_fns["drive_create_folder"](name="Reports")

        assert result["status"] == "created"
        assert result["id"] == "fold"


class TestDriveDeleteFile:
    def test_success(self, tool_fns):
        with (
            patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}),
            patch(
                "aden_tools.tools.google_drive_tool.google_drive_tool.httpx.request",
            ) as mock_req,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 204
            mock_resp.content = b""
            mock_req.return_value = mock_resp
            result = tool_fns["drive_delete_file"](file_id="abc123")

        assert result["status"] == "deleted"


class TestDriveShareFile:
    def test_invalid_role(self, tool_fns):
        with patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}):
            result = tool_fns["drive_share_file"](
                file_id="x",
                role="admin",
                share_type="user",
                email_address="a@b.com",
            )
        assert "error" in result

    def test_user_requires_email(self, tool_fns):
        with patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}):
            result = tool_fns["drive_share_file"](
                file_id="x",
                role="reader",
                share_type="user",
                email_address="",
            )
        assert "error" in result


class TestDriveCopyAndMove:
    def test_copy_success(self, tool_fns):
        with (
            patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}),
            patch(
                "aden_tools.tools.google_drive_tool.google_drive_tool.httpx.request",
            ) as mock_req,
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"id": "copy1", "name": "Copy of A"}
            mock_req.return_value = mock_resp
            result = tool_fns["drive_copy_file"](file_id="src")

        assert result.get("id") == "copy1"

    def test_move_missing_parents(self, tool_fns):
        with patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}):
            result = tool_fns["drive_move_file"](
                file_id="f",
                new_parent_id="",
                previous_parent_id="p",
            )
        assert "error" in result


class TestDriveDownloadBinary:
    def test_binary_base64(self, tool_fns):
        meta = {"id": "f1", "name": "x.bin", "mimeType": "application/octet-stream"}
        with (
            patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}),
            patch(
                "aden_tools.tools.google_drive_tool.google_drive_tool.httpx.request",
            ) as mock_req,
            patch(
                "aden_tools.tools.google_drive_tool.google_drive_tool.httpx.get",
            ) as mock_get,
        ):
            meta_resp = MagicMock()
            meta_resp.status_code = 200
            meta_resp.json.return_value = meta

            dl_resp = MagicMock()
            dl_resp.status_code = 200
            dl_resp.content = b"\xff\x00"

            mock_req.return_value = meta_resp
            mock_get.return_value = dl_resp

            result = tool_fns["drive_get_file"](file_id="f1")

        assert result["encoding"] == "base64"
        assert result["content_type"] == "application/octet-stream"


class TestDriveGetGoogleDoc:
    def test_export_default_mime(self, tool_fns):
        meta = {
            "id": "d1",
            "name": "Doc",
            "mimeType": "application/vnd.google-apps.document",
        }
        with (
            patch.dict("os.environ", {"GOOGLE_DRIVE_ACCESS_TOKEN": "tok"}),
            patch(
                "aden_tools.tools.google_drive_tool.google_drive_tool.httpx.request",
            ) as mock_req,
            patch(
                "aden_tools.tools.google_drive_tool.google_drive_tool.httpx.get",
            ) as mock_get,
        ):
            meta_resp = MagicMock()
            meta_resp.status_code = 200
            meta_resp.json.return_value = meta

            ex_resp = MagicMock()
            ex_resp.status_code = 200
            ex_resp.content = b"hello doc"

            mock_req.return_value = meta_resp
            mock_get.return_value = ex_resp

            result = tool_fns["drive_get_file"](file_id="d1")

        assert result["encoding"] == "text"
        assert "hello doc" in result["content"]
        export_url = mock_get.call_args[0][0]
        assert "/export" in export_url
