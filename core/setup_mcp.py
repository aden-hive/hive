#!/usr/bin/env python3
"""
Setup script for Aden Hive Framework MCP Server

This script installs the framework and configures the MCP server.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path
import base64
import torch
import numpy as np
from mcp.server.fastmcp import FastMCP
from robotics.perception import OpenVisionEncoder
from robotics.control import LaplaceTransformer


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
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
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

    # Step 1: Install framework package
    log_step("Step 1: Installing framework package...")
    if not run_command(
        [sys.executable, "-m", "pip", "install", "-e", str(script_dir)],
        "Failed to install framework package",
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

    # Step 3: Verify MCP configuration
    log_step("Step 3: Verifying MCP server configuration...")
    mcp_config_path = script_dir / ".mcp.json"

    if mcp_config_path.exists():
        log_success("MCP configuration found at .mcp.json")
        logger.info("Configuration:")
        with open(mcp_config_path, encoding="utf-8") as f:
            config = json.load(f)
            logger.info(json.dumps(config, indent=2))
    else:
        log_success("No .mcp.json needed (MCP servers configured at repo root)")
    logger.info("")

    # Step 4: Test framework import
    log_step("Step 4: Testing framework import...")
    try:
        subprocess.run(
            [sys.executable, "-c", "import framework; print('OK')"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        log_success("Framework module verified")
    except subprocess.CalledProcessError as e:
        log_error("Failed to import framework module")
        logger.error(f"Error: {e.stderr}")
        sys.exit(1)
    logger.info("")

    # Success summary
    logger.info(f"{Colors.GREEN}=== Setup Complete ==={Colors.NC}")
    logger.info("")
    logger.info("The framework is now ready to use!")
    logger.info("")
    logger.info(f"{Colors.BLUE}MCP Configuration location:{Colors.NC}")
    logger.info(f"  {mcp_config_path}")
    logger.info("")

# Initialize the robotics stack
mcp = FastMCP("RoboticsController")
vision_encoder = OpenVisionEncoder()
control_module = LaplaceTransformer()

@mcp.tool()
async def vision_language_action(image_b64: str, instruction: str) -> dict:
    """
    VLA Tool: Takes a camera frame and a command to generate 
    a smooth robotic trajectory using Laplace s-domain control.
    """
    # 1. Perception: Convert Image to Spatial Embeddings
    image_data = base64.b64decode(image_b64)
    visual_context = vision_encoder.encode(image_data)
    
    # 2. Reasoning: Combine Vision + Language
    # (Typically involves a transformer cross-attention layer)
    multimodal_state = f"{instruction} | Context: {visual_context.shape}"

    # 3. Action: Generate Laplace Trajectory
    # Maps instructions to s-domain algebraic motor commands
    action_chunk = control_module.generate_trajectory(visual_context, instruction)
    
    return {
        "status": "success",
        "action_type": "trajectory_chunk",
        "commands": action_chunk.tolist(),
        "metadata": {"control_mode": "Laplace_s_domain"}
    }
    

if __name__ == "__main__":
    main()
