#!/usr/bin/env python3
"""
Verification script for Aden Hive Framework MCP Server

This script checks if the MCP server is properly installed and configured.
"""

import importlib
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def setup_logger():
    """Configure logger for CLI usage."""
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


class Colors:
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    RED = "\033[0;31m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"


def check(description: str) -> bool:
    """Print check description and return a context manager for result."""
    logger.info(f"Checking {description}... ", extra={"end": ""})
    sys.stdout.flush()
    return True


def success(msg: str = "OK"):
    """Log success message."""
    logger.info(f"{Colors.GREEN}✓ {msg}{Colors.NC}")


def warning(msg: str):
    """Log warning message."""
    logger.warning(f"{Colors.YELLOW}⚠ {msg}{Colors.NC}")


def error(msg: str):
    """Log error message."""
    logger.error(f"{Colors.RED}✗ {msg}{Colors.NC}")


def _try_import(module_name: str):
    """Try importing a module and return (module, error_message)."""
    try:
        module = importlib.import_module(module_name)
        return module, None
    except Exception as exc:
        return None, str(exc)


def main():
    """Run verification checks."""
    setup_logger()
    logger.info("=== MCP Server Verification ===")
    logger.info("")

    script_dir = Path(__file__).parent.absolute()
    all_checks_passed = True

    # Check 1: Framework package installed
    check("framework package installation")
    framework_module, framework_error = _try_import("framework")
    if framework_module is not None:
        framework_path = getattr(framework_module, "__file__", "(unknown path)")
        success(f"installed at {framework_path}")
    else:
        error("framework package not found")
        logger.error(f"  Error: {framework_error}")
        logger.info(f"  Run: uv pip install -e {script_dir}")
        all_checks_passed = False

    # Check 2: MCP dependencies
    check("MCP dependencies")
    missing_deps = []
    for dep in ["mcp", "fastmcp"]:
        _, dep_error = _try_import(dep)
        if dep_error is not None:
            missing_deps.append(dep)

    if missing_deps:
        error(f"missing: {', '.join(missing_deps)}")
        logger.info(f"  Run: uv pip install {' '.join(missing_deps)}")
        all_checks_passed = False
    else:
        success("all installed")

    # Check 3: MCP server module
    check("MCP server module")
    _, module_error = _try_import("framework.mcp.agent_builder_server")
    if module_error is None:
        success("loads successfully")
    else:
        error("failed to import")
        logger.error(f"  Error: {module_error}")
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
                logger.info(f"  Command: {server_config.get('command')}")
                logger.info(f"  Args: {' '.join(server_config.get('args', []))}")
                logger.info(f"  CWD: {server_config.get('cwd')}")
            else:
                warning("exists but missing agent-builder config")
                all_checks_passed = False
        except json.JSONDecodeError:
            error("invalid JSON format")
            all_checks_passed = False
    else:
        warning("not found (optional)")
        logger.info(f"  Location would be: {mcp_config}")
        logger.info("  Run setup_mcp.py to create it")

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
        _, import_error = _try_import(module)
        if import_error is not None:
            failed_modules.append(module)

    if failed_modules:
        error(f"failed to import: {', '.join(failed_modules)}")
        all_checks_passed = False
    else:
        success(f"all {len(modules_to_check)} modules OK")

    # Check 6: Test MCP server startup (quick test)
    check("MCP server startup")
    agent_builder_module, startup_error = _try_import("framework.mcp.agent_builder_server")
    if startup_error is None and hasattr(agent_builder_module, "mcp"):
        success("server can start")
    elif startup_error is None:
        warning("module loaded but MCP object not found")
        all_checks_passed = False
    else:
        error("server failed to start")
        logger.error(f"  Error: {startup_error}")
        all_checks_passed = False

    logger.info("")
    logger.info("=" * 40)
    if all_checks_passed:
        logger.info(f"{Colors.GREEN}✓ All checks passed!{Colors.NC}")
        logger.info("")
        logger.info("Your MCP server is ready to use.")
        logger.info("")
        logger.info(f"{Colors.BLUE}To start the server:{Colors.NC}")
        logger.info("  uv run python -m framework.mcp.agent_builder_server")
        logger.info("")
        logger.info(f"{Colors.BLUE}To use with Claude Desktop:{Colors.NC}")
        logger.info("  Add the configuration from .mcp.json to your")
        logger.info("  Claude Desktop MCP settings")
    else:
        logger.info(f"{Colors.RED}✗ Some checks failed{Colors.NC}")
        logger.info("")
        logger.info("To fix issues, run:")
        logger.info(f"  uv run python {script_dir / 'setup_mcp.py'}")
    logger.info("")


if __name__ == "__main__":
    main()
