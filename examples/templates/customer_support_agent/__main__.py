"""CLI entry point for Customer Support Agent."""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent, CustomerSupportAgent


def setup_logging(verbose=False, debug=False):
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
    """Customer Support Agent - Classify, reply, and log support tickets."""
    pass


@cli.command()
@click.option("--quiet", "-q", is_flag=True)
@click.option("--verbose", "-v", is_flag=True)
@click.option("--debug", is_flag=True)
def run(quiet, verbose, debug):
    """Run the customer support agent."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)
    result = asyncio.run(default_agent.run({}))
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
@click.option("--verbose", "-v", is_flag=True)
@click.option("--debug", is_flag=True)
def tui(verbose, debug):
    """Launch TUI dashboard."""
    setup_logging(verbose=verbose, debug=debug)
    try:
        from framework.tui.app import AdenTUI
    except ImportError:
        click.echo("TUI requires 'textual'. Install with: pip install textual")
        sys.exit(1)

    from pathlib import Path
    from framework.llm import LiteLLMProvider
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.agent_runtime import create_agent_runtime
    from framework.runtime.event_bus import EventBus
    from framework.runtime.execution_stream import EntryPointSpec

    async def run_with_tui():
        agent = CustomerSupportAgent()
        agent._event_bus = EventBus()
        agent._tool_registry = ToolRegistry()
        storage_path = Path.home() / ".hive" / "agents" / "customer_support_agent"
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
                    name="Start Support Session",
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
        click.echo(f"Client-facing: {', '.join(info_data['client_facing_nodes'])}")
        click.echo(f"Entry: {info_data['entry_node']}")
        click.echo(f"Terminal: {', '.join(info_data['terminal_nodes'])}")


@cli.command()
def validate():
    """Validate agent structure."""
    validation = default_agent.validate()
    if validation["valid"]:
        click.echo("Agent is valid")
    else:
        click.echo("Agent has errors:")
        for error in validation["errors"]:
            click.echo(f"  ERROR: {error}")
    sys.exit(0 if validation["valid"] else 1)


@cli.command()
@click.option("--verbose", "-v", is_flag=True)
def shell(verbose):
    """Interactive support session."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    setup_logging(verbose=verbose)
    click.echo("=== Customer Support Agent ===")
    click.echo("Type your issue below (or 'quit' to exit):\n")

    agent = CustomerSupportAgent()
    await agent.start()

    try:
        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Support> "
                )
                if user_input.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break
                result = await agent.trigger_and_wait("start", {})
                if result is None:
                    click.echo("\n[Execution timed out]\n")
                    continue
                if result.success:
                    output = result.output
                    if "ticket_id" in output:
                        click.echo(f"\nTicket logged: {output['ticket_id']}\n")
                else:
                    click.echo(f"\nFailed: {result.error}\n")
            except KeyboardInterrupt:
                click.echo("\nGoodbye!")
                break
    finally:
        await agent.stop()


if __name__ == "__main__":
    cli()