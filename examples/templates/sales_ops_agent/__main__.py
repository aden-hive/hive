"""
CLI entry point for Sales Ops Agent.

Supports manual execution, TUI dashboard, and agent validation.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from typing import Literal

import click

from .agent import SalesOpsAgent, default_agent


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
    """Sales Ops Agent - Automated sales territory rebalancing."""
    pass


@cli.command()
@click.option(
    "--crm-type",
    "-c",
    type=click.Choice(["salesforce", "hubspot", "demo"]),
    required=True,
    help="CRM platform to use (salesforce, hubspot, or demo for mock data)",
)
@click.option(
    "--date",
    "-d",
    type=str,
    default=None,
    help="Date to run as (YYYY-MM-DD format). Defaults to today.",
)
@click.option("--mock", is_flag=True, help="Run in mock mode")
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(
    crm_type: Literal["salesforce", "hubspot", "demo"],
    date: str | None,
    mock: bool,
    quiet: bool,
    verbose: bool,
    debug: bool,
):
    """Execute sales territory analysis and rebalancing."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    # Parse date or use today
    if date:
        try:
            run_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            click.echo("Error: Date must be in YYYY-MM-DD format", err=True)
            sys.exit(1)
    else:
        run_date = datetime.now().date()

    context = {
        "crm_type": crm_type,
        "current_date": run_date.isoformat(),
    }

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


@cli.command()
@click.option("--mock", is_flag=True, help="Run in mock mode")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def tui(mock: bool, verbose: bool, debug: bool):
    """Launch the TUI dashboard for interactive sales ops management."""
    setup_logging(verbose=verbose, debug=debug)

    try:
        from framework.tui.app import AdenTUI
    except ImportError:
        click.echo("TUI requires the 'textual' package. Install with: pip install textual")
        sys.exit(1)

    async def run_with_tui():
        agent = SalesOpsAgent()
        await agent.start(mock_mode=mock)

        try:
            app = AdenTUI(agent._agent_runtime)
            await app.run_async()
        finally:
            await agent.stop()

    asyncio.run(run_with_tui())


@cli.command()
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def info(output_json: bool):
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
@click.option(
    "--crm-type", "-c", type=click.Choice(["salesforce", "hubspot", "demo"]), default="demo", help="CRM platform to use"
)
def shell(verbose: bool, crm_type: str):
    """Interactive sales ops session (CLI, no TUI)."""
    setup_logging(verbose=verbose)

    click.echo("=== Sales Ops Agent ===")
    click.echo(f"CRM: {crm_type}")
    click.echo("Enter 'run' to execute, 'quit' to exit:\n")

    agent = SalesOpsAgent()

    async def _interactive_shell():
        await agent.start()
        try:
            while True:
                try:
                    command = await asyncio.get_event_loop().run_in_executor(None, input, "sales-ops> ")
                    if command.lower() in ["quit", "exit", "q"]:
                        click.echo("Goodbye!")
                        break

                    if command.lower() == "run":
                        click.echo("\nRunning territory analysis and rebalancing...\n")

                        context = {
                            "crm_type": crm_type,
                            "current_date": datetime.now().date().isoformat(),
                        }

                        result = await agent.trigger_and_wait("default", context)

                        if result is None:
                            click.echo("\n[Execution timed out]\n")
                            continue

                        if result.success:
                            output = result.output
                            if "summary_report" in output:
                                click.echo("\n" + output["summary_report"] + "\n")
                        else:
                            click.echo(f"\nExecution failed: {result.error}\n")
                    else:
                        click.echo(f"Unknown command: {command}")
                        click.echo("Available: run, quit")

                except KeyboardInterrupt:
                    click.echo("\nGoodbye!")
                    break
                except Exception as e:
                    click.echo(f"Error: {e}", err=True)
                    import traceback

                    traceback.print_exc()
        finally:
            await agent.stop()

    asyncio.run(_interactive_shell())


if __name__ == "__main__":
    cli()
