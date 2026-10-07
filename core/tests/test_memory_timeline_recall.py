"""Timeline extraction (``framework.agents.queen.timeline``) and the past-conversations reminder."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from framework.agent_loop.past_conversations_reminder import PastConversationsReminderSource
from framework.agent_loop.reminders import ReminderContext, ReminderHub, ReminderPoint
from framework.agents.queen import timeline as TL
from framework.llm.provider import LLMResponse

SESSION = "session_20231015_100000_abcd1234"


class FakeLLM:
    """Answers each extraction call with scripted items; records the prompts."""

    model = "fake-model"

    def __init__(self, items_for: callable) -> None:
        self.items_for = items_for
        self.prompts: list[str] = []

    async def acomplete(self, messages, system="", **kwargs) -> LLMResponse:
        prompt = messages[0]["content"]
        self.prompts.append(prompt)
        return LLMResponse(content=json.dumps({"items": self.items_for(prompt)}), model=self.model)


def _write_session(root: Path, session: str, user_messages: list[str]) -> Path:
    sdir = root / session
    sdir.mkdir(parents=True, exist_ok=True)
    events = []
    for text in user_messages:
        events.append({"type": "client_input_received", "data": {"content": text}})
        events.append({"type": "client_output_delta", "data": {"snapshot": "ok", "iteration": 0, "inner_turn": 0}})
    (sdir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return sdir


def _timeline(sdir: Path) -> list[dict]:
    path = sdir / TL.TIMELINE_FILE
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def test_extract_cleans_items_and_resolves_defaults(tmp_path: Path) -> None:
    def items(_prompt: str) -> list[dict]:
        return [
            {"session": "S1", "turn": 2, "kind": "event", "text": "The user attended Jen's wedding.", "start": "2023-10-08", "end": "2023-10-07"},
            {"session": "S1", "turn": 1, "kind": "FACT", "text": "The user commutes 45 minutes each way.", "aliases": ["drive to work"] * 6},
            {"session": "S1", "turn": 99, "kind": "rumor", "text": "Out-of-range turn and unknown kind."},
            {"session": "S9", "text": "Unknown session label is dropped."},
            {"session": "S1", "text": "   "},
        ]

    session = TL.SessionText(SESSION, TL.session_started_at(SESSION), [(1, "My commute is 45 minutes."), (2, "Back from Jen's wedding.")])
    out = asyncio.run(TL.extract(FakeLLM(items), [session]))[SESSION]

    assert [i["text"] for i in out] == [
        "The user attended Jen's wedding.",
        "The user commutes 45 minutes each way.",
        "Out-of-range turn and unknown kind.",
    ]
    wedding, commute, odd = out
    assert (wedding["start"], wedding["end"]) == ("2023-10-07", "2023-10-08")  # swapped into order
    assert commute["kind"] == "fact" and commute["start"] == commute["end"] == "2023-10-15"  # no date -> session date
    assert len(commute["aliases"]) == 4
    assert odd["kind"] == "event" and odd["turn"] == 1


def test_big_sessions_split_across_calls_but_keep_their_identity() -> None:
    # Eight messages cut to MESSAGE_CHARS each don't fit one BATCH_CHARS call.
    long = "x" * 5000
    s1 = TL.SessionText("session_20230101_000000_s1", TL.session_started_at("session_20230101_000000_s1"), [(i, long) for i in range(1, 9)])
    s2 = TL.SessionText("session_20230102_000000_s2", TL.session_started_at("session_20230102_000000_s2"), [(1, "short")])

    batches = TL._batches([s1, s2])

    assert len(batches) > 1
    assert all(sum(len(t) for s in b for _, t in s.messages) <= TL.BATCH_CHARS for b in batches)
    turns = sorted(t for b in batches for s in b if s.session_id == s1.session_id for t, _ in s.messages)
    assert turns == list(range(1, 9))
    assert any(s.session_id == s2.session_id for b in batches for s in b)


def test_update_extracts_only_new_messages(tmp_path: Path) -> None:
    sdir = _write_session(tmp_path, SESSION, ["I bought a road bike.", "I rode 40 km today."])

    def one_item_per_message(prompt: str) -> list[dict]:
        return [{"session": "S1", "turn": int(n), "text": f"item from turn {n}"} for n in re.findall(r"^\[(\d+)\]", prompt, flags=re.M)]

    llm = FakeLLM(one_item_per_message)

    assert asyncio.run(TL.update_session_timeline(llm, sdir)) == 2
    assert asyncio.run(TL.update_session_timeline(llm, sdir)) == 0  # nothing new, no call
    assert len(llm.prompts) == 1

    _write_session(tmp_path, SESSION, ["I bought a road bike.", "I rode 40 km today.", "I sold my old bike."])
    assert asyncio.run(TL.update_session_timeline(llm, sdir)) == 1
    assert "[3] I sold my old bike." in llm.prompts[-1] and "[1]" not in llm.prompts[-1]
    assert [i["turn"] for i in _timeline(sdir)] == [1, 2, 3]


def test_backfill_reuses_cached_extractions(tmp_path: Path) -> None:
    llm = FakeLLM(lambda _p: [{"session": "S1", "turn": 1, "text": "The user adopted a cat."}])
    first, second = tmp_path / "home1" / "sessions", tmp_path / "home2" / "sessions"
    _write_session(first, SESSION, ["We adopted a cat named Miso."])
    shutil.copytree(first, second)
    cache = tmp_path / "cache"

    assert asyncio.run(TL.backfill_timelines(llm, first, cache_dir=cache)) == 1
    assert asyncio.run(TL.backfill_timelines(llm, second, cache_dir=cache)) == 1
    assert len(llm.prompts) == 1  # the second home was served from cache
    assert _timeline(second / SESSION) == _timeline(first / SESSION)
    assert asyncio.run(TL.backfill_timelines(llm, first, cache_dir=cache)) == 0  # already current


# ---------------------------------------------------------------------------
# Past-conversations reminder
# ---------------------------------------------------------------------------


def _queen_ctx(provider) -> SimpleNamespace:
    return SimpleNamespace(is_queen_stream=True, past_conversation_recall_provider=provider)


def test_reminder_passes_the_user_message_to_the_provider() -> None:
    seen: list[str] = []
    source = PastConversationsReminderSource()
    ctx = _queen_ctx(lambda text: seen.append(text) or "Excerpts: commute is 45 minutes")

    body = asyncio.run(source.render(ReminderContext(point=ReminderPoint.USER_PROMPT_SUBMIT, agent_ctx=ctx, user_text="How long is my commute?")))

    assert body == "Excerpts: commute is 45 minutes"
    assert seen == ["How long is my commute?"]


def test_reminder_skips_short_messages_non_queens_and_slow_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    import framework.agent_loop.past_conversations_reminder as mod

    source = PastConversationsReminderSource()
    calls: list[str] = []
    ctx = _queen_ctx(lambda text: calls.append(text) or "x")
    assert asyncio.run(source.render(ReminderContext(point=ReminderPoint.USER_PROMPT_SUBMIT, agent_ctx=ctx, user_text="ok"))) is None
    assert calls == []
    assert not source.applies_to(SimpleNamespace(is_queen_stream=False, past_conversation_recall_provider=lambda t: "x"))
    assert not source.applies_to(SimpleNamespace(is_queen_stream=True, past_conversation_recall_provider=None))

    monkeypatch.setattr(mod, "RECALL_TIMEOUT_S", 0.05)
    slow = _queen_ctx(lambda text: time.sleep(0.5) or "late")
    rctx = ReminderContext(point=ReminderPoint.SESSION_START, agent_ctx=slow, user_text="What did I buy last week?")
    assert asyncio.run(source.render(rctx)) is None


def test_hub_hands_user_text_to_sources() -> None:
    hub = ReminderHub()
    hub.register(PastConversationsReminderSource())
    ctx = _queen_ctx(lambda text: f"related to: {text}")

    block = asyncio.run(hub.fire(ReminderPoint.USER_PROMPT_SUBMIT, ctx, user_text="Where did I meet Sophia?"))

    assert block is not None and "related to: Where did I meet Sophia?" in block
