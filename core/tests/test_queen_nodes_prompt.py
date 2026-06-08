"""Tests for vision-only prompt block stripping in Queen nodes.

Covers ``finalize_queen_prompt`` — the function that resolves
``<!-- vision-only -->...<!-- /vision-only -->`` markers in Queen phase
prompts before they reach the LLM. Vision-capable models see the inner
content; text-only models see the block removed entirely.
"""

from __future__ import annotations

from framework.agents.queen.nodes import finalize_queen_prompt


class TestFinalizeQueenPrompt:
    def test_vision_model_keeps_inner_content_and_strips_markers(self):
        text = "before <!-- vision-only -->secret<!-- /vision-only --> after"
        result = finalize_queen_prompt(text, has_vision=True)
        assert result == "before secret after"

    def test_text_only_model_removes_entire_block(self):
        text = "before <!-- vision-only -->secret<!-- /vision-only --> after"
        result = finalize_queen_prompt(text, has_vision=False)
        assert result == "before  after"
        assert "secret" not in result
        assert "vision-only" not in result

    def test_multiline_block_handled(self):
        """Regex must use DOTALL so blocks can span newlines."""
        text = "- item 1\n<!-- vision-only -->\n- item 2 (vision only)\n<!-- /vision-only -->\n- item 3\n"
        vision = finalize_queen_prompt(text, has_vision=True)
        text_only = finalize_queen_prompt(text, has_vision=False)
        assert "- item 2 (vision only)" in vision
        assert "- item 2 (vision only)" not in text_only
        assert "- item 1" in text_only and "- item 3" in text_only

    def test_multiple_blocks_in_same_text(self):
        text = "A <!-- vision-only -->X<!-- /vision-only --> B <!-- vision-only -->Y<!-- /vision-only --> C"
        assert finalize_queen_prompt(text, has_vision=True) == "A X B Y C"
        assert finalize_queen_prompt(text, has_vision=False) == "A  B  C"

    def test_non_greedy_match_does_not_swallow_between_blocks(self):
        """A naïve greedy regex would match from the first opening marker
        to the last closing marker and wipe out the middle section. Lock
        that down so a future refactor can't regress to greedy."""
        text = "<!-- vision-only -->first<!-- /vision-only -->KEEP<!-- vision-only -->second<!-- /vision-only -->"
        assert finalize_queen_prompt(text, has_vision=False) == "KEEP"
        assert finalize_queen_prompt(text, has_vision=True) == "firstKEEPsecond"

    def test_text_without_markers_is_unchanged(self):
        text = "plain prompt with no markers at all"
        assert finalize_queen_prompt(text, has_vision=True) == text
        assert finalize_queen_prompt(text, has_vision=False) == text
