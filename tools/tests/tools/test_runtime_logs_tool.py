"""Tests for MCP runtime_logs_tool.

Uses fixture data written to tmp_path, verifying the three query tools
return correct results. L2/L3 use JSONL format; L1 uses standard JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastmcp import FastMCP

from aden_tools.tools.runtime_logs_tool import register_tools


def _write_jsonl(path: Path, items: list[dict]) -> None:
    """Write a list of dicts as JSONL (one JSON object per line)."""
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")


@pytest.fixture
def runtime_logs_dir(tmp_path: Path) -> Path:
    """Create fixture runtime log data in JSONL format."""
    runs_dir = tmp_path / "runtime_logs" / "runs"

    # Run 1: success (2 nodes)
    run1_dir = runs_dir / "20250101T000001_abc12345"
    run1_dir.mkdir(parents=True)
    (run1_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "20250101T000001_abc12345",
                "agent_id": "agent-a",
                "goal_id": "goal-1",
                "status": "success",
                "total_nodes_executed": 2,
                "node_path": ["node-1", "node-2"],
                "total_input_tokens": 200,
                "total_output_tokens": 100,
                "needs_attention": False,
                "attention_reasons": [],
                "started_at": "2025-01-01T00:00:01",
                "duration_ms": 3000,
                "execution_quality": "clean",
            }
        )
    )
    _write_jsonl(
        run1_dir / "details.jsonl",
        [
            {
                "node_id": "node-1",
                "node_name": "Search",
                "node_type": "event_loop",
                "success": True,
                "total_steps": 2,
                "tokens_used": 250,
                "exit_status": "success",
                "accept_count": 1,
                "retry_count": 1,
                "needs_attention": False,
                "attention_reasons": [],
            },
            {
                "node_id": "node-2",
                "node_name": "Format",
                "node_type": "event_loop",
                "success": True,
                "total_steps": 1,
                "tokens_used": 0,
                "needs_attention": False,
                "attention_reasons": [],
            },
        ],
    )
    _write_jsonl(
        run1_dir / "tool_logs.jsonl",
        [
            {
                "node_id": "node-1",
                "node_type": "event_loop",
                "step_index": 0,
                "llm_text": "Let me search.",
                "tool_calls": [
                    {
                        "tool_use_id": "tc_1",
                        "tool_name": "web_search",
                        "tool_input": {"query": "test"},
                        "result": "Found data",
                        "is_error": False,
                    }
                ],
                "input_tokens": 100,
                "output_tokens": 50,
                "latency_ms": 1000,
                "verdict": "RETRY",
            },
            {
                "node_id": "node-1",
                "node_type": "event_loop",
                "step_index": 1,
                "llm_text": "Here is your result.",
                "tool_calls": [],
                "input_tokens": 100,
                "output_tokens": 50,
                "latency_ms": 800,
                "verdict": "ACCEPT",
            },
            {
                "node_id": "node-2",
                "node_type": "event_loop",
                "step_index": 0,
                "llm_text": "",
                "tool_calls": [],
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": 50,
            },
        ],
    )

    # Run 2: failure with needs_attention
    run2_dir = runs_dir / "20250101T000002_def67890"
    run2_dir.mkdir(parents=True)
    (run2_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "20250101T000002_def67890",
                "agent_id": "agent-a",
                "goal_id": "goal-2",
                "status": "failure",
                "total_nodes_executed": 1,
                "node_path": ["node-1"],
                "total_input_tokens": 10000,
                "total_output_tokens": 5000,
                "needs_attention": True,
                "attention_reasons": ["Node node-1 failed: Max iterations exhausted"],
                "started_at": "2025-01-01T00:00:02",
                "duration_ms": 60000,
                "execution_quality": "failed",
            }
        )
    )
    _write_jsonl(
        run2_dir / "details.jsonl",
        [
            {
                "node_id": "node-1",
                "node_name": "Search",
                "node_type": "event_loop",
                "success": False,
                "error": "Max iterations exhausted",
                "total_steps": 50,
                "exit_status": "failure",
                "retry_count": 50,
                "needs_attention": True,
                "attention_reasons": ["Node node-1 failed: Max iterations exhausted"],
            },
        ],
    )
    _write_jsonl(
        run2_dir / "tool_logs.jsonl",
        [],
    )

    return tmp_path


@pytest.fixture
def runtime_logs_dir_with_in_progress(runtime_logs_dir: Path) -> Path:
    """Extend the fixture with an in-progress run (no summary.json)."""
    runs_dir = runtime_logs_dir / "runtime_logs" / "runs"
    run3_dir = runs_dir / "20250101T000003_fff00000"
    run3_dir.mkdir(parents=True)
    # Only L2/L3 files, no summary.json
    _write_jsonl(
        run3_dir / "details.jsonl",
        [
            {
                "node_id": "node-1",
                "node_name": "Active",
                "node_type": "event_loop",
                "success": True,
            },
        ],
    )
    _write_jsonl(
        run3_dir / "tool_logs.jsonl",
        [
            {
                "node_id": "node-1",
                "node_type": "event_loop",
                "step_index": 0,
                "llm_text": "Working...",
            },
        ],
    )
    return runtime_logs_dir


@pytest.fixture
def query_logs_fn(mcp: FastMCP):
    register_tools(mcp)
    return mcp._tool_manager._tools["query_runtime_logs"].fn


@pytest.fixture
def query_details_fn(mcp: FastMCP):
    register_tools(mcp)
    return mcp._tool_manager._tools["query_runtime_log_details"].fn


@pytest.fixture
def query_raw_fn(mcp: FastMCP):
    register_tools(mcp)
    return mcp._tool_manager._tools["query_runtime_log_raw"].fn


class TestQueryRuntimeLogs:
    def test_list_all_runs(self, query_logs_fn, runtime_logs_dir: Path):
        result = query_logs_fn(agent_work_dir=str(runtime_logs_dir))
        assert result["total"] == 2
        assert len(result["runs"]) == 2
        # Sorted by started_at desc
        assert result["runs"][0]["run_id"] == "20250101T000002_def67890"

    def test_filter_by_status(self, query_logs_fn, runtime_logs_dir: Path):
        result = query_logs_fn(agent_work_dir=str(runtime_logs_dir), status="success")
        assert result["total"] == 1
        assert result["runs"][0]["status"] == "success"

    def test_filter_needs_attention(self, query_logs_fn, runtime_logs_dir: Path):
        result = query_logs_fn(agent_work_dir=str(runtime_logs_dir), status="needs_attention")
        assert result["total"] == 1
        assert result["runs"][0]["needs_attention"] is True

    def test_empty_directory(self, query_logs_fn, tmp_path: Path):
        result = query_logs_fn(agent_work_dir=str(tmp_path))
        assert result["total"] == 0
        assert result["runs"] == []

    def test_limit(self, query_logs_fn, runtime_logs_dir: Path):
        result = query_logs_fn(agent_work_dir=str(runtime_logs_dir), limit=1)
        assert len(result["runs"]) == 1

    def test_in_progress_runs_visible(self, query_logs_fn, runtime_logs_dir_with_in_progress: Path):
        result = query_logs_fn(agent_work_dir=str(runtime_logs_dir_with_in_progress))
        assert result["total"] == 3
        run_ids = {r["run_id"] for r in result["runs"]}
        assert "20250101T000003_fff00000" in run_ids

        # Filter in_progress only
        result_ip = query_logs_fn(
            agent_work_dir=str(runtime_logs_dir_with_in_progress),
            status="in_progress",
        )
        assert result_ip["total"] == 1
        assert result_ip["runs"][0]["status"] == "in_progress"


class TestQueryRuntimeLogDetails:
    def test_load_details(self, query_details_fn, runtime_logs_dir: Path):
        result = query_details_fn(
            agent_work_dir=str(runtime_logs_dir),
            run_id="20250101T000001_abc12345",
        )
        assert result["run_id"] == "20250101T000001_abc12345"
        assert len(result["nodes"]) == 2
        assert result["nodes"][0]["node_id"] == "node-1"

    def test_filter_by_node_id(self, query_details_fn, runtime_logs_dir: Path):
        result = query_details_fn(
            agent_work_dir=str(runtime_logs_dir),
            run_id="20250101T000001_abc12345",
            node_id="node-2",
        )
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["node_id"] == "node-2"

    def test_needs_attention_only(self, query_details_fn, runtime_logs_dir: Path):
        result = query_details_fn(
            agent_work_dir=str(runtime_logs_dir),
            run_id="20250101T000002_def67890",
            needs_attention_only=True,
        )
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["needs_attention"] is True

    def test_missing_run(self, query_details_fn, runtime_logs_dir: Path):
        result = query_details_fn(
            agent_work_dir=str(runtime_logs_dir),
            run_id="nonexistent",
        )
        assert "error" in result


class TestQueryRuntimeLogRaw:
    def test_load_all_steps(self, query_raw_fn, runtime_logs_dir: Path):
        result = query_raw_fn(
            agent_work_dir=str(runtime_logs_dir),
            run_id="20250101T000001_abc12345",
        )
        assert result["run_id"] == "20250101T000001_abc12345"
        assert len(result["steps"]) == 3

    def test_filter_by_step_index(self, query_raw_fn, runtime_logs_dir: Path):
        result = query_raw_fn(
            agent_work_dir=str(runtime_logs_dir),
            run_id="20250101T000001_abc12345",
            step_index=0,
        )
        assert len(result["steps"]) == 2  # step_index=0 for both node-1 and node-2
        assert all(s["step_index"] == 0 for s in result["steps"])

    def test_filter_by_node_id(self, query_raw_fn, runtime_logs_dir: Path):
        result = query_raw_fn(
            agent_work_dir=str(runtime_logs_dir),
            run_id="20250101T000001_abc12345",
            node_id="node-1",
        )
        assert len(result["steps"]) == 2  # 2 steps for node-1
        assert all(s["node_id"] == "node-1" for s in result["steps"])
        assert result["steps"][0]["tool_calls"][0]["tool_name"] == "web_search"

    def test_filter_by_node_id_and_step_index(self, query_raw_fn, runtime_logs_dir: Path):
        result = query_raw_fn(
            agent_work_dir=str(runtime_logs_dir),
            run_id="20250101T000001_abc12345",
            node_id="node-1",
            step_index=0,
        )
        assert len(result["steps"]) == 1
        assert result["steps"][0]["node_id"] == "node-1"
        assert result["steps"][0]["step_index"] == 0

    def test_missing_run(self, query_raw_fn, runtime_logs_dir: Path):
        result = query_raw_fn(
            agent_work_dir=str(runtime_logs_dir),
            run_id="nonexistent",
        )
        assert "error" in result
