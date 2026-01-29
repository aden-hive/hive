#!/usr/bin/env python3
"""
Setup script for Aden Hive Framework MCP Server

This script installs the framework and configures the MCP server with Windows compatibility.
"""

import json
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Platform detection
IS_WINDOWS = platform.system() == "Windows"
SCRIPT_DIR = Path(__file__).parent.absolute()

class Colors:
    """ANSI color codes for terminal output."""
    if IS_WINDOWS:
        try:
            import colorama
            colorama.init()
            GREEN = colorama.Fore.GREEN
            YELLOW = colorama.Fore.YELLOW
            RED = colorama.Fore.RED
            BLUE = colorama.Fore.BLUE
            NC = colorama.Style.RESET_ALL
        except ImportError:
            GREEN = YELLOW = RED = BLUE = NC = ""
    else:
        GREEN = "\033[0;32m"
        YELLOW = "\033[1;33m"
        RED = "\033[0;31m"
        BLUE = "\033[0;34m"
        NC = "\033[0m"

def log_step(message: str):
    """Log a colored step message."""
    logger.info(f"{Colors.YELLOW}==> {message}{Colors.NC}")

def log_success(message: str):
    """Log a success message."""
    logger.info(f"{Colors.GREEN}✓ {message}{Colors.NC}")

def log_error(message: str):
    """Log an error message."""
    logger.error(f"{Colors.RED}✗ {message}{Colors.NC}")

def run_command(cmd: list, error_msg: str, cwd: str = None):
    """Run a command with better error handling and cross-platform support."""
    try:
        # Convert path-like objects to strings for Windows compatibility
        cmd = [str(arg) for arg in cmd]

        # On Windows, use shell=True for better command execution
        subprocess.run(
            cmd,
            check=True,
            cwd=cwd or os.getcwd(),
            shell=IS_WINDOWS,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )
        return True
    except subprocess.CalledProcessError as e:
        error_output = e.stderr if e.stderr else str(e)
        log_error(f"{error_msg}: {error_output}")
        return False
    except Exception as e:
        log_error(f"{error_msg}: {str(e)}")
        return False

def setup_virtualenv(venv_dir: Path):
    """Set up a Python virtual environment."""
    if not venv_dir.exists():
        log_step("Creating virtual environment...")
        if not run_command(
            [sys.executable, "-m", "venv", str(venv_dir)],
            "Failed to create virtual environment"
        ):
            return False
        log_success(f"Virtual environment created at {venv_dir}")
    else:
        log_success(f"Using existing virtual environment at {venv_dir}")
    return True

def install_requirements(venv_dir: Path, requirements_path: Path):
    """Install Python requirements."""
    if not requirements_path.exists():
        log_error(f"Requirements file not found: {requirements_path}")
        return False

    # Determine the correct pip executable
    pip_executable = venv_dir / "Scripts" / "pip" if IS_WINDOWS else venv_dir / "bin" / "pip"

    log_step("Installing requirements...")
    if not run_command(
        [str(pip_executable), "install", "-r", str(requirements_path)],
        "Failed to install requirements"
    ):
        return False

    log_success(f"Requirements installed from {requirements_path}")
    return True

def setup_mcp_config(script_dir: Path):
    """Set up MCP configuration file."""
    mcp_config_path = script_dir / ".mcp.json"

    if mcp_config_path.exists():
        log_success(f"MCP configuration found at {mcp_config_path}")
        return True

    log_step("Creating MCP configuration...")
    config = {
        "mcpServers": {
            "agent-builder": {
                "command": "python",
                "args": ["-m", "framework.mcp.agent_builder_server"],
                "cwd": str(script_dir),
            }
        }
    }

    try:
        with open(mcp_config_path, "w") as f:
            json.dump(config, f, indent=2)
        log_success(f"Created MCP configuration at {mcp_config_path}")
        return True
    except Exception as e:
        log_error(f"Failed to create MCP configuration: {str(e)}")
        return False

def test_mcp_server():
    """Test if the MCP server module can be imported."""
    log_step("Testing MCP server module...")
    try:
        subprocess.run(
            [sys.executable, "-c", "from framework.mcp import agent_builder_server"],
            check=True,
            capture_output=True,
            text=True,
        )
        log_success("MCP server module verified")
        return True
    except subprocess.CalledProcessError as e:
        log_error(f"Failed to import MCP server module: {e.stderr}")
        return False

def main():
    """Main setup function."""
    try:
        log_step("Starting Aden Hive Framework MCP Server setup...")

        # Set up paths
        venv_dir = SCRIPT_DIR / ".venv"
        requirements_path = SCRIPT_DIR / "requirements.txt"

        # Set up virtual environment
        if not setup_virtualenv(venv_dir):
            sys.exit(1)

        # Install requirements
        if not install_requirements(venv_dir, requirements_path):
            sys.exit(1)

        # Set up MCP configuration
        if not setup_mcp_config(SCRIPT_DIR):
            log_error("Failed to set up MCP configuration")
            sys.exit(1)

        # Test MCP server
        if not test_mcp_server():
            log_error("MCP server test failed")
            sys.exit(1)

        # Platform-specific setup
        if IS_WINDOWS:
            log_step("Windows-specific setup complete")

        # Success message
        log_success("\nSetup completed successfully! 🎉")
        print("\nNext steps:")
        print("1. Activate the virtual environment:")
        if IS_WINDOWS:
            print(f"   PowerShell: .\\{venv_dir}\\Scripts\\Activate.ps1")
            print(f"   CMD:       {venv_dir}\\Scripts\\activate.bat")
        else:
            print(f"   source {venv_dir}/bin/activate")

        print("\n2. Start the MCP server:")
        print("   python -m framework.mcp.agent_builder_server")

    except KeyboardInterrupt:
        log_error("Setup was interrupted by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"An unexpected error occurred: {str(e)}")
        if "--debug" in sys.argv:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
