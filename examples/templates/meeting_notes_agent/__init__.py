"""
meeting_notes_agent
===================
Aden Hive agent that parses meeting transcripts and extracts structured
action items, decisions, blockers, and summaries. Supports Slack delivery.

Usage:
    hive run examples/templates/meeting_notes_agent --input '{"transcript": "..."}'
    hive run examples/templates/meeting_notes_agent --tui
"""

from .agent import (
    MeetingNotesOutput,
    ActionItem,
    validate_input,
    extract_meeting_data,
    parse_and_validate_output,
    format_slack_message,
    post_to_slack,
    compile_final_output,
    handle_error,
)

__all__ = [
    "MeetingNotesOutput",
    "ActionItem",
    "validate_input",
    "extract_meeting_data",
    "parse_and_validate_output",
    "format_slack_message",
    "post_to_slack",
    "compile_final_output",
    "handle_error",
]