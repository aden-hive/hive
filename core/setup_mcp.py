#!/usr/bin/env python3
"""
Setup script for Aden Hive Framework MCP Server

This script installs the framework and configures the MCP server.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def setup_logger():
    """Configure logger for CLI usage with colored output."""
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


class Colors:
    """ANSI color codes for terminal output."""

    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    RED = "\033[0;31m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"  # No Color


def log_step(message: str):
    """Log a colored step message."""
    logger.info(f"{Colors.YELLOW}{message}{Colors.NC}")


def log_success(message: str):
    """Log a success message."""
    logger.info(f"{Colors.GREEN}✓ {message}{Colors.NC}")


def log_error(message: str):
    """Log an error message."""
    logger.error(f"{Colors.RED}✗ {message}{Colors.NC}")


def run_command(cmd: list, error_msg: str) -> bool:
    """Run a command and return success status."""
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        log_error(error_msg)
        logger.error(f"Error output: {e.stderr}")
        return False


def main():
    """Main setup function."""
    setup_logger()
    logger.info("=== Aden Hive Framework MCP Server Setup ===")
    logger.info("")

    # Get script directory
    script_dir = Path(__file__).parent.absolute()
    os.chdir(script_dir)

    # Step 1: Install framework package
    log_step("Step 1: Installing framework package...")
    if not run_command(
        [sys.executable, "-m", "pip", "install", "-e", "."], "Failed to install framework package"
    ):
        sys.exit(1)
    log_success("Framework package installed")
    logger.info("")

    # Step 2: Install MCP dependencies
    log_step("Step 2: Installing MCP dependencies...")
    if not run_command(
        [sys.executable, "-m", "pip", "install", "mcp", "fastmcp"],
        "Failed to install MCP dependencies",
    ):
        sys.exit(1)
    log_success("MCP dependencies installed")
    logger.info("")

    # Step 3: Verify/create MCP configuration
    log_step("Step 3: Verifying MCP server configuration...")
    mcp_config_path = script_dir / ".mcp.json"

    if mcp_config_path.exists():
        log_success("MCP configuration found at .mcp.json")
        logger.info("Configuration:")
        with open(mcp_config_path) as f:
            config = json.load(f)
            logger.info(json.dumps(config, indent=2))
    else:
        log_error("No .mcp.json found")
        logger.info("Creating default MCP configuration...")

        config = {
            "mcpServers": {
                "agent-builder": {
                    "command": "python",
                    "args": ["-m", "framework.mcp.agent_builder_server"],
                    "cwd": str(script_dir),
                }
            }
        }

        with open(mcp_config_path, "w") as f:
            json.dump(config, f, indent=2)

        log_success("Created .mcp.json")
    logger.info("")

    # Step 4: Test MCP server
    log_step("Step 4: Testing MCP server...")
    try:
        # Try importing the MCP server module
        subprocess.run(
            [sys.executable, "-c", "from framework.mcp import agent_builder_server"],
            check=True,
            capture_output=True,
            text=True,
        )
        log_success("MCP server module verified")
    except subprocess.CalledProcessError as e:
        log_error("Failed to import MCP server module")
        logger.error(f"Error: {e.stderr}")
        sys.exit(1)
    logger.info("")

    # Success summary
    logger.info(f"{Colors.GREEN}=== Setup Complete ==={Colors.NC}")
    logger.info("")
    logger.info("The MCP server is now ready to use!")
    logger.info("")
    logger.info(f"{Colors.BLUE}To start the MCP server manually:{Colors.NC}")
    logger.info("  uv run python -m framework.mcp.agent_builder_server")
    logger.info("")
    logger.info(f"{Colors.BLUE}MCP Configuration location:{Colors.NC}")
    logger.info(f"  {mcp_config_path}")
    logger.info("")
    logger.info(f"{Colors.BLUE}To use with Claude Desktop or other MCP clients,{Colors.NC}")
    logger.info(f"{Colors.BLUE}add the following to your MCP client configuration:{Colors.NC}")
    logger.info("")

    example_config = {
        "mcpServers": {
            "agent-builder": {
                "command": "python",
                "args": ["-m", "framework.mcp.agent_builder_server"],
                "cwd": str(script_dir),
            }
        }
    }
    logger.info(json.dumps(example_config, indent=2))
    logger.info("")


if __name__ == "__main__":
    main()
