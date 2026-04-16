"""Tests for aden_tools.file_state_cache and its integration with file_ops.

These tests cover the stale-edit guard added for Gap 4:
- read_file records a per-file hash snapshot
- edit_file / write_file / hashline_edit refuse to run when the on-disk
  file has diverged from the last recorded read
- write_file is allowed without a prior read when the target doesn't
  exist yet (brand-new file, nothing to clobber)
- re-recording after a successful write keeps chained edits working
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastmcp import FastMCP

from aden_tools import file_state_cache
from aden_tools.file_ops import register_file_tools


def _find_tool(mcp: FastMCP, name: str):
    """Pull a tool function out of an MCP registration for direct testing."""
    # fastmcp stores tools in a ToolManager. We reach through it to grab
    # the underlying callable so tests can invoke tools directly without
    # a full MCP round-trip.
    manager = getattr(mcp, "_tool_manager", None) or getattr(mcp, "tool_manager", None)
    assert manager is not None, "could not locate fastmcp tool manager"
    tools = getattr(manager, "_tools", None) or getattr(manager, "tools", None)
    assert tools is not None, "could not locate fastmcp tools dict"
    tool = tools[name]
    return getattr(tool, "fn", None) or getattr(tool, "func", None) or tool


@pytest.fixture
def sandbox(tmp_path: Path):
    """A sandbox directory the tools are allowed to read/write within."""
    file_state_cache.reset_all()
    return tmp_path


@pytest.fixture
def tools(sandbox: Path):
    """Register file_ops onto a fresh FastMCP and return the tool callables."""
    mcp = FastMCP("test-server")

    def resolve(path: str) -> str:
        # Absolute paths under the sandbox are fine; relative paths
        # resolve against the sandbox root.
        if os.path.isabs(path):
            return os.path.abspath(path)
        return str(sandbox / path)

    register_file_tools(mcp, resolve_path=resolve)

    return {
        "read_file": _find_tool(mcp, "read_file"),
        "write_file": _find_tool(mcp, "write_file"),
        "edit_file": _find_tool(mcp, "edit_file"),
        "hashline_edit": _find_tool(mcp, "hashline_edit"),
    }


# ---------------------------------------------------------------------------
# Cache primitives
# ---------------------------------------------------------------------------


def test_check_fresh_returns_unread_when_never_recorded(sandbox: Path):
    target = sandbox / "nope.txt"
    target.write_text("hi")
    result = file_state_cache.check_fresh(None, str(target))
    assert result.status is file_state_cache.Freshness.UNREAD


def test_record_then_check_returns_fresh(sandbox: Path):
    target = sandbox / "a.txt"
    target.write_text("one")
    file_state_cache.record_read(None, str(target), content_bytes=b"one")
    result = file_state_cache.check_fresh(None, str(target))
    assert result.status is file_state_cache.Freshness.FRESH


def test_external_write_makes_check_return_stale(sandbox: Path):
    target = sandbox / "b.txt"
    target.write_text("original")
    file_state_cache.record_read(None, str(target), content_bytes=b"original")

    # Simulate an external editor save with different content. Sleep
    # briefly to ensure mtime moves (some filesystems have 1s resolution
    # but most Linux fs have ns; this is belt-and-braces).
    time.sleep(0.01)
    target.write_text("hijacked by the user")
    os.utime(str(target), None)  # bump mtime in case the write was too fast

    result = file_state_cache.check_fresh(None, str(target))
    assert result.status is file_state_cache.Freshness.STALE
    assert "changed on disk" in result.detail or "differs" in result.detail


def test_identical_content_rewrite_stays_fresh(sandbox: Path):
    """Editors that rewrite a file without changing its bytes shouldn't
    be reported as stale even though mtime moved."""
    target = sandbox / "c.txt"
    target.write_text("same")
    file_state_cache.record_read(None, str(target), content_bytes=b"same")

    time.sleep(0.01)
    target.write_text("same")  # different mtime, same content
    os.utime(str(target), None)

    result = file_state_cache.check_fresh(None, str(target))
    assert result.status is file_state_cache.Freshness.FRESH


def test_agent_scopes_are_isolated(sandbox: Path):
    target = sandbox / "d.txt"
    target.write_text("xyz")
    file_state_cache.record_read("agent-A", str(target), content_bytes=b"xyz")

    # Another agent hasn't read this file yet.
    result = file_state_cache.check_fresh("agent-B", str(target))
    assert result.status is file_state_cache.Freshness.UNREAD


# ---------------------------------------------------------------------------
# file_ops integration
# ---------------------------------------------------------------------------


def test_edit_file_refuses_without_prior_read(sandbox: Path, tools):
    target = sandbox / "e.py"
    target.write_text("print('hello')\n")
    # Clear the cache first so there's definitely no recorded read.
    file_state_cache.reset_all()

    result = tools["edit_file"]("e.py", "hello", "world")
    assert "Refusing to edit" in result
    assert "read_file" in result


def test_edit_file_proceeds_after_read(sandbox: Path, tools):
    target = sandbox / "f.py"
    target.write_text("print('hello')\n")
    file_state_cache.reset_all()

    tools["read_file"]("f.py")
    result = tools["edit_file"]("f.py", "hello", "world")
    assert "Replaced" in result
    assert target.read_text() == "print('world')\n"


def test_edit_file_refuses_when_file_changed_between_read_and_edit(sandbox: Path, tools):
    target = sandbox / "g.py"
    target.write_text("print('hello')\n")
    file_state_cache.reset_all()

    tools["read_file"]("g.py")

    # Simulate the user editing the file outside the agent.
    time.sleep(0.01)
    target.write_text("print('bye')\n")
    os.utime(str(target), None)

    result = tools["edit_file"]("g.py", "hello", "world")
    assert "Refusing to edit" in result
    assert "Re-read" in result


def test_write_file_allowed_for_new_file_without_prior_read(sandbox: Path, tools):
    file_state_cache.reset_all()
    result = tools["write_file"]("brand_new.txt", "first contents\n")
    assert "Created" in result
    assert (sandbox / "brand_new.txt").read_text() == "first contents\n"


def test_write_file_refuses_overwrite_without_prior_read(sandbox: Path, tools):
    target = sandbox / "existing.txt"
    target.write_text("do not clobber\n")
    file_state_cache.reset_all()

    result = tools["write_file"]("existing.txt", "clobbered\n")
    assert "Refusing to overwrite" in result
    assert target.read_text() == "do not clobber\n"  # unchanged


def test_chained_edits_in_same_turn_do_not_self_invalidate(sandbox: Path, tools):
    target = sandbox / "chained.py"
    target.write_text("print('a')\nprint('b')\n")
    file_state_cache.reset_all()

    tools["read_file"]("chained.py")
    r1 = tools["edit_file"]("chained.py", "a", "A")
    assert "Replaced" in r1
    # Immediate second edit must NOT trip the stale guard because
    # edit_file re-records the post-write state.
    r2 = tools["edit_file"]("chained.py", "b", "B")
    assert "Replaced" in r2
    assert target.read_text() == "print('A')\nprint('B')\n"
