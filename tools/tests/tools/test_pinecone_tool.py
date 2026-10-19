"""Tests for pinecone_tool - Pinecone vector database operations."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.pinecone_tool.pinecone_tool import register_tools

ENV = {"PINECONE_API_KEY": "pc-test-key"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestPineconeListIndexes:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["pinecone_list_indexes"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"indexes": []}'
        mock_resp.json.return_value = {
            "indexes": [
                {
                    "name": "my-index",
                    "dimension": 1536,
                    "metric": "cosine",
                    "host": "my-index-abc123.svc.pinecone.io",
                    "vector_type": "dense",
                    "status": {"ready": True, "state": "Ready"},
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pinecone_tool.pinecone_tool.httpx.get", return_value=mock_resp),
        ):
            result = tool_fns["pinecone_list_indexes"]()

        assert len(result["indexes"]) == 1
        assert result["indexes"][0]["name"] == "my-index"
        assert result["indexes"][0]["dimension"] == 1536


class TestPineconeCreateIndex:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pinecone_create_index"](name="", dimension=0)
        assert "error" in result

    def test_successful_create(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.content = b'{"name": "new-idx"}'
        mock_resp.json.return_value = {
            "name": "new-idx",
            "dimension": 768,
            "metric": "cosine",
            "host": "new-idx-xyz.svc.pinecone.io",
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pinecone_tool.pinecone_tool.httpx.post", return_value=mock_resp),
        ):
            result = tool_fns["pinecone_create_index"](name="new-idx", dimension=768)

        assert result["status"] == "created"
        assert result["name"] == "new-idx"


class TestPineconeDescribeIndex:
    def test_missing_name(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pinecone_describe_index"](index_name="")
        assert "error" in result

    def test_successful_describe(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"name": "my-index"}'
        mock_resp.json.return_value = {
            "name": "my-index",
            "dimension": 1536,
            "metric": "cosine",
            "host": "my-index-abc.svc.pinecone.io",
            "vector_type": "dense",
            "status": {"ready": True, "state": "Ready"},
            "deletion_protection": "disabled",
            "spec": {"serverless": {"cloud": "aws", "region": "us-east-1"}},
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pinecone_tool.pinecone_tool.httpx.get", return_value=mock_resp),
        ):
            result = tool_fns["pinecone_describe_index"](index_name="my-index")

        assert result["name"] == "my-index"
        assert result["ready"] is True


class TestPineconeDeleteIndex:
    def test_missing_name(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pinecone_delete_index"](index_name="")
        assert "error" in result

    def test_successful_delete(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.content = b""
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pinecone_tool.pinecone_tool.httpx.delete", return_value=mock_resp),
        ):
            result = tool_fns["pinecone_delete_index"](index_name="old-index")

        assert result["status"] == "deleted"


class TestPineconeUpsertVectors:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pinecone_upsert_vectors"](index_host="", vectors=[])
        assert "error" in result

    def test_successful_upsert(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"upsertedCount": 2}'
        mock_resp.json.return_value = {"upsertedCount": 2}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pinecone_tool.pinecone_tool.httpx.post", return_value=mock_resp),
        ):
            result = tool_fns["pinecone_upsert_vectors"](
                index_host="my-index-abc.svc.pinecone.io",
                vectors=[
                    {"id": "v1", "values": [0.1, 0.2, 0.3]},
                    {"id": "v2", "values": [0.4, 0.5, 0.6]},
                ],
            )

        assert result["upserted_count"] == 2


class TestPineconeQueryVectors:
    def test_missing_vector_and_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pinecone_query_vectors"](index_host="host.io")
        assert "error" in result

    def test_successful_query(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"matches": []}'
        mock_resp.json.return_value = {
            "matches": [
                {"id": "v1", "score": 0.95, "metadata": {"topic": "AI"}},
                {"id": "v2", "score": 0.82, "metadata": {"topic": "ML"}},
            ],
            "namespace": "",
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pinecone_tool.pinecone_tool.httpx.post", return_value=mock_resp),
        ):
            result = tool_fns["pinecone_query_vectors"](
                index_host="my-index-abc.svc.pinecone.io",
                vector=[0.1, 0.2, 0.3],
                top_k=5,
            )

        assert len(result["matches"]) == 2
        assert result["matches"][0]["score"] == 0.95


class TestPineconeFetchVectors:
    def test_missing_ids(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pinecone_fetch_vectors"](index_host="host.io", ids=[])
        assert "error" in result

    def test_successful_fetch(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"vectors": {}}'
        mock_resp.json.return_value = {
            "vectors": {
                "v1": {"id": "v1", "values": [0.1, 0.2], "metadata": None},
            },
            "namespace": "",
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pinecone_tool.pinecone_tool.httpx.get", return_value=mock_resp),
        ):
            result = tool_fns["pinecone_fetch_vectors"](
                index_host="my-index-abc.svc.pinecone.io",
                ids=["v1"],
            )

        assert "v1" in result["vectors"]


class TestPineconeDeleteVectors:
    def test_missing_criteria(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pinecone_delete_vectors"](index_host="host.io")
        assert "error" in result

    def test_successful_delete(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"{}"
        mock_resp.json.return_value = {}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pinecone_tool.pinecone_tool.httpx.post", return_value=mock_resp),
        ):
            result = tool_fns["pinecone_delete_vectors"](
                index_host="my-index-abc.svc.pinecone.io",
                ids=["v1", "v2"],
            )

        assert result["status"] == "deleted"


class TestPineconeIndexStats:
    def test_missing_host(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pinecone_index_stats"](index_host="")
        assert "error" in result

    def test_successful_stats(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"namespaces": {}}'
        mock_resp.json.return_value = {
            "namespaces": {
                "": {"vectorCount": 100},
                "docs": {"vectorCount": 50},
            },
            "dimension": 1536,
            "totalVectorCount": 150,
            "metric": "cosine",
            "vectorType": "dense",
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pinecone_tool.pinecone_tool.httpx.post", return_value=mock_resp),
        ):
            result = tool_fns["pinecone_index_stats"](
                index_host="my-index-abc.svc.pinecone.io",
            )

        assert result["total_vector_count"] == 150
        assert result["namespaces"]["docs"]["vector_count"] == 50
