"""CLI entry point for Contract Intelligence & Risk Agent."""

import asyncio
import json
import logging
import sys

import click

from .agent import default_agent, ContractIntelligenceAgent


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
    """Contract Intelligence & Risk Agent — Automated Contract Review and Clause Risk Scoring."""
    pass


@cli.command()
@click.option("--file", "-f", "file_path", help="Path to contract file (PDF)")
@click.option("--text", "-t", "contract_text", help="Contract text (if no file)")
@click.option(
    "--type",
    "-y",
    "contract_type",
    help="Contract type (vendor, client, employment, saas, nda, msa)",
)
@click.option("--verbose", "-v", is_flag=True)
def run(file_path, contract_text, contract_type, verbose):
    """Execute the agent."""
    setup_logging(verbose=verbose)
    input_data = {}
    if file_path:
        input_data["file_path"] = file_path
    if contract_text:
        input_data["contract_text"] = contract_text
    if contract_type:
        input_data["contract_type"] = contract_type
    result = asyncio.run(default_agent.run(input_data))
    click.echo(
        json.dumps(
            {"success": result.success, "output": result.output},
            indent=2,
            default=str,
        )
    )
    sys.exit(0 if result.success else 1)


@cli.command()
def tui():
    """Launch TUI dashboard."""
    from pathlib import Path

    from framework.tui.app import AdenTUI
    from framework.llm import LiteLLMProvider
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.agent_runtime import create_agent_runtime
    from framework.runtime.execution_stream import EntryPointSpec

    async def run_tui():
        agent = ContractIntelligenceAgent()
        agent._tool_registry = ToolRegistry()
        storage = Path.home() / ".hive" / "agents" / "contract_intelligence_agent"
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
                    name="Analyze Contract",
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
    click.echo(f"Nodes: {', '.join(data['nodes'])}")
    click.echo(f"Client-facing: {', '.join(data['client_facing_nodes'])}")
    click.echo(f"HITL Gate: {data['hitl_gate']}")


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
    if v["warnings"]:
        click.echo("Warnings:")
        for w in v["warnings"]:
            click.echo(f"  {w}")
    sys.exit(0 if v["valid"] else 1)


if __name__ == "__main__":
    cli()
