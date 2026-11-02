"""Past turns as an inverted index, so recall can answer without scanning the mirror cache.

Recall runs before the model is called, on every user message. Asking ``rg`` which of the
mirror's files hold a term costs seconds on a warm disk and half a minute on a cold one, for a
store of a few dozen sessions. So each scope/owner keeps one SQLite file beside the mirror: a
row per turn and, per term, the turns holding it with their counts. That is everything BM25
needs, so a query reads a few index pages, and the text of the turns it picks.

The file is derived from the mirror: deleting it costs a rebuild, nothing more. It follows each
session's ``events.jsonl``, so a session that hasn't changed costs one stat per query.

A turn is one user message plus the assistant replies that follow it.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from collections import Counter
from pathlib import Path

from memory_tools import paths as P
from memory_tools.index import sync_session

logger = logging.getLogger(__name__)

# Chinese and Japanese have no spaces: a run of these characters is cut into overlapping
# two-character terms ("好累啊" -> "好累", "累啊").
CJK_RUN_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]{2,}")
_WORD_RE = re.compile(r"[a-z0-9]+")
_FILE_RE = re.compile(r"^(\d{6})\.(user|assistant|tool)\.txt$")
# Sorts after every term, closing the range of terms that start with a prefix.
_LAST_CHAR = "\U0010ffff"
# Marks a session with no events.jsonl of its own (a mirror whose source is gone).
_NO_EVENTS = -1

# Bump when term_counts or the tables change; an older file is rebuilt.
_VERSION = 1
_SCHEMA = (
    "DROP TABLE IF EXISTS sessions",
    "DROP TABLE IF EXISTS turns",
    "DROP TABLE IF EXISTS postings",
    "CREATE TABLE sessions (name TEXT PRIMARY KEY, events_size INTEGER NOT NULL, last_user INTEGER NOT NULL)",
    """CREATE TABLE turns (
        id INTEGER PRIMARY KEY,
        session TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        user TEXT NOT NULL,
        reply TEXT NOT NULL,
        length INTEGER NOT NULL,
        UNIQUE (session, ordinal)
    )""",
    "CREATE TABLE postings (term TEXT NOT NULL, turn INTEGER NOT NULL, tf INTEGER NOT NULL, PRIMARY KEY (term, turn)) WITHOUT ROWID",
    f"PRAGMA user_version = {_VERSION}",
)

# One refresh per index at a time, in this process; see refresh().
_refreshing: dict[Path, threading.Lock] = {}


def term_counts(text: str) -> Counter[str]:
    """Every term in *text* a query could ask for: words, and CJK two-character terms."""
    # query_terms drops shorter words unless they are numbers, so they would never be asked for.
    counts = Counter(word for word in _WORD_RE.findall(text.lower()) if len(word) >= 3 or word[0].isdigit())
    for run in CJK_RUN_RE.findall(text):
        counts.update(run[i : i + 2] for i in range(len(run) - 1))
    return counts


def _turn_counts(user: str, reply: str) -> Counter[str]:
    """Term counts for a turn. User text counts double; see ``memory_tools.recall``."""
    user_counts = term_counts(user)
    return user_counts + user_counts + term_counts(reply)


def connect(scope: P.Scope, owner: str) -> sqlite3.Connection:
    """Open the index for *owner*, creating or rebuilding its tables if they are out of date."""
    path = P.turn_index_path(scope, owner)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    try:
        # WAL: a query reads while a long refresh writes.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        if conn.execute("PRAGMA user_version").fetchone()[0] != _VERSION:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("PRAGMA user_version").fetchone()[0] != _VERSION:
                for statement in _SCHEMA:
                    conn.execute(statement)
            conn.commit()
    except BaseException:
        conn.close()
        raise
    return conn


def refresh(conn: sqlite3.Connection, scope: P.Scope, owner: str, *, skip: str | None = None) -> None:
    """Bring the index up to date with every session but *skip*.

    Never waits for another thread's refresh: a first build of a large store takes a minute,
    and a query can answer from what is already there meanwhile.
    """
    lock = _refreshing.setdefault(P.turn_index_path(scope, owner), threading.Lock())
    if not lock.acquire(blocking=False):
        return
    try:
        known = {name: (size, last_user) for name, size, last_user in conn.execute("SELECT name, events_size, last_user FROM sessions")}
        mirror = P.events_index_dir(scope, owner)
        present = set(P.list_sessions(scope, owner))
        if mirror.is_dir():
            present.update(entry.name for entry in os.scandir(mirror) if entry.is_dir())
        for session in known.keys() - present:
            with conn:
                _forget_session(conn, session)
        for session in sorted(present - {skip}):
            size = _events_size(scope, owner, session)
            old_size, last_user = known.get(session, (None, -1))
            if size == old_size:
                continue
            try:
                with conn:
                    if old_size is not None and size < old_size:
                        # The session's log was rewritten; sync starts its mirror over too.
                        _forget_session(conn, session)
                        last_user = -1
                sync_session(scope, owner, session)
                with conn:
                    _index_session(conn, session, mirror / session, size, last_user)
            except OSError:
                # Windows refuses a file another process is replacing. The session stays
                # behind its log, so the next query tries it again.
                logger.debug("memory_tools: couldn't index session %s", session, exc_info=True)
    finally:
        lock.release()


def turns_with(conn: sqlite3.Connection, term: str) -> dict[int, int]:
    """turn id -> count of *term*. Latin terms match as word prefixes, CJK terms exactly."""
    if CJK_RUN_RE.fullmatch(term):
        return dict(conn.execute("SELECT turn, tf FROM postings WHERE term = ?", (term,)))
    return dict(conn.execute("SELECT turn, SUM(tf) FROM postings WHERE term >= ? AND term < ? GROUP BY turn", (term, term + _LAST_CHAR)))


def all_turns(conn: sqlite3.Connection) -> dict[int, tuple[str, int, int]]:
    """turn id -> (session, ordinal, length), with user text counted double in the length."""
    return {turn: (session, ordinal, length) for turn, session, ordinal, length in conn.execute("SELECT id, session, ordinal, length FROM turns")}


def turn_text(conn: sqlite3.Connection, session: str, ordinal: int) -> tuple[str, str]:
    """(user text, reply text) of one turn."""
    row = conn.execute("SELECT user, reply FROM turns WHERE session = ? AND ordinal = ?", (session, ordinal)).fetchone()
    return row if row else ("", "")


def _events_size(scope: P.Scope, owner: str, session: str) -> int:
    try:
        return P.events_jsonl(scope, owner, session).stat().st_size
    except OSError:
        return _NO_EVENTS


def _session_turns(session_dir: Path) -> dict[int, tuple[Path, list[Path]]]:
    """user ordinal → (user file, the assistant files answering it)."""
    if not session_dir.is_dir():
        return {}
    entries = sorted((int(m.group(1)), m.group(2), session_dir / name) for name in os.listdir(session_dir) if (m := _FILE_RE.match(name)))
    turns: dict[int, tuple[Path, list[Path]]] = {}
    current: int | None = None
    for ordinal, role, path in entries:
        if role == "user":
            current = ordinal
            turns[ordinal] = (path, [])
        elif role == "assistant" and current is not None:
            turns[current][1].append(path)
    return turns


def _index_session(conn: sqlite3.Connection, session: str, session_dir: Path, size: int, last_user: int) -> None:
    """Index the turns from *last_user* on: the last one seen can still grow, earlier ones can't."""
    turns = _session_turns(session_dir)
    for ordinal in sorted(turns):
        if ordinal >= last_user:
            user_file, reply_files = turns[ordinal]
            user = user_file.read_text(encoding="utf-8", errors="replace")
            reply = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in reply_files)
            _put_turn(conn, session, ordinal, user, reply)
    conn.execute(
        "INSERT OR REPLACE INTO sessions (name, events_size, last_user) VALUES (?, ?, ?)",
        (session, size, max(turns, default=-1)),
    )


def _put_turn(conn: sqlite3.Connection, session: str, ordinal: int, user: str, reply: str) -> None:
    old = conn.execute("SELECT id, user, reply FROM turns WHERE session = ? AND ordinal = ?", (session, ordinal)).fetchone()
    if old and old[1:] == (user, reply):
        return
    length = len(user) * 2 + len(reply)
    if old:
        turn = old[0]
        _delete_postings(conn, turn, old[1], old[2])
        conn.execute("UPDATE turns SET user = ?, reply = ?, length = ? WHERE id = ?", (user, reply, length, turn))
    else:
        turn = conn.execute(
            "INSERT INTO turns (session, ordinal, user, reply, length) VALUES (?, ?, ?, ?, ?)",
            (session, ordinal, user, reply, length),
        ).lastrowid
    conn.executemany("INSERT INTO postings (term, turn, tf) VALUES (?, ?, ?)", ((term, turn, tf) for term, tf in _turn_counts(user, reply).items()))


def _delete_postings(conn: sqlite3.Connection, turn: int, user: str, reply: str) -> None:
    conn.executemany("DELETE FROM postings WHERE term = ? AND turn = ?", ((term, turn) for term in _turn_counts(user, reply)))


def _forget_session(conn: sqlite3.Connection, session: str) -> None:
    for turn, user, reply in conn.execute("SELECT id, user, reply FROM turns WHERE session = ?", (session,)).fetchall():
        _delete_postings(conn, turn, user, reply)
    conn.execute("DELETE FROM turns WHERE session = ?", (session,))
    conn.execute("DELETE FROM sessions WHERE name = ?", (session,))
