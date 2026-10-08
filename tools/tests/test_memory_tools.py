"""Tests for memory_tools — search_messages and supporting cache layer.

Each test points HIVE_HOME at a tmp dir, builds a synthetic queen
session laid out the way the runtime writes one, and exercises the
sync → locate → enrich pipeline end-to-end.

Scope binding (which queen/colony to search) is read from
HIVE_QUEEN_ID / HIVE_COLONY_NAME env vars — the host injects these
before launching the memory-tools subprocess so the model never
chooses the scope. Tests set them via ``monkeypatch.setenv``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def hive_home(tmp_path: Path, monkeypatch) -> Path:
    """Point HIVE_HOME at an isolated tmp dir for each test."""
    monkeypatch.setenv("HIVE_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def bind_queen(monkeypatch):
    """Helper to inject the host scope binding for a test."""

    def _bind(queen_id: str) -> None:
        monkeypatch.setenv("HIVE_QUEEN_ID", queen_id)
        monkeypatch.delenv("HIVE_COLONY_NAME", raising=False)

    return _bind


@pytest.fixture
def bind_colony(monkeypatch):
    def _bind(colony_name: str) -> None:
        monkeypatch.setenv("HIVE_COLONY_NAME", colony_name)
        monkeypatch.delenv("HIVE_QUEEN_ID", raising=False)

    return _bind


@pytest.fixture
def unbind_scope(monkeypatch):
    """Ensure no scope is bound — exercises the scope_unbound error path."""
    monkeypatch.delenv("HIVE_QUEEN_ID", raising=False)
    monkeypatch.delenv("HIVE_COLONY_NAME", raising=False)


def _write_session(
    hive_home: Path,
    *,
    queen: str,
    session: str,
    events: list[dict],
    spilled_files: dict[str, str] | None = None,
) -> Path:
    """Materialize a synthetic queen session under HIVE_HOME."""
    sdir = hive_home / "agents" / "queens" / queen / "sessions" / session
    sdir.mkdir(parents=True, exist_ok=True)
    events_path = sdir / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    (sdir / "meta.json").write_text(json.dumps({"created_at": 0.0, "queen_id": queen}), encoding="utf-8")
    if spilled_files:
        ddir = sdir / "data"
        ddir.mkdir(parents=True, exist_ok=True)
        for name, body in spilled_files.items():
            (ddir / name).write_text(body, encoding="utf-8")
    return sdir


def _user_event(content: str, *, ts: str = "2026-05-01T10:00:00") -> dict:
    return {
        "type": "client_input_received",
        "data": {"content": content},
        "timestamp": ts,
    }


def _assistant_deltas(snapshot: str, *, iteration: int = 0, inner_turn: int = 0) -> list[dict]:
    """Two deltas: a partial then the full snapshot, like the runtime emits."""
    half = snapshot[: max(1, len(snapshot) // 2)]
    return [
        {
            "type": "client_output_delta",
            "data": {
                "content": half,
                "snapshot": half,
                "iteration": iteration,
                "inner_turn": inner_turn,
            },
        },
        {
            "type": "client_output_delta",
            "data": {
                "content": snapshot[len(half) :],
                "snapshot": snapshot,
                "iteration": iteration,
                "inner_turn": inner_turn,
            },
        },
    ]


def _tool_event(
    *,
    tool_name: str,
    result: str,
    tool_use_id: str = "call_x",
    is_error: bool = False,
) -> dict:
    return {
        "type": "tool_call_completed",
        "data": {
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "result": result,
            "is_error": is_error,
        },
    }


# ── Index unit tests (exercise the indexer directly) ──────────────────


def test_sync_emits_one_cache_file_per_in_scope_message(hive_home: Path):
    from memory_tools import index, paths as P

    events = [
        _user_event("hello queen"),
        *_assistant_deltas("greetings, human"),
        _tool_event(tool_name="bash", result="output line"),
    ]
    _write_session(hive_home, queen="queen_x", session="session_20260501_100000_aaaa", events=events)

    stats = index.sync_scope("queens", "queen_x")
    assert stats.sessions_visited == 1
    assert stats.ordinals_added == 3

    events_dir = P.events_index_dir("queens", "queen_x", "session_20260501_100000_aaaa")
    files = sorted(p.name for p in events_dir.iterdir())
    assert files == ["000000.user.txt", "000001.assistant.txt", "000002.tool.txt"]
    assert (events_dir / "000000.user.txt").read_text() == "hello queen"
    assert (events_dir / "000001.assistant.txt").read_text() == "greetings, human"
    assert (events_dir / "000002.tool.txt").read_text() == "output line"


def test_sync_excludes_out_of_scope_fields(hive_home: Path):
    """tool_name, tool_input, reasoning, etc must NEVER appear in cache."""
    from memory_tools import index, paths as P

    events = [
        # tool_call_started carries tool_name + tool_input — should be ignored entirely.
        {
            "type": "tool_call_started",
            "data": {
                "tool_use_id": "call_1",
                "tool_name": "ZZZZ_secret_tool_name",
                "tool_input": {"hidden_arg": "MUST_NOT_LEAK"},
            },
        },
        # llm_turn_complete carries token counts + reasoning metadata.
        {
            "type": "llm_turn_complete",
            "data": {
                "stop_reason": "tool_calls",
                "model": "x",
                "input_tokens": 999,
                "output_tokens": 999,
                "reasoning_details": "MUST_NOT_LEAK",
            },
        },
        _user_event("real user message"),
    ]
    _write_session(hive_home, queen="queen_x", session="session_20260501_100000_aaaa", events=events)

    index.sync_scope("queens", "queen_x")

    events_dir = P.events_index_dir("queens", "queen_x", "session_20260501_100000_aaaa")
    bodies = "".join(p.read_text() for p in events_dir.iterdir())
    assert "ZZZZ_secret_tool_name" not in bodies
    assert "MUST_NOT_LEAK" not in bodies
    assert "real user message" in bodies


def test_sync_resumes_from_cursor(hive_home: Path):
    from memory_tools import index, paths as P

    sdir = _write_session(
        hive_home,
        queen="queen_x",
        session="session_20260501_100000_aaaa",
        events=[_user_event("first")],
    )
    index.sync_scope("queens", "queen_x")

    with (sdir / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(_user_event("second")) + "\n")

    stats = index.sync_scope("queens", "queen_x")
    assert stats.ordinals_added == 1

    events_dir = P.events_index_dir("queens", "queen_x", "session_20260501_100000_aaaa")
    files = sorted(p.name for p in events_dir.iterdir())
    assert files == ["000000.user.txt", "000001.user.txt"]
    assert (events_dir / "000001.user.txt").read_text() == "second"


def test_sync_detects_wipe(hive_home: Path):
    """When events.jsonl is truncated, cache resets cleanly."""
    from memory_tools import index, paths as P

    sdir = _write_session(
        hive_home,
        queen="queen_x",
        session="session_20260501_100000_aaaa",
        events=[_user_event("alpha"), _user_event("beta")],
    )
    index.sync_scope("queens", "queen_x")

    (sdir / "events.jsonl").write_text(json.dumps(_user_event("gamma")) + "\n", encoding="utf-8")

    stats = index.sync_scope("queens", "queen_x")
    assert stats.ordinals_added == 1

    events_dir = P.events_index_dir("queens", "queen_x", "session_20260501_100000_aaaa")
    files = sorted(p.name for p in events_dir.iterdir())
    assert files == ["000000.user.txt"]
    assert (events_dir / "000000.user.txt").read_text() == "gamma"


def test_sync_indexes_spilled_tool_result(hive_home: Path):
    """Large tool results: events caches the full body via the spill file."""
    from memory_tools import index, paths as P

    spill_name = "browser_snapshot_4.txt"
    sdir = hive_home / "agents" / "queens" / "queen_x" / "sessions" / "session_20260501_100000_aaaa"
    spill_abs = sdir / "data" / spill_name
    full_body = "needle_in_a_haystack " + ("x" * 200)
    placeholder = (
        "Tool `browser_snapshot` returned 60,108 characters (too large for context). "
        f"Full result saved at: {spill_abs}\n"
        f"Read the complete data with read_file(path='{spill_abs}').\n"
        "Preview: ...preview body without the needle..."
    )
    _write_session(
        hive_home,
        queen="queen_x",
        session="session_20260501_100000_aaaa",
        events=[
            _user_event("snap it"),
            _tool_event(tool_name="browser_snapshot", result=placeholder, tool_use_id="call_42"),
        ],
        spilled_files={spill_name: full_body},
    )

    index.sync_scope("queens", "queen_x")

    events_dir = P.events_index_dir("queens", "queen_x", "session_20260501_100000_aaaa")
    tool_cache = events_dir / "000001.tool.txt"
    assert tool_cache.exists()
    assert "needle_in_a_haystack" in tool_cache.read_text()

    dmap = json.loads(P.data_map_path("queens", "queen_x", "session_20260501_100000_aaaa").read_text())
    assert dmap[spill_name] == 1

    data_dir = P.data_index_dir("queens", "queen_x", "session_20260501_100000_aaaa")
    assert (data_dir / spill_name).exists()


def test_sync_handles_missing_spill_file(hive_home: Path):
    """If the placeholder references a missing path, fall back to placeholder text."""
    from memory_tools import index, paths as P

    placeholder = (
        "Tool `read_file` returned 12,345 characters (too large for context). "
        "Full result saved at: /nonexistent/path/foo.txt\n"
        "Preview: still a placeholder body"
    )
    _write_session(
        hive_home,
        queen="queen_x",
        session="session_20260501_100000_aaaa",
        events=[_tool_event(tool_name="read_file", result=placeholder)],
    )
    index.sync_scope("queens", "queen_x")
    events_dir = P.events_index_dir("queens", "queen_x", "session_20260501_100000_aaaa")
    body = (events_dir / "000000.tool.txt").read_text()
    assert "still a placeholder body" in body


# ── Tool-level e2e tests (use the host-injected scope binding) ────────


def _build_test_session(hive_home: Path, *, queen: str, session: str) -> None:
    events = [
        _user_event("step by step help me find a needle"),
        *_assistant_deltas("Sure — let me search for a needle now.", iteration=0, inner_turn=0),
        _tool_event(tool_name="bash", result="found NEEDLE_HIT in haystack"),
        *_assistant_deltas("I found it.", iteration=1, inner_turn=0),
        _user_event("great, do another one"),
        *_assistant_deltas("ok", iteration=2, inner_turn=0),
        _tool_event(tool_name="bash", result="nothing relevant here"),
    ]
    _write_session(hive_home, queen=queen, session=session, events=events)


def _make_tool():
    """Build a fresh FastMCP and return the registered search_messages fn."""
    from fastmcp import FastMCP

    from memory_tools import register_memory_tools

    mcp = FastMCP("t")
    register_memory_tools(mcp)
    return mcp._tool_manager._tools["search_messages"].fn


def test_search_messages_returns_turn_window(hive_home: Path, bind_queen):
    _build_test_session(hive_home, queen="queen_x", session="session_20260501_100000_aaaa")
    bind_queen("queen_x")
    fn = _make_tool()

    result = fn(pattern="NEEDLE_HIT")

    assert "error" not in result
    assert result["total_matches"] == 1
    assert len(result["matches"]) == 1
    m = result["matches"][0]
    assert m["session"].startswith("session_")
    assert m["session_started_at"] is not None
    # The hit turn entry is role=tool with is_hit set; turn includes the
    # preceding user message.
    roles = [t["role"] for t in m["turn"]]
    assert "user" in roles
    hit_entries = [t for t in m["turn"] if t.get("is_hit")]
    assert len(hit_entries) == 1
    assert hit_entries[0]["role"] == "tool"


def test_search_messages_role_filter(hive_home: Path, bind_queen):
    _build_test_session(hive_home, queen="queen_x", session="session_20260501_100000_aaaa")
    bind_queen("queen_x")
    fn = _make_tool()

    # Inline (?i) replaces the old ignore_case=True parameter.
    res_user = fn(pattern="(?i)needle", role="user")
    res_asst = fn(pattern="(?i)needle", role="assistant")
    res_tool = fn(pattern="(?i)needle", role="tool")

    def _hit_role(m):
        return next(t["role"] for t in m["turn"] if t.get("is_hit"))

    assert all(_hit_role(m) == "user" for m in res_user["matches"])
    assert all(_hit_role(m) == "assistant" for m in res_asst["matches"])
    assert all(_hit_role(m) == "tool" for m in res_tool["matches"])


def test_search_messages_inline_case_flag_works(hive_home: Path, bind_queen):
    """(?i) inline flag is the only way to do case-insensitive search."""
    _build_test_session(hive_home, queen="queen_x", session="session_20260501_100000_aaaa")
    bind_queen("queen_x")
    fn = _make_tool()

    case_sensitive = fn(pattern="NEEDLE_hit")
    case_insensitive = fn(pattern="(?i)NEEDLE_hit")

    assert case_sensitive["total_matches"] == 0
    assert case_insensitive["total_matches"] == 1


def test_search_messages_rejects_lookaround(hive_home: Path, bind_queen):
    _build_test_session(hive_home, queen="queen_x", session="session_20260501_100000_aaaa")
    bind_queen("queen_x")
    fn = _make_tool()

    res = fn(pattern="needle(?=foo)")
    assert res.get("error") == "regex_unsupported"
    assert res.get("feature") == "lookahead"


def test_search_messages_rejects_backreference(hive_home: Path, bind_queen):
    _build_test_session(hive_home, queen="queen_x", session="session_20260501_100000_aaaa")
    bind_queen("queen_x")
    fn = _make_tool()

    res = fn(pattern=r"(foo)\1")
    assert res.get("error") == "regex_unsupported"
    assert res.get("feature") == "backreference"


def test_search_messages_errors_when_scope_unbound(hive_home: Path, unbind_scope):
    """No HIVE_QUEEN_ID / HIVE_COLONY_NAME → scope_unbound."""
    fn = _make_tool()
    res = fn(pattern="x")
    assert res.get("error") == "scope_unbound"


def test_search_messages_errors_when_both_scopes_bound(hive_home: Path, monkeypatch):
    monkeypatch.setenv("HIVE_QUEEN_ID", "queen_a")
    monkeypatch.setenv("HIVE_COLONY_NAME", "colony_b")
    fn = _make_tool()
    res = fn(pattern="x")
    assert res.get("error") == "scope_unbound"


def test_search_messages_unknown_queen(hive_home: Path, bind_queen):
    _build_test_session(hive_home, queen="queen_real", session="session_20260501_100000_aaaa")
    bind_queen("queen_does_not_exist")
    fn = _make_tool()

    res = fn(pattern="x")
    assert res.get("error") == "scope_not_found"
    assert "queen_real" in res.get("available", [])


def test_search_messages_context_none_omits_turn(hive_home: Path, bind_queen):
    _build_test_session(hive_home, queen="queen_x", session="session_20260501_100000_aaaa")
    bind_queen("queen_x")
    fn = _make_tool()

    res = fn(pattern="NEEDLE_HIT", context="none")
    m = res["matches"][0]
    assert "turn" not in m


def test_search_messages_context_narrow_only_hit(hive_home: Path, bind_queen):
    _build_test_session(hive_home, queen="queen_x", session="session_20260501_100000_aaaa")
    bind_queen("queen_x")
    fn = _make_tool()

    res = fn(pattern="NEEDLE_HIT", context="narrow")
    m = res["matches"][0]
    assert len(m["turn"]) == 1
    assert m["turn"][0]["is_hit"] is True
