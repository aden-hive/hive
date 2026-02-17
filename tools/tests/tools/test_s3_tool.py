"""Tests for S3 tool (FastMCP).

Covers:
- Tool registration
- Credential handling (missing, adapter, env vars)
- Happy-path operations (upload, download, list, delete)
- S3 error handling (403 Forbidden, 404 Not Found)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastmcp import FastMCP

from aden_tools.tools.s3_tool import register_tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client_error(code: str, message: str = "mocked") -> ClientError:
    """Build a botocore ClientError for testing."""
    return ClientError(
        error_response={"Error": {"Code": code, "Message": message}},
        operation_name="TestOp",
    )


@pytest.fixture
def mcp() -> FastMCP:
    """Fresh FastMCP instance."""
    return FastMCP("test-s3")


def _register_and_get(mcp: FastMCP, credentials=None) -> dict:
    """Register tools and return a dict of {name: fn}."""
    register_tools(mcp, credentials=credentials)
    return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


# ---------------------------------------------------------------------------
# 1. Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify all S3 tools are registered with correct names."""

    EXPECTED_TOOLS = {
        "s3_upload",
        "s3_download",
        "s3_list",
        "s3_delete",
    }

    def test_all_tools_registered(self, mcp: FastMCP):
        register_tools(mcp)
        registered = set(mcp._tool_manager._tools.keys())
        assert self.EXPECTED_TOOLS == registered

    def test_tool_count(self, mcp: FastMCP):
        register_tools(mcp)
        assert len(mcp._tool_manager._tools) == 4


# ---------------------------------------------------------------------------
# 2. Credential handling
# ---------------------------------------------------------------------------


class TestCredentialHandling:
    """Missing / invalid credentials return {error, help} dicts."""

    def test_missing_credentials_returns_error_dict(self, mcp: FastMCP, monkeypatch):
        """No env vars and no adapter → error dict with 'help' key."""
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)

        tools = _register_and_get(mcp)
        result = tools["s3_upload"](
            bucket="b", key="k", data="hello"
        )

        assert "error" in result
        assert "help" in result
        assert result.get("success") is False

    def test_missing_credentials_download(self, mcp: FastMCP, monkeypatch):
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

        tools = _register_and_get(mcp)
        result = tools["s3_download"](bucket="b", key="k")

        assert "error" in result
        assert "help" in result

    def test_missing_credentials_list(self, mcp: FastMCP, monkeypatch):
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

        tools = _register_and_get(mcp)
        result = tools["s3_list"](bucket="b")

        assert "error" in result
        assert "help" in result

    def test_missing_credentials_delete(self, mcp: FastMCP, monkeypatch):
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

        tools = _register_and_get(mcp)
        result = tools["s3_delete"](bucket="b", key="k")

        assert "error" in result
        assert "help" in result

    def test_credentials_adapter_used(self, mcp: FastMCP):
        """CredentialStoreAdapter.get() is called for each key."""
        mock_creds = MagicMock()
        mock_creds.get.side_effect = lambda key: {
            "aws_access_key_id": "AKID",
            "aws_secret_access_key": "SECRET",
            "aws_region": "us-west-2",
            "aws_session_token": None,
        }.get(key)

        with patch("aden_tools.tools.s3_tool.s3_tool.S3Storage") as MockStorage:
            mock_instance = MagicMock()
            mock_instance.upload_file.return_value = {"success": True}
            MockStorage.return_value = mock_instance

            tools = _register_and_get(mcp, credentials=mock_creds)
            result = tools["s3_upload"](bucket="b", key="k", data="hi")

        assert result["success"] is True
        mock_creds.get.assert_any_call("aws_access_key_id")
        mock_creds.get.assert_any_call("aws_secret_access_key")


# ---------------------------------------------------------------------------
# 3. Happy-path operations
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Each operation succeeds when the S3 client is properly mocked."""

    @pytest.fixture
    def tools(self, mcp: FastMCP):
        """Register tools with a mocked S3Storage."""
        with patch("aden_tools.tools.s3_tool.s3_tool._get_s3_client") as mock_get:
            storage = MagicMock()
            storage.upload_file.return_value = {
                "success": True, "bucket": "b", "key": "k",
            }
            storage.download_file.return_value = {
                "success": True, "content": "hello", "bucket": "b", "key": "k",
            }
            storage.list_objects.return_value = {
                "success": True, "objects": [{"key": "a.txt"}], "folders": [],
            }
            storage.delete_object.return_value = {
                "success": True, "bucket": "b", "key": "k",
            }
            mock_get.return_value = storage
            yield _register_and_get(mcp)

    def test_upload_success(self, tools):
        result = tools["s3_upload"](bucket="b", key="k", data="hello")
        assert result["success"] is True
        assert result["bucket"] == "b"

    def test_download_success(self, tools):
        result = tools["s3_download"](bucket="b", key="k")
        assert result["success"] is True
        assert result["content"] == "hello"

    def test_list_success(self, tools):
        result = tools["s3_list"](bucket="b")
        assert result["success"] is True
        assert len(result["objects"]) == 1

    def test_delete_success(self, tools):
        result = tools["s3_delete"](bucket="b", key="k")
        assert result["success"] is True


# ---------------------------------------------------------------------------
# 4. S3 error handling (403, 404)
# ---------------------------------------------------------------------------


class TestS3ErrorHandling:
    """ClientError from boto3 is caught and returned as a dict."""

    @pytest.fixture
    def tools(self, mcp: FastMCP):
        with patch("aden_tools.tools.s3_tool.s3_tool._get_s3_client") as mock_get:
            storage = MagicMock()
            mock_get.return_value = storage
            self._storage = storage
            yield _register_and_get(mcp)

    def test_403_forbidden_upload(self, tools):
        self._storage.upload_file.side_effect = _make_client_error("AccessDenied")
        result = tools["s3_upload"](bucket="b", key="k", data="x")
        assert result["success"] is False
        assert "AccessDenied" in str(result.get("error", ""))

    def test_403_forbidden_download(self, tools):
        self._storage.download_file.side_effect = _make_client_error("AccessDenied")
        result = tools["s3_download"](bucket="b", key="k")
        assert result["success"] is False

    def test_403_forbidden_list(self, tools):
        self._storage.list_objects.side_effect = _make_client_error("AccessDenied")
        result = tools["s3_list"](bucket="b")
        assert result["success"] is False

    def test_403_forbidden_delete(self, tools):
        self._storage.delete_object.side_effect = _make_client_error("AccessDenied")
        result = tools["s3_delete"](bucket="b", key="k")
        assert result["success"] is False

    def test_404_not_found_download(self, tools):
        self._storage.download_file.side_effect = _make_client_error("NoSuchKey")
        result = tools["s3_download"](bucket="b", key="missing.txt")
        assert result["success"] is False
        assert "NoSuchKey" in str(result.get("error", ""))

    def test_404_not_found_delete(self, tools):
        self._storage.delete_object.side_effect = _make_client_error("NoSuchKey")
        result = tools["s3_delete"](bucket="b", key="missing.txt")
        assert result["success"] is False

    def test_no_such_bucket_list(self, tools):
        self._storage.list_objects.side_effect = _make_client_error("NoSuchBucket")
        result = tools["s3_list"](bucket="nonexistent")
        assert result["success"] is False
        assert "NoSuchBucket" in str(result.get("error", ""))