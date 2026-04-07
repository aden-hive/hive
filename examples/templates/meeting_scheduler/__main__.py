"""CLI entry point for Meeting Scheduler."""

import asyncio
import json
import logging
import sys
import click
from .agent import default_agent, MeetingScheduler


def setup_logging(verbose=False, debug=False):
    if debug:
        level, fmt = logging.DEBUG, "%(asctime)s %(name)s: %(message)s"
    elif verbose:
        level, fmt = logging.INFO, "%(message)s"
    else:
        level, fmt = logging.WARNING, "%(levelname)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """Meeting Scheduler — Find available times on your calendar and book meetings."""
    pass


@cli.command()
@click.option("--attendee", "-a", required=True, help="Attendee email address")
@click.option("--duration", "-d", type=int, required=True, help="Meeting duration in minutes")
@click.option("--title", "-t", required=True, help="Meeting title")
@click.option("--verbose", "-v", is_flag=True)
def run(attendee, duration, title, verbose):
    """Execute the scheduler."""
    setup_logging(verbose=verbose)
    result = asyncio.run(
        default_agent.run(
            {
                "attendee_email": attendee,
                "meeting_duration_minutes": str(duration),
                "meeting_title": title,
            }
        )
    )
    click.echo(
        json.dumps({"success": result.success, "output": result.output}, indent=2, default=str)
    )
    sys.exit(0 if result.success else 1)


@cli.command()
def tui():
    """Launch TUI dashboard."""
    from pathlib import Path
    from framework.tui.app import AdenTUI
    from framework.llm import LiteLLMProvider
    from framework.loader.tool_registry import ToolRegistry
    from framework.host.agent_host import create_agent_runtime
    from framework.host.execution_manager import EntryPointSpec

    async def run_tui():
        agent = MeetingScheduler()
        agent._tool_registry = ToolRegistry()
        storage = Path.home() / ".hive" / "agents" / "meeting_scheduler"
        storage.mkdir(parents=True, exist_ok=True)
        mcp_cfg = Path(__file__).parent / "mcp_servers.json"
        if mcp_cfg.exists():
            agent._tool_registry.load_mcp_config(mcp_cfg)
        llm = LiteLLMProvider(
            model=agent.config.model,
            api_key=agent.config.api_key,
            api_base=agent.config.api_base,
        )
        runtime = create_agent_runtime(
            graph=agent._build_graph(),
            goal=agent.goal,
            storage_path=storage,
            entry_points=[
                EntryPointSpec(
                    id="start",
                    name="Start",
                    entry_node="intake",
                    trigger_type="manual",
                    isolation_level="isolated",
                )
            ],
            llm=llm,
            tools=list(agent._tool_registry.get_tools().values()),
            tool_executor=agent._tool_registry.get_executor(),
        )
        await runtime.start()
        try:
            app = AdenTUI(runtime)
            await app.run_async()
        finally:
            await runtime.stop()

    asyncio.run(run_tui())


@cli.command()
def info():
    """Show agent info."""
    data = default_agent.info()
    click.echo(
        f"Agent: {data['name']}\nVersion: {data['version']}\nDescription: {data['description']}"
    )
    click.echo(
        f"Nodes: {', '.join(data['nodes'])}\nClient-facing: {', '.join(data['client_facing_nodes'])}"
    )


@cli.command()
def validate():
    """Validate agent structure."""
    v = default_agent.validate()
    if v["valid"]:
        click.echo("Agent is valid")
    else:
        click.echo("Errors:")
        for e in v["errors"]:
            click.echo(f"  {e}")
    sys.exit(0 if v["valid"] else 1)


if __name__ == "__main__":
    cli()
