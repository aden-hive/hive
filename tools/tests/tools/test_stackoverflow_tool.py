"""Tests for stackoverflow_tool - StackOverflow question and answer search."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.stackoverflow_tool.stackoverflow_tool import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


def _mock_response(payload: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class TestStackOverflowSearch:
    def test_empty_query(self, tool_fns):
        result = tool_fns["stackoverflow_search"](query=" ")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        response = _mock_response(
            {
                "items": [
                    {
                        "question_id": 42,
                        "title": "How do I print in Python?",
                        "link": "https://stackoverflow.com/questions/42",
                        "tags": ["python"],
                        "score": 10,
                        "answer_count": 2,
                        "view_count": 100,
                        "is_answered": True,
                        "accepted_answer_id": 99,
                        "creation_date": 1700000000,
                        "last_activity_date": 1700000100,
                        "owner": {
                            "user_id": 7,
                            "display_name": "Ada",
                            "link": "https://stackoverflow.com/users/7/ada",
                            "reputation": 1234,
                            "user_type": "registered",
                        },
                        "body": (
                            "<p>Use <code>print</code>.</p>"
                            "<pre><code>print(&quot;hello&quot;)</code></pre>"
                        ),
                    }
                ],
                "has_more": False,
                "quota_remaining": 299,
            }
        )

        with patch(
            "aden_tools.tools.stackoverflow_tool.stackoverflow_tool.httpx.get",
            return_value=response,
        ) as mock_get:
            result = tool_fns["stackoverflow_search"](
                query="python print",
                tags=["python", "beginner"],
                max_results=50,
                min_answers=1,
                accepted=True,
            )

        params = mock_get.call_args.kwargs["params"]
        assert params["pagesize"] == 30
        assert params["tagged"] == "python;beginner"
        assert params["accepted"] == "true"
        assert result["count"] == 1
        assert result["results"][0]["question_id"] == 42
        assert result["results"][0]["code_snippets"] == ['print("hello")']
        assert result["quota_remaining"] == 299

    def test_rate_limited_search(self, tool_fns):
        response = _mock_response({"backoff": 12}, status_code=429)

        with patch(
            "aden_tools.tools.stackoverflow_tool.stackoverflow_tool.httpx.get",
            return_value=response,
        ):
            result = tool_fns["stackoverflow_search"](query="python")

        assert result == {
            "error": (
                "StackOverflow search failed: StackExchange API rate limited. "
                "Wait 12 seconds before retrying."
            )
        }


class TestStackOverflowQuestion:
    def test_invalid_question_id(self, tool_fns):
        result = tool_fns["stackoverflow_get_question"](question_id=0)
        assert result == {"error": "question_id must be greater than 0"}

    def test_fetch_question(self, tool_fns):
        response = _mock_response(
            {
                "items": [
                    {
                        "question_id": 123,
                        "title": "Why is my list empty?",
                        "link": "https://stackoverflow.com/questions/123",
                        "tags": ["python", "list"],
                        "score": 3,
                        "answer_count": 1,
                        "view_count": 55,
                        "is_answered": True,
                        "creation_date": 1700000200,
                        "last_activity_date": 1700000300,
                        "body": "<p>Example body</p>",
                    }
                ],
                "quota_remaining": 298,
            }
        )

        with patch(
            "aden_tools.tools.stackoverflow_tool.stackoverflow_tool.httpx.get",
            return_value=response,
        ):
            result = tool_fns["stackoverflow_get_question"](question_id=123)

        assert result["question"]["title"] == "Why is my list empty?"
        assert result["question"]["body_text"] == "Example body"
        assert result["quota_remaining"] == 298


class TestStackOverflowAnswers:
    def test_fetch_answers(self, tool_fns):
        response = _mock_response(
            {
                "items": [
                    {
                        "answer_id": 456,
                        "question_id": 123,
                        "score": 25,
                        "is_accepted": True,
                        "creation_date": 1700000400,
                        "last_activity_date": 1700000500,
                        "body": "<p>Try this:</p><pre><code>x = 1</code></pre>",
                    }
                ],
                "has_more": False,
                "quota_remaining": 297,
            }
        )

        with patch(
            "aden_tools.tools.stackoverflow_tool.stackoverflow_tool.httpx.get",
            return_value=response,
        ) as mock_get:
            result = tool_fns["stackoverflow_get_question_answers"](
                question_id=123,
                max_results=5,
                sort_by="votes",
            )

        params = mock_get.call_args.kwargs["params"]
        assert params["sort"] == "votes"
        assert result["count"] == 1
        assert result["results"][0]["link"] == "https://stackoverflow.com/questions/123#answer-456"
        assert result["results"][0]["code_snippets"] == ["x = 1"]

    def test_http_error(self, tool_fns):
        request = httpx.Request("GET", "https://api.stackexchange.com/2.3/questions/123/answers")
        response = httpx.Response(500, request=request)
        http_error = httpx.HTTPStatusError("server error", request=request, response=response)

        with patch(
            "aden_tools.tools.stackoverflow_tool.stackoverflow_tool.httpx.get",
            side_effect=http_error,
        ):
            result = tool_fns["stackoverflow_get_question_answers"](question_id=123)

        assert result == {"error": "Fetching StackOverflow answers failed: server error"}
