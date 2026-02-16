"""
CLI entry point for Gmail Inbox Guardian.

Uses AgentRuntime for multi-entry-point support with event-driven triggers.
"""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent, GmailInboxGuardianAgent


def setup_logging(verbose=False, debug=False):
    """Configure logging for execution visibility."""
    if debug:
        level, fmt = logging.DEBUG, "%(asctime)s %(name)s: %(message)s"
    elif verbose:
        level, fmt = logging.INFO, "%(message)s"
    else:
        level, fmt = logging.WARNING, "%(levelname)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)
    logging.getLogger("framework").setLevel(level)


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """Gmail Inbox Guardian - Event-driven email triage with user-defined rules."""
    pass


@click.command()
@click.option("--rules", "-r", type=str, help="Email triage rules in plain language")
@click.option("--max-emails", "-n", type=int, default=10, help="Max emails per batch")
@click.option("--mock", is_flag=True, help="Run in mock mode")
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(rules, max_emails, mock, quiet, verbose, debug):
    """Execute inbox triage with the given rules."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    context = {}
    if rules:
        context["rules"] = rules
    if max_emails:
        context["max_emails"] = str(max_emails)

    result = asyncio.run(default_agent.run(context, mock_mode=mock))

    output_data = {
        "success": result.success,
        "steps_executed": result.steps_executed,
        "output": result.output,
    }
    if result.error:
        output_data["error"] = result.error

    click.echo(json.dumps(output_data, indent=2, default=str))
    sys.exit(0 if result.success else 1)


cli.add_command(run)


@cli.command()
@click.option("--mock", is_flag=True, help="Run in mock mode")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def tui(mock, verbose, debug):
    """Launch the TUI dashboard for interactive inbox management."""
    setup_logging(verbose=verbose, debug=debug)

    try:
        from framework.tui.app import AdenTUI
    except ImportError:
        click.echo(
            "TUI requires the 'textual' package. Install with: pip install textual"
        )
        sys.exit(1)

    from pathlib import Path

    from framework.llm import LiteLLMProvider
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.agent_runtime import create_agent_runtime
    from framework.runtime.event_bus import EventBus
    from framework.runtime.execution_stream import EntryPointSpec

    async def run_with_tui():
        agent = GmailInboxGuardianAgent()

        agent._tool_registry = ToolRegistry()

        storage_path = Path.home() / ".hive" / "agents" / "gmail_inbox_guardian"
        storage_path.mkdir(parents=True, exist_ok=True)

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            agent._tool_registry.load_mcp_config(mcp_config_path)

        llm = None
        if not mock:
            llm = LiteLLMProvider(
                model=agent.config.model,
                api_key=agent.config.api_key,
                api_base=agent.config.api_base,
            )

        tools = list(agent._tool_registry.get_tools().values())
        tool_executor = agent._tool_registry.get_executor()
        graph = agent._build_graph()

        runtime = create_agent_runtime(
            graph=graph,
            goal=agent.goal,
            storage_path=storage_path,
            entry_points=[
                EntryPointSpec(
                    id="start",
                    name="Rule Setup",
                    entry_node="intake",
                    trigger_type="manual",
                    isolation_level="shared",
                ),
                EntryPointSpec(
                    id="email-event",
                    name="Email Event Handler",
                    entry_node="fetch-emails",
                    trigger_type="event",
                    trigger_config={
                        "event_types": ["webhook_received"],
                    },
                    isolation_level="shared",
                    max_concurrent=10,
                ),
                EntryPointSpec(
                    id="email-timer",
                    name="Scheduled Inbox Check",
                    entry_node="fetch-emails",
                    trigger_type="timer",
                    trigger_config={"interval_minutes": 20},
                    isolation_level="shared",
                    max_concurrent=1,
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


@cli.command()
@click.option("--json", "output_json", is_flag=True)
def info(output_json):
    """Show agent information."""
    info_data = default_agent.info()
    if output_json:
        click.echo(json.dumps(info_data, indent=2))
    else:
        click.echo(f"Agent: {info_data['name']}")
        click.echo(f"Version: {info_data['version']}")
        click.echo(f"Description: {info_data['description']}")
        click.echo(f"\nNodes: {', '.join(info_data['nodes'])}")
        click.echo(f"Client-facing: {', '.join(info_data['client_facing_nodes'])}")
        click.echo(f"Entry: {info_data['entry_node']}")
        click.echo(f"Terminal: {', '.join(info_data['terminal_nodes'])}")


@cli.command()
def validate():
    """Validate agent structure."""
    validation = default_agent.validate()
    if validation["valid"]:
        click.echo("Agent is valid")
        if validation["warnings"]:
            for warning in validation["warnings"]:
                click.echo(f"  WARNING: {warning}")
    else:
        click.echo("Agent has errors:")
        for error in validation["errors"]:
            click.echo(f"  ERROR: {error}")
    sys.exit(0 if validation["valid"] else 1)


@cli.command()
@click.option("--verbose", "-v", is_flag=True)
def shell(verbose):
    """Interactive inbox guardian session (CLI, no TUI)."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    """Async interactive shell."""
    setup_logging(verbose=verbose)

    click.echo("=== Gmail Inbox Guardian ===")
    click.echo("Define your email triage rules (or 'quit' to exit):\n")

    agent = GmailInboxGuardianAgent()
    await agent.start()

    try:
        while True:
            try:
                rules = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Rules> "
                )
                if rules.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break

                if not rules.strip():
                    continue

                click.echo("\nProcessing inbox...\n")

                result = await agent.trigger_and_wait(
                    "default", {"rules": rules, "max_emails": "10"}
                )

                if result is None:
                    click.echo("\n[Execution timed out]\n")
                    continue

                if result.success:
                    output = result.output
                    if "summary_report" in output:
                        click.echo("\n--- Report ---\n")
                        click.echo(output["summary_report"])
                        click.echo("\n")
                else:
                    click.echo(f"\nProcessing failed: {result.error}\n")

            except KeyboardInterrupt:
                click.echo("\nGoodbye!")
                break
            except Exception as e:
                click.echo(f"Error: {e}", err=True)
                import traceback

                traceback.print_exc()
    finally:
        await agent.stop()


if __name__ == "__main__":
    cli()
