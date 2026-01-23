"""
CLI commands for goal-based testing.

Provides commands:
- test-run: Run tests for an agent
- test-debug: Debug a failed test
- test-list: List tests for a goal
- test-stats: Show test statistics
"""

import argparse
import os
import subprocess
from pathlib import Path

from framework.testing.test_storage import TestStorage


DEFAULT_STORAGE_PATH = Path("exports")


def register_testing_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register testing CLI commands."""

    # test-run
    run_parser = subparsers.add_parser(
        "test-run",
        help="Run tests for an agent",
    )
    run_parser.add_argument(
        "agent_path",
        help="Path to agent export folder",
    )
    run_parser.add_argument(
        "--goal",
        "-g",
        required=True,
        help="Goal ID to run tests for",
    )
    run_parser.add_argument(
        "--parallel",
        "-p",
        type=int,
        default=-1,
        help="Number of parallel workers (-1 for auto, 0 for sequential)",
    )
    run_parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first failure",
    )
    run_parser.add_argument(
        "--type",
        choices=["constraint", "success", "edge_case", "all"],
        default="all",
        help="Type of tests to run",
    )
    run_parser.set_defaults(func=cmd_test_run)

    # test-debug
    debug_parser = subparsers.add_parser(
        "test-debug",
        help="Debug a failed test by re-running with verbose output",
    )
    debug_parser.add_argument(
        "agent_path",
        help="Path to agent export folder (e.g., exports/my_agent)",
    )
    debug_parser.add_argument(
        "test_name",
        help="Name of the test function (e.g., test_constraint_foo)",
    )
    debug_parser.add_argument(
        "--goal",
        "-g",
        default="",
        help="Goal ID (optional, for display only)",
    )
    debug_parser.set_defaults(func=cmd_test_debug)

    # test-list
    list_parser = subparsers.add_parser(
        "test-list",
        help="List tests for a goal",
    )
    list_parser.add_argument(
        "goal_id",
        help="Goal ID",
    )
    list_parser.add_argument(
        "--status",
        choices=["pending", "approved", "modified", "rejected", "all"],
        default="all",
        help="Filter by approval status",
    )
    list_parser.set_defaults(func=cmd_test_list)

    # test-stats
    stats_parser = subparsers.add_parser(
        "test-stats",
        help="Show test statistics for a goal",
    )
    stats_parser.add_argument(
        "goal_id",
        help="Goal ID",
    )
    stats_parser.set_defaults(func=cmd_test_stats)


def cmd_test_run(args: argparse.Namespace) -> int:
    """Run tests for an agent using pytest subprocess."""
    agent_path = Path(args.agent_path)
    tests_dir = agent_path / "tests"

    if not tests_dir.exists():
        print(f"Error: Tests directory not found: {tests_dir}")
        print("Hint: Generate and approve tests first using test-generate")
        return 1

    # Build pytest command
    cmd = ["pytest"]

    # Add test path(s) based on type filter
    if args.type == "all":
        cmd.append(str(tests_dir))
    else:
        type_to_file = {
            "constraint": "test_constraints.py",
            "success": "test_success_criteria.py",
            "edge_case": "test_edge_cases.py",
        }
        if args.type in type_to_file:
            test_file = tests_dir / type_to_file[args.type]
            if test_file.exists():
                cmd.append(str(test_file))
            else:
                print(f"Error: Test file not found: {test_file}")
                return 1

    # Add flags
    cmd.append("-v")  # Always verbose for CLI
    if args.fail_fast:
        cmd.append("-x")

    # Parallel execution
    if args.parallel > 0:
        cmd.extend(["-n", str(args.parallel)])
    elif args.parallel == -1:
        cmd.extend(["-n", "auto"])

    cmd.append("--tb=short")

    # Set PYTHONPATH to project root
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    # Find project root (parent of core/)
    project_root = Path(__file__).parent.parent.parent.parent.resolve()
    env["PYTHONPATH"] = f"{project_root}:{pythonpath}"

    print(f"Running: {' '.join(cmd)}\n")

    # Run pytest
    try:
        result = subprocess.run(
            cmd,
            env=env,
            timeout=600,  # 10 minute timeout
        )
    except subprocess.TimeoutExpired:
        print("Error: Test execution timed out after 10 minutes")
        return 1
    except Exception as e:
        print(f"Error: Failed to run pytest: {e}")
        return 1

    return result.returncode


def cmd_test_debug(args: argparse.Namespace) -> int:
    """Debug a failed test by re-running with verbose output."""
    import subprocess

    agent_path = Path(args.agent_path)
    test_name = args.test_name
    tests_dir = agent_path / "tests"

    if not tests_dir.exists():
        print(f"Error: Tests directory not found: {tests_dir}")
        return 1

    # Find which file contains the test
    test_file = None
    for py_file in tests_dir.glob("test_*.py"):
        content = py_file.read_text()
        if f"def {test_name}" in content or f"async def {test_name}" in content:
            test_file = py_file
            break

    if not test_file:
        print(f"Error: Test '{test_name}' not found in {tests_dir}")
        print("Hint: Use test-list to see available tests")
        return 1

    # Run specific test with verbose output
    cmd = [
        "pytest",
        f"{test_file}::{test_name}",
        "-vvs",  # Very verbose with stdout
        "--tb=long",  # Full traceback
    ]

    # Set PYTHONPATH to project root
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    project_root = Path(__file__).parent.parent.parent.parent.resolve()
    env["PYTHONPATH"] = f"{project_root}:{pythonpath}"

    print(f"Running: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(
            cmd,
            env=env,
            timeout=120,  # 2 minute timeout for single test
        )
    except subprocess.TimeoutExpired:
        print("Error: Test execution timed out after 2 minutes")
        return 1
    except Exception as e:
        print(f"Error: Failed to run pytest: {e}")
        return 1

    return result.returncode


def cmd_test_list(args: argparse.Namespace) -> int:
    """List tests for a goal."""
    storage = TestStorage(DEFAULT_STORAGE_PATH / args.goal_id)
    tests = storage.get_tests_by_goal(args.goal_id)

    # Filter by status
    if args.status != "all":
        from framework.testing.test_case import ApprovalStatus
        try:
            filter_status = ApprovalStatus(args.status)
            tests = [t for t in tests if t.approval_status == filter_status]
        except ValueError:
            pass

    if not tests:
        print(f"No tests found for goal {args.goal_id}")
        return 0

    print(f"Tests for goal {args.goal_id}:\n")
    for t in tests:
        status_icon = {
            "pending": "⏳",
            "approved": "✓",
            "modified": "✓*",
            "rejected": "✗",
        }.get(t.approval_status.value, "?")

        result_icon = ""
        if t.last_result:
            result_icon = " [PASS]" if t.last_result == "passed" else " [FAIL]"

        print(f"  {status_icon} {t.test_name} ({t.test_type.value}){result_icon}")
        print(f"      ID: {t.id}")
        print(f"      Criteria: {t.parent_criteria_id}")
        if t.llm_confidence:
            print(f"      Confidence: {t.llm_confidence:.0%}")
        print()

    return 0


def cmd_test_stats(args: argparse.Namespace) -> int:
    """Show test statistics."""
    storage = TestStorage(DEFAULT_STORAGE_PATH / args.goal_id)
    stats = storage.get_stats()

    print(f"Statistics for goal {args.goal_id}:\n")
    print(f"  Total tests: {stats['total_tests']}")
    print("\n  By approval status:")
    for status, count in stats["by_approval"].items():
        print(f"    {status}: {count}")

    # Get pass/fail stats
    tests = storage.get_approved_tests(args.goal_id)
    passed = sum(1 for t in tests if t.last_result == "passed")
    failed = sum(1 for t in tests if t.last_result == "failed")
    not_run = sum(1 for t in tests if t.last_result is None)

    print("\n  Execution results:")
    print(f"    Passed: {passed}")
    print(f"    Failed: {failed}")
    print(f"    Not run: {not_run}")

    return 0
