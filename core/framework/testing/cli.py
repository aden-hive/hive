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
