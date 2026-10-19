"""Tests for AgentLoop._pick_park_tail — the conversation-tail scan that feeds
the sentinel classifier.

The safety-critical property: only a *real human* message (``is_client_input``)
may be reported as the user's words. User-role messages also carry
framework-injected content (system reminders, external events, nudges); if one
of those were handed to the classifier as "the user said", a reminder could
masquerade as a steer — suppressing a real escalation, or resuming a queen the
human told to stop.
"""

from __future__ import annotations

from framework.agent_loop.agent_loop import AgentLoop
from framework.agent_loop.conversation import Message


def _pick(msgs):
    return AgentLoop._pick_park_tail(msgs)


def test_picks_real_human_message_over_later_system_reminder():
    # A genuine steer, then a <system-reminder> injected afterwards as a
    # user-role message. The scan must return the human steer, not the reminder.
    msgs = [
        Message(seq=0, role="user", content="Stop and wait for me.", is_client_input=True),
        Message(seq=1, role="assistant", content="Okay, pausing."),
        Message(seq=2, role="user", content="<system-reminder>idle tick</system-reminder>", is_system_reminder=True),
    ]
    last_assistant, last_user = _pick(msgs)
    assert last_user == "Stop and wait for me."
    assert last_assistant == "Okay, pausing."


def test_ignores_external_event_user_message():
    # Forwarded worker events land as user-role messages without is_client_input.
    msgs = [
        Message(seq=0, role="user", content="Go enrich the leads.", is_client_input=True),
        Message(seq=1, role="assistant", content="Working on it."),
        Message(seq=2, role="user", content="[External event] worker 3 asked a question"),
    ]
    _, last_user = _pick(msgs)
    assert last_user == "Go enrich the leads."


def test_no_human_message_returns_empty_user_text():
    # Only framework-injected user-role messages → no human intent to report.
    msgs = [
        Message(seq=0, role="user", content="<system-reminder>boot</system-reminder>", is_system_reminder=True),
        Message(seq=1, role="assistant", content="Starting."),
        Message(seq=2, role="user", content="[External event] something"),
    ]
    last_assistant, last_user = _pick(msgs)
    assert last_user == ""
    assert last_assistant == "Starting."


def test_skips_empty_content():
    msgs = [
        Message(seq=0, role="user", content="Real instruction", is_client_input=True),
        Message(seq=1, role="user", content="   ", is_client_input=True),
    ]
    _, last_user = _pick(msgs)
    assert last_user == "Real instruction"


def test_empty_conversation():
    assert _pick([]) == ("", "")
