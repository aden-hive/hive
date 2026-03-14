"""CLI entry point for Document Intelligence Agent Team.

Usage:
    python -m document_intelligence_agent_team run --document "your document text"
    python -m document_intelligence_agent_team tui
    python -m document_intelligence_agent_team info
    python -m document_intelligence_agent_team validate
    python -m document_intelligence_agent_team shell
"""

import argparse
import asyncio
import json
import logging
import os
import sys

# ---------------------------------------------------------------------------
# Path setup — ensure framework imports work from examples/templates/
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__))
_EXAMPLES_DIR = os.path.dirname(os.path.dirname(_TEMPLATE_DIR))
_CORE_DIR = os.path.join(os.path.dirname(_EXAMPLES_DIR), "core")

for _p in (_CORE_DIR, os.path.dirname(_TEMPLATE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_info() -> None:
    """Display agent information."""
    from document_intelligence_agent_team import default_agent

    print(default_agent.info())


def cmd_validate() -> None:
    """Validate agent graph structure."""
    from document_intelligence_agent_team import default_agent

    result = default_agent.validate()
    print(json.dumps(result, indent=2, default=str))
    if result["valid"]:
        print("\n✅ Agent graph is valid.")
    else:
        print("\n❌ Agent graph has issues:")
        for issue in result["issues"]:
            print(f"  - {issue}")
        sys.exit(1)


def cmd_run(document: str, verbose: bool = False) -> None:
    """Run the agent with a document."""
    _setup_logging(verbose)
    from document_intelligence_agent_team import default_agent

    runtime = default_agent.build_runtime()

    async def _run():
        await runtime.start()
        try:
            exec_id = await runtime.trigger(
                "start",
                {"document_text": document, "analysis_brief": "Comprehensive analysis"},
            )
            print(f"Execution started: {exec_id}")
            # Wait for user to interact via TUI or API
        except KeyboardInterrupt:
            pass
        finally:
            await runtime.stop()

    asyncio.run(_run())


def cmd_tui(verbose: bool = False) -> None:
    """Launch the TUI dashboard."""
    _setup_logging(verbose)

    try:
        from framework.tui.app import HiveApp
    except ImportError:
        print("Error: TUI requires the 'textual' package.")
        print("Install with: pip install textual")
        sys.exit(1)

    from document_intelligence_agent_team import default_agent

    runtime = default_agent.build_runtime()
    app = HiveApp(runtime=runtime)
    app.run()


def cmd_shell(verbose: bool = False) -> None:
    """Start an interactive shell session."""
    _setup_logging(verbose)
    from document_intelligence_agent_team import default_agent

    runtime = default_agent.build_runtime()

    async def _shell():
        await runtime.start()
        print(default_agent.metadata.intro_message)
        print("\nType your document text or 'quit' to exit.\n")
        try:
            while True:
                user_input = input("You: ").strip()
                if user_input.lower() in ("quit", "exit", "q"):
                    break
                if not user_input:
                    continue

                exec_id = await runtime.trigger(
                    "start",
                    {"document_text": user_input},
                )
                print(f"\n[Execution {exec_id} started]\n")
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
        finally:
            await runtime.stop()

    asyncio.run(_shell())


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="document_intelligence_agent_team",
        description="Document Intelligence Agent Team — A2A multi-agent analysis",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # info
    subparsers.add_parser("info", help="Show agent information")

    # validate
    subparsers.add_parser("validate", help="Validate agent graph structure")

    # run
    run_parser = subparsers.add_parser("run", help="Run analysis on a document")
    run_parser.add_argument("--document", "-d", required=True, help="Document text to analyze")
    run_parser.add_argument("--verbose", "-v", action="store_true")

    # tui
    tui_parser = subparsers.add_parser("tui", help="Launch TUI dashboard")
    tui_parser.add_argument("--verbose", "-v", action="store_true")

    # shell
    shell_parser = subparsers.add_parser("shell", help="Interactive shell session")
    shell_parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "info":
        cmd_info()
    elif args.command == "validate":
        cmd_validate()
    elif args.command == "run":
        cmd_run(args.document, args.verbose)
    elif args.command == "tui":
        cmd_tui(getattr(args, "verbose", False))
    elif args.command == "shell":
        cmd_shell(getattr(args, "verbose", False))


if __name__ == "__main__":
    main()
