"""Tests for vector database tool (chromadb)."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.vector_db_tool import register_tools


@pytest.fixture
def vector_search_fn(mcp: FastMCP):
    """Register and return the vector_search tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["vector_search"].fn


@pytest.fixture
def vector_upsert_fn(mcp: FastMCP):
    """Register and return the vector_upsert tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["vector_upsert"].fn


class TestVectorSearch:
    """Tests for vector_search tool."""

    @patch("aden_tools.tools.vector_db_tool.chromadb.ChromaDBStore")
    def test_search_success(self, mock_store_class, vector_search_fn, monkeypatch):
        """Successful search returns results."""
        monkeypatch.setenv("CHROMA_PERSIST_DIR", "./test_chroma")
        monkeypatch.setenv("CHROMA_COLLECTION_NAME", "test_collection")

        mock_store = MagicMock()
        mock_store.search.return_value = {
            "success": True,
            "results": [
                {"id": "doc1", "text": "Test document", "distance": 0.1},
                {"id": "doc2", "text": "Another doc", "distance": 0.3},
            ],
        }
        mock_store_class.return_value = mock_store

        result = vector_search_fn(query="test query", top_k=5)

        assert result["success"] is True
        assert "results" in result
        assert len(result["results"]) == 2
        mock_store.search.assert_called_once_with("test query", top_k=5)

    @patch("aden_tools.tools.vector_db_tool.chromadb.ChromaDBStore")
    def test_search_no_env_config(self, mock_store_class, vector_search_fn, monkeypatch):
        """Search without env config uses defaults."""
        monkeypatch.delenv("CHROMA_PERSIST_DIR", raising=False)
        monkeypatch.delenv("CHROMA_COLLECTION_NAME", raising=False)

        mock_store = MagicMock()
        mock_store.search.return_value = {"success": True, "results": []}
        mock_store_class.return_value = mock_store

        result = vector_search_fn(query="test")

        assert result["success"] is True
        # Default collection name should be used
        mock_store_class.assert_called_once()

    @patch("aden_tools.tools.vector_db_tool.chromadb.ChromaDBStore")
    def test_search_with_filters(self, mock_store_class, vector_search_fn, monkeypatch):
        """Search with metadata filters."""
        monkeypatch.setenv("CHROMA_PERSIST_DIR", "./test_chroma")
        monkeypatch.setenv("CHROMA_COLLECTION_NAME", "test_collection")

        mock_store = MagicMock()
        mock_store.search.return_value = {"success": True, "results": []}
        mock_store_class.return_value = mock_store

        result = vector_search_fn(
            query="test",
            top_k=3,
            filters={"type": "github_issue", "state": "open"},
        )

        assert result["success"] is True
        call_kwargs = mock_store.search.call_args.kwargs
        assert call_kwargs.get("top_k") == 3
        assert call_kwargs.get("filters") == {"type": "github_issue", "state": "open"}

    @patch("aden_tools.tools.vector_db_tool.chromadb.ChromaDBStore")
    def test_search_error_handling(self, mock_store_class, vector_search_fn, monkeypatch):
        """Search handles errors gracefully."""
        monkeypatch.setenv("CHROMA_PERSIST_DIR", "./test_chroma")
        monkeypatch.setenv("CHROMA_COLLECTION_NAME", "test_collection")

        mock_store = MagicMock()
        mock_store.search.side_effect = Exception("ChromaDB connection error")
        mock_store_class.return_value = mock_store

        result = vector_search_fn(query="test")

        assert "error" in result
        assert "ChromaDB connection error" in result["error"]


class TestVectorUpsert:
    """Tests for vector_upsert tool."""

    @patch("aden_tools.tools.vector_db_tool.chromadb.ChromaDBStore")
    def test_upsert_success(self, mock_store_class, vector_upsert_fn, monkeypatch):
        """Successful upsert returns success."""
        monkeypatch.setenv("CHROMA_PERSIST_DIR", "./test_chroma")
        monkeypatch.setenv("CHROMA_COLLECTION_NAME", "test_collection")

        mock_store = MagicMock()
        mock_store.upsert.return_value = {"success": True, "id": "doc123"}
        mock_store_class.return_value = mock_store

        result = vector_upsert_fn(
            id="doc123",
            text="Test document content",
            metadata={"type": "github_issue", "number": 42},
        )

        assert result["success"] is True
        assert result["id"] == "doc123"
        mock_store.upsert.assert_called_once_with(
            id="doc123",
            text="Test document content",
            metadata={"type": "github_issue", "number": 42},
        )

    @patch("aden_tools.tools.vector_db_tool.chromadb.ChromaDBStore")
    def test_upsert_without_metadata(self, mock_store_class, vector_upsert_fn, monkeypatch):
        """Upsert without metadata works."""
        monkeypatch.setenv("CHROMA_PERSIST_DIR", "./test_chroma")
        monkeypatch.setenv("CHROMA_COLLECTION_NAME", "test_collection")

        mock_store = MagicMock()
        mock_store.upsert.return_value = {"success": True, "id": "doc456"}
        mock_store_class.return_value = mock_store

        result = vector_upsert_fn(id="doc456", text="Content only")

        assert result["success"] is True
        mock_store.upsert.assert_called_once()

    @patch("aden_tools.tools.vector_db_tool.chromadb.ChromaDBStore")
    def test_upsert_error_handling(self, mock_store_class, vector_upsert_fn, monkeypatch):
        """Upsert handles errors gracefully."""
        monkeypatch.setenv("CHROMA_PERSIST_DIR", "./test_chroma")
        monkeypatch.setenv("CHROMA_COLLECTION_NAME", "test_collection")

        mock_store = MagicMock()
        mock_store.upsert.side_effect = Exception("Invalid metadata format")
        mock_store_class.return_value = mock_store

        result = vector_upsert_fn(id="doc999", text="Test")

        assert "error" in result
        assert "Invalid metadata format" in result["error"]
