"""Tests for the browser ref system (annotate_snapshot / resolve_ref)."""

from __future__ import annotations

import pytest

from gcu.browser.refs import (
    RefEntry,
    annotate_snapshot,
    resolve_ref,
)

# ---------------------------------------------------------------------------
# annotate_snapshot
# ---------------------------------------------------------------------------

SAMPLE_SNAPSHOT = """\
- navigation "Main":
  - link "Home"
  - link "About"
- main:
  - heading "Welcome"
  - textbox "Search"
  - button "Submit"
  - paragraph: some text here
  - img "Logo"
  - list:
    - listitem:
      - link "Item 1"
    - listitem:
      - link "Item 2\""""


class TestAnnotateSnapshot:
    def test_assigns_refs_to_interactive_roles(self):
        annotated, ref_map = annotate_snapshot(SAMPLE_SNAPSHOT)
        # link, textbox, button should all get refs
        assert "[ref=e" in annotated
        # Check that specific interactive elements got refs
        roles_in_map = {entry.role for entry in ref_map.values()}
        assert "link" in roles_in_map
        assert "textbox" in roles_in_map
        assert "button" in roles_in_map

    def test_skips_structural_roles(self):
        annotated, ref_map = annotate_snapshot(SAMPLE_SNAPSHOT)
        roles_in_map = {entry.role for entry in ref_map.values()}
        # navigation, main, list, listitem, paragraph are structural — no refs
        assert "navigation" not in roles_in_map
        assert "main" not in roles_in_map
        assert "list" not in roles_in_map
        assert "listitem" not in roles_in_map
        assert "paragraph" not in roles_in_map

    def test_named_content_roles_get_refs(self):
        annotated, ref_map = annotate_snapshot(SAMPLE_SNAPSHOT)
        roles_in_map = {entry.role for entry in ref_map.values()}
        # heading and img have names, so they should get refs
        assert "heading" in roles_in_map
        assert "img" in roles_in_map

    def test_unnamed_content_roles_skip(self):
        snapshot = "- heading\n- img"
        _, ref_map = annotate_snapshot(snapshot)
        # No names → no refs for content roles
        assert len(ref_map) == 0

    def test_preserves_non_matching_lines(self):
        snapshot = 'some random text\n- button "OK"\nanother line'
        annotated, _ = annotate_snapshot(snapshot)
        lines = annotated.split("\n")
        assert lines[0] == "some random text"
        assert lines[2] == "another line"

    def test_nth_disambiguation(self):
        snapshot = '- button "Save"\n- button "Save"\n- button "Cancel"'
        annotated, ref_map = annotate_snapshot(snapshot)

        # Two "Save" buttons should have nth=0 and nth=1
        save_entries = [
            (rid, e) for rid, e in ref_map.items() if e.role == "button" and e.name == "Save"
        ]
        assert len(save_entries) == 2
        nths = sorted(e.nth for _, e in save_entries)
        assert nths == [0, 1]

        # "Cancel" should have nth=0
        cancel_entries = [e for e in ref_map.values() if e.role == "button" and e.name == "Cancel"]
        assert len(cancel_entries) == 1
        assert cancel_entries[0].nth == 0

    def test_sequential_ref_ids(self):
        snapshot = '- link "A"\n- link "B"\n- link "C"'
        _, ref_map = annotate_snapshot(snapshot)
        assert set(ref_map.keys()) == {"e0", "e1", "e2"}

    def test_empty_snapshot(self):
        annotated, ref_map = annotate_snapshot("")
        assert annotated == ""
        assert ref_map == {}


# ---------------------------------------------------------------------------
# resolve_ref
# ---------------------------------------------------------------------------


class TestResolveRef:
    def test_resolves_valid_ref(self):
        ref_map = {
            "e0": RefEntry(role="button", name="Submit", nth=0),
        }
        result = resolve_ref("e0", ref_map)
        assert result == '[role="button"][aria-label="Submit"]:nth-of-type(1)'

    def test_passes_through_css_selectors(self):
        ref_map = {"e0": RefEntry(role="button", name="OK", nth=0)}
        assert resolve_ref("#my-button", ref_map) == "#my-button"
        assert resolve_ref(".btn-primary", ref_map) == ".btn-primary"
        assert resolve_ref("div > button", ref_map) == "div > button"

    def test_passes_through_role_selectors(self):
        ref_map = {"e0": RefEntry(role="button", name="OK", nth=0)}
        sel = 'role=button[name="OK"]'
        assert resolve_ref(sel, ref_map) == sel

    def test_raises_on_unknown_ref(self):
        ref_map = {"e0": RefEntry(role="button", name="OK", nth=0)}
        with pytest.raises(ValueError, match="not found"):
            resolve_ref("e99", ref_map)

    def test_raises_when_no_ref_map(self):
        with pytest.raises(ValueError, match="no snapshot"):
            resolve_ref("e0", None)

    def test_quoted_name_passes_through(self):
        # Note: the CSS selector output does not currently escape inner quotes.
        # This produces technically-broken CSS when name contains double quotes,
        # but the bridge-based matcher appears to tolerate it. Tracked as
        # a follow-up concern — see PR #6955.
        ref_map = {
            "e0": RefEntry(role="button", name='Say "Hello"', nth=0),
        }
        result = resolve_ref("e0", ref_map)
        assert result == '[role="button"][aria-label="Say "Hello""]:nth-of-type(1)'

    def test_no_name_produces_role_only_selector(self):
        ref_map = {
            "e0": RefEntry(role="textbox", name=None, nth=0),
        }
        result = resolve_ref("e0", ref_map)
        assert result == '[role="textbox"]:nth-of-type(1)'

    def test_empty_name(self):
        ref_map = {
            "e0": RefEntry(role="button", name="", nth=0),
        }
        result = resolve_ref("e0", ref_map)
        assert result == '[role="button"][aria-label=""]:nth-of-type(1)'

    def test_nth_in_selector(self):
        ref_map = {
            "e0": RefEntry(role="link", name="Next", nth=2),
        }
        result = resolve_ref("e0", ref_map)
        assert result == '[role="link"][aria-label="Next"]:nth-of-type(3)'


# ---------------------------------------------------------------------------
# Round-trip: annotate → resolve
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_annotate_then_resolve(self):
        snapshot = '- button "Submit"\n- textbox "Email"\n- link "Home"'
        _, ref_map = annotate_snapshot(snapshot)

        # Each ref should resolve to a valid CSS selector (bridge-based API)
        for ref_id, entry in ref_map.items():
            resolved = resolve_ref(ref_id, ref_map)
            assert resolved.startswith(f'[role="{entry.role}"]')
            if entry.name is not None:
                assert f'[aria-label="{entry.name}"]' in resolved
            assert f":nth-of-type({entry.nth + 1})" in resolved

    def test_css_selectors_still_work_after_annotate(self):
        snapshot = '- button "OK"'
        _, ref_map = annotate_snapshot(snapshot)
        # CSS selectors pass through even when a ref_map exists
        assert resolve_ref("#submit-btn", ref_map) == "#submit-btn"
