"""
Stack Overflow Tool - Search questions and retrieve answers.

Uses the Stack Exchange API (no key required for basic usage, 10k req/day).
Enables agents to look up coding solutions, debug help, and technical Q&A.
"""

from __future__ import annotations

import re

import httpx
from fastmcp import FastMCP

_BASE_URL = "https://api.stackexchange.com/2.3"
_USER_AGENT = "AdenHive/1.0 (https://github.com/adenhq/hive)"


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


def register_tools(mcp: FastMCP) -> None:
    """Register Stack Overflow tools with the MCP server."""

    @mcp.tool()
    def stack_overflow_search(
        query: str,
        site: str = "stackoverflow",
        max_results: int = 5,
        sort: str = "relevance",
    ) -> dict:
        """
        Search Stack Overflow for questions matching a query.

        Use when you need coding solutions, error fixes, or technical Q&A.
        Returns question titles, excerpts, links, scores, and answer counts.

        Args:
            query: Search query (e.g. "python asyncio timeout", "react useState")
            site: Stack Exchange site (default: stackoverflow). Others: serverfault,
                  superuser, askubuntu
            max_results: Max results to return (1-10, default 5)
            sort: Sort order - relevance, votes, creation, activity (default: relevance)

        Returns:
            Dict with query, count, and results (title, excerpt, link, score, answer_count)
        """
        if not query or not query.strip():
            return {"error": "Query cannot be empty"}

        max_results = max(1, min(max_results, 10))
        valid_sort = ("relevance", "votes", "creation", "activity")
        sort = sort if sort in valid_sort else "relevance"

        try:
            response = httpx.get(
                f"{_BASE_URL}/search",
                params={
                    "order": "desc",
                    "sort": sort,
                    "intitle": query.strip()[:200],
                    "site": site,
                    "pagesize": max_results,
                    "filter": "withbody",
                },
                timeout=15.0,
                headers={"User-Agent": _USER_AGENT},
            )

            if response.status_code != 200:
                return {
                    "error": f"Stack Exchange API error: {response.status_code}",
                    "query": query,
                }

            data = response.json()
            items = data.get("items", [])

            if data.get("quota_remaining", 0) == 0:
                return {"error": "API quota exceeded. Try again later.", "query": query}

            results = []
            for item in items:
                body = item.get("body") or item.get("excerpt") or ""
                results.append(
                    {
                        "question_id": item.get("question_id"),
                        "title": item.get("title", ""),
                        "excerpt": _strip_html(body)[:500],
                        "link": item.get("link", ""),
                        "score": item.get("score", 0),
                        "answer_count": item.get("answer_count", 0),
                        "is_answered": item.get("is_answered", False),
                        "view_count": item.get("view_count", 0),
                    }
                )

            return {
                "query": query,
                "site": site,
                "count": len(results),
                "results": results,
            }

        except httpx.TimeoutException:
            return {"error": "Request timed out", "query": query}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}", "query": query}
        except Exception as e:
            return {"error": f"Search failed: {str(e)}", "query": query}

    @mcp.tool()
    def stack_overflow_get_answers(
        question_id: int,
        site: str = "stackoverflow",
        max_answers: int = 3,
    ) -> dict:
        """
        Get the top answers for a Stack Overflow question by ID.

        Use after stack_overflow_search to fetch full answer content for a
        specific question. Returns accepted answer first, then highest-scored.

        Args:
            question_id: The question ID from search results
            site: Stack Exchange site (default: stackoverflow)
            max_answers: Max answers to return (1-5, default 3)

        Returns:
            Dict with question title, link, and answers (body, score, is_accepted)
        """
        if question_id < 1:
            return {"error": "question_id must be a positive integer"}

        max_answers = max(1, min(max_answers, 5))

        try:
            # Fetch question + answers in one call
            response = httpx.get(
                f"{_BASE_URL}/questions/{question_id}",
                params={
                    "order": "desc",
                    "sort": "votes",
                    "site": site,
                    "filter": "withbody",
                },
                timeout=15.0,
                headers={"User-Agent": _USER_AGENT},
            )

            if response.status_code != 200:
                return {
                    "error": f"Stack Exchange API error: {response.status_code}",
                    "question_id": question_id,
                }

            data = response.json()
            items = data.get("items", [])

            if not items:
                return {"error": "Question not found", "question_id": question_id}

            question = items[0]
            title = question.get("title", "")
            link = question.get("link", "")

            # Fetch answers
            ans_response = httpx.get(
                f"{_BASE_URL}/questions/{question_id}/answers",
                params={
                    "order": "desc",
                    "sort": "votes",
                    "site": site,
                    "pagesize": max_answers,
                    "filter": "withbody",
                },
                timeout=15.0,
                headers={"User-Agent": _USER_AGENT},
            )

            if ans_response.status_code != 200:
                return {
                    "error": f"Failed to fetch answers: {ans_response.status_code}",
                    "question_id": question_id,
                }

            ans_data = ans_response.json()
            ans_items = ans_data.get("items", [])

            # Sort: accepted first, then by score
            def _key(a: dict) -> tuple:
                return (0 if a.get("is_accepted") else 1, -a.get("score", 0))

            ans_items = sorted(ans_items, key=_key)[:max_answers]

            answers = []
            for a in ans_items:
                answers.append(
                    {
                        "answer_id": a.get("answer_id"),
                        "body": _strip_html(a.get("body", ""))[:2000],
                        "score": a.get("score", 0),
                        "is_accepted": a.get("is_accepted", False),
                    }
                )

            return {
                "question_id": question_id,
                "title": title,
                "link": link,
                "answer_count": len(answers),
                "answers": answers,
            }

        except httpx.TimeoutException:
            return {"error": "Request timed out", "question_id": question_id}
        except httpx.RequestError as e:
            return {"error": f"Network error: {str(e)}", "question_id": question_id}
        except Exception as e:
            return {"error": f"Failed to fetch answers: {str(e)}", "question_id": question_id}
