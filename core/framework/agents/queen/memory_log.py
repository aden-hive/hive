"""Every change to a memory file goes through here, and is kept.

A memory file used to be overwritten or deleted in place: a rewrite lost whatever it didn't restate,
a deletion was final, and nothing said who had written a file or when it was last true. So:

* each scope folder keeps ``log.jsonl``, one line per change: when, who, why, on what evidence, and
  the file's text before and after. A file that is retired leaves the folder and stays in the log,
  from where it can be restored (:func:`restore`).
* each file's frontmatter says who wrote it and how fresh it is::

      author: owner | queen | reflection   who last wrote it
      learned: 2026-11-09                  the day it was first written
      confirmed: 2026-11-09                the last day a conversation supported it

  A file the owner wrote is theirs: she can't overwrite or retire it (:class:`OwnerWritten`). A file
  with no ``author`` predates this and is nobody's yet; the owner's first edit claims it.
  ``confirmed`` is what a recalled memory's age is counted from, so tidying a file up doesn't make
  an old fact look new.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from framework.agents.queen.queen_memory_v2 import _FRONTMATTER_RE, MAX_FILE_SIZE_BYTES, parse_frontmatter

logger = logging.getLogger(__name__)

LOG_FILE = "log.jsonl"
Author = Literal["owner", "queen", "reflection"]
AUTHORS: tuple[str, ...] = ("owner", "queen", "reflection")


class OwnerWritten(ValueError):
    """The owner wrote this file; only they change or retire it."""


class TooLarge(ValueError):
    """The file would exceed ``MAX_FILE_SIZE_BYTES``."""


def author_of(text: str) -> str | None:
    """Who last wrote a memory file, or None for one written before authors were recorded."""
    author = parse_frontmatter(text).get("author", "").lower()
    return author if author in AUTHORS else None


def _day(value: str | None) -> str | None:
    """*value* as YYYY-MM-DD, or None when it isn't a date."""
    try:
        return date.fromisoformat((value or "").strip()[:10]).isoformat()
    except ValueError:
        return None


def confirmed_on(text: str) -> date | None:
    """The last day a conversation supported the file, when it says."""
    day = _day(parse_frontmatter(text).get("confirmed"))
    return date.fromisoformat(day) if day else None


def _with_frontmatter(text: str, fields: dict[str, str]) -> str:
    """*text* with *fields* set in its frontmatter, which is added when it has none."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        head = "\n".join(f"{key}: {value}" for key, value in fields.items())
        return f"---\n{head}\n---\n\n{text.lstrip()}"
    lines = match.group(1).splitlines()
    for key, value in fields.items():
        at = next((i for i, line in enumerate(lines) if line.partition(":")[0].strip().lower() == key), None)
        if at is None:
            lines.append(f"{key}: {value}")
        else:
            lines[at] = f"{key}: {value}"
    return "---\n" + "\n".join(lines) + text[match.end(1) :]


def _append(memory_dir: Path, entry: dict[str, Any]) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    with (memory_dir / LOG_FILE).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _guard(before: str | None, filename: str, author: str) -> None:
    if author != "owner" and before is not None and author_of(before) == "owner":
        raise OwnerWritten(f"{filename} was written by the owner; write what you learned to another file and tell them where the two differ")


def write(
    memory_dir: Path,
    filename: str,
    content: str,
    *,
    author: Author,
    reason: str = "",
    sources: list[dict[str, str]] | None = None,
    confirms: bool = True,
    claim: bool = True,
    now: datetime | None = None,
) -> str:
    """Make *content* the memory file *filename*, and log the change. Returns the text written.

    *confirms*: a conversation supports what the file says as of *now* (false when it is only being
    reorganised, which keeps the day it was last confirmed). *claim*: the file becomes *author*'s
    (false for a change that leaves it whoever's it was, like the settings page's identity lines).
    """
    path = memory_dir / filename
    before = _read(path)
    _guard(before, filename, author)
    today = (now or datetime.now()).date().isoformat()
    old = parse_frontmatter(before or "")
    new = parse_frontmatter(content)
    # A change that doesn't claim the file leaves it whoever's it was: nobody's, when it is new.
    fields = {"author": author if claim else (author_of(before or "") or "")}
    fields["learned"] = _day(old.get("learned")) or min(_day(new.get("learned")) or today, today)
    fields["confirmed"] = today if confirms else (_day(old.get("confirmed")) or min(_day(new.get("confirmed")) or today, today))
    if not content.endswith("\n"):
        content += "\n"
    text = _with_frontmatter(content, {k: v for k, v in fields.items() if v})
    if len(text.encode("utf-8")) > MAX_FILE_SIZE_BYTES:
        raise TooLarge(f"Content exceeds {MAX_FILE_SIZE_BYTES} byte limit.")
    memory_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _append(memory_dir, _entry("write", filename, author, reason, before, text, sources, now))
    return text


def retire(memory_dir: Path, filename: str, *, author: Author, reason: str = "", now: datetime | None = None) -> None:
    """Take a memory file out of use. Its text stays in the log."""
    path = memory_dir / filename
    before = _read(path)
    if before is None:
        raise FileNotFoundError(filename)
    _guard(before, filename, author)
    path.unlink()
    _append(memory_dir, _entry("retire", filename, author, reason, before, None, None, now))


def _entry(
    op: str,
    filename: str,
    author: str,
    reason: str,
    before: str | None,
    after: str | None,
    sources: list[dict[str, str]] | None,
    now: datetime | None,
) -> dict[str, Any]:
    return {
        "at": (now or datetime.now()).astimezone().isoformat(timespec="seconds"),
        "op": op,
        "file": filename,
        "author": author,
        "reason": reason,
        "sources": sources or [],
        "before": before,
        "after": after,
    }


def history(memory_dir: Path, filename: str | None = None) -> list[dict[str, Any]]:
    """The changes made in *memory_dir* (to *filename* when given), oldest first, each with its ``n`` in the log."""
    entries: list[dict[str, Any]] = []
    text = _read(memory_dir / LOG_FILE) or ""
    for n, line in enumerate(text.splitlines()):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and (filename is None or entry.get("file") == filename):
            entries.append({"n": n, **entry})
    return entries


def retired(memory_dir: Path) -> list[dict[str, Any]]:
    """The files whose last change retired them, newest first: their retirement's log entry."""
    last: dict[str, dict[str, Any]] = {}
    for entry in history(memory_dir):
        last[entry.get("file", "")] = entry
    gone = [e for name, e in last.items() if e.get("op") == "retire" and not (memory_dir / name).exists()]
    return sorted(gone, key=lambda e: e["n"], reverse=True)


def restore(memory_dir: Path, filename: str, n: int, *, now: datetime | None = None) -> str:
    """Bring *filename* back to what it said after change *n* (before it, for a retirement). The owner's doing."""
    entry = next((e for e in history(memory_dir, filename) if e["n"] == n), None)
    text = (entry or {}).get("after") or (entry or {}).get("before")
    if not isinstance(text, str):
        raise LookupError(f"{filename} has no change {n} to go back to")
    path = memory_dir / filename
    before = _read(path)
    memory_dir.mkdir(parents=True, exist_ok=True)
    # As it was, author and dates included: going back doesn't make it the owner's or today's.
    path.write_text(text, encoding="utf-8")
    _append(memory_dir, _entry("restore", filename, "owner", f"back to change {n}", before, text, None, now))
    return text
