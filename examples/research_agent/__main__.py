"""
CLI entry point for Research Agent.
"""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent


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
    """Research + Summary Agent - Gathers info, extracts key points, and summarizes."""
    pass


@cli.command()
@click.option("--query", "-q", type=str, required=True, help="Research query")
@click.option("--quiet", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(query, quiet, verbose, debug):
    """Execute research on a query."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    context = {"query": query}

    result = asyncio.run(default_agent.run(context))

    if result.success:
        if not quiet:
            click.echo("\n\n--- SUMMARY ---\n")
            click.echo(result.output.get("final_summary", "No summary generated."))
            click.echo("\n-----------------\n")
        else:
            click.echo(json.dumps({"success": True, "output": result.output}))
        sys.exit(0)
    else:
        if not quiet:
            click.echo(f"\nExecution failed: {result.error}", err=True)
        else:
            click.echo(json.dumps({"success": False, "error": result.error}))
        sys.exit(1)


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


if __name__ == "__main__":
    cli()
