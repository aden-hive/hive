"""Tests for AS-9: Skill directory allowlisting in file-read tool interception."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.llm.provider import ToolResult


def _make_tool_call_event(tool_name: str, path: str):
    """Build a minimal ToolCallEvent-like object."""
    tc = MagicMock()
    tc.tool_use_id = "tc-1"
    tc.tool_name = tool_name
    tc.tool_input = {"path": path}
    return tc


def _make_node(skill_dirs: list[str]):
    """Build a minimal EventLoopNode with skill_dirs set."""
    from framework.graph.event_loop_node import EventLoopNode

    node = EventLoopNode(
        tool_executor=MagicMock(return_value=ToolResult(tool_use_id="tc-1", content="from-executor"))
    )
    node._skill_dirs = skill_dirs
    return node


class TestSkillFileReadInterception:
    @pytest.mark.asyncio
    async def test_reads_file_in_skill_dir(self, tmp_path):
        """File under a skill dir is read directly, bypassing the executor."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        script = skill_dir / "scripts" / "run.py"
        script.parent.mkdir()
        script.write_text("print('hello')")

        node = _make_node([str(skill_dir)])
        tc = _make_tool_call_event("view_file", str(script))

        result = await node._execute_tool(tc)

        assert result.content == "print('hello')"
        assert not result.is_error
        node._tool_executor.assert_not_called()

    @pytest.mark.asyncio
    async def test_skill_md_read_marked_as_skill_content(self, tmp_path):
        """Reading SKILL.md sets is_skill_content=True for AS-10 protection."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nname: my-skill\ndescription: Test\n---\nInstructions.")

        node = _make_node([str(skill_dir)])
        tc = _make_tool_call_event("view_file", str(skill_md))

        result = await node._execute_tool(tc)

        assert result.is_skill_content is True
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_non_skill_md_resource_not_marked(self, tmp_path):
        """Bundled resource (not SKILL.md) is NOT marked as skill_content."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        ref = skill_dir / "references" / "api.md"
        ref.parent.mkdir()
        ref.write_text("# API Reference")

        node = _make_node([str(skill_dir)])
        tc = _make_tool_call_event("load_data", str(ref))

        result = await node._execute_tool(tc)

        assert result.is_skill_content is False
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_path_outside_skill_dir_goes_to_executor(self, tmp_path):
        """Path outside skill dirs is passed through to the executor unchanged."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        other_file = tmp_path / "other" / "file.txt"
        other_file.parent.mkdir()
        other_file.write_text("other content")

        node = _make_node([str(skill_dir)])
        tc = _make_tool_call_event("view_file", str(other_file))

        result = await node._execute_tool(tc)

        assert result.content == "from-executor"
        node._tool_executor.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_skill_dirs_goes_to_executor(self, tmp_path):
        """When skill_dirs is empty, all tool calls go to executor."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        script = skill_dir / "scripts" / "run.py"
        script.parent.mkdir()
        script.write_text("print('hello')")

        node = _make_node([])
        tc = _make_tool_call_event("view_file", str(script))

        result = await node._execute_tool(tc)

        assert result.content == "from-executor"
        node._tool_executor.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_file_returns_error(self, tmp_path):
        """Non-existent file under skill dir returns is_error=True."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        missing = skill_dir / "scripts" / "missing.py"

        node = _make_node([str(skill_dir)])
        tc = _make_tool_call_event("view_file", str(missing))

        result = await node._execute_tool(tc)

        assert result.is_error is True
        assert "Could not read skill resource" in result.content

    @pytest.mark.asyncio
    async def test_non_file_read_tool_goes_to_executor(self, tmp_path):
        """Non file-read tools (e.g. web_search) bypass the interceptor."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()

        node = _make_node([str(skill_dir)])
        tc = _make_tool_call_event("web_search", str(skill_dir / "SKILL.md"))

        result = await node._execute_tool(tc)

        assert result.content == "from-executor"
        node._tool_executor.assert_called_once()
