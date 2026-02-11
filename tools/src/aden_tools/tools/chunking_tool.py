"""
Chunking Tool - Split text into chunks for vector storage.

Logic extracted from vector_db_tool to avoid credential requirement.
"""

from __future__ import annotations

from fastmcp import FastMCP

from aden_tools.tools.vector_db_tool.chunking import chunk_text


def register_tools(mcp: FastMCP) -> None:
    """Register chunking tools with the MCP server."""

    @mcp.tool()
    def vector_db_chunk_text(
        text: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separator: str = "\n\n",
    ) -> dict:
        """
        Split text into chunks for efficient vector storage and retrieval.

        Args:
            text: Input text to chunk
            chunk_size: Maximum characters per chunk (default 1000)
            chunk_overlap: Number of overlapping characters between chunks (default 200)
            separator: Primary separator to use for splitting (default "\\n\\n")

        Returns:
            Dict with list of text chunks
        """
        if not text:
            return {"error": "text is required"}

        try:
            chunks = chunk_text(text, chunk_size, chunk_overlap, separator)
            return {"success": True, "chunks": chunks, "count": len(chunks)}
        except Exception as e:
            return {"error": f"Text chunking failed: {e}"}
