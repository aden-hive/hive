"""CLI entry point for AI Paper Research Agent."""

import asyncio
import json
import logging
import sys

import click

from .agent import AIPaperResearchAgent, default_agent


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
    """AI Paper Research Agent - deep understanding for ML papers."""


@cli.command()
@click.option("--objective", "-o", type=str, required=True, help="Research objective")
@click.option(
    "--paper-pdf",
    "paper_pdfs",
    multiple=True,
    type=str,
    help="Optional local PDF path(s) for direct pdf_read analysis",
)
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(objective, paper_pdfs, quiet, verbose, debug):
    """Execute deep research for an AI-paper objective."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    context = {
        "objective": objective,
        "paper_pdf_paths": list(paper_pdfs) if paper_pdfs else [],
    }

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
    """Interactive paper research session (CLI)."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    """Async interactive shell."""
    setup_logging(verbose=verbose)

    click.echo("=== AI Paper Research Agent ===")
    click.echo("Enter a research objective (or 'quit' to exit):\n")

    agent = AIPaperResearchAgent()
    await agent.start()

    try:
        while True:
            try:
                objective = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Objective> "
                )
                if objective.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break

                if not objective.strip():
                    continue

                click.echo("\nResearching papers...\n")

                result = await agent.trigger_and_wait(
                    "start", {"objective": objective, "paper_pdf_paths": []}
                )

                if result is None:
                    click.echo("\n[Execution timed out]\n")
                    continue

                if result.success:
                    output = result.output
                    status = output.get("delivery_status", "unknown")
                    click.echo(f"\nResearch complete (status: {status})\n")
                else:
                    click.echo(f"\nResearch failed: {result.error}\n")

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
