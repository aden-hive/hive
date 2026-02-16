"""ArXiv toolkit for Hive agents.

Enables searching for papers and downloading PDFs for research.
"""

import os
import tempfile
import time
from typing import Any, Optional

import arxiv
from fastmcp import FastMCP

from aden_tools.credentials import CredentialStoreAdapter

# ArXiv API suggests a 3-second delay between requests.
# The library might handle some of this, but we'll add a minimal safety delay.
LAST_REQUEST_TIME = 0.0
RATE_LIMIT_DELAY = 3.0


def _rate_limit():
    """Ensure we respect ArXiv rate limits."""
    global LAST_REQUEST_TIME
    elapsed = time.time() - LAST_REQUEST_TIME
    if elapsed < RATE_LIMIT_DELAY:
        time.sleep(RATE_LIMIT_DELAY - elapsed)
    LAST_REQUEST_TIME = time.time()


def register_tools(mcp: FastMCP, credentials: Optional[CredentialStoreAdapter] = None):
    """Register ArXiv tools with the provided MCP instance."""

    @mcp.tool()
    def arxiv_search_papers(query: str, max_results: int = 5) -> dict[str, Any]:
        """
        Search for scholarly papers on ArXiv.

        Args:
            query: Search query (e.g., 'AI Agents', 'id:1706.03762', 'au:Hinton').
            max_results: Maximum number of papers to return (default: 5).

        Returns:
            List of papers with metadata (title, summary, authors, paper_id).
        """
        _rate_limit()
        try:
            client = arxiv.Client()
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance
            )

            results = []
            for paper in client.results(search):
                results.append({
                    "title": paper.title,
                    "summary": paper.summary,
                    "authors": [author.name for author in paper.authors],
                    "published": paper.published.isoformat(),
                    "paper_id": paper.get_short_id(),
                    "pdf_url": paper.pdf_url,
                    "entry_id": paper.entry_id,
                })
            
            return {"papers": results, "count": len(results)}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def arxiv_download_paper(paper_id: str, download_dir: Optional[str] = None) -> dict[str, Any]:
        """
        Download a paper as a PDF file from ArXiv.

        Args:
            paper_id: The ID of the paper (e.g., '1706.03762').
            download_dir: Optional directory to save the PDF. Defaults to a temporary directory.

        Returns:
            Local file path to the downloaded PDF.
        """
        _rate_limit()
        try:
            client = arxiv.Client()
            search = arxiv.Search(id_list=[paper_id])
            paper = next(client.results(search))

            if not download_dir:
                download_dir = tempfile.gettempdir()
            
            # download_pdf returns the filename
            file_path = paper.download_pdf(dirpath=download_dir)
            
            return {
                "file_path": file_path,
                "title": paper.title,
                "paper_id": paper_id
            }
        except StopIteration:
            return {"error": f"Paper with ID {paper_id} not found."}
        except Exception as e:
            return {"error": str(e)}
