"""Probes: the same questions answered with the soul before and after a proposal's changes."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import framework.config as hive_config
from framework.agents.queen import soul as soul_mod, soul_probes, soul_reflection as sr
from framework.agents.queen.soul import Edit, Item, Proposal
from framework.config import get_soul_config

QUEEN = "queen_x"


@pytest.fixture
def home(tmp_path, monkeypatch):
    config = {"soul": {"queens": {QUEEN: {"enabled": True, "sections": [{"key": "now", "title": "Now", "limit": 80}]}}}}
    monkeypatch.setattr(hive_config, "get_hive_config", lambda: config)
    monkeypatch.setattr(soul_mod, "QUEENS_DIR", tmp_path / "queens")
    monkeypatch.setattr(sr, "_identity", lambda queen_id: ("Fox", "<core_identity>Fox draws.</core_identity>"))
    return tmp_path


def _llm():
    """Answers "cat" when the soul it was given mentions the cat, else "lantern"."""

    async def answer(*, messages, system, max_tokens):
        return MagicMock(content="cat" if "a cat next" in system else "lantern")

    return SimpleNamespace(acomplete=AsyncMock(side_effect=answer))


def _write_probes(probes):
    folder = soul_mod.soul_dir(QUEEN)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / soul_probes.PROBES_FILE).write_text(json.dumps(probes), encoding="utf-8")


@pytest.mark.asyncio
async def test_each_probe_is_answered_before_and_after_the_changes(home):
    cfg = get_soul_config(QUEEN)
    soul_mod.save(QUEEN, cfg, {"now": [Item("drawing a lantern")]}, author="owner", note="v1")
    _write_probes([{"q": "[Ann(42)]: what are you drawing?", "anchor": "a lantern, for now"}, {"q": "hi", "extra": 1}, {"q": " "}])
    proposal = Proposal(id="p1", created_at="", base_version=1, edits=[Edit(op="update", section="now", old="drawing a lantern", text="a cat next")])
    soul_mod.save_proposal(QUEEN, proposal)
    llm = _llm()

    results = await soul_probes.probe(QUEEN, cfg, llm, proposal)

    assert results == [
        {"q": "[Ann(42)]: what are you drawing?", "anchor": "a lantern, for now", "before": "lantern", "after": "cat"},
        {"q": "hi", "anchor": "", "before": "lantern", "after": "cat"},
    ]
    assert soul_mod.load_proposal(QUEEN, "p1").probes == results
    assert llm.acomplete.await_count == 4
    assert not soul_probes.is_probing(QUEEN)


@pytest.mark.asyncio
async def test_without_probe_questions_nothing_is_asked(home):
    llm = _llm()

    assert await soul_probes.probe(QUEEN, get_soul_config(QUEEN), llm, Proposal(id="p1", created_at="", base_version=0, edits=[])) == []

    llm.acomplete.assert_not_awaited()


def test_a_probe_brings_the_memories_that_mention_its_speaker(home, monkeypatch):
    from framework.agents.queen import queen_memory_v2

    queen_memory, global_memory = home / "mem_queen", home / "mem_global"
    queen_memory.mkdir()
    global_memory.mkdir()
    (queen_memory / "sister.md").write_text("Ann (10000001) is my big sister.", encoding="utf-8")
    (queen_memory / "other.md").write_text("Bo (20000002) likes cats.", encoding="utf-8")
    (global_memory / "owner.md").write_text("The owner is 30000003.", encoding="utf-8")
    monkeypatch.setattr(queen_memory_v2, "queen_memory_dir", lambda queen_id: queen_memory)
    monkeypatch.setattr(queen_memory_v2, "global_memory_dir", lambda: global_memory)

    block = soul_probes.related_memories(QUEEN, "[Ann(10000001)]: pat pat")

    assert block == "<recalled_memories>\n### sister.md\nAnn (10000001) is my big sister.\n</recalled_memories>"
    assert soul_probes.related_memories(QUEEN, "hello there") == ""
