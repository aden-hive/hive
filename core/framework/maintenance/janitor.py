"""Janitor run orchestration: global lock, tier sequencing, report + manifest.

``run_once`` is synchronous (pure filesystem work). The API route builds
a SafetyContext on the event loop first, then dispatches here in an
executor; the CLI runs it directly. Dry-run is the default everywhere —
callers must pass ``execute=True`` to delete anything.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from framework import config
from framework.maintenance import retention
from framework.maintenance.retention import (
    DeleteDisposer,
    DryRunDisposer,
    Manifest,
    SafetyContext,
    TargetReport,
)
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)

_GLOBAL_LOCK_TTL_S = 2 * 3600.0
_REPORT_FILENAME = "last_janitor_report.json"
_SERVER_MARKER_FILENAME = "server.lock"


def _pid_alive(pid: int) -> bool:
    """Cross-platform liveness probe (mirrors SessionManager._is_pid_alive)."""
    import platform

    if platform.system() == "Windows":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def server_marker_path() -> Path:
    return maintenance_dir() / _SERVER_MARKER_FILENAME


def write_server_marker(port: int | None = None) -> None:
    """Record that a live runtime owns this HIVE_HOME (written at startup).

    This is what lets an offline CLI janitor detect a server it cannot
    reach by port probe (the desktop app uses an ephemeral port + auth).
    """
    path = server_marker_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_write(path) as f:
            json.dump({"pid": os.getpid(), "port": port, "started_at": time.time()}, f)
    except OSError:
        logger.warning("janitor: failed to write server marker", exc_info=True)


def clear_server_marker() -> None:
    try:
        marker = json.loads(server_marker_path().read_text(encoding="utf-8"))
        if marker.get("pid") == os.getpid():
            server_marker_path().unlink(missing_ok=True)
    except (OSError, json.JSONDecodeError):
        pass


def live_server_owns_hive_home() -> bool:
    """True when the server marker names a still-running process."""
    try:
        marker = json.loads(server_marker_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    pid = marker.get("pid")
    return isinstance(pid, int) and pid != os.getpid() and _pid_alive(pid)


@dataclass
class JanitorReport:
    started_at: float
    finished_at: float = 0.0
    dry_run: bool = True
    mode: str = "archive"
    tiers: list[int] = field(default_factory=list)
    targets: list[TargetReport] = field(default_factory=list)
    manifest_path: str = ""
    archive_path: str = ""
    error: str = ""

    def total_bytes(self) -> int:
        return sum(t.bytes_freed for t in self.targets)

    def total_files(self) -> int:
        return sum(t.files for t in self.targets)

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "dry_run": self.dry_run,
            "mode": self.mode,
            "tiers": self.tiers,
            "total_bytes": self.total_bytes(),
            "total_files": self.total_files(),
            "targets": [t.to_dict() for t in self.targets],
            "manifest_path": self.manifest_path,
            "archive_path": self.archive_path,
            "error": self.error,
        }


def maintenance_dir() -> Path:
    return config.HIVE_HOME / "maintenance"


def _global_lock_path() -> Path:
    return maintenance_dir() / "janitor.lock"


def _acquire_global_lock(now: float) -> bool:
    lock = _global_lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        if now - lock.stat().st_mtime < _GLOBAL_LOCK_TTL_S:
            return False
        lock.unlink(missing_ok=True)  # stale takeover
    except OSError:
        pass
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "started_at": now}, f)
    return True


def _release_global_lock() -> None:
    _global_lock_path().unlink(missing_ok=True)


def load_last_report() -> dict | None:
    path = maintenance_dir() / _REPORT_FILENAME
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_report(report: JanitorReport) -> None:
    path = maintenance_dir() / _REPORT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_write(path) as f:
        json.dump(report.to_dict(), f, indent=2)


def _write_manifest(manifest: Manifest, started_at: float) -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(started_at))
    path = maintenance_dir() / f"prune_manifest-{stamp}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            for item in manifest.items:
                f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("janitor: failed to write manifest %s", path, exc_info=True)
        return ""
    return str(path)


def _build_disposer(cfg, execute: bool):
    """Disposer for tiers 2/3 + one-time targets (tier 1 always deletes)."""
    if not execute:
        return DryRunDisposer()
    if cfg.mode == "archive":
        from framework.maintenance.archive import ArchiveDisposer

        archive_dir = Path(cfg.archive_dir).expanduser() if cfg.archive_dir else None
        return ArchiveDisposer(archive_dir=archive_dir)
    return DeleteDisposer()


def run_once(
    safety: SafetyContext,
    cfg=None,
    *,
    tiers: set[int] = frozenset({1, 2, 3}),
    execute: bool = False,
    include_legacy: bool = False,
    include_junk: bool = False,
    process_start_ts: float | None = None,
) -> JanitorReport:
    """One full janitor pass. Synchronous; safe to run in an executor.

    ``execute=False`` (the default) is a pure measurement pass: nothing
    is modified, and the manifest lists every candidate with the bytes a
    real run would free.
    """
    cfg = cfg or config.get_retention_config()
    report = JanitorReport(
        started_at=safety.now,
        dry_run=not execute,
        mode=cfg.mode,
        tiers=sorted(tiers),
    )
    if not cfg.enabled:
        report.error = "retention disabled (kill switch)"
        report.finished_at = time.time()
        return report

    # Defense in depth for the CLI path: an offline SafetyContext has an
    # empty protected set, so destructive tiers must never run while a
    # live server owns this HIVE_HOME (the port probe can't see the
    # desktop runtime — ephemeral port + auth — but the marker can).
    destructive = bool((tiers & {2, 3}) or include_legacy or include_junk)
    if execute and destructive and safety.offline and live_server_owns_hive_home():
        report.error = (
            "a live runtime owns this HIVE_HOME (maintenance/server.lock); run tiers 2/3 through POST /api/maintenance/janitor/run or stop the server"
        )
        report.finished_at = time.time()
        return report

    manifest = Manifest()
    tier1_disposer = DeleteDisposer() if execute else DryRunDisposer()
    try:
        # Built BEFORE the global lock: a failing archive-dir setup must
        # not leave a 2h lockout behind.
        disposer = _build_disposer(cfg, execute)
    except (OSError, ValueError) as exc:
        report.error = f"disposer setup failed: {exc}"
        report.finished_at = time.time()
        report.manifest_path = _write_manifest(manifest, report.started_at)
        _save_report(report)
        return report

    if execute and not _acquire_global_lock(safety.now):
        closer = getattr(disposer, "close", None)
        if callable(closer):
            closer()
        report.error = "another janitor run is in progress"
        report.finished_at = time.time()
        return report

    def pace() -> None:
        if cfg.io_sleep_ms > 0:
            time.sleep(cfg.io_sleep_ms / 1000.0)

    try:
        if execute:
            report.targets.append(retention.sweep_janitor_leftovers(manifest))

        if 1 in tiers:
            hive_home = config.HIVE_HOME
            tier1_specs = (
                ("event_logs", cfg.event_logs_days, 1),
                # keep_newest 1 (not 0): the offline CLI janitor runs with
                # process_start_ts=None, so this is the only protection for
                # the file a dev's live opt-in logger holds open.
                ("llm_logs", cfg.llm_logs_days, 1),
                ("compaction_log", cfg.compaction_log_days, 0),
                ("tool-artifacts", cfg.tool_artifacts_days, 0),
                ("logs", cfg.rotated_logs_days, 2),
            )
            for name, days, keep in tier1_specs:
                report.targets.append(
                    retention.prune_aged_dir(
                        hive_home / name,
                        target=name,
                        max_age_days=days,
                        disposer=tier1_disposer,
                        manifest=manifest,
                        keep_newest=keep,
                        process_start_ts=process_start_ts,
                        now=safety.now,
                        pace=pace,
                    )
                )

        if 2 in tiers:
            tier2 = TargetReport(name="worker_deep_clean", tier=2)
            for colony_id, worker_id, wdir in retention.iter_worker_sessions():
                ok, _reason = safety.is_safe_to_prune(wdir, min_age_days=cfg.worker_deep_clean_days)
                if not ok:
                    tier2.skipped += 1
                    continue
                # A live spawning queen may still resume this worker.
                meta = retention._read_json(wdir / "meta.json")
                if meta.get("queen_session_id") in safety.protected_session_ids:
                    tier2.skipped += 1
                    continue
                sub = retention.deep_clean_worker(colony_id, worker_id, wdir, disposer=disposer, manifest=manifest)
                tier2.files += sub.files
                tier2.bytes_freed += sub.bytes_freed
                tier2.errors.extend(sub.errors)
                pace()
            report.targets.append(tier2)

        if 3 in tiers or include_legacy:
            tier3 = TargetReport(name="queen_hygiene", tier=3)
            # Dedupe by resolved path: in layouts where QUEENS_DIR is the
            # legacy tree the two iterators overlap.
            session_dirs: dict[str, Path] = {}
            if 3 in tiers:
                for session_dir in retention.iter_queen_sessions():
                    session_dirs[str(session_dir.resolve())] = session_dir
            if include_legacy:
                for session_dir in retention.iter_legacy_queen_sessions():
                    session_dirs.setdefault(str(session_dir.resolve()), session_dir)
            for session_dir in session_dirs.values():
                ok, _reason = safety.is_safe_to_prune(session_dir, min_age_days=cfg.queen_hygiene_days)
                if not ok:
                    tier3.skipped += 1
                    continue
                sub = retention.prune_queen_session(session_dir, cfg=cfg, safety=safety, disposer=disposer, manifest=manifest)
                tier3.files += sub.files
                tier3.bytes_freed += sub.bytes_freed
                tier3.skipped += sub.skipped
                tier3.errors.extend(sub.errors)
                pace()
            report.targets.append(tier3)

        if include_legacy:
            report.targets.append(retention.sweep_orphan_message_index(DeleteDisposer() if execute else DryRunDisposer(), manifest))

        junk = retention.find_junk_entries(cfg.junk_min_bytes)
        junk_report = TargetReport(name="junk", tier=0)
        for path, size in junk:
            item = retention.PruneItem(
                path=str(path),
                bytes=size,
                tier=0,
                target="junk",
                action="archive" if getattr(disposer, "archives", False) else "delete",
                reason="top-level entry outside known layout",
            )
            if include_junk and execute:
                try:
                    if path.is_dir():
                        files, freed = disposer.dispose_dir(path)
                        junk_report.files += files
                    else:
                        freed = disposer.dispose_file(path)
                        junk_report.files += 1
                    junk_report.bytes_freed += freed
                    item.outcome = "done"
                except (OSError, ValueError) as exc:
                    item.outcome = "error"
                    item.error = str(exc)
                    junk_report.errors.append(f"{path}: {exc}")
            else:
                item.outcome = "candidate"
                junk_report.skipped += 1
            manifest.add(item)
        report.targets.append(junk_report)

    except Exception as exc:  # never lose the partial report
        logger.exception("janitor: run failed")
        report.error = str(exc)
    finally:
        closer = getattr(disposer, "close", None)
        if callable(closer):
            archive_path = closer()
            if archive_path:
                report.archive_path = str(archive_path)
        if execute:
            _release_global_lock()

    report.finished_at = time.time()
    report.manifest_path = _write_manifest(manifest, report.started_at)
    _save_report(report)
    logger.info(
        "janitor: %s freed %.1f MB across %d files (tiers=%s, mode=%s)",
        "would have" if report.dry_run else "run",
        report.total_bytes() / 1e6,
        report.total_files(),
        report.tiers,
        report.mode,
    )
    return report
