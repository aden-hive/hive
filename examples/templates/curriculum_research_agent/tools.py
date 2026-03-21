"""
Custom tool functions for Curriculum Research Agent.

Follows the ToolRegistry.discover_from_module() contract:
  - TOOLS: dict[str, Tool]  — tool definitions
  - tool_executor(tool_use)  — unified dispatcher

These tools provide curriculum-specific utilities for loading a brief
from a JSON file and saving the final content brief to the session's
data directory.
"""

from __future__ import annotations

import json

from framework.llm.provider import Tool, ToolResult, ToolUse
from framework.runner.tool_registry import _execution_context

# ---------------------------------------------------------------------------
# Tool definitions (auto-discovered by ToolRegistry.discover_from_module)
# ---------------------------------------------------------------------------

TOOLS = {
    "load_curriculum_brief": Tool(
        name="load_curriculum_brief",
        description=(
            "Load a curriculum brief JSON file containing topic, level, "
            "audience, and accreditation_context fields. Returns the "
            "parsed fields for use in the intake node."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "Absolute or relative path to a JSON file containing "
                        "the curriculum brief (topic, level, audience, "
                        "accreditation_context)."
                    ),
                },
            },
            "required": ["file_path"],
        },
    ),
    "save_curriculum_brief": Tool(
        name="save_curriculum_brief",
        description=(
            "Save the final content brief to a file in the session data "
            "directory. Returns the filename and character count."
        ),
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The full content brief text (markdown format).",
                },
                "filename": {
                    "type": "string",
                    "description": (
                        "Output filename (default: 'content_brief.md')."
                    ),
                },
            },
            "required": ["content"],
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
# Core implementations
# ---------------------------------------------------------------------------


def _load_curriculum_brief(file_path: str) -> dict:
    """Read a curriculum brief JSON file and return its fields.

    Args:
        file_path: Path to the JSON file.

    Returns:
        dict with ``topic``, ``level``, ``audience``, ``accreditation_context``.
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"error": f"File not found: {file_path}"}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}

    required_fields = ["topic", "level", "audience", "accreditation_context"]
    missing = [f for f in required_fields if f not in data]
    if missing:
        return {"error": f"Missing required fields: {', '.join(missing)}"}

    return {
        "topic": data["topic"],
        "level": data["level"],
        "audience": data["audience"],
        "accreditation_context": data["accreditation_context"],
    }


def _save_curriculum_brief(content: str, filename: str = "content_brief.md") -> dict:
    """Save the content brief to the session data directory.

    Args:
        content: The full brief text.
        filename: Output filename.

    Returns:
        dict with ``filename`` and ``chars``.
    """
    from pathlib import Path

    data_dir = _get_data_dir()
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    output_path = Path(data_dir) / filename

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return {"filename": filename, "chars": len(content)}


# ---------------------------------------------------------------------------
# Unified tool executor (auto-discovered by ToolRegistry.discover_from_module)
# ---------------------------------------------------------------------------


def tool_executor(tool_use: ToolUse) -> ToolResult:
    """Dispatch tool calls to their implementations."""
    if tool_use.name == "load_curriculum_brief":
        try:
            file_path = tool_use.input.get("file_path", "")
            result = _load_curriculum_brief(file_path=file_path)
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

    if tool_use.name == "save_curriculum_brief":
        try:
            content = tool_use.input.get("content", "")
            filename = tool_use.input.get("filename", "content_brief.md")
            result = _save_curriculum_brief(content=content, filename=filename)
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
