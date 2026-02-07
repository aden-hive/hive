"""ChromaDB vector store for issue knowledge base."""

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings


class IssueMemory:
    """Manages the vector store for issue similarity search."""
    
    def __init__(self):
        """Initialize ChromaDB client and collection."""
        self.client = chromadb.PersistentClient(
            path=settings.chroma_persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name="issue_knowledge_base",
            metadata={"hnsw:space": "cosine"}
        )
    
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
        
        self.collection.upsert(
            ids=[issue_id],
            documents=[full_text],
            metadatas=[metadata_with_summary]
        )
    
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
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results + (1 if exclude_id else 0)
        )
        
        if not results or not results["ids"]:
            return []
        
        # Filter out the excluded ID if present
        similar_issues = []
        for i, issue_id in enumerate(results["ids"][0]):
            if exclude_id and issue_id == exclude_id:
                continue
            similar_issues.append({
                "id": issue_id,
                "distance": results["distances"][0][i] if "distances" in results else None,
                "metadata": results["metadatas"][0][i]
            })
        
        return similar_issues[:n_results]


# Global instance
issue_memory = IssueMemory()
