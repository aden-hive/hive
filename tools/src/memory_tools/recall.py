"""Keyword recall over past conversations, for automatic injection.

``search_messages`` answers a pattern the model writes. This module answers
the user's raw message instead: it takes the content words, scores past
turns against them with BM25 over the same mirror cache, and renders the
best few as a short, dated excerpt block. The host injects that block ahead
of each user turn, so related history is in front of the model even when it
doesn't think to search.

A turn is one user message plus the assistant reply that follows it. User
text counts double: it is where the user states facts about themselves,
while replies are long and generic.
"""

from __future__ import annotations

import bisect
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from memory_tools import paths as P
from memory_tools.index import sync_scope

# Question scaffolding and filler that carries no topic. Temporal words are
# here too: "last week" says when, not what, and matches everything.
_STOPWORDS = frozenset(
    """
    a about above after again against all also am an and any are aren around as at be because been before being
    below between both but by can cannot could couldn did didn do does doesn doing don down during each else
    ever every few for from further get gets getting give go going got had has have having he her here hers
    herself him himself his how however i if in into is isn it its itself just know let like ll made make many
    may me might mine more most much must my myself need no nor not now of off on once one only or other ought
    our ours ourselves out over own please re really remind remember said same say see she should so some such
    tell than thank thanks that the their theirs them themselves then there these they thing things think this
    those through to too under until up us use used very want was wasn way we well were weren what whats when
    where which while who whom why will with would yes yet you your yours yourself yourselves
    tip tips recommend recommendation recommendations suggest suggestion suggestions advice idea ideas help
    mention mentioned told talk talked earlier previously before total amount number times time
    today yesterday tomorrow day days week weeks month months year years ago recently recent last past next
    current currently lately now since
    again become becoming bit lot little good great new try trying keep keeping kind sort
    """.split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_FILE_RE = re.compile(r"^(\d{6})\.(user|assistant|tool)\.txt$")
# Chinese and Japanese have no spaces: a run of these characters is cut into overlapping
# two-character terms ("好累啊" -> "好累", "累啊").
_CJK_RUN_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]{2,}")
# Two-character words too common to say what a message is about.
_CJK_STOPWORDS = frozenset(
    """
    什么 怎么 为什么 我们 你们 他们 她们 这个 那个 这样 那样 这些 那些 就是 还是 但是 因为 所以 如果 可以 没有 不是 一下
    一个 已经 现在 今天 时候 知道 觉得 真的 还有 然后 自己 的话 一样 有点 一点 东西 好的 是的 吧吧 了吗 的吗 了吧
    """.split()
)
# The envelope around a message: the time the loop stamps on it ("[2026-10-17 22:47 Pacific
# Daylight Time] "), and a sender a channel puts before it ("[name(id)]: "). They say who and
# when, not what; when a sender header is present, only the text after the last one is used.
_STAMP_RE = re.compile(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}[^\]\n]*\]\s*")
_SENDER_RE = re.compile(r"\[[^\[\]\n]{1,80}\]:\s*")
# Numbers this long are ids (accounts, chats, requests), not topics.
_ID_DIGITS = 5

MAX_TERMS = 12
TOP_K = 6
USER_CHARS = 500
# The reply budget matches the user budget. It used to be 300: narrower, on the
# theory that replies are long and generic. Measured on LongMemEval-S, that cost
# real answers — for questions about what the assistant said, the share of blocks
# carrying every word of the gold answer went 43% -> 60% from centring the window
# on the query (above) and 60% -> 68% from this budget, for ~860 more characters
# per block. 800 would reach 74%, at roughly double that cost.
REPLY_CHARS = 500
# Expansion inside a session that already placed a top hit: how many extra
# turns per session, the overall cap, and the fraction of the best score they
# must still reach. Tuned offline on LongMemEval-S; see _expand_within_sessions.
EXPAND_PER_SESSION = 2
EXPAND_TOTAL = 4
EXPAND_FLOOR = 0.15
_K1, _B = 1.2, 0.75
# Cap on term occurrences scanned when choosing a snippet window; a long reply
# can hold hundreds and the extra ones do not change which window wins.
_MAX_MARKS = 200


@dataclass
class RecalledTurn:
    session: str
    ordinal: int
    user: str
    reply: str
    score: float


def query_terms(text: str) -> list[str]:
    """Content-word stems (matched later as word prefixes) and CJK two-character terms from *text*."""
    text = _STAMP_RE.sub("", text)
    senders = list(_SENDER_RE.finditer(text))
    if senders:
        text = text[senders[-1].end() :]
    terms: list[str] = []
    for token in _TOKEN_RE.findall(text.lower()):
        token = token.split("'")[0]
        if token in _STOPWORDS or (len(token) < 3 and not token.isdigit()) or (token.isdigit() and len(token) >= _ID_DIGITS):
            continue
        stem = _stem(token)
        if stem not in terms:
            terms.append(stem)
    for run in _CJK_RUN_RE.findall(text):
        for i in range(len(run) - 1):
            pair = run[i : i + 2]
            if pair not in _CJK_STOPWORDS and pair not in terms:
                terms.append(pair)
    return terms[:MAX_TERMS]


def _term_pattern(term: str) -> str:
    """Latin terms match at a word start; CJK terms anywhere, since CJK text has no word breaks."""
    return re.escape(term) if _CJK_RUN_RE.fullmatch(term) else r"\b" + re.escape(term)


def _stem(word: str) -> str:
    """Crude suffix strip; prefix matching recovers the inflections."""
    for suffix, min_len in (("ies", 5), ("ing", 6), ("ed", 5), ("es", 6), ("s", 4)):
        if word.endswith(suffix) and len(word) >= min_len and not word.endswith("ss"):
            return word[: -len(suffix)]
    return word


def _candidate_files(root: Path, pattern: str) -> list[Path]:
    """User/assistant message files under *root* containing any query term."""
    if not root.exists():
        return []
    if shutil.which("rg"):
        argv = ["rg", "-l", "-i", "--glob", "*.user.txt", "--glob", "*.assistant.txt", "-e", pattern, str(root)]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode in (0, 1):
            return [Path(line) for line in proc.stdout.splitlines() if line.strip()]
    regex = re.compile(pattern, re.IGNORECASE)
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith((".user.txt", ".assistant.txt")):
                path = Path(dirpath) / name
                if regex.search(path.read_text(encoding="utf-8", errors="replace")):
                    out.append(path)
    return out


def _session_turns(session_dir: Path) -> dict[int, tuple[Path, list[Path]]]:
    """user ordinal → (user file, the assistant files answering it)."""
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


def recall(
    scope: P.Scope,
    owner: str,
    text: str,
    *,
    exclude_session: str | None = None,
    top_k: int = TOP_K,
) -> list[RecalledTurn]:
    """The past turns most related to *text*, best first. ``[]`` when none clear the bar."""
    terms = query_terms(text)
    if not terms:
        return []
    sync_scope(scope, owner)
    root = P.events_index_dir(scope, owner)
    pattern = "(?:" + "|".join(_term_pattern(t) for t in terms) + ")"
    files = _candidate_files(root, pattern)
    if not files:
        return []

    by_session: dict[str, set[Path]] = {}
    for f in files:
        if f.parent.name != exclude_session:
            by_session.setdefault(f.parent.name, set()).add(f)
    term_res = [re.compile(_term_pattern(t), re.IGNORECASE) for t in terms]

    docs: list[tuple[str, int, str, str, list[int]]] = []
    total_turns = 0
    for session_dir in (p for p in root.iterdir() if p.is_dir()):
        turns = _session_turns(session_dir)
        total_turns += len(turns)
        hit_files = by_session.get(session_dir.name)
        if not hit_files:
            continue
        for ordinal, (user_file, reply_files) in turns.items():
            if user_file not in hit_files and not hit_files.intersection(reply_files):
                continue
            user = user_file.read_text(encoding="utf-8", errors="replace")
            reply = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in reply_files)
            tf = [2 * len(r.findall(user)) + len(r.findall(reply)) for r in term_res]
            if any(tf):
                docs.append((session_dir.name, ordinal, user, reply, tf))
    if not docs:
        return []

    n = max(total_turns, len(docs))
    df = [sum(1 for d in docs if d[4][i]) for i in range(len(terms))]
    idf = [math.log(1 + (n - df[i] + 0.5) / (df[i] + 0.5)) for i in range(len(terms))]
    lengths = [len(d[2]) * 2 + len(d[3]) for d in docs]
    avg_len = sum(lengths) / len(lengths)
    rare = max(2, int(0.02 * n))

    scored: list[RecalledTurn] = []
    for (session, ordinal, user, reply, tf), length in zip(docs, lengths, strict=True):
        matched = [i for i in range(len(terms)) if tf[i]]
        # One common word in common is noise; two terms, a rare one, or a
        # one-word query is signal.
        if len(matched) < 2 and len(terms) > 1 and not any(df[i] <= rare for i in matched):
            continue
        norm = _K1 * (1 - _B + _B * length / avg_len)
        score = sum(idf[i] * tf[i] * (_K1 + 1) / (tf[i] + norm) for i in matched)
        scored.append(RecalledTurn(session, ordinal, user, reply, score))
    if not scored:
        return []
    scored.sort(key=lambda t: t.score, reverse=True)
    best = scored[0].score
    primary = [t for t in scored[:top_k] if t.score >= 0.35 * best]
    if not primary:
        return []
    return primary + _expand_within_sessions(scored, primary, best)


def _expand_within_sessions(
    scored: list[RecalledTurn],
    primary: list[RecalledTurn],
    best: float,
) -> list[RecalledTurn]:
    """More turns from the conversations that already placed a top hit.

    A question's evidence is often spread over several turns of one
    conversation — what the user wants, said in turn 1, and the constraint that
    shapes the answer, said in turn 7. The global cut keeps only the single
    best-matching turn of that conversation, so the rest never reaches the
    model. A session that already produced a top hit has proved relevant, so
    its other matching turns clear a lower bar.
    """
    if not EXPAND_TOTAL or not EXPAND_PER_SESSION:
        return []
    hot = {t.session for t in primary}
    seen = {(t.session, t.ordinal) for t in primary}
    added: dict[str, int] = {}
    extra: list[RecalledTurn] = []
    floor = EXPAND_FLOOR * best
    for t in scored:
        if len(extra) >= EXPAND_TOTAL:
            break
        if t.score < floor:
            break  # sorted by score, so nothing further qualifies
        if t.session not in hot or (t.session, t.ordinal) in seen:
            continue
        if added.get(t.session, 0) >= EXPAND_PER_SESSION:
            continue
        extra.append(t)
        seen.add((t.session, t.ordinal))
        added[t.session] = added.get(t.session, 0) + 1
    return extra


def _window_start(text: str, terms: list[str], limit: int) -> int:
    """Where a *limit*-char window should start to carry the most of the query.

    Centering on the first term is wrong when the terms are spread out: a reply
    that opens with one topic word and answers the question 400 characters later
    gets cut before the answer. So consider a window around every occurrence and
    keep the one covering the most distinct terms (then the most occurrences,
    then the earliest).
    """
    marks: list[tuple[int, int]] = []
    for i, term in enumerate(terms):
        for m in re.finditer(_term_pattern(term), text, re.IGNORECASE):
            marks.append((m.start(), i))
            if len(marks) >= _MAX_MARKS:
                break
        if len(marks) >= _MAX_MARKS:
            break
    if not marks:
        return 0
    marks.sort()
    positions = [p for p, _ in marks]
    # Several marks clamp to the same start; score each distinct one once.
    starts = sorted({max(0, min(p - limit // 3, len(text) - limit)) for p in positions})
    best_start, best_key = starts[0], (-1, -1)
    for start in starts:
        lo = bisect.bisect_left(positions, start)
        hi = bisect.bisect_left(positions, start + limit)
        if hi <= lo:
            continue
        window = marks[lo:hi]
        key = (len({i for _, i in window}), len(window))
        if key > best_key:
            best_key, best_start = key, start
    return best_start


def _snippet(text: str, terms: list[str], limit: int) -> str:
    """*text* cut to *limit* chars, on the window carrying the most query terms."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    start = _window_start(text, terms, limit)
    return ("…" if start else "") + text[start : start + limit].strip() + ("…" if start + limit < len(text) else "")


def render(turns: list[RecalledTurn], text: str) -> str | None:
    """The excerpt block, oldest first so dates read as a timeline."""
    if not turns:
        return None
    terms = query_terms(text)
    lines = [
        "Excerpts from earlier conversations that may relate to the user's latest message "
        "(matched by keyword, so possibly incomplete; search_messages and search_timeline go deeper):"
    ]
    for t in sorted(turns, key=lambda t: (t.session, t.ordinal)):
        started = P.parse_session_started_at(t.session)
        when = f"{started:%Y-%m-%d (%a)}" if started else "undated"
        lines.append(f"- {when}, {t.session}")
        lines.append(f"  user: {_snippet(t.user, terms, USER_CHARS)}")
        if t.reply.strip():
            lines.append(f"  you: {_snippet(t.reply, terms, REPLY_CHARS)}")
    return "\n".join(lines)


def recall_block(scope: P.Scope, owner: str, text: str, *, exclude_session: str | None = None) -> str | None:
    """:func:`recall` + :func:`render`; ``None`` when nothing clears the bar."""
    return render(recall(scope, owner, text, exclude_session=exclude_session), text)
