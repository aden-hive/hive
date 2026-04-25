"""
Custom tools for Sales Ops Agent.

Provides demo mode support with mock data loading, plus standard data
management tools (load_data, append_data) for reading and writing JSONL files
in the session data directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from framework.llm.provider import Tool, ToolResult, ToolUse
from framework.loader.tool_registry import _execution_context

# ---------------------------------------------------------------------------
# Tool definitions (auto-discovered by ToolRegistry.discover_from_module)
# ---------------------------------------------------------------------------

TOOLS = {
    "load_data": Tool(
        name="load_data",
        description=(
            "Load data from a JSONL file in the session data directory. "
            "Returns the file contents with has_more flag for pagination. "
            "Use offset and limit to navigate through large files."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the JSONL file to load (e.g., 'sales_data.jsonl').",
                },
                "offset": {
                    "type": "integer",
                    "description": "Zero-based record offset for pagination. Use the next_offset from the previous call to get the next page.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of records to return. Default is 10.",
                },
            },
            "required": ["filename"],
        },
    ),
    "append_data": Tool(
        name="append_data",
        description=(
            "Append a JSON-serializable object to a JSONL file in the session data directory. "
            "Creates the file if it doesn't exist. Returns success confirmation."
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the JSONL file to append to (e.g., 'sales_data.jsonl').",
                },
                "data": {
                    "type": "object",
                    "description": "JSON-serializable object to write as a line in the file.",
                },
            },
            "required": ["filename", "data"],
        },
    ),
    "load_demo_sales_data": Tool(
        name="load_demo_sales_data",
        description=(
            "Load mock sales data from demo_data.json for demonstration/testing. "
            "Returns sales representatives with their metrics and unassigned account pool. "
            "Use only when crm_type is 'demo'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "data_file": {
                    "type": "string",
                    "description": "Path to demo_data.json file (optional, uses default if not provided).",
                },
            },
            "required": [],
        },
    ),
    "demo_log_action": Tool(
        name="demo_log_action",
        description=(
            "Log a rebalance action in demo mode (writes to demo_rebalance_log.json). "
            "Use only when crm_type is 'demo' instead of actual CRM logging."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "JSON string of the rebalance action to log.",
                },
            },
            "required": ["action"],
        },
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_data_dir() -> str:
    """Get the session-scoped data_dir from ToolRegistry execution context."""
    ctx = _execution_context.get()
    if not ctx or "data_dir" not in ctx:
        raise RuntimeError("data_dir not set in execution context. Is the tool running inside a Orchestrator?")
    return ctx["data_dir"]


def _resolve_safe_path(filename: str) -> Path:
    """Resolve a user-supplied filename safely within the data directory.

    Prevents path traversal attacks by ensuring the resolved path is within
    the session data directory.

    Args:
        filename: User-supplied filename (may contain path traversal attempts)

    Returns:
        Resolved Path within data_dir

    Raises:
        ValueError: If the path would escape the data directory
    """
    data_dir = _get_data_dir()
    data_dir_path = Path(data_dir).resolve()

    # Join with data_dir and resolve to handle any ".." or absolute paths
    resolved_path = (data_dir_path / filename).resolve()

    # Verify the resolved path is within data_dir
    try:
        resolved_path.relative_to(data_dir_path)
    except ValueError:
        raise ValueError(
            f"Path traversal detected: '{filename}' resolves outside the data directory. "
            f"Only files within {data_dir_path} are accessible."
        )

    return resolved_path


# ---------------------------------------------------------------------------
# Core implementation
# ---------------------------------------------------------------------------


def _load_data(filename: str, offset: int = 0, limit: int = 10) -> dict:
    """Load data from a JSONL file in the session data directory.

    Args:
        filename: Name of the JSONL file to load.
        offset: Zero-based record offset for pagination.
        limit: Maximum number of records to return.

    Returns:
        dict with records list, has_more pagination flag, total count, and next_offset.
    """
    try:
        file_path = _resolve_safe_path(filename)
    except ValueError as e:
        return {"error": str(e), "records": [], "has_more": False, "total": 0, "next_offset": None}

    if not file_path.exists():
        return {"error": f"File not found: {filename}", "records": [], "has_more": False, "total": 0, "next_offset": None}

    try:
        records = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        total = len(records)
        page = records[offset : offset + limit]
        next_offset = offset + len(page) if page else None
        has_more = offset + len(page) < total

        return {
            "records": page,
            "has_more": has_more,
            "total": total,
            "next_offset": next_offset,
        }
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON in file: {e}", "records": [], "has_more": False, "total": 0, "next_offset": None}
    except Exception as e:
        return {"error": f"Error reading file: {e}", "records": [], "has_more": False, "total": 0, "next_offset": None}


def _append_data(filename: str, data: dict) -> dict:
    """Append a JSON-serializable object to a JSONL file.

    Args:
        filename: Name of the JSONL file to append to.
        data: JSON-serializable object to write.

    Returns:
        dict with success status and record count.
    """
    try:
        file_path = _resolve_safe_path(filename)
    except ValueError as e:
        return {"error": str(e)}

    # Ensure data directory exists
    file_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

        # Count total records
        count = 0
        if file_path.exists():
            with open(file_path, "r") as f:
                for line in f:
                    if line.strip():
                        count += 1

        return {"success": True, "filename": filename, "total_records": count}
    except Exception as e:
        return {"error": f"Error writing to file: {e}"}


def _load_demo_sales_data(data_file: str = "") -> dict:
    """Load mock sales data from demo_data.json.

    Args:
        data_file: Optional path to demo data file. Must be within the agent directory.

    Returns:
        dict with sales_reps and unassigned_accounts.
    """
    # If no file specified, use the default demo_data.json
    if not data_file:
        agent_dir = Path(__file__).parent.resolve()
        demo_file = agent_dir / "demo_data.json"
    else:
        # Validate user-provided path is within agent directory
        agent_dir = Path(__file__).parent.resolve()
        requested_file = (agent_dir / data_file).resolve()
        try:
            requested_file.relative_to(agent_dir)
            demo_file = requested_file
        except ValueError:
            return {"error": f"Path traversal detected: '{data_file}' is outside the agent directory", "sales_reps": [], "unassigned_accounts": []}

    if not demo_file.exists():
        return {"error": f"Demo data file not found: {demo_file}", "sales_reps": [], "unassigned_accounts": []}

    try:
        with open(demo_file, encoding="utf-8") as f:
            data = json.load(f)

        # Write to session data directory for downstream nodes
        data_dir = _get_data_dir()
        # Ensure data directory exists before writing
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        # Write sales reps
        sales_file = Path(data_dir) / "demo_sales_reps.jsonl"
        with open(sales_file, "w", encoding="utf-8") as f:
            for rep in data.get("sales_reps", []):
                f.write(json.dumps(rep, ensure_ascii=False) + "\n")

        # Write unassigned accounts
        accounts_file = Path(data_dir) / "demo_unassigned_accounts.jsonl"
        with open(accounts_file, "w", encoding="utf-8") as f:
            for acct in data.get("unassigned_accounts", []):
                f.write(json.dumps(acct, ensure_ascii=False) + "\n")

        return {
            "sales_reps_file": "demo_sales_reps.jsonl",
            "unassigned_accounts_file": "demo_unassigned_accounts.jsonl",
            "total_reps": len(data.get("sales_reps", [])),
            "total_unassigned": len(data.get("unassigned_accounts", [])),
        }
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON in demo data file: {e}", "sales_reps": [], "unassigned_accounts": []}
    except Exception as e:
        return {"error": f"Error loading demo data: {e}", "sales_reps": [], "unassigned_accounts": []}


def _demo_log_action(action: str) -> dict:
    """Log a rebalance action in demo mode.

    Args:
        action: JSON string of the rebalance action.

    Returns:
        dict with logging status.
    """
    data_dir = _get_data_dir()
    log_file = Path(data_dir) / "demo_rebalance_log.jsonl"

    try:
        action_data = json.loads(action) if isinstance(action, str) else action

        # Add timestamp if not present
        if "timestamp" not in action_data:
            from datetime import datetime

            action_data["timestamp"] = datetime.now().isoformat()

        action_data["crm_type"] = "demo"
        action_data["logged"] = True

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(action_data, ensure_ascii=False) + "\n")

        return {"status": "logged", "file": "demo_rebalance_log.jsonl", "action": action_data}
    except Exception as e:
        return {"error": f"Error logging action: {e}"}


# ---------------------------------------------------------------------------
# Unified tool executor (auto-discovered by ToolRegistry.discover_from_module)
# ---------------------------------------------------------------------------


def tool_executor(tool_use: ToolUse) -> ToolResult:
    """Dispatch tool calls to their implementations."""
    if tool_use.name == "load_data":
        try:
            filename = tool_use.input.get("filename", "")
            offset = tool_use.input.get("offset", 0)
            limit = tool_use.input.get("limit", 10)
            result = _load_data(filename=filename, offset=offset, limit=limit)
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps(result),
                is_error="error" in result,
            )
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps({"error": str(e)}),
                is_error=True,
            )

    if tool_use.name == "append_data":
        try:
            filename = tool_use.input.get("filename", "")
            data = tool_use.input.get("data", {})
            result = _append_data(filename=filename, data=data)
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps(result),
                is_error="error" in result,
            )
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps({"error": str(e)}),
                is_error=True,
            )

    if tool_use.name == "load_demo_sales_data":
        try:
            data_file = tool_use.input.get("data_file", "")
            result = _load_demo_sales_data(data_file=data_file)
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps(result),
                is_error="error" in result,
            )
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps({"error": str(e)}),
                is_error=True,
            )

    if tool_use.name == "demo_log_action":
        try:
            action = tool_use.input.get("action", "")
            result = _demo_log_action(action)
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps(result),
                is_error="error" in result,
            )
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps({"error": str(e)}),
                is_error=True,
            )

    return ToolResult(
        tool_use_id=tool_use.id,
        content=json.dumps({"error": f"Unknown tool: {tool_use.name}"}),
        is_error=True,
    )
