"""
arXiv Tool - Search and download scholarly articles.

Uses the arxiv Python package to interact with the public arXiv API.
No authentication required.
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import arxiv
from fastmcp import FastMCP


class _ArxivRateLimiter:
    """Thread-safe rate limiter enforcing 3-second delays between API calls."""

    _lock = threading.Lock()
    _last_request_time = 0.0
    _min_interval = 3.0  # arXiv API requirement

    @classmethod
    def wait(cls) -> None:
        """Block until next request is allowed."""
        with cls._lock:
            now = time.time()
            time_since_last = now - cls._last_request_time
            if time_since_last < cls._min_interval:
                sleep_time = cls._min_interval - time_since_last
                time.sleep(sleep_time)
            cls._last_request_time = time.time()


def register_tools(mcp: FastMCP) -> None:
    """Register arXiv tools with the MCP server."""

    @mcp.tool()
    def search_papers(
        query: str,
        max_results: int = 10,
        sort_by: str = "relevance",
    ) -> dict:
        """
        Search arXiv for scholarly articles.

        Searches by keyword (e.g., "transformer architecture") or arXiv ID
        (e.g., "1706.03762"). Returns paper metadata including paper_id for
        use with download_paper.

        Args:
            query: Search query or arXiv ID (1-500 chars)
            max_results: Maximum results to return (1-100)
            sort_by: Sort order - "relevance", "recent", or "submitted"

        Returns:
            Dict with papers list and metadata, or error dict
        """
        # Input validation
        if not query or len(query) > 500:
            return {"error": "Query must be 1-500 characters"}

        if max_results < 1:
            max_results = 1
        elif max_results > 100:
            max_results = 100

        # Map user-friendly names to arXiv sort criteria
        sort_map = {
            "relevance": arxiv.SortCriterion.Relevance,
            "recent": arxiv.SortCriterion.LastUpdatedDate,
            "submitted": arxiv.SortCriterion.SubmittedDate,
        }
        sort_criterion = sort_map.get(sort_by, arxiv.SortCriterion.Relevance)

        try:
            # Enforce rate limit
            _ArxivRateLimiter.wait()

            # Create and execute search
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=sort_criterion,
            )

            # Parse results
            papers = []
            for result in search.results():
                papers.append({
                    "paper_id": result.entry_id.split("/")[-1],  # Extract ID
                    "title": result.title,
                    "authors": [author.name for author in result.authors],
                    "abstract": result.summary,
                    "published": result.published.isoformat(),
                    "updated": result.updated.isoformat() if result.updated else None,
                    "pdf_url": result.pdf_url,
                    "categories": result.categories,
                })

            return {
                "query": query,
                "num_results": len(papers),
                "sort_by": sort_by,
                "papers": papers,
            }

        except Exception as e:
            return {"error": f"Search failed: {str(e)}"}

    @mcp.tool()
    def download_paper(
        paper_id: str,
    ) -> dict:
        """
        Download a paper PDF from arXiv.

        Downloads the PDF to a temporary directory and returns the absolute
        file path for use with pdf_read. The paper_id should come from
        search_papers results.

        Args:
            paper_id: arXiv ID (e.g., "1706.03762" or "arXiv:1706.03762")

        Returns:
            Dict with file_path and metadata, or error dict
        """
        # Input validation
        if not paper_id:
            return {"error": "paper_id is required"}

        # Clean paper_id (remove "arXiv:" prefix if present)
        clean_id = paper_id.replace("arXiv:", "").replace("arxiv:", "").strip()
        if not clean_id:
            return {"error": "Invalid paper_id format"}

        try:
            # Enforce rate limit
            _ArxivRateLimiter.wait()

            # Search for the paper by ID
            search = arxiv.Search(id_list=[clean_id])
            paper = next(search.results(), None)

            if not paper:
                return {"error": f"Paper not found: {clean_id}"}

            # Create temp directory for downloads
            temp_dir = Path(tempfile.gettempdir()) / "arxiv_papers"
            temp_dir.mkdir(exist_ok=True)

            # Download PDF
            file_path = temp_dir / f"{clean_id}.pdf"
            paper.download_pdf(filename=str(file_path))

            # Verify download succeeded
            if not file_path.exists():
                return {"error": "Download failed - file not created"}

            return {
                "paper_id": clean_id,
                "title": paper.title,
                "file_path": str(file_path.absolute()),
                "file_size_bytes": file_path.stat().st_size,
            }

        except Exception as e:
            return {"error": f"Download failed: {str(e)}"}
