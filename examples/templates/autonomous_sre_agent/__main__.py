"""CLI entry point for Autonomous SRE Incident Resolution Agent."""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent, AutonomousSREAgent


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
    """Autonomous SRE Incident Resolution Agent."""
    pass


@cli.command()
@click.option("--service", "-s", required=True, help="Service name (e.g. payment-service)")
@click.option("--alert-type", "-a", required=True, help="Alert type (e.g. high_error_rate)")
@click.option("--mock", is_flag=True, help="Run in mock LLM mode")
@click.option("--verbose", "-v", is_flag=True)
@click.option("--debug", is_flag=True)
def run(service, alert_type, mock, verbose, debug):
    """Run incident resolution for a given alert."""
    if not mock:
        setup_logging(verbose=verbose, debug=debug)

    context = {
        "alert": json.dumps({
            "service": service,
            "alert_type": alert_type,
            "started_at": "now",
            "description": f"{alert_type} detected on {service}",
        })
    }

    result = asyncio.run(default_agent.run(context, mock_mode=mock))
    output = {"success": result.success, "output": result.output}
    if result.error:
        output["error"] = result.error
    click.echo(json.dumps(output, indent=2, default=str))
    sys.exit(0 if result.success else 1)


@cli.command()
@click.option("--mock", is_flag=True)
@click.option("--verbose", "-v", is_flag=True)
@click.option("--debug", is_flag=True)
def tui(mock, verbose, debug):
    """Launch the TUI dashboard for interactive incident resolution."""
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
        agent = AutonomousSREAgent()
        agent._event_bus = EventBus()
        agent._tool_registry = ToolRegistry()

        from .tools import (
            fetch_mock_logs, get_similar_incidents,
            draft_slack_message, draft_jira_ticket, store_incident_outcome,
        )
        for fn in [fetch_mock_logs, get_similar_incidents, draft_slack_message,
                   draft_jira_ticket, store_incident_outcome]:
            agent._tool_registry.register_function(fn)

        storage_path = Path.home() / ".hive" / "agents" / "autonomous_sre"
        storage_path.mkdir(parents=True, exist_ok=True)

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            agent._tool_registry.load_mcp_config(mcp_config_path)

        llm = None
        if not mock:
            llm = LiteLLMProvider(
                model=agent.config.model,
                api_key=agent.config.api_key,
                api_base=agent.config.api_base,
            )

        tools = list(agent._tool_registry.get_tools().values())
        tool_executor = agent._tool_registry.get_executor()
        graph = agent._build_graph()

        from framework.runtime.agent_runtime import create_agent_runtime
        runtime = create_agent_runtime(
            graph=graph,
            goal=agent.goal,
            storage_path=storage_path,
            entry_points=[
                EntryPointSpec(
                    id="start",
                    name="Start Incident Resolution",
                    entry_node="alert-intake",
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
        click.echo(f"Nodes: {', '.join(info_data['nodes'])}")
        click.echo(f"Client-facing: {', '.join(info_data['client_facing_nodes'])}")
        click.echo(f"Entry: {info_data['entry_node']}")
        click.echo(f"Terminal: {', '.join(info_data['terminal_nodes']) or '(forever-alive)'}")


@cli.command()
def validate():
    """Validate agent structure."""
    result = default_agent.validate()
    if result["valid"]:
        click.echo("Agent is valid")
        for w in result["warnings"]:
            click.echo(f"  WARNING: {w}")
    else:
        click.echo("Agent has errors:")
        for e in result["errors"]:
            click.echo(f"  ERROR: {e}")
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    cli()
