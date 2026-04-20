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


def sanitize_ask_user_inputs(
    raw_question: Any,
    raw_options: Any,
) -> tuple[str, list[str] | None]:
    """Self-heal a malformed ``ask_user`` tool call.

    Some model families (notably when the system prompt teaches them
    XML-ish scratchpad tags like ``<relationship>...</relationship>``)
    carry that style into tool arguments and produce calls like::

        ask_user({
            "question": "What now?</question>\\n_OPTIONS: [\\"A\\", \\"B\\"]"
        })

    Symptoms:
    - The chat UI renders ``</question>`` and ``_OPTIONS: [...]`` as
      literal text in the question bubble.
    - No buttons appear because the real ``options`` parameter is
      empty.

    This function:
    - Strips leading/trailing whitespace.
    - Removes a trailing ``</question>`` (with optional preceding
      whitespace) from the question text.
    - Detects an inline ``_OPTIONS:``, ``OPTIONS:``, or ``options:``
      line followed by a JSON array, parses it, and returns the
      recovered list as the second element.
    - Removes the parsed line from the returned question text.

    Returns ``(cleaned_question, recovered_options_or_None)``. The
    caller should treat the recovered list as a fallback only when
    the model did not also supply a real ``options`` array.
    """
    import json as _json
    import re as _re

    if raw_question is None:
        return "", None
    q = str(raw_question)

    # Strip a stray </question> tag (case-insensitive, with optional
    # preceding whitespace) anywhere in the string. This is the most
    # common failure mode and never represents valid content.
    q = _re.sub(r"\s*</\s*question\s*>\s*", "\n", q, flags=_re.IGNORECASE)

    # Look for an inline options line. Match _OPTIONS, OPTIONS, options
    # (with or without leading underscore), followed by ':' or '=', then
    # a JSON array on the same line OR on the next line.
    inline_options_re = _re.compile(
        r"(?im)^\s*_?options\s*[:=]\s*(\[.*?\])\s*$",
        _re.DOTALL,
    )

    recovered: list[str] | None = None
    match = inline_options_re.search(q)
    if match is not None:
        try:
            parsed = _json.loads(match.group(1))
            if isinstance(parsed, list):
                cleaned = [str(o).strip() for o in parsed if str(o).strip()]
                if 1 <= len(cleaned) <= 8:
                    recovered = cleaned
        except (ValueError, TypeError):
            pass
        if recovered is not None:
            # Remove the parsed line so it doesn't leak into the
            # rendered question text.
            q = inline_options_re.sub("", q, count=1)

    # Strip any final whitespace / leftover blank lines from the
    # question after removals.
    q = _re.sub(r"\n{3,}", "\n\n", q).strip()

    return q, recovered


ask_user_prompt = (
    "You MUST call this tool whenever you need the user's response. "
    "Always call it after greeting the user, asking a question, or "
    "requesting approval. Do NOT call it for status updates or "
    "summaries that don't require a response.\n\n"
    "USAGE:\n"
    "Pass a 'questions' array with 1-8 entries. Each entry has an "
    "'id' (short identifier used in the user's reply), a 'prompt' "
    "(the question text), and optional 'options' (2-3 predefined "
    "choices). For a single question, pass a one-item array. For "
    "several clarifications, batch them in one call so the user can "
    "answer everything in one interaction instead of going back and "
    "forth — ALWAYS prefer a batch over multiple sequential calls.\n\n"
    "STRUCTURE RULES (CRITICAL):\n"
    "- The 'prompt' field is PLAIN TEXT shown to the user. Do NOT "
    "include XML tags, pseudo-tags like </question>, or option lists "
    "in the prompt string. The UI does not parse them — they render "
    "as raw text and look broken.\n"
    "- The 'options' parameter is the ONLY way to render buttons. "
    "If you want buttons, put them in the 'options' array, not in "
    "the prompt string. Do NOT write 'OPTIONS: [...]', "
    "'_options: [...]', or any inline list inside 'prompt'.\n"
    "- Each prompt must read as a single clean sentence with no "
    "markup. Example: 'What would you like to do?' — not "
    "'What would you like to do?</question>'.\n\n"
    "OPTIONS GUIDANCE:\n"
    "Include 2-3 predefined options in most cases. The UI "
    "automatically appends an 'Other' free-text input after your "
    "options, so NEVER include catch-all options like 'Custom idea', "
    "'Something else', 'Other', or 'None of the above' — the UI "
    "handles that. When the question primarily needs a typed answer "
    "but you must include options, make one option signal that "
    "typing is expected (e.g. \"I'll type my response\"). Omit "
    "options ONLY when the question demands a free-form answer the "
    "user must type out (e.g. 'Describe your agent idea', 'Paste "
    "the error message'). Workers MUST always provide options — "
    "only the queen may ask free-form questions.\n\n"
    "IMPORTANT: Do NOT repeat the questions in your text response — "
    "the widget renders them. Keep your text to a brief intro only.\n\n"
    "SINGLE-QUESTION EXAMPLE:\n"
    '{"questions": [{"id": "next", "prompt": "What would you like '
    'to do?", "options": ["Build a new agent", '
    '"Modify existing agent", "Run tests"]}]}\n\n'
    "BATCH EXAMPLE:\n"
    '{"questions": ['
    '{"id": "scope", "prompt": "What scope?", '
    '"options": ["Full", "Partial"]}, '
    '{"id": "format", "prompt": "Output format?", '
    '"options": ["PDF", "CSV", "JSON"]}, '
    '{"id": "details", "prompt": "Any special requirements?"}'
    "]}\n\n"
    "FREE-FORM EXAMPLE (queen only):\n"
    '{"questions": [{"id": "idea", "prompt": "Describe the agent '
    'you want to build."}]}\n\n'
    "WRONG (do NOT do this — buttons will not render):\n"
    '{"questions": [{"id": "q", "prompt": "What now?</question>\\n'
    '_OPTIONS: [\\"A\\", \\"B\\"]"}]}'
)


def build_ask_user_tool() -> Tool:
    """Build the synthetic ask_user tool for explicit user-input requests.

    The queen calls ask_user() when it needs to pause and wait for user
    input. Accepts an array of 1-8 questions — a single question for the
    common case, or a batch when several clarifications are needed at once.
    Text-only turns WITHOUT ask_user flow through without blocking, allowing
    progress updates and summaries to stream freely.
    """
    return Tool(
        name="ask_user",
        description=ask_user_prompt,
        parameters={
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "description": "List of questions to present to the user.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": ("Short identifier for this question (used in the response)."),
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
                    "description": ("The output value — a brief note, count, status, or data filename reference."),
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
                    "description": ("Short reason for escalation (e.g. 'Tool repeatedly failing')."),
                },
                "context": {
                    "type": "string",
                    "description": "Optional diagnostic details for the queen.",
                },
            },
            "required": ["reason"],
        },
    )


def build_report_to_parent_tool() -> Tool:
    """Build the synthetic ``report_to_parent`` tool.

    Parallel workers (those spawned by the overseer via
    ``run_parallel_workers``) call this to send a structured report back
    to the overseer queen when they have finished their task. Calling
    ``report_to_parent`` terminates the worker's loop cleanly -- do not
    call other tools after it.

    The overseer receives these as ``SUBAGENT_REPORT`` events and
    aggregates them into a single summary for the user.
    """
    return Tool(
        name="report_to_parent",
        description=(
            "Send a structured report back to the parent overseer and "
            "terminate. Call this when you have finished your task "
            "(success, partial, or failed) or cannot make further "
            "progress. Your loop ends after this call -- do not call any "
            "other tool afterwards. The overseer reads the summary + "
            "data fields and aggregates them into a user-facing response."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["success", "partial", "failed"],
                    "description": (
                        "Overall outcome. 'success' = task complete. "
                        "'partial' = some progress but incomplete. "
                        "'failed' = could not make progress."
                    ),
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "One-paragraph narrative for the overseer. What "
                        "you did, what you found, and any notable issues."
                    ),
                },
                "data": {
                    "type": "object",
                    "description": (
                        "Optional structured payload (rows fetched, IDs "
                        "processed, files written, etc.) that the "
                        "overseer can merge into its final summary."
                    ),
                },
            },
            "required": ["status", "summary"],
        },
    )


def handle_report_to_parent(tool_input: dict[str, Any]) -> ToolResult:
    """Normalise + validate a ``report_to_parent`` tool call.

    Returns a ``ToolResult`` with the acknowledgement text the LLM sees;
    the side effects (record on Worker, emit SUBAGENT_REPORT, terminate
    loop) are performed by ``AgentLoop`` after this helper returns.
    """
    status = str(tool_input.get("status", "success")).strip().lower()
    if status not in ("success", "partial", "failed"):
        status = "success"
    summary = str(tool_input.get("summary", "")).strip()
    if not summary:
        summary = f"(worker returned {status} with no summary)"
    data = tool_input.get("data") or {}
    if not isinstance(data, dict):
        data = {"value": data}
    # Store the normalised payload back on the input dict so the caller
    # can pick it up without re-parsing.
    tool_input["_normalised"] = {
        "status": status,
        "summary": summary,
        "data": data,
    }
    return ToolResult(
        tool_use_id=tool_input.get("tool_use_id", ""),
        content=(f"Report delivered to overseer (status={status}). This worker will terminate now."),
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
