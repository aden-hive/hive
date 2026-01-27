"""
Audit Trail Tool - Generate human-readable timelines for agent runs.

Allows developers to see exactly what decisions an agent made and what the outcomes were.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from framework.storage.backend import FileStorage


def list_agent_runs(storage_path: str = ".agent_runs") -> list[dict]:
    """
    List all available agent runs in the specified storage path.

    Args:
        storage_path: Path to the directory where runs are stored.
    """
    if not os.path.exists(storage_path):
        return []
        
    storage = FileStorage(storage_path)
    run_ids = storage.list_all_runs()
    
    results = []
    for run_id in run_ids:
        summary = storage.load_summary(run_id)
        if summary:
            # Extract timestamp from run_id if possible
            # Format: run_YYYYMMDD_HHMMSS_xxxx
            timestamp = "unknown"
            if "_" in run_id:
                parts = run_id.split("_")
                if len(parts) >= 3:
                    timestamp = f"{parts[1]}_{parts[2]}"
            
            results.append({
                "run_id": summary.run_id,
                "goal_id": summary.goal_id,
                "status": summary.status,
                "narrative": summary.narrative,
                "duration_ms": summary.duration_ms,
                "timestamp": timestamp
            })
    
    # Sort by run_id (descending) as it contains timestamp
    results.sort(key=lambda x: x["run_id"], reverse=True)
    return results


def get_run_audit_trail(run_id: str, storage_path: str = ".agent_runs") -> str:
    """
    Generate a human-readable audit trail (timeline) for an agent run.
    
    This shows the step-by-step sequence of decisions and outcomes.

    Args:
        run_id: The ID of the run to audit.
        storage_path: Path to the directory where runs are stored.
    """
    if not os.path.exists(storage_path):
        return f"Error: Storage path '{storage_path}' does not exist."
        
    storage = FileStorage(storage_path)
    run = storage.load_run(run_id)
    
    if not run:
        return f"Error: Run '{run_id}' not found in '{storage_path}'."
        
    lines = []
    lines.append(f"# Audit Trail: {run_id}")
    lines.append(f"Goal: {run.goal_description}")
    lines.append(f"Status: {run.status.value.upper()}")
    lines.append(f"Started: {run.started_at}")
    if run.completed_at:
        lines.append(f"Completed: {run.completed_at} ({run.duration_ms}ms)")
    lines.append("")
    
    lines.append("## Timeline")
    lines.append("")
    
    if not run.decisions:
        lines.append("*No decisions recorded for this run.*")
    else:
        for i, decision in enumerate(run.decisions):
            lines.append(f"### {i+1}. {decision.intent}")
            lines.append(f"- **Node**: `{decision.node_id}`")
            lines.append(f"- **Chosen**: `{decision.chosen_option_id}`")
            lines.append(f"- **Reasoning**: {decision.reasoning}")
            
            if decision.outcome:
                status = "✓" if decision.outcome.success else "✗"
                lines.append(f"- **Outcome**: {status} {'Success' if decision.outcome.success else 'Failure'}")
                if decision.outcome.summary:
                    lines.append(f"  - *{decision.outcome.summary}*")
                if decision.outcome.error:
                    lines.append(f"  - **Error**: {decision.outcome.error}")
                if decision.outcome.tokens_used:
                    lines.append(f"  - **Usage**: {decision.outcome.tokens_used} tokens, {decision.outcome.latency_ms}ms")
            else:
                lines.append("- **Outcome**: Pending/Incomplete")
            lines.append("")
            
    if run.problems:
        lines.append("## Problems Encountered")
        lines.append("")
        for problem in run.problems:
            severity_emoji = "🔴" if problem.severity == "critical" else "🟠"
            lines.append(f"### {severity_emoji} {problem.severity.upper()}: {problem.description}")
            if problem.root_cause:
                lines.append(f"- **Root Cause**: {problem.root_cause}")
            if problem.suggested_fix:
                lines.append(f"- **Suggested Fix**: {problem.suggested_fix}")
            lines.append("")
            
    if run.narrative:
        lines.append("## Narrative Summary")
        lines.append(run.narrative)
        
    return "\n".join(lines)


def register_tools(mcp: FastMCP) -> None:
    """Register audit trail tools with the MCP server."""

    @mcp.tool()
    def list_agent_runs_tool(storage_path: str = ".agent_runs") -> list[dict]:
        """
        List all available agent runs in the specified storage path.

        Args:
            storage_path: Path to the directory where runs are stored.
        """
        return list_agent_runs(storage_path)

    @mcp.tool()
    def get_run_audit_trail_tool(run_id: str, storage_path: str = ".agent_runs") -> str:
        """
        Generate a human-readable audit trail (timeline) for an agent run.
        
        This shows the step-by-step sequence of decisions and outcomes.

        Args:
            run_id: The ID of the run to audit.
            storage_path: Path to the directory where runs are stored.
        """
        return get_run_audit_trail(run_id, storage_path)
