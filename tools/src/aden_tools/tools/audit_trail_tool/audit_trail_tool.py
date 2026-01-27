"""
Audit Trail Tool - Track and record agent decisions over time.

Creates a timeline of agent decisions for debugging, compliance, and observability.
Stores decision history in JSON files for easy querying and export.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Optional

from fastmcp import FastMCP

# Default storage location for audit trails
DEFAULT_AUDIT_DIR = Path.home() / ".aden" / "audit_trails"


def _ensure_audit_dir(audit_dir: Path = DEFAULT_AUDIT_DIR) -> Path:
    """Ensure the audit trail directory exists."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    return audit_dir


def _get_audit_file_path(agent_id: str, audit_dir: Path = DEFAULT_AUDIT_DIR) -> Path:
    """Get the file path for an agent's audit trail."""
    _ensure_audit_dir(audit_dir)
    return audit_dir / f"{agent_id}_audit.json"


def _load_audit_trail(agent_id: str, audit_dir: Path = DEFAULT_AUDIT_DIR) -> list[dict[str, Any]]:
    """Load existing audit trail for an agent."""
    audit_file = _get_audit_file_path(agent_id, audit_dir)
    if not audit_file.exists():
        return []
    
    try:
        with open(audit_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_audit_trail(
    agent_id: str,
    decisions: list[dict[str, Any]],
    audit_dir: Path = DEFAULT_AUDIT_DIR,
) -> None:
    """Save audit trail to file."""
    audit_file = _get_audit_file_path(agent_id, audit_dir)
    with open(audit_file, "w", encoding="utf-8") as f:
        json.dump(decisions, f, indent=2, ensure_ascii=False)


def register_tools(mcp: FastMCP) -> None:
    """Register audit trail tools with the MCP server."""

    @mcp.tool()
    def record_decision(
        agent_id: str,
        decision_type: str,
        decision: str,
        context: Optional[str] = None,
        outcome: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        audit_dir: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Record an agent decision in the audit trail.

        Use this to track important decisions made by agents for debugging,
        compliance, and observability purposes.

        Args:
            agent_id: Unique identifier for the agent making the decision
            decision_type: Type of decision (e.g., "action", "retry", "escalate", "accept")
            decision: Description of the decision made
            context: Optional context or reasoning for the decision
            outcome: Optional outcome or result of the decision
            metadata: Optional additional metadata as a dictionary
            audit_dir: Optional custom directory for audit files (default: ~/.aden/audit_trails)

        Returns:
            Dict with success status and decision record
        """
        try:
            # Validate inputs
            if not agent_id or not agent_id.strip():
                return {"error": "agent_id is required"}
            if not decision_type or not decision_type.strip():
                return {"error": "decision_type is required"}
            if not decision or not decision.strip():
                return {"error": "decision description is required"}

            # Determine audit directory
            base_dir = Path(audit_dir) if audit_dir else DEFAULT_AUDIT_DIR

            # Load existing audit trail
            decisions = _load_audit_trail(agent_id, base_dir)

            # Create decision record
            decision_record: dict[str, Any] = {
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "agent_id": agent_id,
                "decision_type": decision_type,
                "decision": decision,
            }

            if context:
                decision_record["context"] = context
            if outcome:
                decision_record["outcome"] = outcome
            if metadata:
                decision_record["metadata"] = metadata

            # Add to audit trail
            decisions.append(decision_record)

            # Save audit trail
            _save_audit_trail(agent_id, decisions, base_dir)

            return {
                "success": True,
                "decision_id": len(decisions) - 1,
                "timestamp": decision_record["timestamp"],
                "message": f"Decision recorded for agent {agent_id}",
            }

        except Exception as e:
            return {"error": f"Failed to record decision: {str(e)}"}

    @mcp.tool()
    def get_audit_trail(
        agent_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        decision_type: Optional[str] = None,
        limit: int = 100,
        audit_dir: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Retrieve audit trail for an agent with optional filtering.

        Use this to query decision history for debugging, analysis, or compliance reporting.

        Args:
            agent_id: Unique identifier for the agent
            start_date: Optional start date filter (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            end_date: Optional end date filter (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            decision_type: Optional filter by decision type
            limit: Maximum number of decisions to return (default: 100, max: 1000)
            audit_dir: Optional custom directory for audit files (default: ~/.aden/audit_trails)

        Returns:
            Dict with filtered decisions and metadata
        """
        try:
            # Validate inputs
            if not agent_id or not agent_id.strip():
                return {"error": "agent_id is required"}
            if limit < 1 or limit > 1000:
                limit = max(1, min(1000, limit))

            # Determine audit directory
            base_dir = Path(audit_dir) if audit_dir else DEFAULT_AUDIT_DIR

            # Load audit trail
            decisions = _load_audit_trail(agent_id, base_dir)

            # Apply filters
            filtered = decisions.copy()

            # Filter by decision type
            if decision_type:
                filtered = [d for d in filtered if d.get("decision_type") == decision_type]

            # Filter by date range
            if start_date:
                try:
                    start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                    filtered = [
                        d
                        for d in filtered
                        if datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")) >= start_dt
                    ]
                except ValueError:
                    return {"error": f"Invalid start_date format: {start_date}. Use ISO format."}

            if end_date:
                try:
                    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    filtered = [
                        d
                        for d in filtered
                        if datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")) <= end_dt
                    ]
                except ValueError:
                    return {"error": f"Invalid end_date format: {end_date}. Use ISO format."}

            # Sort by timestamp (newest first) and limit
            filtered.sort(key=lambda x: x["timestamp"], reverse=True)
            filtered = filtered[:limit]

            return {
                "agent_id": agent_id,
                "total_decisions": len(decisions),
                "filtered_count": len(filtered),
                "decisions": filtered,
            }

        except Exception as e:
            return {"error": f"Failed to retrieve audit trail: {str(e)}"}

    @mcp.tool()
    def export_audit_trail(
        agent_id: str,
        output_format: str = "json",
        output_path: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        decision_type: Optional[str] = None,
        audit_dir: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Export audit trail to a file in JSON or CSV format.

        Use this to generate compliance reports or share decision history.

        Args:
            agent_id: Unique identifier for the agent
            output_format: Export format - "json" or "csv" (default: "json")
            output_path: Optional custom output file path (default: agent_id_audit_export.json/csv)
            start_date: Optional start date filter (ISO format)
            end_date: Optional end date filter (ISO format)
            decision_type: Optional filter by decision type
            audit_dir: Optional custom directory for audit files (default: ~/.aden/audit_trails)

        Returns:
            Dict with export status and file path
        """
        try:
            # Validate format
            if output_format not in ("json", "csv"):
                return {"error": "output_format must be 'json' or 'csv'"}

            # Get filtered audit trail using internal functions
            base_dir = Path(audit_dir) if audit_dir else DEFAULT_AUDIT_DIR
            decisions = _load_audit_trail(agent_id, base_dir)

            # Apply filters (same logic as get_audit_trail)
            filtered = decisions.copy()
            if decision_type:
                filtered = [d for d in filtered if d.get("decision_type") == decision_type]
            if start_date:
                try:
                    start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                    filtered = [
                        d
                        for d in filtered
                        if datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")) >= start_dt
                    ]
                except ValueError:
                    return {"error": f"Invalid start_date format: {start_date}. Use ISO format."}
            if end_date:
                try:
                    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    filtered = [
                        d
                        for d in filtered
                        if datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")) <= end_dt
                    ]
                except ValueError:
                    return {"error": f"Invalid end_date format: {end_date}. Use ISO format."}
            filtered.sort(key=lambda x: x["timestamp"], reverse=True)

            # Determine output path
            if not output_path:
                _ensure_audit_dir(base_dir)
                timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                ext = "csv" if output_format == "csv" else "json"
                output_path = str(base_dir / f"{agent_id}_audit_export_{timestamp}.{ext}")

            output_file = Path(output_path)

            # Export based on format
            if output_format == "json":
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "agent_id": agent_id,
                            "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                            "total_decisions": len(filtered),
                            "decisions": filtered,
                        },
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )
            else:  # CSV
                import csv

                if not filtered:
                    return {"error": "No decisions to export"}

                # Get all possible fields
                fieldnames = ["timestamp", "agent_id", "decision_type", "decision"]
                for decision in filtered:
                    if "context" in decision:
                        fieldnames.append("context")
                    if "outcome" in decision:
                        fieldnames.append("outcome")
                    if "metadata" in decision:
                        fieldnames.append("metadata")
                    break

                with open(output_file, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                    writer.writeheader()
                    for decision in filtered:
                        row = decision.copy()
                        # Convert metadata dict to string for CSV
                        if "metadata" in row and isinstance(row["metadata"], dict):
                            row["metadata"] = json.dumps(row["metadata"])
                        writer.writerow(row)

            return {
                "success": True,
                "output_path": str(output_file),
                "format": output_format,
                "decisions_exported": len(filtered),
                "message": f"Audit trail exported to {output_file}",
            }

        except Exception as e:
            return {"error": f"Failed to export audit trail: {str(e)}"}
