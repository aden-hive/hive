"""
CLI commands for goal-based testing.

Provides commands:
- test-generate: Generate tests from a goal
- test-approve: Review and approve pending tests
- test-run: Run tests for an agent
- test-debug: Debug a failed test
"""

import argparse
import json
from pathlib import Path

from framework.graph.goal import Goal
from framework.testing.test_case import TestType
from framework.testing.test_storage import TestStorage
from framework.testing.constraint_gen import ConstraintTestGenerator
from framework.testing.success_gen import SuccessCriteriaTestGenerator
from framework.testing.approval_cli import interactive_approval
from framework.testing.parallel import ParallelTestRunner, ParallelConfig, AgentFactory
from framework.testing.debug_tool import DebugTool


DEFAULT_STORAGE_PATH = Path("data/tests")


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
        default=0,
        help="Number of parallel workers (0 for sequential)",
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
        help="Debug a failed test",
    )
    debug_parser.add_argument(
        "goal_id",
        help="Goal ID",
    )
    debug_parser.add_argument(
        "test_id",
        help="Test ID to debug",
    )
    debug_parser.add_argument(
        "--run-id",
        help="Runtime run ID for detailed logs",
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
    """Run tests for an agent."""
    storage = TestStorage(DEFAULT_STORAGE_PATH / args.goal)

    # Get approved tests
    tests = storage.get_approved_tests(args.goal)

    # Filter by type
    if args.type != "all":
        type_map = {
            "constraint": TestType.CONSTRAINT,
            "success": TestType.SUCCESS_CRITERIA,
            "edge_case": TestType.EDGE_CASE,
        }
        filter_type = type_map.get(args.type)
        if filter_type:
            tests = [t for t in tests if t.test_type == filter_type]

    if not tests:
        print(f"No approved tests found for goal {args.goal}")
        return 1

    print(f"Running {len(tests)} tests...\n")

    # Configure runner
    config = ParallelConfig(
        num_workers=args.parallel if args.parallel > 0 else 1,
        fail_fast=args.fail_fast,
    )

    # Run with progress - use AgentFactory for picklable parallel execution
    runner = ParallelTestRunner(config, storage)

    def on_result(result):
        status = "✓" if result.passed else "✗"
        print(f"  {status} {result.test_id} ({result.duration_ms}ms)")

    result = runner.run_all(
        goal_id=args.goal,
        agent_factory=AgentFactory(args.agent_path),
        tests=tests,
        on_result=on_result,
    )

    # Print summary
    print(f"\n{'=' * 40}")
    print(f"Results: {result.passed}/{result.total} passed ({result.pass_rate:.1%})")
    print(f"Duration: {result.duration_ms}ms")

    if not result.all_passed:
        print("\nFailed tests:")
        for r in result.get_failed_results():
            print(f"  - {r.test_id}: {r.error_message}")
            if r.error_category:
                print(f"    Category: {r.error_category.value}")

    return 0 if result.all_passed else 1


def cmd_test_debug(args: argparse.Namespace) -> int:
    """Debug a failed test."""
    storage = TestStorage(DEFAULT_STORAGE_PATH / args.goal_id)

    # Try to load runtime storage
    runtime_storage = None
    try:
        from framework.storage.backend import FileStorage
        runtime_storage = FileStorage(f"data/runtime/{args.goal_id}")
    except Exception:
        pass

    debug_tool = DebugTool(storage, runtime_storage)
    info = debug_tool.analyze(args.goal_id, args.test_id, args.run_id)

    # Print debug info
    print(f"Debug Info for: {info.test_name}")
    print("=" * 50)

    print(f"\nTest ID: {info.test_id}")
    print(f"Passed: {info.passed}")

    if info.error_category:
        print(f"\nError Category: {info.error_category}")
        print(f"Suggested Fix: {info.suggested_fix}")

    if info.error_message:
        print(f"\nError Message:\n{info.error_message}")

    if info.stack_trace:
        print(f"\nStack Trace:\n{info.stack_trace}")

    if info.iteration_guidance:
        print("\nIteration Guidance:")
        print(f"  Stage: {info.iteration_guidance.get('stage')}")
        print(f"  Action: {info.iteration_guidance.get('action')}")
        print(f"  Restart Required: {info.iteration_guidance.get('restart_required')}")

    print(f"\nInput:\n{json.dumps(info.input, indent=2)}")
    print(f"\nExpected:\n{json.dumps(info.expected, indent=2)}")
    print(f"\nActual:\n{json.dumps(info.actual, indent=2, default=str)}")

    return 0


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
