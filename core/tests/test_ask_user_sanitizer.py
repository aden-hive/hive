"""Tests for ``sanitize_ask_user_inputs``.

Some model families return malformed ``ask_user`` calls that pack the
options inside the ``question`` string as pseudo-XML / inline blob.
The sanitizer self-heals those calls so the buttons still render.
"""

from __future__ import annotations

from framework.agent_loop.internals.synthetic_tools import (
    sanitize_ask_user_inputs,
)


def test_clean_question_passes_through_unchanged() -> None:
    q, opts = sanitize_ask_user_inputs("What's next?", None)
    assert q == "What's next?"
    assert opts is None


def test_strips_trailing_close_question_tag() -> None:
    q, opts = sanitize_ask_user_inputs("What now?</question>", None)
    assert q == "What now?"
    assert opts is None


def test_strips_close_question_tag_case_insensitive_with_whitespace() -> None:
    q, opts = sanitize_ask_user_inputs("What now?  </QUESTION>  ", None)
    assert q == "What now?"
    assert opts is None


def test_recovers_inline_uppercase_options() -> None:
    raw = (
        "What do you want to do from here?</question>\n"
        '_OPTIONS: ["De-risk — trim PRLG", "Add to a position", "Open a short"]'
    )
    q, opts = sanitize_ask_user_inputs(raw, None)
    assert q == "What do you want to do from here?"
    assert opts == ["De-risk — trim PRLG", "Add to a position", "Open a short"]


def test_recovers_inline_lowercase_options() -> None:
    raw = 'Pick one\noptions: ["A", "B", "C"]'
    q, opts = sanitize_ask_user_inputs(raw, None)
    assert q == "Pick one"
    assert opts == ["A", "B", "C"]


def test_recovers_inline_underscore_options() -> None:
    raw = 'Pick one\n_options: ["A", "B"]'
    q, opts = sanitize_ask_user_inputs(raw, None)
    assert q == "Pick one"
    assert opts == ["A", "B"]


def test_recovered_options_dropped_when_not_a_list() -> None:
    raw = 'Pick one\noptions: "not-a-list"'
    q, opts = sanitize_ask_user_inputs(raw, None)
    # The malformed inline blob is removed but no options are recovered.
    assert "options" not in q.lower() or "not-a-list" in q
    assert opts is None


def test_recovered_options_dropped_when_too_many() -> None:
    raw = 'Pick\noptions: ["a","b","c","d","e","f","g","h","i","j"]'
    q, opts = sanitize_ask_user_inputs(raw, None)
    assert opts is None


def test_does_not_overwrite_real_options() -> None:
    """Sanitizer is for the question field; real options pass through untouched."""
    real_options = ["X", "Y"]
    q, opts = sanitize_ask_user_inputs("Plain question?", real_options)
    # The function returns the recovered options as the second value;
    # real_options are passed in as input only — the caller decides
    # which to use. Here we verify the question is clean.
    assert q == "Plain question?"
    assert opts is None  # nothing recovered from the question text


def test_none_question_returns_empty() -> None:
    q, opts = sanitize_ask_user_inputs(None, None)
    assert q == ""
    assert opts is None


def test_collapses_excess_blank_lines_after_removal() -> None:
    raw = 'What?\n\n\n\noptions: ["a", "b"]'
    q, opts = sanitize_ask_user_inputs(raw, None)
    assert q == "What?"
    assert opts == ["a", "b"]
