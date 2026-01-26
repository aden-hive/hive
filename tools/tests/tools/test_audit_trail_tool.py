"""Tests for the Audit Trail Tool."""
import json
import tempfile
from pathlib import Path

import pytest
from fastmcp import FastMCP

from aden_tools.tools.audit_trail_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP server for testing."""
    return FastMCP("test-server")


@pytest.fixture
def storage_with_runs(tmp_path):
    """Create a temporary storage directory with sample runs."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    
    # Create sample run data
    sample_run = {
        "id": "run-001",
        "goal_id": "goal-test",
        "goal_description": "Test the system",
        "status": "completed",
        "started_at": "2024-01-15T10:00:00Z",
        "completed_at": "2024-01-15T10:05:00Z",
        "narrative": "Agent successfully completed the test.",
        "input_data": {"query": "test"},
        "output_data": {"result": "success"},
        "decisions": [
            {
                "id": "decision-1",
                "node_id": "node-analyze",
                "timestamp": "2024-01-15T10:01:00Z",
                "intent": "Analyze the input",
                "options": [
                    {"id": "opt-1", "description": "Use method A"},
                    {"id": "opt-2", "description": "Use method B"},
                ],
                "chosen_option_id": "opt-1",
                "reasoning": "Method A is faster",
                "outcome": {"success": True, "summary": "Analysis complete"},
            },
            {
                "id": "decision-2",
                "node_id": "node-execute",
                "timestamp": "2024-01-15T10:03:00Z",
                "intent": "Execute the plan",
                "options": [
                    {"id": "exec-1", "description": "Run in parallel"},
                    {"id": "exec-2", "description": "Run sequentially"},
                ],
                "chosen_option_id": "exec-1",
                "reasoning": "Parallel is more efficient",
                "outcome": {"success": True, "summary": "Execution complete"},
            },
        ],
        "metrics": {
            "total_tokens": 1500,
            "total_cost_usd": 0.0045,
            "duration_ms": 300000,
            "nodes_executed": ["node-analyze", "node-execute"],
            "tools_used": ["web_search"],
        },
        "problems": [],
    }
    
    (runs_dir / "run-001.json").write_text(json.dumps(sample_run))
    
    # Create a failed run
    failed_run = {
        "id": "run-002",
        "goal_id": "goal-test",
        "goal_description": "Another test",
        "status": "failed",
        "started_at": "2024-01-15T11:00:00Z",
        "completed_at": "2024-01-15T11:02:00Z",
        "narrative": "Agent failed due to an error.",
        "decisions": [],
        "metrics": {},
        "problems": [
            {"severity": "error", "description": "API rate limit exceeded"}
        ],
    }
    
    (runs_dir / "run-002.json").write_text(json.dumps(failed_run))
    
    return tmp_path


class TestAuditTrailRegistration:
    """Test tool registration."""
    
    def test_register_tools(self, mcp):
        """Test that tools are registered correctly."""
        register_tools(mcp)
        # If no exception, registration succeeded
        assert True


class TestGenerateAuditTrail:
    """Test generate_audit_trail tool."""
    
    def test_generate_audit_trail_success(self, mcp, storage_with_runs):
        """Test generating an audit trail for a valid run."""
        register_tools(mcp)
        
        # Get the tool
        tool = mcp._tool_manager._tools.get("generate_audit_trail")
        assert tool is not None
        
        # Call the tool function directly
        result = tool.fn(
            run_id="run-001",
            storage_path=str(storage_with_runs),
        )
        
        data = json.loads(result)
        
        assert "audit_report" in data
        assert data["audit_report"]["run_id"] == "run-001"
        assert "run_summary" in data
        assert data["run_summary"]["status"] == "completed"
        assert "decision_timeline" in data
        assert len(data["decision_timeline"]) == 2
        assert "performance_metrics" in data
    
    def test_generate_audit_trail_not_found(self, mcp, storage_with_runs):
        """Test error handling for non-existent run."""
        register_tools(mcp)
        
        tool = mcp._tool_manager._tools.get("generate_audit_trail")
        result = tool.fn(
            run_id="run-nonexistent",
            storage_path=str(storage_with_runs),
        )
        
        data = json.loads(result)
        assert "error" in data
        assert "not found" in data["error"].lower()


class TestGetDecisionTimeline:
    """Test get_decision_timeline tool."""
    
    def test_get_timeline_success(self, mcp, storage_with_runs):
        """Test getting a decision timeline."""
        register_tools(mcp)
        
        tool = mcp._tool_manager._tools.get("get_decision_timeline")
        result = tool.fn(
            run_id="run-001",
            storage_path=str(storage_with_runs),
        )
        
        data = json.loads(result)
        
        assert data["run_id"] == "run-001"
        assert data["total_decisions"] == 2
        assert len(data["timeline"]) == 2
        
        # Check first decision
        first = data["timeline"][0]
        assert first["step"] == 1
        assert first["node_id"] == "node-analyze"
        assert first["chosen"]["option_id"] == "opt-1"
    
    def test_get_timeline_with_filter(self, mcp, storage_with_runs):
        """Test filtering timeline by node."""
        register_tools(mcp)
        
        tool = mcp._tool_manager._tools.get("get_decision_timeline")
        result = tool.fn(
            run_id="run-001",
            storage_path=str(storage_with_runs),
            node_filter="node-execute",
        )
        
        data = json.loads(result)
        
        assert data["total_decisions"] == 1
        assert data["node_filter"] == "node-execute"
        assert data["timeline"][0]["node_id"] == "node-execute"


class TestExportAuditReport:
    """Test export_audit_report tool."""
    
    def test_export_json(self, mcp, storage_with_runs):
        """Test exporting as JSON."""
        register_tools(mcp)
        
        tool = mcp._tool_manager._tools.get("export_audit_report")
        result = tool.fn(
            run_id="run-001",
            storage_path=str(storage_with_runs),
            output_format="json",
        )
        
        # Should be valid JSON
        data = json.loads(result)
        assert data["id"] == "run-001"
    
    def test_export_markdown(self, mcp, storage_with_runs):
        """Test exporting as Markdown."""
        register_tools(mcp)
        
        tool = mcp._tool_manager._tools.get("export_audit_report")
        result = tool.fn(
            run_id="run-001",
            storage_path=str(storage_with_runs),
            output_format="markdown",
        )
        
        assert "# Agent Run Audit Report" in result
        assert "run-001" in result
        assert "## Decision Timeline" in result
    
    def test_export_csv(self, mcp, storage_with_runs):
        """Test exporting as CSV."""
        register_tools(mcp)
        
        tool = mcp._tool_manager._tools.get("export_audit_report")
        result = tool.fn(
            run_id="run-001",
            storage_path=str(storage_with_runs),
            output_format="csv",
        )
        
        lines = result.strip().split("\n")
        assert lines[0] == "decision_id,node_id,timestamp,intent,chosen_option,reasoning,success"
        assert len(lines) == 3  # Header + 2 decisions
    
    def test_export_to_file(self, mcp, storage_with_runs, tmp_path):
        """Test exporting to a file."""
        register_tools(mcp)
        
        output_file = tmp_path / "output" / "report.md"
        
        tool = mcp._tool_manager._tools.get("export_audit_report")
        result = tool.fn(
            run_id="run-001",
            storage_path=str(storage_with_runs),
            output_format="markdown",
            output_file=str(output_file),
        )
        
        data = json.loads(result)
        assert data["success"] is True
        assert output_file.exists()
        assert "# Agent Run Audit Report" in output_file.read_text()


class TestListRuns:
    """Test list_runs tool."""
    
    def test_list_all_runs(self, mcp, storage_with_runs):
        """Test listing all runs."""
        register_tools(mcp)
        
        tool = mcp._tool_manager._tools.get("list_runs")
        result = tool.fn(storage_path=str(storage_with_runs))
        
        data = json.loads(result)
        
        assert data["total_found"] == 2
        run_ids = [r["run_id"] for r in data["runs"]]
        assert "run-001" in run_ids
        assert "run-002" in run_ids
    
    def test_list_runs_by_status(self, mcp, storage_with_runs):
        """Test filtering runs by status."""
        register_tools(mcp)
        
        tool = mcp._tool_manager._tools.get("list_runs")
        result = tool.fn(
            storage_path=str(storage_with_runs),
            status="failed",
        )
        
        data = json.loads(result)
        
        assert data["total_found"] == 1
        assert data["runs"][0]["run_id"] == "run-002"
        assert data["runs"][0]["status"] == "failed"
    
    def test_list_runs_empty_storage(self, mcp, tmp_path):
        """Test listing runs from non-existent storage."""
        register_tools(mcp)
        
        tool = mcp._tool_manager._tools.get("list_runs")
        result = tool.fn(storage_path=str(tmp_path / "nonexistent"))
        
        data = json.loads(result)
        assert "error" in data
