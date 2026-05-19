"""Tests for databricks_tool - Databricks workspace, SQL, and jobs."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.databricks_tool.databricks_tool import register_tools

ENV = {"DATABRICKS_TOKEN": "dapi-test", "DATABRICKS_HOST": "https://test.cloud.databricks.com"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestDatabricksSqlQuery:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["databricks_sql_query"](statement="SELECT 1", warehouse_id="w1")
        assert "error" in result

    def test_missing_fields(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["databricks_sql_query"](statement="", warehouse_id="")
        assert "error" in result

    def test_successful_query(self, tool_fns):
        mock_resp = {
            "statement_id": "stmt-1",
            "status": {"state": "SUCCEEDED"},
            "manifest": {"schema": {"columns": [{"name": "id"}, {"name": "name"}]}},
            "result": {"data_array": [["1", "Alice"], ["2", "Bob"]]},
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.databricks_tool.databricks_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            mock_post.return_value.text = "{}"
            result = tool_fns["databricks_sql_query"](
                statement="SELECT * FROM users", warehouse_id="w1"
            )

        assert result["status"] == "SUCCEEDED"
        assert result["columns"] == ["id", "name"]
        assert result["row_count"] == 2


class TestDatabricksListJobs:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "jobs": [
                {
                    "job_id": 1,
                    "settings": {"name": "ETL Pipeline"},
                    "creator_user_name": "admin@co.com",
                    "created_time": 1700000000000,
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.databricks_tool.databricks_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["databricks_list_jobs"]()

        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["name"] == "ETL Pipeline"


class TestDatabricksRunJob:
    def test_missing_job_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["databricks_run_job"](job_id=0)
        assert "error" in result

    def test_successful_run(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.databricks_tool.databricks_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"run_id": 42}
            mock_post.return_value.text = '{"run_id": 42}'
            result = tool_fns["databricks_run_job"](job_id=1)

        assert result["run_id"] == 42
        assert result["status"] == "triggered"


class TestDatabricksGetRun:
    def test_successful_get(self, tool_fns):
        mock_resp = {
            "run_id": 42,
            "job_id": 1,
            "state": {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"},
            "start_time": 1700000000000,
            "run_page_url": "https://test.cloud.databricks.com/run/42",
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.databricks_tool.databricks_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["databricks_get_run"](run_id=42)

        assert result["state"] == "TERMINATED"
        assert result["result_state"] == "SUCCESS"


class TestDatabricksListClusters:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "clusters": [
                {
                    "cluster_id": "c-1",
                    "cluster_name": "Dev Cluster",
                    "state": "RUNNING",
                    "spark_version": "14.3.x-scala2.12",
                    "creator_user_name": "admin@co.com",
                    "num_workers": 4,
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.databricks_tool.databricks_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["databricks_list_clusters"]()

        assert len(result["clusters"]) == 1
        assert result["clusters"][0]["state"] == "RUNNING"


class TestDatabricksStartCluster:
    def test_missing_cluster_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["databricks_start_cluster"](cluster_id="")
        assert "error" in result

    def test_successful_start(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.databricks_tool.databricks_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {}
            mock_post.return_value.text = ""
            result = tool_fns["databricks_start_cluster"](cluster_id="c-1")

        assert result["status"] == "starting"


class TestDatabricksListWorkspace:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "objects": [
                {"path": "/Users/admin/notebook1", "object_type": "NOTEBOOK", "language": "PYTHON"},
                {"path": "/Users/admin/folder1", "object_type": "DIRECTORY", "language": ""},
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.databricks_tool.databricks_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["databricks_list_workspace"]()

        assert len(result["objects"]) == 2
        assert result["objects"][0]["object_type"] == "NOTEBOOK"
