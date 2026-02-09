"""Vector store for issue knowledge base using MCP vector_db_tool.

This module provides a simplified interface to ChromaDB operations
using the aden_tools vector_db_tool via MCP.
"""
from app.mcp_client import mcp_client


class IssueMemory:
    """Manages the vector store for issue similarity search."""
    
    def __init__(self):
        """Initialize vector DB collection."""
        self.collection_name = "issue_knowledge_base"

    
    def upsert_issue(self, issue_id: str, full_text: str, summary: str, metadata: dict):
        """
        Add or update an issue in the vector store.
        
        Args:
            issue_id: GitHub issue ID
            full_text: Complete issue thread (title + body + comments)
            summary: AI-generated one-sentence summary
            metadata: Additional metadata (title, state, etc.)
        """
        metadata_with_summary = {**metadata, "summary": summary}
        
        result = mcp_client.upsert_document(
            document_id=issue_id,
            text=full_text,
            metadata=metadata_with_summary
        )
        
        if isinstance(result, dict) and "error" in result:
            raise Exception(f"Failed to upsert issue: {result['error']}")
    
    def find_similar(self, query_text: str, n_results: int = 5, exclude_id: str | None = None):
        """
        Find similar issues using semantic search.
        
        Args:
            query_text: Text to search for
            n_results: Number of results to return
            exclude_id: Issue ID to exclude from results
            
        Returns:
            List of similar issues with metadata
        """
        # Query more results if we need to exclude one
        query_n = n_results + (1 if exclude_id else 0)
        
        result = mcp_client.query_similar(
            query_text=query_text,
            n_results=query_n
        )
        
        if isinstance(result, dict) and "error" in result:
            raise Exception(f"Failed to query similar issues: {result['error']}")
        
        # Handle ChromaDB columnar format
        # result = {'ids': [['id1', ...]], 'distances': [[0.1, ...]], 'metadatas': [[{...}, ...]]}
        ids = result.get('ids', [[]])[0]
        distances = result.get('distances', [[]])[0] or []  # distances might be None
        metadatas = result.get('metadatas', [[]])[0] or []  # metadatas might be None
        
        similar_issues = []
        for i, item_id in enumerate(ids):
            # Filter out the excluded ID if present
            if exclude_id and item_id == exclude_id:
                continue
                
            similar_issues.append({
                "id": item_id,
                "distance": distances[i] if i < len(distances) else None,
                "metadata": metadatas[i] if i < len(metadatas) else {}
            })
        
        return similar_issues[:n_results]


# Global instance
issue_memory = IssueMemory()
