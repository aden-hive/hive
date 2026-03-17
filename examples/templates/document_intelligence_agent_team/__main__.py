"""
CLI entry point for Document Intelligence Agent Team.

Coordinates three specialist Worker Bee agents (Researcher, Analyst, Strategist)
via a Queen Bee coordinator to produce a cross-referenced document intelligence report.
"""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent, DocumentIntelligenceAgentTeam


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
    """Document Intelligence Agent Team - Multi-perspective A2A document analysis."""
    pass


@cli.command()
@click.option("--document", "-d", type=str, required=True, help="Document text to analyze")
@click.option("--brief", "-b", type=str, default="Comprehensive analysis", help="Analysis focus (optional)")
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(document, brief, quiet, verbose, debug):
    """Run multi-perspective analysis on a document."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    context = {
        "document_text": document,
        "analysis_brief": brief,
    }

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
    """Launch the TUI dashboard for interactive document analysis."""
    setup_logging(verbose=verbose, debug=debug)

    try:
        from framework.tui.app import AdenTUI
    except ImportError:
        click.echo(
            "TUI requires the 'textual' package. Install with: pip install textual"
        )
        sys.exit(1)

    from pathlib import Path

    from framework.llm import LiteLLMProvider
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.agent_runtime import create_agent_runtime
    from framework.runtime.event_bus import EventBus
    from framework.runtime.execution_stream import EntryPointSpec

    async def run_with_tui():
        agent = DocumentIntelligenceAgentTeam()

        agent._event_bus = EventBus()
        agent._tool_registry = ToolRegistry()

        storage_path = Path.home() / ".hive" / "agents" / "document_intelligence_agent_team"
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
                    name="Start Analysis",
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
    """Interactive document analysis session (CLI, no TUI)."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    """Async interactive shell."""
    setup_logging(verbose=verbose)

    click.echo("=== Document Intelligence Agent Team ===")
    click.echo("Paste your document, then press Enter twice to submit.")
    click.echo("Type 'quit' to exit.\n")

    agent = DocumentIntelligenceAgentTeam()
    await agent.start()

    try:
        while True:
            lines = []
            try:
                while True:
                    line = await asyncio.get_event_loop().run_in_executor(None, input, "")
                    if line.lower() in ["quit", "exit", "q"]:
                        click.echo("Goodbye!")
                        return
                    if line == "" and lines:
                        break
                    lines.append(line)
            except (KeyboardInterrupt, EOFError):
                click.echo("\nGoodbye!")
                break

            document = "\n".join(lines).strip()
            if not document:
                continue

            click.echo("\nAnalyzing...\n")
            result = await agent.trigger_and_wait("start", {"document_text": document})

            if result is None:
                click.echo("\n[Execution timed out]\n")
            elif result.success:
                click.echo("\nAnalysis complete.\n")
            else:
                click.echo(f"\nAnalysis failed: {result.error}\n")

    finally:
        await agent.stop()


if __name__ == "__main__":
    cli()
