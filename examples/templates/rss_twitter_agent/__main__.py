"""CLI for RSS-to-Twitter Playwright agent."""

from __future__ import annotations

import asyncio
import json
import sys

import click

from .agent import default_agent
from .run import run_interactive


@click.group()
@click.version_option(version="1.1.0")
def cli() -> None:
    """RSS-to-Twitter Playwright agent."""


@cli.command()
@click.option("--feed-url", default="https://news.ycombinator.com/rss", show_default=True)
@click.option("--max-articles", default=3, show_default=True, type=int)
@click.option(
    "--twitter-credential-ref",
    default=None,
    help="Hive credential reference in {name}/{alias} format (example: twitter/default).",
)
def run(feed_url: str, max_articles: int, twitter_credential_ref: str | None) -> None:
    """Run the interactive RSS -> summarize -> approve -> post flow."""
    summary = asyncio.run(
        run_interactive(
            feed_url=feed_url,
            max_articles=max_articles,
            twitter_credential_ref=twitter_credential_ref,
        )
    )
    click.echo(json.dumps(summary, indent=2, default=str))
    sys.exit(0)


@cli.command()
def validate() -> None:
    """Validate basic graph structure metadata."""
    result = default_agent.validate()
    if result["valid"]:
        click.echo("Agent is valid")
        return
    click.echo("Agent has errors:")
    for err in result["errors"]:
        click.echo(f"  ERROR: {err}")
    sys.exit(1)


@cli.command()
@click.option("--json", "output_json", is_flag=True)
def info(output_json: bool) -> None:
    """Show agent metadata."""
    data = default_agent.info()
    if output_json:
        click.echo(json.dumps(data, indent=2))
        return
    click.echo(f"Agent: {data['name']}")
    click.echo(f"Version: {data['version']}")
    click.echo(f"Description: {data['description']}")
    click.echo(f"Nodes: {', '.join(data['nodes'])}")
    click.echo(f"Entry: {data['entry_node']}")
    click.echo(f"Terminal: {', '.join(data['terminal_nodes'])}")


if __name__ == "__main__":
    cli()
