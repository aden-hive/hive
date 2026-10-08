"""terminal_rg + terminal_glob — basic functionality, structured output."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from terminal_tools.common.ripgrep import resolve_ripgrep


def test_stream_paths_drains_stderr_and_keeps_partial_results(monkeypatch):
    from terminal_tools.search import tools

    monkeypatch.setattr(tools, "_DEFAULT_TIMEOUT_SEC", 0.5)
    paths, truncated, timed_out, errors = tools._stream_paths(
        [sys.executable, "-c", "import sys,time; sys.stderr.write('x'*100000); sys.stderr.flush(); print('first.py',flush=True); time.sleep(30)"],
        10,
    )
    assert paths == ["first.py"]
    assert timed_out and not truncated
    assert errors == "x" * 2000


def test_stream_paths_stops_at_cap_and_handles_final_line():
    from terminal_tools.search.tools import _stream_paths

    paths, truncated, timed_out, _ = _stream_paths([sys.executable, "-c", "print('a.py\\nb.py\\nc.py',end='')"], 10)
    assert paths == ["a.py", "b.py", "c.py"]
    assert not truncated and not timed_out
    paths, truncated, timed_out, _ = _stream_paths([sys.executable, "-c", "print('a.py\\nb.py\\nc.py')"], 1)
    assert paths == ["a.py"]
    assert truncated and not timed_out


def test_stream_paths_filters_before_applying_result_cap():
    from terminal_tools.search.tools import _stream_paths

    paths, truncated, timed_out, _ = _stream_paths(
        [sys.executable, "-c", "print('skip.log\\nkeep.py\\nskip.log\\nlast.py',end='')"],
        2,
        accept=lambda path: path.endswith(".py"),
    )
    assert paths == ["keep.py", "last.py"]
    assert not timed_out


@pytest.fixture
def search_tools(mcp):
    from terminal_tools.search.tools import register_search_tools

    register_search_tools(mcp)
    return {
        "rg": mcp._tool_manager._tools["terminal_rg"].fn,
        "glob": mcp._tool_manager._tools["terminal_glob"].fn,
    }


@pytest.mark.skipif(not resolve_ripgrep(), reason="ripgrep not installed")
def test_rg_finds_pattern(search_tools, tmp_path):
    (tmp_path / "a.txt").write_text("hello\nworld\nfoo\n")
    (tmp_path / "b.txt").write_text("bar\nworld\n")

    result = search_tools["rg"](pattern="world", path=str(tmp_path))
    assert result["total"] >= 2
    paths = {m["path"] for m in result["matches"]}
    assert any("a.txt" in p for p in paths)


@pytest.mark.skipif(not resolve_ripgrep(), reason="ripgrep not installed")
def test_rg_no_matches(search_tools, tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    result = search_tools["rg"](pattern="zzz_no_match_zzz", path=str(tmp_path))
    assert result["total"] == 0
    assert result["matches"] == []


@pytest.mark.skipif(not resolve_ripgrep(), reason="ripgrep not installed")
def test_glob_by_name(search_tools, tmp_path):
    (tmp_path / "alpha.log").write_text("a")
    (tmp_path / "beta.log").write_text("b")
    (tmp_path / "ignore.txt").write_text("c")

    result = search_tools["glob"](pattern="*.log", path=str(tmp_path))
    assert result["count"] == 2
    assert all(p.endswith(".log") for p in result["paths"])


@pytest.mark.skipif(not resolve_ripgrep(), reason="ripgrep not installed")
def test_glob_bare_stem_matches_file_with_extension(search_tools, tmp_path):
    """Regression: a bare filename stem (no wildcard, no extension) must find
    the file. The old find -name semantics returned a silent zero here — the
    exact trap that motivated the rewrite. WHY it matters: models routinely
    pass the stem they remember, not a glob, and a silent zero reads as
    "file doesn't exist."
    """
    nested = tmp_path / "scripts"
    nested.mkdir()
    (nested / "lk_scan_post_reactors.py").write_text("x")

    result = search_tools["glob"](pattern="lk_scan_post_reactors", path=str(tmp_path))
    assert result["expanded_pattern"] == "**/*lk_scan_post_reactors*"
    assert any(p.endswith("lk_scan_post_reactors.py") for p in result["paths"]), result


@pytest.mark.skipif(not resolve_ripgrep(), reason="ripgrep not installed")
def test_glob_recurses_by_default(search_tools, tmp_path):
    """A glob with a metachar but no '/' should recurse (gets a '**/' prefix)."""
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    (deep / "config.py").write_text("x")

    result = search_tools["glob"](pattern="*.py", path=str(tmp_path))
    assert any(p.endswith("config.py") for p in result["paths"]), result


@pytest.mark.skipif(not resolve_ripgrep(), reason="ripgrep not installed")
def test_glob_no_matches(search_tools, tmp_path):
    (tmp_path / "a.txt").write_text("x")
    result = search_tools["glob"](pattern="zzz_no_such_file_zzz", path=str(tmp_path))
    assert result["count"] == 0
    assert result["paths"] == []


def test_expand_glob_pattern_rules():
    from terminal_tools.search.tools import _expand_glob_pattern

    # bare stem -> recursive substring
    assert _expand_glob_pattern("lk_scan") == "**/*lk_scan*"
    # has metachar, no slash -> recursive
    assert _expand_glob_pattern("*.py") == "**/*.py"
    # explicit path -> verbatim
    assert _expand_glob_pattern("src/**/*.py") == "src/**/*.py"


def test_walk_fallback_finds_bare_stem(tmp_path):
    """The os.walk fallback (no ripgrep) honors the same expanded pattern."""
    from terminal_tools.search.tools import _expand_glob_pattern, _walk_paths

    nested = tmp_path / "scripts"
    nested.mkdir()
    (nested / "lk_scan_post_reactors.py").write_text("x")

    expanded = _expand_glob_pattern("lk_scan_post_reactors")
    paths, truncated = _walk_paths(expanded, str(tmp_path), 1000, include_ignored=False)
    assert any(p.endswith("lk_scan_post_reactors.py") for p in paths)
    assert truncated is False


def test_rg_fallback_requires_explicit_opt_in(search_tools, tmp_path, monkeypatch):
    """A missing executable must not silently broaden a gitignore-aware search."""
    import terminal_tools.search.tools as st

    monkeypatch.setattr(st, "_resolve_rg", lambda: None)

    (tmp_path / "a.txt").write_text("hello\nworld\nfoo\n")
    (tmp_path / "b.py").write_text("bar\nworld\n")
    (tmp_path / ".gitignore").write_text("b.py\n")

    result = search_tools["rg"](pattern="world", path=str(tmp_path))
    assert result["code"] == "ripgrep_required"
    assert "matches" not in result
    assert "allow_fallback=True" in result["error"]

    result = search_tools["rg"](pattern="world", path=str(tmp_path), allow_fallback=True)
    assert "error" not in result, result
    assert result["fallback"] == "python-walk"
    assert "No .gitignore awareness" in result["fallback_limitations"]
    assert result["total"] >= 2
    paths = {m["path"] for m in result["matches"]}
    assert any(p.endswith("a.txt") for p in paths)
    assert any(p.endswith("b.py") for p in paths)


def test_rg_fallback_respects_glob_and_case(search_tools, tmp_path, monkeypatch):
    """The fallback honors the glob filter and ignore_case flag."""
    import terminal_tools.search.tools as st

    monkeypatch.setattr(st, "_resolve_rg", lambda: None)

    (tmp_path / "a.txt").write_text("NEEDLE\n")
    (tmp_path / "b.py").write_text("needle\n")

    result = search_tools["rg"](pattern="needle", path=str(tmp_path), glob="*.py", ignore_case=True, allow_fallback=True)
    assert result["total"] == 1
    assert result["matches"][0]["path"].endswith("b.py")
    assert result["matches"][0]["line"] == 1


def test_walk_grep_max_count_per_file(tmp_path):
    """max_count caps matches per file, like rg -m."""
    from terminal_tools.search.tools import _walk_grep

    (tmp_path / "f.txt").write_text("x\nx\nx\nx\n")
    res = _walk_grep(
        "x",
        str(tmp_path),
        glob=None,
        type_filter=None,
        ignore_case=False,
        max_count=2,
        max_depth=None,
        hidden=False,
        no_ignore=False,
        allow_fallback=True,
    )
    assert res["total"] == 2


@pytest.mark.parametrize("options", [{"context": 2}, {"extra_args": ["-F"]}, {"type_filter": "unknown_type"}, {"glob": "src/**/*.py"}])
@pytest.mark.parametrize("disappears", [False, True])
def test_rg_fallback_rejects_unsupported_parameters_before_search(search_tools, monkeypatch, options, disappears):
    import terminal_tools.search.tools as st

    monkeypatch.setattr(st, "_resolve_rg", lambda: "rg" if disappears else None)

    def vanished(*args, **kwargs):
        raise FileNotFoundError("rg disappeared")

    def unexpected_walk(*args, **kwargs):
        pytest.fail("Unsupported searches must fail before traversing files")

    monkeypatch.setattr(st.subprocess, "run", vanished)
    monkeypatch.setattr(st.os, "walk", unexpected_walk)
    result = search_tools["rg"](pattern="needle", allow_fallback=True, **options)
    assert result["code"] == "ripgrep_required"
    assert result["unsupported_parameters"] == list(options)
    assert "matches" not in result


def test_rg_preserves_context_events(search_tools, monkeypatch):
    import terminal_tools.search.tools as st

    monkeypatch.setattr(st, "_resolve_rg", lambda: "rg")
    events = [
        {"type": kind, "data": {"path": {"text": "code.py"}, "line_number": line, "lines": {"text": text}}}
        for kind, line, text in [("context", 1, "before\r\n"), ("match", 2, "needle\r\n"), ("context", 3, "after\r\n")]
    ]

    def run(argv, **kwargs):
        assert argv[argv.index("-C") + 1] == "1"
        return subprocess.CompletedProcess(argv, 0, stdout="\n".join(map(json.dumps, events)).encode(), stderr=b"")

    monkeypatch.setattr(st.subprocess, "run", run)
    result = search_tools["rg"](pattern="needle", context=1)
    assert result["matches"] == [{"path": "code.py", "line": 2, "text": "needle"}]
    assert result["total"] == 1
    assert result["context"] == [{"path": "code.py", "line": 1, "text": "before"}, {"path": "code.py", "line": 3, "text": "after"}]


@pytest.mark.skipif(not resolve_ripgrep(), reason="ripgrep not installed")
def test_rg_native_context_and_gitignore(search_tools, tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    (tmp_path / "ignored.txt").write_text("needle\n")
    (tmp_path / "visible.txt").write_text("before\nneedle\nafter\n")
    result = search_tools["rg"](pattern="needle", path=str(tmp_path), context=1)
    assert result["total"] == 1
    assert result["matches"][0]["path"].endswith("visible.txt")
    assert [(item["line"], item["text"]) for item in result["context"]] == [(1, "before"), (3, "after")]


@pytest.mark.skipif(not resolve_ripgrep(), reason="ripgrep not installed")
@pytest.mark.parametrize("fallback", [False, True])
def test_glob_path_segments_braces_and_recursion(search_tools, tmp_path, monkeypatch, fallback):
    from terminal_tools.search import tools

    if fallback:
        monkeypatch.setattr(tools, "_resolve_rg", lambda: None)
    for name in ("src/a.py", "src/deep/b.py", "src/deep/b.ts", "src/deep/c.txt", "other/a.py"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")
    result = search_tools["glob"](pattern="src/**/*.{py,ts}", path=str(tmp_path))
    assert {Path(path).relative_to(tmp_path).as_posix() for path in result["paths"]} == {"src/a.py", "src/deep/b.py", "src/deep/b.ts"}
    result = search_tools["glob"](pattern="src/*.py", path=str(tmp_path))
    assert {Path(path).relative_to(tmp_path).as_posix() for path in result["paths"]} == {"src/a.py"}


@pytest.mark.skipif(not resolve_ripgrep(), reason="ripgrep not installed")
@pytest.mark.parametrize("include_ignored", [False, True])
def test_glob_respects_ignore_rules_unless_opted_out(search_tools, tmp_path, include_ignored):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("ignored.txt\n")
    (tmp_path / ".ignore").write_text("extra.txt\n")
    for name in ("visible.txt", "ignored.txt", "extra.txt", ".hidden.txt"):
        (tmp_path / name).write_text("x")
    result = search_tools["glob"](pattern="*.txt", path=str(tmp_path), include_ignored=include_ignored)
    expected = {"visible.txt", "ignored.txt", "extra.txt", ".hidden.txt"} if include_ignored else {"visible.txt"}
    assert {Path(path).name for path in result["paths"]} == expected
