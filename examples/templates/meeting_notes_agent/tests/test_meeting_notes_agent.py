"""
Tests for Meeting Notes Agent
==============================
Covers:
  - Input validation (constraint tests)
  - Output parsing and schema validation
  - Slack message formatting
  - End-to-end success scenarios
  - LLM provider selection (Claude + Gemini)

Run:
    PYTHONPATH=examples/templates uv run pytest examples/templates/meeting_notes_agent/tests/ -v
"""

from __future__ import annotations

import json
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add parent directory to path for direct test runs
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from meeting_notes_agent.agent import (
    ActionItem,
    MeetingNotesOutput,
    _build_extraction_prompt,
    _build_slack_blocks,
    _extract_json,
    compile_final_output,
    format_slack_message,
    handle_error,
    parse_and_validate_output,
    validate_input,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_TRANSCRIPT = """
Meeting: Q1 Planning
Date: 2026-02-20
Attendees: Sarah Chen (PM), Marcus Rodriguez (Engineering Lead), Tom Walker (CEO)

Tom: The mobile app launch is non-negotiable by March 31st.
Marcus: We have a blocker — waiting on the Apple Developer certificate renewal.
Sarah: Who owns that? We need to unblock it today.
Marcus: I'll chase it with Jake and cc you Tom. I'll send him a message now.
Tom: Great. Marcus, resolve it by EOD Tuesday.
Sarah: Aisha finished mobile onboarding screens. She'll share the Figma link today.
Tom: Let's ship analytics dashboard updates in Q2, end of April. Sarah, write the spec by Friday.
Sarah: Will do. I'll also set up the weekly Monday standup today.
"""

SAMPLE_LLM_RESPONSE = """{
  "summary": "Q1 planning meeting focused on the mobile app launch and analytics dashboard. Key outcomes include unblocking the Apple certificate and committing to Q2 analytics delivery.",
  "attendees": ["Sarah Chen (PM)", "Marcus Rodriguez (Engineering Lead)", "Tom Walker (CEO)"],
  "decisions": [
    "Mobile app launch target remains March 31st",
    "Analytics dashboard updates to ship in Q2 (end of April)"
  ],
  "action_items": [
    {
      "task": "Chase Apple Developer certificate renewal with Jake",
      "owner": "Marcus Rodriguez",
      "due": "EOD Tuesday",
      "priority": "high"
    },
    {
      "task": "Write analytics dashboard spec",
      "owner": "Sarah Chen",
      "due": "by Friday",
      "priority": "medium"
    },
    {
      "task": "Set up weekly Monday standup recurring invite",
      "owner": "Sarah Chen",
      "due": "today",
      "priority": "medium"
    }
  ],
  "blockers": [
    "Apple Developer certificate renewal is pending — blocking TestFlight build"
  ],
  "follow_ups": [
    "Aisha to share final Figma link for mobile onboarding screens in Slack by EOD"
  ]
}"""


def _make_ctx(**memory_vals) -> MagicMock:
    """Create a minimal mock NodeContext."""
    ctx = MagicMock()
    ctx.memory = MagicMock()
    ctx.logger = MagicMock()
    ctx.llm = MagicMock()
    ctx.tools = MagicMock()

    store = {}
    store.update(memory_vals)

    ctx.memory.get = lambda key, default=None: store.get(key, default)
    ctx.memory.set = lambda key, val: store.update({key: val})
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Constraint Tests (hard rules that must never be violated)
# ─────────────────────────────────────────────────────────────────────────────

class TestConstraints(unittest.TestCase):

    def test_empty_transcript_raises(self):
        """CONSTRAINT: Empty transcript must be rejected."""
        ctx = _make_ctx(transcript="", meeting_name="Test")
        with self.assertRaises(ValueError):
            validate_input(ctx)
        error = ctx.memory.get("validation_error")
        self.assertIsNotNone(error)

    def test_whitespace_only_transcript_raises(self):
        """CONSTRAINT: Whitespace-only transcript must be rejected."""
        ctx = _make_ctx(transcript="   \n\t  ", meeting_name="Test")
        with self.assertRaises(ValueError):
            validate_input(ctx)

    def test_too_short_transcript_raises(self):
        """CONSTRAINT: Transcript under 50 chars must be rejected."""
        ctx = _make_ctx(transcript="Short text.", meeting_name="Test")
        with self.assertRaises(ValueError):
            validate_input(ctx)

    def test_unknown_llm_provider_falls_back(self):
        """CONSTRAINT: Unknown provider must fall back to anthropic without crashing."""
        ctx = _make_ctx(transcript=SAMPLE_TRANSCRIPT, llm_provider="gpt-99-turbo")
        validate_input(ctx)
        self.assertEqual(ctx.memory.get("llm_provider"), "anthropic")

    def test_action_item_priority_must_be_valid(self):
        """CONSTRAINT: Action item priority must be high/medium/low."""
        with self.assertRaises(Exception):
            ActionItem(task="Do something", owner="Alice", due="Friday", priority="urgent")

    def test_invalid_json_from_llm_raises(self):
        """CONSTRAINT: Malformed LLM JSON must raise, not silently produce empty data."""
        ctx = _make_ctx(raw_extraction="This is not JSON at all.")
        with self.assertRaises(ValueError):
            parse_and_validate_output(ctx)
        self.assertIsNotNone(ctx.memory.get("parse_error"))

    def test_missing_summary_raises(self):
        """CONSTRAINT: Output without summary field must fail schema validation."""
        no_summary = json.dumps({
            "attendees": [],
            "decisions": [],
            "action_items": [],
            "blockers": [],
            "follow_ups": [],
        })
        ctx = _make_ctx(raw_extraction=no_summary)
        with self.assertRaises((ValueError, Exception)):
            parse_and_validate_output(ctx)


# ─────────────────────────────────────────────────────────────────────────────
# Success Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSuccessScenarios(unittest.TestCase):

    def test_validate_input_happy_path(self):
        """Valid transcript passes validation."""
        ctx = _make_ctx(
            transcript=SAMPLE_TRANSCRIPT,
            meeting_name="Q1 Planning",
            meeting_date="2026-02-20",
            slack_channel="#team",
            llm_provider="anthropic",
        )
        result = validate_input(ctx)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(ctx.memory.get("validation_error"))
        self.assertEqual(ctx.memory.get("llm_provider"), "anthropic")
        self.assertEqual(ctx.memory.get("meeting_name"), "Q1 Planning")

    def test_gemini_provider_accepted(self):
        """Gemini provider is accepted and resolved correctly."""
        ctx = _make_ctx(transcript=SAMPLE_TRANSCRIPT, llm_provider="gemini")
        validate_input(ctx)
        self.assertEqual(ctx.memory.get("llm_provider"), "gemini")

    def test_parse_valid_llm_response(self):
        """Valid LLM JSON is parsed into MeetingNotesOutput correctly."""
        ctx = _make_ctx(raw_extraction=SAMPLE_LLM_RESPONSE)
        parse_and_validate_output(ctx)
        notes = ctx.memory.get("meeting_notes")
        self.assertIsNotNone(notes)
        self.assertIn("summary", notes)
        self.assertEqual(len(notes["action_items"]), 3)
        self.assertEqual(len(notes["decisions"]), 2)
        self.assertEqual(len(notes["blockers"]), 1)
        self.assertEqual(len(notes["follow_ups"]), 1)

    def test_action_item_priorities_are_valid(self):
        """All parsed action items have valid priority values."""
        ctx = _make_ctx(raw_extraction=SAMPLE_LLM_RESPONSE)
        parse_and_validate_output(ctx)
        notes = ctx.memory.get("meeting_notes")
        valid_priorities = {"high", "medium", "low"}
        for item in notes["action_items"]:
            self.assertIn(item["priority"], valid_priorities)

    def test_json_with_markdown_fences_parsed(self):
        """JSON wrapped in markdown fences is still parsed correctly."""
        fenced = f"```json\n{SAMPLE_LLM_RESPONSE}\n```"
        ctx = _make_ctx(raw_extraction=fenced)
        parse_and_validate_output(ctx)
        notes = ctx.memory.get("meeting_notes")
        self.assertIsNotNone(notes["summary"])

    def test_compile_final_output_without_slack(self):
        """Final output compiles correctly when Slack was not used."""
        notes = json.loads(SAMPLE_LLM_RESPONSE)
        notes["slack_message_sent"] = False
        ctx = _make_ctx(
            meeting_notes=notes,
            slack_result={"sent": False},
        )
        output = compile_final_output(ctx)
        self.assertFalse(output["slack_message_sent"])
        self.assertIn("summary", output)

    def test_compile_final_output_with_slack_success(self):
        """Final output reflects Slack delivery success."""
        notes = json.loads(SAMPLE_LLM_RESPONSE)
        ctx = _make_ctx(
            meeting_notes=notes,
            slack_result={"sent": True, "ts": "1234567890.123456"},
        )
        output = compile_final_output(ctx)
        self.assertTrue(output["slack_message_sent"])

    def test_handle_error_produces_valid_structure(self):
        """handle_error always returns a valid output structure."""
        ctx = _make_ctx(validation_error="Transcript was empty", parse_error=None)
        output = handle_error(ctx)
        self.assertTrue(output["error"])
        self.assertEqual(output["error_message"], "Transcript was empty")
        self.assertEqual(output["summary"], "")
        self.assertIsInstance(output["action_items"], list)


# ─────────────────────────────────────────────────────────────────────────────
# Slack Formatting Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSlackFormatting(unittest.TestCase):

    def _get_notes(self) -> MeetingNotesOutput:
        return MeetingNotesOutput(**json.loads(SAMPLE_LLM_RESPONSE))

    def test_slack_blocks_is_list(self):
        notes = self._get_notes()
        blocks = _build_slack_blocks(notes, "Q1 Planning", "2026-02-20")
        self.assertIsInstance(blocks, list)
        self.assertGreater(len(blocks), 0)

    def test_slack_blocks_has_header(self):
        notes = self._get_notes()
        blocks = _build_slack_blocks(notes, "Q1 Planning", "2026-02-20")
        types = [b["type"] for b in blocks]
        self.assertIn("header", types)

    def test_slack_blocks_all_have_type(self):
        """Every block must have a 'type' field (Slack requirement)."""
        notes = self._get_notes()
        blocks = _build_slack_blocks(notes, "Q1 Planning", "2026-02-20")
        for block in blocks:
            self.assertIn("type", block, f"Block missing 'type': {block}")

    def test_format_slack_message_node(self):
        notes_dict = json.loads(SAMPLE_LLM_RESPONSE)
        ctx = _make_ctx(
            meeting_notes=notes_dict,
            meeting_name="Q1 Planning",
            meeting_date="2026-02-20",
        )
        format_slack_message(ctx)
        payload = ctx.memory.get("slack_payload")
        self.assertIn("blocks", payload)
        self.assertIn("text", payload)

    def test_post_to_slack_skips_when_no_channel(self):
        """post_to_slack sets sent=False when no channel is configured."""
        ctx = _make_ctx(
            slack_channel=None,
            slack_payload={"blocks": [], "text": "test"},
        )
        post_to_slack(ctx)
        result = ctx.memory.get("slack_result")
        self.assertFalse(result["sent"])

    @patch("meeting_notes_agent.agent.os")
    def test_post_to_slack_calls_tool(self, mock_os):
        """post_to_slack calls ctx.tools.call with correct args."""
        ctx = _make_ctx(
            slack_channel="#team-standup",
            slack_payload={"blocks": [{"type": "header"}], "text": "Meeting Notes"},
        )
        ctx.tools.call = MagicMock(return_value={"ok": True})
        post_to_slack(ctx)
        ctx.tools.call.assert_called_once()
        call_args = ctx.tools.call.call_args[0]
        self.assertEqual(call_args[0], "slack_post_message")
        self.assertEqual(call_args[1]["channel"], "#team-standup")


# ─────────────────────────────────────────────────────────────────────────────
# JSON Extraction Utility Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestJsonExtraction(unittest.TestCase):

    def test_plain_json(self):
        data = _extract_json('{"summary": "Test", "action_items": []}')
        self.assertEqual(data["summary"], "Test")

    def test_json_with_preamble(self):
        data = _extract_json('Here is the result:\n{"summary": "Test", "action_items": []}')
        self.assertEqual(data["summary"], "Test")

    def test_json_with_markdown_fences(self):
        data = _extract_json('```json\n{"summary": "Fenced", "action_items": []}\n```')
        self.assertEqual(data["summary"], "Fenced")

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            _extract_json("No JSON here at all.")

    def test_malformed_json_raises(self):
        with self.assertRaises((json.JSONDecodeError, ValueError)):
            _extract_json('{"summary": "bad json"')


# ─────────────────────────────────────────────────────────────────────────────
# Prompt Builder Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptBuilder(unittest.TestCase):

    def test_prompt_contains_transcript(self):
        prompt = _build_extraction_prompt("Meeting about AI", "AI Summit", "2026-01-01")
        self.assertIn("Meeting about AI", prompt)

    def test_prompt_contains_meeting_metadata(self):
        prompt = _build_extraction_prompt("transcript text", "Q1 Planning", "2026-02-20")
        self.assertIn("Q1 Planning", prompt)
        self.assertIn("2026-02-20", prompt)

    def test_prompt_instructs_no_hallucination(self):
        prompt = _build_extraction_prompt("text", "name", "date")
        self.assertIn("ONLY extract", prompt)
        self.assertIn("Never fabricate", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)