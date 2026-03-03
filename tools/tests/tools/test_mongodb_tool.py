"""
Unit tests for the MongoDB Tool.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

# Corregido para coincidir con tu estructura de doble carpeta (igual a Wikipedia)
from aden_tools.tools.mongodb_tool.mongodb_tool import register_tools


@pytest.fixture
def mcp():
    return FastMCP("test-server")


@pytest.fixture
def tools(mcp):
    """Register the tools and return a dictionary of callable functions."""
    registered_tools = {}
    mock_mcp = MagicMock()

    def mock_tool(**kwargs):
        def decorator(f):
            registered_tools[f.__name__] = f
            return f

        return decorator

    mock_mcp.tool = mock_tool
    register_tools(mock_mcp)
    return registered_tools


@pytest.fixture(autouse=True)
def mock_env():
    with patch.dict("os.environ", {"MONGODB_URI": "mongodb://fake:fake@localhost:27017"}):
        yield


@pytest.fixture(autouse=True)
def reset_global_client():
    """
    Crucial: Resets the global MongoDB client in your file before and after each test.
    This prevents cross-test contamination due to the global connection pool.
    """
    import aden_tools.tools.mongodb_tool.mongodb_tool as mongo_module
    
    # Limpiamos la caché global antes del test
    mongo_module._global_mongo_client = None
    yield
    # Limpiamos la caché global después del test
    mongo_module._global_mongo_client = None


# La ruta EXACTA hacia donde está importado el MongoClient en tu archivo real
PATCH_TARGET = "aden_tools.tools.mongodb_tool.mongodb_tool.MongoClient"


def test_mongodb_ping_database_success(tools):
    tool_func = tools["mongodb_ping_database"]

    with patch(PATCH_TARGET) as mock_mongo_class:
        mock_client_instance = MagicMock()
        mock_client_instance.admin.command.return_value = {"ok": 1}
        mock_mongo_class.return_value = mock_client_instance

        result = tool_func()

        assert result["success"] is True
        assert "Successfully connected" in result["message"]
        mock_client_instance.admin.command.assert_called_once_with('ping')


def test_mongodb_insert_document_success(tools):
    tool_func = tools["mongodb_insert_document"]

    with patch(PATCH_TARGET) as mock_mongo_class:
        mock_collection = MagicMock()
        mock_collection.insert_one.return_value.inserted_id = "507f1f77bcf86cd799439011"
        mock_mongo_class.return_value.__getitem__.return_value.__getitem__.return_value = mock_collection

        doc_json = '{"name": "Test User", "role": "admin"}'
        result = tool_func(database="test_db", collection="test_col", document_json=doc_json)

        assert result["success"] is True
        assert result["inserted_id"] == "507f1f77bcf86cd799439011"
        mock_collection.insert_one.assert_called_once_with({"name": "Test User", "role": "admin"})


def test_mongodb_insert_invalid_json(tools):
    tool_func = tools["mongodb_insert_document"]

    result = tool_func(database="test_db", collection="test_col", document_json="this is not json")

    assert "error" in result
    assert "Invalid JSON format" in result["error"]


def test_mongodb_find_document_success(tools):
    tool_func = tools["mongodb_find_document"]

    with patch(PATCH_TARGET) as mock_mongo_class:
        mock_collection = MagicMock()
        mock_cursor = [{"_id": "507f191e810c19729de860ea", "name": "Test User"}]
        mock_collection.find.return_value.limit.return_value = mock_cursor
        mock_mongo_class.return_value.__getitem__.return_value.__getitem__.return_value = mock_collection

        query_json = '{"name": "Test User"}'
        result = tool_func(database="test_db", collection="test_col", query_json=query_json, limit=5)

        assert result["success"] is True
        assert result["count"] == 1
        assert result["data"][0]["name"] == "Test User"
        mock_collection.find.assert_called_once_with({"name": "Test User"})


def test_mongodb_missing_credentials(tools):
    tool_func = tools["mongodb_ping_database"]

    with patch.dict("os.environ", {}, clear=True):
        result = tool_func()

        assert "error" in result
        assert "MongoDB URI not configured" in result["error"]

def test_mongodb_list_collections_success(tools):
    tool_func = tools["mongodb_list_collections"]

    with patch(PATCH_TARGET) as mock_mongo_class:
        mock_db = MagicMock()
        mock_db.list_collection_names.return_value = ["users", "orders"]
        mock_mongo_class.return_value.__getitem__.return_value = mock_db

        result = tool_func(database="test_db")

        assert result["success"] is True
        assert "users" in result["collections"]
        assert "orders" in result["collections"]
        mock_db.list_collection_names.assert_called_once()


def test_mongodb_aggregate_success(tools):
    tool_func = tools["mongodb_aggregate"]

    with patch(PATCH_TARGET) as mock_mongo_class:
        mock_collection = MagicMock()
        mock_cursor = [{"_id": "analytics_id", "total": 150}]
        mock_collection.aggregate.return_value = mock_cursor
        mock_mongo_class.return_value.__getitem__.return_value.__getitem__.return_value = mock_collection

        pipeline_json = '[{"$match": {"status": "A"}}, {"$group": {"_id": "$item", "total": {"$sum": "$amount"}}}]'
        result = tool_func(database="test_db", collection="test_col", pipeline_json=pipeline_json)

        assert result["success"] is True
        assert result["count"] == 1
        assert result["data"][0]["total"] == 150
        
        # Verify the pipeline was parsed from JSON to a Python list
        expected_pipeline = [{"$match": {"status": "A"}}, {"$group": {"_id": "$item", "total": {"$sum": "$amount"}}}]
        mock_collection.aggregate.assert_called_once_with(expected_pipeline)


def test_mongodb_aggregate_invalid_json(tools):
    tool_func = tools["mongodb_aggregate"]

    # Test bad JSON
    result_bad_json = tool_func(database="test_db", collection="test_col", pipeline_json="not a json array")
    assert "error" in result_bad_json
    assert "Invalid JSON format" in result_bad_json["error"]

    # Test valid JSON but not a list/array
    result_not_array = tool_func(database="test_db", collection="test_col", pipeline_json='{"$match": {"status": "A"}}')
    assert "error" in result_not_array
    assert "must be a JSON array" in result_not_array["error"]
