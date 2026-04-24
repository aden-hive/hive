from __future__ import annotations

from framework.agents.queen.queen_profiles import DEFAULT_QUEENS, format_queen_identity_prompt


def test_identity_prompt_starts_with_plain_identity() -> None:
    prompt = format_queen_identity_prompt(DEFAULT_QUEENS["queen_brand_design"], max_examples=1)

    assert prompt.startswith("<core_identity>\nYou are Sophia, Head of Brand & Design.")
    assert "<hidden_background>" in prompt
    assert "<behavior_rules>" in prompt
    assert "<psychological_profile>" in prompt
    assert "<roleplay_examples>" in prompt
    assert "You are a strategist who uses visual language as your tool." in prompt
    assert "She's" not in prompt
    assert "she thrives" not in prompt


def test_full_identity_prompt_examples_still_render_authoring_scratchpad() -> None:
    prompt = format_queen_identity_prompt(DEFAULT_QUEENS["queen_brand_design"])

    assert "<roleplay_examples>" in prompt
    assert "User: hi" in prompt
    assert "Assistant:" in prompt
    assert "<relationship>" in prompt
    assert "<sentiment>" in prompt
