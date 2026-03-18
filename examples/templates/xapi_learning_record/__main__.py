"""
CLI entry point for xAPI Learning Record Agent.

Captures learning events as xAPI 1.0.3 statements and dispatches them
to an LRS via HTTP Basic auth. No LLM required for the core pipeline.
"""

import asyncio
import json
import logging
import sys

import click

from .agent import XAPILearningRecordAgent, default_agent


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
@click.version_option(version="0.1.0")
def cli():
    """xAPI Learning Record Agent - Deterministic LRS statement pipeline."""
    pass


@cli.command()
@click.option(
    "--actor-name", "-n", type=str, required=True, help="Learner full name"
)
@click.option(
    "--actor-mbox",
    "-e",
    type=str,
    required=True,
    help="Learner email (mailto: prefix added automatically if missing)",
)
@click.option(
    "--verb-id",
    "-v",
    type=str,
    required=True,
    help="xAPI verb IRI (e.g. http://adlnet.gov/expapi/verbs/completed)",
)
@click.option(
    "--verb-display",
    "-d",
    type=str,
    required=True,
    help="Human-readable verb label (e.g. completed)",
)
@click.option(
    "--object-id",
    "-o",
    type=str,
    required=True,
    help="Activity IRI (e.g. https://example.com/activities/intro-course)",
)
@click.option(
    "--object-name",
    "-a",
    type=str,
    required=True,
    help="Human-readable activity name",
)
@click.option(
    "--score-raw", type=float, default=None, help="Raw score (optional)"
)
@click.option(
    "--score-min", type=float, default=None, help="Minimum possible score (optional)"
)
@click.option(
    "--score-max", type=float, default=None, help="Maximum possible score (optional)"
)
@click.option(
    "--score-scaled",
    type=float,
    default=None,
    help="Scaled score 0.0-1.0 (optional)",
)
@click.option(
    "--completion/--no-completion",
    default=None,
    help="Whether the activity was completed (optional)",
)
@click.option(
    "--success/--no-success",
    "result_success",
    default=None,
    help="Whether the activity was passed (optional)",
)
@click.option(
    "--lrs-endpoint",
    type=str,
    default=None,
    help="Override LRS endpoint URL (uses config.py default if omitted)",
)
@click.option(
    "--lrs-username",
    type=str,
    default=None,
    help="Override LRS username (uses config.py default if omitted)",
)
@click.option(
    "--lrs-password",
    type=str,
    default=None,
    help="Override LRS password (uses config.py default if omitted)",
)
@click.option("--mock", is_flag=True, help="Run in mock mode without LLM or LRS calls")
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-V", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(
    actor_name,
    actor_mbox,
    verb_id,
    verb_display,
    object_id,
    object_name,
    score_raw,
    score_min,
    score_max,
    score_scaled,
    completion,
    result_success,
    lrs_endpoint,
    lrs_username,
    lrs_password,
    mock,
    quiet,
    verbose,
    debug,
):
    """Record a learning event as an xAPI statement and dispatch to LRS."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    # Normalize mbox
    if actor_mbox and not actor_mbox.startswith("mailto:"):
        actor_mbox = f"mailto:{actor_mbox}"

    # Build event dict
    learning_event: dict = {
        "actor": {"name": actor_name, "mbox": actor_mbox},
        "verb": {"id": verb_id, "display": verb_display},
        "object": {"id": object_id, "name": object_name},
    }

    # Optional result
    score: dict = {}
    if score_raw is not None:
        score["raw"] = score_raw
    if score_min is not None:
        score["min"] = score_min
    if score_max is not None:
        score["max"] = score_max
    if score_scaled is not None:
        score["scaled"] = score_scaled

    result: dict = {}
    if score:
        result["score"] = score
    if completion is not None:
        result["completion"] = completion
    if result_success is not None:
        result["success"] = result_success

    if result:
        learning_event["result"] = result

    context: dict = {"learning_event": json.dumps(learning_event)}

    # Optional LRS credential overrides
    if lrs_endpoint:
        context["lrs_endpoint"] = lrs_endpoint
    if lrs_username:
        context["lrs_username"] = lrs_username
    if lrs_password:
        context["lrs_password"] = lrs_password

    result_obj = asyncio.run(default_agent.run(context, mock_mode=mock))

    output_data = {
        "success": result_obj.success,
        "steps_executed": result_obj.steps_executed,
        "output": result_obj.output,
    }
    if result_obj.error:
        output_data["error"] = result_obj.error

    click.echo(json.dumps(output_data, indent=2, default=str))
    sys.exit(0 if result_obj.success else 1)


@cli.command()
@click.option("--mock", is_flag=True, help="Run in mock mode")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def tui(mock, verbose, debug):
    """Launch the TUI dashboard for interactive xAPI event recording."""
    setup_logging(verbose=verbose, debug=debug)

    try:
        from framework.tui.app import AdenTUI
    except ImportError:
        click.echo(
            "TUI requires the 'textual' package. Install with: pip install textual"
        )
        sys.exit(1)

    async def run_with_tui():
        agent = XAPILearningRecordAgent()
        await agent.start(mock_mode=mock)

        try:
            app = AdenTUI(agent._agent_runtime)
            await app.run_async()
        finally:
            await agent.stop()

    asyncio.run(run_with_tui())


@cli.command()
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
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
        click.echo(f"Terminal: {', '.join(info_data['terminal_nodes']) or '(none — loops)'}")


@cli.command()
def validate():
    """Validate agent graph structure."""
    validation = default_agent.validate()
    if validation["valid"]:
        click.echo("Agent is valid")
        for warning in validation.get("warnings", []):
            click.echo(f"  WARNING: {warning}")
    else:
        click.echo("Agent has errors:")
        for error in validation["errors"]:
            click.echo(f"  ERROR: {error}")
    sys.exit(0 if validation["valid"] else 1)


@cli.command()
@click.option("--mock", is_flag=True, help="Run in mock mode (skip LRS dispatch)")
@click.option("--verbose", "-v", is_flag=True)
def shell(mock, verbose):
    """Interactive xAPI event recording session (CLI, no TUI)."""
    asyncio.run(_interactive_shell(mock=mock, verbose=verbose))


async def _interactive_shell(mock: bool = False, verbose: bool = False):
    """Async interactive shell for recording learning events."""
    setup_logging(verbose=verbose)

    click.echo("=== xAPI Learning Record Agent ===")
    click.echo(
        "Enter learning events interactively. "
        "Provide actor, verb, object as prompted.\n"
        "Type 'quit' to exit.\n"
    )

    agent = XAPILearningRecordAgent()
    await agent.start(mock_mode=mock)

    try:
        while True:
            try:
                actor_name = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Actor name> "
                )
                if actor_name.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break

                actor_mbox = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Actor email> "
                )
                verb_id = await asyncio.get_event_loop().run_in_executor(
                    None,
                    input,
                    "Verb IRI (e.g. http://adlnet.gov/expapi/verbs/completed)> ",
                )
                verb_display = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Verb display (e.g. completed)> "
                )
                object_id = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Object IRI> "
                )
                object_name = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Object name> "
                )

                if not actor_name.strip():
                    continue

                if not actor_mbox.startswith("mailto:"):
                    actor_mbox = f"mailto:{actor_mbox}"

                learning_event = {
                    "actor": {"name": actor_name, "mbox": actor_mbox},
                    "verb": {"id": verb_id, "display": verb_display},
                    "object": {"id": object_id, "name": object_name},
                }

                click.echo("\nRecording...\n")
                result = await agent.trigger_and_wait(
                    "default",
                    {"learning_event": json.dumps(learning_event)},
                )

                if result is None:
                    click.echo("\n[Execution timed out]\n")
                elif result.success:
                    output = result.output
                    if "confirmation" in output:
                        conf = (
                            json.loads(output["confirmation"])
                            if isinstance(output["confirmation"], str)
                            else output["confirmation"]
                        )
                        if conf.get("success"):
                            click.echo(
                                f"\nRecorded — Statement ID: {conf.get('statement_id')}\n"
                            )
                        else:
                            click.echo(
                                f"\nFailed — {conf.get('errors', [])}\n"
                            )
                else:
                    click.echo(f"\nFailed: {result.error}\n")

            except (KeyboardInterrupt, EOFError):
                click.echo("\nGoodbye!")
                break
            except Exception as exc:
                click.echo(f"Error: {exc}", err=True)
    finally:
        await agent.stop()


if __name__ == "__main__":
    cli()
