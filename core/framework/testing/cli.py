"""
CLI commands for goal-based testing.

Provides commands:
- test-generate: Generate tests from a goal
- test-approve: Review and approve pending tests
- test-run: Run tests for an agent
- test-debug: Debug a failed test
"""

import argparse
import os
import subprocess
from pathlib import Path

from framework.graph.goal import Goal
from framework.testing.test_storage import TestStorage
from framework.testing.constraint_gen import ConstraintTestGenerator
from framework.testing.success_gen import SuccessCriteriaTestGenerator
from framework.testing.approval_cli import interactive_approval


DEFAULT_STORAGE_PATH = Path("exports")


def register_testing_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register testing CLI commands."""

    # test-generate
    gen_parser = subparsers.add_parser(
        "test-generate",
        help="Generate tests from goal criteria",
    )
    gen_parser.add_argument(
        "goal_file",
        help="Path to goal JSON file",
    )
    gen_parser.add_argument(
        "--type",
        choices=["constraint", "success", "all"],
        default="all",
        help="Type of tests to generate",
    )
    gen_parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Skip interactive approval (use with caution)",
    )
    gen_parser.add_argument(
        "--output",
        "-o",
        help="Output directory for tests (default: data/tests/<goal_id>)",
    )
    gen_parser.set_defaults(func=cmd_test_generate)

    # test-approve
    approve_parser = subparsers.add_parser(
        "test-approve",
        help="Review and approve pending tests",
    )
    approve_parser.add_argument(
        "goal_id",
        help="Goal ID to review tests for",
    )
    approve_parser.add_argument(
        "--storage",
        help="Storage directory (default: data/tests/<goal_id>)",
    )
    approve_parser.set_defaults(func=cmd_test_approve)

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


def cmd_test_generate(args: argparse.Namespace) -> int:
    """Generate tests from a goal file."""
    # Load goal
    goal_path = Path(args.goal_file)
    if not goal_path.exists():
        print(f"Error: Goal file not found: {goal_path}")
        return 1

    with open(goal_path) as f:
        goal = Goal.model_validate_json(f.read())

    print(f"Loaded goal: {goal.name} ({goal.id})")

    # Determine output directory
    output_dir = Path(args.output) if args.output else DEFAULT_STORAGE_PATH / goal.id
    storage = TestStorage(output_dir)

    # Get LLM provider
    try:
        from framework.llm import AnthropicProvider
        llm = AnthropicProvider()
    except Exception as e:
        print(f"Error: Failed to initialize LLM provider: {e}")
        return 1

    all_tests = []

    # Generate constraint tests
    if args.type in ("constraint", "all"):
        print(f"\nGenerating constraint tests for {len(goal.constraints)} constraints...")
        generator = ConstraintTestGenerator(llm)
        constraint_tests = generator.generate(goal)
        all_tests.extend(constraint_tests)
        print(f"Generated {len(constraint_tests)} constraint tests")

    # Generate success criteria tests
    if args.type in ("success", "all"):
        print(f"\nGenerating success criteria tests for {len(goal.success_criteria)} criteria...")
        generator = SuccessCriteriaTestGenerator(llm)
        success_tests = generator.generate(goal)
        all_tests.extend(success_tests)
        print(f"Generated {len(success_tests)} success criteria tests")

    if not all_tests:
        print("\nNo tests generated.")
        return 0

    print(f"\nTotal tests generated: {len(all_tests)}")

    # Approval
    if args.auto_approve:
        print("\nAuto-approving all tests...")
        for test in all_tests:
            test.approve("cli-auto")
            storage.save_test(test)
        print(f"Saved {len(all_tests)} tests to {output_dir}")
    else:
        print("\nStarting interactive approval...")
        # Save pending tests first
        for test in all_tests:
            storage.save_test(test)

        results = interactive_approval(all_tests, storage)
        approved = sum(1 for r in results if r.action.value in ("approve", "modify"))
        print(f"\nApproved: {approved}/{len(all_tests)} tests")

    return 0


def cmd_test_approve(args: argparse.Namespace) -> int:
    """Review and approve pending tests."""
    storage_path = Path(args.storage) if args.storage else DEFAULT_STORAGE_PATH / args.goal_id
    storage = TestStorage(storage_path)

    pending = storage.get_pending_tests(args.goal_id)

    if not pending:
        print(f"No pending tests for goal {args.goal_id}")
        return 0

    print(f"Found {len(pending)} pending tests\n")

    results = interactive_approval(pending, storage)
    approved = sum(1 for r in results if r.action.value in ("approve", "modify"))
    print(f"\nApproved: {approved}/{len(pending)} tests")

    return 0


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
