"""CLI entry point for Linear Triage & Auto-Labeling Agent."""

import asyncio
import json
import logging
import sys
from datetime import datetime

import click

from .agent import LinearTriageAgent, default_agent


def setup_logging(verbose: bool = False, debug: bool = False) -> None:
    """Configure logging based on verbosity level."""
    if debug:
        level, fmt = logging.DEBUG, "%(asctime)s %(name)s: %(message)s"
    elif verbose:
        level, fmt = logging.INFO, "%(message)s"
    else:
        level, fmt = logging.WARNING, "%(levelname)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)


@click.group()
@click.version_option(version="1.0.0")
def cli() -> None:
    """Linear Triage & Auto-Labeling Agent — Router Pattern with Conditional Edges."""
    pass


@cli.command()
@click.option("--issue", "-i", "raw_issue", required=True, help="Raw issue description to triage")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
def run(raw_issue: str, verbose: bool) -> None:
    """Execute the triage agent on a raw issue description.

    Example:
        python -m linear_triage_agent --issue "Login page crashes on Safari"
    """
    setup_logging(verbose=verbose)

    click.echo(f"Triage starting at {datetime.now().isoformat()}")
    click.echo(f"Issue: {raw_issue[:100]}{'...' if len(raw_issue) > 100 else ''}")
    click.echo("-" * 60)

    result = asyncio.run(default_agent.run({"raw_issue": raw_issue}))

    output = {
        "success": result.success,
        "output": result.output if result.output else {},
        "error": result.error if result.error else None,
    }

    click.echo(json.dumps(output, indent=2, default=str))
    sys.exit(0 if result.success else 1)


@cli.command()
def tui() -> None:
    """Launch TUI dashboard for interactive triage."""
    from pathlib import Path

    from framework.llm import LiteLLMProvider
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.agent_runtime import create_agent_runtime
    from framework.runtime.execution_stream import EntryPointSpec
    from framework.tui.app import AdenTUI

    async def run_tui() -> None:
        agent = LinearTriageAgent()
        agent._tool_registry = ToolRegistry()

        storage = Path.home() / ".hive" / "agents" / "linear_triage_agent"
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
                    name="Triage Issue",
                    entry_node="classify",
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
def info() -> None:
    """Show agent information."""
    data = default_agent.info()

    click.echo(f"Agent: {data['name']}")
    click.echo(f"Version: {data['version']}")
    click.echo(f"Description: {data['description']}")
    click.echo()
    click.echo(f"Pattern: {data['pattern']}")
    click.echo(f"Nodes: {', '.join(data['nodes'])}")
    click.echo(f"Edges: {', '.join(data['edges'])}")
    click.echo(f"Entry Node: {data['entry_node']}")
    click.echo(f"Terminal Nodes: {', '.join(data['terminal_nodes'])}")
    click.echo(f"Client-facing Nodes: {', '.join(data['client_facing_nodes']) or 'None'}")


@cli.command()
def validate() -> None:
    """Validate agent structure and graph wiring."""
    v = default_agent.validate()

    if v["valid"]:
        click.echo("✓ Agent is valid")
    else:
        click.echo("✗ Validation failed")
        click.echo("\nErrors:")
        for e in v["errors"]:
            click.echo(f"  - {e}")

    if v["warnings"]:
        click.echo("\nWarnings:")
        for w in v["warnings"]:
            click.echo(f"  - {w}")

    sys.exit(0 if v["valid"] else 1)


@cli.command()
@click.option("--type", "-t", "issue_type", type=click.Choice(["security", "bug", "feature"]))
def demo(issue_type: str | None) -> None:
    """Run a demo with sample issues.

    Examples:
        python -m linear_triage_agent demo --type security
        python -m linear_triage_agent demo --type bug
        python -m linear_triage_agent demo --type feature
    """
    setup_logging(verbose=True)

    demo_issues = {
        "security": (
            "CRITICAL: SQL injection vulnerability found in the user search endpoint. "
            "Attackers can bypass authentication by injecting malicious SQL in the "
            "search query parameter. This affects all production environments."
        ),
        "bug": (
            "Login page crashes on Safari when uploading a PDF file larger than 5MB. "
            "The error occurs consistently after selecting the file. Console shows "
            "'TypeError: undefined is not an object' in the upload handler."
        ),
        "feature": (
            "Request: Add dark mode support to the dashboard. Users have been asking "
            "for this feature to reduce eye strain during night-time usage. Should "
            "include automatic switching based on system preferences."
        ),
    }

    if issue_type:
        issues = {issue_type: demo_issues[issue_type]}
    else:
        issues = demo_issues

    for itype, issue in issues.items():
        click.echo(f"\n{'=' * 60}")
        click.echo(f"Demo: {itype.upper()} Issue")
        click.echo(f"{'=' * 60}")
        click.echo(f"Input: {issue[:100]}...")
        click.echo("-" * 60)

        result = asyncio.run(default_agent.run({"raw_issue": issue}))

        if result.success:
            click.echo("✓ Triage completed successfully")
            if result.output:
                click.echo(json.dumps(result.output, indent=2, default=str))
        else:
            click.echo(f"✗ Triage failed: {result.error}")


if __name__ == "__main__":
    cli()
