"""Tests for the queen memory v2 system (reflection + recall)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.agents.queen import queen_memory_v2 as qm
from framework.agents.queen.recall_selector import (
    format_recall_injection,
    select_memories,
)
from framework.agents.queen.reflection_agent import subscribe_worker_memory_triggers
from framework.graph.prompting import build_system_prompt_for_node_context
from framework.runtime.event_bus import AgentEvent, EventBus, EventType
from framework.tools.queen_lifecycle_tools import QueenPhaseState

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
    assert qm.parse_memory_type("profile") == "profile"
    assert qm.parse_memory_type("feedback") == "feedback"


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
# read_conversation_parts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_conversation_parts(tmp_path: Path):
    parts_dir = tmp_path / "conversations" / "parts"
    parts_dir.mkdir(parents=True)
    for i in range(5):
        (parts_dir / f"{i:010d}.json").write_text(
            json.dumps({"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"})
        )

    msgs = await qm.read_conversation_parts(tmp_path)
    assert len(msgs) == 5
    assert msgs[0]["content"] == "msg 0"
    assert msgs[4]["content"] == "msg 4"


@pytest.mark.asyncio
async def test_read_conversation_parts_empty(tmp_path: Path):
    msgs = await qm.read_conversation_parts(tmp_path)
    assert msgs == []


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
    llm.acomplete.return_value = MagicMock(content=json.dumps({"selected_memories": ["a.md"]}))

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


def test_format_recall_injection_custom_heading(tmp_path: Path):
    (tmp_path / "a.md").write_text("---\nname: a\n---\nbody of a")
    result = format_recall_injection(["a.md"], memory_dir=tmp_path, heading="Colony Memories")
    assert "Colony Memories" in result


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
                            "content": (
                                "---\nname: user-likes-tests\n"
                                "type: technique\n"
                                "description: User values thorough testing\n"
                                "---\nObserved emphasis on test coverage."
                            ),
                        },
                    }
                ]
            },
        ),
        # Turn 2: LLM has no more tool calls → done
        MagicMock(content="Done reflecting.", raw_response={}),
    ]

    session_dir = tmp_path / "session"
    await run_short_reflection(
        session_dir,
        llm,
        memory_dir=mem_dir,
        caller="queen",
    )

    # Verify the memory file was created.
    written = mem_dir / "user-likes-tests.md"
    assert written.exists()
    assert "user-likes-tests" in written.read_text()
    assert llm.acomplete.call_count == 2


@pytest.mark.asyncio
async def test_long_reflection(tmp_path: Path):
    """Long reflection reads all memories and can merge/delete them."""
    from framework.agents.queen.reflection_agent import run_long_reflection

    mem_dir = tmp_path / "memories"
    mem_dir.mkdir()
    (mem_dir / "dup-a.md").write_text(
        "---\nname: dup-a\ntype: goal\ndescription: goal A\n---\nGoal A details."
    )
    (mem_dir / "dup-b.md").write_text(
        "---\nname: dup-b\ntype: goal\ndescription: goal A duplicate\n---\nSame goal A."
    )

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
                            "content": (
                                "---\nname: dup-a\ntype: goal\n"
                                "description: goal A (merged)\n"
                                "---\nGoal A details."
                                " Also same goal A."
                            ),
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

    await run_long_reflection(llm, memory_dir=mem_dir, caller="queen")

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
    result = _execute_tool(
        "read_memory_file", {"filename": "../../etc/passwd"}, tmp_path, caller="queen"
    )
    assert "ERROR" in result
    assert "path components not allowed" in result.lower() or "escapes" in result.lower()


def test_path_traversal_write(tmp_path: Path):
    from framework.agents.queen.reflection_agent import _execute_tool

    result = _execute_tool(
        "write_memory_file",
        {"filename": "../escape.md", "content": "---\nname: evil\n---\nbad"},
        tmp_path,
        caller="queen",
    )
    assert "ERROR" in result
    assert not (tmp_path.parent / "escape.md").exists()


def test_path_traversal_delete(tmp_path: Path):
    from framework.agents.queen.reflection_agent import _execute_tool

    (tmp_path / "target.md").write_text("content")
    result = _execute_tool(
        "delete_memory_file", {"filename": "../target.md"}, tmp_path, caller="queen"
    )
    assert "ERROR" in result
    assert (tmp_path / "target.md").exists()  # not deleted


def test_safe_path_accepted(tmp_path: Path):
    from framework.agents.queen.reflection_agent import _execute_tool

    result = _execute_tool(
        "write_memory_file",
        {"filename": "good-file.md", "content": "---\nname: good\n---\ncontent"},
        tmp_path,
        caller="queen",
    )
    assert "Wrote" in result
    assert (tmp_path / "good-file.md").exists()

    result = _execute_tool(
        "read_memory_file", {"filename": "good-file.md"}, tmp_path, caller="queen"
    )
    assert "content" in result

    result = _execute_tool(
        "delete_memory_file", {"filename": "good-file.md"}, tmp_path, caller="queen"
    )
    assert "Deleted" in result


def test_init_memory_dir_migrates_shared_memories_into_colony(tmp_path: Path):
    source = tmp_path / "legacy-shared"
    source.mkdir()
    (source / "shared-memory.md").write_text(
        "---\nname: shared\ndescription: old shared memory\ntype: goal\n---\nbody",
        encoding="utf-8",
    )
    target = tmp_path / "colony"

    qm.migrate_shared_v2_memories(target, source_dir=source)

    assert (target / "shared-memory.md").exists()
    assert not (source / "shared-memory.md").exists()
    assert (target / ".migrated-from-shared-memory").exists()


def test_shared_memory_migration_marker_prevents_repeat(tmp_path: Path):
    source = tmp_path / "legacy-shared"
    source.mkdir()
    target = tmp_path / "colony"
    target.mkdir()
    (target / ".migrated-from-shared-memory").write_text("done\n", encoding="utf-8")
    (source / "shared-memory.md").write_text("body", encoding="utf-8")

    qm.migrate_shared_v2_memories(target, source_dir=source)

    assert not (target / "shared-memory.md").exists()
    assert (source / "shared-memory.md").exists()


def test_global_memory_is_not_populated_by_colony_migration(tmp_path: Path):
    source = tmp_path / "legacy-shared"
    source.mkdir()
    (source / "shared-memory.md").write_text("body", encoding="utf-8")
    colony = tmp_path / "colony"
    global_dir = tmp_path / "global"

    qm.migrate_shared_v2_memories(colony, source_dir=source)
    qm.init_memory_dir(global_dir)

    assert list(global_dir.glob("*.md")) == []


def test_save_global_memory_rejects_runtime_details(tmp_path: Path):
    with pytest.raises(ValueError):
        qm.save_global_memory(
            category="profile",
            description="codebase preference",
            content="The user wants the worker graph to use node retries.",
            memory_dir=tmp_path,
        )


def test_save_global_memory_persists_frontmatter(tmp_path: Path):
    filename, path = qm.save_global_memory(
        category="preference",
        description="Prefers concise updates",
        content="The user prefers concise, direct status updates.",
        memory_dir=tmp_path,
    )

    assert filename.endswith(".md")
    text = path.read_text(encoding="utf-8")
    assert "type: preference" in text
    assert "Prefers concise updates" in text


def test_build_system_prompt_injects_dynamic_memory():
    ctx = SimpleNamespace(
        identity_prompt="Identity",
        node_spec=SimpleNamespace(
            system_prompt="Focus", node_type="event_loop", output_keys=["out"]
        ),
        narrative="Narrative",
        accounts_prompt="",
        skills_catalog_prompt="",
        protocols_prompt="",
        memory_prompt="",
        dynamic_memory_provider=lambda: "--- Colony Memories ---\nremember this",
        is_subagent_mode=False,
    )

    prompt = build_system_prompt_for_node_context(ctx)
    assert "Colony Memories" in prompt
    assert "remember this" in prompt


def test_queen_phase_state_appends_colony_and_global_memory_blocks():
    phase = QueenPhaseState(
        prompt_building="base prompt",
        _cached_colony_recall_block="--- Colony Memories ---\ncolony",
        _cached_global_recall_block="--- Global Memories ---\nglobal",
    )

    prompt = phase.get_current_prompt()
    assert "base prompt" in prompt
    assert "Colony Memories" in prompt
    assert "Global Memories" in prompt


@pytest.mark.asyncio
async def test_worker_colony_reflection_at_handoff(tmp_path: Path):
    """Colony reflection runs via WorkerAgent._reflect_colony_memory at node handoff."""
    import asyncio

    from framework.graph.context import GraphContext
    from framework.graph.worker_agent import WorkerAgent

    worker_sessions_dir = tmp_path / "worker-sessions"
    execution_id = "exec-1"
    session_dir = worker_sessions_dir / execution_id / "conversations" / "parts"
    session_dir.mkdir(parents=True)
    (session_dir / "0000000000.json").write_text(
        json.dumps({"role": "user", "content": "Please remember I like terse summaries."}),
        encoding="utf-8",
    )
    (session_dir / "0000000001.json").write_text(
        json.dumps({"role": "assistant", "content": "I'll keep that in mind."}),
        encoding="utf-8",
    )

    colony_dir = tmp_path / "colony"
    colony_dir.mkdir()
    recall_cache: dict[str, str] = {execution_id: ""}

    reflect_llm = AsyncMock()
    reflect_llm.acomplete.side_effect = [
        # Short reflection: write a memory file
        MagicMock(
            content="",
            raw_response={
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "name": "write_memory_file",
                        "input": {
                            "filename": "user-prefers-terse-summaries.md",
                            "content": (
                                "---\n"
                                "name: user-prefers-terse-summaries\n"
                                "description: Prefers terse summaries\n"
                                "type: preference\n"
                                "---\n\n"
                                "The user prefers terse summaries."
                            ),
                        },
                    }
                ]
            },
        ),
        # Short reflection done
        MagicMock(content="done", raw_response={}),
        # Recall selector picks the new memory
        MagicMock(content=json.dumps({"selected_memories": ["user-prefers-terse-summaries.md"]})),
    ]

    # Build a minimal GraphContext with colony memory fields
    gc = MagicMock(spec=GraphContext)
    gc.colony_memory_dir = colony_dir
    gc.worker_sessions_dir = worker_sessions_dir
    gc.colony_recall_cache = recall_cache
    gc.colony_reflect_llm = reflect_llm
    gc.execution_id = execution_id
    gc._colony_reflect_lock = asyncio.Lock()

    node_spec = SimpleNamespace(id="test-node")
    worker = WorkerAgent.__new__(WorkerAgent)
    worker._gc = gc
    worker.node_spec = node_spec

    await worker._reflect_colony_memory()

    assert (colony_dir / "user-prefers-terse-summaries.md").exists()
    assert "Colony Memories" in recall_cache[execution_id]
    assert "terse summaries" in recall_cache[execution_id]


@pytest.mark.asyncio
async def test_subscribe_worker_triggers_only_lifecycle_events(tmp_path: Path):
    """After simplification, worker triggers only subscribe to start and terminal events."""
    colony_dir = tmp_path / "colony"
    colony_dir.mkdir()
    recall_cache: dict[str, str] = {}
    bus = EventBus()
    llm = AsyncMock()

    subs = await subscribe_worker_memory_triggers(
        bus,
        llm,
        worker_sessions_dir=tmp_path / "sessions",
        colony_memory_dir=colony_dir,
        recall_cache=recall_cache,
    )
    try:
        # Should have exactly 2 subscriptions (start + terminal)
        assert len(subs) == 2

        # EXECUTION_STARTED initialises cache
        await bus.publish(
            AgentEvent(
                type=EventType.EXECUTION_STARTED,
                stream_id="default",
                execution_id="exec-1",
            )
        )
        assert recall_cache.get("exec-1") == ""
    finally:
        for sub_id in subs:
            bus.unsubscribe(sub_id)
