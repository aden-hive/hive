"""The daily reflection that revises a queen's soul: what she reads, what the code lets through, when it runs."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import framework.config as hive_config
from framework.agents.queen import soul as soul_mod, soul_reflection as sr
from framework.agents.queen.soul import Item
from framework.config import get_soul_config

QUEEN = "queen_x"
NOW = datetime.fromisoformat("2026-10-21T05:00:00+08:00")
SECTIONS = [
    {"key": "now", "title": "Now", "limit": 80, "max_age_days": 14},
    {"key": "people", "title": "Me and them", "limit": 80, "evidence": 2},
]


@pytest.fixture
def home(tmp_path, monkeypatch):
    entry = {"enabled": True, "sections": SECTIONS, "sources": {"file": "channels/x/sessions.json", "keys": ["/group/"]}}
    config_file = tmp_path / "configuration.json"
    config_file.write_text(json.dumps({"soul": {"queens": {QUEEN: entry}}}), encoding="utf-8")
    monkeypatch.setattr(hive_config, "get_hive_config", lambda: json.loads(config_file.read_text(encoding="utf-8")))
    for module in (soul_mod, sr):
        monkeypatch.setattr(module, "QUEENS_DIR", tmp_path / "queens")
    monkeypatch.setattr(sr, "HIVE_HOME", tmp_path)
    monkeypatch.setattr(sr, "_identity", lambda queen_id: ("Fox", "<core_identity>Fox draws.</core_identity>"))
    (tmp_path / "channels" / "x").mkdir(parents=True)
    (tmp_path / "channels" / "x" / "sessions.json").write_text(json.dumps({"1/group/100": "s_group", "1/private/42": "s_private"}), encoding="utf-8")
    return SimpleNamespace(root=tmp_path, config=config_file, entry=entry)


def _set(home, **changes):
    home.entry.update(changes)
    home.config.write_text(json.dumps({"soul": {"queens": {QUEEN: home.entry}}}), encoding="utf-8")


def _session(home, session_id, events, *, title="Night owls", channel="x"):
    folder = home.root / "queens" / QUEEN / "sessions" / session_id
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({"title": title, "channel": channel}), encoding="utf-8")
    (folder / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return folder


def said(at, content, stream="queen"):
    return {"type": "client_input_received", "timestamp": at, "stream_id": stream, "data": {"content": content}}


def replied(at, snapshot, turn=1):
    return {
        "type": "client_output_delta",
        "timestamp": at,
        "stream_id": "queen",
        "execution_id": "e",
        "data": {"snapshot": snapshot, "iteration": turn, "inner_turn": 0},
    }


GROUP_EVENTS = [
    said("2026-10-20T14:00:00", "<system-reminder>a brief</system-reminder>\n[recent lines]\nBo(7): lol\n\n[Ann(42)]: your lantern sketch is lovely"),
    replied("2026-10-20T14:01:00", "Than"),
    replied("2026-10-20T14:01:02", "Thank you, the next one will be a cat"),
    said("2026-10-20T15:00:00", "[Bo(7)]: Ann is always praising you"),
]


def _llm(*turns):
    """A model that answers with these tool calls, one list per turn, then nothing."""

    def response(calls):
        if not calls:
            return MagicMock(content="done", raw_response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None))]))
        objs = [SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=n, arguments=json.dumps(a))) for i, (n, a) in enumerate(calls)]
        return MagicMock(content="", raw_response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=objs))]))

    llm = AsyncMock()
    llm.acomplete.side_effect = [response(t) for t in turns] + [response([])] * 4
    return llm


def _cfg():
    return get_soul_config(QUEEN)


def _tool_results(llm):
    return [m["content"] for call in llm.acomplete.call_args_list for m in call.kwargs["messages"] if m["role"] == "tool"]


def test_she_reads_what_was_said_to_her_and_her_replies(home):
    folder = _session(
        home, "s_group", [said("2026-10-19T09:00:00", "[Old(1)]: before"), *GROUP_EVENTS, said("2026-10-20T16:00:00", "[W(9)]: x", stream="worker")]
    )

    chat = sr.read_chat(folder, since="2026-10-19T23:00:00", message_chars=400, session_chars=10_000, me="Fox")

    assert chat.lines == [
        ("10-20 14:00", "Ann(42)", "your lantern sketch is lovely"),
        ("10-20 14:01", "Fox", "Thank you, the next one will be a cat"),
        ("10-20 15:00", "Bo(7)", "Ann is always praising you"),
    ]
    assert chat.last_at == "2026-10-20T15:00:00"


def test_a_long_chat_keeps_its_newest_lines(home):
    events = [said(f"2026-10-20T1{i}:00:00", f"[Ann(42)]: message number {i}") for i in range(6)]
    folder = _session(home, "s_group", events)

    chat = sr.read_chat(folder, since="", message_chars=400, session_chars=90, me="Fox")

    assert [text for _, _, text in chat.lines] == ["message number 4", "message number 5"]


def test_only_the_chats_the_source_file_lets_in_are_read(home):
    _session(home, "s_group", GROUP_EVENTS)
    _session(home, "s_private", GROUP_EVENTS, title="Ann")
    _session(home, "s_dashboard", GROUP_EVENTS, title="Planning", channel=None)

    assert [d.name for d in sr.sessions_to_read(QUEEN, _cfg())] == ["s_group"]


@pytest.mark.asyncio
async def test_a_change_resting_on_what_was_said_waits_for_approval(home):
    _session(home, "s_group", GROUP_EVENTS)
    llm = _llm(
        [("add_item", {"section": "now", "text": "next I draw a cat", "date": "2026-10-20", "evidence": ["the next one will be a cat"]})],
        [("finish", {"summary": "promised a cat"})],
    )

    proposal = await sr.reflect(QUEEN, _cfg(), llm, now=NOW)

    assert [(e.op, e.section, e.text) for e in proposal.edits] == [("add", "now", "next I draw a cat")]
    assert proposal.edits[0].evidence == [{"quote": "the next one will be a cat", "where": "Night owls · Fox"}]
    assert (proposal.summary, proposal.status, proposal.sources) == ("promised a cat", "pending", ["Night owls"])
    assert soul_mod.load(QUEEN).is_empty()
    assert soul_mod.pending_proposal(QUEEN).id == proposal.id
    assert sr.load_state(QUEEN)["cursors"]["s_group"] == "2026-10-20T15:00:00"
    system = llm.acomplete.call_args_list[0].kwargs["system"]
    assert system.startswith("You are Fox.") and "<core_identity>Fox draws.</core_identity>" in system


@pytest.mark.asyncio
async def test_a_quote_nobody_said_is_refused_and_she_can_correct_it(home):
    _session(home, "s_group", GROUP_EVENTS)
    llm = _llm(
        [("add_item", {"section": "now", "text": "Ann loves me", "evidence": ["Ann said she loves me"]})],
        [("add_item", {"section": "now", "text": "Ann likes my lantern", "evidence": ["your lantern sketch is lovely"]})],
        [("finish", {"summary": "ok"})],
    )

    proposal = await sr.reflect(QUEEN, _cfg(), llm, now=NOW)

    assert [e.text for e in proposal.edits] == ["Ann likes my lantern"]
    assert "is not in what you read" in _tool_results(llm)[0]


@pytest.mark.asyncio
async def test_a_section_that_needs_two_sources_refuses_one(home):
    _session(home, "s_group", GROUP_EVENTS)
    llm = _llm(
        [("add_item", {"section": "people", "text": "Ann is kind to me", "evidence": ["your lantern sketch is lovely"]})],
        [
            (
                "add_item",
                {"section": "people", "text": "Ann is kind to me", "evidence": ["your lantern sketch is lovely", "Ann is always praising you"]},
            )
        ],
    )

    proposal = await sr.reflect(QUEEN, _cfg(), llm, now=NOW)

    assert "needs quotes from 2 different people or chats; you gave 1" in _tool_results(llm)[0]
    assert [(e.section, len(e.evidence)) for e in proposal.edits] == [("people", 2)]


@pytest.mark.asyncio
async def test_changes_past_the_budget_and_over_the_limit_are_refused(home):
    _set(home, max_edits=1)
    _session(home, "s_group", GROUP_EVENTS)
    llm = _llm(
        [("add_item", {"section": "now", "text": "x" * 81, "evidence": ["the next one will be a cat"]})],
        [("add_item", {"section": "now", "text": "a cat next", "evidence": ["the next one will be a cat"]})],
        [("add_item", {"section": "now", "text": "and a fox", "evidence": ["the next one will be a cat"]})],
    )

    proposal = await sr.reflect(QUEEN, _cfg(), llm, now=NOW)

    results = _tool_results(llm)
    assert "would hold 81/80 characters" in results[0]
    assert "all 1 changes" in results[2]
    assert [e.text for e in proposal.edits] == ["a cat next"]


@pytest.mark.asyncio
async def test_saying_the_same_thing_twice_is_refused(home):
    soul_mod.save(QUEEN, _cfg(), {"now": [Item("a cat next")]}, author="owner", note="v1")
    _session(home, "s_group", GROUP_EVENTS)
    llm = _llm(
        [("add_item", {"section": "now", "text": "a  cat next", "evidence": ["the next one will be a cat"]})],
        [("add_item", {"section": "now", "text": "and a fox", "evidence": ["the next one will be a cat"]})],
        [("add_item", {"section": "now", "text": "and a fox", "evidence": ["the next one will be a cat"]})],
    )

    proposal = await sr.reflect(QUEEN, _cfg(), llm, now=NOW)

    results = _tool_results(llm)
    assert "already says that" in results[0] and "already says that" in results[2]
    assert [e.text for e in proposal.edits] == ["and a fox"]


@pytest.mark.asyncio
async def test_items_past_their_age_are_dropped_on_their_own(home):
    soul_mod.save(QUEEN, _cfg(), {"now": [Item("drawing a lantern", "2026-09-01"), Item("tired today", "2026-10-20")]}, author="owner", note="v1")
    _session(home, "s_group", GROUP_EVENTS)
    llm = _llm(
        [("update_item", {"section": "now", "number": 1, "text": "x", "evidence": ["the next one will be a cat"]})],
        [("finish", {"summary": "nothing new"})],
    )

    proposal = await sr.reflect(QUEEN, _cfg(), llm, now=NOW)

    assert [(e.op, e.old, e.expired) for e in proposal.edits] == [("remove", "drawing a lantern", True)]
    assert "already being changed" in _tool_results(llm)[0]


@pytest.mark.asyncio
async def test_auto_mode_applies_the_changes_at_once(home):
    _set(home, mode="auto")
    _session(home, "s_group", GROUP_EVENTS)
    llm = _llm([("add_item", {"section": "now", "text": "a cat next", "date": "2026-10-20", "evidence": ["the next one will be a cat"]})])

    proposal = await sr.reflect(QUEEN, _cfg(), llm, now=NOW)

    assert soul_mod.load(QUEEN).items("now") == [Item("a cat next", "2026-10-20")]
    assert soul_mod.load_proposal(QUEEN, proposal.id).status == "applied"
    assert soul_mod.history(QUEEN)[0]["author"] == "her"


@pytest.mark.asyncio
async def test_nothing_new_records_the_run_without_asking_the_model(home):
    _session(home, "s_group", GROUP_EVENTS)
    sr.save_state(QUEEN, {"cursors": {"s_group": "2026-10-20T15:00:00"}})
    llm = _llm()

    assert await sr.reflect(QUEEN, _cfg(), llm, now=NOW) is None

    llm.acomplete.assert_not_awaited()
    assert sr.load_state(QUEEN)["last_run"] == "2026-10-21"


@pytest.mark.asyncio
async def test_the_first_draft_reads_the_listed_memories(home, monkeypatch):
    from framework.agents.queen import queen_memory_v2

    memory = home.root / "memories" / QUEEN
    memory.mkdir(parents=True)
    (memory / "me.md").write_text("---\nname: me\n---\nI used to hiss at everyone, now I tease softly.", encoding="utf-8")
    monkeypatch.setattr(queen_memory_v2, "queen_memory_dir", lambda queen_id: memory)
    _set(home, bootstrap_memories=["me.md"])
    llm = _llm([("add_item", {"section": "now", "text": "I tease softly now", "evidence": ["now I tease softly"]})])

    proposal = await sr.reflect(QUEEN, _cfg(), llm, bootstrap=True, now=NOW)

    assert proposal.bootstrap and proposal.sources == ["memory me.md"]
    assert proposal.edits[0].evidence[0]["where"] == "memory me.md · memory"
    assert "This is your first time" in llm.acomplete.call_args_list[0].kwargs["messages"][0]["content"]


def test_when_the_reflection_is_due(home):
    cfg = _cfg()
    assert not sr.due(QUEEN, cfg, datetime.fromisoformat("2026-10-21T03:59:00+08:00"))
    assert sr.due(QUEEN, cfg, NOW)

    sr.save_state(QUEEN, {"last_run": "2026-10-21"})
    assert not sr.due(QUEEN, cfg, NOW)

    sr.save_state(QUEEN, {"attempts": {"day": "2026-10-21", "count": 3, "at": "2026-10-21T01:00:00+08:00"}})
    assert not sr.due(QUEEN, cfg, NOW)
    sr.save_state(QUEEN, {"attempts": {"day": "2026-10-21", "count": 1, "at": "2026-10-21T04:30:00+08:00"}})
    assert not sr.due(QUEEN, cfg, NOW)  # retried less than an hour ago


def test_a_pending_proposal_holds_the_next_reflection_in_review_mode(home):
    soul_mod.save_proposal(QUEEN, soul_mod.Proposal(id="2026-10-20-040000", created_at="", base_version=0, edits=[]))

    assert not sr.due(QUEEN, _cfg(), NOW)
