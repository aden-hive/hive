"""Tests for vision-only prompt block stripping in Queen nodes.

Covers ``finalize_queen_prompt`` — the function that resolves
``<!-- vision-only -->...<!-- /vision-only -->`` markers in Queen phase
prompts before they reach the LLM. Vision-capable models see the inner
content; text-only models see the block removed entirely.
"""

from __future__ import annotations

from framework.agents.queen.nodes import (
    _queen_behavior_always,
    _queen_behavior_colony,
    _queen_behavior_independent,
    _queen_character_core,
    _queen_role_colony,
    _queen_tools_colony,
    finalize_queen_prompt,
    queen_node,
)


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


def test_colony_prompt_tells_queen_to_probe_uncertain_fanout() -> None:
    assert "do not refuse based" in _queen_behavior_colony
    assert "unverified assumption" in _queen_behavior_colony
    # The queen probes uncertain shared behavior herself, not via a worker.
    assert "probe it yourself first" in _queen_behavior_colony
    assert "Do not spend a worker to test what you can verify directly" in (_queen_behavior_colony)


def test_colony_prompt_preserves_latest_constraints_in_worker_skill() -> None:
    assert "restate the latest user" in _queen_behavior_colony
    assert "instructions override earlier task framing" in _queen_behavior_colony


def test_colony_prompt_keeps_detailed_delegation_manual_out_of_system_text() -> None:
    assert "# Concrete example" not in _queen_behavior_colony
    assert "Good:   (a)" not in _queen_behavior_colony
    assert "Step 1 of every fan-out" not in _queen_tools_colony
    assert "Tool schemas carry syntax" in _queen_tools_colony


def test_colony_role_establishes_tracker_db_world_model() -> None:
    """The queen must read the colony-tracker world model in the role
    prompt, not buried in a tool schema. Without this the colony queen
    has been observed asking the user "Where should I save the tracker
    table?" — a question the runtime answers structurally."""
    assert "tracker.db" in _queen_role_colony
    assert "pre-provisioned" in _queen_role_colony
    # "Create the tracker table" must be disambiguated from
    # "provision a database file".
    assert "CREATE TABLE" in _queen_role_colony


def test_colony_role_drops_stale_incubating_phase_reference() -> None:
    """INCUBATING is not a current phase (the model is 2-phase:
    independent / colony). The reference used to dangle in role_colony."""
    assert "INCUBATING" not in _queen_role_colony


def test_delegation_loop_step1_disambiguates_create_table() -> None:
    """Step 1 used to read "Open with tracker_sql('CREATE TABLE ...')",
    which the queen could misread as "open / provision storage". The
    rephrasing makes the existing-DB context explicit at the action
    site, even though the role prompt already establishes it."""
    assert "existing" in _queen_behavior_colony
    assert "tracker.db" in _queen_behavior_colony


def test_shared_always_block_strips_independent_only_content() -> None:
    """The shared System Rules must not name tools that aren't on the
    colony tool surface (``suggest_colony``) — otherwise the colony
    queen reads dead instructions before reaching the delegation loop.

    The pivot block IS now shared (it applies to both phases — the
    field name varies, the criteria don't), so we don't strip pivot
    content from the always block anymore. See
    ``test_pivot_block_is_shared`` below.
    """
    # The suggest_colony reference inside ask_user examples — the tool
    # is not on the colony tool surface.
    assert "Before calling ``suggest_colony``" not in _queen_behavior_always
    # The "Build me a colony to monitor LinkedIn jobs" example is the
    # only ask_user example that describes pre-colony scope-setting;
    # it lives in _queen_behavior_independent instead.
    assert "Build me a colony to monitor LinkedIn jobs" not in _queen_behavior_always


def test_independent_block_keeps_independent_only_content() -> None:
    """Per-phase content the colony queen mustn't see still lives in
    _queen_behavior_independent. Pivot teaching moved to the shared
    always block — see ``test_pivot_block_is_shared``."""
    assert "Build me a colony to monitor LinkedIn jobs" in _queen_behavior_independent
    assert "suggest_colony" in _queen_behavior_independent


def test_pivot_block_is_shared() -> None:
    """The pivot is a single concept covered once in the always block.

    Previously each phase had its own ``<new_session>`` /
    ``<new_colony>`` block re-stating the same criteria with mechanism
    leakage in both directions, which drifted (e.g. role_independent's
    pivot paragraph predated the goal-required field). Consolidated
    into one ``<pivot>`` block in _queen_behavior_always that names
    both field names so the queen knows the schema's phase-swapped
    field is the same concept either way.
    """
    assert "<pivot>" in _queen_behavior_always
    assert "</pivot>" in _queen_behavior_always
    # The criteria + the universal goal/handoff/tasks contract must
    # appear once in the always block.
    assert "goal" in _queen_behavior_always
    assert "handoff" in _queen_behavior_always
    # The two field names appear together so the queen knows which one
    # the schema is exposing in her current phase.
    assert "new_session" in _queen_behavior_always
    assert "new_colony" in _queen_behavior_always
    # The per-phase prompts must NOT have their own <new_session> /
    # <new_colony> blocks anymore — that's the duplication we removed.
    assert "<new_session>" not in _queen_behavior_independent
    assert "<new_colony>" not in _queen_behavior_colony


def test_outbound_voice_rules_reach_both_phases() -> None:
    """Outbound drafting happens in BOTH modes: a DM queen writes the
    pilot message herself, and a colony queen writes the pilot plus the
    skill that N workers copy from. So the voice rules live in the
    shared always block — if they were phase-scoped, half the outbound
    the product sends would still read like machine copy.

    The em-dash ban is the load-bearing line (it is the loudest tell),
    and it must not be diluted into "prefer" by a later edit.
    """
    assert "<draft_outbound_message>" in _queen_behavior_always
    assert "</draft_outbound_message>" in _queen_behavior_always
    assert "NEVER use an em-dash" in _queen_behavior_always

    # Both composed phase prompts carry the block, since each starts
    # from a different concatenation order.
    independent = queen_node.system_prompt
    colony = _queen_character_core + _queen_role_colony + _queen_tools_colony + _queen_behavior_colony + _queen_behavior_always
    assert "<draft_outbound_message>" in independent
    assert "<draft_outbound_message>" in colony
