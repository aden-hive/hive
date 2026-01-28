"""
Test execution MCP tools.

Handles running pytest, debugging individual tests, listing available
tests, and loading exported plans for validation.
"""

import json
import os
from pathlib import Path
from typing import Annotated

from framework.mcp.session import get_current_session_raw


def register(mcp):
    """Register test execution tools on the MCP server."""

    @mcp.tool()
    def run_tests(
        goal_id: Annotated[str, "ID of the goal to test"],
        agent_path: Annotated[str, "Path to the agent export folder"],
        test_types: Annotated[
            str,
            'JSON array of test types: ["constraint", "success", "edge_case", "all"]',
        ] = '["all"]',
        parallel: Annotated[
            int,
            "Number of parallel workers (-1 for auto/CPU count, 0 to disable)",
        ] = -1,
        fail_fast: Annotated[bool, "Stop on first failure (-x flag)"] = False,
        verbose: Annotated[bool, "Verbose output (-v flag)"] = True,
    ) -> str:
        """
        Run pytest on agent test files.

        Tests are located at {agent_path}/tests/test_*.py
        By default, tests run in parallel using pytest-xdist with auto-detected
        worker count. Returns pass/fail summary with detailed results parsed
        from pytest output.
        """
        import re
        import subprocess

        tests_dir = Path(agent_path) / "tests"

        if not tests_dir.exists():
            return json.dumps(
                {
                    "goal_id": goal_id,
                    "error": f"Tests directory not found: {tests_dir}",
                    "hint": (
                        "Use generate_constraint_tests or "
                        "generate_success_tests to get guidelines, "
                        "then write tests with Write tool"
                    ),
                }
            )

        # Parse test types
        try:
            types_list = json.loads(test_types)
        except json.JSONDecodeError:
            types_list = ["all"]

        # Build pytest command
        cmd = ["pytest"]

        # Add test path(s) based on type filter
        if "all" in types_list:
            cmd.append(str(tests_dir))
        else:
            type_to_file = {
                "constraint": "test_constraints.py",
                "success": "test_success_criteria.py",
                "outcome": "test_success_criteria.py",
                "edge_case": "test_edge_cases.py",
            }
            for t in types_list:
                if t in type_to_file:
                    test_file = tests_dir / type_to_file[t]
                    if test_file.exists():
                        cmd.append(str(test_file))

        # Add flags
        if verbose:
            cmd.append("-v")
        if fail_fast:
            cmd.append("-x")

        # Parallel execution
        if parallel == -1:
            cmd.extend(["-n", "auto"])
        elif parallel > 0:
            cmd.extend(["-n", str(parallel)])

        cmd.append("--tb=short")

        # Set PYTHONPATH to project root
        env = os.environ.copy()
        pythonpath = env.get("PYTHONPATH", "")
        project_root = Path(__file__).parent.parent.parent.parent.resolve()
        env["PYTHONPATH"] = f"{project_root}:{pythonpath}"

        # Run pytest
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return json.dumps(
                {
                    "goal_id": goal_id,
                    "error": ("Test execution timed out after 10 minutes"),
                    "command": " ".join(cmd),
                }
            )
        except Exception as e:
            return json.dumps(
                {
                    "goal_id": goal_id,
                    "error": f"Failed to run pytest: {e}",
                    "command": " ".join(cmd),
                }
            )

        # Parse pytest output
        output = result.stdout + "\n" + result.stderr

        summary_match = re.search(r"=+ ([\d\w,\s]+) in [\d.]+s =+", output)
        summary_text = summary_match.group(1) if summary_match else "unknown"

        passed = 0
        failed = 0
        skipped = 0
        error = 0

        passed_match = re.search(r"(\d+) passed", summary_text)
        if passed_match:
            passed = int(passed_match.group(1))

        failed_match = re.search(r"(\d+) failed", summary_text)
        if failed_match:
            failed = int(failed_match.group(1))

        skipped_match = re.search(r"(\d+) skipped", summary_text)
        if skipped_match:
            skipped = int(skipped_match.group(1))

        error_match = re.search(r"(\d+) error", summary_text)
        if error_match:
            error = int(error_match.group(1))

        total = passed + failed + skipped + error

        # Extract individual test results
        test_results = []
        test_pattern = re.compile(r"([\w/]+\.py)::(\w+)\s+(PASSED|FAILED|SKIPPED|ERROR)")
        for match in test_pattern.finditer(output):
            test_results.append(
                {
                    "file": match.group(1),
                    "test_name": match.group(2),
                    "status": match.group(3).lower(),
                }
            )

        # Extract failure details
        failures = []
        failure_section = re.search(
            r"=+ FAILURES =+(.+?)"
            r"(?:=+ (?:short test summary|ERRORS|warnings) =+|$)",
            output,
            re.DOTALL,
        )
        if failure_section:
            failure_text = failure_section.group(1)
            failure_blocks = re.split(r"_+ (test_\w+) _+", failure_text)
            for i in range(1, len(failure_blocks), 2):
                if i + 1 < len(failure_blocks):
                    test_name = failure_blocks[i]
                    details = failure_blocks[i + 1].strip()[:500]
                    failures.append(
                        {
                            "test_name": test_name,
                            "details": details,
                        }
                    )

        return json.dumps(
            {
                "goal_id": goal_id,
                "overall_passed": result.returncode == 0,
                "summary": {
                    "total": total,
                    "passed": passed,
                    "failed": failed,
                    "skipped": skipped,
                    "errors": error,
                    "pass_rate": (f"{(passed / total * 100):.1f}%" if total > 0 else "0%"),
                },
                "command": " ".join(cmd),
                "return_code": result.returncode,
                "test_results": test_results,
                "failures": failures,
                "raw_output": (output[-2000:] if len(output) > 2000 else output),
            }
        )

    @mcp.tool()
    def debug_test(
        goal_id: Annotated[str, "ID of the goal"],
        test_name: Annotated[
            str,
            "Name of the test function (e.g., test_constraint_foo)",
        ],
        agent_path: Annotated[str, "Path to agent export folder (e.g., 'exports/my_agent')"] = "",
    ) -> str:
        """Run a specific test with verbose output for debugging."""
        import re
        import subprocess

        _session = get_current_session_raw()

        # Derive agent_path from session if not provided
        if not agent_path and _session:
            agent_path = f"exports/{_session.name}"

        if not agent_path:
            return json.dumps({"error": "agent_path required (e.g., 'exports/my_agent')"})

        tests_dir = Path(agent_path) / "tests"

        if not tests_dir.exists():
            return json.dumps(
                {
                    "goal_id": goal_id,
                    "error": f"Tests directory not found: {tests_dir}",
                }
            )

        # Find which file contains the test
        test_file = None
        for py_file in tests_dir.glob("test_*.py"):
            content = py_file.read_text()
            if f"def {test_name}" in content or f"async def {test_name}" in content:
                test_file = py_file
                break

        if not test_file:
            return json.dumps(
                {
                    "goal_id": goal_id,
                    "error": (f"Test '{test_name}' not found in {tests_dir}"),
                    "hint": "Use list_tests to see available tests",
                }
            )

        # Run specific test with verbose output
        cmd = [
            "pytest",
            f"{test_file}::{test_name}",
            "-vvs",
            "--tb=long",
        ]

        # Set PYTHONPATH
        env = os.environ.copy()
        pythonpath = env.get("PYTHONPATH", "")
        project_root = Path(__file__).parent.parent.parent.parent.resolve()
        env["PYTHONPATH"] = f"{project_root}:{pythonpath}"

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return json.dumps(
                {
                    "goal_id": goal_id,
                    "test_name": test_name,
                    "error": ("Test execution timed out after 2 minutes"),
                }
            )
        except Exception as e:
            return json.dumps(
                {
                    "goal_id": goal_id,
                    "test_name": test_name,
                    "error": f"Failed to run pytest: {e}",
                }
            )

        output = result.stdout + "\n" + result.stderr
        passed = result.returncode == 0

        # Categorize error if failed
        error_category = None
        suggestion = None

        if not passed:
            output_lower = output.lower()
            _categories = [
                (
                    ["typeerror", "attributeerror", "keyerror", "valueerror"],
                    "IMPLEMENTATION_ERROR",
                    "Fix the bug - check traceback for location",
                ),
                (
                    ["assertionerror", "assert", "expected"],
                    "ASSERTION_FAILURE",
                    "Assertion failed - fix logic or update expectation",
                ),
                (["timeout", "timed out"], "TIMEOUT", "Too slow - check for infinite loops"),
                (
                    ["importerror", "modulenotfounderror"],
                    "IMPORT_ERROR",
                    "Missing module - check package structure",
                ),
                (
                    ["connectionerror", "api", "rate limit"],
                    "API_ERROR",
                    "API issue - check keys and connectivity",
                ),
            ]
            for patterns, cat, sug in _categories:
                if any(p in output_lower for p in patterns):
                    error_category, suggestion = cat, sug
                    break
            else:
                error_category = "UNKNOWN"
                suggestion = "Review the traceback and test output for clues"

        # Extract the assertion/error message
        error_message = None
        error_match = re.search(
            r"(AssertionError|Error|Exception):\s*(.+?)(?:\n|$)",
            output,
        )
        if error_match:
            error_message = error_match.group(2).strip()

        return json.dumps(
            {
                "goal_id": goal_id,
                "test_name": test_name,
                "test_file": str(test_file),
                "passed": passed,
                "error_category": error_category,
                "error_message": error_message,
                "suggestion": suggestion,
                "command": " ".join(cmd),
                "output": (output[-3000:] if len(output) > 3000 else output),
            },
            indent=2,
        )

    @mcp.tool()
    def list_tests(
        goal_id: Annotated[str, "ID of the goal"],
        agent_path: Annotated[str, "Path to agent export folder (e.g., 'exports/my_agent')"] = "",
    ) -> str:
        """List tests for an agent by scanning test files."""
        import ast

        _session = get_current_session_raw()

        # Derive agent_path from session if not provided
        if not agent_path and _session:
            agent_path = f"exports/{_session.name}"

        if not agent_path:
            return json.dumps({"error": "agent_path required (e.g., 'exports/my_agent')"})

        tests_dir = Path(agent_path) / "tests"

        if not tests_dir.exists():
            return json.dumps(
                {
                    "goal_id": goal_id,
                    "agent_path": agent_path,
                    "total": 0,
                    "tests": [],
                    "hint": (
                        "No tests directory found. Generate tests with "
                        "generate_constraint_tests or "
                        "generate_success_tests"
                    ),
                }
            )

        # Scan all test files
        tests = []
        for test_file in sorted(tests_dir.glob("test_*.py")):
            try:
                content = test_file.read_text()
                tree = ast.parse(content)

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                        if node.name.startswith("test_"):
                            if "constraint" in test_file.name:
                                test_type = "constraint"
                            elif "success" in test_file.name:
                                test_type = "success_criteria"
                            elif "edge" in test_file.name:
                                test_type = "edge_case"
                            else:
                                test_type = "unknown"

                            docstring = ast.get_docstring(node) or ""

                            tests.append(
                                {
                                    "test_name": node.name,
                                    "file": test_file.name,
                                    "file_path": str(test_file),
                                    "line": node.lineno,
                                    "test_type": test_type,
                                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                                    "description": (docstring[:200] if docstring else None),
                                }
                            )
            except SyntaxError as e:
                tests.append(
                    {
                        "file": test_file.name,
                        "error": f"Syntax error: {e}",
                    }
                )
            except Exception as e:
                tests.append(
                    {
                        "file": test_file.name,
                        "error": str(e),
                    }
                )

        # Group by type
        by_type = {}
        for t in tests:
            ttype = t.get("test_type", "unknown")
            if ttype not in by_type:
                by_type[ttype] = 0
            by_type[ttype] += 1

        return json.dumps(
            {
                "goal_id": goal_id,
                "agent_path": agent_path,
                "tests_dir": str(tests_dir),
                "total": len(tests),
                "by_type": by_type,
                "tests": tests,
                "run_command": f"pytest {tests_dir} -v",
            }
        )

    @mcp.tool()
    def load_exported_plan(
        plan_json: Annotated[str, "JSON string from export_graph() output"],
    ) -> str:
        """Validate and load an exported plan, returning its structure."""
        from framework.mcp.handlers.test_generation_handler import (
            load_plan_from_json,
        )

        try:
            plan = load_plan_from_json(plan_json)
            return json.dumps(
                {
                    "success": True,
                    "plan_id": plan.id,
                    "goal_id": plan.goal_id,
                    "description": plan.description,
                    "step_count": len(plan.steps),
                    "steps": [
                        {
                            "id": s.id,
                            "description": s.description,
                            "action_type": s.action.action_type.value,
                            "dependencies": s.dependencies,
                        }
                        for s in plan.steps
                    ],
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
