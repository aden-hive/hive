"""CLI entry point for Release Notes Generator Agent."""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent, ReleaseNotesGeneratorAgent


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
    """Release Notes Generator Agent - Generate structured release notes from GitHub commits."""
    pass


@cli.command()
@click.option("--repo", required=True, help="GitHub repository in format 'owner/repo'")
@click.option("--from-tag", required=True, help="Starting tag for release notes")
@click.option("--to-tag", required=True, help="Ending tag for release notes")
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(repo, from_tag, to_tag, quiet, verbose, debug):
    """Execute the release notes generation workflow."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    # Map CLI inputs to node inputs (intake_node expects repo/version/since)
    context = {
        "repo": repo,
        "version": from_tag,
        "since": to_tag,
    }

    result = asyncio.run(default_agent.run(context))

    output_data = {
        "success": result.success,
        "steps_executed": result.steps_executed,
        "output": result.output,
    }

    if result.error:
        output_data["error"] = result.error

    if quiet:
        click.echo(json.dumps(output_data, indent=2))
    else:
        if result.success:
            click.echo("Release notes generated successfully!")
        else:
            click.echo("Failed to generate release notes")
            if result.error:
                click.echo(f"Error: {result.error}")
        click.echo(json.dumps(output_data, indent=2))


@cli.command()
def info():
    """Show agent information."""
    info_data = default_agent.info()
    click.echo(json.dumps(info_data, indent=2))


@cli.command()
def validate():
    """Validate agent configuration."""
    validation = default_agent.validate()
    if validation["valid"]:
        click.echo("Agent configuration is valid")
    else:
        click.echo("Agent configuration has errors:")
        for error in validation["errors"]:
            click.echo(f"  - {error}")
    click.echo(json.dumps(validation, indent=2))


if __name__ == "__main__":
    cli()
