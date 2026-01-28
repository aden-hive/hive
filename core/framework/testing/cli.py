"""
CLI commands for goal-based testing.

Provides commands:
- test-run: Run tests for an agent
- test-debug: Debug a failed test
- test-list: List tests for an agent
- test-stats: Show test statistics for an agent
"""

import argparse
import ast
import os
import subprocess
from pathlib import Path


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
        help="List tests for an agent by scanning test files",
    )
    list_parser.add_argument(
        "agent_path",
        help="Path to agent export folder (e.g., exports/my_agent)",
    )
    list_parser.add_argument(
        "--type",
        choices=["constraint", "success", "edge_case", "all"],
        default="all",
        help="Filter by test type",
    )
    list_parser.set_defaults(func=cmd_test_list)

    # test-stats
    stats_parser = subparsers.add_parser(
        "test-stats",
        help="Show test statistics for an agent",
    )
    stats_parser.add_argument(
        "agent_path",
        help="Path to agent export folder (e.g., exports/my_agent)",
    )
    stats_parser.set_defaults(func=cmd_test_stats)

    # failures-list
    failures_list_parser = subparsers.add_parser(
        "failures-list",
        help="List recorded failures for an agent",
    )
    failures_list_parser.add_argument(
        "agent_path",
        help="Path to agent export folder (e.g., exports/my_agent)",
    )
    failures_list_parser.add_argument(
        "--goal",
        "-g",
        default="",
        help="Filter by goal ID",
    )
    failures_list_parser.add_argument(
        "--severity",
        choices=["critical", "error", "warning"],
        default="",
        help="Filter by severity level",
    )
    failures_list_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=20,
        help="Maximum number of failures to show",
    )
    failures_list_parser.set_defaults(func=cmd_failures_list)

    # failures-show
    failures_show_parser = subparsers.add_parser(
        "failures-show",
        help="Show details of a specific failure",
    )
    failures_show_parser.add_argument(
        "agent_path",
        help="Path to agent export folder (e.g., exports/my_agent)",
    )
    failures_show_parser.add_argument(
        "failure_id",
        help="Failure ID to show details for",
    )
    failures_show_parser.add_argument(
        "--goal",
        "-g",
        required=True,
        help="Goal ID the failure belongs to",
    )
    failures_show_parser.set_defaults(func=cmd_failures_show)

    # failures-stats
    failures_stats_parser = subparsers.add_parser(
        "failures-stats",
        help="Show failure statistics for an agent",
    )
    failures_stats_parser.add_argument(
        "agent_path",
        help="Path to agent export folder (e.g., exports/my_agent)",
    )
    failures_stats_parser.add_argument(
        "--goal",
        "-g",
        default="",
        help="Goal ID to get stats for (omit for overall stats)",
    )
    failures_stats_parser.set_defaults(func=cmd_failures_stats)


def cmd_test_run(args: argparse.Namespace) -> int:
    """Run tests for an agent using pytest subprocess."""
    agent_path = Path(args.agent_path)
    tests_dir = agent_path / "tests"

    if not tests_dir.exists():
        print(f"Error: Tests directory not found: {tests_dir}")
        print(
            "Hint: Use generate_constraint_tests/generate_success_tests MCP tools, "
            "then write tests with Write tool"
        )
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


def _scan_test_files(tests_dir: Path) -> list[dict]:
    """Scan test files and extract test functions using AST parsing."""
    tests = []

    for test_file in sorted(tests_dir.glob("test_*.py")):
        try:
            content = test_file.read_text()
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("test_"):
                        # Determine test type from filename
                        if "constraint" in test_file.name:
                            test_type = "constraint"
                        elif "success" in test_file.name:
                            test_type = "success"
                        elif "edge" in test_file.name:
                            test_type = "edge_case"
                        else:
                            test_type = "unknown"

                        docstring = ast.get_docstring(node) or ""

                        tests.append(
                            {
                                "test_name": node.name,
                                "file": test_file.name,
                                "line": node.lineno,
                                "test_type": test_type,
                                "is_async": isinstance(node, ast.AsyncFunctionDef),
                                "description": docstring[:100] if docstring else None,
                            }
                        )
        except SyntaxError as e:
            print(f"  Warning: Syntax error in {test_file.name}: {e}")
        except Exception as e:
            print(f"  Warning: Error parsing {test_file.name}: {e}")

    return tests


def cmd_test_list(args: argparse.Namespace) -> int:
    """List tests for an agent by scanning pytest files."""
    agent_path = Path(args.agent_path)
    tests_dir = agent_path / "tests"

    if not tests_dir.exists():
        print(f"No tests directory found at: {tests_dir}")
        print(
            "Hint: Generate tests using the MCP generate_constraint_tests "
            "or generate_success_tests tools"
        )
        return 0

    tests = _scan_test_files(tests_dir)

    # Filter by type if specified
    if args.type != "all":
        tests = [t for t in tests if t["test_type"] == args.type]

    if not tests:
        print(f"No tests found in {tests_dir}")
        return 0

    print(f"Tests in {tests_dir}:\n")

    # Group by type
    by_type: dict[str, list] = {}
    for t in tests:
        ttype = t["test_type"]
        if ttype not in by_type:
            by_type[ttype] = []
        by_type[ttype].append(t)

    for test_type, type_tests in sorted(by_type.items()):
        print(f"  [{test_type.upper()}] ({len(type_tests)} tests)")
        for t in type_tests:
            async_marker = "async " if t["is_async"] else ""
            desc = f" - {t['description']}" if t.get("description") else ""
            print(f"    {async_marker}{t['test_name']}{desc}")
            print(f"        {t['file']}:{t['line']}")
        print()

    print(f"Total: {len(tests)} tests")
    print(f"\nRun with: pytest {tests_dir} -v")

    return 0


def cmd_test_stats(args: argparse.Namespace) -> int:
    """Show test statistics by scanning pytest files."""
    agent_path = Path(args.agent_path)
    tests_dir = agent_path / "tests"

    if not tests_dir.exists():
        print(f"No tests directory found at: {tests_dir}")
        return 0

    tests = _scan_test_files(tests_dir)

    if not tests:
        print(f"No tests found in {tests_dir}")
        return 0

    print(f"Test Statistics for {agent_path}:\n")
    print(f"  Total tests: {len(tests)}")

    # Count by type
    by_type: dict[str, int] = {}
    async_count = 0
    for t in tests:
        ttype = t["test_type"]
        by_type[ttype] = by_type.get(ttype, 0) + 1
        if t["is_async"]:
            async_count += 1

    print("\n  By type:")
    for test_type, count in sorted(by_type.items()):
        print(f"    {test_type}: {count}")

    print(f"\n  Async tests: {async_count}/{len(tests)}")

    # List test files
    test_files = list(tests_dir.glob("test_*.py"))
    print(f"\n  Test files ({len(test_files)}):")
    for f in sorted(test_files):
        count = sum(1 for t in tests if t["file"] == f.name)
        print(f"    {f.name} ({count} tests)")

    print(f"\nRun all tests: pytest {tests_dir} -v")

    return 0


def cmd_failures_list(args: argparse.Namespace) -> int:
    """List recorded failures for an agent."""
    from framework.testing.failure_storage import FailureStorage
    from framework.testing.failure_record import FailureSeverity
    
    agent_path = Path(args.agent_path)
    failures_path = agent_path / ".aden" / "failures"
    
    if not failures_path.exists():
        print(f"No failures recorded for agent at: {agent_path}")
        print("Failures are recorded during agent execution when errors occur.")
        return 0
    
    storage = FailureStorage(failures_path)
    
    # Get failures
    if args.goal:
        # Filter by severity if provided
        severity = None
        if args.severity:
            severity = FailureSeverity(args.severity)
        failures = storage.get_failures_by_goal(args.goal, limit=args.limit, severity=severity)
    else:
        failures = storage.get_recent_failures(limit=args.limit)
    
    if not failures:
        if args.goal:
            print(f"No failures found for goal: {args.goal}")
        else:
            print("No failures recorded.")
        return 0
    
    print(f"Recorded Failures ({len(failures)} shown):\n")
    
    for f in failures:
        severity_icon = {"critical": "🔴", "error": "🟠", "warning": "🟡"}.get(f.severity.value, "⚪")
        timestamp = f.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"  {severity_icon} [{f.id}]")
        print(f"      Goal: {f.goal_id}")
        if f.node_id:
            print(f"      Node: {f.node_id}")
        print(f"      Error: {f.error_type}: {f.error_message[:80]}...")
        print(f"      Source: {f.source.value}")
        print(f"      Time: {timestamp}")
        print()
    
    print(f"\nShow details: python -m framework failures-show {args.agent_path} <failure_id> --goal <goal_id>")
    
    return 0


def cmd_failures_show(args: argparse.Namespace) -> int:
    """Show detailed information about a specific failure."""
    from framework.testing.failure_storage import FailureStorage
    
    agent_path = Path(args.agent_path)
    failures_path = agent_path / ".aden" / "failures"
    
    if not failures_path.exists():
        print(f"No failures recorded for agent at: {agent_path}")
        return 1
    
    storage = FailureStorage(failures_path)
    failure = storage.get_failure(args.goal, args.failure_id)
    
    if not failure:
        print(f"Failure not found: {args.failure_id}")
        print(f"Hint: Use 'failures-list' to see available failure IDs")
        return 1
    
    severity_icon = {"critical": "🔴", "error": "🟠", "warning": "🟡"}.get(failure.severity.value, "⚪")
    
    print(f"Failure Details: {failure.id}")
    print("=" * 60)
    print()
    
    print(f"  {severity_icon} Severity: {failure.severity.value.upper()}")
    print(f"  Source: {failure.source.value}")
    print(f"  Goal: {failure.goal_id}")
    print(f"  Run: {failure.run_id}")
    if failure.node_id:
        print(f"  Node: {failure.node_id}")
    print(f"  Time: {failure.timestamp}")
    
    print(f"\nError:")
    print(f"  Type: {failure.error_type}")
    print(f"  Message: {failure.error_message}")
    
    if failure.attempt_number > 1 or failure.max_attempts > 1:
        print(f"\nRetry Info:")
        print(f"  Attempt: {failure.attempt_number}/{failure.max_attempts}")
    
    if failure.stack_trace:
        print(f"\nStack Trace:")
        for line in failure.stack_trace.split('\n')[-15:]:  # Last 15 lines
            print(f"  {line}")
    
    if failure.input_data:
        print(f"\nInput Data:")
        for key, value in list(failure.input_data.items())[:5]:
            val_str = str(value)[:100]
            print(f"  {key}: {val_str}...")
    
    if failure.execution_path:
        print(f"\nExecution Path (last {len(failure.execution_path)} steps):")
        for step in failure.execution_path[-5:]:
            print(f"  → {step}")
    
    if failure.decisions_before_failure:
        print(f"\nDecisions Before Failure:")
        for dec in failure.decisions_before_failure[-3:]:
            print(f"  • [{dec.get('node_id', 'unknown')}] {dec.get('intent', 'N/A')}")
            print(f"    Chose: {dec.get('chosen', 'N/A')}")
    
    # Find similar failures
    print(f"\nSimilar Failures:")
    similar = storage.get_similar_failures(args.failure_id, args.goal, limit=3)
    if similar:
        for s in similar:
            print(f"  • {s.id} ({s.error_type}) - {s.timestamp.strftime('%Y-%m-%d')}")
    else:
        print("  No similar failures found.")
    
    return 0


def cmd_failures_stats(args: argparse.Namespace) -> int:
    """Show failure statistics for an agent."""
    from framework.testing.failure_storage import FailureStorage
    
    agent_path = Path(args.agent_path)
    failures_path = agent_path / ".aden" / "failures"
    
    if not failures_path.exists():
        print(f"No failures recorded for agent at: {agent_path}")
        return 0
    
    storage = FailureStorage(failures_path)
    
    if args.goal:
        # Stats for specific goal
        stats = storage.get_failure_stats(args.goal)
        
        print(f"Failure Statistics for Goal: {args.goal}")
        print("=" * 60)
        print()
        
        print(f"  Total Failures: {stats.total_failures}")
        
        if stats.first_failure:
            print(f"  First Failure: {stats.first_failure.strftime('%Y-%m-%d %H:%M')}")
        if stats.last_failure:
            print(f"  Last Failure: {stats.last_failure.strftime('%Y-%m-%d %H:%M')}")
        
        if stats.by_severity:
            print(f"\n  By Severity:")
            for sev, count in sorted(stats.by_severity.items()):
                icon = {"critical": "🔴", "error": "🟠", "warning": "🟡"}.get(sev, "⚪")
                print(f"    {icon} {sev}: {count}")
        
        if stats.by_source:
            print(f"\n  By Source:")
            for source, count in sorted(stats.by_source.items(), key=lambda x: -x[1]):
                print(f"    {source}: {count}")
        
        if stats.top_errors:
            print(f"\n  Top Error Types:")
            for err in stats.top_errors[:5]:
                print(f"    • {err['error_type']}: {err['count']}")
        
        if stats.top_failing_nodes:
            print(f"\n  Top Failing Nodes:")
            for node in stats.top_failing_nodes[:5]:
                print(f"    • {node['node_id']}: {node['count']}")
    
    else:
        # Overall storage stats
        stats = storage.get_storage_stats()
        
        print(f"Failure Storage Statistics")
        print("=" * 60)
        print()
        
        print(f"  Total Goals with Failures: {stats['total_goals']}")
        print(f"  Total Failures: {stats['total_failures']}")
        
        if stats.get('by_severity'):
            print(f"\n  By Severity:")
            for sev, count in sorted(stats['by_severity'].items()):
                icon = {"critical": "🔴", "error": "🟠", "warning": "🟡"}.get(sev, "⚪")
                print(f"    {icon} {sev}: {count}")
        
        print(f"\n  Storage Path: {stats['storage_path']}")
        
        # List goals with failures
        goals = storage.list_all_goals()
        if goals:
            print(f"\n  Goals with Failures ({len(goals)}):")
            for goal in goals[:10]:
                goal_count = len(storage._get_index("by_goal", goal))
                print(f"    • {goal}: {goal_count} failures")
            if len(goals) > 10:
                print(f"    ... and {len(goals) - 10} more")
    
    return 0
