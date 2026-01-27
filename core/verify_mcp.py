#!/usr/bin/env python3
"""
Verification script for Aden Hive Framework MCP Server

This script checks if the MCP server is properly installed and configured.
"""

import json
import subprocess
import sys
from pathlib import Path


class Colors:
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    RED = "\033[0;31m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"


def check(description: str) -> bool:
    """Print check description and return a context manager for result."""
    print(f"Checking {description}...", end=" ")
    return True


def success(msg: str = "OK"):
    """Print success message."""
    print(f"{Colors.GREEN}✓ {msg}{Colors.NC}")


def warning(msg: str):
    """Print warning message."""
    print(f"{Colors.YELLOW}⚠ {msg}{Colors.NC}")


def error(msg: str):
    """Print error message."""
    print(f"{Colors.RED}✗ {msg}{Colors.NC}")


def main():
    """Run verification checks."""
    print("=== MCP Server Verification ===")
    print()

    script_dir = Path(__file__).parent.absolute()
    all_checks_passed = True

    # Check 1: Framework package installed
    check("framework package installation")
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import framework; print(framework.__file__)"],
            capture_output=True,
            text=True,
            check=True,
        )
        framework_path = result.stdout.strip()
        success(f"installed at {framework_path}")
    except subprocess.CalledProcessError:
        error("framework package not found")
        print(f"  Run: pip install -e {script_dir}")
        all_checks_passed = False

    # Check 2: MCP dependencies
    check("MCP dependencies")
    missing_deps = []
    for dep in ["mcp", "fastmcp"]:
        try:
            subprocess.run([sys.executable, "-c", f"import {dep}"], capture_output=True, check=True)
        except subprocess.CalledProcessError:
            missing_deps.append(dep)

    if missing_deps:
        error(f"missing: {', '.join(missing_deps)}")
        print(f"  Run: pip install {' '.join(missing_deps)}")
        all_checks_passed = False
    else:
        success("all installed")

    # Check 3: MCP server module
    check("MCP server module")
    try:
        subprocess.run(
            [sys.executable, "-c", "from framework.mcp import agent_builder_server"],
            capture_output=True,
            text=True,
            check=True,
        )
        success("loads successfully")
    except subprocess.CalledProcessError as e:
        error("failed to import")
        print(f"  Error: {e.stderr}")
        all_checks_passed = False

    # Check 4: MCP configuration file
    check("MCP configuration file")
    mcp_config = script_dir / ".mcp.json"
    if mcp_config.exists():
        try:
            with open(mcp_config) as f:
                config = json.load(f)

            if "mcpServers" in config and "agent-builder" in config["mcpServers"]:
                server_config = config["mcpServers"]["agent-builder"]
                success("found and valid")
                print(f"  Command: {server_config.get('command')}")
                print(f"  Args: {' '.join(server_config.get('args', []))}")
                print(f"  CWD: {server_config.get('cwd')}")
            else:
                warning("exists but missing agent-builder config")
                all_checks_passed = False
        except json.JSONDecodeError:
            error("invalid JSON format")
            all_checks_passed = False
    else:
        warning("not found (optional)")
        print(f"  Location would be: {mcp_config}")
        print("  Run setup_mcp.py to create it")

    # Check 5: Framework modules
    check("core framework modules")
    modules_to_check = [
        "framework.runtime.core",
        "framework.graph.executor",
        "framework.graph.node",
        "framework.builder.query",
        "framework.llm",
    ]

    failed_modules = []
    for module in modules_to_check:
        try:
            subprocess.run(
                [sys.executable, "-c", f"import {module}"], capture_output=True, check=True
            )
        except subprocess.CalledProcessError:
            failed_modules.append(module)

    if failed_modules:
        error(f"failed to import: {', '.join(failed_modules)}")
        all_checks_passed = False
    else:
        success(f"all {len(modules_to_check)} modules OK")

    # Check 6: Test MCP server startup (quick test)
    check("MCP server startup")
    try:
        # Try to import and instantiate the MCP server
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from framework.mcp.agent_builder_server import mcp; print('OK')",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        if "OK" in result.stdout:
            success("server can start")
        else:
            warning("unexpected output")
    except subprocess.TimeoutExpired:
        warning("server startup slow (might be OK)")
    except subprocess.CalledProcessError as e:
        error("server failed to start")
        print(f"  Error: {e.stderr}")
        all_checks_passed = False

    print()
    print("=" * 40)
    if all_checks_passed:
        print(f"{Colors.GREEN}✓ All checks passed!{Colors.NC}")
        print()
        print("Your MCP server is ready to use.")
        print()
        print(f"{Colors.BLUE}To start the server:{Colors.NC}")
        print("  python -m framework.mcp.agent_builder_server")
        print()
        print(f"{Colors.BLUE}To use with Claude Desktop:{Colors.NC}")
        print("  Add the configuration from .mcp.json to your")
        print("  Claude Desktop MCP settings")
    else:
        print(f"{Colors.RED}✗ Some checks failed{Colors.NC}")
        print()
        print("To fix issues, run:")
        print(f"  python {script_dir / 'setup_mcp.py'}")
    print()


if __name__ == "__main__":
    main()
