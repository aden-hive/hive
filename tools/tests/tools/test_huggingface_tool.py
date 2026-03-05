"""Tests for huggingface_tool - HuggingFace Hub model/dataset/space discovery."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.huggingface_tool.huggingface_tool import register_tools

ENV = {"HUGGINGFACE_TOKEN": "hf_test_token"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestHuggingFaceSearchModels:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["huggingface_search_models"]()
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "id": "meta-llama/Llama-3-8B",
                "author": "meta-llama",
                "downloads": 1000000,
                "likes": 5000,
                "pipeline_tag": "text-generation",
                "tags": ["pytorch", "llama"],
                "lastModified": "2024-06-01T00:00:00Z",
            }
        ]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.huggingface_tool.huggingface_tool.httpx.get",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["huggingface_search_models"](query="llama")

        assert len(result["models"]) == 1
        assert result["models"][0]["id"] == "meta-llama/Llama-3-8B"


class TestHuggingFaceGetModel:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["huggingface_get_model"](model_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "meta-llama/Llama-3-8B",
            "author": "meta-llama",
            "downloads": 1000000,
            "likes": 5000,
            "pipeline_tag": "text-generation",
            "tags": ["pytorch"],
            "library_name": "transformers",
            "private": False,
            "lastModified": "2024-06-01T00:00:00Z",
            "createdAt": "2024-04-01T00:00:00Z",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.huggingface_tool.huggingface_tool.httpx.get",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["huggingface_get_model"](model_id="meta-llama/Llama-3-8B")

        assert result["id"] == "meta-llama/Llama-3-8B"
        assert result["library_name"] == "transformers"


class TestHuggingFaceSearchDatasets:
    def test_successful_search(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "id": "squad",
                "author": "rajpurkar",
                "downloads": 500000,
                "likes": 200,
                "tags": ["question-answering"],
                "lastModified": "2024-01-01T00:00:00Z",
            }
        ]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.huggingface_tool.huggingface_tool.httpx.get",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["huggingface_search_datasets"](query="squad")

        assert len(result["datasets"]) == 1
        assert result["datasets"][0]["id"] == "squad"


class TestHuggingFaceGetDataset:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["huggingface_get_dataset"](dataset_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "openai/gsm8k",
            "author": "openai",
            "downloads": 100000,
            "likes": 300,
            "tags": ["math"],
            "private": False,
            "lastModified": "2024-01-01T00:00:00Z",
            "createdAt": "2023-01-01T00:00:00Z",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.huggingface_tool.huggingface_tool.httpx.get",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["huggingface_get_dataset"](dataset_id="openai/gsm8k")

        assert result["id"] == "openai/gsm8k"


class TestHuggingFaceSearchSpaces:
    def test_successful_search(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "id": "gradio/chatbot",
                "author": "gradio",
                "likes": 100,
                "sdk": "gradio",
                "tags": ["chatbot"],
                "lastModified": "2024-01-01T00:00:00Z",
            }
        ]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.huggingface_tool.huggingface_tool.httpx.get",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["huggingface_search_spaces"](query="chatbot")

        assert len(result["spaces"]) == 1
        assert result["spaces"][0]["sdk"] == "gradio"


class TestHuggingFaceWhoami:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["huggingface_whoami"]()
        assert "error" in result

    def test_successful_whoami(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "name": "testuser",
            "fullname": "Test User",
            "email": "test@example.com",
            "avatarUrl": "https://huggingface.co/avatars/test.png",
            "orgs": [{"name": "test-org", "roleInOrg": "admin"}],
            "type": "user",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.huggingface_tool.huggingface_tool.httpx.get",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["huggingface_whoami"]()

        assert result["name"] == "testuser"
        assert len(result["orgs"]) == 1
