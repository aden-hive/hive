"""Tests for apify_tool - Apify web scraping and automation platform."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.apify_tool.apify_tool import register_tools

ENV = {"APIFY_API_TOKEN": "test-token"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestApifyRunActor:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["apify_run_actor"](actor_id="apify/web-scraper")
        assert "error" in result

    def test_missing_actor_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["apify_run_actor"](actor_id="")
        assert "error" in result

    def test_successful_run(self, tool_fns):
        mock_resp = {
            "data": {
                "id": "run-1",
                "status": "RUNNING",
                "defaultDatasetId": "ds-1",
                "defaultKeyValueStoreId": "kv-1",
                "startedAt": "2024-01-01T00:00:00Z",
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.apify_tool.apify_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["apify_run_actor"](actor_id="apify/web-scraper")

        assert result["run_id"] == "run-1"
        assert result["status"] == "RUNNING"
        assert result["dataset_id"] == "ds-1"


class TestApifyGetRun:
    def test_missing_ids(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["apify_get_run"](actor_id="", run_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = {
            "data": {
                "id": "run-1",
                "status": "SUCCEEDED",
                "startedAt": "2024-01-01T00:00:00Z",
                "finishedAt": "2024-01-01T00:01:00Z",
                "defaultDatasetId": "ds-1",
                "defaultKeyValueStoreId": "kv-1",
                "usage": {"ACTOR_COMPUTE_UNITS": 0.005},
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.apify_tool.apify_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["apify_get_run"](actor_id="apify/web-scraper", run_id="run-1")

        assert result["status"] == "SUCCEEDED"
        assert result["usage_usd"] == 0.005


class TestApifyGetDatasetItems:
    def test_missing_dataset_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["apify_get_dataset_items"](dataset_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_items = [
            {"url": "https://example.com", "title": "Example"},
            {"url": "https://test.com", "title": "Test"},
        ]
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.apify_tool.apify_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_items
            result = tool_fns["apify_get_dataset_items"](dataset_id="ds-1")

        assert result["count"] == 2
        assert result["items"][0]["url"] == "https://example.com"


class TestApifyListActors:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "data": {
                "items": [
                    {
                        "id": "act-1",
                        "name": "web-scraper",
                        "title": "Web Scraper",
                        "description": "Crawls websites",
                        "stats": {"totalRuns": 100},
                    }
                ]
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.apify_tool.apify_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["apify_list_actors"]()

        assert len(result["actors"]) == 1
        assert result["actors"][0]["name"] == "web-scraper"


class TestApifyListRuns:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "data": {
                "items": [
                    {
                        "id": "run-1",
                        "actId": "act-1",
                        "status": "SUCCEEDED",
                        "startedAt": "2024-01-01T00:00:00Z",
                        "finishedAt": "2024-01-01T00:01:00Z",
                        "defaultDatasetId": "ds-1",
                    }
                ]
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.apify_tool.apify_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["apify_list_runs"]()

        assert len(result["runs"]) == 1
        assert result["runs"][0]["status"] == "SUCCEEDED"


class TestApifyGetKvStoreRecord:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["apify_get_kv_store_record"](store_id="", key="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.apify_tool.apify_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"screenshot": "base64..."}
            result = tool_fns["apify_get_kv_store_record"](store_id="kv-1", key="OUTPUT")

        assert result["key"] == "OUTPUT"
        assert result["value"]["screenshot"] == "base64..."
