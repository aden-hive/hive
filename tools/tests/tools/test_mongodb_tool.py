"""Tests for mongodb_tool - Document CRUD and aggregation."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.mongodb_tool.mongodb_tool import register_tools

ENV = {
    "MONGODB_DATA_API_URL": "https://data.mongodb-api.com/app/test/endpoint/data/v1",
    "MONGODB_API_KEY": "test-api-key",
    "MONGODB_DATA_SOURCE": "Cluster0",
}


def _mock_resp(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = ""
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestMongodbFind:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["mongodb_find"](database="db", collection="col")
        assert "error" in result

    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["mongodb_find"](database="", collection="")
        assert "error" in result

    def test_invalid_filter_json(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["mongodb_find"](database="db", collection="col", filter="not json")
        assert "error" in result

    def test_successful_find(self, tool_fns):
        data = {"documents": [{"_id": "1", "name": "Alice"}, {"_id": "2", "name": "Bob"}]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.mongodb_tool.mongodb_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["mongodb_find"](database="mydb", collection="users")

        assert result["count"] == 2
        assert result["documents"][0]["name"] == "Alice"


class TestMongodbFindOne:
    def test_successful_find_one(self, tool_fns):
        data = {"document": {"_id": "1", "name": "Alice", "age": 30}}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.mongodb_tool.mongodb_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["mongodb_find_one"](database="mydb", collection="users", filter='{"name": "Alice"}')

        assert result["name"] == "Alice"
        assert result["age"] == 30

    def test_no_match(self, tool_fns):
        data = {"document": None}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.mongodb_tool.mongodb_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["mongodb_find_one"](database="mydb", collection="users", filter='{"name": "Nobody"}')

        assert "error" in result


class TestMongodbInsertOne:
    def test_missing_document(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["mongodb_insert_one"](database="db", collection="col", document="")
        assert "error" in result

    def test_successful_insert(self, tool_fns):
        data = {"insertedId": "abc123"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.mongodb_tool.mongodb_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["mongodb_insert_one"](
                database="mydb", collection="users", document='{"name": "Alice", "age": 30}'
            )

        assert result["result"] == "inserted"
        assert result["insertedId"] == "abc123"


class TestMongodbUpdateOne:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["mongodb_update_one"](database="db", collection="col", filter="", update="")
        assert "error" in result

    def test_successful_update(self, tool_fns):
        data = {"matchedCount": 1, "modifiedCount": 1}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.mongodb_tool.mongodb_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["mongodb_update_one"](
                database="mydb",
                collection="users",
                filter='{"name": "Alice"}',
                update='{"$set": {"age": 31}}',
            )

        assert result["matchedCount"] == 1
        assert result["modifiedCount"] == 1


class TestMongodbDeleteOne:
    def test_missing_filter(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["mongodb_delete_one"](database="db", collection="col", filter="")
        assert "error" in result

    def test_successful_delete(self, tool_fns):
        data = {"deletedCount": 1}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.mongodb_tool.mongodb_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["mongodb_delete_one"](database="mydb", collection="users", filter='{"name": "Alice"}')

        assert result["deletedCount"] == 1


class TestMongodbAggregate:
    def test_missing_pipeline(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["mongodb_aggregate"](database="db", collection="col", pipeline="")
        assert "error" in result

    def test_invalid_pipeline(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["mongodb_aggregate"](database="db", collection="col", pipeline='{"not": "array"}')
        assert "error" in result

    def test_successful_aggregate(self, tool_fns):
        data = {"documents": [{"_id": "active", "count": 5}, {"_id": "inactive", "count": 2}]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.mongodb_tool.mongodb_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["mongodb_aggregate"](
                database="mydb",
                collection="users",
                pipeline='[{"$group": {"_id": "$status", "count": {"$sum": 1}}}]',
            )

        assert result["count"] == 2
        assert result["documents"][0]["_id"] == "active"
