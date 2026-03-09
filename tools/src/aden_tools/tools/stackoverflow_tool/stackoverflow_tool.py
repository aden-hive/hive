"""
StackOverflow Tool - Search StackOverflow questions and answers via the public
StackExchange API.

No credentials are required. For higher rate limits, optionally set the
STACKEXCHANGE_API_KEY environment variable.
"""

from __future__ import annotations

import os
import re
from html import unescape
from typing import Any, Literal

import httpx
from fastmcp import FastMCP

_STACKEXCHANGE_API_BASE_URL = "https://api.stackexchange.com/2.3"
_STACKOVERFLOW_SITE = "stackoverflow"
_DEFAULT_TIMEOUT = 30.0
_MAX_RESULTS = 30
_CODE_BLOCK_RE = re.compile(r"<pre><code>(.*?)</code></pre>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _clamp_results(max_results: int) -> int:
    return max(1, min(max_results, _MAX_RESULTS))


def _html_to_text(value: str) -> str:
    text = unescape(_HTML_TAG_RE.sub(" ", value))
    return " ".join(text.split())


def _extract_code_snippets(body: str) -> list[str]:
    snippets = []
    for snippet in _CODE_BLOCK_RE.findall(body):
        normalized = unescape(_HTML_TAG_RE.sub("", snippet)).strip()
        if normalized:
            snippets.append(normalized)
    return snippets


def _normalize_owner(owner: dict[str, Any] | None) -> dict[str, Any] | None:
    if not owner:
        return None

    return {
        "user_id": owner.get("user_id"),
        "display_name": owner.get("display_name"),
        "link": owner.get("link"),
        "reputation": owner.get("reputation"),
        "user_type": owner.get("user_type"),
    }


def _normalize_question(item: dict[str, Any]) -> dict[str, Any]:
    body = item.get("body", "")
    return {
        "question_id": item.get("question_id"),
        "title": item.get("title", ""),
        "link": item.get("link", ""),
        "tags": item.get("tags", []),
        "score": item.get("score", 0),
        "answer_count": item.get("answer_count", 0),
        "view_count": item.get("view_count", 0),
        "is_answered": item.get("is_answered", False),
        "accepted_answer_id": item.get("accepted_answer_id"),
        "creation_date": item.get("creation_date"),
        "last_activity_date": item.get("last_activity_date"),
        "owner": _normalize_owner(item.get("owner")),
        "body": body,
        "body_text": _html_to_text(body) if body else "",
        "code_snippets": _extract_code_snippets(body) if body else [],
    }


def _normalize_answer(item: dict[str, Any]) -> dict[str, Any]:
    body = item.get("body", "")
    answer_id = item.get("answer_id")
    question_id = item.get("question_id")
    link = item.get("link", "")
    if not link and answer_id and question_id:
        link = f"https://stackoverflow.com/questions/{question_id}#answer-{answer_id}"

    return {
        "answer_id": answer_id,
        "question_id": question_id,
        "link": link,
        "score": item.get("score", 0),
        "is_accepted": item.get("is_accepted", False),
        "creation_date": item.get("creation_date"),
        "last_activity_date": item.get("last_activity_date"),
        "owner": _normalize_owner(item.get("owner")),
        "body": body,
        "body_text": _html_to_text(body) if body else "",
        "code_snippets": _extract_code_snippets(body) if body else [],
    }


def _stackexchange_get(path: str, *, params: dict[str, Any]) -> dict[str, Any]:
    request_params: dict[str, Any] = {
        "site": _STACKOVERFLOW_SITE,
        **params,
    }
    api_key = os.getenv("STACKEXCHANGE_API_KEY")
    if api_key:
        request_params["key"] = api_key

    response = httpx.get(
        f"{_STACKEXCHANGE_API_BASE_URL}{path}",
        params=request_params,
        headers={"Accept-Encoding": "gzip, deflate"},
        timeout=_DEFAULT_TIMEOUT,
    )

    if response.status_code == 429:
        payload = response.json()
        backoff = payload.get("backoff")
        retry_hint = f" Wait {backoff} seconds before retrying." if backoff else " Wait and retry."
        raise RuntimeError(f"StackExchange API rate limited.{retry_hint}")

    response.raise_for_status()
    payload = response.json()

    error_message = payload.get("error_message")
    if error_message:
        raise RuntimeError(f"StackExchange API error: {error_message}")

    return payload


def register_tools(mcp: FastMCP) -> None:
    """Register StackOverflow tools with the MCP server (no credentials needed)."""

    @mcp.tool()
    def stackoverflow_search(
        query: str,
        max_results: int = 10,
        tags: list[str] | None = None,
        sort_by: Literal["activity", "creation", "votes", "relevance"] = "relevance",
        accepted: bool | None = None,
        min_answers: int = 0,
    ) -> dict[str, Any]:
        """
        Search StackOverflow questions by query text and optional tags.

        Args:
            query: Search query
            max_results: Number of questions to return (1-30)
            tags: Optional tag filters, like ["python", "pandas"]
            sort_by: Sort order: activity, creation, votes, or relevance
            accepted: Filter by whether the question has an accepted answer
            min_answers: Minimum answer count required

        Returns:
            Dict with question results, extracted code snippets, and rate-limit metadata
        """
        normalized_query = query.strip()
        if not normalized_query:
            return {"error": "query is required"}
        if min_answers < 0:
            return {"error": "min_answers must be 0 or greater"}

        params: dict[str, Any] = {
            "q": normalized_query,
            "pagesize": _clamp_results(max_results),
            "order": "desc",
            "sort": sort_by,
            "filter": "withbody",
        }
        if tags:
            params["tagged"] = ";".join(tag.strip() for tag in tags if tag.strip())
        if accepted is not None:
            params["accepted"] = str(accepted).lower()
        if min_answers:
            params["answers"] = min_answers

        try:
            payload = _stackexchange_get("/search/advanced", params=params)
        except (httpx.HTTPError, RuntimeError) as exc:
            return {"error": f"StackOverflow search failed: {exc}"}

        results = [_normalize_question(item) for item in payload.get("items", [])]
        return {
            "query": normalized_query,
            "tags": tags or [],
            "results": results,
            "count": len(results),
            "has_more": payload.get("has_more", False),
            "quota_remaining": payload.get("quota_remaining"),
            "backoff": payload.get("backoff"),
        }

    @mcp.tool()
    def stackoverflow_get_question(question_id: int) -> dict[str, Any]:
        """
        Fetch a single StackOverflow question with full body content.

        Args:
            question_id: StackOverflow question ID

        Returns:
            Dict containing the normalized question details
        """
        if question_id <= 0:
            return {"error": "question_id must be greater than 0"}

        try:
            payload = _stackexchange_get(
                f"/questions/{question_id}",
                params={
                    "order": "desc",
                    "sort": "activity",
                    "filter": "withbody",
                },
            )
        except (httpx.HTTPError, RuntimeError) as exc:
            return {"error": f"Fetching StackOverflow question failed: {exc}"}

        items = payload.get("items", [])
        if not items:
            return {"error": f"Question {question_id} was not found on StackOverflow"}

        return {
            "question_id": question_id,
            "question": _normalize_question(items[0]),
            "quota_remaining": payload.get("quota_remaining"),
            "backoff": payload.get("backoff"),
        }

    @mcp.tool()
    def stackoverflow_get_question_answers(
        question_id: int,
        max_results: int = 10,
        sort_by: Literal["activity", "creation", "votes"] = "votes",
    ) -> dict[str, Any]:
        """
        Fetch answers for a StackOverflow question, including answer bodies and code.

        Args:
            question_id: StackOverflow question ID
            max_results: Number of answers to return (1-30)
            sort_by: Sort order: activity, creation, or votes

        Returns:
            Dict containing normalized answers for the question
        """
        if question_id <= 0:
            return {"error": "question_id must be greater than 0"}

        try:
            payload = _stackexchange_get(
                f"/questions/{question_id}/answers",
                params={
                    "pagesize": _clamp_results(max_results),
                    "order": "desc",
                    "sort": sort_by,
                    "filter": "withbody",
                },
            )
        except (httpx.HTTPError, RuntimeError) as exc:
            return {"error": f"Fetching StackOverflow answers failed: {exc}"}

        results = [_normalize_answer(item) for item in payload.get("items", [])]
        return {
            "question_id": question_id,
            "results": results,
            "count": len(results),
            "has_more": payload.get("has_more", False),
            "quota_remaining": payload.get("quota_remaining"),
            "backoff": payload.get("backoff"),
        }
