"""
Custom tool functions for SDR Agent.

Follows the ToolRegistry.discover_from_module() contract:
  - TOOLS: dict[str, Tool]  — tool definitions
  - tool_executor(tool_use)  — unified dispatcher

These tools provide SDR-specific utilities for loading contact data
from a JSON file and writing it to the session's data directory for
downstream nodes to process via the standard load_data/append_data tools.
"""

from __future__ import annotations

import json

from framework.llm.provider import Tool, ToolResult, ToolUse
from framework.runner.tool_registry import _execution_context

# ---------------------------------------------------------------------------
# Tool definitions (auto-discovered by ToolRegistry.discover_from_module)
# ---------------------------------------------------------------------------

TOOLS = {
    "load_contacts_from_file": Tool(
        name="load_contacts_from_file",
        description=(
            "Load a contacts JSON file from an absolute or relative path "
            "and write its contents to contacts.jsonl in the session data directory. "
            "Returns the number of contacts loaded and the output filename."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "Absolute or relative path to a JSON file containing "
                        "a list of contact objects."
                    ),
                },
            },
            "required": ["file_path"],
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
        raise RuntimeError(
            "data_dir not set in execution context. "
            "Is the tool running inside a GraphExecutor?"
        )
    return ctx["data_dir"]


# ---------------------------------------------------------------------------
# Core implementation
# ---------------------------------------------------------------------------


def _load_contacts_from_file(file_path: str) -> dict:
    """Read a contacts JSON file and write it as contacts.jsonl to data_dir.

    Args:
        file_path: Path to the contacts JSON file.

    Returns:
        dict with ``filename`` (always ``"contacts.jsonl"``) and ``count``.
    """
    from pathlib import Path

    data_dir = _get_data_dir()
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    output_path = Path(data_dir) / "contacts.jsonl"

    try:
        with open(file_path, encoding="utf-8") as f:
            contacts = json.load(f)
    except FileNotFoundError:
        return {"error": f"File not found: {file_path}"}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    if not isinstance(contacts, list):
        contacts = [contacts]

    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for contact in contacts:
            f.write(json.dumps(contact, ensure_ascii=False) + "\n")
            count += 1

    return {"filename": "contacts.jsonl", "count": count}


# ---------------------------------------------------------------------------
# Unified tool executor (auto-discovered by ToolRegistry.discover_from_module)
# ---------------------------------------------------------------------------


def tool_executor(tool_use: ToolUse) -> ToolResult:
    """Dispatch tool calls to their implementations."""
    if tool_use.name == "load_contacts_from_file":
        try:
            file_path = tool_use.input.get("file_path", "")
            result = _load_contacts_from_file(file_path=file_path)
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
