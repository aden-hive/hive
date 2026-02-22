"""
arXiv Tool - Search and download scientific papers.
"""

import atexit
import os
import re
import tempfile
from typing import Literal
from urllib.parse import urlparse

import arxiv
import requests
from fastmcp import FastMCP

_SHARED_ARXIV_CLIENT = arxiv.Client(page_size=100, delay_seconds=3, num_retries=3)

_TEMP_DIR = tempfile.TemporaryDirectory(prefix="arxiv_papers_")
atexit.register(_TEMP_DIR.cleanup)


def register_tools(mcp: FastMCP) -> None:
    """Register arXiv tools with the MCP server."""

    @mcp.tool()
    def search_papers(
        query: str = "",
        id_list: list[str] | None = None,
        max_results: int = 10,
        sort_by: Literal["relevance", "lastUpdatedDate", "submittedDate"] = "relevance",
        sort_order: Literal["descending", "ascending"] = "descending",
    ) -> dict:
        """
        Searches arXiv for scientific papers using keywords or specific IDs.

        CRITICAL: You MUST provide either a `query` OR an `id_list`.

        Args:
            query (str): The search query (e.g., "multi-agent systems").
                        Default is empty.

                        QUERY SYNTAX & PREFIXES:
                        - Use prefixes: 'ti:' (Title), 'au:' (Author),
                          'abs:' (Abstract), 'cat:' (Category).
                        - Boolean: AND, OR, ANDNOT (Must be capitalized).
                        - Example: "ti:transformer AND au:vaswani"

            id_list (list[str] | None): Specific arXiv IDs (e.g., ["1706.03762"]).
                                        Use this to retrieve specific known papers.

            max_results (int): Max results to return (default 10).

            sort_by (Literal): The sorting criterion.
                            Options: "relevance", "lastUpdatedDate", "submittedDate".
                            Default: "relevance".

            sort_order (Literal): The order of sorting.
                                Options: "descending", "ascending".
                                Default: "descending".

        Returns:
            dict: { "success": bool, "data": list[dict], "count": int }
        """

        # VALIDATION: Ensure the Agent didn't send an empty request
        if not query and not id_list:
            return {
                "success": False,
                "error": "Invalid Request: You must provide either a 'query' or an 'id_list'.",
            }

        # Prevent the agent from accidentally requesting too much data
        max_results = min(max_results, 100)

        # INTERNAL MAPS: Bridge String (Agent) -> Enum Object (Library)
        sort_criteria_map = {
            "relevance": arxiv.SortCriterion.Relevance,
            "lastUpdatedDate": arxiv.SortCriterion.LastUpdatedDate,
            "submittedDate": arxiv.SortCriterion.SubmittedDate,
        }
        sort_order_map = {
            "descending": arxiv.SortOrder.Descending,
            "ascending": arxiv.SortOrder.Ascending,
        }

        try:
            search = arxiv.Search(
                query=query,
                id_list=id_list or [],
                max_results=max_results,
                sort_by=sort_criteria_map.get(sort_by, arxiv.SortCriterion.Relevance),
                sort_order=sort_order_map.get(sort_order, arxiv.SortOrder.Descending),
            )

            result_object = _SHARED_ARXIV_CLIENT.results(search)
            results = []

            # EXECUTION & SERIALIZATION
            for r in result_object:
                results.append(
                    {
                        "id": r.get_short_id(),
                        "title": r.title,
                        "summary": r.summary.replace("\n", " "),
                        "published": str(r.published.date()),
                        "authors": [a.name for a in r.authors],
                        "pdf_url": r.pdf_url,
                        "categories": r.categories,
                    }
                )
            return {
                "success": True,
                "query": query,
                "id_list": id_list or [],
                "results": results,
                "total": len(results),
            }
        except arxiv.ArxivError as e:
            return {"success": False, "error": f"arXiv specific error: {e}"}

        except ConnectionError:
            return {"success": False, "error": "Network unreachable."}
        except Exception as e:
            return {"success": False, "error": f"arXiv search failed: {str(e)}"}

    @mcp.tool()
    def download_paper(paper_id: str) -> dict:
        """
         Downloads a paper from arXiv by its ID and saves it to a managed temporary directory
          for the lifetime of the server process.

        Args:
             paper_id (str): The arXiv identifier (e.g., "2207.13219v4").

         Returns:
             dict: { "success": bool, "file_path": str, "paper_id": str }
                 The file is valid until the server process exits. No cleanup needed.
        """
        local_path = None
        try:
            # Find the PDF Link
            search = arxiv.Search(id_list=[paper_id])
            results_generator = _SHARED_ARXIV_CLIENT.results(search)
            paper = next(results_generator, None)

            if not paper:
                return {
                    "success": False,
                    "error": f"No paper found with ID: {paper_id}",
                }

            pdf_url = paper.pdf_url

            if not pdf_url:
                return {
                    "success": False,
                    "error": "PDF URL not available for this paper.",
                }

            parsed_url = urlparse(pdf_url)
            pdf_url = parsed_url._replace(netloc="export.arxiv.org").geturl()

            # Clean the title to make it a valid filename
            clean_title = re.sub(r"[^\w\s-]", "", paper.title).strip().replace(" ", "_")
            clean_id = re.sub(r"[^\w\s-]", "_", paper_id)
            prefix = f"{clean_title[:50]}_{clean_id}_"

            filename = f"{prefix}.pdf"
            local_path = os.path.join(_TEMP_DIR.name, filename)

            try:
                # Start the Stream
                # stream=True prevents loading the entire file into memory
                headers = {"User-Agent": "Hive-Agent/1.0 (https://github.com/adenhq/hive)"}

                # No rate limiting needed for PDF download.
                # The 3-second rule only applies to the metadata API (export.arxiv.org/api/query),
                # as explicitly stated in the arXiv API User Manual.
                # This is a plain HTTPS file download (export.arxiv.org/pdf/...), not an API call.
                # The deprecated arxiv.py helper `Result.download_pdf()` confirms this —
                # it was just a bare urlretrieve() call,
                # with zero rate limiting or client involvement,
                # because Result objects are pure data and hold no reference back to the Client.
                response = requests.get(pdf_url, stream=True, timeout=60, headers=headers)
                response.raise_for_status()

                content_type = response.headers.get("Content-Type", "")
                if "pdf" not in content_type.lower():
                    return {
                        "success": False,
                        "error": (
                            f"Failed during download or write: Expected PDF content but got "
                            f"'{content_type}'. arXiv may have returned an error page."
                        ),
                    }

                with open(local_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

            except (requests.RequestException, OSError) as e:
                if os.path.exists(local_path):
                    os.remove(local_path)
                local_path = None  # prevent double-deletion in the outer except

                return {
                    "success": False,
                    "error": f"Failed during download or write: {str(e)}",
                }

            return {
                "success": True,
                "file_path": local_path,
                "paper_id": paper_id,
            }

        except arxiv.ArxivError as e:
            return {"success": False, "error": f"arXiv library error: {str(e)}"}
        except ConnectionError as e:
            return {"success": False, "error": f"Network error: {str(e)}"}
        except Exception as e:
            if local_path and os.path.exists(local_path):
                os.remove(local_path)
            return {"success": False, "error": f"Unexpected error: {str(e)}"}
