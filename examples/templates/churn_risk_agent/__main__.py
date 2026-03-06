"""CLI entry point for Churn Risk Agent."""

import asyncio
import json
import logging
import sys

import click

from .agent import default_agent, ChurnRiskAgent


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
    """Churn Risk Agent — detect at-risk customers and trigger retention actions."""
    pass


@cli.command()
@click.option("--account", "-a", "account_data", help="Customer account data string")
@click.option("--verbose", "-v", is_flag=True)
@click.option("--debug", is_flag=True)
def run(account_data, verbose, debug):
    """Assess churn risk for a customer account."""
    setup_logging(verbose=verbose, debug=debug)
    result = asyncio.run(
        default_agent.run({"account_data": account_data or ""})
    )
    click.echo(
        json.dumps(
            {"success": result.success, "output": result.output},
            indent=2,
            default=str,
        )
    )
    sys.exit(0 if result.success else 1)


@cli.command()
def shell():
    """Interactive shell session for churn risk assessment."""

    async def run_shell():
        agent = ChurnRiskAgent()
        await agent.start()
        try:
            print("\n🔍 Churn Risk Agent — Interactive Shell")
            print("=" * 50)
            account = input("Enter customer account data: ").strip()
            if not account:
                print("No input provided. Exiting.")
                return
            print("\n⏳ Analysing churn risk...\n")
            result = await agent.trigger_and_wait(
                "default",
                {"account_data": account},
            )
            if result and result.output:
                print("\n✅ Result:")
                print(json.dumps(result.output, indent=2, default=str))
            else:
                print("No output returned.")
        finally:
            await agent.stop()

    asyncio.run(run_shell())


@cli.command()
def tui():
    """Launch the TUI dashboard for interactive churn risk assessment."""
    from pathlib import Path
    from framework.tui.app import AdenTUI
    from framework.llm import LiteLLMProvider
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.agent_runtime import create_agent_runtime
    from framework.runtime.execution_stream import EntryPointSpec
    from framework.graph.checkpoint_config import CheckpointConfig

    async def run_tui():
        agent = ChurnRiskAgent()
        agent._tool_registry = ToolRegistry()
        storage = Path.home() / ".hive" / "agents" / "churn_risk_agent"
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
                    entry_node="signal_intake",
                    trigger_type="manual",
                    isolation_level="isolated",
                )
            ],
            llm=llm,
            tools=list(agent._tool_registry.get_tools().values()),
            tool_executor=agent._tool_registry.get_executor(),
            checkpoint_config=CheckpointConfig(
                enabled=True,
                checkpoint_on_node_complete=True,
                checkpoint_max_age_days=7,
                async_checkpoint=True,
            ),
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
    """Show agent information."""
    data = default_agent.info()
    click.echo(f"Agent:         {data['name']}")
    click.echo(f"Version:       {data['version']}")
    click.echo(f"Description:   {data['description']}")
    click.echo(f"Nodes:         {', '.join(data['nodes'])}")
    click.echo(f"Client-facing: {', '.join(data['client_facing_nodes'])}")
    click.echo(f"Entry node:    {data['entry_node']}")
    click.echo(f"Terminal:      {', '.join(data['terminal_nodes'])}")


@cli.command()
def validate():
    """Validate the agent structure."""
    v = default_agent.validate()
    if v["valid"]:
        click.echo("✅ Agent structure is valid")
    else:
        click.echo("❌ Errors found:")
        for e in v["errors"]:
            click.echo(f"  - {e}")
    sys.exit(0 if v["valid"] else 1)


if __name__ == "__main__":
    cli()
