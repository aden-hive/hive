"""CLI for the retention janitor.

    hive janitor run [--execute] [--tiers 1,2,3] [--legacy] [--junk]
                     [--no-archive] [--port 8787] [-v]
    hive janitor status

Dry-run is the default: without ``--execute`` nothing is deleted and the
run produces the full would-prune report + manifest.

Offline safety: the CLI cannot see a running server's live sessions. If
a local runtime responds on the health endpoint, tiers 2/3 (and
--legacy/--junk) are refused with a pointer to the API endpoint, which
snapshots the live-session registry before pruning. Tier 1 stays
allowed offline — it only ages out debug logs and always skips the
newest / recently-written file per directory.
"""

from __future__ import annotations

import argparse
import json
import time
from urllib import error as urlerror, request as urlrequest


def register_janitor_commands(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "janitor",
        help="Data-retention janitor (dry-run by default)",
        description="Prune aged debug logs, finished-worker transcripts, and cold-session bloat from HIVE_HOME.",
    )
    sub = p.add_subparsers(dest="janitor_command", required=True)

    run = sub.add_parser("run", help="Run a janitor pass (dry-run unless --execute)")
    run.add_argument("--execute", action="store_true", help="Actually delete/archive (default: dry-run report only)")
    run.add_argument("--tiers", type=str, default="1,2,3", help="Comma-separated tiers to run (default: 1,2,3)")
    run.add_argument("--legacy", action="store_true", help="One-time: archive+delete legacy agents/ tree + orphaned index sweep")
    run.add_argument("--junk", action="store_true", help="Also delete oversized top-level entries outside the known layout")
    run.add_argument("--no-archive", action="store_true", help="Delete outright instead of archiving first")
    run.add_argument("--port", type=int, default=8787, help="Local runtime port to probe for live-server safety check")
    run.add_argument("--verbose", "-v", action="store_true", help="Print every manifest line")
    run.set_defaults(func=cmd_janitor_run)

    status = sub.add_parser("status", help="Show the last janitor report")
    status.set_defaults(func=cmd_janitor_status)


def _server_is_up(port: int) -> bool:
    """True when any Hive runtime plausibly serves this HIVE_HOME.

    Primary signal: the server marker under HIVE_HOME (works for the
    desktop runtime, which binds an ephemeral port with auth that a port
    probe can never see). Secondary: an HTTP probe of the given port —
    where ANY HTTP response, including 401, proves a listener.
    """
    from framework.maintenance.janitor import live_server_owns_hive_home

    if live_server_owns_hive_home():
        return True
    try:
        with urlrequest.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2):
            return True
    except urlerror.HTTPError:
        return True  # 401/403/...: something IS serving on this port
    except (urlerror.URLError, OSError, ValueError):
        return False


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def cmd_janitor_run(args: argparse.Namespace) -> int:
    from framework import config
    from framework.maintenance.janitor import run_once
    from framework.maintenance.retention import SafetyContext

    try:
        tiers = {int(t) for t in str(args.tiers).split(",") if t.strip()}
    except ValueError:
        print(f"invalid --tiers value: {args.tiers!r}")
        return 2
    if not tiers <= {1, 2, 3}:
        print(f"invalid --tiers value: {args.tiers!r} (allowed: 1,2,3)")
        return 2

    cfg = config.get_retention_config()
    if args.no_archive:
        cfg.mode = "delete"

    # Dry-run is pure measurement — only an EXECUTE of destructive tiers
    # needs the live-server refusal (execute is double-guarded: run_once
    # re-checks the server marker before deleting anything).
    needs_session_safety = bool(args.execute) and bool((tiers & {2, 3}) or args.legacy or args.junk)
    if needs_session_safety and _server_is_up(args.port):
        print(
            "A live Hive runtime owns this HIVE_HOME (server marker or port probe).\n"
            "Tiers 2/3 and --legacy/--junk must run through the server so live sessions\n"
            "are protected — POST /api/maintenance/janitor/run on the runtime's port, e.g.:\n"
            f"  curl -X POST http://127.0.0.1:<port>/api/maintenance/janitor/run "
            '-H "Content-Type: application/json" '
            f'-d \'{{"execute": {str(bool(args.execute)).lower()}, "tiers": {sorted(tiers)}}}\'\n'
            "Or stop the desktop app / server and re-run this command."
        )
        return 1

    safety = SafetyContext.for_offline(cfg)
    started = time.time()
    report = run_once(
        safety,
        cfg,
        tiers=tiers,
        execute=bool(args.execute),
        include_legacy=bool(args.legacy),
        include_junk=bool(args.junk),
    )

    _print_report(report.to_dict(), verbose=bool(args.verbose))
    print(f"\nelapsed: {time.time() - started:.1f}s")
    if report.error:
        print(f"ERROR: {report.error}")
        return 1
    if report.dry_run:
        print("dry-run only — re-run with --execute to apply")
    return 0


def cmd_janitor_status(args: argparse.Namespace) -> int:
    from framework.maintenance.janitor import load_last_report

    report = load_last_report()
    if report is None:
        print("no janitor run recorded")
        return 1
    _print_report(report, verbose=False)
    return 0


def _print_report(report: dict, *, verbose: bool) -> None:
    header = "DRY-RUN (nothing deleted)" if report.get("dry_run") else f"EXECUTED (mode={report.get('mode')})"
    print(f"janitor report — {header}")
    print(f"  tiers: {report.get('tiers')}   started: {time.ctime(report.get('started_at', 0))}")
    for target in report.get("targets", []):
        if not (target.get("files") or target.get("bytes_freed") or target.get("skipped") or target.get("errors")):
            continue
        line = f"  {target['name']:<22} files={target['files']:<7} freed={_human(target['bytes_freed']):<10} skipped={target['skipped']}"
        if target.get("errors"):
            line += f" errors={len(target['errors'])}"
        print(line)
    print(f"  TOTAL: {_human(report.get('total_bytes', 0))} across {report.get('total_files', 0)} files")
    if report.get("archive_path"):
        print(f"  archive: {report['archive_path']}")
    if report.get("manifest_path"):
        print(f"  manifest: {report['manifest_path']}")
        if verbose:
            try:
                with open(report["manifest_path"], encoding="utf-8") as f:
                    for line in f:
                        item = json.loads(line)
                        print(f"    [{item['outcome']:<9}] {item['action']:<9} {_human(item['bytes']):<10} {item['path']}  ({item['reason']})")
            except (OSError, json.JSONDecodeError, KeyError):
                pass
