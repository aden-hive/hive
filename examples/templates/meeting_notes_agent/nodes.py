"""Node definitions for Meeting Notes & Action Item Agent."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from framework.graph.node import NodeSpec

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────────────────────

class ActionItem(BaseModel):
    task: str = Field(..., description="Clear description of the task")
    owner: str = Field(..., description="Person responsible for the task")
    due: str = Field(default="TBD", description="Due date or timeframe")
    priority: str = Field(
        default="medium",
        pattern="^(high|medium|low)$",
        description="Priority level: high, medium, or low",
    )


class MeetingNotesOutput(BaseModel):
    summary: str = Field(..., description="2-3 sentence executive summary")
    attendees: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    slack_message_sent: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Node Functions
# ─────────────────────────────────────────────────────────────────────────────

def validate_input(ctx: Any) -> dict:
    """Node: validate_input — validates and normalises the incoming transcript."""
    transcript = ctx.memory.get("transcript", "")
    meeting_name = ctx.memory.get("meeting_name", "Untitled Meeting")
    meeting_date = ctx.memory.get("meeting_date", "Unknown Date")
    slack_channel = ctx.memory.get("slack_channel", None)
    llm_provider = ctx.memory.get("llm_provider", "anthropic")

    if not transcript or not transcript.strip():
        ctx.memory.set("validation_error", "transcript field is required and cannot be empty")
        ctx.logger.error("Input validation failed: empty transcript")
        raise ValueError("Empty transcript provided")

    transcript = transcript.strip()
    if len(transcript) < 50:
        ctx.memory.set(
            "validation_error",
            f"Transcript is too short ({len(transcript)} chars). Minimum 50 characters required.",
        )
        raise ValueError("Transcript too short")

    from .config import MODEL_REGISTRY
    resolved_provider = (llm_provider or "anthropic").lower()
    if resolved_provider not in MODEL_REGISTRY:
        ctx.logger.warning("Unknown LLM provider '%s', falling back to 'anthropic'", llm_provider)
        resolved_provider = "anthropic"

    ctx.memory.set("validated_transcript", transcript)
    ctx.memory.set("meeting_name", meeting_name or "Untitled Meeting")
    ctx.memory.set("meeting_date", meeting_date or "Unknown Date")
    ctx.memory.set("slack_channel", slack_channel)
    ctx.memory.set("llm_provider", resolved_provider)
    ctx.memory.set("validation_error", None)

    ctx.logger.info(
        "Input validated: %d chars | provider=%s | slack=%s",
        len(transcript), resolved_provider, slack_channel or "none",
    )
    return {"status": "ok"}


def extract_meeting_data(ctx: Any) -> dict:
    """Node: extract_meeting_data — calls Claude or Gemini to extract structured data."""
    from .config import MODEL_REGISTRY, default_config

    provider = ctx.memory.get("llm_provider", "anthropic")
    model = MODEL_REGISTRY.get(provider, default_config.model)

    validated_transcript = ctx.memory.get("validated_transcript", "")
    meeting_name = ctx.memory.get("meeting_name", "Untitled Meeting")
    meeting_date = ctx.memory.get("meeting_date", "Unknown Date")

    prompt = _build_extraction_prompt(validated_transcript, meeting_name, meeting_date)

    ctx.logger.info("Calling LLM provider=%s model=%s", provider, model)

    response = ctx.llm.complete(
        prompt=prompt,
        model=model,
        max_tokens=default_config.max_tokens,
        temperature=default_config.temperature,
    )

    raw_text = response.content if hasattr(response, "content") else str(response)
    ctx.memory.set("raw_extraction", raw_text)
    ctx.logger.info("LLM extraction complete: %d chars", len(raw_text))
    return {"raw_extraction": raw_text}


def parse_and_validate_output(ctx: Any) -> dict:
    """Node: parse_and_validate_output — validates LLM output against Pydantic schema."""
    raw = ctx.memory.get("raw_extraction", "")

    try:
        parsed = _extract_json(raw)
        notes = MeetingNotesOutput(**parsed)
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        error_msg = f"Output parse/validation failed: {exc}"
        ctx.memory.set("parse_error", error_msg)
        ctx.logger.error(error_msg)
        raise ValueError(error_msg) from exc

    ctx.memory.set("meeting_notes", notes.model_dump())
    ctx.memory.set("parse_error", None)
    ctx.logger.info(
        "Parsed: %d decisions | %d action items | %d blockers",
        len(notes.decisions), len(notes.action_items), len(notes.blockers),
    )
    return {"meeting_notes": notes.model_dump()}


def format_slack_message(ctx: Any) -> dict:
    """Node: format_slack_message — builds Slack Block Kit payload."""
    notes_raw = ctx.memory.get("meeting_notes", {})
    notes = MeetingNotesOutput(**notes_raw)
    meeting_name = ctx.memory.get("meeting_name", "Meeting Notes")
    meeting_date = ctx.memory.get("meeting_date", "")

    blocks = _build_slack_blocks(notes, meeting_name, meeting_date)
    payload = {
        "blocks": blocks,
        "text": f":bee: *{meeting_name}* — Meeting Notes Ready",
    }
    ctx.memory.set("slack_payload", payload)
    ctx.logger.info("Slack payload built: %d blocks", len(blocks))
    return {"slack_payload": payload}


def post_to_slack(ctx: Any) -> dict:
    """Node: post_to_slack — delivers message via Slack MCP tool."""
    slack_channel = ctx.memory.get("slack_channel")
    slack_payload = ctx.memory.get("slack_payload", {})

    if not slack_channel:
        ctx.memory.set("slack_result", {"sent": False, "reason": "no_channel"})
        return {"slack_result": {"sent": False}}

    try:
        result = ctx.tools.call(
            "slack_post_message",
            {
                "channel": slack_channel,
                "blocks": slack_payload.get("blocks", []),
                "text": slack_payload.get("text", "Meeting Notes"),
            },
        )
        ctx.memory.set("slack_result", {"sent": True, "result": result})
        ctx.logger.info("Slack message posted to channel: %s", slack_channel)
    except Exception as exc:
        ctx.logger.warning("Slack delivery failed (non-fatal): %s", exc)
        ctx.memory.set("slack_result", {"sent": False, "reason": str(exc)})

    return {"slack_result": ctx.memory.get("slack_result")}


def compile_final_output(ctx: Any) -> dict:
    """Node: compile_final_output — assembles the final agent output."""
    notes_raw = ctx.memory.get("meeting_notes", {})
    slack_result = ctx.memory.get("slack_result", {"sent": False})
    output = {**notes_raw, "slack_message_sent": slack_result.get("sent", False)}
    ctx.memory.set("final_output", output)
    ctx.logger.info("Final output compiled. slack_sent=%s", output["slack_message_sent"])
    return output


def handle_error(ctx: Any) -> dict:
    """Node: handle_error — returns a structured error response."""
    validation_error = ctx.memory.get("validation_error")
    parse_error = ctx.memory.get("parse_error")
    error_msg = validation_error or parse_error or "Unknown error occurred"
    output = {
        "error": True,
        "error_message": error_msg,
        "summary": "",
        "attendees": [],
        "decisions": [],
        "action_items": [],
        "blockers": [],
        "follow_ups": [],
        "slack_message_sent": False,
    }
    ctx.memory.set("final_output", output)
    ctx.logger.error("Agent completed with error: %s", error_msg)
    return output


# ─────────────────────────────────────────────────────────────────────────────
# NodeSpec Definitions  (imported by agent.py)
# ─────────────────────────────────────────────────────────────────────────────

validate_input_node = NodeSpec(
    id="validate-input",
    name="Validate Input",
    node_type="event_loop",
    description="Validates and normalises the incoming meeting transcript.",
    function=validate_input,
    input_keys=["transcript", "meeting_name", "meeting_date", "slack_channel", "llm_provider"],
    output_keys=["validated_transcript", "meeting_name", "meeting_date", "slack_channel", "llm_provider", "validation_error"],
    client_facing=False,
)

extract_meeting_data_node = NodeSpec(
    id="extract-meeting-data",
    name="Extract Meeting Data",
    node_type="event_loop",
    description="Calls Claude or Gemini to parse the transcript and extract structured meeting data.",
    function=extract_meeting_data,
    input_keys=["validated_transcript", "meeting_name", "meeting_date", "llm_provider"],
    output_keys=["raw_extraction"],
    client_facing=False,
)

parse_and_validate_node = NodeSpec(
    id="parse-and-validate",
    name="Parse & Validate Output",
    node_type="event_loop",
    description="Parses the LLM JSON output and validates against MeetingNotesOutput Pydantic schema.",
    function=parse_and_validate_output,
    input_keys=["raw_extraction"],
    output_keys=["meeting_notes", "parse_error"],
    client_facing=False,
)

format_slack_node = NodeSpec(
    id="format-slack-message",
    name="Format Slack Message",
    node_type="event_loop",
    description="Converts structured meeting notes into a Slack Block Kit payload.",
    function=format_slack_message,
    input_keys=["meeting_notes", "meeting_name", "meeting_date"],
    output_keys=["slack_payload"],
    client_facing=False,
)

post_to_slack_node = NodeSpec(
    id="post-to-slack",
    name="Post to Slack",
    node_type="event_loop",
    description="Delivers the formatted message to the specified Slack channel via MCP tool.",
    function=post_to_slack,
    input_keys=["slack_payload", "slack_channel"],
    output_keys=["slack_result"],
    client_facing=False,
)

compile_output_node = NodeSpec(
    id="compile-final-output",
    name="Compile Final Output",
    node_type="event_loop",
    description="Assembles the final agent output including meeting notes and Slack delivery status.",
    function=compile_final_output,
    input_keys=["meeting_notes", "slack_result"],
    output_keys=["final_output"],
    client_facing=True,
)

handle_error_node = NodeSpec(
    id="handle-error",
    name="Handle Error",
    node_type="event_loop",
    description="Captures validation or parse errors and returns a structured error response.",
    function=handle_error,
    input_keys=["validation_error", "parse_error"],
    output_keys=["final_output"],
    client_facing=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# Private Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_extraction_prompt(transcript: str, meeting_name: str, meeting_date: str) -> str:
    return f"""You are a professional meeting analyst. Analyse the provided meeting transcript and return ONLY a valid JSON object. No markdown fences, no preamble, no trailing text — pure JSON only.

JSON structure:
{{
  "summary": "2-3 sentence executive summary of the meeting",
  "attendees": ["Name (Role)", "..."],
  "decisions": ["Decision agreed upon..."],
  "action_items": [
    {{
      "task": "Clear actionable task description",
      "owner": "Person's name",
      "due": "Due date or timeframe (e.g. EOD Tuesday, by Friday, next Monday)",
      "priority": "high|medium|low"
    }}
  ],
  "blockers": ["Unresolved issue preventing progress..."],
  "follow_ups": ["Item needing future attention but not yet formally assigned..."]
}}

Rules:
- ONLY extract what is explicitly stated. Never fabricate names, tasks, or dates.
- Priority: urgent/today/asap/critical = high; this week/by Friday/soon = medium; otherwise low.
- Blockers = things preventing progress right now.
- Follow-ups = items for future attention not formally assigned.
- If no attendees listed, set attendees to [].
- If no blockers, decisions, or follow-ups exist, return empty arrays [].

Meeting Title: {meeting_name}
Date: {meeting_date}

Transcript:
{transcript}"""


def _extract_json(raw: str) -> dict:
    clean = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM response. Raw: {raw[:200]}")
    return json.loads(clean[start:end + 1])


def _build_slack_blocks(notes: MeetingNotesOutput, meeting_name: str, meeting_date: str) -> list[dict]:
    blocks: list[dict] = []
    blocks.append({"type": "header", "text": {"type": "plain_text", "text": f"🐝 {meeting_name}", "emoji": True}})

    meta_parts = []
    if meeting_date and meeting_date != "Unknown Date":
        meta_parts.append(f"📅 *{meeting_date}*")
    if notes.attendees:
        meta_parts.append(f"👥 {', '.join(notes.attendees)}")
    if meta_parts:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "  |  ".join(meta_parts)}})

    blocks.append({"type": "divider"})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*📋 Summary*\n{notes.summary}"}})

    if notes.decisions:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*✅ Key Decisions*\n" + "\n".join(f"• {d}" for d in notes.decisions)}})

    if notes.action_items:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*⚡ Action Items*"}})
        priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        for item in notes.action_items:
            if isinstance(item, dict):
                task, owner, due, priority = item.get("task", ""), item.get("owner", ""), item.get("due", "TBD"), item.get("priority", "medium")
            else:
                task, owner, due, priority = item.task, item.owner, item.due, item.priority
            emoji = priority_emoji.get(priority, "⚪")
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"{emoji} *{task}*\n   👤 {owner}   📅 {due}   `{priority.upper()}`"}})

    if notes.blockers:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*🚧 Blockers*\n" + "\n".join(f"⚠️ {b}" for b in notes.blockers)}})

    if notes.follow_ups:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*🔁 Follow-ups*\n" + "\n".join(f"→ {f}" for f in notes.follow_ups)}})

    blocks.append({"type": "divider"})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "_Generated by Aden Hive Meeting Notes Agent · https://adenhq.com_"}]})
    return blocks