"""Tests for Stack Overflow tool."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.stack_overflow_tool.stack_overflow_tool import register_tools


@pytest.fixture
def mcp():
    return FastMCP("test-server")


@pytest.fixture
def tools(mcp):
    """Register tools and return dict of tool name -> function."""
    tools_dict = {}
    mock_mcp = MagicMock()

    def mock_tool():
        def decorator(f):
            tools_dict[f.__name__] = f
            return f

        return decorator

    mock_mcp.tool = mock_tool
    register_tools(mock_mcp)
    return tools_dict


def test_stack_overflow_search_success(tools):
    search_fn = tools["stack_overflow_search"]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "items": [
            {
                "question_id": 12345,
                "title": "Python asyncio timeout",
                "body": "<p>How do I set a timeout...</p>",
                "link": "https://stackoverflow.com/q/12345",
                "score": 42,
                "answer_count": 5,
                "is_answered": True,
                "view_count": 1000,
            },
        ],
        "quota_remaining": 9999,
    }

    patch_target = "aden_tools.tools.stack_overflow_tool.stack_overflow_tool.httpx.get"
    with patch(patch_target, return_value=mock_response):
        result = search_fn(query="python asyncio timeout", max_results=5)

    assert result["query"] == "python asyncio timeout"
    assert result["count"] == 1
    assert result["results"][0]["question_id"] == 12345
    assert result["results"][0]["title"] == "Python asyncio timeout"
    assert result["results"][0]["score"] == 42
    assert result["results"][0]["answer_count"] == 5
    assert "<p>" not in result["results"][0]["excerpt"]


def test_stack_overflow_search_empty_query(tools):
    search_fn = tools["stack_overflow_search"]
    result = search_fn(query="")
    assert "error" in result
    assert "empty" in result["error"].lower()


def test_stack_overflow_search_api_error(tools):
    search_fn = tools["stack_overflow_search"]
    mock_response = MagicMock()
    mock_response.status_code = 500

    patch_target = "aden_tools.tools.stack_overflow_tool.stack_overflow_tool.httpx.get"
    with patch(patch_target, return_value=mock_response):
        result = search_fn(query="test")

    assert "error" in result
    assert "500" in result["error"]


def test_stack_overflow_search_quota_exceeded(tools):
    search_fn = tools["stack_overflow_search"]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"items": [], "quota_remaining": 0}

    patch_target = "aden_tools.tools.stack_overflow_tool.stack_overflow_tool.httpx.get"
    with patch(patch_target, return_value=mock_response):
        result = search_fn(query="test")

    assert "error" in result
    assert "quota" in result["error"].lower()


def test_stack_overflow_get_answers_success(tools):
    get_fn = tools["stack_overflow_get_answers"]
    q_response = MagicMock()
    q_response.status_code = 200
    q_response.json.return_value = {
        "items": [
            {
                "question_id": 12345,
                "title": "Python timeout question",
                "link": "https://stackoverflow.com/q/12345",
            },
        ],
    }
    a_response = MagicMock()
    a_response.status_code = 200
    a_response.json.return_value = {
        "items": [
            {
                "answer_id": 67890,
                "body": "<p>Use asyncio.wait_for()</p>",
                "score": 100,
                "is_accepted": True,
            },
        ],
    }

    patch_target = "aden_tools.tools.stack_overflow_tool.stack_overflow_tool.httpx.get"
    with patch(patch_target, side_effect=[q_response, a_response]):
        result = get_fn(question_id=12345)

    assert result["question_id"] == 12345
    assert result["title"] == "Python timeout question"
    assert result["answer_count"] == 1
    assert result["answers"][0]["is_accepted"] is True
    assert result["answers"][0]["score"] == 100
    assert "<p>" not in result["answers"][0]["body"]


def test_stack_overflow_get_answers_question_not_found(tools):
    get_fn = tools["stack_overflow_get_answers"]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"items": []}

    patch_target = "aden_tools.tools.stack_overflow_tool.stack_overflow_tool.httpx.get"
    with patch(patch_target, return_value=mock_response):
        result = get_fn(question_id=999999999)

    assert "error" in result
    assert "not found" in result["error"].lower()


def test_stack_overflow_get_answers_invalid_id(tools):
    get_fn = tools["stack_overflow_get_answers"]
    result = get_fn(question_id=0)
    assert "error" in result
    assert "positive" in result["error"].lower()
