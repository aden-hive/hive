"""shell_rg + shell_find — basic functionality, structured output."""

from __future__ import annotations

import shutil

import pytest


@pytest.fixture
def search_tools(mcp):
    from shell_tools.search.tools import register_search_tools

    register_search_tools(mcp)
    return {
        "rg": mcp._tool_manager._tools["shell_rg"].fn,
        "find": mcp._tool_manager._tools["shell_find"].fn,
    }


@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not installed")
def test_rg_finds_pattern(search_tools, tmp_path):
    (tmp_path / "a.txt").write_text("hello\nworld\nfoo\n")
    (tmp_path / "b.txt").write_text("bar\nworld\n")

    result = search_tools["rg"](pattern="world", path=str(tmp_path))
    assert result["total"] >= 2
    paths = {m["path"] for m in result["matches"]}
    assert any("a.txt" in p for p in paths)


@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not installed")
def test_rg_no_matches(search_tools, tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    result = search_tools["rg"](pattern="zzz_no_match_zzz", path=str(tmp_path))
    assert result["total"] == 0
    assert result["matches"] == []


def test_find_by_name(search_tools, tmp_path):
    (tmp_path / "alpha.log").write_text("a")
    (tmp_path / "beta.log").write_text("b")
    (tmp_path / "ignore.txt").write_text("c")

    result = search_tools["find"](path=str(tmp_path), name="*.log")
    assert result["count"] == 2
    assert all(p.endswith(".log") for p in result["paths"])


def test_find_by_type_dir(search_tools, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "file.txt").write_text("x")

    result = search_tools["find"](path=str(tmp_path), type_filter="d")
    paths = result["paths"]
    # tmp_path itself + sub
    assert any(p.endswith("sub") for p in paths)
    assert not any(p.endswith("file.txt") for p in paths)
