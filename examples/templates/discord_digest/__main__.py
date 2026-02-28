"""
CLI entry point for Discord Community Digest.

Uses AgentRuntime for multi-entrypoint support with HITL pause/resume.
"""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent, DiscordDigestAgent


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
    """Discord Community Digest - Monitor Discord and get actionable summaries."""
    pass


@cli.command()
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
@click.option("--reconfigure", is_flag=True, help="Force re-run of configure step")
def run(quiet, verbose, debug, reconfigure):
    """Execute the Discord digest agent."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    from pathlib import Path
    from .config import load_user_config, save_user_config
    from .cursor import read_cursors, save_cursors, update_cursors

    storage_path = Path.home() / ".hive" / "discord_digest"
    context = {}

    # Load saved config if available (skip configure node)
    if not reconfigure:
        saved = load_user_config(storage_path)
        if saved:
            config_dict = {
                "servers": saved.servers,
                "channels": saved.channels,
                "lookback_days": saved.lookback_days,
                "keywords": saved.keywords,
                "user_id": saved.user_id,
            }
            # Inject cursors for dedup
            cursors = read_cursors(storage_path)
            if cursors:
                config_dict["cursors"] = cursors
            context["digest_config"] = json.dumps(config_dict)

    result = asyncio.run(default_agent.run(context))

    # Save cursors on success
    if result.success and result.output:
        channel_data = result.output.get("channel_data")
        if channel_data:
            try:
                data = (
                    json.loads(channel_data)
                    if isinstance(channel_data, str)
                    else channel_data
                )
                new_cursors = data.get("new_cursors", {})
                if new_cursors:
                    existing = read_cursors(storage_path)
                    merged = update_cursors(existing, new_cursors)
                    save_cursors(merged, storage_path)
            except (json.JSONDecodeError, TypeError):
                pass

        # Save user config if it came from configure node
        digest_config = result.output.get("digest_config")
        if digest_config:
            try:
                data = (
                    json.loads(digest_config)
                    if isinstance(digest_config, str)
                    else digest_config
                )
                from .config import UserConfig

                save_user_config(
                    UserConfig(
                        servers=data.get("servers", ["all"]),
                        channels=data.get("channels", ["all"]),
                        lookback_days=data.get("lookback_days", 3),
                        keywords=data.get("keywords", []),
                        user_id=data.get("user_id", ""),
                    ),
                    storage_path,
                )
            except (json.JSONDecodeError, TypeError):
                pass

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
    """Launch the TUI dashboard for interactive digest management."""
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
        agent = DiscordDigestAgent()

        agent._event_bus = EventBus()
        agent._tool_registry = ToolRegistry()

        storage_path = Path.home() / ".hive" / "agents" / "discord_digest"
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
                    name="Start Digest",
                    entry_node="configure",
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
    """Interactive Discord digest session (CLI, no TUI)."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    """Async interactive shell."""
    setup_logging(verbose=verbose)

    click.echo("=== Discord Community Digest ===")
    click.echo("Press Enter to generate a digest (or 'quit' to exit):\n")

    agent = DiscordDigestAgent()
    await agent.start()

    try:
        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Digest> "
                )
                if user_input.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break

                click.echo("\nScanning Discord channels...\n")

                result = await agent.trigger_and_wait("start", {})

                if result is None:
                    click.echo("\n[Execution timed out]\n")
                    continue

                if result.success:
                    output = result.output
                    if "digest_report" in output:
                        click.echo("\nDigest delivered!\n")
                else:
                    click.echo(f"\nFailed: {result.error}\n")

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
