"""Tests for aws_s3_tool - S3 object storage operations."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.aws_s3_tool.aws_s3_tool import register_tools

ENV = {
    "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
    "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "AWS_REGION": "us-east-1",
}


def _mock_resp(text="", status_code=200, headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.content = text.encode() if isinstance(text, str) else text
    resp.headers = headers or {}
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


LIST_BUCKETS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ListAllMyBucketsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Buckets>
    <Bucket><Name>my-bucket</Name><CreationDate>2024-01-15T10:30:00.000Z</CreationDate></Bucket>
    <Bucket><Name>other-bucket</Name><CreationDate>2024-02-01T08:00:00.000Z</CreationDate></Bucket>
  </Buckets>
</ListAllMyBucketsResult>"""

LIST_OBJECTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <Name>my-bucket</Name>
  <IsTruncated>false</IsTruncated>
  <Contents>
    <Key>file1.txt</Key><Size>1024</Size><LastModified>2024-01-15T10:30:00.000Z</LastModified>
  </Contents>
  <Contents>
    <Key>file2.json</Key><Size>256</Size><LastModified>2024-02-01T08:00:00.000Z</LastModified>
  </Contents>
  <CommonPrefixes><Prefix>images/</Prefix></CommonPrefixes>
</ListBucketResult>"""


class TestS3ListBuckets:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["s3_list_buckets"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.aws_s3_tool.aws_s3_tool.httpx.get",
                return_value=_mock_resp(LIST_BUCKETS_XML),
            ),
        ):
            result = tool_fns["s3_list_buckets"]()

        assert result["count"] == 2
        assert result["buckets"][0]["name"] == "my-bucket"


class TestS3ListObjects:
    def test_missing_bucket(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["s3_list_objects"](bucket="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.aws_s3_tool.aws_s3_tool.httpx.get",
                return_value=_mock_resp(LIST_OBJECTS_XML),
            ),
        ):
            result = tool_fns["s3_list_objects"](bucket="my-bucket")

        assert result["count"] == 2
        assert result["objects"][0]["key"] == "file1.txt"
        assert result["objects"][0]["size"] == 1024
        assert result["common_prefixes"] == ["images/"]


class TestS3GetObject:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["s3_get_object"](bucket="", key="")
        assert "error" in result

    def test_successful_get_text(self, tool_fns):
        resp = _mock_resp(
            "Hello, world!",
            headers={
                "content-type": "text/plain",
                "content-length": "13",
                "etag": '"abc"',
                "last-modified": "Wed, 15 Jan 2024",
            },
        )
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.aws_s3_tool.aws_s3_tool.httpx.get", return_value=resp),
        ):
            result = tool_fns["s3_get_object"](bucket="my-bucket", key="file.txt")

        assert result["content"] == "Hello, world!"
        assert result["content_type"] == "text/plain"


class TestS3PutObject:
    def test_missing_content(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["s3_put_object"](bucket="my-bucket", key="file.txt", content="")
        assert "error" in result

    def test_successful_put(self, tool_fns):
        resp = _mock_resp("", headers={"etag": '"abc123"'})
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.aws_s3_tool.aws_s3_tool.httpx.put", return_value=resp),
        ):
            result = tool_fns["s3_put_object"](
                bucket="my-bucket", key="new-file.txt", content="Hello!"
            )

        assert result["result"] == "uploaded"
        assert result["key"] == "new-file.txt"
        assert result["size"] == 6


class TestS3DeleteObject:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["s3_delete_object"](bucket="", key="")
        assert "error" in result

    def test_successful_delete(self, tool_fns):
        resp = _mock_resp("", status_code=204)
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.aws_s3_tool.aws_s3_tool.httpx.delete", return_value=resp),
        ):
            result = tool_fns["s3_delete_object"](bucket="my-bucket", key="old-file.txt")

        assert result["result"] == "deleted"
