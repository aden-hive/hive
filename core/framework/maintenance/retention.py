"""Retention policy engine: what the janitor may touch, and how.

Three tiers, all manual-trigger (see janitor.py):

- Tier 1: age-out debug stores (event_logs/, llm_logs/, compaction_log/,
  tool-artifacts/, rotated logs/). Plain delete — no consumer exists.
  llm_logs/ writing is now opt-in (HIVE_ENABLE_LLM_LOGS); local files
  there are legacy.
- Tier 2: deep-clean finished colony workers — archive+delete the
  transcript (conversations/ + data/), write a result.json tombstone,
  keep meta.json/tasks.json so the workers UI keeps rendering.
- Tier 3: cold queen session hygiene — delete orphaned spillover
  data/*.txt and rewrite events.jsonl dropping context_usage_updated
  telemetry (plus legacy full_request payloads).

Safety model: sessions live in the running SessionManager are
hard-blocked; everything else must pass an age gate computed from the
max of several on-disk activity signals (never bare mtime of the dir).
All paths are resolved through ``framework.config`` attribute access at
call time so test monkeypatching of HIVE_HOME applies.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from framework import config
from framework.server import compaction_status
from framework.utils.io import atomic_write

if TYPE_CHECKING:
    from framework.server.session_manager import SessionManager

try:
    import fcntl
except ImportError:  # Windows: no flock; index reset proceeds best-effort
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Top-level HIVE_HOME entries the janitor must never touch, ever.
KEEP_ALWAYS: frozenset[str] = frozenset(
    {
        "memories",
        "charts",
        "credentials",
        "secrets",
        "mcp_registry",
        "configuration.json",
        "runtime_id",
        "sentinel_secret",
        "desktop",
        "skills",
        "workspace",
        "sessions",
        "archive",
        "maintenance",
    }
)

# Top-level entries the janitor knows about (used by the junk detector:
# anything top-level NOT in KEEP_ALWAYS ∪ KNOWN_ENTRIES is "unknown").
KNOWN_ENTRIES: frozenset[str] = frozenset(
    {
        "queens",
        "colonies",
        "agents",
        "event_logs",
        "llm_logs",
        "compaction_log",
        "tool-artifacts",
        "failed_requests",
        "logs",
        ".message_index",
        ".janitor",
    }
)

_SESSION_TS_RE = re.compile(r"^session_(\d{8})_(\d{6})_")
# event_logs / llm_logs: 20260515_131452.jsonl
_LOG_TS_RE = re.compile(r"^(\d{8})_(\d{6})\.jsonl$")
# compaction_log: 20260429T002854_346307_queen.md
_COMPACTION_TS_RE = re.compile(r"^(\d{8})T(\d{6})_\d+")
# tool-artifacts: browser_snapshot_1783031564665_tab2.txt (epoch millis)
_EPOCH_MS_RE = re.compile(r"_(\d{13})[_.]")

_JANITOR_LOCK_NAME = ".janitor.lock"
_SESSION_LOCK_TTL_S = 3600.0
_COMPACTION_STALE_S = 1800.0
_EVENTS_TMP_SUFFIX = ".janitor-tmp"

# Worker session-root files that survive a deep-clean.
_WORKER_KEEP_FILES = frozenset({"meta.json", "tasks.json", "result.json"})

_TOMBSTONE_SUMMARY_CAP = 1000


def parse_session_dir_ts(name: str) -> float | None:
    """Timestamp embedded in a ``session_YYYYMMDD_HHMMSS_hex`` dir name.

    Mirrors tools/src/memory_tools/paths.py:parse_session_started_at
    (memory_tools is a separate uv package, not importable from core).
    """
    m = _SESSION_TS_RE.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").timestamp()
    except ValueError:
        return None


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _safe_stat_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _dir_size(path: Path) -> tuple[int, int]:
    """(file_count, total_bytes) for a tree; OSErrors skip entries."""
    files = 0
    total = 0
    try:
        for p in path.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    files += 1
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return files, total


def assert_safe_target(path: Path) -> None:
    """Refuse to dispose anything under a KEEP_ALWAYS top-level entry."""
    hive_home = config.HIVE_HOME.resolve()
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(hive_home)
    except ValueError:
        raise ValueError(f"janitor target escapes HIVE_HOME: {path}") from None
    if rel.parts and rel.parts[0] in KEEP_ALWAYS:
        raise ValueError(f"janitor refusing protected target: {path}")


# ---------------------------------------------------------------------------
# Manifest / report
# ---------------------------------------------------------------------------


@dataclass
class PruneItem:
    """One manifest line: a candidate and what happened to it."""

    path: str
    bytes: int
    tier: int
    target: str  # e.g. "event_logs", "worker_deep_clean"
    action: str  # "delete" | "archive" | "rewrite" | "tombstone"
    reason: str
    outcome: str = "candidate"  # dry-run: "candidate"; real: "done"|"skipped"|"error"
    error: str | None = None

    def to_dict(self) -> dict:
        d = {
            "path": self.path,
            "bytes": self.bytes,
            "tier": self.tier,
            "target": self.target,
            "action": self.action,
            "reason": self.reason,
            "outcome": self.outcome,
        }
        if self.error:
            d["error"] = self.error
        return d


@dataclass
class TargetReport:
    name: str
    tier: int
    files: int = 0
    bytes_freed: int = 0
    archived_files: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tier": self.tier,
            "files": self.files,
            "bytes_freed": self.bytes_freed,
            "archived_files": self.archived_files,
            "skipped": self.skipped,
            "errors": self.errors[:20],
        }


class Manifest:
    """Collects PruneItems across a run; janitor.py serializes to JSONL."""

    def __init__(self) -> None:
        self.items: list[PruneItem] = []

    def add(self, item: PruneItem) -> None:
        self.items.append(item)


# ---------------------------------------------------------------------------
# Disposers
# ---------------------------------------------------------------------------


class Disposer(Protocol):
    dry_run: bool

    def dispose_file(self, path: Path) -> int:
        """Remove one file; returns bytes freed."""
        ...

    def dispose_dir(self, path: Path) -> tuple[int, int]:
        """Remove a tree; returns (files, bytes) freed."""
        ...


class DryRunDisposer:
    """Measures what would be freed without touching anything."""

    dry_run = True

    def dispose_file(self, path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def dispose_dir(self, path: Path) -> tuple[int, int]:
        return _dir_size(path)


class DeleteDisposer:
    dry_run = False

    def dispose_file(self, path: Path) -> int:
        assert_safe_target(path)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        path.unlink(missing_ok=True)
        return size

    def dispose_dir(self, path: Path) -> tuple[int, int]:
        assert_safe_target(path)
        files, total = _dir_size(path)
        # Rename first so a crash mid-rmtree leaves an obviously-dead tree
        # a later run can sweep, instead of a half-valid session dir.
        trash = path.with_name(f"{path.name}.jtrash-{int(time.time())}")
        try:
            path.rename(trash)
        except OSError:
            trash = path  # cross-device or already gone: delete in place
        shutil.rmtree(trash, ignore_errors=True)
        return files, total


# ---------------------------------------------------------------------------
# Safety context
# ---------------------------------------------------------------------------


@dataclass
class SafetyContext:
    """Everything needed to decide whether a session dir is touchable."""

    protected_session_ids: frozenset[str]
    live_session_dirs: frozenset[str]
    grace_seconds: float
    now: float = field(default_factory=time.time)
    # CLI-offline runs cannot see in-process state; when a local server is
    # detected the CLI refuses tiers 2/3 outright instead of guessing.
    offline: bool = False
    # Optional callable returning a fresh (protected_ids, live_dirs)
    # snapshot; used to re-check right before destructive tier-3 steps so
    # a session resumed mid-run (after the initial snapshot) is seen.
    refresher: Callable[[], tuple[frozenset[str], frozenset[str]]] | None = None

    def refresh(self) -> None:
        if self.refresher is None:
            return
        try:
            protected, live_dirs = self.refresher()
        except Exception:
            logger.warning("janitor: protected-set refresh failed; keeping stale snapshot", exc_info=True)
            return
        self.protected_session_ids = protected
        self.live_session_dirs = live_dirs

    @classmethod
    def from_manager(cls, manager: SessionManager, cfg) -> SafetyContext:
        """Snapshot live sessions + in-flight workers from the running server.

        Must be called on the event loop thread (plain dict reads; the
        registry is only mutated from that same loop).
        """
        protected: set[str] = set()
        live_dirs: set[str] = set()
        for session in manager.list_sessions():
            protected.add(session.id)
            queen_dir = getattr(session, "queen_dir", None)
            if queen_dir:
                live_dirs.add(str(queen_dir))
                protected.add(Path(queen_dir).name)
            colony = getattr(session, "colony", None)
            if colony is not None:
                try:
                    for info in colony.list_workers():
                        if str(info.status) in ("queued", "pending", "running"):
                            protected.add(info.id)
                except Exception:
                    # A colony mid-teardown must not break the snapshot —
                    # fail closed by protecting every known worker id.
                    workers = getattr(colony, "_workers", {}) or {}
                    protected.update(workers.keys())
        return cls(
            protected_session_ids=frozenset(protected),
            live_session_dirs=frozenset(live_dirs),
            grace_seconds=cfg.active_grace_hours * 3600.0,
        )

    @classmethod
    def for_offline(cls, cfg) -> SafetyContext:
        return cls(
            protected_session_ids=frozenset(),
            live_session_dirs=frozenset(),
            grace_seconds=cfg.active_grace_hours * 3600.0,
            offline=True,
        )

    # -- signals ---------------------------------------------------------

    def last_activity(self, session_dir: Path) -> float:
        """Newest activity signal for a session dir.

        Combines summary.json last_active_at, events.jsonl mtime, the
        conversation parts/cursor mtimes and the dir-name timestamp. The
        result can only err toward "more recent" (skipping), never toward
        premature pruning.
        """
        candidates = [parse_session_dir_ts(session_dir.name) or 0.0]
        summary = _read_json(session_dir / "summary.json")
        try:
            candidates.append(float(summary.get("last_active_at") or 0.0))
        except (TypeError, ValueError):
            pass
        candidates.append(_safe_stat_mtime(session_dir / "events.jsonl"))
        candidates.append(_safe_stat_mtime(session_dir / "conversations" / "cursor.json"))
        candidates.append(_safe_stat_mtime(session_dir / "conversations" / "parts"))
        return max(candidates)

    def is_safe_to_prune(self, session_dir: Path, *, min_age_days: float, ignore_janitor_lock: bool = False) -> tuple[bool, str]:
        """(touchable, reason_if_not) for one session dir.

        ``ignore_janitor_lock`` is for the post-lock re-check: after this
        janitor takes the session lock itself, the lock clause would
        short-circuit ahead of the liveness/age checks and turn the
        re-check into a no-op.
        """
        sid = session_dir.name
        if sid in self.protected_session_ids:
            return False, "live in SessionManager"
        if str(session_dir) in self.live_session_dirs:
            return False, "dir belongs to a live session"
        status = compaction_status.get_status(session_dir)
        if status and status.get("status") == "in_progress":
            started = _parse_iso_ts(status.get("started_at"))
            if started is None or self.now - started < _COMPACTION_STALE_S:
                return False, "fork-compaction in progress"
            # else: stale marker from a crashed compactor — not blocking.
        if not ignore_janitor_lock and _fresh_lock_exists(session_dir / _JANITOR_LOCK_NAME, self.now):
            return False, "another janitor holds the session lock"
        age_gate = min_age_days * 86400.0
        last_active = self.last_activity(session_dir)
        idle = self.now - last_active
        if idle < max(age_gate, self.grace_seconds):
            return False, f"active {idle / 86400:.1f}d ago (< gate)"
        partials = session_dir / "conversations" / "partials"
        try:
            has_partials = any(partials.iterdir())
        except OSError:
            has_partials = False
        if has_partials and idle < 2 * age_gate:
            # Crashed mid-turn: the in-flight checkpoint makes a resume
            # likelier, so demand double the idle window.
            return False, "in-flight partials present (< 2x gate)"
        return True, ""


def _parse_iso_ts(value) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def _fresh_lock_exists(lock_path: Path, now: float, ttl: float = _SESSION_LOCK_TTL_S) -> bool:
    try:
        return now - lock_path.stat().st_mtime < ttl
    except OSError:
        return False


def acquire_session_lock(session_dir: Path, now: float) -> bool:
    """O_EXCL session lock (NFS-portable; no flock). Stale locks are broken."""
    lock_path = session_dir / _JANITOR_LOCK_NAME
    if _fresh_lock_exists(lock_path, now):
        return False
    lock_path.unlink(missing_ok=True)  # break stale lock
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except OSError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "ts": now}, f)
    return True


def release_session_lock(session_dir: Path) -> None:
    (session_dir / _JANITOR_LOCK_NAME).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Tier 1 — aged debug stores
# ---------------------------------------------------------------------------


def _tier1_file_ts(name: str) -> float | None:
    """Timestamp from a tier-1 filename; None when unparseable."""
    m = _LOG_TS_RE.match(name)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").timestamp()
        except ValueError:
            return None
    m = _COMPACTION_TS_RE.match(name)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").timestamp()
        except ValueError:
            return None
    m = _EPOCH_MS_RE.search(name)
    if m:
        return int(m.group(1)) / 1000.0
    return None


def prune_aged_dir(
    dir_path: Path,
    *,
    target: str,
    max_age_days: float,
    disposer: Disposer,
    manifest: Manifest,
    keep_newest: int = 1,
    process_start_ts: float | None = None,
    now: float | None = None,
    pace: Callable[[], None] | None = None,
) -> TargetReport:
    """Delete files in a flat debug dir older than the window.

    Age comes from the filename timestamp with mtime fallback. Always
    keeps the ``keep_newest`` most recent entries and anything modified
    since ``process_start_ts`` — the runtime holds one file per dir open
    for its whole lifetime (llm_debug_logger.py when enabled /
    event_bus.py).
    """
    report = TargetReport(name=target, tier=1)
    now = now if now is not None else time.time()
    if not dir_path.is_dir():
        return report
    entries: list[tuple[float, Path]] = []
    try:
        for p in dir_path.iterdir():
            if not p.is_file():
                continue
            ts = _tier1_file_ts(p.name)
            if ts is None:
                ts = _safe_stat_mtime(p)
            entries.append((ts, p))
    except OSError:
        return report
    entries.sort(reverse=True)
    cutoff = now - max_age_days * 86400.0
    for i, (ts, p) in enumerate(entries):
        if i < keep_newest:
            continue
        mtime = _safe_stat_mtime(p)
        if process_start_ts is not None and mtime >= process_start_ts:
            continue  # possibly held open by the running server
        if max(ts, mtime) >= cutoff:
            continue
        item = PruneItem(
            path=str(p),
            bytes=0,
            tier=1,
            target=target,
            action="delete",
            reason=f"older than {max_age_days:g}d",
        )
        try:
            item.bytes = disposer.dispose_file(p)
            item.outcome = "candidate" if disposer.dry_run else "done"
            report.files += 1
            report.bytes_freed += item.bytes
        except PermissionError:
            item.outcome = "skipped"
            item.error = "permission denied (open handle?)"
            report.skipped += 1
        except (OSError, ValueError) as exc:
            item.outcome = "error"
            item.error = str(exc)
            report.errors.append(f"{p.name}: {exc}")
        manifest.add(item)
        if pace:
            pace()
    return report


# ---------------------------------------------------------------------------
# Tier 2 — finished-worker deep-clean
# ---------------------------------------------------------------------------


def iter_worker_sessions() -> Iterator[tuple[str, str, Path]]:
    """Yield (colony_id, worker_id, worker_dir) for every on-disk worker."""
    colonies_dir = config.COLONIES_DIR
    if not colonies_dir.is_dir():
        return
    try:
        colonies = sorted(p for p in colonies_dir.iterdir() if p.is_dir())
    except OSError:
        return
    for colony in colonies:
        workers_dir = colony / "workers"
        if not workers_dir.is_dir():
            continue
        try:
            worker_dirs = sorted(p for p in workers_dir.iterdir() if p.is_dir())
        except OSError:
            continue
        for wdir in worker_dirs:
            if wdir.name.endswith("~") or ".jtrash-" in wdir.name:
                continue
            yield colony.name, wdir.name, wdir


def _extract_worker_summary(wdir: Path) -> tuple[str, str]:
    """(status, summary) from the worker's own parts — no queen-file scan.

    The queen already holds the authoritative [WORKER_REPORT]; this is
    only a display string for the workers UI after the transcript is gone.
    """
    parts_dir = wdir / "conversations" / "parts"
    try:
        files = sorted((p for p in parts_dir.iterdir() if p.suffix == ".json"), reverse=True)
    except OSError:
        return "unknown", ""
    last_role = ""
    for p in files:
        data = _read_json(p)
        if not last_role:
            last_role = str(data.get("role") or "")
        if data.get("role") == "assistant":
            content = data.get("content")
            if isinstance(content, str) and content.strip():
                summary = content.strip()[:_TOMBSTONE_SUMMARY_CAP]
                # A run whose final part is a clean assistant message ended
                # normally; anything else (dangling tool call, partials) is
                # indeterminate from disk alone.
                status = "completed" if last_role == "assistant" else "unknown"
                return status, summary
    return "unknown", ""


def _delete_message_index_subtrees(session_id: str, disposer: Disposer, manifest: Manifest, tier: int, target: str) -> int:
    """Remove .message_index/{events,data,meta}/*/*/<session_id> subtrees.

    The index stores its own copies (and hardlinks of spillover files),
    so leaving it behind both strands bytes and serves ghost results
    from search_messages after the source is pruned.
    """
    index_root = config.HIVE_HOME / ".message_index"
    freed = 0
    for tree in ("events", "data", "meta"):
        base = index_root / tree
        if not base.is_dir():
            continue
        for sub in base.glob(f"*/*/{session_id}"):
            item = PruneItem(
                path=str(sub),
                bytes=0,
                tier=tier,
                target=target,
                action="delete",
                reason="message index copy of pruned session",
            )
            try:
                _, item.bytes = disposer.dispose_dir(sub)
                item.outcome = "candidate" if disposer.dry_run else "done"
                freed += item.bytes
            except (OSError, ValueError) as exc:
                item.outcome = "error"
                item.error = str(exc)
            manifest.add(item)
    return freed


def deep_clean_worker(
    colony_id: str,
    worker_id: str,
    wdir: Path,
    *,
    disposer: Disposer,
    manifest: Manifest,
) -> TargetReport:
    """Archive/delete a finished worker's transcript, leaving a tombstone.

    Order is crash-safe: the tombstone is written before any deletion so
    (a) resume_worker refuses the worker from that point on and (b) a
    rerun after a crash simply finishes the deletions.
    """
    report = TargetReport(name="worker_deep_clean", tier=2)
    result_path = wdir / "result.json"

    tombstone_exists = result_path.exists()
    already_cleaned = tombstone_exists and not (wdir / "conversations").exists()
    if already_cleaned:
        return report

    if not tombstone_exists:
        status, summary = _extract_worker_summary(wdir)
        tombstone = {
            "status": status,
            "summary": summary,
            "error": None,
            "tokens_used": 0,
            "duration_seconds": 0.0,
            "_janitor": {
                "pruned_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "source": "worker_parts" if summary else "synthesized",
            },
        }
        if not disposer.dry_run:
            with atomic_write(result_path) as f:
                json.dump(tombstone, f, ensure_ascii=False)
        manifest.add(
            PruneItem(
                path=str(result_path),
                bytes=0,
                tier=2,
                target="worker_deep_clean",
                action="tombstone",
                reason="preserve status/summary for workers UI",
                outcome="candidate" if disposer.dry_run else "done",
            )
        )

    report.bytes_freed += _delete_message_index_subtrees(worker_id, disposer, manifest, 2, "worker_deep_clean")

    targets: list[Path] = []
    for sub in ("conversations", "data"):
        p = wdir / sub
        if p.exists():
            targets.append(p)
    try:
        for p in wdir.iterdir():
            if p.is_file() and p.name not in _WORKER_KEEP_FILES:
                targets.append(p)
    except OSError:
        pass

    for p in targets:
        item = PruneItem(
            path=str(p),
            bytes=0,
            tier=2,
            target="worker_deep_clean",
            action="archive" if getattr(disposer, "archives", False) else "delete",
            reason=f"finished worker in colony {colony_id}",
        )
        try:
            if p.is_dir():
                files, item.bytes = disposer.dispose_dir(p)
                report.files += files
            else:
                item.bytes = disposer.dispose_file(p)
                report.files += 1
            item.outcome = "candidate" if disposer.dry_run else "done"
            report.bytes_freed += item.bytes
        except (OSError, ValueError) as exc:
            item.outcome = "error"
            item.error = str(exc)
            report.errors.append(f"{worker_id}/{p.name}: {exc}")
        manifest.add(item)
    return report


# ---------------------------------------------------------------------------
# Tier 3 — cold queen session hygiene
# ---------------------------------------------------------------------------


def iter_queen_sessions() -> Iterator[Path]:
    """Every queen session dir: standalone queens and colony overseers."""
    queens_dir = config.QUEENS_DIR
    if queens_dir.is_dir():
        yield from sorted(queens_dir.glob("*/sessions/session_*"))
    colonies_dir = config.COLONIES_DIR
    if colonies_dir.is_dir():
        yield from sorted(colonies_dir.glob("*/queens/*/sessions/session_*"))


def _spillover_reference_corpus(session_dir: Path) -> str | None:
    """Concatenated text that may reference spillover files by path/name.

    Raw JSON text of live parts + partials (so tool_calls arguments count
    as references, not just the content field) plus the raw cursor.json
    (its ``outputs`` map holds "Output saved at: ..." strings).

    FAILS CLOSED: any read error returns None — a corpus missing even one
    unreadable part could misclassify a referenced spillover as an
    orphan, and deleting a referenced spillover destroys the only copy.
    """
    chunks: list[str] = []
    conv = session_dir / "conversations"
    for sub in ("parts", "partials"):
        d = conv / sub
        if not d.is_dir():
            continue
        try:
            files = sorted(p for p in d.iterdir() if p.suffix == ".json")
            for p in files:
                chunks.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            logger.warning("janitor: cannot read %s; skipping orphan scan for this session", d)
            return None
    cursor = conv / "cursor.json"
    if cursor.exists():
        try:
            chunks.append(cursor.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            logger.warning("janitor: cannot read %s; skipping orphan scan for this session", cursor)
            return None
    return "\n".join(chunks)


def find_orphan_spillovers(session_dir: Path, *, min_age_days: float, now: float) -> list[Path]:
    """Spillover files in <session>/data/ referenced by no live message.

    Conservative: keeps a file if its basename appears anywhere in the
    reference corpus (covers "Full result at: <abs path>", legacy
    "[Saved to 'name']", and model-retyped bare names). Skips
    subdirectories (attachments/ lives there) and conversation_*.md
    handoff transcripts.
    """
    data_dir = session_dir / "data"
    if not data_dir.is_dir():
        return []
    try:
        candidates = [p for p in data_dir.iterdir() if p.is_file() and p.suffix in (".txt", ".json") and not p.name.startswith("conversation_")]
    except OSError:
        return []
    if not candidates:
        return []
    corpus = _spillover_reference_corpus(session_dir)
    if corpus is None:
        return []  # fail closed: unreadable corpus => treat everything as referenced
    cutoff = now - min_age_days * 86400.0
    orphans = []
    for p in candidates:
        if p.name in corpus:
            continue
        if _safe_stat_mtime(p) >= cutoff:
            continue
        orphans.append(p)
    return orphans


def rewrite_events_jsonl(
    events_path: Path,
    *,
    min_bytes: int,
    disposer: Disposer,
    manifest: Manifest,
    drop_types: frozenset[str] = frozenset({"context_usage_updated"}),
) -> int:
    """Strip telemetry events from a COLD session's events.jsonl.

    Drops whole lines whose ``type`` is in ``drop_types`` and removes any
    legacy ``data.full_request`` payloads from kept lines (current
    event_bus strips these on write; old files still carry them).
    Unparseable lines are preserved verbatim. The rewrite is
    tmp+fsync+replace in the same dir, and aborts if the source changed
    between read and replace (a live appender snuck in).

    Returns bytes saved (0 if skipped). Caller must hold the session lock.
    """
    try:
        pre = events_path.stat()
    except OSError:
        return 0
    if pre.st_size < min_bytes:
        return 0

    kept: list[str] = []
    dropped_lines = 0
    stripped_fields = 0
    try:
        with open(events_path, encoding="utf-8") as f:
            for line in f:
                stripped = line.rstrip("\n")
                if not stripped:
                    continue
                try:
                    evt = json.loads(stripped)
                except json.JSONDecodeError:
                    kept.append(stripped)
                    continue
                if isinstance(evt, dict) and evt.get("type") in drop_types:
                    dropped_lines += 1
                    continue
                data = evt.get("data") if isinstance(evt, dict) else None
                if isinstance(data, dict) and "full_request" in data:
                    data.pop("full_request", None)
                    stripped_fields += 1
                    kept.append(json.dumps(evt, ensure_ascii=False, separators=(",", ":")))
                else:
                    kept.append(stripped)
    except OSError as exc:
        logger.warning("janitor: cannot read %s: %s", events_path, exc)
        return 0

    if dropped_lines == 0 and stripped_fields == 0:
        return 0

    body = "\n".join(kept) + ("\n" if kept else "")
    saved = pre.st_size - len(body.encode("utf-8"))
    if saved < pre.st_size * 0.10:
        return 0  # not worth an inode swap

    item = PruneItem(
        path=str(events_path),
        bytes=saved,
        tier=3,
        target="events_rewrite",
        action="rewrite",
        reason=f"drop {dropped_lines} telemetry events, strip {stripped_fields} full_request",
    )
    if disposer.dry_run:
        item.outcome = "candidate"
        manifest.add(item)
        return saved

    tmp = events_path.with_name(events_path.name + _EVENTS_TMP_SUFFIX)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        post = events_path.stat()
        if (post.st_size, post.st_mtime_ns) != (pre.st_size, pre.st_mtime_ns):
            tmp.unlink(missing_ok=True)
            item.outcome = "skipped"
            item.error = "source changed during rewrite"
            manifest.add(item)
            return 0
        os.replace(tmp, events_path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        item.outcome = "error"
        item.error = str(exc)
        manifest.add(item)
        return 0
    item.outcome = "done"
    manifest.add(item)
    return saved


def _reset_message_index_for_session(session_id: str) -> None:
    """Force the memory index to re-sync a rewritten session from scratch.

    The index's own shrink detection only fires when its cursor offset
    exceeds the new file size; a cursor that was behind would resume
    mid-line. Deleting the cached copies + cursor (under the index's own
    flock protocol) is the safe reset. Mirrors memory_tools
    index._reset_session_cache. On Windows (no fcntl) the reset proceeds
    without the lock — a concurrent sync at worst re-caches and the next
    reset converges.
    """
    index_root = config.HIVE_HOME / ".message_index"
    meta_base = index_root / "meta"
    if not meta_base.is_dir():
        return
    for meta_dir in meta_base.glob(f"*/*/{session_id}"):
        scope_owner = meta_dir.relative_to(meta_base).parts[:2]
        lock_path = meta_dir / ".lock"
        fd = None
        try:
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            if fd is not None:
                os.close(fd)
            continue
        try:
            for tree in ("events", "data"):
                shutil.rmtree(index_root / tree / Path(*scope_owner) / session_id, ignore_errors=True)
            (meta_dir / "cursor.json").unlink(missing_ok=True)
            (meta_dir / "data_map.json").unlink(missing_ok=True)
        finally:
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def prune_queen_session(
    session_dir: Path,
    *,
    cfg,
    safety: SafetyContext,
    disposer: Disposer,
    manifest: Manifest,
) -> TargetReport:
    """Tier-3 hygiene for one cold queen session (caller pre-checked age).

    The orphan-spillover pass runs unlocked (deleting a data file cannot
    corrupt a racing resume; worst case is a recoverable read_file error).
    The events.jsonl rewrite — the step a racing resume MUST not overlap,
    or its append fd lands on the orphaned inode — runs under the session
    lock with a refreshed liveness re-check, keeping the lock window as
    short as possible (the resume path waits on this lock).
    """
    report = TargetReport(name="queen_hygiene", tier=3)

    for orphan in find_orphan_spillovers(session_dir, min_age_days=cfg.queen_hygiene_days, now=safety.now):
        item = PruneItem(
            path=str(orphan),
            bytes=0,
            tier=3,
            target="orphan_spillover",
            action="archive" if getattr(disposer, "archives", False) else "delete",
            reason="spillover unreferenced by any live message",
        )
        try:
            item.bytes = disposer.dispose_file(orphan)
            item.outcome = "candidate" if disposer.dry_run else "done"
            report.files += 1
            report.bytes_freed += item.bytes
        except (OSError, ValueError) as exc:
            item.outcome = "error"
            item.error = str(exc)
            report.errors.append(f"{orphan.name}: {exc}")
        manifest.add(item)

    if disposer.dry_run:
        saved = rewrite_events_jsonl(
            session_dir / "events.jsonl",
            min_bytes=cfg.events_rewrite_min_bytes,
            disposer=disposer,
            manifest=manifest,
        )
        if saved:
            report.bytes_freed += saved
            report.files += 1
        return report

    if not acquire_session_lock(session_dir, safety.now):
        report.skipped += 1
        return report
    try:
        # Re-check under the lock with a REFRESHED live-set: a session
        # resumed after the run-start snapshot must be seen here. The
        # janitor's own lock is excluded so the liveness/age clauses
        # actually run instead of short-circuiting on it.
        safety.refresh()
        ok, _reason = safety.is_safe_to_prune(session_dir, min_age_days=cfg.queen_hygiene_days, ignore_janitor_lock=True)
        if not ok:
            report.skipped += 1
            return report

        saved = rewrite_events_jsonl(
            session_dir / "events.jsonl",
            min_bytes=cfg.events_rewrite_min_bytes,
            disposer=disposer,
            manifest=manifest,
        )
        if saved:
            report.bytes_freed += saved
            report.files += 1
            _reset_message_index_for_session(session_dir.name)

        if report.files or report.bytes_freed:
            with atomic_write(session_dir / ".pruned.json") as f:
                json.dump({"schema": 1, "pruned_at": safety.now, "bytes_freed": report.bytes_freed}, f)
    finally:
        release_session_lock(session_dir)
    return report


# ---------------------------------------------------------------------------
# One-time cleanups (CLI flags)
# ---------------------------------------------------------------------------


def sweep_janitor_leftovers(manifest: Manifest) -> TargetReport:
    """Remove crash residue from prior runs: *.janitor-tmp, *.jtrash-*."""
    report = TargetReport(name="leftover_sweep", tier=0)
    hive_home = config.HIVE_HOME
    if not hive_home.is_dir():
        return report
    patterns = ("*.janitor-tmp", "*.jtrash-*")
    for pattern in patterns:
        try:
            matches = list(hive_home.rglob(pattern))
        except OSError:
            continue
        for p in matches:
            # Only sweep residue that's had time to be finished by its owner.
            if time.time() - _safe_stat_mtime(p) < _SESSION_LOCK_TTL_S:
                continue
            try:
                size = 0
                if p.is_dir():
                    _, size = _dir_size(p)
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    size = p.stat().st_size
                    p.unlink(missing_ok=True)
                report.files += 1
                report.bytes_freed += size
                manifest.add(
                    PruneItem(
                        path=str(p),
                        bytes=size,
                        tier=0,
                        target="leftover_sweep",
                        action="delete",
                        reason="crash residue from prior janitor run",
                        outcome="done",
                    )
                )
            except OSError:
                continue
    return report


def sweep_orphan_message_index(disposer: Disposer, manifest: Manifest) -> TargetReport:
    """Delete index subtrees whose source session no longer exists.

    Source resolution mirrors tools/src/memory_tools/paths.py: scope
    "queens" reads from HIVE_HOME/agents/queens/<owner>/sessions/<sid>,
    scope "colonies" from HIVE_HOME/colonies/<owner>/sessions/<sid>.
    """
    report = TargetReport(name="orphan_index_sweep", tier=0)
    index_root = config.HIVE_HOME / ".message_index"
    meta_base = index_root / "meta"
    if not meta_base.is_dir():
        return report
    for meta_dir in sorted(meta_base.glob("*/*/*")):
        parts = meta_dir.relative_to(meta_base).parts
        if len(parts) != 3:
            continue
        scope, owner, session = parts
        if scope == "queens":
            source = config.HIVE_HOME / "agents" / "queens" / owner / "sessions" / session / "events.jsonl"
        elif scope == "colonies":
            source = config.HIVE_HOME / "colonies" / owner / "sessions" / session / "events.jsonl"
        else:
            continue
        if source.exists():
            continue
        for tree in ("events", "data", "meta"):
            sub = index_root / tree / scope / owner / session
            if not sub.exists():
                continue
            item = PruneItem(
                path=str(sub),
                bytes=0,
                tier=0,
                target="orphan_index_sweep",
                action="delete",
                reason=f"source session gone ({source})",
            )
            try:
                _, item.bytes = disposer.dispose_dir(sub)
                item.outcome = "candidate" if disposer.dry_run else "done"
                report.files += 1
                report.bytes_freed += item.bytes
            except (OSError, ValueError) as exc:
                item.outcome = "error"
                item.error = str(exc)
                report.errors.append(f"{sub}: {exc}")
            manifest.add(item)
    return report


def iter_legacy_queen_sessions() -> Iterator[Path]:
    """Queen session dirs under the pre-v3 HIVE_HOME/agents/queens tree.

    NOTE: HIVE_HOME/agents is NOT wholly legacy — v3 reuses it for live
    agent storage (colony worker stores, cloud-sync queen-session
    destinations, framework agents like credential_tester; see
    storage/migrate_v3.py). The janitor therefore never deletes the tree.
    Only the old queen DM session TRANSCRIPT dirs get the same tier-3
    hygiene (orphan spillovers + events rewrite) as current sessions —
    which preserves the transcript itself — and each one still passes the
    full SafetyContext gate.
    """
    legacy_queens = config.HIVE_HOME / "agents" / "queens"
    if legacy_queens.is_dir():
        yield from sorted(legacy_queens.glob("*/sessions/session_*"))


def find_junk_entries(min_bytes: int) -> list[tuple[Path, int]]:
    """Top-level HIVE_HOME entries outside the known layout, above a size floor."""
    hive_home = config.HIVE_HOME
    out: list[tuple[Path, int]] = []
    if not hive_home.is_dir():
        return out
    known = KEEP_ALWAYS | KNOWN_ENTRIES
    try:
        entries = sorted(hive_home.iterdir())
    except OSError:
        return out
    for p in entries:
        if p.name in known or p.name.startswith("."):
            continue
        try:
            size = p.stat().st_size if p.is_file() else _dir_size(p)[1]
        except OSError:
            continue
        if size >= min_bytes:
            out.append((p, size))
    return out
