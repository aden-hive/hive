"""CLI entry point for DSA Mentor Agent."""

import asyncio
import json
import sys
import logging
from pathlib import Path

# Add core and tools directories to Python path so we can import framework and aden_tools
# This must happen BEFORE any framework imports
_project_root = Path(__file__).resolve().parent.parent.parent.parent
_core_dir = _project_root / "core"
_tools_src_dir = _project_root / "tools" / "src"
if str(_core_dir) not in sys.path:
    sys.path.insert(0, str(_core_dir))
if str(_tools_src_dir) not in sys.path:
    sys.path.insert(0, str(_tools_src_dir))

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    stream=sys.stderr,
)


def main():
    from .agent import DSAMentorAgent
    from .config import default_config

    # Check for TUI mode
    if len(sys.argv) > 1 and sys.argv[1] == "tui":
        _run_tui()
        return

    # Default input for testing
    input_data = {
        "problem_statement": "Find two numbers in array that sum to target",
    }

    # Accept JSON input from command line
    if len(sys.argv) > 1 and sys.argv[1] == "--input":
        input_data = json.loads(sys.argv[2])

    agent = DSAMentorAgent(config=default_config)

    try:
        result = asyncio.run(agent.run(input_data))

        output = {
            "success": result["success"],
            "steps_executed": result["steps"],
            "path": result["path"],
            "output": result["output"],
        }

        if not result["success"]:
            output["note"] = (
                "⚠️  Client-facing nodes require interactive input. "
                "The intake node is waiting for user interaction. "
                "To test interactively, run: python3 -m examples.templates.dsa_mentor tui"
            )

        print(json.dumps(output, indent=2, default=str))

    except Exception as e:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                indent=2,
            )
        )
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


def _run_tui():
    """Launch TUI mode for interactive testing."""
    # Ensure core and tools are in path (in case it wasn't set up correctly)
    _project_root = Path(__file__).resolve().parent.parent.parent.parent
    _core_dir = _project_root / "core"
    _tools_src_dir = _project_root / "tools" / "src"
    if str(_core_dir) not in sys.path:
        sys.path.insert(0, str(_core_dir))
    if str(_tools_src_dir) not in sys.path:
        sys.path.insert(0, str(_tools_src_dir))

    try:
        from framework.tui.app import AdenTUI
    except ImportError as e:
        print(f"TUI import failed: {e}")
        print(
            "TUI requires the 'textual' package. Install with: python3 -m pip install textual"
        )
        print(f"Also ensure core directory is accessible: {_core_dir}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    from framework.llm.anthropic import AnthropicProvider
    from framework.runtime.agent_runtime import create_agent_runtime
    from framework.runtime.execution_stream import EntryPointSpec

    from .agent import DSAMentorAgent

    async def run_with_tui():
        agent = DSAMentorAgent()

        storage_path = Path.home() / ".hive" / "agents" / "dsa_mentor"
        storage_path.mkdir(parents=True, exist_ok=True)

        llm = AnthropicProvider(model=agent.config.model)
        tools = []
        tool_executor = None
        graph = agent._build_graph()

        runtime = create_agent_runtime(
            graph=graph,
            goal=agent.goal,
            storage_path=storage_path,
            entry_points=[
                EntryPointSpec(
                    id="start",
                    name="Start DSA Mentor",
                    entry_node="intake",
                    trigger_type="manual",
                    isolation_level="isolated",
                ),
            ],
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
        )

        await runtime.start()

        try:
            app = AdenTUI(runtime)
            await app.run_async()
        finally:
            await runtime.stop()

    asyncio.run(run_with_tui())


if __name__ == "__main__":
    main()
