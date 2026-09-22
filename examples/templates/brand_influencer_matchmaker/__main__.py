"""
CLI entry point for Brand-Influencer Matchmaker Agent.

Uses AgentRuntime for multi-entrypoint support with HITL pause/resume.
"""

import asyncio
import json
import logging
import sys
import click
from pathlib import Path

# Importing from .graph as that is where we defined the class in the previous step
from .agent import default_agent, BrandInfluencerMatchmakerAgent


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
    """Brand-Influencer Matchmaker - Autonomous affinity scoring & sales briefs."""
    pass


@cli.command()
@click.option("--brand", "-b", type=str, required=True, help="Brand Website URL (e.g., https://nike.com)")
@click.option("--influencer", "-i", type=str, required=True, help="Influencer Name or Handle")
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(brand, influencer, quiet, verbose, debug):
    """Execute a match analysis between a Brand and an Influencer."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    # Pass the inputs expected by the Intake/Graph
    context = {
        "brand_url": brand,
        "influencer_query": influencer
    }

    if not quiet:
        click.echo(f"Starting analysis for Brand: {brand} + Influencer: {influencer}...")

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
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def tui(verbose, debug):
    """Launch the TUI dashboard for interactive matchmaking."""
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

    async def run_with_tui():
        agent = BrandInfluencerMatchmakerAgent()

        agent._event_bus = EventBus()
        agent._tool_registry = ToolRegistry()

        storage_path = Path.home() / ".hive" / "agents" / "brand_influencer_matchmaker"
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
        print(tools)
        tool_executor = agent._tool_registry.get_executor()
        graph = agent._build_graph()

        runtime = create_agent_runtime(
            graph=graph,
            goal=agent.goal,
            storage_path=storage_path,
            entry_points=[
                EntryPointSpec(
                    id="start",
                    name="Start Match Analysis",
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


@cli.command()
@click.option("--verbose", "-v", is_flag=True)
def shell(verbose):
    """Interactive matchmaking session (CLI, no TUI)."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    """Async interactive shell."""
    setup_logging(verbose=verbose)

    click.echo("=== Brand-Influencer Matchmaker ===")
    click.echo("Identify the perfect partnership opportunities.\n")

    agent = BrandInfluencerMatchmakerAgent()
    await agent.start()

    try:
        while True:
            try:
                # We need two inputs for this agent
                click.echo("\n--- New Analysis ---")
                brand = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Brand URL (or 'q' to quit)> "
                )
                if brand.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break

                if not brand.strip():
                    continue

                influencer = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Influencer Handle/Name> "
                )
                if not influencer.strip():
                    click.echo("Influencer is required.")
                    continue

                click.echo(f"\nAnalyzing match: {brand} <-> {influencer}...\n")

                # Trigger the agent
                result = await agent.trigger_and_wait(
                    "start",
                    {"brand_url": brand, "influencer_query": influencer}
                )

                if result is None:
                    click.echo("\n[Execution timed out]\n")
                    continue

                if result.success:
                    output = result.output

                    # Display Match Data if available
                    if "match_data" in output:
                        match = output["match_data"]
                        score = match.get("score", "N/A")
                        reasons = match.get("reasons", [])

                        click.echo("\n" + "="*30)
                        click.echo(f" MATCH SCORE: {score}/100")
                        click.echo("="*30)

                        if reasons:
                            click.echo("\nKey Drivers:")
                            for r in reasons:
                                click.echo(f"- {r}")

                    # Display Report Location
                    if "final_brief" in output:
                        click.echo(f"\n[SUCCESS] Sales Brief generated: {output['final_brief']}")
                        click.echo("Open the file in your browser to view the full report.")

                    click.echo("\n")
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
