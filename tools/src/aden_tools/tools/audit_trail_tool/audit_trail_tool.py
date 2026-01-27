"""
Audit Trail Tool - Generate compliance-friendly decision timelines.

Provides tools for:
- Generating audit trails from agent runs
- Querying decision history
- Exporting audit reports in various formats

Usage:
    # Register with MCP server
    from audit_trail_tool import register_tools
    register_tools(mcp)
    
    # Then use via MCP:
    # - generate_audit_trail: Create an audit report from a run
    # - get_decision_timeline: Get chronological decision list
    # - export_audit_report: Export to JSON/CSV/Markdown
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Annotated

from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register audit trail tools with the MCP server."""

    @mcp.tool()
    def generate_audit_trail(
        run_id: Annotated[str, "The ID of the run to generate audit trail for"],
        storage_path: Annotated[str, "Path to the storage directory (default: ./storage)"] = "./storage",
        include_decisions: Annotated[bool, "Include detailed decision records"] = True,
        include_metrics: Annotated[bool, "Include performance metrics"] = True,
    ) -> str:
        """
        Generate a comprehensive audit trail for an agent run.
        
        Returns a structured audit report including:
        - Run metadata (goal, timing, outcome)
        - Decision timeline with reasoning
        - Performance metrics
        - Any problems or violations
        
        Use this for compliance, debugging, or analysis.
        """
        try:
            storage = Path(storage_path)
            run_file = storage / "runs" / f"{run_id}.json"
            
            if not run_file.exists():
                return json.dumps({
                    "error": f"Run not found: {run_id}",
                    "hint": f"Check that the run exists in {storage_path}/runs/",
                })
            
            with open(run_file) as f:
                run_data = json.load(f)
            
            # Build audit trail
            audit_trail = {
                "audit_report": {
                    "generated_at": datetime.now().isoformat(),
                    "run_id": run_id,
                    "report_type": "agent_execution_audit",
                },
                "run_summary": {
                    "goal_id": run_data.get("goal_id"),
                    "goal_description": run_data.get("goal_description"),
                    "status": run_data.get("status"),
                    "started_at": run_data.get("started_at"),
                    "completed_at": run_data.get("completed_at"),
                    "duration_ms": run_data.get("metrics", {}).get("duration_ms"),
                    "narrative": run_data.get("narrative"),
                },
                "input_output": {
                    "input_data": run_data.get("input_data", {}),
                    "output_data": run_data.get("output_data", {}),
                },
            }
            
            # Add decisions if requested
            if include_decisions:
                decisions = run_data.get("decisions", [])
                audit_trail["decision_timeline"] = [
                    {
                        "decision_id": d.get("id"),
                        "node_id": d.get("node_id"),
                        "timestamp": d.get("timestamp"),
                        "intent": d.get("intent"),
                        "options_considered": len(d.get("options", [])),
                        "chosen_option": d.get("chosen_option_id"),
                        "reasoning": d.get("reasoning"),
                        "outcome": d.get("outcome", {}).get("success") if d.get("outcome") else None,
                    }
                    for d in decisions
                ]
                audit_trail["decision_count"] = len(decisions)
            
            # Add metrics if requested
            if include_metrics:
                metrics = run_data.get("metrics", {})
                audit_trail["performance_metrics"] = {
                    "total_tokens": metrics.get("total_tokens", 0),
                    "total_cost_usd": metrics.get("total_cost_usd", 0),
                    "duration_ms": metrics.get("duration_ms", 0),
                    "nodes_executed": metrics.get("nodes_executed", []),
                    "tools_used": metrics.get("tools_used", []),
                }
            
            # Add problems
            problems = run_data.get("problems", [])
            if problems:
                audit_trail["problems"] = problems
            
            return json.dumps(audit_trail, indent=2, default=str)
            
        except Exception as e:
            return json.dumps({"error": f"Failed to generate audit trail: {e}"})

    @mcp.tool()
    def get_decision_timeline(
        run_id: Annotated[str, "The ID of the run"],
        storage_path: Annotated[str, "Path to the storage directory"] = "./storage",
        node_filter: Annotated[str, "Filter to specific node ID (optional)"] = "",
    ) -> str:
        """
        Get a chronological timeline of decisions made during a run.
        
        Returns a list of decisions with:
        - What the agent was trying to do
        - What options it considered
        - What it chose and why
        - Whether it worked
        
        Useful for understanding agent behavior and debugging.
        """
        try:
            storage = Path(storage_path)
            run_file = storage / "runs" / f"{run_id}.json"
            
            if not run_file.exists():
                return json.dumps({"error": f"Run not found: {run_id}"})
            
            with open(run_file) as f:
                run_data = json.load(f)
            
            decisions = run_data.get("decisions", [])
            
            # Filter by node if specified
            if node_filter:
                decisions = [d for d in decisions if d.get("node_id") == node_filter]
            
            # Build timeline
            timeline = []
            for i, d in enumerate(decisions, 1):
                options = d.get("options", [])
                chosen_id = d.get("chosen_option_id")
                chosen_option = next((o for o in options if o.get("id") == chosen_id), None)
                
                timeline.append({
                    "step": i,
                    "decision_id": d.get("id"),
                    "node_id": d.get("node_id"),
                    "timestamp": d.get("timestamp"),
                    "intent": d.get("intent"),
                    "options": [
                        {
                            "id": o.get("id"),
                            "description": o.get("description"),
                            "was_chosen": o.get("id") == chosen_id,
                        }
                        for o in options
                    ],
                    "chosen": {
                        "option_id": chosen_id,
                        "description": chosen_option.get("description") if chosen_option else None,
                    },
                    "reasoning": d.get("reasoning"),
                    "outcome": {
                        "success": d.get("outcome", {}).get("success"),
                        "summary": d.get("outcome", {}).get("summary"),
                    } if d.get("outcome") else None,
                })
            
            return json.dumps({
                "run_id": run_id,
                "total_decisions": len(timeline),
                "node_filter": node_filter or None,
                "timeline": timeline,
            }, indent=2, default=str)
            
        except Exception as e:
            return json.dumps({"error": f"Failed to get decision timeline: {e}"})

    @mcp.tool()
    def export_audit_report(
        run_id: Annotated[str, "The ID of the run"],
        storage_path: Annotated[str, "Path to the storage directory"] = "./storage",
        output_format: Annotated[str, "Output format: 'json', 'markdown', or 'csv'"] = "markdown",
        output_file: Annotated[str, "Output file path (optional, returns content if not provided)"] = "",
    ) -> str:
        """
        Export an audit report in the specified format.
        
        Formats:
        - json: Structured JSON for programmatic use
        - markdown: Human-readable document
        - csv: Spreadsheet-compatible decision log
        
        Can either return the content or write to a file.
        """
        try:
            storage = Path(storage_path)
            run_file = storage / "runs" / f"{run_id}.json"
            
            if not run_file.exists():
                return json.dumps({"error": f"Run not found: {run_id}"})
            
            with open(run_file) as f:
                run_data = json.load(f)
            
            content = ""
            
            if output_format == "json":
                content = json.dumps(run_data, indent=2, default=str)
                
            elif output_format == "markdown":
                content = _format_markdown_report(run_data)
                
            elif output_format == "csv":
                content = _format_csv_decisions(run_data)
                
            else:
                return json.dumps({"error": f"Unknown format: {output_format}. Use 'json', 'markdown', or 'csv'"})
            
            # Write to file if specified
            if output_file:
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(content)
                return json.dumps({
                    "success": True,
                    "output_file": str(output_path),
                    "format": output_format,
                    "size_bytes": len(content),
                })
            
            return content
            
        except Exception as e:
            return json.dumps({"error": f"Failed to export audit report: {e}"})

    @mcp.tool()
    def list_runs(
        storage_path: Annotated[str, "Path to the storage directory"] = "./storage",
        goal_id: Annotated[str, "Filter to specific goal (optional)"] = "",
        status: Annotated[str, "Filter by status: 'completed', 'failed', 'running' (optional)"] = "",
        limit: Annotated[int, "Maximum number of runs to return"] = 20,
    ) -> str:
        """
        List available runs for audit.
        
        Returns run IDs with basic metadata for filtering and selection.
        Use this to find runs before generating detailed audit trails.
        """
        try:
            storage = Path(storage_path)
            runs_dir = storage / "runs"
            
            if not runs_dir.exists():
                return json.dumps({
                    "error": "No runs directory found",
                    "hint": f"Check that {storage_path}/runs/ exists",
                })
            
            runs = []
            for run_file in sorted(runs_dir.glob("*.json"), reverse=True):
                if len(runs) >= limit:
                    break
                    
                try:
                    with open(run_file) as f:
                        run_data = json.load(f)
                    
                    # Apply filters
                    if goal_id and run_data.get("goal_id") != goal_id:
                        continue
                    if status and run_data.get("status") != status:
                        continue
                    
                    runs.append({
                        "run_id": run_data.get("id"),
                        "goal_id": run_data.get("goal_id"),
                        "status": run_data.get("status"),
                        "started_at": run_data.get("started_at"),
                        "decision_count": len(run_data.get("decisions", [])),
                    })
                    
                except Exception:
                    continue
            
            return json.dumps({
                "total_found": len(runs),
                "limit": limit,
                "filters": {
                    "goal_id": goal_id or None,
                    "status": status or None,
                },
                "runs": runs,
            }, indent=2, default=str)
            
        except Exception as e:
            return json.dumps({"error": f"Failed to list runs: {e}"})


def _format_markdown_report(run_data: dict) -> str:
    """Format run data as a Markdown report."""
    lines = [
        f"# Agent Run Audit Report",
        f"",
        f"**Run ID:** {run_data.get('id')}",
        f"**Generated:** {datetime.now().isoformat()}",
        f"",
        f"## Summary",
        f"",
        f"| Property | Value |",
        f"|----------|-------|",
        f"| Goal | {run_data.get('goal_description', 'N/A')} |",
        f"| Status | {run_data.get('status', 'N/A')} |",
        f"| Started | {run_data.get('started_at', 'N/A')} |",
        f"| Completed | {run_data.get('completed_at', 'N/A')} |",
        f"",
        f"## Narrative",
        f"",
        f"{run_data.get('narrative', 'No narrative provided.')}",
        f"",
    ]
    
    # Decisions
    decisions = run_data.get("decisions", [])
    if decisions:
        lines.extend([
            f"## Decision Timeline",
            f"",
            f"| # | Node | Intent | Chosen | Outcome |",
            f"|---|------|--------|--------|---------|",
        ])
        
        for i, d in enumerate(decisions, 1):
            outcome = d.get("outcome", {})
            outcome_str = "✓" if outcome.get("success") else "✗" if outcome.get("success") is False else "—"
            lines.append(
                f"| {i} | {d.get('node_id', 'N/A')} | {d.get('intent', 'N/A')[:50]} | {d.get('chosen_option_id', 'N/A')} | {outcome_str} |"
            )
        
        lines.append("")
    
    # Metrics
    metrics = run_data.get("metrics", {})
    if metrics:
        lines.extend([
            f"## Performance Metrics",
            f"",
            f"- **Total Tokens:** {metrics.get('total_tokens', 0):,}",
            f"- **Total Cost:** ${metrics.get('total_cost_usd', 0):.4f}",
            f"- **Duration:** {metrics.get('duration_ms', 0):,}ms",
            f"",
        ])
    
    # Problems
    problems = run_data.get("problems", [])
    if problems:
        lines.extend([
            f"## Problems",
            f"",
        ])
        for p in problems:
            lines.append(f"- **{p.get('severity', 'unknown')}:** {p.get('description', 'No description')}")
        lines.append("")
    
    return "\n".join(lines)


def _format_csv_decisions(run_data: dict) -> str:
    """Format decisions as CSV."""
    lines = ["decision_id,node_id,timestamp,intent,chosen_option,reasoning,success"]
    
    for d in run_data.get("decisions", []):
        outcome = d.get("outcome", {})
        success = "true" if outcome.get("success") else "false" if outcome.get("success") is False else ""
        
        # Escape CSV fields
        intent = (d.get("intent") or "").replace('"', '""')
        reasoning = (d.get("reasoning") or "").replace('"', '""')
        
        lines.append(
            f'"{d.get("id", "")}","{d.get("node_id", "")}","{d.get("timestamp", "")}",'
            f'"{intent}","{d.get("chosen_option_id", "")}","{reasoning}","{success}"'
        )
    
    return "\n".join(lines)
