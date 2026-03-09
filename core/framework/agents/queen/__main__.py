"""CLI entry point for Hive Coder agent."""

import json
import logging
import sys

import click

from .agent import entry_node, goal, nodes
from .config import metadata


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
    """Hive Coder — Build Hive agent packages from natural language."""
    pass


@cli.command()
@click.option("--json", "output_json", is_flag=True)
def info(output_json):
    """Show agent information."""
    info_data = {
        "name": metadata.name,
        "version": metadata.version,
        "description": metadata.description,
        "goal": {
            "name": goal.name,
            "description": goal.description,
        },
        "nodes": [n.id for n in nodes],
        "entry_node": entry_node,
        "client_facing_nodes": [n.id for n in nodes if n.client_facing],
    }
    if output_json:
        click.echo(json.dumps(info_data, indent=2))
    else:
        click.echo(f"Agent: {info_data['name']}")
        click.echo(f"Version: {info_data['version']}")
        click.echo(f"Description: {info_data['description']}")
        click.echo(f"\nNodes: {', '.join(info_data['nodes'])}")
        click.echo(f"Client-facing: {', '.join(info_data['client_facing_nodes'])}")
        click.echo(f"Entry: {info_data['entry_node']}")


if __name__ == "__main__":
    cli()
