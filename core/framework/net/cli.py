"""
CLI subcommands for health checking, status reporting, and merge gates.

Registers:
    hive health           — Run all health checks once
    hive health --watch   — Continuous monitoring
    hive health --json    — JSON output
    hive gate             — Run merge-gate checks (TestSprite-style)
    hive gate --watch     — Continuous merge gate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from framework.net.health import (
    CheckResult,
    CodeScanningCheck,
    GitHubStatusCheck,
    HealthChecker,
    HealthStatus,
    HttpHealthCheck,
)
from framework.net.test_runner import (
    ContinuousTestRunner,
    TestConfig,
    TestSuite,
)

STATUS_SYMBOLS = {
    HealthStatus.HEALTHY: "✅",
    HealthStatus.DEGRADED: "⚠️ ",
    HealthStatus.UNHEALTHY: "❌",
    HealthStatus.PENDING: "⏳",
    HealthStatus.UNKNOWN: "❓",
}


def _print_result(result: CheckResult) -> None:
    symbol = STATUS_SYMBOLS.get(result.status, "❓")
    print(
        f"  {symbol} {result.name}: {result.status.value} "
        f"({result.latency_ms:.0f}ms) — {result.message}"
    )


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def _build_default_checks() -> list[Any]:
    """Build default health checks from environment variables."""
    checks: list[Any] = []
    token = os.environ.get("GITHUB_TOKEN", "")
    owner = os.environ.get("HIVE_GITHUB_OWNER", "")
    repo = os.environ.get("HIVE_GITHUB_REPO", "")

    if owner and repo:
        checks.append(
            GitHubStatusCheck(
                "github-ci",
                owner,
                repo,
                token=token if token else None,
                required_checks=[
                    "Analyze (python)",
                    "Lint Python",
                    "Test Python Framework (ubuntu-latest)",
                ],
            )
        )

    if token and owner and repo:
        checks.append(CodeScanningCheck("code-scanning", owner, repo, token=token))

    # Custom endpoints from HIVE_HEALTH_ENDPOINTS (comma-separated URLs)
    endpoints = os.environ.get("HIVE_HEALTH_ENDPOINTS", "")
    for url in endpoints.split(","):
        url = url.strip()
        if url:
            checks.append(HttpHealthCheck(f"endpoint:{url}", url))

    return checks


def _build_default_test_suites() -> list[TestConfig]:
    """Build default test suites for the repo."""
    return [
        TestConfig(
            name="unit-tests",
            suite=TestSuite.UNIT,
            command="uv run pytest tests/ -x -q --tb=short",
            timeout=120.0,
            required_for_merge=True,
            working_dir="core",
        ),
        TestConfig(
            name="lint",
            suite=TestSuite.UNIT,
            command="uv run ruff check core/ tools/",
            timeout=60.0,
            required_for_merge=True,
            working_dir=".",
        ),
    ]


# ---------------------------------------------------------------------------
# ``hive health`` subcommand
# ---------------------------------------------------------------------------


def _cmd_health(args: argparse.Namespace) -> int:
    checks = _build_default_checks()
    if not checks:
        print(
            "No health checks configured.\n"
            "Set GITHUB_TOKEN + HIVE_GITHUB_OWNER + HIVE_GITHUB_REPO env vars,\n"
            "or HIVE_HEALTH_ENDPOINTS=https://example.com/health"
        )
        return 1

    async def _run() -> int:
        checker = HealthChecker(checks, interval=args.interval)
        if args.watch:
            print(f"🔄 Watching health (every {args.interval}s). Ctrl+C to stop.\n")
            try:
                while True:
                    results = await checker.run_once()
                    if args.json:
                        print(json.dumps(checker.summary(), indent=2))
                    else:
                        overall = checker.overall_status
                        symbol = STATUS_SYMBOLS.get(overall, "❓")
                        print(f"\n{symbol} Overall: {overall.value}")
                        for r in results:
                            _print_result(r)
                    await asyncio.sleep(args.interval)
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\nStopped.")
            return 0
        else:
            results = await checker.run_once()
            if args.json:
                print(json.dumps(checker.summary(), indent=2))
            else:
                overall = checker.overall_status
                symbol = STATUS_SYMBOLS.get(overall, "❓")
                print(f"{symbol} Overall: {overall.value}\n")
                for r in results:
                    _print_result(r)
            return 0 if checker.overall_status == HealthStatus.HEALTHY else 1

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# ``hive gate`` subcommand (TestSprite-style merge gate)
# ---------------------------------------------------------------------------


def _cmd_gate(args: argparse.Namespace) -> int:
    suites = _build_default_test_suites()
    if not suites:
        print("No test suites configured.")
        return 1

    def _on_result(r: Any) -> None:
        if not args.json:
            symbol = "✅" if r.passed else "❌"
            status = "PASSED" if r.passed else "FAILED"
            print(f"  {symbol} {r.config.name}: {status} ({r.duration_ms:.0f}ms)")

    runner = ContinuousTestRunner(suites, on_result=_on_result)

    async def _run() -> int:
        if args.watch:
            print(f"🔄 Merge gate watcher (every {args.interval}s). Ctrl+C to stop.\n")
            try:
                while True:
                    await runner.run_all()
                    summary = runner.gate_summary
                    if args.json:
                        print(json.dumps(summary, indent=2))
                    else:
                        symbol = "✅" if summary["merge_ready"] else "❌"
                        print(
                            f"\n{symbol} Merge Gate: "
                            f"{'READY' if summary['merge_ready'] else 'BLOCKED'} "
                            f"({summary['passing']}/{summary['total']} passing)"
                        )
                    await asyncio.sleep(args.interval)
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\nStopped.")
            return 0
        else:
            print("🔍 Running merge gate checks...\n")
            await runner.run_all()
            summary = runner.gate_summary
            if args.json:
                print(json.dumps(summary, indent=2))
            else:
                symbol = "✅" if summary["merge_ready"] else "❌"
                print(
                    f"\n{symbol} Merge Gate: "
                    f"{'READY — safe to merge' if summary['merge_ready'] else 'BLOCKED'} "
                    f"({summary['passing']}/{summary['total']} passing)"
                )
            return 0 if summary["merge_ready"] else 1

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# Registration (called from framework/cli.py)
# ---------------------------------------------------------------------------


def register_health_commands(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register ``hive health`` and ``hive gate`` CLI subcommands."""

    # -- hive health ----------------------------------------------------------
    health_parser = subparsers.add_parser(
        "health",
        help="Run health checks (GitHub status, code scanning, endpoints)",
    )
    health_parser.add_argument(
        "--watch", "-w", action="store_true", help="Continuous monitoring"
    )
    health_parser.add_argument(
        "--json", "-j", action="store_true", help="Output as JSON"
    )
    health_parser.add_argument(
        "--interval", "-i", type=int, default=30, help="Watch interval in seconds"
    )
    health_parser.set_defaults(func=_cmd_health)

    # -- hive gate ------------------------------------------------------------
    gate_parser = subparsers.add_parser(
        "gate",
        help="Run merge-gate checks (TestSprite-style continuous validation)",
    )
    gate_parser.add_argument(
        "--watch", "-w", action="store_true", help="Continuous monitoring"
    )
    gate_parser.add_argument(
        "--json", "-j", action="store_true", help="Output as JSON"
    )
    gate_parser.add_argument(
        "--interval", "-i", type=int, default=60, help="Watch interval in seconds"
    )
    gate_parser.set_defaults(func=_cmd_gate)
