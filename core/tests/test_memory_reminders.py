"""How memory notes reach the queen before she answers: the "wait" and "index" recall modes."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from framework import config
from framework.agent_loop.memory_reminders import (
    INDEX_CHANGED_HEADER,
    INDEX_HEADER,
    RECALL_HEADER,
    MemoryIndexReminderSource,
    MemoryRecallReminderSource,
)
from framework.agent_loop.reminders import ReminderContext, ReminderPoint
from framework.agents.queen.recall_selector import memory_index


def _render(source, ctx, point=ReminderPoint.USER_PROMPT_SUBMIT, user_text=None):
    return asyncio.run(source.render(ReminderContext(point=point, agent_ctx=ctx, user_text=user_text)))


def _note(directory: Path, filename: str, description: str, body: str = "") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(f"---\nname: {filename[:-3]}\ntype: preference\ndescription: {description}\n---\n{body}\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_recall_mode_defaults_to_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HIVE_MEMORY_RECALL", raising=False)
    monkeypatch.setattr(config, "get_hive_config", lambda: {"memory_recall": {"mode": "someday", "wait_seconds": -1}})

    assert config.get_memory_recall_config() == config.MemoryRecallConfig(mode="index", wait_seconds=10.0)


def test_recall_mode_comes_from_the_config_and_the_env_overrides_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "get_hive_config", lambda: {"memory_recall": {"mode": "wait", "wait_seconds": 4}})
    monkeypatch.delenv("HIVE_MEMORY_RECALL", raising=False)
    assert config.get_memory_recall_config() == config.MemoryRecallConfig(mode="wait", wait_seconds=4.0)

    monkeypatch.setenv("HIVE_MEMORY_RECALL", "index")
    assert config.get_memory_recall_config().mode == "index"


# ---------------------------------------------------------------------------
# "wait": a model's pick, before she answers
# ---------------------------------------------------------------------------


def _recall_ctx(provider) -> SimpleNamespace:
    return SimpleNamespace(is_queen_stream=True, memory_recall_provider=provider)


def _set_mode(monkeypatch: pytest.MonkeyPatch, mode: str, **section) -> None:
    monkeypatch.delenv("HIVE_MEMORY_RECALL", raising=False)
    monkeypatch.setattr(config, "get_hive_config", lambda: {"memory_recall": {"mode": mode, **section}})


def test_wait_shows_the_pick_for_the_users_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_mode(monkeypatch, "wait")
    seen: list[str] = []

    async def pick(text: str) -> str:
        seen.append(text)
        return "### tea.md\n\nAva drinks pu-erh."

    body = _render(MemoryRecallReminderSource(), _recall_ctx(pick), point=ReminderPoint.SESSION_START, user_text="What tea do I like?")

    assert body == f"{RECALL_HEADER}\n\n### tea.md\n\nAva drinks pu-erh."
    assert seen == ["What tea do I like?"]


def test_wait_shows_an_unchanged_pick_once_until_compaction(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_mode(monkeypatch, "wait")

    async def pick(text: str) -> str:
        return "### tea.md\n\nAva drinks pu-erh."

    source, ctx = MemoryRecallReminderSource(), _recall_ctx(pick)
    assert _render(source, ctx, user_text="What tea do I like?") is not None
    assert _render(source, ctx, user_text="And for breakfast?") is None

    assert _render(source, ctx, point=ReminderPoint.POST_COMPACT) is None
    assert _render(source, ctx, user_text="And for breakfast?") is not None


def test_wait_gives_up_past_its_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_mode(monkeypatch, "wait", wait_seconds=0.05)

    async def slow(text: str) -> str:
        await asyncio.sleep(1)
        return "late"

    assert _render(MemoryRecallReminderSource(), _recall_ctx(slow), user_text="What tea do I like?") is None


def test_wait_applies_only_to_a_queen_with_a_pick(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_mode(monkeypatch, "wait")

    async def pick(text: str) -> str:
        return ""

    source = MemoryRecallReminderSource()
    assert source.applies_to(_recall_ctx(pick))
    assert not source.applies_to(SimpleNamespace(is_queen_stream=False, memory_recall_provider=pick))
    assert not source.applies_to(SimpleNamespace(is_queen_stream=True, memory_recall_provider=None))
    assert _render(source, _recall_ctx(pick), user_text="What tea do I like?") is None


def test_wait_is_silent_while_another_mode_is_set_and_shows_the_pick_again_after(monkeypatch: pytest.MonkeyPatch) -> None:
    async def pick(text: str) -> str:
        return "### tea.md\n\nAva drinks pu-erh."

    source, ctx = MemoryRecallReminderSource(), _recall_ctx(pick)
    _set_mode(monkeypatch, "wait")
    assert _render(source, ctx, user_text="What tea do I like?") is not None

    _set_mode(monkeypatch, "index")
    assert _render(source, ctx, user_text="What tea do I like?") is None

    _set_mode(monkeypatch, "wait")
    assert _render(source, ctx, user_text="What tea do I like?") is not None


# ---------------------------------------------------------------------------
# "index": every note listed, she reads what she wants
# ---------------------------------------------------------------------------


def test_index_lists_each_scopes_notes(tmp_path: Path) -> None:
    shared, own = tmp_path / "global", tmp_path / "queen"
    _note(shared, "tea.md", "What Ava drinks")
    _note(own, "garden.md", "Ava's balcony garden")

    scopes = memory_index([("Shared", shared), ("Yours", own), ("Nowhere", None), ("Empty", tmp_path / "empty")])

    assert scopes == [
        ("Shared", shared, {"tea.md": "[preference] tea.md: What Ava drinks"}),
        ("Yours", own, {"garden.md": "[preference] garden.md: Ava's balcony garden"}),
    ]


def _index_ctx(tmp_path: Path) -> SimpleNamespace:
    folders = [("Shared", tmp_path / "global"), ("Yours", tmp_path / "queen")]
    return SimpleNamespace(is_queen_stream=True, memory_index_provider=lambda: memory_index(folders))


def test_index_is_shown_in_full_at_the_start(tmp_path: Path) -> None:
    _note(tmp_path / "global", "tea.md", "What Ava drinks")
    _note(tmp_path / "queen", "garden.md", "Ava's balcony garden")

    body = _render(MemoryIndexReminderSource(), _index_ctx(tmp_path), point=ReminderPoint.SESSION_START, user_text="Hi")

    assert body == (
        f"{INDEX_HEADER}\n\n"
        f"## Shared ({(tmp_path / 'global').as_posix()})\n- [preference] tea.md: What Ava drinks\n\n"
        f"## Yours ({(tmp_path / 'queen').as_posix()})\n- [preference] garden.md: Ava's balcony garden"
    )


def test_index_then_shows_only_what_changed(tmp_path: Path) -> None:
    shared, own = tmp_path / "global", tmp_path / "queen"
    _note(shared, "tea.md", "What Ava drinks")
    _note(shared, "pets.md", "Ava's cat")
    _note(own, "garden.md", "Ava's balcony garden")
    source, ctx = MemoryIndexReminderSource(), _index_ctx(tmp_path)
    _render(source, ctx, point=ReminderPoint.SESSION_START, user_text="Hi")

    assert _render(source, ctx, user_text="How are you?") is None

    _note(shared, "tea.md", "What Ava drinks, morning and night")
    _note(shared, "work.md", "Where Ava works")
    # Newest first, as the notes are scanned.
    os.utime(shared / "tea.md", (1_000_000, 1_000_000))
    os.utime(shared / "work.md", (2_000_000, 2_000_000))
    (shared / "pets.md").unlink()
    (own / "garden.md").unlink()
    body = _render(source, ctx, user_text="What should I drink?")

    assert body == (
        f"{INDEX_CHANGED_HEADER}\n\n"
        f"## Shared ({shared.as_posix()})\n"
        "New or updated:\n"
        "- [preference] work.md: Where Ava works\n"
        "- [preference] tea.md: What Ava drinks, morning and night\n"
        "Removed:\n"
        "- pets.md\n\n"
        f"## Yours ({own.as_posix()})\n"
        "Removed:\n"
        "- garden.md"
    )


def test_index_is_shown_in_full_again_after_compaction(tmp_path: Path) -> None:
    _note(tmp_path / "global", "tea.md", "What Ava drinks")
    source, ctx = MemoryIndexReminderSource(), _index_ctx(tmp_path)
    _render(source, ctx, point=ReminderPoint.SESSION_START, user_text="Hi")

    body = _render(source, ctx, point=ReminderPoint.POST_COMPACT)

    assert body is not None and body.startswith(INDEX_HEADER)
    assert "- [preference] tea.md: What Ava drinks" in body


def test_index_says_nothing_without_notes(tmp_path: Path) -> None:
    source, ctx = MemoryIndexReminderSource(), _index_ctx(tmp_path)

    assert _render(source, ctx, point=ReminderPoint.SESSION_START, user_text="Hi") is None

    _note(tmp_path / "global", "tea.md", "What Ava drinks")
    body = _render(source, ctx, user_text="What tea do I like?")
    assert body is not None and body.startswith(INDEX_HEADER)


def test_index_is_silent_while_another_mode_is_set_and_lists_in_full_after(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _note(tmp_path / "global", "tea.md", "What Ava drinks")
    source, ctx = MemoryIndexReminderSource(), _index_ctx(tmp_path)
    _render(source, ctx, point=ReminderPoint.SESSION_START, user_text="Hi")

    _set_mode(monkeypatch, "wait")
    assert _render(source, ctx, user_text="What tea do I like?") is None

    _set_mode(monkeypatch, "index")
    body = _render(source, ctx, user_text="And for breakfast?")
    assert body is not None and body.startswith(INDEX_HEADER)
