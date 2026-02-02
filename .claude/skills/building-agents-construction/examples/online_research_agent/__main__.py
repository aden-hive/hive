"""
CLI entry point for Online Research Agent.

Uses AgentRuntime for multi-entrypoint support with HITL pause/resume.
"""

import asyncio
import json
import logging
import sys
import click

from .agent import default_agent, OnlineResearchAgent


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
    """Online Research Agent - Deep-dive research with narrative reports."""
    pass


@cli.command()
@click.option("--topic", "-t", type=str, required=True, help="Research topic")
@click.option("--mock", is_flag=True, help="Run in mock mode")
@click.option("--quiet", "-q", is_flag=True, help="Only output result JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show execution details")
@click.option("--debug", is_flag=True, help="Show debug logging")
def run(topic, mock, quiet, verbose, debug):
    """Execute research on a topic."""
    if not quiet:
        setup_logging(verbose=verbose, debug=debug)

    context = {"topic": topic}

    result = asyncio.run(default_agent.run(context, mock_mode=mock))

    output_data = {
        "success": result.success,
        "steps_executed": result.steps_executed,
        "output": result.output,
    }
    if result.error:
        output_data["error"] = result.error

    click.echo(json.dumps(output_data, indent=2, default=str))
    sys.exit(0 if result.success else 1)

def draw_tree(current_node, edges, visited=None, depth=0, prefix=""):
    """
    Recursively draws the agent graph as a tree with proper branch styling.
    """
    if visited is None:
        visited = set()
    
    # Handle cycles/loops gracefully
    if current_node in visited:
        click.echo(f"{prefix}└── {click.style(current_node, fg='yellow')} (loop back)")
        return
    visited.add(current_node)

    # Find all children (target nodes) for the current node
    children = [e['target'] for e in edges if e['source'] == current_node]
    
    # Print the current node. If it's the root (depth 0), we don't need a branch symbol
    if depth == 0:
        click.echo(click.style(current_node, fg="green", bold=True))
    
    # Iterate through children and draw branches
    for i, child in enumerate(children):
        is_last = (i == len(children) - 1)
        
        # Branch symbol: T-shape for middle, L-shape for last
        connector = "└── " if is_last else "├── "
        
        # Display the child node
        click.echo(f"{prefix}{connector}{child}")
    
        new_prefix = prefix + ("    " if is_last else "│   ")
        
        draw_tree(child, edges, visited, depth + 1, new_prefix)

@cli.command()
@click.option("--json", "output_json", is_flag=True)
def info(output_json):
    """Show agent information with a hierarchical flow visualization."""
    info_data = default_agent.info()
    
    if output_json:
        click.echo(json.dumps(info_data, indent=2))
        return

    click.echo(click.style(f"Agent: {info_data['name']}", fg="cyan", bold=True))
    click.echo(f"Version: {info_data['version']}")
    click.echo(f"Description: {info_data['description']}")
    
    click.echo(click.style("\n[Nodes]", fg="yellow"))
    for node in info_data['nodes']:
        roles = []
        if node == info_data['entry_node']: roles.append("ENTRY")
        if node in info_data['terminal_nodes']: roles.append("TERMINAL")
        
        role_str = f" ({', '.join(roles)})" if roles else ""
        click.echo(f"  • {node}{click.style(role_str, dim=True)}")

    # Hierarchy tree
    click.echo(click.style("\n[Agent Flow Tree]", fg="yellow"))
    if info_data['edges']:
        draw_tree(info_data['entry_node'], info_data['edges'])
    else:
        click.echo("  No edges defined.")


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
    """Interactive research session."""
    asyncio.run(_interactive_shell(verbose))


async def _interactive_shell(verbose=False):
    """Async interactive shell."""
    setup_logging(verbose=verbose)

    click.echo("=== Online Research Agent ===")
    click.echo("Enter a topic to research (or 'quit' to exit):\n")

    agent = OnlineResearchAgent()
    await agent.start()

    try:
        while True:
            try:
                topic = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Topic> "
                )
                if topic.lower() in ["quit", "exit", "q"]:
                    click.echo("Goodbye!")
                    break

                if not topic.strip():
                    continue

                click.echo("\nResearching... (this may take a few minutes)\n")

                result = await agent.trigger_and_wait("start", {"topic": topic})

                if result is None:
                    click.echo("\n[Execution timed out]\n")
                    continue

                if result.success:
                    output = result.output
                    if "file_path" in output:
                        click.echo(f"\nReport saved to: {output['file_path']}\n")
                    if "final_report" in output:
                        click.echo("\n--- Report Preview ---\n")
                        preview = (
                            output["final_report"][:500] + "..."
                            if len(output.get("final_report", "")) > 500
                            else output.get("final_report", "")
                        )
                        click.echo(preview)
                        click.echo("\n")
                else:
                    click.echo(f"\nResearch failed: {result.error}\n")

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
