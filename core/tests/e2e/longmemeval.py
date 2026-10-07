"""LongMemEval-S, run through the whole system.

Each question's chat history (~48 sessions, ~120k tokens) is written to an
isolated ``HIVE_HOME`` as finished queen sessions, dated with the
benchmark's session dates. A real queen is then booted with its clock
frozen at the question's date and asked the question, as a user would ask
it. Whatever the queen does to answer — ``search_messages`` over those
sessions, or nothing — is the system under test. The reply is graded with
LongMemEval's own per-type judge prompts.

What this measures is Hive's memory as shipped, not a reader model: the
queen never sees the history in its context, only what it retrieves.

Dataset: the 2025 cleaned release of LongMemEval-S
(https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned), fetched
on first use into ``$HIVE_LME_DATA`` (default ``<repo>/.cache/longmemeval``)
and split into one file per question.

Environment:

    HIVE_LME_QUESTIONS    how many / which questions: an integer (stratified
                          by type, deterministic), "all", or comma-separated
                          question ids. Default 12.
    HIVE_LME_QUEEN        queen to ask. Default queen_technology.
    HIVE_LME_JUDGE_MODEL  judge model on the live endpoint. Defaults to the
                          agent model; the paper's judge is gpt-4o.
    HIVE_LME_RUN_DIR      where results go. Default a timestamped directory
                          under ``$HIVE_LME_DATA/runs``.
"""

from __future__ import annotations

import json
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

DATA_URL = "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json"
REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("HIVE_LME_DATA") or REPO_ROOT / ".cache" / "longmemeval")
RAW_FILE = DATA_DIR / "longmemeval_s_cleaned.json"
SPLIT_DIR = DATA_DIR / "s_cleaned"
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


def ensure_split() -> Path:
    """Fetch the dataset if needed and split it into one file per question.

    Tests then read only the questions they run, instead of each loading
    the whole 277 MB file.
    """
    index_path = SPLIT_DIR / "index.json"
    if index_path.is_file():
        return index_path
    if not RAW_FILE.is_file():
        _download(RAW_FILE)
    items = json.loads(RAW_FILE.read_text(encoding="utf-8"))
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    for item in items:
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


async def judge(item: dict[str, Any], response: str, *, api_base: str, api_key: str, model: str) -> Verdict:
    """Grade *response* the way LongMemEval does: ``'yes' in reply.lower()``."""
    body: dict[str, Any] = {"model": model, "messages": [{"role": "user", "content": judge_prompt(item, response)}], "temperature": 0}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{api_base}/chat/completions", json=body, headers={"Authorization": f"Bearer {api_key}"})
        if resp.status_code == 400 and "temperature" in resp.text:
            del body["temperature"]  # reasoning models reject it
            resp = await client.post(f"{api_base}/chat/completions", json=body, headers={"Authorization": f"Bearer {api_key}"})
        resp.raise_for_status()
    raw = (resp.json()["choices"][0]["message"].get("content") or "").strip()
    return Verdict(correct="yes" in raw.lower(), raw=raw, judge_model=model)


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


def record(item: dict[str, Any], run: Any, verdict: Verdict, session_map: dict[str, str]) -> dict[str, Any]:
    """Append one result line and save the transcript. Returns the line."""
    searches = run.called("search_messages")
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
        "searched": bool(searches),
        "search_calls": [c.input for c in searches],
        # Did any evidence session show up in what search returned? Splits
        # "never found it" from "found it and still answered wrong".
        "evidence_retrieved": any(sid in seen for sid in evidence) if evidence else None,
        "tools": [c.name for c in run.tool_calls],
        "seconds": sum(t.seconds for t in run.turns),
    }
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


def summarize(path: Path) -> str:
    """Per-type accuracy, plus how often the queen searched and found the evidence."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return ""

    def pct(n: int, d: int) -> str:
        return f"{100 * n / d:5.1f}%" if d else "    -"

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[r["question_type"]].append(r)
    lines = [
        f"LongMemEval-S through Hive - {len(rows)} question(s), judge {rows[0]['judge_model']}",
        f"{'type':28} {'n':>4} {'correct':>8} {'searched':>9} {'evidence':>9}",
    ]
    for qtype in sorted(groups) + ["ALL"]:
        rs = rows if qtype == "ALL" else groups[qtype]
        found = [r for r in rs if r["evidence_retrieved"] is not None]
        lines.append(
            f"{qtype:28} {len(rs):4} {pct(sum(r['correct'] for r in rs), len(rs)):>8} "
            f"{pct(sum(r['searched'] for r in rs), len(rs)):>9} "
            f"{pct(sum(bool(r['evidence_retrieved']) for r in found), len(found)):>9}"
        )
    abstain = [r for r in rows if r["abstention"]]
    if abstain:
        lines.append(f"abstention questions: {pct(sum(r['correct'] for r in abstain), len(abstain)).strip()} of {len(abstain)}")
    lines.append(f"median seconds per question: {statistics.median(r['seconds'] for r in rows):.0f}")
    lines.append("searched = called search_messages; evidence = an answer session appeared in search results")
    return "\n".join(lines)
