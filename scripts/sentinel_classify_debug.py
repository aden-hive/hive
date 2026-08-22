#!/usr/bin/env python
"""Inspect Sentinel's classifier decisions — what input it saw, what it decided.

WHY THIS EXISTS
---------------
When a colony queen parks before its goal is done, Sentinel's classifier
(`framework.sentinel.classifier.classify_park`) decides nudge-vs-escalate-vs-done.
A wrong verdict shows up as a bad behaviour — most commonly a queen that gets
nudged ("keep working") *after* it already reported the goal complete. The
classifier's input and verdict are otherwise ephemeral, so each call now emits a
structured ``classify_decision`` line (added in classifier._log_decision). This
script finds, parses, and pretty-prints those lines so you can see exactly what
the classifier was handed and why it answered the way it did.

ENABLE THE LOG FIRST
--------------------
The decision lines only hit disk when Sentinel's dedicated file logger is on:

    export HIVE_SENTINEL_LOG=1        # then (re)start the runtime / desktop app

That diverts ``framework.sentinel.*`` (DEBUG) to ``<HIVE_HOME>/logs/sentinel.log``.
On the desktop build HIVE_HOME is the per-user dir, so logs land at
``~/Library/Application Support/Hive/users/<id>/logs/sentinel.log``. This script
auto-discovers all of them.

USAGE
-----
    uv run scripts/sentinel_classify_debug.py                 # newest log, all decisions
    uv run scripts/sentinel_classify_debug.py --follow        # live tail (tail -f)
    uv run scripts/sentinel_classify_debug.py --verdict continue   # only this verdict
    uv run scripts/sentinel_classify_debug.py --grep InMail        # goal/last-msg contains text
    uv run scripts/sentinel_classify_debug.py --all          # merge every user's log
    uv run scripts/sentinel_classify_debug.py --file PATH     # a specific log file
    uv run scripts/sentinel_classify_debug.py --list          # just list discovered logs
    uv run scripts/sentinel_classify_debug.py --raw           # print matching raw lines

Reading the output: a ``continue`` verdict whose ``last_assistant_text`` is a
completion/closing report ("goal complete", "all done", "idle") is the classic
misfire — the queen said done, the classifier said keep going.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Stable grep anchor emitted by classifier._log_decision. Keep in sync.
MARKER = "classify_decision "

_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_VERDICT_COLOR = {
    "continue": "\033[33m",  # yellow — keeps nudging
    "needs_human": "\033[31m",  # red — escalates
    "done": "\033[32m",  # green — terminal
}

# Heuristic markers of a queen that believes it is finished — used only to flag
# a likely misfire (continue verdict over a completion-style last message). Not
# authoritative; purely a visual hint for the human reading the dump.
_DONE_HINTS = (
    "goal is complete",
    "goal is done",
    "goal complete",
    "all done",
    "nothing left",
    "i'm idle",
    "im idle",
    "idle until",
    "waiting for your",
    "waiting for next",
    "next instruction",
)


def _candidate_bases() -> list[Path]:
    """Likely HIVE_HOME roots to search for sentinel.log files."""
    bases: list[Path] = []
    env = os.environ.get("HIVE_HOME")
    if env:
        bases.append(Path(env).expanduser())
    home = Path.home()
    bases.extend(
        [
            home / "Library" / "Application Support" / "Hive",  # macOS desktop
            home / ".hive",  # OSS default
            home / ".config" / "Hive",  # linux desktop
        ]
    )
    # Dedupe, keep only existing.
    seen: set[Path] = set()
    out: list[Path] = []
    for b in bases:
        if b in seen or not b.is_dir():
            continue
        seen.add(b)
        out.append(b)
    return out


def discover_logs() -> list[Path]:
    """All sentinel.log files under known roots, newest first."""
    found: dict[Path, float] = {}
    for base in _candidate_bases():
        # Top-level (OSS single-user) and per-user (desktop) locations.
        for pattern in ("logs/sentinel.log", "users/*/logs/sentinel.log"):
            for p in base.glob(pattern):
                try:
                    found[p] = p.stat().st_mtime
                except OSError:
                    continue
    return sorted(found, key=lambda p: found[p], reverse=True)


def _short_id(path: Path) -> str:
    """A compact label for which log a line came from (the user id, if any)."""
    parts = path.parts
    if "users" in parts:
        i = parts.index("users")
        if i + 1 < len(parts):
            return parts[i + 1][:12]
    return path.parent.parent.name[:12] or "hive"


def parse_line(line: str) -> dict | None:
    """Extract the JSON payload from a classify_decision log line, or None."""
    idx = line.find(MARKER)
    if idx < 0:
        return None
    blob = line[idx + len(MARKER) :].strip()
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        return None
    # Best-effort timestamp prefix (RotatingFileHandler formats it leading).
    ts = line[:23].strip() if len(line) > 23 else ""
    payload["_ts"] = ts
    return payload


def _looks_done(text: str) -> bool:
    t = (text or "").lower()
    return any(h in t for h in _DONE_HINTS)


def render(p: dict, source: str, color: bool) -> str:
    def c(s: str, code: str) -> str:
        return f"{code}{s}{_RESET}" if color else s

    verdict = p.get("verdict", "?")
    vcolor = _VERDICT_COLOR.get(verdict, "")
    head = c(verdict.upper(), _BOLD + vcolor) if color else verdict.upper()
    ts = p.get("_ts", "")
    misfire = ""
    if verdict == "continue" and _looks_done(p.get("last_assistant_text", "")):
        misfire = c("  ⚠ LIKELY MISFIRE: continue over a completion-style message", "\033[1;31m")

    lines = [
        f"{c(ts, _DIM)}  [{source}]  {head}{misfire}",
        f"  reason:      {p.get('reason', '')}",
        f"  park_reason: {p.get('park_reason', '')}   "
        f"hard_blocker={p.get('hard_blocker')}   "
        f"workers={p.get('running_workers')}",
        f"  goal:        {p.get('goal')}",
    ]
    open_tasks = p.get("open_tasks") or []
    lines.append(f"  open_tasks:  {open_tasks if open_tasks else '(none)'}")
    errs = p.get("recent_errors") or []
    if errs:
        lines.append(f"  errors:      {errs}")
    user_txt = (p.get("recent_user_text") or "").strip()
    if user_txt:
        lines.append(f"  user_said:   {user_txt[:300]!r}")
    last = (p.get("last_assistant_text") or "").strip()
    lines.append(f"  queen_said:  {last[:600]!r}")
    return "\n".join(lines)


def _matches(p: dict, args: argparse.Namespace) -> bool:
    if args.verdict and p.get("verdict") != args.verdict:
        return False
    if args.grep:
        hay = " ".join(
            str(p.get(k, "")) for k in ("goal", "last_assistant_text", "recent_user_text", "reason")
        ).lower()
        if args.grep.lower() not in hay:
            return False
    return True


def _follow(path: Path, args: argparse.Namespace) -> None:
    source = _short_id(path)
    print(f"# following {path}  (Ctrl-C to stop)\n", file=sys.stderr)
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        fh.seek(0, os.SEEK_END)
        while True:
            line = fh.readline()
            if not line:
                time.sleep(0.5)
                continue
            if args.raw:
                if MARKER in line:
                    print(line.rstrip())
                continue
            p = parse_line(line)
            if p and _matches(p, args):
                print(render(p, source, args.color))
                print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, help="specific sentinel.log to read")
    ap.add_argument("--all", action="store_true", help="merge every discovered log (sorted by time)")
    ap.add_argument("--follow", "-f", action="store_true", help="live tail the newest (or --file) log")
    ap.add_argument("--verdict", choices=["continue", "needs_human", "done"], help="only this verdict")
    ap.add_argument("--grep", help="only decisions whose goal/messages/reason contain this text")
    ap.add_argument("--list", action="store_true", help="list discovered sentinel.log files and exit")
    ap.add_argument("--raw", action="store_true", help="print matching raw log lines (no parsing)")
    ap.add_argument("--no-color", dest="color", action="store_false", help="disable ANSI color")
    args = ap.parse_args()
    args.color = getattr(args, "color", True) and sys.stdout.isatty()

    logs = [args.file] if args.file else discover_logs()
    logs = [p for p in logs if p and p.exists()]

    if args.list or not logs:
        if not logs:
            print("No sentinel.log found. Enable it with HIVE_SENTINEL_LOG=1 and restart the runtime.")
            print("Searched roots:", ", ".join(str(b) for b in _candidate_bases()) or "(none existed)")
            return 1
        print("Discovered sentinel logs (newest first):")
        for p in logs:
            mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))
            print(f"  [{_short_id(p)}]  {mtime}  {p}")
        return 0

    if args.follow:
        try:
            _follow(args.file or logs[0], args)
        except KeyboardInterrupt:
            return 0
        return 0

    targets = logs if args.all else [logs[0]]

    # Collect (timestamp, source, payload-or-rawline) across targets, print in order.
    rows: list[tuple[str, str, dict | str]] = []
    for path in targets:
        source = _short_id(path)
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if MARKER not in line:
                    continue
                if args.raw:
                    rows.append((line[:23], source, line.rstrip()))
                    continue
                p = parse_line(line)
                if p and _matches(p, args):
                    rows.append((p.get("_ts", ""), source, p))
    rows.sort(key=lambda r: r[0])

    if not rows:
        print("No matching classify_decision lines.", file=sys.stderr)
        print(
            "If the log exists but is empty of these, the classifier may not have run "
            "(gated earlier), or HIVE_SENTINEL_LOG was off when it did.",
            file=sys.stderr,
        )
        return 0

    misfires = 0
    for _ts, source, payload in rows:
        if args.raw:
            print(payload)
            continue
        if payload.get("verdict") == "continue" and _looks_done(payload.get("last_assistant_text", "")):
            misfires += 1
        print(render(payload, source, args.color))
        print()

    if not args.raw:
        print(f"{_DIM if args.color else ''}{len(rows)} decision(s)"
              f"{f', {misfires} likely misfire(s)' if misfires else ''}."
              f"{_RESET if args.color else ''}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
