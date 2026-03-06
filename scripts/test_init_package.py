"""Quick test script for initialize_agent_package."""

import sys
import os

# Add project paths so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

# Set PROJECT_ROOT before importing
import tools.coder_tools_server as srv
srv.PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Access the underlying function (FastMCP wraps it as FunctionTool)
tool = srv.initialize_agent_package
result = tool.fn("richard_test2", nodes=["intake", "process", "review"])
print(result)
