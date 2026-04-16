"""Tests for cloudinary_tool - Image/video upload, management, and search."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.cloudinary_tool.cloudinary_tool import register_tools

ENV = {
    "CLOUDINARY_CLOUD_NAME": "test-cloud",
    "CLOUDINARY_API_KEY": "test-key",
    "CLOUDINARY_API_SECRET": "test-secret",
}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestCloudinaryUpload:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["cloudinary_upload"](file_url="https://example.com/img.jpg")
        assert "error" in result

    def test_missing_file_url(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["cloudinary_upload"](file_url="")
        assert "error" in result

    def test_successful_upload(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "public_id": "sample",
            "secure_url": "https://res.cloudinary.com/test-cloud/image/upload/sample.jpg",
            "format": "jpg",
            "resource_type": "image",
            "bytes": 12345,
            "width": 800,
            "height": 600,
            "created_at": "2024-01-01T00:00:00Z",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.cloudinary_tool.cloudinary_tool.httpx.post",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["cloudinary_upload"](file_url="https://example.com/img.jpg")

        assert result["public_id"] == "sample"
        assert result["format"] == "jpg"
        assert result["bytes"] == 12345


class TestCloudinaryListResources:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["cloudinary_list_resources"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "resources": [
                {
                    "public_id": "sample1",
                    "secure_url": "https://res.cloudinary.com/test-cloud/image/upload/sample1.jpg",
                    "format": "jpg",
                    "bytes": 5000,
                    "width": 400,
                    "height": 300,
                    "created_at": "2024-01-01T00:00:00Z",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.cloudinary_tool.cloudinary_tool.httpx.get", return_value=mock_resp),
        ):
            result = tool_fns["cloudinary_list_resources"]()

        assert result["count"] == 1
        assert result["resources"][0]["public_id"] == "sample1"


class TestCloudinaryGetResource:
    def test_missing_public_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["cloudinary_get_resource"](public_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "public_id": "sample1",
            "secure_url": "https://res.cloudinary.com/test-cloud/image/upload/sample1.jpg",
            "format": "jpg",
            "resource_type": "image",
            "bytes": 5000,
            "width": 400,
            "height": 300,
            "tags": ["nature"],
            "created_at": "2024-01-01T00:00:00Z",
            "status": "active",
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.cloudinary_tool.cloudinary_tool.httpx.get", return_value=mock_resp),
        ):
            result = tool_fns["cloudinary_get_resource"](public_id="sample1")

        assert result["public_id"] == "sample1"
        assert result["tags"] == ["nature"]


class TestCloudinaryDeleteResource:
    def test_missing_public_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["cloudinary_delete_resource"](public_id="")
        assert "error" in result

    def test_successful_delete(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": "ok"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.cloudinary_tool.cloudinary_tool.httpx.post",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["cloudinary_delete_resource"](public_id="sample1")

        assert result["result"] == "ok"
        assert result["public_id"] == "sample1"


class TestCloudinarySearch:
    def test_missing_expression(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["cloudinary_search"](expression="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "resources": [
                {
                    "public_id": "nature/sunset",
                    "secure_url": "https://res.cloudinary.com/test-cloud/image/upload/nature/sunset.jpg",
                    "format": "jpg",
                    "resource_type": "image",
                    "bytes": 8000,
                    "created_at": "2024-01-01T00:00:00Z",
                }
            ],
            "total_count": 1,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.cloudinary_tool.cloudinary_tool.httpx.post",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["cloudinary_search"](expression="resource_type:image AND tags=nature")

        assert result["total_count"] == 1
        assert result["resources"][0]["public_id"] == "nature/sunset"
