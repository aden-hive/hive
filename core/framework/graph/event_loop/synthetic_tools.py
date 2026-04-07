"""Synthetic tool builders for the event loop.

Factory functions that create ``Tool`` definitions for framework-level
synthetic tools (set_output, ask_user, escalate, delegate, report_to_parent).
Also includes the ``handle_set_output`` validation logic.

All functions are pure — they receive explicit parameters and return
``Tool`` or ``ToolResult`` objects with no side effects.
"""

from __future__ import annotations

from typing import Any

from framework.llm.provider import Tool, ToolResult


def build_ask_user_tool() -> Tool:
    """Build the synthetic ask_user tool for explicit user-input requests.

    The queen calls ask_user() when it needs to pause and wait
    for user input.  Text-only turns WITHOUT ask_user flow through without
    blocking, allowing progress updates and summaries to stream freely.
    """
    return Tool(
        name="ask_user",
        description=(
            "You MUST call this tool whenever you need the user's response. "
            "Always call it after greeting the user, asking a question, or "
            "requesting approval. Do NOT call it for status updates or "
            "summaries that don't require a response. "
            "Always include 2-3 predefined options. The UI automatically "
            "appends an 'Other' free-text input after your options, so NEVER "
            "include catch-all options like 'Custom idea', 'Something else', "
            "'Other', or 'None of the above' — the UI handles that. "
            "When the question primarily needs a typed answer but you must "
            "include options, make one option signal that typing is expected "
            "(e.g. 'I\\'ll type my response'). This helps users discover the "
            "free-text input. "
            "The ONLY exception: omit options when the question demands a "
            "free-form answer the user must type out (e.g. 'Describe your "
            "agent idea', 'Paste the error message'). "
            '{"question": "What would you like to do?", "options": '
            '["Build a new agent", "Modify existing agent", "Run tests"]} '
            "Free-form example: "
            '{"question": "Describe the agent you want to build."}'
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question or prompt shown to the user.",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "2-3 specific predefined choices. Include in most cases. "
                        'Example: ["Option A", "Option B", "Option C"]. '
                        "The UI always appends an 'Other' free-text input, so "
                        "do NOT include catch-alls like 'Custom idea' or 'Other'. "
                        "Omit ONLY when the user must type a free-form answer."
                    ),
                    "minItems": 2,
                    "maxItems": 3,
                },
            },
            "required": ["question"],
        },
    )


def build_ask_user_multiple_tool() -> Tool:
    """Build the synthetic ask_user_multiple tool for batched questions.

    Queen-only tool that presents multiple questions at once so the user
    can answer them all in a single interaction rather than one at a time.
    """
    return Tool(
        name="ask_user_multiple",
        description=(
            "Ask the user multiple questions at once. Use this instead of "
            "ask_user when you have 2 or more questions to ask in the same "
            "turn — it lets the user answer everything in one go rather than "
            "going back and forth. Each question can have its own predefined "
            "options (2-3 choices) or be free-form. The UI renders all "
            "questions together with a single Submit button. "
            "ALWAYS prefer this over ask_user when you have multiple things "
            "to clarify. "
            "IMPORTANT: Do NOT repeat the questions in your text response — "
            "the widget renders them. Keep your text to a brief intro only. "
            '{"questions": ['
            '  {"id": "scope", "prompt": "What scope?", "options": ["Full", "Partial"]},'
            '  {"id": "format", "prompt": "Output format?", "options": ["PDF", "CSV", "JSON"]},'
            '  {"id": "details", "prompt": "Any special requirements?"}'
            "]}"
        ),
        parameters={
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": (
                                    "Short identifier for this question (used in the response)."
                                ),
                            },
                            "prompt": {
                                "type": "string",
                                "description": "The question text shown to the user.",
                            },
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "2-3 predefined choices. The UI appends an "
                                    "'Other' free-text input automatically. "
                                    "Omit only when the user must type a free-form answer."
                                ),
                                "minItems": 2,
                                "maxItems": 3,
                            },
                        },
                        "required": ["id", "prompt"],
                    },
                    "minItems": 2,
                    "maxItems": 8,
                    "description": "List of questions to present to the user.",
                },
            },
            "required": ["questions"],
        },
    )


def build_set_output_tool(output_keys: list[str] | None) -> Tool | None:
    """Build the synthetic set_output tool for explicit output declaration."""
    if not output_keys:
        return None
    return Tool(
        name="set_output",
        description=(
            "Set an output value for this node. Call once per output key. "
            "Use this for brief notes, counts, status, and file references — "
            "NOT for large data payloads. When a tool result was saved to a "
            "data file, pass the filename as the value "
            "(e.g. 'google_sheets_get_values_1.txt') so the next phase can "
            "load the full data. Values exceeding ~2000 characters are "
            "auto-saved to data files. "
            f"Valid keys: {output_keys}"
        ),
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": f"Output key. Must be one of: {output_keys}",
                    "enum": output_keys,
                },
                "value": {
                    "type": "string",
                    "description": (
                        "The output value — a brief note, count, status, "
                        "or data filename reference."
                    ),
                },
            },
            "required": ["key", "value"],
        },
    )


def build_escalate_tool() -> Tool:
    """Build the synthetic escalate tool for worker -> queen handoff."""
    return Tool(
        name="escalate",
        description=(
            "Escalate to the queen when requesting user input, "
            "blocked by errors, missing "
            "credentials, or ambiguous constraints that require supervisor "
            "guidance. Include a concise reason and optional context. "
            "The node will pause until the queen injects guidance."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": (
                        "Short reason for escalation (e.g. 'Tool repeatedly failing')."
                    ),
                },
                "context": {
                    "type": "string",
                    "description": "Optional diagnostic details for the queen.",
                },
            },
            "required": ["reason"],
        },
    )


def build_delegate_tool(sub_agents: list[str], node_registry: dict[str, Any]) -> Tool | None:
    """Build the synthetic delegate_to_sub_agent tool for subagent invocation.

    Args:
        sub_agents: List of node IDs that can be invoked as subagents.
        node_registry: Map of node_id -> NodeSpec for looking up subagent descriptions.

    Returns:
        Tool definition if sub_agents is non-empty, None otherwise.
    """
    if not sub_agents:
        return None

    agent_descriptions = []
    for agent_id in sub_agents:
        spec = node_registry.get(agent_id)
        if spec:
            desc = getattr(spec, "description", "(no description)")
            agent_descriptions.append(f"- {agent_id}: {desc}")
        else:
            agent_descriptions.append(f"- {agent_id}: (not found in registry)")

    return Tool(
        name="delegate_to_sub_agent",
        description=(
            "Delegate a task to a specialized sub-agent. The sub-agent runs "
            "autonomously with read-only access to current memory and returns "
            "its result. Use this to parallelize work or leverage specialized capabilities.\n\n"
            "Available sub-agents:\n" + "\n".join(agent_descriptions)
        ),
        parameters={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": f"The sub-agent to invoke. Must be one of: {sub_agents}",
                    "enum": sub_agents,
                },
                "task": {
                    "type": "string",
                    "description": (
                        "The task description for the sub-agent to execute. "
                        "Be specific about what you want the sub-agent to do and "
                        "what information to return."
                    ),
                },
            },
            "required": ["agent_id", "task"],
        },
    )


def build_report_to_parent_tool() -> Tool:
    """Build the synthetic report_to_parent tool for sub-agent progress reports.

    Sub-agents call this to send one-way progress updates, partial findings,
    or status reports to the parent node (and external observers via event bus)
    without blocking execution.

    When ``wait_for_response`` is True, the sub-agent blocks until the parent
    relays the user's response — used for escalation (e.g. login pages, CAPTCHAs).

    When ``mark_complete`` is True, the sub-agent terminates immediately after
    sending the report — no need to call set_output for each output key.
    """
    return Tool(
        name="report_to_parent",
        description=(
            "Send a report to the parent agent. By default this is fire-and-forget: "
            "the parent receives the report but does not respond. "
            "Set wait_for_response=true to BLOCK until the user replies — use this "
            "when you need human intervention (e.g. login pages, CAPTCHAs, "
            "authentication walls). The user's response is returned as the tool result. "
            "Set mark_complete=true to finish your task and terminate immediately "
            "after sending the report — use this when your findings are in the "
            "message/data fields and you don't need to call set_output."
        ),
        parameters={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "A human-readable status or progress message.",
                },
                "data": {
                    "type": "object",
                    "description": "Optional structured data to include with the report.",
                },
                "wait_for_response": {
                    "type": "boolean",
                    "description": (
                        "If true, block execution until the user responds. "
                        "Use for escalation scenarios requiring human intervention."
                    ),
                    "default": False,
                },
                "mark_complete": {
                    "type": "boolean",
                    "description": (
                        "If true, terminate the sub-agent immediately after sending "
                        "this report. The report message and data are delivered to the "
                        "parent as the final result. No set_output calls are needed."
                    ),
                    "default": False,
                },
            },
            "required": ["message"],
        },
    )


def handle_set_output(
    tool_input: dict[str, Any],
    output_keys: list[str] | None,
) -> ToolResult:
    """Handle set_output tool call. Returns ToolResult (sync)."""
    import logging
    import re

    logger = logging.getLogger(__name__)

    key = tool_input.get("key", "")
    value = tool_input.get("value", "")
    valid_keys = output_keys or []

    # Recover from truncated JSON (max_tokens hit mid-argument).
    # The _raw key is set by litellm when json.loads fails.
    if not key and "_raw" in tool_input:
        raw = tool_input["_raw"]
        key_match = re.search(r'"key"\s*:\s*"(\w+)"', raw)
        if key_match:
            key = key_match.group(1)
        val_match = re.search(r'"value"\s*:\s*"', raw)
        if val_match:
            start = val_match.end()
            value = raw[start:].rstrip()
            for suffix in ('"}\n', '"}', '"'):
                if value.endswith(suffix):
                    value = value[: -len(suffix)]
                    break
        if key:
            logger.warning(
                "Recovered set_output args from truncated JSON: key=%s, value_len=%d",
                key,
                len(value),
            )
            # Re-inject so the caller sees proper key/value
            tool_input["key"] = key
            tool_input["value"] = value

    if key not in valid_keys:
        return ToolResult(
            tool_use_id="",
            content=f"Invalid output key '{key}'. Valid keys: {valid_keys}",
            is_error=True,
        )

    return ToolResult(
        tool_use_id="",
        content=f"Output '{key}' set successfully.",
        is_error=False,
    )
