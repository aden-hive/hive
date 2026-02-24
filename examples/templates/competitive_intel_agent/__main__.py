"""
CLI entry point for Competitive Intelligence Agent.

Uses AgentRuntime for multi-entrypoint support with HITL pause/resume.
"""

import asyncio
import json
import logging
import sys
from typing import Any
from pathlib import Path

import click

from .agent import CompetitiveIntelAgent, default_agent


def setup_logging(verbose: bool = False, debug: bool = False) -> None:
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
def cli() -> None:
    """Competitive Intelligence Agent - Monitor competitors and deliver weekly digests."""
    pass


@cli.command()
@click.option(
    "--competitors",
    "-c",
    type=str,
    required=True,
    help='Competitors JSON string or file path (e.g. \'[{"name":"Acme","website":"https://acme.com"}]\')',
)
@click.option(
    "--focus-areas",
    "-f",
    type=str,
    default="pricing,features,partnerships,hiring",
    help="Comma-separated focus areas (default: pricing,features,partnerships,hiring)",
)
@click.option(
    "--frequency",
    type=click.Choice(["weekly", "daily", "monthly"]),
    default="weekly",
    help="Report frequency (default: weekly)",
)
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(
    competitors: str,
    focus_areas: str,
    frequency: str,
    quiet: bool,
    verbose: bool,
    debug: bool,
) -> None:
    """Execute competitive intelligence gathering and report generation."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    # Parse competitors — accept JSON string or file path
    try:
        competitors_data = json.loads(competitors)
    except json.JSONDecodeError:
        # Try loading from file
        try:
            with open(competitors) as f:
                competitors_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            click.echo(f"Error parsing competitors: {e}", err=True)
            sys.exit(1)

    context: dict[str, Any] = {
        "competitors_input": json.dumps({
            "competitors": competitors_data,
            "focus_areas": [a.strip() for a in focus_areas.split(",")],
            "report_frequency": frequency,
        })
    }

    result = asyncio.run(default_agent.run(context))

    output_data: dict[str, Any] = {
        "success": result.success,
        "steps_executed": result.steps_executed,
        "output": result.output,
    }
    if result.error:
        output_data["error"] = result.error

    click.echo(json.dumps(output_data, indent=2, default=str))
    sys.exit(0 if result.success else 1)


@cli.command()
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def tui(verbose: bool, debug: bool) -> None:
    """Launch the TUI dashboard for interactive competitive intelligence."""
    setup_logging(verbose=verbose, debug=debug)

    try:
        from framework.tui.app import AdenTUI
    except ImportError:
        click.echo(
            "TUI requires the 'textual' package. Install with: pip install textual"
        )
        sys.exit(1)

    from framework.llm import LiteLLMProvider
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.agent_runtime import create_agent_runtime
    from framework.runtime.event_bus import EventBus
    from framework.runtime.execution_stream import EntryPointSpec

    async def run_with_tui() -> None:
        agent = CompetitiveIntelAgent()

        # Build graph and tools
        agent._event_bus = EventBus()
        agent._tool_registry = ToolRegistry()

        storage_path = Path.home() / ".hive" / "agents" / "competitive_intel_agent"
        storage_path.mkdir(parents=True, exist_ok=True)

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            agent._tool_registry.load_mcp_config(mcp_config_path)

        llm = LiteLLMProvider(
            model=agent.config.model,
            api_key=agent.config.api_key,
            api_base=agent.config.api_base,
        )

        tools = list(agent._tool_registry.get_tools().values())
        tool_executor = agent._tool_registry.get_executor()
        graph = agent._build_graph()

        runtime = create_agent_runtime(
            graph=graph,
            goal=agent.goal,
            storage_path=storage_path,
            entry_points=[
                EntryPointSpec(
                    id="start",
                    name="Start Competitive Analysis",
                    entry_node="intake",
                    trigger_type="manual",
                    isolation_level="isolated",
                ),
            ],
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
        )

        await runtime.start()

        try:
            app = AdenTUI(runtime)
            await app.run_async()
        finally:
            await runtime.stop()

    asyncio.run(run_with_tui())


@cli.command()
@click.option("--json", "output_json", is_flag=True)
def info(output_json: bool) -> None:
    """Show agent information."""
    info_data = default_agent.info()
    if output_json:
        click.echo(json.dumps(info_data, indent=2))
    else:
        click.echo(f"Agent: {info_data['name']}")
        click.echo(f"Version: {info_data['version']}")
        click.echo(f"Description: {info_data['description']}")
        click.echo(f"\nGoal: {info_data['goal']['name']}")
        click.echo(f"  {info_data['goal']['description']}")
        click.echo(f"\nNodes: {', '.join(info_data['nodes'])}")
        # click.echo(f"Client-facing: {', '.join(info_data['client_facing_nodes'])}")
        click.echo(f"Entry: {info_data['entry_node']}")
        click.echo(f"Terminal: {', '.join(info_data['terminal_nodes'])}")
        click.echo(f"Edges: {len(info_data['edges'])}")


@cli.command()
def validate() -> None:
    """Validate agent structure."""
    validation = default_agent.validate()
    if validation["valid"]:
        click.echo("✅ Agent is valid")
        if validation["warnings"]:
            for warning in validation["warnings"]:
                click.echo(f"  ⚠️  {warning}")
    else:
        click.echo("❌ Agent has errors:")
        for error in validation["errors"]:
            click.echo(f"  ERROR: {error}")
    sys.exit(0 if validation["valid"] else 1)


@cli.command()
@click.option("--verbose", "-v", is_flag=True)
def shell(verbose: bool) -> None:
    """Interactive competitive intelligence session (CLI, no TUI)."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose: bool = False) -> None:
    """Async interactive shell."""
    setup_logging(verbose=verbose)

    click.echo("=== Competitive Intelligence Agent ===")
    click.echo("Provide competitor details to begin analysis (or 'quit' to exit):\n")

    agent = CompetitiveIntelAgent()
    await agent.start()

    try:
        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Competitors> "
                )
                if user_input.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break

                if not user_input.strip():
                    continue

                click.echo("\nGathering competitive intelligence...\n")

                result = await agent.trigger_and_wait(
                    "start", {"competitors_input": user_input}
                )

                if result is None:
                    click.echo("\n[Execution timed out]\n")
                    continue

                if result.success:
                    output = result.output
                    status = output.get("delivery_status", "unknown")
                    click.echo(f"\nAnalysis complete (status: {status})\n")
                else:
                    click.echo(f"\nAnalysis failed: {result.error}\n")

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
