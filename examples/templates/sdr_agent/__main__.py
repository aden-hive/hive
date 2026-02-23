"""
CLI entry point for SDR Agent.

Automates sales development outreach: score contacts, filter suspicious
profiles, generate personalized messages, and create Gmail drafts.
"""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent, SDRAgent


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
    """SDR Agent - Automated outreach with contact scoring and personalization."""
    pass


@cli.command()
@click.option("--contacts", "-c", type=str, required=True, help="JSON string or file path of contacts list")
@click.option("--goal", "-g", type=str, default="coffee chat", help="Outreach goal (e.g. 'coffee chat', 'sales pitch')")
@click.option("--background", "-b", type=str, default="", help="Your background/role for personalization")
@click.option(
    "--max-contacts",
    "-m",
    type=int,
    default=20,
    help="Max contacts to process per batch (default: 20)",
)
@click.option("--mock", is_flag=True, help="Run in mock mode without LLM or Gmail calls")
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(contacts, goal, background, max_contacts, mock, quiet, verbose, debug):
    """Execute an SDR outreach campaign for the given contacts."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    context = {
        "contacts": contacts,
        "outreach_goal": goal,
        "user_background": background,
        "max_contacts": str(max_contacts),
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
def tui(mock, verbose, debug):
    """Launch the TUI dashboard for interactive SDR outreach."""
    setup_logging(verbose=verbose, debug=debug)

    try:
        from framework.tui.app import AdenTUI
    except ImportError:
        click.echo(
            "TUI requires the 'textual' package. Install with: pip install textual"
        )
        sys.exit(1)

    async def run_with_tui():
        agent = SDRAgent()
        await agent.start(mock_mode=mock)

        try:
            app = AdenTUI(agent._agent_runtime)
            await app.run_async()
        finally:
            await agent.stop()

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
    """Interactive SDR outreach session (CLI, no TUI)."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    """Async interactive shell."""
    setup_logging(verbose=verbose)

    click.echo("=== SDR Agent ===")
    click.echo("Automated contact scoring, filtering, and outreach personalization\n")

    agent = SDRAgent()
    await agent.start()

    try:
        while True:
            try:
                goal = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Outreach goal (e.g. 'coffee chat')> "
                )
                if goal.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break

                contacts = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Contacts (JSON)> "
                )
                background = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Your background/role> "
                )

                if not contacts.strip():
                    continue

                click.echo("\nRunning SDR campaign...\n")

                result = await agent.trigger_and_wait(
                    "start",
                    {
                        "contacts": contacts,
                        "outreach_goal": goal,
                        "user_background": background,
                        "max_contacts": "20",
                    },
                )

                if result is None:
                    click.echo("\n[Execution timed out]\n")
                    continue

                if result.success:
                    output = result.output
                    if "summary_report" in output:
                        click.echo("\n--- Campaign Report ---\n")
                        click.echo(output["summary_report"])
                        click.echo("\n")
                else:
                    click.echo(f"\nCampaign failed: {result.error}\n")

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
