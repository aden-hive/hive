"""
CLI entry point for the Hello Agent.

This module enables running the agent via:
    PYTHONPATH=core:exports python -m hello_agent <command>

Commands:
    validate    - Validate the agent configuration
    info        - Show agent information
    run         - Run the agent with input
    run --mock  - Run in mock mode (no LLM calls)
"""

import sys
from pathlib import Path

# Add core to path if needed
core_path = Path(__file__).parent.parent.parent / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

from framework.runner.cli import main

if __name__ == "__main__":
    # CLI will auto-detect agent from current module
    main()
