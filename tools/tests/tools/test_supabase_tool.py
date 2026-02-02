"""Tests for Supabase tool."""

import os
from unittest.mock import MagicMock, mock_open, patch

import httpx
import pytest

from aden_tools.tools.supabase_tool.supabase_tool import SupabaseClient


class TestSupabaseClient:
    """Test Suite for SupabaseClient."""

    @pytest.fixture
    def client(self):
        """Standard client with dummy key."""
        return SupabaseClient(url="https://test.supabase.co", key="test-key")

    @patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.request")
    def test_init_headers(self, mock_request, client):
        """Test that headers are correctly set."""
        assert client.headers["apikey"] == "test-key"
        assert client.headers["Authorization"] == "Bearer test-key"
        assert client.headers["Content-Type"] == "application/json"

    @patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.request")
    def test_select(self, mock_request, client):
        """Test select query construction."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers.get.return_value = "application/json"
        mock_response.json.return_value = [{"id": 1}]
        mock_request.return_value = mock_response

        client.select(
            table="users",
            columns="id,name",
            filters={"age": "gt.20"},
            limit=50,
            order="name.asc"
        )

        args = mock_request.call_args
        assert args[0][0] == "GET"
        assert args[0][1] == "https://test.supabase.co/rest/v1/users"

        params = args.kwargs["params"]
        assert params["select"] == "id,name"
        assert params["age"] == "gt.20"
        assert params["limit"] == 50
        assert params["order"] == "name.asc"

        headers = args.kwargs["headers"]
        assert headers["apikey"] == "test-key"

    @patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.request")
    def test_insert(self, mock_request, client):
        """Test insert request."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.headers.get.return_value = "application/json"
        mock_response.json.return_value = [{"id": 1}]
        mock_request.return_value = mock_response

        data = {"name": "Test"}
        client.insert("users", data, upsert=True)

        args = mock_request.call_args
        assert args[0][0] == "POST"
        assert args[0][1] == "https://test.supabase.co/rest/v1/users"
        assert args.kwargs["json"] == data

        headers = args.kwargs["headers"]
        assert "return=representation" in headers["Prefer"]
        assert "resolution=merge-duplicates" in headers["Prefer"]

    @patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.request")
    def test_update(self, mock_request, client):
        """Test update request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers.get.return_value = "application/json"
        mock_request.return_value = mock_response

        client.update("users", {"name": "New"}, {"id": "eq.1"})

        args = mock_request.call_args
        assert args[0][0] == "PATCH"
        assert args.kwargs["json"] == {"name": "New"}
        assert args.kwargs["params"] == {"id": "eq.1"}

    @patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.request")
    def test_delete(self, mock_request, client):
        """Test delete request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers.get.return_value = "application/json"
        mock_request.return_value = mock_response

        client.delete("users", {"id": "eq.1"})

        args = mock_request.call_args
        assert args[0][0] == "DELETE"
        assert args.kwargs["params"] == {"id": "eq.1"}

    @patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.request")
    def test_upload_file(self, mock_request, client):
        """Test file upload."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers.get.return_value = "application/json"
        mock_response.json.return_value = [{"Key": "bucket/path"}
        ]
        mock_request.return_value = mock_response

        with patch("builtins.open", mock_open(read_data=b"content")):
            with patch("os.path.exists", return_value=True):
                client.upload_file("mybucket", "folder/file.txt", "/tmp/file.txt")

        args = mock_request.call_args
        assert args[0][0] == "POST"
        assert args[0][1] == "https://test.supabase.co/storage/v1/object/mybucket/folder/file.txt"
        assert args.kwargs["content"] == b"content"
        assert args.kwargs["headers"]["Content-Type"] == "text/plain"

    @patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.request")
    def test_error_handling(self, mock_request, client):
        """Test error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"message": "Bad Request"}
        # setup raises for failure
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request", request=MagicMock(), response=mock_response
        )
        mock_request.return_value = mock_response

        result = client.select("users")
        assert result["error"] == "Bad Request"
        assert result["code"] == 400

    @patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.request")
    def test_auth_error(self, mock_request, client):
        """Test 401 handling."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_request.return_value = mock_response

        result = client.select("users")
        assert "Unauthorized" in result["error"]

    def test_init_missing_creds(self):
        """Test initialization failure when credentials are missing."""
        # Unset env vars just in case
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Supabase URL and Key are required"):
                SupabaseClient()

    @patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.request")
    def test_download_file(self, mock_request, client):
        """Test file download."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers.get.return_value = "application/octet-stream"
        mock_response.content = b"file-content"
        mock_request.return_value = mock_response

        with patch("builtins.open", mock_open()) as mock_file:
            # Need to mock os.makedirs to avoid actual filesystem access
            with patch("os.makedirs"):
                result = client.download_file("mybucket", "folder/doc.pdf", "/tmp/doc.pdf")

            assert result["status"] == "success"
            assert result["path"] == "/tmp/doc.pdf"
            mock_file.assert_called_with("/tmp/doc.pdf", "wb")
            mock_file().write.assert_called_with(b"file-content")

        args = mock_request.call_args
        assert args[0][0] == "GET"
        assert args[0][1] == "https://test.supabase.co/storage/v1/object/mybucket/folder/doc.pdf"

    def test_upload_file_not_found(self, client):
        """Test upload fails if local file doesn't exist."""
        with patch("os.path.exists", return_value=False):
            result = client.upload_file("bucket", "path", "/nonexistent.txt")
            assert "File not found" in result["error"]

    @patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.request")
    def test_network_error(self, mock_request, client):
        """Test handling of network connection errors."""
        mock_request.side_effect = httpx.RequestError("DNS probe finished nxdomain")

        result = client.select("users")
        assert "Network error" in result["error"]
        assert "DNS probe finished nxdomain" in result["error"]

    @patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.request")
    def test_unexpected_exception(self, mock_request, client):
        """Test handling of unexpected exceptions during request."""
        mock_request.side_effect = Exception("Software error")

        result = client.select("users")
        assert "Unexpected error" in result["error"]
        assert "Software error" in result["error"]

    @patch("aden_tools.tools.supabase_tool.supabase_tool.httpx.request")
    def test_download_write_error(self, mock_request, client):
        """Test download failure when writing to disk fails."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"data"
        mock_request.return_value = mock_response

        # Mock open to raise generic IOError
        with patch("builtins.open", side_effect=IOError("Disk full")):
            with patch("os.makedirs"):
                result = client.download_file("bucket", "path", "/tmp/file")

        assert "Failed to write file" in result["error"]
        assert "Disk full" in result["error"]
