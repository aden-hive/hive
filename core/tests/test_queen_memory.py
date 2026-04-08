"""Tests for the queen global memory system (reflection + recall)."""

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
from framework.graph.prompting import build_system_prompt_for_node_context
from framework.tools.queen_lifecycle_tools import QueenPhaseState


def _make_litellm_response(tool_calls: list[dict] | None = None, content: str = ""):
    """Build a mock that mirrors litellm ModelResponse structure."""
    if tool_calls:
        tc_objects = []
        for tc in tool_calls:
            fn = SimpleNamespace(
                name=tc["name"],
                arguments=json.dumps(tc.get("input", {})),
            )
            tc_objects.append(SimpleNamespace(id=tc["id"], function=fn))
        message = SimpleNamespace(tool_calls=tc_objects)
    else:
        message = SimpleNamespace(tool_calls=None)
    raw = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    return MagicMock(content=content, raw_response=raw)

# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


def test_parse_frontmatter_valid():
    text = "---\nname: foo\ntype: profile\ndescription: bar baz\n---\ncontent"
    fm = qm.parse_frontmatter(text)
    assert fm == {"name": "foo", "type": "profile", "description": "bar baz"}


def test_parse_frontmatter_missing():
    assert qm.parse_frontmatter("no frontmatter here") == {}


def test_parse_frontmatter_empty():
    assert qm.parse_frontmatter("") == {}


def test_parse_frontmatter_broken_yaml():
    text = "---\n: bad\nno colon\n---\n"
    fm = qm.parse_frontmatter(text)
    assert fm == {}


# ---------------------------------------------------------------------------
# parse_global_memory_category
# ---------------------------------------------------------------------------


def test_parse_global_memory_category_valid():
    assert qm.parse_global_memory_category("profile") == "profile"
    assert qm.parse_global_memory_category("preference") == "preference"
    assert qm.parse_global_memory_category("environment") == "environment"
    assert qm.parse_global_memory_category("feedback") == "feedback"


def test_parse_global_memory_category_case_insensitive():
    assert qm.parse_global_memory_category("Profile") == "profile"
    assert qm.parse_global_memory_category("  FEEDBACK  ") == "feedback"


def test_parse_global_memory_category_invalid():
    assert qm.parse_global_memory_category("goal") is None
    assert qm.parse_global_memory_category("unknown") is None
    assert qm.parse_global_memory_category(None) is None


# ---------------------------------------------------------------------------
# MemoryFile.from_path
# ---------------------------------------------------------------------------


def test_memory_file_from_path(tmp_path: Path):
    f = tmp_path / "test.md"
    f.write_text("---\nname: test\ntype: profile\ndescription: a test\n---\nbody\n")
    mf = qm.MemoryFile.from_path(f)
    assert mf.filename == "test.md"
    assert mf.name == "test"
    assert mf.type == "profile"
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
            type="profile",
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
    assert "[profile] a.md" in manifest
    assert "desc a" in manifest
    assert "[unknown] b.md" in manifest
    assert "(no description)" in manifest


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
    (tmp_path / "a.md").write_text("---\nname: a\ndescription: about A\ntype: profile\n---\nbody")
    (tmp_path / "b.md").write_text(
        "---\nname: b\ndescription: about B\ntype: preference\n---\nbody"
    )

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
    assert "Global Memories" in result
    assert "body of a" in result


def test_format_recall_injection_empty():
    assert format_recall_injection([]) == ""


# ---------------------------------------------------------------------------
# reflection_agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_reflection(tmp_path: Path):
    """Short reflection reads messages and writes a global memory file via LLM tools."""
    from framework.agents.queen.reflection_agent import run_short_reflection

    parts_dir = tmp_path / "session" / "conversations" / "parts"
    parts_dir.mkdir(parents=True)
    for i in range(3):
        role = "user" if i % 2 == 0 else "assistant"
        (parts_dir / f"{i:010d}.json").write_text(
            json.dumps({"role": role, "content": f"message {i}"})
        )

    mem_dir = tmp_path / "global_memory"
    mem_dir.mkdir()

    llm = AsyncMock()
    llm.acomplete.side_effect = [
        # Turn 1: LLM writes a global memory file
        _make_litellm_response(tool_calls=[
            {
                "id": "tc_1",
                "name": "write_memory_file",
                "input": {
                    "filename": "user-likes-tests.md",
                    "content": (
                        "---\nname: user-likes-tests\n"
                        "type: preference\n"
                        "description: User values thorough testing\n"
                        "---\nObserved emphasis on test coverage."
                    ),
                },
            }
        ]),
        # Turn 2: done
        _make_litellm_response(content="Done reflecting."),
    ]

    session_dir = tmp_path / "session"
    await run_short_reflection(session_dir, llm, memory_dir=mem_dir)

    written = mem_dir / "user-likes-tests.md"
    assert written.exists()
    assert "user-likes-tests" in written.read_text()


@pytest.mark.asyncio
async def test_short_reflection_rejects_non_global_types(tmp_path: Path):
    """Reflection agent rejects memory types not in GLOBAL_MEMORY_CATEGORIES."""
    from framework.agents.queen.reflection_agent import _execute_tool

    mem_dir = tmp_path / "global_memory"
    mem_dir.mkdir()

    result = _execute_tool(
        "write_memory_file",
        {
            "filename": "bad-type.md",
            "content": "---\nname: bad\ntype: goal\n---\nbody",
        },
        mem_dir,
    )
    assert "ERROR" in result
    assert not (mem_dir / "bad-type.md").exists()


@pytest.mark.asyncio
async def test_long_reflection(tmp_path: Path):
    """Long reflection reads all memories and can merge/delete them."""
    from framework.agents.queen.reflection_agent import run_long_reflection

    mem_dir = tmp_path / "global_memory"
    mem_dir.mkdir()
    (mem_dir / "dup-a.md").write_text(
        "---\nname: dup-a\ntype: profile\ndescription: profile A\n---\nProfile A details."
    )
    (mem_dir / "dup-b.md").write_text(
        "---\nname: dup-b\ntype: profile\ndescription: profile A dup\n---\nSame profile A."
    )

    llm = AsyncMock()
    llm.acomplete.side_effect = [
        _make_litellm_response(tool_calls=[
            {"id": "tc_1", "name": "list_memory_files", "input": {}},
        ]),
        _make_litellm_response(tool_calls=[
            {
                "id": "tc_2",
                "name": "write_memory_file",
                "input": {
                    "filename": "dup-a.md",
                    "content": (
                        "---\nname: dup-a\ntype: profile\n"
                        "description: profile A (merged)\n"
                        "---\nProfile A details. Also same profile A."
                    ),
                },
            },
            {
                "id": "tc_3",
                "name": "delete_memory_file",
                "input": {"filename": "dup-b.md"},
            },
        ]),
        _make_litellm_response(content="Housekeeping complete."),
    ]

    await run_long_reflection(llm, memory_dir=mem_dir)

    assert not (mem_dir / "dup-b.md").exists()
    assert (mem_dir / "dup-a.md").exists()
    assert "merged" in (mem_dir / "dup-a.md").read_text()


# ---------------------------------------------------------------------------
# Path traversal prevention
# ---------------------------------------------------------------------------


def test_path_traversal_read(tmp_path: Path):
    from framework.agents.queen.reflection_agent import _execute_tool

    (tmp_path / "safe.md").write_text("safe content")
    result = _execute_tool("read_memory_file", {"filename": "../../etc/passwd"}, tmp_path)
    assert "ERROR" in result


def test_path_traversal_write(tmp_path: Path):
    from framework.agents.queen.reflection_agent import _execute_tool

    result = _execute_tool(
        "write_memory_file",
        {"filename": "../escape.md", "content": "---\nname: evil\n---\nbad"},
        tmp_path,
    )
    assert "ERROR" in result
    assert not (tmp_path.parent / "escape.md").exists()


def test_safe_path_accepted(tmp_path: Path):
    from framework.agents.queen.reflection_agent import _execute_tool

    result = _execute_tool(
        "write_memory_file",
        {"filename": "good-file.md", "content": "---\nname: good\ntype: profile\n---\ncontent"},
        tmp_path,
    )
    assert "Wrote" in result
    assert (tmp_path / "good-file.md").exists()

    result = _execute_tool("read_memory_file", {"filename": "good-file.md"}, tmp_path)
    assert "content" in result

    result = _execute_tool("delete_memory_file", {"filename": "good-file.md"}, tmp_path)
    assert "Deleted" in result


# ---------------------------------------------------------------------------
# system prompt integration
# ---------------------------------------------------------------------------


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
        dynamic_memory_provider=lambda: "--- Global Memories ---\nremember this",
        is_subagent_mode=False,
    )

    prompt = build_system_prompt_for_node_context(ctx)
    assert "Global Memories" in prompt
    assert "remember this" in prompt


def test_queen_phase_state_appends_global_memory_block():
    phase = QueenPhaseState(
        prompt_building="base prompt",
        _cached_global_recall_block="--- Global Memories ---\nglobal stuff",
    )

    prompt = phase.get_current_prompt()
    assert "base prompt" in prompt
    assert "Global Memories" in prompt
    assert "global stuff" in prompt


def test_queen_phase_state_prompt_without_memory():
    phase = QueenPhaseState(prompt_building="base prompt")

    prompt = phase.get_current_prompt()
    assert "base prompt" in prompt
    assert "Global Memories" not in prompt
