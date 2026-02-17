"""
arXiv Tool - Search and download scientific papers.
"""

import os
import re
import tempfile
from typing import Literal

import arxiv
import requests
from fastmcp import FastMCP

_SHARED_ARXIV_CLIENT = arxiv.Client(page_size=100, delay_seconds=3, num_retries=3)


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
        Downloads a paper from arXiv by its ID and saves it to a temporary PDF file.

        Args:
            paper_id (str): The arXiv identifier (e.g., "2207.13219v4").

        Returns:
            dict: { "success": bool, "file_path": str, "paper_id": str }
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

            # Clean the title to make it a valid filename
            clean_title = re.sub(r"[^\w\s-]", "", paper.title).strip().replace(" ", "_")
            clean_id = re.sub(r"[^\w\s-]", "_", paper_id)
            filename = f"{clean_title[:50]}_{clean_id}.pdf"
            local_path = os.path.join(tempfile.gettempdir(), filename)

            # Start the Stream
            # stream=True prevents loading the entire file into memory
            response = requests.get(pdf_url, stream=True)
            response.raise_for_status()

            # Create a Permanent Temp File
            try:
                with open(local_path, "wb") as tmp_file:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            tmp_file.write(chunk)
            except OSError as e:
                return {
                    "success": False,
                    "error": f"File System Error during write: {str(e)}",
                }

            local_path = tmp_file.name

            return {
                "success": True,
                "file_path": local_path,
                "paper_id": paper_id,
            }

        except arxiv.ArxivError as e:
            return {"success": False, "error": f"arXiv library error: {str(e)}"}
        except (ConnectionError, requests.RequestException) as e:
            if local_path and os.path.exists(local_path):
                os.remove(local_path)
            return {"success": False, "error": f"Network error: {str(e)}"}
        except OSError as e:
            if local_path and os.path.exists(local_path):
                os.remove(local_path)
            return {"success": False, "error": f"File system error: {str(e)}"}
        except Exception as e:
            if local_path and os.path.exists(local_path):
                os.remove(local_path)
            return {"success": False, "error": f"Unexpected error: {str(e)}"}
