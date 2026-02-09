"""MCP client wrapper for accessing aden_tools.

This module initializes the MCP server with aden_tools and provides
a simple interface for other modules to use GitHub, Email, and Vector DB tools.
"""
import os
import sys
from pathlib import Path

# Load .env file into environment (required for MCP tools to access credentials)
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # Try parent directory as fallback
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)

# Add tools package to path
tools_path = Path(__file__).resolve().parent.parent.parent / "tools" / "src"
if str(tools_path) not in sys.path:
    sys.path.insert(0, str(tools_path))

from fastmcp import FastMCP

# Initialize MCP server
mcp = FastMCP("maintainer_service")

# Register all aden_tools (pass None for credentials to use env vars)
from aden_tools.tools.github_tool import register_tools as register_github_tools
from aden_tools.tools.email_tool import register_tools as register_email_tools
from aden_tools.tools.vector_db_tool import register_tools as register_vector_db_tools

register_github_tools(mcp, credentials=None)
register_email_tools(mcp, credentials=None)
register_vector_db_tools(mcp)


class MCPClient:
    """Wrapper around MCP tools for easy access."""
    
    def __init__(self):
        self._tools = mcp._tool_manager._tools
        # Get repo config from env (GitHub tools require owner/repo for each call)
        self._github_owner = os.getenv("GITHUB_REPO_OWNER", "")
        self._github_repo = os.getenv("GITHUB_REPO_NAME", "")
        # Get chroma config from env
        self._chroma_collection = os.getenv("CHROMA_COLLECTION_NAME", "issues")
        self._chroma_persist_dir = os.getenv("CHROMA_PERSIST_DIRECTORY", "./data/chroma")
    
    def _call_tool(self, tool_name: str, **kwargs):
        """Call a registered MCP tool."""
        if tool_name not in self._tools:
            available = list(self._tools.keys())
            raise ValueError(f"Tool '{tool_name}' not registered. Available: {available}")
        return self._tools[tool_name].fn(**kwargs)
    
    # GitHub tools (note: all require owner and repo parameters)
    def get_issues(self, state: str = "open", assignee: str | None = None, page: int = 1, limit: int = 30):
        """Fetch issues from GitHub."""
        response = self._call_tool(
            "github_list_issues",
            owner=self._github_owner,
            repo=self._github_repo,
            state=state,
            assignee=assignee,
            page=page,
            limit=limit
        )
        # Unwrap data from aden_tools response format
        if isinstance(response, dict) and "error" in response:
            return response
        if isinstance(response, dict) and "success" in response and "data" in response:
            return response["data"]
        return response
    
    def get_issue(self, issue_number: int):
        """Get a single issue."""
        response = self._call_tool(
            "github_get_issue",
            owner=self._github_owner,
            repo=self._github_repo,
            issue_number=issue_number
        )
        # Unwrap data from aden_tools response format
        if isinstance(response, dict) and "error" in response:
            return response
        if isinstance(response, dict) and "success" in response and "data" in response:
            return response["data"]
        return response
    
    def get_issue_comments(self, issue_number: int):
        """Get comments for an issue."""
        response = self._call_tool(
            "github_get_issue_comments",
            owner=self._github_owner,
            repo=self._github_repo,
            issue_number=issue_number
        )
        # Unwrap data from aden_tools response format
        if isinstance(response, dict) and "error" in response:
            return response
        if isinstance(response, dict) and "success" in response and "data" in response:
            return response["data"]
        return response
    
    def get_issue_timeline(self, issue_number: int):
        """Get timeline events for an issue."""
        response = self._call_tool(
            "github_get_issue_timeline",
            owner=self._github_owner,
            repo=self._github_repo,
            issue_number=issue_number
        )
        # Unwrap data from aden_tools response format
        if isinstance(response, dict) and "error" in response:
            return response
        if isinstance(response, dict) and "success" in response and "data" in response:
            return response["data"]
        return response
    
    def get_pull_request(self, pull_number: int):
        """Get PR details."""
        response = self._call_tool(
            "github_get_pull_request",
            owner=self._github_owner,
            repo=self._github_repo,
            pull_number=pull_number
        )
        # Unwrap data from aden_tools response format
        if isinstance(response, dict) and "error" in response:
            return response
        if isinstance(response, dict) and "success" in response and "data" in response:
            return response["data"]
        return response
    
    # Email tools
    def send_email(self, to: str | list[str], subject: str, html: str, from_email: str | None = None, provider: str = "smtp"):
        """Send an email."""
        return self._call_tool(
            "send_email",
            to=to,
            subject=subject,
            html=html,
            from_email=from_email,
            provider=provider
        )
    
    # Vector DB tools
    def upsert_document(self, document_id: str, text: str, metadata: dict | None = None):
        """Upsert a single document to the collection."""
        return self._call_tool(
            "vector_db_upsert",
            ids=[document_id],
            documents=[text],
            metadatas=[metadata] if metadata else None,
            collection_name=self._chroma_collection,
            persist_directory=self._chroma_persist_dir
        )
    
    def query_similar(self, query_text: str, n_results: int = 5, where: dict | None = None):
        """Query similar documents."""
        response = self._call_tool(
            "vector_db_search",
            query_texts=[query_text],
            n_results=n_results,
            where=where,
            collection_name=self._chroma_collection,
            persist_directory=self._chroma_persist_dir
        )
        if isinstance(response, dict) and "success" in response and "data" in response:
            return response["data"]
        return response
    
    def delete_documents(self, document_ids: list[str]):
        """Delete documents from the collection."""
        return self._call_tool(
            "vector_db_delete",
            ids=document_ids,
            collection_name=self._chroma_collection,
            persist_directory=self._chroma_persist_dir
        )
    
    def count_documents(self):
        """Get count of documents in the collection."""
        return self._call_tool(
            "vector_db_count",
            collection_name=self._chroma_collection,
            persist_directory=self._chroma_persist_dir
        )


# Global instance
mcp_client = MCPClient()
