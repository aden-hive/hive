#!/usr/bin/env python3
"""Test script to validate Job Hunter PDF support implementation."""

import sys
import os

# Add the necessary paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'examples', 'templates', 'job_hunter'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'core'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tools', 'src'))

try:
    # Test imports
    from aden_tools.tools.pdf_read_tool import register_tools
    print("✓ pdf_read tool imports successfully")

    from fastmcp import FastMCP
    mcp = FastMCP('test')
    register_tools(mcp)
    print("✓ pdf_read tool registers successfully")

    # Check if pdf_read tool is available
    if 'pdf_read' in mcp._tool_manager._tools:
        print("✓ pdf_read tool is registered in MCP")
    else:
        print("✗ pdf_read tool not found in MCP")
        sys.exit(1)

    # Test Job Hunter agent import
    from agent import JobHunterAgent
    print("✓ Job Hunter agent imports successfully")

    # Check if intake node has pdf_read tool
    intake_node = None
    for node in JobHunterAgent().nodes:
        if node.id == "intake":
            intake_node = node
            break

    if intake_node and "pdf_read" in intake_node.tools:
        print("✓ Intake node has pdf_read tool configured")
    else:
        print("✗ Intake node missing pdf_read tool")
        sys.exit(1)

    # Check system prompt mentions PDF
    if "pdf_read" in intake_node.system_prompt:
        print("✓ Intake node system prompt mentions pdf_read")
    else:
        print("✗ Intake node system prompt missing pdf_read reference")
        sys.exit(1)

    print("\n🎉 All checks passed! PDF resume support is properly implemented.")

except ImportError as e:
    print(f"✗ Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"✗ Unexpected error: {e}")
    sys.exit(1)