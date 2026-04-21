"""Cross-session failure memory for the agent event loop.

Records judge-rejected outputs and silent failures to a persistent JSONL store,
then retrieves task-relevant past failures at session start and injects them
into the Layer 2 (narrative) section of the system prompt.

After N matching failures of the same pattern, a deterministic EvaluationRule
is proposed to ``rule_proposals.json`` for human review.

Design constraints (matching stall_detector.py conventions):
- Pure functions with no class dependencies — safe to call from any context.
- Async I/O is delegated to ``asyncio.to_thread`` so the event loop is never
  blocked by disk writes.
- All persistence paths live under ``~/.hive/`` by default and are
  configurable via ``HIVE_FAILURE_MEMORY_DIR``.
- All thresholds are ENV-configurable (see _env_int/_env_float helpers).

Concurrency model
-----------------
New records use append-only writes (safe for concurrent agents).
Upserts (incrementing occurrence_count) require a read-modify-write cycle;
this is protected by a per-directory threading.Lock held for the full
critical section.  Separate processes are coordinated by the same advisory
file lock used during append.  This gives correct behaviour for the common
case (multiple async tasks in one process) and best-effort safety for the
rare case (multiple processes sharing one store).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import random
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

# Ensure this module has a stable name in sys.modules so dataclass
# introspection works regardless of how the module is loaded.
if __name__ == "__main__" or __name__ not in sys.modules:
    sys.modules.setdefault("framework.agent_loop.internals.failure_memory", sys.modules[__name__])

# ---------------------------------------------------------------------------
# Cross-platform file locking
# ---------------------------------------------------------------------------
# fcntl is Unix-only.  On Windows we fall back to msvcrt.locking (advisory).
# TODO: replace both with `filelock` once it lands in project dependencies.

if sys.platform == "win32":  # pragma: no cover
    import msvcrt

    def _lock_file(fh: Any) -> None:  # type: ignore[misc]
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            pass

    def _unlock_file(fh: Any) -> None:  # type: ignore[misc]
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def _lock_file(fh: Any) -> None:
        fcntl.flock(fh, fcntl.LOCK_EX)

    def _unlock_file(fh: Any) -> None:
        fcntl.flock(fh, fcntl.LOCK_UN)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-directory threading locks  (fix #1 — concurrency safety)
# ---------------------------------------------------------------------------
# One Lock per memory directory eliminates read-modify-write races when
# multiple async tasks run in the same process.

_DIR_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_MUTEX = threading.Lock()


def _dir_lock(memory_dir: Path) -> threading.Lock:
    key = str(memory_dir.resolve())
    with _LOCKS_MUTEX:
        if key not in _DIR_LOCKS:
            _DIR_LOCKS[key] = threading.Lock()
        return _DIR_LOCKS[key]


# ---------------------------------------------------------------------------
# Configuration  (fix #10 — ENV-configurable thresholds)
# ---------------------------------------------------------------------------

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


_DEFAULT_MEMORY_DIR = Path.home() / ".hive" / "failure_memory"
_MEMORY_FILE = "failures.jsonl"
_RULE_PROPOSALS_FILE = "rule_proposals.json"

_TASK_SIMILARITY_THRESHOLD: float = _env_float("HIVE_FM_SIMILARITY_THRESHOLD", 0.30)
_RULE_PROPOSAL_THRESHOLD: int   = _env_int("HIVE_FM_RULE_THRESHOLD", 3)
_MIN_OCCURRENCES_TO_STORE: int  = _env_int("HIVE_FM_MIN_OCCURRENCES", 1)   # fix #6 — noise gate
_MAX_RETRIEVED: int             = _env_int("HIVE_FM_MAX_RETRIEVED", 3)
_MAX_RECORD_AGE_SECONDS: int    = _env_int("HIVE_FM_MAX_AGE_DAYS", 30) * 24 * 3600
_COMPACT_ON_RETRIEVE_PROB: float = _env_float("HIVE_FM_COMPACT_PROB", 0.05)  # fix #2

_SILENT_FAILURE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*$"),
    re.compile(r"^(n/?a|none|null|undefined)\s*$", re.I),
    re.compile(r"^(not found|no results?|nothing)\s*$", re.I),
    re.compile(r"^(error|failed|failure)\s*$", re.I),
    re.compile(r"^\[.{0,30}\]$"),
    re.compile(r"^<.{0,30}>$"),
]

_SILENT_FAILURE_MIN_LEN = 3
_SILENT_FAILURE_MAX_LEN = 50

# fix #7 — strip prompt-injection anchors before storing / injecting
_PROMPT_UNSAFE_RE = re.compile(r"[<>{}\[\]`\\]|system:|assistant:|human:", re.I)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

FailureType = Literal["silent_failure", "tool_failure", "logic_failure", "unknown"]  # fix #4


@dataclass
class FailureRecord:
    """A single persisted failure event."""

    record_id: str
    task_type: str
    pattern_key: str
    judge_feedback: str
    output_sample: str
    iteration: int
    failure_type: FailureType = "unknown"          # fix #4
    timestamp: float = field(default_factory=time.time)
    occurrence_count: int = 1
    proposed_rule: bool = False


@dataclass
class RuleProposal:
    """A proposed EvaluationRule derived from repeated judge rejections."""

    proposal_id: str
    task_type: str
    pattern_key: str
    failure_type: FailureType                       # fix #4
    occurrence_count: int
    proposed_condition: str
    proposed_action: str
    rationale: str
    examples: list[str]
    created_at: float = field(default_factory=time.time)
    approved: bool = False
    approved_at: float | None = None


# ---------------------------------------------------------------------------
# Silent failure detection  (pure, synchronous)
# ---------------------------------------------------------------------------

def is_silent_failure(output: dict[str, Any]) -> tuple[bool, str]:
    """Detect whether an ACCEPT-ed output is semantically empty or useless.

    Silent failure detection exists because the judge's structural checks
    (e.g. required keys are present) can pass even when all field values
    are empty strings, None, or placeholder patterns like "N/A".  Without
    this check, the agent loop would accept outputs that look complete but
    carry no real information, effectively silently failing the task.

    Returns (True, reason) when a silent failure is detected, (False, "") otherwise.
    """
    if not output:
        return True, "output dict is empty — agent produced no values"

    flagged: list[str] = []
    substantive_seen = False

    for key, value in output.items():
        if value is None:
            flagged.append(f"key '{key}' is None")
            continue
        val_str = str(value).strip()
        if len(val_str) < _SILENT_FAILURE_MIN_LEN:
            flagged.append(f"key '{key}' suspiciously short ({len(val_str)} chars)")
            continue
        matched_placeholder = False
        for pat in _SILENT_FAILURE_PATTERNS:
            if pat.search(val_str):
                flagged.append(f"key '{key}' matches placeholder: {val_str!r:.60}")
                matched_placeholder = True
                break
        if not matched_placeholder:
            # At least one field has real, substantive content — not a silent failure.
            substantive_seen = True

    if substantive_seen:
        return False, ""
    return (True, "; ".join(flagged)) if flagged else (False, "")


def classify_failure(judge_feedback: str, output: dict[str, Any]) -> FailureType:
    """Classify failure into a broad category.  Heuristic; no LLM call.  (fix #4)"""
    fb = judge_feedback.lower()
    out_str = str(output).lower()
    if any(kw in fb or kw in out_str for kw in ("tool", "api", "timeout", "http", "connection")):
        return "tool_failure"
    if any(kw in fb for kw in ("empty", "placeholder", "n/a", "null", "blank", "useless")):
        return "silent_failure"
    if any(kw in fb for kw in ("incorrect", "wrong", "logic", "missed", "incomplete", "hallucin")):
        return "logic_failure"
    return "unknown"


# ---------------------------------------------------------------------------
# Prompt injection sanitization  (fix #7)
# ---------------------------------------------------------------------------

def _sanitize_for_prompt(text: str, max_len: int = 400) -> str:
    """Strip characters that could act as prompt injection anchors."""
    cleaned = _PROMPT_UNSAFE_RE.sub(" ", text)
    cleaned = re.sub(r" {2,}", " ", cleaned).strip()
    return cleaned[:max_len]


# ---------------------------------------------------------------------------
# Storage helpers  (all sync, called via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _memory_dir() -> Path:
    env = os.environ.get("HIVE_FAILURE_MEMORY_DIR")
    return Path(env) if env else _DEFAULT_MEMORY_DIR


def _normalize_task_type(agent_id: str, node_name: str) -> str:
    raw = f"{agent_id}:{node_name}"
    return re.sub(r"[^a-z0-9:_\-]", "_", raw.lower())


def _normalize_pattern(feedback: str, output_sample: str) -> str:
    """Normalize feedback+output into a stable pattern key.  (fix #3)

    Strips stopwords and punctuation so minor rephrasing of the same failure
    does not produce duplicate keys.

    TODO: replace with embedding-based similarity once a local model is
          available in the framework, enabling fuzzy dedup of paraphrased
          failures.
    """
    _STOPWORDS = frozenset(
        "the a an is was were be been being have has had do does did "
        "will would could should may might shall can of in on at to for "
        "with by from this that these those it its".split()
    )

    def _norm(s: str) -> str:
        s = s.lower().strip()
        s = re.sub(r"[^\w\s\-]", " ", s)
        return " ".join(t for t in s.split() if t not in _STOPWORDS)

    return f"{_norm(feedback[:200])}|{_norm(output_sample[:100])}"


def _record_id(task_type: str, pattern_key: str) -> str:
    return hashlib.sha256(f"{task_type}|{pattern_key}".encode()).hexdigest()[:16]


def _ngrams(s: str, n: int = 2) -> set[str]:
    s = s.lower()
    return {s[i: i + n] for i in range(len(s) - n + 1)} if len(s) >= n else set()


def _task_similarity(a: str, b: str) -> float:
    ng_a, ng_b = _ngrams(a), _ngrams(b)
    if not ng_a or not ng_b:
        return 0.0
    return len(ng_a & ng_b) / len(ng_a | ng_b)


def _retrieval_score(sim: float, count: int, ts: float, now: float) -> float:
    """Composite retrieval score: similarity + frequency + recency.  (fix #5)"""
    recency  = max(0.0, 1.0 - (now - ts) / (30 * 86_400))
    freq     = math.log1p(count) / math.log1p(100)
    return 0.5 * sim + 0.35 * freq + 0.15 * recency


def _load_records_sync(memory_dir: Path) -> list[FailureRecord]:
    path = memory_dir / _MEMORY_FILE
    if not path.exists():
        return []
    records: list[FailureRecord] = []
    now = time.time()
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                data.setdefault("failure_type", "unknown")   # back-compat
                rec = FailureRecord(**data)
                if now - rec.timestamp <= _MAX_RECORD_AGE_SECONDS:
                    records.append(rec)
            except Exception:  # noqa: BLE001
                logger.debug("Skipping malformed failure record: %r", line[:80])
    return records


def _save_records_sync(memory_dir: Path, records: list[FailureRecord]) -> None:
    """Atomic rewrite via tmp file.  Caller MUST hold _dir_lock."""
    memory_dir.mkdir(parents=True, exist_ok=True)
    tmp = memory_dir / f"{_MEMORY_FILE}.tmp"
    with tmp.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(asdict(rec)) + "\n")
    tmp.replace(memory_dir / _MEMORY_FILE)


def _append_record_sync(memory_dir: Path, record: FailureRecord) -> None:
    """Append-only write with advisory file lock for cross-process safety.

    # NOTE: JSONL used for simplicity; can be replaced with indexed storage if needed.

    On Windows, msvcrt.locking is exclusive and blocks concurrent readers;
    NTFS append-mode writes are atomic for our record sizes so the OS-level
    advisory lock is skipped on win32 to prevent PermissionError under
    high-concurrency tests.
    """
    memory_dir.mkdir(parents=True, exist_ok=True)
    path = memory_dir / _MEMORY_FILE
    with path.open("a", encoding="utf-8") as fh:
        if sys.platform != "win32":
            _lock_file(fh)
        try:
            fh.write(json.dumps(asdict(record)) + "\n")
        finally:
            if sys.platform != "win32":
                _unlock_file(fh)


def _load_proposals_sync(memory_dir: Path) -> list[RuleProposal]:
    path = memory_dir / _RULE_PROPOSALS_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data:
            item.setdefault("failure_type", "unknown")
        return [RuleProposal(**p) for p in data]
    except Exception:  # noqa: BLE001
        return []


def _save_proposals_sync(memory_dir: Path, proposals: list[RuleProposal]) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    path = memory_dir / _RULE_PROPOSALS_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(p) for p in proposals], indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Core async API
# ---------------------------------------------------------------------------

async def record_failure(
    *,
    agent_id: str,
    node_name: str,
    judge_feedback: str,
    output: dict[str, Any],
    iteration: int,
    failure_type: FailureType | None = None,
    memory_dir: Path | None = None,
) -> FailureRecord:
    """Persist a judge-RETRY or silent-failure event.  Thread-safe upsert.

    The full read-modify-write cycle is held under a per-directory
    threading.Lock (fix #1), eliminating concurrent-increment races.

    Records are noise-gated: the threshold _MIN_OCCURRENCES_TO_STORE (fix #6)
    controls whether a pattern influences retrieval and rule proposals.
    """
    dir_ = memory_dir or _memory_dir()
    task_type   = _normalize_task_type(agent_id, node_name)
    out_sample  = _sanitize_for_prompt(_output_sample(output), max_len=300)
    safe_feedback = _sanitize_for_prompt(judge_feedback)   # fix #7
    pattern_key = _normalize_pattern(safe_feedback, out_sample)
    rec_id      = _record_id(task_type, pattern_key)
    ftype: FailureType = failure_type or classify_failure(judge_feedback, output)

    lock = _dir_lock(dir_)

    def _upsert() -> FailureRecord:
        with lock:                                          # fix #1
            records  = _load_records_sync(dir_)
            existing = next((r for r in records if r.record_id == rec_id), None)

            if existing is not None:
                existing.occurrence_count += 1
                existing.timestamp = time.time()
                _save_records_sync(dir_, records)           # lock already held
                return existing

            new_rec = FailureRecord(
                record_id=rec_id,
                task_type=task_type,
                pattern_key=pattern_key,
                judge_feedback=safe_feedback,
                output_sample=out_sample,
                iteration=iteration,
                failure_type=ftype,
            )
            # Append inside lock to prevent rare duplicate write on high concurrency
            _append_record_sync(dir_, new_rec)
            return new_rec

    record = await asyncio.to_thread(_upsert)

    logger.info("failure_memory: recorded failure type=%s", ftype)  # checklist log
    logger.info(                                            # fix #8
        "failure_memory: recorded agent=%s node=%s type=%s pattern=%r count=%d",
        agent_id, node_name, ftype, pattern_key[:50], record.occurrence_count,
    )

    if (
        record.occurrence_count >= _RULE_PROPOSAL_THRESHOLD
        and record.occurrence_count >= _MIN_OCCURRENCES_TO_STORE
        and not record.proposed_rule
    ):
        await _maybe_propose_rule(record, dir_)

    return record


async def retrieve_relevant_failures(
    *,
    agent_id: str,
    node_name: str,
    max_results: int = _MAX_RETRIEVED,
    failure_type: FailureType | None = None,
    memory_dir: Path | None = None,
) -> list[FailureRecord]:
    """Return the most relevant past failures, ranked by composite score (fix #5).

    Optionally filter by failure_type (fix #4).
    Triggers probabilistic background compaction (fix #2).
    """
    dir_      = memory_dir or _memory_dir()
    task_type = _normalize_task_type(agent_id, node_name)
    now       = time.time()

    def _retrieve() -> list[FailureRecord]:
        records = _load_records_sync(dir_)
        scored: list[tuple[float, FailureRecord]] = []
        for rec in records:
            if rec.proposed_rule:
                continue
            if rec.occurrence_count < _MIN_OCCURRENCES_TO_STORE:   # fix #6
                continue
            if failure_type is not None and rec.failure_type != failure_type:
                continue
            sim = 1.0 if rec.task_type == task_type else _task_similarity(task_type, rec.task_type)
            if sim < _TASK_SIMILARITY_THRESHOLD:
                continue
            scored.append((_retrieval_score(sim, rec.occurrence_count, rec.timestamp, now), rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:max_results]]

    results = await asyncio.to_thread(_retrieve)

    logger.info(                                            # fix #8
        "failure_memory: retrieved %d failures agent=%s node=%s",
        len(results), agent_id, node_name,
    )

    if random.random() < _COMPACT_ON_RETRIEVE_PROB:         # fix #2
        asyncio.create_task(_background_compact(dir_))

    return results


def build_failure_memory_prompt(
    failures: list[FailureRecord],
    max_chars: int = 1_800,
) -> str:
    """Render a compact, sanitized Layer-2 narrative block.  (fix #7 + #4)

    - All strings were sanitized at record time (fix #7).
    - Records are grouped by failure_type for structured signal (fix #4).
    - Hard max_chars ceiling prevents context bloat.
    """
    if not failures:
        return ""

    groups: dict[str, list[FailureRecord]] = {}
    for rec in failures:
        groups.setdefault(rec.failure_type, []).append(rec)

    overhead = 180
    per_record_budget = max(80, (max_chars - overhead) // max(len(failures), 1))

    lines = [
        "## Failure memory — learned from past runs\n",
        "These patterns have caused task failures before. Avoid repeating them:\n",
    ]
    n = 0
    for ftype, recs in groups.items():
        safe_type = _sanitize_for_prompt(str(ftype).replace("_", " ").title(), max_len=40)
        lines.append(f"\n**{safe_type}**")
        for rec in recs:
            n += 1
            safe_pattern  = _sanitize_for_prompt(rec.pattern_key, max_len=70)
            safe_feedback = _sanitize_for_prompt(rec.judge_feedback, max_len=100)
            safe_output   = _sanitize_for_prompt(rec.output_sample, max_len=60)
            entry = (
                f"  {n}. (seen {rec.occurrence_count}x) {safe_pattern}\n"
                f"     Feedback: {safe_feedback}\n"
                f"     Output: {safe_output}\n"
            )
            if len(entry) > per_record_budget:
                entry = entry[:per_record_budget] + "…\n"
            lines.append(entry)

    lines.append("\nEnsure your output does not repeat these patterns.\n")
    prompt = "\n".join(lines)
    return prompt[:max_chars - 3] + "…" if len(prompt) > max_chars else prompt


# ---------------------------------------------------------------------------
# Rule proposal generation
# ---------------------------------------------------------------------------

async def _maybe_propose_rule(record: FailureRecord, memory_dir: Path) -> None:
    lock = _dir_lock(memory_dir)

    def _propose() -> None:
        with lock:
            records   = _load_records_sync(memory_dir)
            proposals = _load_proposals_sync(memory_dir)

            examples = [r.output_sample for r in records if r.record_id == record.record_id][:5]
            snippet  = re.sub(r"['\"\\'\n\r]", " ", record.judge_feedback[:80]).strip()
            condition = f"'{snippet[:40]}' in str(context.get('judge_feedback', ''))"

            proposal = RuleProposal(
                proposal_id=record.record_id,
                task_type=record.task_type,
                pattern_key=record.pattern_key,
                failure_type=record.failure_type,
                occurrence_count=record.occurrence_count,
                proposed_condition=condition,
                proposed_action="RETRY",
                rationale=(
                    f"Pattern triggered {record.occurrence_count} {record.failure_type} "
                    f"rejections for '{record.task_type}'.  Proposing deterministic rule "
                    f"to catch it earlier without an LLM call."
                ),
                examples=examples,
            )

            proposals = [p for p in proposals if p.proposal_id != proposal.proposal_id]
            proposals.append(proposal)
            _save_proposals_sync(memory_dir, proposals)

            for rec in records:
                if rec.record_id == record.record_id:
                    rec.proposed_rule = True
            _save_records_sync(memory_dir, records)

        logger.info(
            "failure_memory: rule proposal created type=%s pattern=%r count=%d",
            record.failure_type, record.pattern_key[:60], record.occurrence_count,
        )

    await asyncio.to_thread(_propose)


# ---------------------------------------------------------------------------
# Maintenance helpers
# ---------------------------------------------------------------------------

async def compact_memory(memory_dir: Path | None = None) -> int:
    """Prune age-expired records.  Returns count removed."""
    dir_  = memory_dir or _memory_dir()
    lock  = _dir_lock(dir_)

    def _compact() -> int:
        with lock:
            path = dir_ / _MEMORY_FILE
            if not path.exists():
                return 0
            raw = sum(1 for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip())
            fresh   = _load_records_sync(dir_)
            removed = raw - len(fresh)
            if removed > 0:
                _save_records_sync(dir_, fresh)
                logger.info("failure_memory: compacted %d expired records", removed)
            return removed

    return await asyncio.to_thread(_compact)


async def _background_compact(memory_dir: Path) -> None:
    try:
        await compact_memory(memory_dir)
    except Exception:  # noqa: BLE001
        pass


async def list_proposals(memory_dir: Path | None = None) -> list[RuleProposal]:
    dir_ = memory_dir or _memory_dir()
    all_ = await asyncio.to_thread(_load_proposals_sync, dir_)
    return [p for p in all_ if not p.approved]


async def approve_proposal(proposal_id: str, memory_dir: Path | None = None) -> bool:
    dir_  = memory_dir or _memory_dir()
    lock  = _dir_lock(dir_)

    def _approve() -> bool:
        with lock:
            proposals = _load_proposals_sync(dir_)
            for p in proposals:
                if p.proposal_id == proposal_id:
                    p.approved    = True
                    p.approved_at = time.time()
                    _save_proposals_sync(dir_, proposals)
                    return True
        return False

    return await asyncio.to_thread(_approve)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _output_sample(output: dict[str, Any]) -> str:
    try:
        return json.dumps(output, default=str, ensure_ascii=False)[:300]
    except Exception:  # noqa: BLE001
        return str(output)[:300]


__all__ = [
    "FailureRecord",
    "FailureType",
    "RuleProposal",
    "approve_proposal",
    "build_failure_memory_prompt",
    "classify_failure",
    "compact_memory",
    "is_silent_failure",
    "list_proposals",
    "record_failure",
    "retrieve_relevant_failures",
]
