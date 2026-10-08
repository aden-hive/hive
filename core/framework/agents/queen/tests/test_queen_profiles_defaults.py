"""Default queen loading + capability/persona split.

Guards two things that are easy to break:
  1. Default queens load from ``queen_defaults/*.yaml`` with their capability
     config (default_tools / default_skills) intact.
  2. ``profile.yaml`` is persona-only, and ``default_profile_persona`` matches
     it exactly — the equality the ``handle_initialize_preferences`` self-heal
     route relies on to tell "untouched default" from "user-edited".
"""

from __future__ import annotations

import yaml

from framework.agents.queen import queen_profiles as qp


def test_all_defaults_load_from_yaml():
    """Every default queen loads with persona + capability keys."""
    assert len(qp.DEFAULT_QUEENS) == 13
    for queen_id, profile in qp.DEFAULT_QUEENS.items():
        assert profile.get("name"), queen_id
        assert profile.get("title"), queen_id
        # tool categories present for all current defaults; preset skills always a list
        assert isinstance(profile.get("default_tool_categories"), list), queen_id
        assert isinstance(profile.get("default_preset_skills"), list), queen_id


def test_no_queen_carries_preset_skill_defaults():
    """The ``hive.linkedin-message-campaign`` preset was retired; LinkedIn is now
    a set of framework-default skills (``hive.linkedin-core`` + capability skills)
    that are on by default for every browser-capable queen via the catalog. No
    default queen should pin a preset-scope skill in ``default_preset_skills`` —
    that field only governs opt-in preset skills, and we ship none as role
    defaults anymore. This guards against a stale preset reference creeping back
    in (which resolves to nothing, since preset-scope skills off by default)."""
    with_presets = {q for q in qp.DEFAULT_QUEENS if qp.default_skills_for(q)}
    assert with_presets == set()
    assert qp.default_skills_for("queen_outbound") == frozenset()
    assert qp.default_skills_for("queen_technology") == frozenset()


def test_default_tools_for_known_and_unknown():
    assert "charts" in (qp.default_tools_for("queen_outbound") or [])
    # operations intentionally omits research
    assert "research" not in (qp.default_tools_for("queen_operations") or [])
    assert qp.default_tools_for("queen_does_not_exist") is None


def test_materialize_writes_persona_only(tmp_path, monkeypatch):
    """profile.yaml must not carry capability config."""
    monkeypatch.setattr(qp, "QUEENS_DIR", tmp_path)
    path = qp._materialize_default_queen("queen_outbound")
    assert path is not None
    written = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "default_tool_categories" not in written
    assert "default_preset_skills" not in written
    assert written["name"] == qp.DEFAULT_QUEENS["queen_outbound"]["name"]


def test_self_heal_equality_holds_for_untouched_default(tmp_path, monkeypatch):
    """A freshly materialized default must compare equal to
    default_profile_persona — otherwise the /me self-heal route would treat
    every default as a user edit and never apply preferences."""
    monkeypatch.setattr(qp, "QUEENS_DIR", tmp_path)
    path = qp._materialize_default_queen("queen_sales")
    on_disk = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert on_disk == qp.default_profile_persona("queen_sales")


def test_default_profile_persona_unknown_is_none():
    assert qp.default_profile_persona("queen_nope") is None


# ---------------------------------------------------------------------------
# Retired titles — the per-install profile.yaml is a cache, and it goes stale.
# ---------------------------------------------------------------------------


def test_a_retired_title_is_replaced_by_the_shipped_one():
    """Renaming a queen has to reach installs that already materialized her.

    `profile.yaml` is written once, on first use, and never refreshed — so a
    catalog rename used to land on new installs only. Everyone who had already
    opened that queen kept the old name in the org chart, the sidebar, and her
    own greeting, with nothing on screen to explain the disagreement.
    """
    assert qp._current_title("queen_sales", "Head of Sales") == "Head of RevOps"
    assert qp.DEFAULT_QUEENS["queen_sales"]["title"] == "Head of RevOps"


def test_a_title_the_user_chose_is_never_touched():
    """The narrowness is the safety: only an EXACT retired default is replaced.

    Anything else in that field was typed by the user in the profile panel, and
    silently reverting it would be us overwriting their work to fix our own
    cache.
    """
    assert qp._current_title("queen_sales", "VP Revenue") == "VP Revenue"
    assert qp._current_title("queen_sales", "") == ""


def test_queens_with_no_retired_titles_pass_through():
    assert qp._current_title("queen_growth", "Head of Growth") == "Head of Growth"
    assert qp._current_title("queen_growth", "anything at all") == "anything at all"


def test_every_retired_title_names_a_real_queen_with_a_current_one():
    """A typo'd id here would silently do nothing forever."""
    for queen_id in qp._SUPERSEDED_TITLES:
        assert queen_id in qp.DEFAULT_QUEENS, queen_id
        current = qp.DEFAULT_QUEENS[queen_id]["title"]
        assert current, queen_id
        # The current title must not also be listed as retired, or the lookup
        # would map it onto itself and mask a later rename.
        assert current not in qp._SUPERSEDED_TITLES[queen_id], queen_id
