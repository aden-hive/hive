"""A queen's soul: configuration, versions, proposals, and its place in her prompt."""

from __future__ import annotations

import json

import pytest

import framework.config as hive_config
from framework.agents.queen import soul as soul_mod
from framework.agents.queen.soul import Edit, Item, Proposal, SoulError
from framework.config import SoulSection, get_soul_config

QUEEN = "queen_x"
SECTIONS = [
    {"key": "now", "title": "Now", "limit": 40, "max_age_days": 14},
    {"key": "people", "title": "Me and them", "limit": 60, "evidence": 2},
]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A HIVE_HOME with a configuration that gives queen_x a soul."""
    config = {"soul": {"queens": {QUEEN: {"enabled": True, "sections": SECTIONS, "header": "Your own notes."}}}}
    config_file = tmp_path / "configuration.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(hive_config, "get_hive_config", lambda: json.loads(config_file.read_text(encoding="utf-8")))
    monkeypatch.setattr(soul_mod, "QUEENS_DIR", tmp_path / "queens")
    monkeypatch.setattr(soul_mod, "HIVE_CONFIG_FILE", config_file)
    soul_mod._prompt_cache.clear()
    return config_file


def _cfg():
    return get_soul_config(QUEEN)


def test_a_queen_without_a_soul_entry_has_none(home):
    assert get_soul_config("queen_other") is None
    assert get_soul_config(None) is None


def test_the_configured_sections_and_defaults(home):
    cfg = _cfg()

    assert [s.key for s in cfg.sections] == ["now", "people"]
    assert cfg.sections[0] == SoulSection("now", "Now", 40, max_age_days=14, evidence=1)
    assert cfg.sections[1].evidence == 2
    assert (cfg.mode, cfg.hour, cfg.max_edits, cfg.model) == ("review", 4, 5, "queen")


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"mode": "sometimes", "hour": 24, "max_edits": 0, "model": "big"}, ("review", 4, 5, "queen")),
        ({"mode": "auto", "hour": 0, "max_edits": 3, "model": "worker"}, ("auto", 0, 3, "worker")),
        ({"hour": True, "max_edits": "5"}, ("review", 4, 5, "queen")),
    ],
)
def test_invalid_values_fall_back_to_defaults(home, entry, expected):
    home.write_text(json.dumps({"soul": {"queens": {QUEEN: entry}}}), encoding="utf-8")

    cfg = _cfg()

    assert (cfg.mode, cfg.hour, cfg.max_edits, cfg.model) == expected
    assert [s.key for s in cfg.sections] == ["now", "people", "threads", "views", "changes"]


def test_duplicate_section_keys_fall_back_to_the_default_sections(home):
    home.write_text(json.dumps({"soul": {"queens": {QUEEN: {"sections": [SECTIONS[0], SECTIONS[0]]}}}}), encoding="utf-8")

    assert [s.key for s in _cfg().sections] == ["now", "people", "threads", "views", "changes"]


def test_a_disabled_soul_is_none(home):
    home.write_text(json.dumps({"soul": {"queens": {QUEEN: {"enabled": False}}}}), encoding="utf-8")

    assert _cfg() is None


def test_each_save_is_a_new_version_with_history(home):
    first = soul_mod.save(QUEEN, _cfg(), {"now": [Item("drawing a lantern", "2026-10-20")]}, author="owner", note="first")
    second = soul_mod.save(QUEEN, _cfg(), {"now": [Item("finished the lantern", "2026-10-21")]}, author="her", note="second")

    assert (first.version, second.version) == (1, 2)
    assert soul_mod.load(QUEEN).items("now") == [Item("finished the lantern", "2026-10-21")]
    assert soul_mod.load_version(QUEEN, 1).items("now") == [Item("drawing a lantern", "2026-10-20")]
    assert [(h["version"], h["author"], h["note"]) for h in soul_mod.history(QUEEN)] == [(2, "her", "second"), (1, "owner", "first")]


def test_a_section_over_its_limit_is_refused_and_nothing_changes(home):
    with pytest.raises(SoulError, match=r"Now: 41/40 characters"):
        soul_mod.save(QUEEN, _cfg(), {"now": [Item("x" * 41)]}, author="owner", note="too long")

    assert soul_mod.load(QUEEN).version == 0
    assert not (soul_mod.soul_dir(QUEEN) / "log.jsonl").exists()


def test_rollback_makes_an_old_version_current_again(home):
    soul_mod.save(QUEEN, _cfg(), {"now": [Item("one")]}, author="owner", note="v1")
    soul_mod.save(QUEEN, _cfg(), {"now": [Item("two")]}, author="owner", note="v2")

    back = soul_mod.rollback(QUEEN, _cfg(), 1)

    assert back.version == 3
    assert back.items("now") == [Item("one")]
    assert soul_mod.history(QUEEN)[0]["note"] == "back to version 1"
    with pytest.raises(SoulError, match="no version 9"):
        soul_mod.rollback(QUEEN, _cfg(), 9)


def _proposal(edits):
    return Proposal(id="2026-10-21", created_at="2026-10-21T04:00:00+08:00", base_version=1, edits=edits)


def test_approving_some_changes_applies_only_those(home):
    soul_mod.save(QUEEN, _cfg(), {"now": [Item("drawing a lantern")], "people": [Item("Ann teases me")]}, author="owner", note="v1")
    proposal = _proposal(
        [
            Edit(op="update", section="now", old="drawing a lantern", text="lantern done, next a cat", date="2026-10-21"),
            Edit(op="add", section="people", text="Bo asks for drawings late", date="2026-10-21"),
            Edit(op="remove", section="people", old="Ann teases me"),
        ]
    )
    soul_mod.save_proposal(QUEEN, proposal)

    soul = soul_mod.decide(QUEEN, _cfg(), soul_mod.pending_proposal(QUEEN), [0, 1])

    assert soul.items("now") == [Item("lantern done, next a cat", "2026-10-21")]
    assert soul.items("people") == [Item("Ann teases me"), Item("Bo asks for drawings late", "2026-10-21")]
    decided = soul_mod.load_proposal(QUEEN, "2026-10-21")
    assert (decided.status, decided.applied) == ("applied", [0, 1])
    assert soul_mod.pending_proposal(QUEEN) is None


def test_a_change_to_an_item_edited_since_no_longer_applies(home):
    soul_mod.save(QUEEN, _cfg(), {"now": [Item("drawing a lantern")]}, author="owner", note="v1")
    soul_mod.save(QUEEN, _cfg(), {"now": [Item("drawing a fox")]}, author="owner", note="edited by hand")
    proposal = _proposal([Edit(op="remove", section="now", old="drawing a lantern")])

    with pytest.raises(SoulError, match="change 1 no longer applies"):
        soul_mod.decide(QUEEN, _cfg(), proposal, None)

    assert soul_mod.load(QUEEN).items("now") == [Item("drawing a fox")]


def test_dismissing_applies_nothing(home):
    soul_mod.save(QUEEN, _cfg(), {"now": [Item("drawing a lantern")]}, author="owner", note="v1")
    proposal = _proposal([Edit(op="remove", section="now", old="drawing a lantern")])

    assert soul_mod.decide(QUEEN, _cfg(), proposal, []) is None

    assert soul_mod.load(QUEEN).version == 1
    assert soul_mod.load_proposal(QUEEN, "2026-10-21").status == "dismissed"


def test_the_soul_rides_her_prompt_right_after_her_identity(home):
    from framework.tools.queen_lifecycle_tools import QueenPhaseState

    soul_mod.save(QUEEN, _cfg(), {"now": [Item("drawing a lantern", "2026-10-20")]}, author="owner", note="v1")
    state = QueenPhaseState(phase="independent")
    state.queen_id = QUEEN
    state.queen_identity_prompt = "<core_identity>I am X.</core_identity>"

    prompt = state.get_static_prompt()

    soul_block = "<soul>\nYour own notes.\n\n## Now\n- drawing a lantern (10/20)\n</soul>"
    assert prompt.startswith("<core_identity>I am X.</core_identity>\n\n" + soul_block)


def test_her_prompt_follows_a_new_version_and_drops_a_disabled_soul(home):
    soul_mod.save(QUEEN, _cfg(), {"now": [Item("one")]}, author="owner", note="v1")
    assert "- one" in soul_mod.prompt_for(QUEEN)

    soul_mod.save(QUEEN, _cfg(), {"now": [Item("two")]}, author="owner", note="v2")
    assert "- two" in soul_mod.prompt_for(QUEEN)

    home.write_text(json.dumps({"soul": {"queens": {QUEEN: {"enabled": False}}}}), encoding="utf-8")
    assert soul_mod.prompt_for(QUEEN) == ""


def test_an_empty_soul_adds_nothing_to_her_prompt(home):
    assert soul_mod.prompt_for(QUEEN) == ""
    assert soul_mod.prompt_for(None) == ""
