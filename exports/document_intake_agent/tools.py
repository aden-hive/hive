"""
Custom tools for the Document Intake Agent.
Each tool implements document processing functionality that can be called
by the agent nodes during execution.
"""

import os
import time
import uuid
import json
from pathlib import Path
from typing import Dict, Any, Tuple, List

from framework.llm.provider import Tool, ToolResult, ToolUse
from framework.runner.tool_registry import _execution_context


# Tool definitions (auto-discovered by ToolRegistry.discover_from_module)
TOOLS = {
    "save_data": Tool(
        name="save_data",
        description="Save data to persistent storage for the session",
        parameters={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Storage key"},
                "data": {"type": "object", "description": "Data to save"}
            },
            "required": ["key", "data"]
        }
    ),
    "load_data": Tool(
        name="load_data",
        description="Load data from persistent storage",
        parameters={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Storage key"}
            },
            "required": ["key"]
        }
    )
}


def _get_data_dir() -> str:
    """Get the session-scoped data_dir from ToolRegistry execution context."""
    ctx = _execution_context.get()
    if not ctx or "data_dir" not in ctx:
        raise RuntimeError(
            "data_dir not set in execution context. "
            "Is the tool running inside a GraphExecutor?"
        )
    return ctx["data_dir"]


def _save_data(key: str, data: Any) -> dict:
    """Save data to session storage."""
    data_dir = _get_data_dir()
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    storage_file = Path(data_dir) / f"{key}.json"
    with open(storage_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return {
        "success": True,
        "key": key,
        "file": str(storage_file),
        "size_bytes": storage_file.stat().st_size
    }


def _load_data(key: str) -> dict:
    """Load data from session storage."""
    data_dir = _get_data_dir()
    storage_file = Path(data_dir) / f"{key}.json"

    if not storage_file.exists():
        return {"success": False, "error": f"Key '{key}' not found"}

    try:
        with open(storage_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": f"Failed to load '{key}': {str(e)}"}


def tool_executor(tool_use: ToolUse) -> ToolResult:
    """Dispatch tool calls to their implementations."""
    try:
        if tool_use.name == "save_data":
            result = _save_data(
                key=tool_use.input.get("key"),
                data=tool_use.input.get("data")
            )
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps(result),
                is_error=False,
            )

        elif tool_use.name == "load_data":
            result = _load_data(
                key=tool_use.input.get("key")
            )
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps(result),
                is_error=False,
            )

        else:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps({"error": f"Unknown tool: {tool_use.name}"}),
                is_error=True,
            )

    except Exception as e:
        return ToolResult(
            tool_use_id=tool_use.id,
            content=json.dumps({"error": str(e)}),
            is_error=True,
        )