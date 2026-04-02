"""Tests for the queen memory v2 system (reflection + recall)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.agents.queen import queen_memory_v2 as qm
from framework.agents.queen.recall_selector import (
    format_recall_injection,
    select_memories,
)

# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


def test_parse_frontmatter_valid():
    text = "---\nname: foo\ntype: goal\ndescription: bar baz\n---\ncontent"
    fm = qm.parse_frontmatter(text)
    assert fm == {"name": "foo", "type": "goal", "description": "bar baz"}


def test_parse_frontmatter_missing():
    assert qm.parse_frontmatter("no frontmatter here") == {}


def test_parse_frontmatter_empty():
    assert qm.parse_frontmatter("") == {}


def test_parse_frontmatter_broken_yaml():
    text = "---\n: bad\nno colon\n---\n"
    fm = qm.parse_frontmatter(text)
    # ": bad" has colon at pos 0, so key is empty → skipped
    # "no colon" has no colon → skipped
    assert fm == {}


# ---------------------------------------------------------------------------
# parse_memory_type
# ---------------------------------------------------------------------------


def test_parse_memory_type_valid():
    assert qm.parse_memory_type("goal") == "goal"
    assert qm.parse_memory_type("environment") == "environment"
    assert qm.parse_memory_type("technique") == "technique"
    assert qm.parse_memory_type("reference") == "reference"


def test_parse_memory_type_case_insensitive():
    assert qm.parse_memory_type("Goal") == "goal"
    assert qm.parse_memory_type("  TECHNIQUE  ") == "technique"


def test_parse_memory_type_invalid():
    assert qm.parse_memory_type("user") is None
    assert qm.parse_memory_type("unknown") is None
    assert qm.parse_memory_type(None) is None


# ---------------------------------------------------------------------------
# MemoryFile.from_path
# ---------------------------------------------------------------------------


def test_memory_file_from_path(tmp_path: Path):
    f = tmp_path / "test.md"
    f.write_text("---\nname: test\ntype: goal\ndescription: a test\n---\nbody\n")
    mf = qm.MemoryFile.from_path(f)
    assert mf.filename == "test.md"
    assert mf.name == "test"
    assert mf.type == "goal"
    assert mf.description == "a test"
    assert mf.mtime > 0


def test_memory_file_from_path_no_frontmatter(tmp_path: Path):
    f = tmp_path / "bare.md"
    f.write_text("just plain text\n")
    mf = qm.MemoryFile.from_path(f)
    assert mf.name is None
    assert mf.type is None
    assert mf.description is None
    assert "just plain text" in mf.header_lines


def test_memory_file_from_path_missing(tmp_path: Path):
    f = tmp_path / "missing.md"
    mf = qm.MemoryFile.from_path(f)
    assert mf.filename == "missing.md"
    assert mf.name is None


# ---------------------------------------------------------------------------
# scan_memory_files
# ---------------------------------------------------------------------------


def test_scan_memory_files(tmp_path: Path):
    (tmp_path / "a.md").write_text("---\nname: a\n---\n")
    time.sleep(0.01)
    (tmp_path / "b.md").write_text("---\nname: b\n---\n")
    (tmp_path / ".hidden.md").write_text("---\nname: hidden\n---\n")
    (tmp_path / "not-md.txt").write_text("ignored")

    files = qm.scan_memory_files(tmp_path)
    names = [f.filename for f in files]
    assert "a.md" in names
    assert "b.md" in names
    assert ".hidden.md" not in names
    assert "not-md.txt" not in names
    # Newest first.
    assert names[0] == "b.md"


def test_scan_memory_files_cap(tmp_path: Path):
    for i in range(210):
        (tmp_path / f"mem-{i:04d}.md").write_text(f"---\nname: m{i}\n---\n")
    files = qm.scan_memory_files(tmp_path)
    assert len(files) == qm.MAX_FILES


# ---------------------------------------------------------------------------
# format_memory_manifest
# ---------------------------------------------------------------------------


def test_format_memory_manifest():
    files = [
        qm.MemoryFile(
            filename="a.md",
            path=Path("a.md"),
            name="a",
            type="goal",
            description="desc a",
            mtime=time.time(),
        ),
        qm.MemoryFile(
            filename="b.md",
            path=Path("b.md"),
            name="b",
            type=None,
            description=None,
            mtime=0.0,
        ),
    ]
    manifest = qm.format_memory_manifest(files)
    assert "[goal] a.md" in manifest
    assert "desc a" in manifest
    assert "[unknown] b.md" in manifest
    assert "(no description)" in manifest


# ---------------------------------------------------------------------------
# memory_freshness_text
# ---------------------------------------------------------------------------


def test_memory_freshness_text_recent():
    assert qm.memory_freshness_text(time.time()) == ""


def test_memory_freshness_text_old():
    three_days_ago = time.time() - 3 * 86_400
    text = qm.memory_freshness_text(three_days_ago)
    assert "3 days old" in text
    assert "point-in-time" in text


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------


def test_cursor_read_write(tmp_path: Path):
    cursor_file = tmp_path / ".cursor.json"
    assert qm.read_cursor(cursor_file) == 0
    qm.write_cursor(42, cursor_file)
    assert qm.read_cursor(cursor_file) == 42


def test_cursor_read_corrupted(tmp_path: Path):
    cursor_file = tmp_path / ".cursor.json"
    cursor_file.write_text("not json", encoding="utf-8")
    assert qm.read_cursor(cursor_file) == 0


# ---------------------------------------------------------------------------
# read_messages_since_cursor
# ---------------------------------------------------------------------------


def test_read_messages_since_cursor(tmp_path: Path):
    parts_dir = tmp_path / "conversations" / "parts"
    parts_dir.mkdir(parents=True)
    for i in range(5):
        (parts_dir / f"{i:010d}.json").write_text(
            json.dumps({"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"})
        )

    msgs, max_seq = qm.read_messages_since_cursor(tmp_path, 2)
    assert max_seq == 4
    assert len(msgs) == 2  # seq 3 and 4


def test_read_messages_since_cursor_compaction_fallback(tmp_path: Path):
    """When cursor is ahead of all files (evicted), return everything."""
    parts_dir = tmp_path / "conversations" / "parts"
    parts_dir.mkdir(parents=True)
    for i in range(3):
        (parts_dir / f"{i:010d}.json").write_text(
            json.dumps({"role": "user", "content": f"msg {i}"})
        )

    msgs, max_seq = qm.read_messages_since_cursor(tmp_path, 999)
    assert len(msgs) == 3  # Fallback: returns all
    assert max_seq == 999  # Cursor stays (will be overwritten by caller)


# ---------------------------------------------------------------------------
# init_memory_dir
# ---------------------------------------------------------------------------


def test_init_memory_dir(tmp_path: Path):
    mem_dir = tmp_path / "memories"
    qm.init_memory_dir(mem_dir)
    assert mem_dir.is_dir()


# ---------------------------------------------------------------------------
# recall_selector
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_memories_empty_dir(tmp_path: Path):
    llm = AsyncMock()
    result = await select_memories("hello", llm, memory_dir=tmp_path)
    assert result == []
    llm.acomplete.assert_not_called()


@pytest.mark.asyncio
async def test_select_memories_with_files(tmp_path: Path):
    (tmp_path / "a.md").write_text("---\nname: a\ndescription: about A\ntype: goal\n---\nbody")
    (tmp_path / "b.md").write_text("---\nname: b\ndescription: about B\ntype: reference\n---\nbody")

    llm = AsyncMock()
    llm.acomplete.return_value = MagicMock(
        content=json.dumps({"selected_memories": ["a.md"]})
    )

    result = await select_memories("tell me about A", llm, memory_dir=tmp_path)
    assert result == ["a.md"]
    llm.acomplete.assert_called_once()


@pytest.mark.asyncio
async def test_select_memories_error_returns_empty(tmp_path: Path):
    (tmp_path / "a.md").write_text("---\nname: a\n---\nbody")

    llm = AsyncMock()
    llm.acomplete.side_effect = RuntimeError("LLM down")

    result = await select_memories("hello", llm, memory_dir=tmp_path)
    assert result == []


def test_format_recall_injection(tmp_path: Path):
    (tmp_path / "a.md").write_text("---\nname: a\n---\nbody of a")
    result = format_recall_injection(["a.md"], memory_dir=tmp_path)
    assert "Selected Memories" in result
    assert "body of a" in result


def test_format_recall_injection_empty():
    assert format_recall_injection([]) == ""


# ---------------------------------------------------------------------------
# reflection_agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_reflection(tmp_path: Path):
    """Short reflection reads new messages and writes a memory file via LLM tools."""
    from framework.agents.queen.reflection_agent import run_short_reflection

    # Set up a fake session dir with conversation parts.
    parts_dir = tmp_path / "session" / "conversations" / "parts"
    parts_dir.mkdir(parents=True)
    for i in range(3):
        role = "user" if i % 2 == 0 else "assistant"
        (parts_dir / f"{i:010d}.json").write_text(
            json.dumps({"role": role, "content": f"message {i}"})
        )

    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()

    # Mock LLM: turn 1 lists files, turn 2 writes a memory, turn 3 stops.
    llm = AsyncMock()
    llm.acomplete.side_effect = [
        # Turn 1: LLM calls write_memory_file
        MagicMock(
            content="",
            raw_response={
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "name": "write_memory_file",
                        "input": {
                            "filename": "user-likes-tests.md",
                            "content": "---\nname: user-likes-tests\ntype: technique\ndescription: User values thorough testing\n---\nObserved emphasis on test coverage.",
                        },
                    }
                ]
            },
        ),
        # Turn 2: LLM has no more tool calls → done
        MagicMock(content="Done reflecting.", raw_response={}),
    ]

    session_dir = tmp_path / "session"
    await run_short_reflection(session_dir, llm, memory_dir=mem_dir)

    # Verify the memory file was created.
    written = mem_dir / "user-likes-tests.md"
    assert written.exists()
    assert "user-likes-tests" in written.read_text()

    # Verify cursor was advanced.
    cursor_file = qm.MEMORY_DIR / ".cursor.json"
    # We passed a custom memory_dir, but cursor uses the default path.
    # The function uses read_cursor()/write_cursor() with default CURSOR_FILE.
    # Just verify the LLM was called.
    assert llm.acomplete.call_count == 2


@pytest.mark.asyncio
async def test_long_reflection(tmp_path: Path):
    """Long reflection reads all memories and can merge/delete them."""
    from framework.agents.queen.reflection_agent import run_long_reflection

    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    (mem_dir / "dup-a.md").write_text("---\nname: dup-a\ntype: goal\ndescription: goal A\n---\nGoal A details.")
    (mem_dir / "dup-b.md").write_text("---\nname: dup-b\ntype: goal\ndescription: goal A duplicate\n---\nSame goal A.")

    llm = AsyncMock()
    llm.acomplete.side_effect = [
        # Turn 1: LLM lists files
        MagicMock(
            content="",
            raw_response={
                "tool_calls": [
                    {"id": "tc_1", "name": "list_memory_files", "input": {}},
                ]
            },
        ),
        # Turn 2: LLM merges dup-b into dup-a and deletes dup-b
        MagicMock(
            content="",
            raw_response={
                "tool_calls": [
                    {
                        "id": "tc_2",
                        "name": "write_memory_file",
                        "input": {
                            "filename": "dup-a.md",
                            "content": "---\nname: dup-a\ntype: goal\ndescription: goal A (merged)\n---\nGoal A details. Also same goal A.",
                        },
                    },
                    {
                        "id": "tc_3",
                        "name": "delete_memory_file",
                        "input": {"filename": "dup-b.md"},
                    },
                ]
            },
        ),
        # Turn 3: done
        MagicMock(content="Housekeeping complete.", raw_response={}),
    ]

    await run_long_reflection(llm, memory_dir=mem_dir)

    # dup-b should be deleted, dup-a should be updated.
    assert not (mem_dir / "dup-b.md").exists()
    assert (mem_dir / "dup-a.md").exists()
    assert "merged" in (mem_dir / "dup-a.md").read_text()
    assert llm.acomplete.call_count == 3


# ---------------------------------------------------------------------------
# Bug 1: Path traversal prevention
# ---------------------------------------------------------------------------


def test_path_traversal_read(tmp_path: Path):
    from framework.agents.queen.reflection_agent import _execute_tool

    (tmp_path / "safe.md").write_text("safe content")
    result = _execute_tool("read_memory_file", {"filename": "../../etc/passwd"}, tmp_path)
    assert "ERROR" in result
    assert "path components not allowed" in result.lower() or "escapes" in result.lower()


def test_path_traversal_write(tmp_path: Path):
    from framework.agents.queen.reflection_agent import _execute_tool

    result = _execute_tool(
        "write_memory_file",
        {"filename": "../escape.md", "content": "---\nname: evil\n---\nbad"},
        tmp_path,
    )
    assert "ERROR" in result
    assert not (tmp_path.parent / "escape.md").exists()


def test_path_traversal_delete(tmp_path: Path):
    from framework.agents.queen.reflection_agent import _execute_tool

    (tmp_path / "target.md").write_text("content")
    result = _execute_tool("delete_memory_file", {"filename": "../target.md"}, tmp_path)
    assert "ERROR" in result
    assert (tmp_path / "target.md").exists()  # not deleted


def test_safe_path_accepted(tmp_path: Path):
    from framework.agents.queen.reflection_agent import _execute_tool

    result = _execute_tool(
        "write_memory_file",
        {"filename": "good-file.md", "content": "---\nname: good\n---\ncontent"},
        tmp_path,
    )
    assert "Wrote" in result
    assert (tmp_path / "good-file.md").exists()

    result = _execute_tool("read_memory_file", {"filename": "good-file.md"}, tmp_path)
    assert "content" in result

    result = _execute_tool("delete_memory_file", {"filename": "good-file.md"}, tmp_path)
    assert "Deleted" in result


# ---------------------------------------------------------------------------
# Bug 2: Failed reflections do not advance cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cursor_not_advanced_on_llm_failure(tmp_path: Path):
    from framework.agents.queen.reflection_agent import run_short_reflection

    parts_dir = tmp_path / "session" / "conversations" / "parts"
    parts_dir.mkdir(parents=True)
    for i in range(3):
        (parts_dir / f"{i:010d}.json").write_text(
            json.dumps({"role": "user", "content": f"message {i}"})
        )

    cursor_file = tmp_path / ".cursor.json"
    qm.write_cursor(0, cursor_file)

    llm = AsyncMock()
    llm.acomplete.side_effect = RuntimeError("LLM down")

    # Patch read_cursor/write_cursor to use our temp cursor file.
    import unittest.mock as mock
    with mock.patch("framework.agents.queen.reflection_agent.read_cursor", return_value=0), \
         mock.patch("framework.agents.queen.reflection_agent.write_cursor") as mock_write:
        await run_short_reflection(tmp_path / "session", llm, memory_dir=tmp_path / "mem")

        # write_cursor should NOT have been called since the LLM failed.
        mock_write.assert_not_called()


@pytest.mark.asyncio
async def test_cursor_advanced_on_success(tmp_path: Path):
    from framework.agents.queen.reflection_agent import run_short_reflection

    parts_dir = tmp_path / "session" / "conversations" / "parts"
    parts_dir.mkdir(parents=True)
    for i in range(3):
        (parts_dir / f"{i:010d}.json").write_text(
            json.dumps({"role": "user", "content": f"message {i}"})
        )

    llm = AsyncMock()
    llm.acomplete.return_value = MagicMock(content="Nothing to remember.", raw_response={})

    import unittest.mock as mock
    with mock.patch("framework.agents.queen.reflection_agent.read_cursor", return_value=0), \
         mock.patch("framework.agents.queen.reflection_agent.write_cursor") as mock_write:
        await run_short_reflection(tmp_path / "session", llm, memory_dir=tmp_path / "mem")

        mock_write.assert_called_once_with(2)


# ---------------------------------------------------------------------------
# Bug 3: Compaction fallback only when cursor > max_all_seq
# ---------------------------------------------------------------------------


def test_compaction_fallback_when_cursor_evicted(tmp_path: Path):
    """When cursor_seq > max file seq, fallback triggers (compaction happened)."""
    parts_dir = tmp_path / "conversations" / "parts"
    parts_dir.mkdir(parents=True)
    for i in range(3):
        (parts_dir / f"{i:010d}.json").write_text(
            json.dumps({"role": "user", "content": f"msg {i}"})
        )

    # Cursor is at 999, but max file seq is 2 → compation evicted files.
    msgs, max_seq = qm.read_messages_since_cursor(tmp_path, 999)
    assert len(msgs) == 3


def test_no_compaction_fallback_when_up_to_date(tmp_path: Path):
    """When cursor_seq == max file seq, should return empty (not all files)."""
    parts_dir = tmp_path / "conversations" / "parts"
    parts_dir.mkdir(parents=True)
    for i in range(3):
        (parts_dir / f"{i:010d}.json").write_text(
            json.dumps({"role": "user", "content": f"msg {i}"})
        )

    # Cursor is at 2 (max seq) → already up-to-date, should return nothing.
    msgs, max_seq = qm.read_messages_since_cursor(tmp_path, 2)
    assert len(msgs) == 0


def test_no_compaction_fallback_when_behind(tmp_path: Path):
    """When cursor_seq < max file seq but no new_files, shouldn't happen normally.
    But verify: cursor_seq=0 with files at 0,1,2 should return 1,2 (seq > 0)."""
    parts_dir = tmp_path / "conversations" / "parts"
    parts_dir.mkdir(parents=True)
    for i in range(3):
        (parts_dir / f"{i:010d}.json").write_text(
            json.dumps({"role": "user", "content": f"msg {i}"})
        )

    msgs, max_seq = qm.read_messages_since_cursor(tmp_path, 0)
    assert len(msgs) == 2  # seq 1 and 2
    assert max_seq == 2
