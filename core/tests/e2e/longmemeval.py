"""LongMemEval (S or M), run through the whole system.

Each question's chat history (S: ~48 sessions, ~115k tokens; M: ~476
sessions, ~1.1M tokens in the cleaned release) is written to an
isolated ``HIVE_HOME`` as finished queen sessions, dated with the
benchmark's session dates. A real queen is then booted with its clock
frozen at the question's date and asked the question, as a user would ask
it. Whatever the queen does to answer — ``search_messages`` over those
sessions, or nothing — is the system under test. The reply is graded with
LongMemEval's own per-type judge prompts.

What this measures is Hive's memory as shipped, not a reader model: the
queen never sees the history in its context, only what it retrieves.

Dataset: the 2025 cleaned release of LongMemEval S or M
(https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned), fetched
on first use into ``$HIVE_LME_DATA`` (default ``<repo>/.cache/longmemeval``)
and split into one file per question.

Environment:

    HIVE_LME_DATASET      "s" (default) or "m".
    HIVE_LME_RESUME       "1" to skip questions already in HIVE_LME_RUN_DIR.
    HIVE_LME_QUESTIONS    how many / which questions: an integer (stratified
                          by type, deterministic), "all", or comma-separated
                          question ids. Default 12.
    HIVE_LME_QUEEN        queen to ask. Default queen_technology.
    HIVE_LME_JUDGE_MODEL  judge model. Defaults to the agent model. Published
                          scores use gpt-4o-2024-08-06 (OFFICIAL_JUDGE_MODEL),
                          which also gets the official 10-token cap.
    HIVE_LME_JUDGE_API_BASE / HIVE_LME_JUDGE_API_KEY
                          judge endpoint and key, if not the agent's.
    HIVE_LME_RUN_DIR      where results go. Default a timestamped directory
                          under ``$HIVE_LME_DATA/runs``.

Comparable to published numbers (the queen and the judge both gpt-4o, on
the OpenAI API): set HIVE_LIVE_API_BASE=https://api.openai.com/v1,
HIVE_LIVE_API_KEY, HIVE_LIVE_MODEL=gpt-4o-2024-08-06 and the same three for
the judge. Reference points and re-grading, outside pytest:

    python -m tests.e2e.longmemeval rejudge <run dir>         # official judge
    python -m tests.e2e.longmemeval reference oracle --out <dir>  # answer sessions only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import re
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from tests.e2e import synthetic

# "s": ~115k tokens of history per question, fits a large context window.
# "m": ~1.1M tokens per question (~476 sessions, measured; the paper
# describes ~1.5M and ~500), fits none: the condition
# a memory system exists for.
VARIANT = os.environ.get("HIVE_LME_DATASET", "s").strip().lower()
if VARIANT not in ("s", "m"):
    raise ValueError(f"HIVE_LME_DATASET must be 's' or 'm', got {VARIANT!r}")
LABEL = f"LongMemEval-{VARIANT.upper()}"
DATA_URL = f"https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_{VARIANT}_cleaned.json"
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("HIVE_LME_DATA") or REPO_ROOT / ".cache" / "longmemeval")
RAW_FILE = DATA_DIR / f"longmemeval_{VARIANT}_cleaned.json"
SPLIT_DIR = DATA_DIR / f"{VARIANT}_cleaned"
QUEEN_ID = os.environ.get("HIVE_LME_QUEEN", "queen_technology")

# The modules whose ``datetime.now()`` tells the queen what time it is: the
# system-prompt date, the ``[YYYY-MM-DD HH:MM TZ]`` stamps on injected
# messages, and the get_current_time tool.
_CLOCK_MODULES = (
    "framework.agent_loop.prompting",
    "framework.orchestrator.prompting",
    "framework.agent_loop.agent_loop",
    "framework.agent_loop.internals.cursor_persistence",
    "aden_tools.tools.time_tool.time_tool",
)


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


def _download(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", DATA_URL, follow_redirects=True, timeout=httpx.Timeout(60, read=600)) as resp:
        resp.raise_for_status()
        with part.open("wb") as fh:
            for chunk in resp.iter_bytes(1 << 20):
                fh.write(chunk)
    part.replace(dest)


def _iter_json_array(path: Path, chunk_chars: int = 1 << 22) -> Any:
    """Yield the elements of a top-level JSON array without loading it whole.

    The M release is 2.7 GB; ``json.loads`` on it needs several times that
    in memory. Elements (one question each, a few MB) are decoded one at a
    time as enough of the file has been read to hold them.
    """
    decoder = json.JSONDecoder()
    buf = ""
    pos = 0
    started = False
    eof = False
    with path.open(encoding="utf-8") as fh:
        while True:
            # Skip whitespace, the opening bracket and separating commas.
            while pos < len(buf) and buf[pos] in " \t\r\n,[":
                started = started or buf[pos] == "["
                pos += 1
            if pos < len(buf) and buf[pos] == "]" and started:
                return  # the only way to finish: a partial file must not split
            try:
                if pos >= len(buf):
                    raise ValueError("need more data")
                value, end = decoder.raw_decode(buf, pos)
            except ValueError:
                if eof:
                    # Out of data before the closing bracket (or mid-element):
                    # a download cut short, not a smaller dataset.
                    raise ValueError(f"truncated JSON array in {path}") from None
                chunk = fh.read(chunk_chars)
                eof = not chunk
                buf = buf[pos:] + chunk
                pos = 0
                continue
            if not started:
                raise ValueError(f"{path} does not hold a JSON array")
            yield value
            pos = end


def ensure_split() -> Path:
    """Fetch the dataset if needed and split it into one file per question.

    Tests then read only the questions they run, instead of each loading
    the whole file (277 MB for S, 2.7 GB for M).
    """
    index_path = SPLIT_DIR / "index.json"
    if index_path.is_file():
        return index_path
    if not RAW_FILE.is_file():
        _download(RAW_FILE)
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    for item in _iter_json_array(RAW_FILE):
        (SPLIT_DIR / f"{item['question_id']}.json").write_text(json.dumps(item), encoding="utf-8")
        index.append(
            {
                "question_id": item["question_id"],
                "question_type": item["question_type"],
                "question_date": item["question_date"],
                "sessions": len(item["haystack_sessions"]),
            }
        )
    tmp = index_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=1), encoding="utf-8")
    tmp.replace(index_path)
    return index_path


def load_index() -> list[dict[str, Any]]:
    return json.loads(ensure_split().read_text(encoding="utf-8"))


def load_question(question_id: str) -> dict[str, Any]:
    ensure_split()
    return json.loads((SPLIT_DIR / f"{question_id}.json").read_text(encoding="utf-8"))


def select(index: list[dict[str, Any]], spec: str) -> list[str]:
    """Question ids for *spec*: ``"all"``, comma-separated ids, or a count.

    A count is split across question types in proportion to the full
    benchmark (largest remainder, at least one per type), so a sample's
    overall accuracy estimates the full run's. Deterministic.
    """
    spec = spec.strip()
    if spec.lower() == "all":
        return [q["question_id"] for q in index]
    if not spec.isdigit():
        wanted = [s.strip() for s in spec.split(",") if s.strip()]
        known = {q["question_id"] for q in index}
        unknown = [w for w in wanted if w not in known]
        if unknown:
            raise ValueError(f"unknown LongMemEval question ids: {unknown}")
        return wanted

    count = min(int(spec), len(index))
    by_type: dict[str, list[str]] = defaultdict(list)
    for q in index:
        by_type[q["question_type"]].append(q["question_id"])
    types = sorted(by_type)
    if count < len(types):
        types = types[:count]
    share = {t: count * len(by_type[t]) / len(index) for t in types}
    alloc = {t: max(1, int(share[t])) for t in types}
    # Leftover slots go to whoever is furthest below their share; a type
    # lifted to its one-slot minimum is already at or above it.
    for t in sorted(types, key=lambda t: share[t] - alloc[t], reverse=True):
        if sum(alloc.values()) >= count:
            break
        alloc[t] += 1
    while sum(alloc.values()) > count:
        alloc[max(alloc, key=alloc.__getitem__)] -= 1

    rng = random.Random(0)
    chosen: list[str] = []
    for t in types:
        ids = sorted(by_type[t])
        rng.shuffle(ids)
        chosen.extend(ids[: alloc[t]])
    return chosen


# ---------------------------------------------------------------------------
# Seeding and the clock
# ---------------------------------------------------------------------------


def parse_date(text: str) -> datetime:
    """``"2023/05/30 (Tue) 23:40"`` → naive local datetime.

    The weekday is dropped before parsing: ``%a`` is locale-dependent.
    """
    return datetime.strptime(re.sub(r"\s*\([^)]*\)\s*", " ", text).strip(), "%Y/%m/%d %H:%M")


def seed_haystack(hive_home: Path, item: dict[str, Any], queen_id: str = QUEEN_ID) -> dict[str, str]:
    """Write the question's history as finished queen sessions.

    Returns LongMemEval session id → Hive session id, so a result can say
    whether the evidence sessions were among what the queen retrieved.
    """
    mapping: dict[str, str] = {}
    for lme_id, date, turns in zip(item["haystack_session_ids"], item["haystack_dates"], item["haystack_sessions"], strict=True):
        pairs = [(t["role"], t["content"]) for t in turns if t.get("content")]
        if pairs:
            mapping[lme_id] = synthetic.past_session(hive_home, queen_id, started_at=parse_date(date), turns=pairs)
    return mapping


async def build_timelines(hive_home: Path, *, api_base: str, api_key: str, model: str, queen_id: str = QUEEN_ID) -> int:
    """Extract the seeded sessions' timelines, as production would have when they happened.

    Cached by session content under ``$HIVE_LME_DATA/timeline_cache/<model>``,
    so only the first run over a session pays for the extraction.
    """
    from framework.agents.queen.timeline import backfill_timelines
    from framework.llm.litellm import LiteLLMProvider

    llm = LiteLLMProvider(model=f"openai/{model}", api_key=api_key, api_base=api_base)
    return await backfill_timelines(
        llm,
        hive_home / "queens" / queen_id / "sessions",
        cache_dir=DATA_DIR / "timeline_cache" / re.sub(r"[^\w.-]", "_", model),
        concurrency=int(os.environ.get("HIVE_LME_TIMELINE_CONCURRENCY", "4")),
    )


def warm_index(queen_id: str = QUEEN_ID) -> None:
    """Sync the seeded sessions into the memory index before the queen boots.

    In production the index catches up a little on every search, so it is
    warm by the time the user asks. Seeding hundreds of sessions at once and
    then asking would charge that whole catch-up to the first turn, past the
    automatic recall's time cap, and understate what Hive does.
    """
    from memory_tools.index import sync_scope

    sync_scope("queens", queen_id)


def read_results(path: Path) -> list[dict[str, Any]]:
    """Rows of a results file, repairing a tail left by an interrupted write.

    A run killed mid-append can leave a truncated last line. Skipping it is
    not enough: the next append would continue that line and corrupt the new
    row too. So the file is cut back to the end of the last complete row.
    """
    if not path.is_file():
        return []
    data = path.read_bytes()
    rows: list[dict[str, Any]] = []
    good_end = 0
    pos = 0
    for raw in data.splitlines(keepends=True):
        pos += len(raw)
        line = raw.strip()
        if not line:
            good_end = pos
            continue
        try:
            row = json.loads(line)
        except ValueError:
            break
        if not raw.endswith(b"\n"):
            break  # parses, but the write may have stopped mid-line
        rows.append(row)
        good_end = pos
    if good_end < len(data):
        with path.open("r+b") as fh:
            fh.truncate(good_end)
    return rows


def done_ids() -> set[str]:
    """Question ids already recorded in this run, for HIVE_LME_RESUME."""
    return {r["question_id"] for r in read_results(run_dir() / "results.jsonl")}


def freeze_clock(monkeypatch: Any, when: datetime) -> None:
    """Make the queen believe it is *when* (naive local time)."""
    import importlib

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206 - mirrors datetime.now
            return when if tz is None else when.astimezone(tz)

    patched = []
    for name in _CLOCK_MODULES:
        module = importlib.import_module(name)
        if getattr(module, "datetime", None) is datetime:
            monkeypatch.setattr(module, "datetime", _Frozen)
            patched.append(name)
    if "framework.agent_loop.prompting" not in patched:
        raise RuntimeError(f"could not freeze the queen's prompt date; patched only {patched}")


# ---------------------------------------------------------------------------
# Judging and results
# ---------------------------------------------------------------------------

# Verbatim from LongMemEval's src/evaluation/evaluate_qa.py.
_STANDARD = (
    "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response "
    "contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or "
    "contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only "
    "contains a subset of the information required by the answer, answer no. "
)
_ANSWER_TAIL = "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
_TEMPLATES = {
    "single-session-user": _STANDARD + _ANSWER_TAIL,
    "single-session-assistant": _STANDARD + _ANSWER_TAIL,
    "multi-session": _STANDARD + _ANSWER_TAIL,
    "temporal-reasoning": _STANDARD + "In addition, do not penalize off-by-one errors for the number of days. If the question asks for the number of "
    "days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when the answer is 18), "
    "the model's response is still correct. " + _ANSWER_TAIL,
    "knowledge-update": "I will give you a question, a correct answer, and a response from a model. Please answer yes if "
    "the response contains the correct answer. Otherwise, answer no. If the response contains some previous "
    "information along with an updated answer, the response should be considered as correct as long as the updated "
    "answer is the required answer." + _ANSWER_TAIL,
    "single-session-preference": "I will give you a question, a rubric for desired personalized response, and a "
    "response from a model. Please answer yes if the response satisfies the desired response. Otherwise, answer no. "
    "The model does not need to reflect all the points in the rubric. The response is correct as long as it recalls "
    "and utilizes the user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\n"
    "Is the model response correct? Answer yes or no only.",
}
_ABSTENTION = (
    "I will give you an unanswerable question, an explanation, and a response from a model. Please answer yes if the "
    "model correctly identifies the question as unanswerable. The model could say that the information is incomplete, "
    "or some other information is given but the asked information is not.\n\nQuestion: {}\n\nExplanation: {}\n\nModel "
    "Response: {}\n\nDoes the model correctly identify the question as unanswerable? Answer yes or no only."
)


@dataclass(frozen=True)
class Verdict:
    correct: bool
    raw: str
    judge_model: str


def judge_prompt(item: dict[str, Any], response: str) -> str:
    template = _ABSTENTION if "_abs" in item["question_id"] else _TEMPLATES[item["question_type"]]
    return template.format(item["question"], item["answer"], response)


# The judge every published LongMemEval score uses, with the official
# script's settings (src/evaluation/evaluate_qa.py: temperature 0, 10 tokens).
OFFICIAL_JUDGE_MODEL = "gpt-4o-2024-08-06"
OFFICIAL_JUDGE_MAX_TOKENS = 10


async def _chat(api_base: str, api_key: str, body: dict[str, Any], *, timeout: float = 300) -> str:
    """One chat completion; retries rate limits and transient server errors."""
    delay = 2.0
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(8):
            resp = await client.post(f"{api_base}/chat/completions", json=body, headers={"Authorization": f"Bearer {api_key}"})
            if resp.status_code == 400 and "temperature" in resp.text and "temperature" in body:
                body = {k: v for k, v in body.items() if k != "temperature"}  # reasoning models reject it
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 7:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            resp.raise_for_status()
            return (resp.json()["choices"][0]["message"].get("content") or "").strip()
    raise RuntimeError("unreachable")


async def judge(
    item: dict[str, Any],
    response: str,
    *,
    api_base: str,
    api_key: str,
    model: str,
    max_tokens: int | None = None,
) -> Verdict:
    """Grade *response* the way LongMemEval does: ``'yes' in reply.lower()``.

    Pass ``max_tokens=OFFICIAL_JUDGE_MAX_TOKENS`` with the official judge;
    leave it unset for reasoning models, which need room to think.
    """
    body: dict[str, Any] = {"model": model, "messages": [{"role": "user", "content": judge_prompt(item, response)}], "temperature": 0}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    raw = await _chat(api_base, api_key, body)
    return Verdict(correct="yes" in raw.lower(), raw=raw, judge_model=model)


# ---------------------------------------------------------------------------
# Reference points outside Hive: the official reader on a given history
# ---------------------------------------------------------------------------

# Verbatim from LongMemEval's src/generation/run_generation.py (history_format
# "json", cot "true"): the official way to have a model answer from history it
# is handed directly.
_READER_PROMPT = (
    "I will give you several history chats between you and a user. Please answer the question based on the relevant "
    "chat history. Answer the question step by step: first extract all the relevant information, and then reason over "
    "the information to get the answer.\n\n\nHistory Chats:\n\n{}\n\nCurrent Date: {}\nQuestion: {}\nAnswer (step by step):"
)


def reader_prompt(item: dict[str, Any], *, oracle: bool) -> str:
    """The official reading prompt over the answer sessions (*oracle*) or the whole history."""
    chosen = set(item["answer_session_ids"]) if oracle else None
    sessions = sorted(
        (
            (date, turns)
            for sid, date, turns in zip(item["haystack_session_ids"], item["haystack_dates"], item["haystack_sessions"], strict=True)
            if chosen is None or sid in chosen
        ),
        key=lambda s: s[0],  # the official script sorts by date only
    )
    # The official json format: "\n" + json.dumps(session) as the content.
    history = "".join(
        f"\n### Session {i}:\nSession Date: {date}\nSession Content:\n\n{json.dumps(turns)}\n" for i, (date, turns) in enumerate(sessions, 1)
    )
    return _READER_PROMPT.format(history, item["question_date"], item["question"])


_SPILL_RE = re.compile(r"Full result at: (.+?\.txt)")


def _full_result(result: Any) -> str:
    """A tool result's whole text, following the pointer when it was spilled.

    Results too large for context reach the event stream as a short note
    naming the file that holds them; the session ids are in that file.
    """
    text = str(result or "")
    match = _SPILL_RE.search(text)
    if match:
        path = Path(match.group(1).strip())
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    return text


def run_dir() -> Path:
    path = Path(os.environ.get("HIVE_LME_RUN_DIR") or DATA_DIR / "runs" / "adhoc")
    path.mkdir(parents=True, exist_ok=True)
    return path


def record(
    item: dict[str, Any],
    run: Any,
    verdict: Verdict,
    session_map: dict[str, str],
    *,
    reader_model: str | None = None,
    judge_error: BaseException | None = None,
) -> dict[str, Any]:
    """Append one result line and save the transcript. Returns the line.

    With *judge_error* the answer is kept but marked ungraded (counted wrong
    until ``rejudge`` grades it).
    """
    searches = run.called("search_messages") + run.called("search_timeline")
    seen = " ".join(_full_result(c.result) for c in searches)
    abstention = "_abs" in item["question_id"]
    # Abstention questions have no evidence to find: their answer sessions
    # hold the near-miss the question is built around.
    evidence = [] if abstention else [session_map[s] for s in item["answer_session_ids"] if s in session_map]
    line = {
        "question_id": item["question_id"],
        "question_type": item["question_type"],
        "abstention": abstention,
        "question": item["question"],
        "answer": item["answer"],
        "hypothesis": run.text,
        "correct": verdict.correct,
        "judge": verdict.raw,
        "judge_model": verdict.judge_model,
        "reader_model": reader_model,
        "searched": bool(searches),
        "search_calls": [{"tool": c.name, **c.input} for c in searches],
        # Did any evidence session show up in what search returned? Splits
        # "never found it" from "found it and still answered wrong".
        "evidence_retrieved": any(sid in seen for sid in evidence) if evidence else None,
        "tools": [c.name for c in run.tool_calls],
        "seconds": sum(t.seconds for t in run.turns),
    }
    if judge_error is not None:
        line["judge_error"] = f"{type(judge_error).__name__}: {judge_error}"[:500]
    out = run_dir()
    with (out / "results.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, default=str) + "\n")
    transcripts = out / "transcripts"
    transcripts.mkdir(exist_ok=True)
    (transcripts / f"{item['question_id']}.json").write_text(
        json.dumps({"result": line, "turns": [asdict(t) for t in run.turns]}, indent=2, default=str),
        encoding="utf-8",
    )
    return line


def record_error(item: dict[str, Any], exc: BaseException) -> None:
    """Append a miss for a question that never got a gradable answer."""
    line = {
        "question_id": item["question_id"],
        "question_type": item["question_type"],
        "abstention": "_abs" in item["question_id"],
        "question": item["question"],
        "answer": item["answer"],
        "hypothesis": "",
        "correct": False,
        "judge": "",
        "judge_model": "",
        "searched": False,
        "search_calls": [],
        "evidence_retrieved": None,
        "tools": [],
        "seconds": 0,
        "error": f"{type(exc).__name__}: {exc}"[:500],
    }
    with (run_dir() / "results.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, default=str) + "\n")


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for k successes out of n."""
    if not n:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def summarize(path: Path, *, title: str = f"{LABEL} through Hive") -> str:
    """Accuracy overall (with a 95% CI) and averaged over types, per type, and retrieval diagnostics.

    "Overall" is the share of all questions answered correctly, as the
    official script and most products report it; "task-averaged" is the
    unweighted mean of the six type scores, which some (Mastra) report.
    """
    rows = read_results(path)
    if not rows:
        return ""

    def pct(n: int, d: int) -> str:
        return f"{100 * n / d:5.1f}%" if d else "    -"

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[r["question_type"]].append(r)
    judge_model = next((r["judge_model"] for r in rows if r.get("judge_model")), "?")
    reader = next((r["reader_model"] for r in rows if r.get("reader_model")), None)
    correct = sum(r["correct"] for r in rows)
    lo, hi = _wilson(correct, len(rows))
    task_avg = statistics.mean(sum(r["correct"] for r in rs) / len(rs) for rs in groups.values())
    # Retrieval diagnostics exist only for runs through Hive, not reference runs.
    hive_run = any("searched" in r for r in rows)
    lines = [
        f"{title} - {len(rows)} question(s), {f'reader {reader}, ' if reader else ''}judge {judge_model}",
        f"overall {100 * correct / len(rows):.1f}% (95% CI {100 * lo:.1f}-{100 * hi:.1f}), task-averaged {100 * task_avg:.1f}%",
        f"{'type':28} {'n':>4} {'correct':>8}" + (f" {'searched':>9} {'evidence':>9}" if hive_run else ""),
    ]
    for qtype in sorted(groups) + ["ALL"]:
        rs = rows if qtype == "ALL" else groups[qtype]
        found = [r for r in rs if r.get("evidence_retrieved") is not None]
        line = f"{qtype:28} {len(rs):4} {pct(sum(r['correct'] for r in rs), len(rs)):>8}"
        if hive_run:
            line += (
                f" {pct(sum(bool(r.get('searched')) for r in rs), len(rs)):>9}"
                f" {pct(sum(bool(r['evidence_retrieved']) for r in found), len(found)):>9}"
            )
        lines.append(line)
    abstain = [r for r in rows if r["abstention"]]
    if abstain:
        lines.append(f"abstention questions: {pct(sum(r['correct'] for r in abstain), len(abstain)).strip()} of {len(abstain)}")
    errors = [r for r in rows if r.get("error")]
    if errors:
        lines.append(f"no gradable answer (timeout/error, counted wrong): {len(errors)}")
    ungraded = [r for r in rows if r.get("judge_error")]
    if ungraded:
        lines.append(f"answered but not graded (judge failed; counted wrong until `rejudge`): {len(ungraded)}")
    seconds = [r["seconds"] for r in rows if r.get("seconds") is not None]
    if seconds:
        lines.append(f"median seconds per question: {statistics.median(seconds):.0f}")
    if hive_run:
        lines.append(
            "searched = called search_messages or search_timeline; evidence = an answer session appeared in their results "
            "(auto-injected excerpts don't count, so 'correct' can exceed both)"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI: re-grade a saved run, or run the official reader as a reference point
# ---------------------------------------------------------------------------


async def _gather_limited(coros: list[Any], limit: int) -> list[Any]:
    gate = asyncio.Semaphore(limit)

    async def run(coro: Any) -> Any:
        async with gate:
            return await coro

    return await asyncio.gather(*(run(c) for c in coros))


async def rejudge(run: Path, *, api_base: str, api_key: str, model: str, max_tokens: int | None, concurrency: int) -> Path:
    """Re-grade every saved answer in *run* with another judge. Returns the new results file.

    A judge call that still fails after retries keeps its row, marked with
    ``judge_error`` and counted wrong, so the other grades aren't lost and a
    second ``rejudge`` can finish the job.
    """
    rows = read_results(run / "results.jsonl")
    safe_model = re.sub(r"[^\w.-]", "_", model)
    out = run / f"rejudged-{safe_model}"
    out.mkdir(exist_ok=True)

    async def one(row: dict[str, Any]) -> dict[str, Any]:
        if row.get("error"):
            return {**row, "judge_model": model}  # no answer to grade; stays wrong
        row = {k: v for k, v in row.items() if k != "judge_error"}  # graded now
        item = load_question(row["question_id"])
        try:
            verdict = await judge(item, row["hypothesis"], api_base=api_base, api_key=api_key, model=model, max_tokens=max_tokens)
        except Exception as exc:
            return {**row, "correct": False, "judge": "", "judge_model": model, "judge_error": f"{type(exc).__name__}: {exc}"[:500]}
        return {**row, "correct": verdict.correct, "judge": verdict.raw, "judge_model": model, "original_judge": row.get("judge_model")}

    graded = await _gather_limited([one(r) for r in rows], concurrency)
    path = out / "results.jsonl"
    path.write_text("".join(json.dumps(r, default=str) + "\n" for r in graded), encoding="utf-8")
    return path


async def reference_run(
    ids: list[str],
    out: Path,
    *,
    oracle: bool,
    reader: tuple[str, str, str],
    judge_with: tuple[str, str, str, int | None],
    concurrency: int,
) -> Path:
    """The official reader on the answer sessions (*oracle*) or the whole history, graded by the judge.

    Each result is appended as soon as it is graded, and questions already in
    the results file are skipped, so a stopped run resumes without paying twice.
    """
    reader_base, reader_key, reader_model = reader
    judge_base, judge_key, judge_model, judge_max = judge_with
    out.mkdir(parents=True, exist_ok=True)
    path = out / "results.jsonl"
    done = {r["question_id"] for r in read_results(path)}

    async def one(qid: str) -> None:
        item = load_question(qid)
        body = {"model": reader_model, "messages": [{"role": "user", "content": reader_prompt(item, oracle=oracle)}], "temperature": 0}
        error = judge_error = None
        verdict = Verdict(correct=False, raw="", judge_model=judge_model)
        try:
            hypothesis = await _chat(reader_base, reader_key, body)
        except Exception as exc:  # e.g. a whole-history prompt over the context window
            # No answer: counted wrong, like an unanswered question in a Hive run.
            hypothesis, error = "", f"{type(exc).__name__}: {exc}"[:500]
        else:
            try:
                verdict = await judge(item, hypothesis, api_base=judge_base, api_key=judge_key, model=judge_model, max_tokens=judge_max)
            except Exception as exc:
                # The answer exists: keep it for `rejudge`, counted wrong until then.
                judge_error = f"{type(exc).__name__}: {exc}"[:500]
        row = {
            "question_id": qid,
            "question_type": item["question_type"],
            "abstention": "_abs" in qid,
            "question": item["question"],
            "answer": item["answer"],
            "hypothesis": hypothesis,
            "correct": verdict.correct,
            "judge": verdict.raw,
            "judge_model": judge_model,
            "reader_model": reader_model,
            "condition": "oracle" if oracle else "full-history",
        }
        if error:
            row["error"] = error
        if judge_error:
            row["judge_error"] = judge_error
        with path.open("a", encoding="utf-8") as fh:  # single-threaded event loop: no interleaving
            fh.write(json.dumps(row, default=str) + "\n")

    await _gather_limited([one(q) for q in ids if q not in done], concurrency)
    return path


def _main() -> None:
    parser = argparse.ArgumentParser(prog="python -m tests.e2e.longmemeval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rj = sub.add_parser("rejudge", help="re-grade a saved run with another judge (default: the official one)")
    rj.add_argument("run", type=Path)
    ref = sub.add_parser("reference", help="the official reader on the answer sessions or the whole history")
    ref.add_argument("condition", choices=["oracle", "full-history"])
    ref.add_argument("--out", type=Path, required=True)
    ref.add_argument("--questions", default="all")
    ref.add_argument("--reader-model", default=OFFICIAL_JUDGE_MODEL)
    ref.add_argument("--reader-api-base", default="https://api.openai.com/v1")
    for p in (rj, ref):
        p.add_argument("--judge-model", default=OFFICIAL_JUDGE_MODEL)
        p.add_argument("--judge-api-base", default="https://api.openai.com/v1")
        p.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    key = os.environ.get("HIVE_LME_JUDGE_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    judge_max = OFFICIAL_JUDGE_MAX_TOKENS if args.judge_model == OFFICIAL_JUDGE_MODEL else None
    if args.cmd == "rejudge":
        path = asyncio.run(
            rejudge(args.run, api_base=args.judge_api_base, api_key=key, model=args.judge_model, max_tokens=judge_max, concurrency=args.concurrency)
        )
        title = f"{LABEL} through Hive (re-graded)"
    else:
        reader_key = os.environ.get("HIVE_LME_READER_API_KEY") or key
        ids = select(load_index(), args.questions)
        path = asyncio.run(
            reference_run(
                ids,
                args.out,
                oracle=args.condition == "oracle",
                reader=(args.reader_api_base, reader_key, args.reader_model),
                judge_with=(args.judge_api_base, key, args.judge_model, judge_max),
                concurrency=args.concurrency,
            )
        )
        title = f"{LABEL}, official reader, {args.condition}"
    report = summarize(path, title=title)
    (path.parent / "summary.txt").write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    _main()
