"""Cache-stability contract for the agent-loop system-prompt split.

The dynamic suffix is emitted as a system content block that precedes the
ENTIRE message history in the request, so any per-turn churn in it (a
minute-resolution timestamp was the historical offender) invalidates the
provider's cached history prefix every time it changes. Temporal anchoring
belongs on the conversation messages themselves (the loop stamps
``[YYYY-MM-DD HH:MM TZ]`` onto injected events), never in the suffix.
"""

from framework.agent_loop.prompting import (
    PromptSpec,
    build_system_prompt_dynamic_suffix,
    build_system_prompt_static,
)


def test_dynamic_suffix_empty_without_narrative():
    """A worker with no narrative must send NO dynamic suffix at all — the
    single-block system message is the byte-stable shape, and an empty
    suffix must not be padded with a timestamp (that would bust the
    history cache every minute)."""
    suffix = build_system_prompt_dynamic_suffix(PromptSpec(identity_prompt="id"))
    assert suffix == ""


def test_dynamic_suffix_is_narrative_only():
    suffix = build_system_prompt_dynamic_suffix(PromptSpec(narrative="the narrative"))
    assert suffix == "the narrative"
    assert "Current date and time" not in suffix


def test_static_prompt_carries_no_timestamp():
    static = build_system_prompt_static(PromptSpec(identity_prompt="id", focus_prompt="focus"))
    assert "Current date and time" not in static
