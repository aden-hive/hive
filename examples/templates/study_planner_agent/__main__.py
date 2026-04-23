"""
CLI entry point for Study Planner Agent.

Uses AgentRuntime for multi-entrypoint support.
"""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent, StudyPlannerAgent


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
    """Study Planner Agent - Generate structured study schedules."""
    pass


@cli.command()
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(quiet, verbose, debug):
    """Execute the study planner agent."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    context = {}

    result = asyncio.run(default_agent.run(context))

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
    """Interactive study planner session."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    """Async interactive shell."""
    setup_logging(verbose=verbose)

    click.echo("=== Study Planner Agent ===")
    click.echo("Enter your subjects, deadlines, and daily study time.")
    click.echo("Type 'quit' to exit.\n")

    agent = StudyPlannerAgent()
    await agent.start()

    try:
        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Study> "
                )
                if user_input.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break

                context = {"input": user_input}

                result = await agent.trigger_and_wait("start", context)

                if result is None:
                    click.echo("\n[Execution timed out]\n")
                    continue

                if result.success:
                    click.echo("\nGenerated Study Plan:\n")
                    click.echo(str(result.output))
                    click.echo()
                else:
                    click.echo(f"\nFailed: {result.error}\n")

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
