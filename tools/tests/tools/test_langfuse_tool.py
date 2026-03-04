"""Tests for langfuse_tool - Langfuse LLM observability API."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.langfuse_tool.langfuse_tool import register_tools

ENV = {
    "LANGFUSE_PUBLIC_KEY": "pk-lf-test-key",
    "LANGFUSE_SECRET_KEY": "sk-lf-test-secret",
    "LANGFUSE_HOST": "https://cloud.langfuse.com",
}


def _mock_resp(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = ""
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestLangfuseListTraces:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["langfuse_list_traces"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "data": [
                {
                    "id": "trace-abc123",
                    "name": "chat-completion",
                    "timestamp": "2025-10-16T12:00:00.000Z",
                    "userId": "user_123",
                    "sessionId": "session_456",
                    "tags": ["production"],
                    "latency": 1.234,
                    "totalCost": 0.0045,
                    "observations": ["obs-1", "obs-2"],
                }
            ],
            "meta": {"page": 1, "limit": 50, "totalItems": 1, "totalPages": 1},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.langfuse_tool.langfuse_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["langfuse_list_traces"]()

        assert result["count"] == 1
        assert result["total_items"] == 1
        assert result["traces"][0]["id"] == "trace-abc123"
        assert result["traces"][0]["observation_count"] == 2


class TestLangfuseGetTrace:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["langfuse_get_trace"](trace_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "id": "trace-abc123",
            "name": "chat-completion",
            "timestamp": "2025-10-16T12:00:00.000Z",
            "userId": "user_123",
            "sessionId": "session_456",
            "tags": ["production"],
            "latency": 1.234,
            "totalCost": 0.0045,
            "input": {"messages": [{"role": "user", "content": "Hello"}]},
            "output": {"response": "Hi there!"},
            "observations": [
                {
                    "id": "obs-1",
                    "type": "GENERATION",
                    "name": "gpt-4-call",
                    "model": "gpt-4",
                    "startTime": "2025-10-16T12:00:00.500Z",
                    "endTime": "2025-10-16T12:00:01.200Z",
                    "usage": {"input": 150, "output": 80, "total": 230},
                }
            ],
            "scores": [
                {
                    "id": "score-1",
                    "name": "correctness",
                    "value": 0.9,
                    "dataType": "NUMERIC",
                    "source": "API",
                    "comment": "Factually correct",
                }
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.langfuse_tool.langfuse_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["langfuse_get_trace"](trace_id="trace-abc123")

        assert result["id"] == "trace-abc123"
        assert len(result["observations"]) == 1
        assert result["observations"][0]["model"] == "gpt-4"
        assert result["scores"][0]["value"] == 0.9


class TestLangfuseListScores:
    def test_successful_list(self, tool_fns):
        data = {
            "data": [
                {
                    "id": "score-1",
                    "traceId": "trace-abc123",
                    "observationId": None,
                    "name": "correctness",
                    "value": 0.9,
                    "dataType": "NUMERIC",
                    "source": "API",
                    "comment": "Good",
                    "timestamp": "2025-10-16T12:01:00.000Z",
                }
            ],
            "meta": {"page": 1, "limit": 50, "totalItems": 1, "totalPages": 1},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.langfuse_tool.langfuse_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["langfuse_list_scores"]()

        assert result["count"] == 1
        assert result["scores"][0]["name"] == "correctness"
        assert result["scores"][0]["value"] == 0.9


class TestLangfuseCreateScore:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["langfuse_create_score"](trace_id="", name="", value=0.0)
        assert "error" in result

    def test_successful_create(self, tool_fns):
        data = {"id": "score-new-123"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.langfuse_tool.langfuse_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["langfuse_create_score"](
                trace_id="trace-abc123",
                name="helpfulness",
                value=1.0,
                data_type="BOOLEAN",
                comment="Very helpful",
            )

        assert result["id"] == "score-new-123"


class TestLangfuseListPrompts:
    def test_successful_list(self, tool_fns):
        data = {
            "data": [
                {
                    "name": "movie-critic",
                    "versions": [1, 2, 3],
                    "labels": ["production"],
                    "tags": ["chat"],
                    "lastUpdatedAt": "2025-10-15T10:00:00.000Z",
                }
            ],
            "meta": {"page": 1, "limit": 50, "totalItems": 1, "totalPages": 1},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.langfuse_tool.langfuse_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["langfuse_list_prompts"]()

        assert result["count"] == 1
        assert result["prompts"][0]["name"] == "movie-critic"
        assert 3 in result["prompts"][0]["versions"]


class TestLangfuseGetPrompt:
    def test_missing_name(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["langfuse_get_prompt"](prompt_name="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "name": "movie-critic",
            "version": 3,
            "type": "chat",
            "prompt": [
                {"role": "system", "content": "You are a movie critic"},
                {"role": "user", "content": "Review {{movie}}"},
            ],
            "config": {"temperature": 0.7},
            "labels": ["production"],
            "tags": ["chat"],
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.langfuse_tool.langfuse_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["langfuse_get_prompt"](prompt_name="movie-critic")

        assert result["name"] == "movie-critic"
        assert result["version"] == 3
        assert result["type"] == "chat"
        assert len(result["prompt"]) == 2
