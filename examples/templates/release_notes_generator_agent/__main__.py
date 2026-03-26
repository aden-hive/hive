"""CLI entry point for Release Notes Generator Agent."""

import asyncio
import json
import click

from framework.runner.runner import AgentRunner


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """Release Notes Generator Agent CLI"""
    pass


@cli.command()
@click.option("--version", "-v", type=str, required=False, help="Release version")
@click.option("--verbose", is_flag=True, help="Show execution details")
def run(version, verbose):
    """Run the release notes generator agent."""

    context = {}
    if version:
        context["version"] = version

    runner = AgentRunner.load(
        "examples/templates/release_notes_generator_agent"
    )

    result = asyncio.run(runner.run(context))

    output = {
        "success": result.success,
        "steps_executed": result.steps_executed,
        "output": result.output,
    }

    if result.error:
        output["error"] = result.error

    click.echo(json.dumps(output, indent=2))


if __name__ == "__main__":
    cli()
