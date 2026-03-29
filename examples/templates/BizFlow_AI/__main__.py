"""
CLI entry point for BizFlow AI.
"""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent, BizFlowAgent


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
    """BizFlow AI - Generate multi-pipeline n8n workflows."""
    pass


@cli.command()
@click.option(
    "--requirements",
    "-r",
    type=str,
    default=None,
    help="Natural language requirements for the workflow",
)
@click.option("--file", "-f", type=str, help="JSON file with requirements")
@click.option("--output", "-o", type=str, help="Output file for the workflow")
@click.option("--quiet", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(requirements, file, output, quiet, verbose, debug):
    """Generate n8n workflow from requirements."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    # Get requirements
    if file:
        with open(file, 'r') as f:
            data = json.load(f)
            req_text = data.get("requirements", "")
    elif requirements:
        req_text = requirements
    else:
        req_text = "Create a multi-pipeline automation with CV screening and revenue monitoring"

    context = {"requirements": req_text}

    result = asyncio.run(default_agent.run(context))

    output_data = {
        "success": result.success,
        "steps_executed": result.steps_executed,
        "output": result.output,
    }
    if result.error:
        output_data["error"] = result.error

    # Save to file if requested
    if output and result.success and result.output:
        workflow = result.output.get("final_workflow", {})
        with open(output, 'w') as f:
            json.dump(workflow, f, indent=2)
        if not quiet:
            click.echo(f"Workflow saved to {output}")

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


if __name__ == "__main__":
    cli()