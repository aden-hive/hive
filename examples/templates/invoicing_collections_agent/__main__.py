"""CLI entry point for Invoicing & Collections Agent."""

import asyncio
import json
import logging
import sys

import click

from .agent import default_agent


def setup_logging(verbose=False, debug=False):
    if debug:
        level, fmt = logging.DEBUG, "%(asctime)s %(name)s: %(message)s"
    elif verbose:
        level, fmt = logging.INFO, "%(message)s"
    else:
        level, fmt = logging.WARNING, "%(levelname)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """Invoicing & Collections Agent — automated AR collections with HITL escalation."""
    pass


@cli.command()
@click.option("--file", "-f", "invoice_file", help="Path to invoice CSV file")
@click.option("--verbose", "-v", is_flag=True)
def run(invoice_file, verbose):
    """Execute the agent."""
    setup_logging(verbose=verbose)
    result = asyncio.run(default_agent.run({"invoice_file_path": invoice_file or ""}))
    click.echo(
        json.dumps(
            {"success": result.success, "output": result.output},
            indent=2,
            default=str,
        )
    )
    sys.exit(0 if result.success else 1)


@cli.command()
def info():
    """Show agent info."""
    data = default_agent.info()
    click.echo(f"Agent: {data['name']}")
    click.echo(f"Version: {data['version']}")
    click.echo(f"Description: {data['description']}")
    click.echo(f"Nodes: {', '.join(data['nodes'])}")
    click.echo(f"Client-facing: {', '.join(data['client_facing_nodes'])}")


@cli.command()
def validate():
    """Validate agent structure."""
    v = default_agent.validate()
    if v["valid"]:
        click.echo("Agent is valid")
    else:
        click.echo("Errors:")
        for e in v["errors"]:
            click.echo(f"  {e}")
    sys.exit(0 if v["valid"] else 1)


if __name__ == "__main__":
    cli()
