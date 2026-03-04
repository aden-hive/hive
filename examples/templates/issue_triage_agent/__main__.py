"""CLI entry point for Issue Triage Agent."""

import asyncio
import json
import logging
import sys

import click

from .agent import IssueTriageAgent, default_agent


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
    """Issue Triage Agent - triage Discord, email, and GitHub issue signals."""


@cli.command()
@click.option("--github-owner", required=True, help="GitHub repository owner")
@click.option("--github-repo", required=True, help="GitHub repository name")
@click.option(
    "--discord-channel-ids",
    required=True,
    help="Comma-separated Discord channel IDs to scan",
)
@click.option(
    "--triage-policy",
    required=True,
    help="Free-text triage policy, including severity and routing rules",
)
@click.option("--lookback-hours", default=24, show_default=True, type=int)
@click.option("--gmail-query", default="", help="Optional Gmail search query")
@click.option("--mock", is_flag=True, help="Run without real LLM calls")
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(
    github_owner,
    github_repo,
    discord_channel_ids,
    triage_policy,
    lookback_hours,
    gmail_query,
    mock,
    quiet,
    verbose,
    debug,
):
    """Execute a triage run."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    context = {
        "github_owner": github_owner,
        "github_repo": github_repo,
        "discord_channel_ids": discord_channel_ids,
        "triage_policy": triage_policy,
        "lookback_hours": str(lookback_hours),
        "gmail_query": gmail_query,
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
    """Interactive triage session (CLI)."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    """Async interactive shell."""
    setup_logging(verbose=verbose)

    click.echo("=== Issue Triage Agent ===")
    click.echo("Enter triage scope values (or 'quit' to exit).\n")

    agent = IssueTriageAgent()
    await agent.start()

    try:
        while True:
            try:
                github_owner = await asyncio.get_event_loop().run_in_executor(
                    None, input, "GitHub owner> "
                )
                if github_owner.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break

                github_repo = await asyncio.get_event_loop().run_in_executor(
                    None, input, "GitHub repo> "
                )
                discord_channel_ids = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Discord channel IDs (comma-separated)> "
                )
                triage_policy = await asyncio.get_event_loop().run_in_executor(
                    None,
                    input,
                    "Triage policy (severity/routing rules)> ",
                )
                lookback_hours = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Lookback hours (default 24)> "
                )
                gmail_query = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Gmail query (optional)> "
                )

                lookback_hours = lookback_hours.strip() or "24"

                click.echo("\nRunning triage...\n")

                result = await agent.trigger_and_wait(
                    "default",
                    {
                        "github_owner": github_owner,
                        "github_repo": github_repo,
                        "discord_channel_ids": discord_channel_ids,
                        "triage_policy": triage_policy,
                        "lookback_hours": lookback_hours,
                        "gmail_query": gmail_query,
                    },
                )

                if result is None:
                    click.echo("\n[Execution timed out]\n")
                    continue

                if result.success:
                    click.echo("\nTriage run completed.\n")
                    click.echo(json.dumps(result.output, indent=2, default=str))
                    click.echo()
                else:
                    click.echo(f"\nTriage failed: {result.error}\n")

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
