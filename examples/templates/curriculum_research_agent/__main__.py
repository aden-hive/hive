"""
CLI entry point for Curriculum Research Agent.

Research current industry standards, align to learning outcomes using the
ADDIE framework, and generate ID-ready content briefs.
"""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent, CurriculumResearchAgent


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
    """Curriculum Research Agent - ADDIE-based content brief generation."""
    pass


@cli.command()
@click.option(
    "--topic", "-t", type=str, required=True,
    help="Research topic (e.g. 'Medication Safety for Registered Nurses')",
)
@click.option(
    "--level", "-l", type=str, default="Continuing Education",
    help="Education level (e.g. 'Continuing Education', 'Certificate', 'Diploma')",
)
@click.option(
    "--audience", "-a", type=str, default="",
    help="Target audience description",
)
@click.option(
    "--accreditation", type=str, default="",
    help="Accreditation context or standards body",
)
@click.option(
    "--brief-file", "-f", type=str, default=None,
    help="Path to a JSON file with topic, level, audience, accreditation_context",
)
@click.option("--mock", is_flag=True, help="Run in mock mode without LLM or API calls")
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(topic, level, audience, accreditation, brief_file, mock, quiet, verbose, debug):
    """Generate a content brief for the given topic."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    # Load from file if provided
    if brief_file:
        try:
            with open(brief_file, encoding="utf-8") as f:
                data = json.load(f)
            topic = data.get("topic", topic)
            level = data.get("level", level)
            audience = data.get("audience", audience)
            accreditation = data.get("accreditation_context", accreditation)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            click.echo(f"Error loading brief file: {e}", err=True)
            sys.exit(1)

    context = {
        "topic": topic,
        "level": level,
        "audience": audience,
        "accreditation_context": accreditation,
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
@click.option("--mock", is_flag=True, help="Run in mock mode")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def tui(mock, verbose, debug):
    """Launch the TUI dashboard for interactive curriculum research."""
    setup_logging(verbose=verbose, debug=debug)

    try:
        from framework.tui.app import AdenTUI
    except ImportError:
        click.echo(
            "TUI requires the 'textual' package. Install with: pip install textual"
        )
        sys.exit(1)

    async def run_with_tui():
        agent = CurriculumResearchAgent()
        await agent.start(mock_mode=mock)

        try:
            app = AdenTUI(agent._agent_runtime)
            await app.run_async()
        finally:
            await agent.stop()

    asyncio.run(run_with_tui())


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
    """Interactive curriculum research session (CLI, no TUI)."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    """Async interactive shell."""
    setup_logging(verbose=verbose)

    click.echo("=== Curriculum Research Agent ===")
    click.echo("ADDIE-based content brief generation for course development\n")

    agent = CurriculumResearchAgent()
    await agent.start()

    try:
        while True:
            try:
                topic = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Topic> "
                )
                if topic.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break

                level = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Level (e.g. Continuing Education)> "
                )
                audience = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Audience> "
                )
                accreditation = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Accreditation context> "
                )

                if not topic.strip():
                    continue

                click.echo("\nResearching and generating content brief...\n")

                result = await agent.trigger_and_wait(
                    "start",
                    {
                        "topic": topic,
                        "level": level or "Continuing Education",
                        "audience": audience,
                        "accreditation_context": accreditation,
                    },
                )

                if result is None:
                    click.echo("\n[Execution timed out]\n")
                    continue

                if result.success:
                    output = result.output
                    if "content_brief" in output:
                        click.echo("\n--- Content Brief ---\n")
                        click.echo(output["content_brief"])
                        click.echo("\n")
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
