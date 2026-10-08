"""Phase 2 of search_messages: locate matches in the cache.

Two parallel sweeps:
    * events index — flat tree of <NNNNNN>.<role>.txt files
    * data index   — flat tree of mirrored spillover files

For each hit, return the structural coordinates ``(scope, owner,
session, ordinal, role, match_source, match_offsets)`` *without* the
content snippet — enrichment (turn assembly + offset re-anchoring)
runs as a separate phase against the events index.

Engine:
    * Prefer ripgrep (true Rust regex). Required for the public Rust-
      style contract — the whole point.
    * Fall back to Python ``re`` over the same flat tree if rg is
      missing. Same shape of output; lookaround/backref still rejected
      at validation time so behavior matches.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from memory_tools import paths as P

logger = logging.getLogger(__name__)


_EVENT_FILE_RE = re.compile(r"^(\d{6})\.(user|assistant|tool)\.txt$")


@dataclass
class Hit:
    scope: P.Scope
    owner: str
    session: str
    ordinal: int
    role: Literal["user", "assistant", "tool"]
    # Byte offsets into the raw cache file content; enrichment will
    # re-anchor these into the trimmed turn-window content.
    match_offsets: tuple[int, int]
    sources: set[str]  # subset of {"events", "data"}


def _engine_available() -> Literal["rg", "re"]:
    return "rg" if shutil.which("rg") else "re"


# ── Hit parsing helpers ────────────────────────────────────────────────


def _parse_event_path(path: Path) -> tuple[str, int, str] | None:
    """``…/<scope>/<owner>/<session>/000087.tool.txt`` → (session, ord, role)."""
    m = _EVENT_FILE_RE.match(path.name)
    if not m:
        return None
    session = path.parent.name
    return session, int(m.group(1)), m.group(2)


# ── ripgrep driver ─────────────────────────────────────────────────────


def _build_rg_argv(
    pattern: str,
    root: Path,
    *,
    ignore_case: bool,
    multiline: bool,
    dotall: bool,
    max_count: int | None,
) -> list[str]:
    argv = ["rg", "--json", "--no-heading"]
    if ignore_case:
        argv.append("-i")
    if multiline:
        argv.append("-U")  # multiline mode
    # Compose inline flags for dotall — rg treats `(?s)` as dotall enabling
    # `.` to match newlines while keeping the user's pattern intact.
    eff_pattern = f"(?s){pattern}" if dotall else pattern
    if max_count is not None:
        argv.extend(["-m", str(max_count)])
    argv.extend(["--", eff_pattern, str(root)])
    return argv


def _rg_sweep(
    pattern: str,
    root: Path,
    *,
    ignore_case: bool,
    multiline: bool,
    dotall: bool,
    max_count: int | None,
    timeout_sec: int = 30,
) -> list[tuple[Path, tuple[int, int]]]:
    """Run rg over ``root``; return [(path, (start, end))] in match order."""
    if not root.exists():
        return []
    argv = _build_rg_argv(
        pattern,
        root,
        ignore_case=ignore_case,
        multiline=multiline,
        dotall=dotall,
        max_count=max_count,
    )
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("memory_tools: rg timed out")
        return []

    out: list[tuple[Path, tuple[int, int]]] = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if evt.get("type") != "match":
            continue
        data = evt.get("data") or {}
        path_text = ((data.get("path") or {}).get("text")) or ""
        if not path_text:
            continue
        path = Path(path_text)
        # rg gives absolute byte offsets within the file when --json. The
        # ``submatches`` list has per-match {start, end} byte offsets.
        for sub in data.get("submatches") or []:
            start = int(sub.get("start", 0))
            end = int(sub.get("end", 0))
            out.append((path, (start, end)))
    return out


# ── Python re fallback ────────────────────────────────────────────────


def _re_sweep(
    pattern: str,
    root: Path,
    *,
    ignore_case: bool,
    multiline: bool,
    dotall: bool,
    max_count: int | None,
) -> list[tuple[Path, tuple[int, int]]]:
    if not root.exists():
        return []
    flags = 0
    if ignore_case:
        flags |= re.IGNORECASE
    if multiline:
        flags |= re.MULTILINE
    if dotall:
        flags |= re.DOTALL
    try:
        compiled = re.compile(pattern, flags)
    except re.error:
        return []

    out: list[tuple[Path, tuple[int, int]]] = []
    # Walk the tree; for each file run search and emit all matches.
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            fp = Path(dirpath) / fname
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            count = 0
            for m in compiled.finditer(text):
                # Convert character offsets to byte offsets so the rg
                # path and the re path return comparable spans.
                prefix = text[: m.start()].encode("utf-8", errors="replace")
                matched = text[m.start() : m.end()].encode("utf-8", errors="replace")
                start_b = len(prefix)
                end_b = start_b + len(matched)
                out.append((fp, (start_b, end_b)))
                count += 1
                if max_count is not None and count >= max_count:
                    break
    return out


# ── Top-level locate ──────────────────────────────────────────────────


def locate(
    scope: P.Scope,
    owner: str,
    pattern: str,
    *,
    session_filter: str | None,
    role_filter: Literal["user", "assistant", "tool", "all"],
    match_source: Literal["events", "data", "all"],
    ignore_case: bool,
    multiline: bool,
    dotall: bool,
    max_per_source: int = 500,
) -> tuple[list[Hit], str]:
    """Run the locate phase. Returns (deduped_hits, engine_used)."""
    engine = _engine_available()
    sweep = _rg_sweep if engine == "rg" else _re_sweep

    events_root = P.events_index_dir(scope, owner, session_filter) if session_filter else P.events_index_dir(scope, owner)
    data_root = P.data_index_dir(scope, owner, session_filter) if session_filter else P.data_index_dir(scope, owner)

    do_events = match_source in ("events", "all")
    do_data = match_source in ("data", "all")

    # Run the two sweeps in parallel.
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_events = (
            pool.submit(
                sweep,
                pattern,
                events_root,
                ignore_case=ignore_case,
                multiline=multiline,
                dotall=dotall,
                max_count=max_per_source,
            )
            if do_events
            else None
        )
        f_data = (
            pool.submit(
                sweep,
                pattern,
                data_root,
                ignore_case=ignore_case,
                multiline=multiline,
                dotall=dotall,
                max_count=max_per_source,
            )
            if do_data
            else None
        )
        events_raw = f_events.result() if f_events else []
        data_raw = f_data.result() if f_data else []

    hits: dict[tuple[str, int], Hit] = {}

    # Events hits map directly: filename encodes (ordinal, role).
    for path, span in events_raw:
        parsed = _parse_event_path(path)
        if not parsed:
            continue
        session, ordinal, role = parsed
        if role_filter != "all" and role != role_filter:
            continue
        key = (session, ordinal)
        h = hits.get(key)
        if h is None:
            hits[key] = Hit(
                scope=scope,
                owner=owner,
                session=session,
                ordinal=ordinal,
                role=role,  # type: ignore[arg-type]
                match_offsets=span,
                sources={"events"},
            )
        else:
            h.sources.add("events")
            # Prefer the events span for offset re-anchoring (events file
            # is what the enrichment phase reads).
            h.match_offsets = span

    # Data hits → look up ordinal via per-session data_map.
    if data_raw:
        # Cache data_maps per session to avoid re-reading.
        data_map_cache: dict[str, dict] = {}
        for path, _span in data_raw:
            session = path.parent.name
            dmap = data_map_cache.get(session)
            if dmap is None:
                dmap = _read_json_safe(P.data_map_path(scope, owner, session))
                data_map_cache[session] = dmap
            ordinal = dmap.get(path.name)
            if ordinal is None:
                # Orphan spill (placeholder hasn't landed yet, or events
                # entry was wiped). Can't anchor it to a turn — drop.
                continue
            ordinal = int(ordinal)
            # Tool role only (data dir holds spilled tool results).
            if role_filter not in ("all", "tool"):
                continue
            key = (session, ordinal)
            h = hits.get(key)
            if h is None:
                # We have no events-side span for the cache file, so we
                # leave match_offsets pointing at zero — enrichment will
                # search for the pattern again inside the trimmed turn
                # content to produce a final anchored span.
                hits[key] = Hit(
                    scope=scope,
                    owner=owner,
                    session=session,
                    ordinal=ordinal,
                    role="tool",
                    match_offsets=(0, 0),
                    sources={"data"},
                )
            else:
                h.sources.add("data")

    return list(hits.values()), engine


def _read_json_safe(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


__all__ = ["Hit", "locate"]
