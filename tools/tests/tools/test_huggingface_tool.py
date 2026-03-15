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


class TestHuggingFaceRunInference:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["huggingface_run_inference"](
                model_id="facebook/bart-large-cnn", inputs="Hello world"
            )
        assert "error" in result

    def test_missing_model_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["huggingface_run_inference"](model_id="", inputs="Hello")
        assert "error" in result
        assert "model_id" in result["error"]

    def test_missing_inputs(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["huggingface_run_inference"](
                model_id="facebook/bart-large-cnn", inputs=""
            )
        assert "error" in result
        assert "inputs" in result["error"]

    def test_invalid_parameters_json(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["huggingface_run_inference"](
                model_id="facebook/bart-large-cnn",
                inputs="Hello world",
                parameters="not valid json",
            )
        assert "error" in result
        assert "JSON" in result["error"]

    def test_successful_inference(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"generated_text": "This is a summary of the input text."}]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.huggingface_tool.huggingface_tool.httpx.post",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["huggingface_run_inference"](
                model_id="facebook/bart-large-cnn",
                inputs="Long article text here...",
            )

        assert result["model_id"] == "facebook/bart-large-cnn"
        assert result["task"] == "auto"
        assert isinstance(result["output"], list)
        assert result["output"][0]["generated_text"] == "This is a summary of the input text."

    def test_inference_with_parameters(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"generated_text": "Generated output"}]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.huggingface_tool.huggingface_tool.httpx.post",
                return_value=mock_resp,
            ) as mock_post,
        ):
            result = tool_fns["huggingface_run_inference"](
                model_id="meta-llama/Llama-3.1-8B-Instruct",
                inputs="Hello",
                parameters='{"max_new_tokens": 128, "temperature": 0.7}',
            )

        assert "output" in result
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["json"]["parameters"]["max_new_tokens"] == 128

    def test_model_loading_503(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"estimated_time": 30.5}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.huggingface_tool.huggingface_tool.httpx.post",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["huggingface_run_inference"](
                model_id="bigscience/bloom", inputs="Hello"
            )

        assert result["error"] == "Model is loading"
        assert result["estimated_time"] == 30.5


class TestHuggingFaceRunEmbedding:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["huggingface_run_embedding"](
                model_id="sentence-transformers/all-MiniLM-L6-v2", inputs="Hello"
            )
        assert "error" in result

    def test_missing_model_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["huggingface_run_embedding"](model_id="", inputs="Hello")
        assert "error" in result

    def test_missing_inputs(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["huggingface_run_embedding"](
                model_id="sentence-transformers/all-MiniLM-L6-v2", inputs=""
            )
        assert "error" in result

    def test_successful_embedding(self, tool_fns):
        mock_embedding = [0.1, 0.2, 0.3, -0.4, 0.5]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_embedding
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.huggingface_tool.huggingface_tool.httpx.post",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["huggingface_run_embedding"](
                model_id="sentence-transformers/all-MiniLM-L6-v2",
                inputs="Hello world",
            )

        assert result["model_id"] == "sentence-transformers/all-MiniLM-L6-v2"
        assert result["embedding"] == mock_embedding
        assert result["dimensions"] == 5


class TestHuggingFaceListInferenceEndpoints:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["huggingface_list_inference_endpoints"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "name": "my-llama-endpoint",
                "model": {"repository": "meta-llama/Llama-3.1-8B-Instruct"},
                "status": {"state": "running", "url": "https://xyz.endpoints.huggingface.cloud"},
                "type": "protected",
                "provider": {"vendor": "aws", "region": "us-east-1"},
            }
        ]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.huggingface_tool.huggingface_tool.httpx.get",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["huggingface_list_inference_endpoints"]()

        assert result["count"] == 1
        assert result["endpoints"][0]["name"] == "my-llama-endpoint"
        assert result["endpoints"][0]["model"] == "meta-llama/Llama-3.1-8B-Instruct"
        assert result["endpoints"][0]["status"] == "running"

    def test_empty_endpoints(self, tool_fns):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.huggingface_tool.huggingface_tool.httpx.get",
                return_value=mock_resp,
            ),
        ):
            result = tool_fns["huggingface_list_inference_endpoints"]()

        assert result["count"] == 0
        assert result["endpoints"] == []
